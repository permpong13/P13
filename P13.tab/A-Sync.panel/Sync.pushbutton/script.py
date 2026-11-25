# -*- coding: utf-8 -*-
# pylint: disable=import-error,invalid-name,broad-except,too-many-lines
"""P13.extension Cloud Sync & Updater (Pro Edition)."""
from __future__ import print_function

import os
import io
import sys
import json
import time
import stat
import shutil
import filecmp
import zipfile
import subprocess
import traceback

try:
    import urllib2
except ImportError:
    from urllib import request as urllib2
    from urllib import error as urllib_error
else:
    urllib_error = urllib2

import clr
clr.AddReference("System")
clr.AddReference("System.Xml")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

import System
from System import Uri
from System.Net import ServicePointManager
from System.Net import SecurityProtocolType
from System.Threading import ThreadPool
from System.Threading import WaitCallback
from System.Windows import Application
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapImage
from System.Windows.Media.Imaging import BitmapCacheOption
from System.Windows.Threading import DispatcherPriority

from pyrevit.coreutils import ribbon
from pyrevit.loader import sessionmgr
from pyrevit import forms
from pyrevit import EXEC_PARAMS

try:
    from pyrevit import HOST_APP
except Exception:
    HOST_APP = None

# Ensure TLS 1.2 is enabled for GitHub HTTPS API calls
try:
    ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12
except Exception:
    pass


# ------------------------------------------------------------------------------
# CONSTANTS & CONFIGURATION
# ------------------------------------------------------------------------------
USER_REPO = "Permpong13/P13"
BRANCH_NAME = "main"
API_BASE = "https://api.github.com/repos/{}".format(USER_REPO)
GITHUB_COMMIT_API_URL = "{}/commits/{}".format(API_BASE, BRANCH_NAME)
GITHUB_COMMITS_LIST_URL = "{}/commits?sha={}&per_page=8".format(API_BASE, BRANCH_NAME)
GITHUB_COMPARE_URL_TPL = API_BASE + "/compare/{}...{}"
GITHUB_ZIP_SHA_URL_TPL = API_BASE + "/zipball/{}"
GITHUB_ZIP_MAIN_URL = "{}/zipball/{}".format(API_BASE, BRANCH_NAME)

VERSION_MARKER_FILE = ".p13_sync_version"
REMOTE_CACHE_FILE = "P13_sync_remote_status.json"
SYNC_LOG_FILE = "P13_sync_error.log"

BG_CHECK_INTERVAL_SECONDS = 600
DOWNLOAD_CHUNK_SIZE = 65536
FAST_FILE_RETRIES = 2
FAST_FILE_RETRY_WAIT = 0.15
LOCKED_SUFFIX_MARKER = ".old_locked_"

HTTP_USER_AGENT = "P13-pyRevit-Sync-Pro/2.0 (+https://github.com/{})".format(USER_REPO)

STATUS_LATEST = "latest"
STATUS_OUTDATED = "outdated"
STATUS_UNKNOWN = "unknown"
STATUS_ICONS = {
    STATUS_LATEST: "icon.latest.png",
    STATUS_OUTDATED: "icon.outdated.png",
    STATUS_UNKNOWN: "icon.unknown.png",
}

PY2 = sys.version_info[0] < 3
TEXT_TYPE = unicode if PY2 else str  # noqa: F821

# Legacy paths preserved for smooth transition before Manifest takes over
OBSOLETE_RELATIVE_PATHS = [
    os.path.join("P13.tab", "Import_Export.panel", "SheetTools.stack", "CopySheets.pushbutton"),
    os.path.join("P13.tab", "Import_Export.panel", "SheetTools.stack", "Sheet_from_Excel.pushbutton"),
    os.path.join("P13.tab", "Import_Export.panel", "SheetTools.stack"),
]

PRIVATE_SETTING_MIGRATIONS = [
    (
        os.path.join("P13.tab", "Manager.panel", "SuperSheet.pushbutton", "p13_supersheet_config.json"),
        os.path.join("SuperSheet", "profiles.json"),
    ),
    (
        os.path.join("P13.tab", "Manager.panel", "SuperSheet.pushbutton", "p13_last_settings.json"),
        os.path.join("SuperSheet", "last_settings.json"),
    ),
    (
        os.path.join("P13.tab", "Manager.panel", "SuperSheet.pushbutton", "Google_profiles_backup.json"),
        os.path.join("SuperSheet", "Legacy", "Google_profiles_backup.json"),
    ),
    (
        os.path.join("P13.tab", "Manager.panel", "SuperSheet.pushbutton", "OHM2.json"),
        os.path.join("SuperSheet", "Legacy", "OHM2.json"),
    ),
    (
        os.path.join("P13.tab", "Manager.panel", "SuperSheet.pushbutton", "OHM COCO.xml"),
        os.path.join("SuperSheet", "Legacy", "OHM COCO.xml"),
    ),
    (
        os.path.join("P13.tab", "Manager.panel", "SuperSheet.pushbutton", "profiles.json"),
        os.path.join("SuperSheet", "Legacy", "profiles.json"),
    ),
]


# ------------------------------------------------------------------------------
# TEXT, PATH & LOGGING HELPERS
# ------------------------------------------------------------------------------
def to_text(val):
    if val is None:
        return u""
    if isinstance(val, TEXT_TYPE):
        return val
    try:
        return val.decode("utf-8")
    except Exception:
        return TEXT_TYPE(val)


def win_long_path(path):
    """Add Windows extended-length prefix to prevent MAX_PATH (260 char) errors."""
    abs_p = os.path.abspath(to_text(path))
    if os.name == "nt" and not abs_p.startswith(u"\\\\?\\"):
        if abs_p.startswith(u"\\\\"):
            return u"\\\\?\\UNC\\" + abs_p[2:]
        return u"\\\\?\\" + abs_p
    return abs_p


def strip_long_path(path):
    txt = to_text(path)
    if txt.startswith(u"\\\\?\\UNC\\"):
        return u"\\\\" + txt[8:]
    if txt.startswith(u"\\\\?\\"):
        return txt[4:]
    return txt


def find_extension_root(start_path):
    current_path = os.path.abspath(to_text(start_path))
    while not os.path.basename(current_path).lower().startswith(u"p13.extension"):
        parent_path = os.path.dirname(current_path)
        if parent_path == current_path:
            break
        current_path = parent_path
    return current_path


def get_extension_root():
    current_path = os.path.dirname(os.path.abspath(__file__))
    return find_extension_root(current_path)


def is_admin_user():
    """Detect developer git clone so sync never overwrites local dev work."""
    return os.path.isdir(os.path.join(get_extension_root(), ".git"))


def get_temp_path(file_name):
    temp_dir = to_text(os.environ.get("TEMP") or os.environ.get("TMP") or get_extension_root())
    return os.path.join(temp_dir, to_text(file_name))


def write_json_utf8(file_path, payload):
    raw = json.dumps(payload, indent=2, ensure_ascii=False)
    if PY2 and isinstance(raw, str):
        raw = raw.decode("utf-8")
    tmp_p = to_text(file_path) + u".tmp_{}".format(os.getpid())
    with io.open(win_long_path(tmp_p), "w", encoding="utf-8") as f:
        f.write(raw)
    if os.path.exists(win_long_path(file_path)):
        os.remove(win_long_path(file_path))
    os.rename(win_long_path(tmp_p), win_long_path(file_path))


def read_json_utf8(file_path):
    with io.open(win_long_path(file_path), "r", encoding="utf-8") as f:
        return json.load(f)


def write_sync_log(message):
    log_path = get_temp_path(SYNC_LOG_FILE)
    try:
        entry = u"\n[{}]\n{}\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), to_text(message))
        with io.open(win_long_path(log_path), "a", encoding="utf-8") as log_file:
            log_file.write(entry)
    except Exception:
        pass
    return log_path


def report_sync_error(message, exception):
    details = u"{}\n{}\n{}".format(to_text(message), to_text(exception), to_text(traceback.format_exc()))
    log_path = write_sync_log(details)
    exc_txt = to_text(exception).strip()
    if len(exc_txt) > 260:
        exc_txt = exc_txt[:257] + u"..."
    try:
        forms.alert(
            u"{}\n\nReason: {}\n\nDiagnostic log:\n{}".format(
                to_text(message),
                exc_txt or u"Unknown error",
                log_path
            ),
            title="P13 Sync (Pro)",
            warn_icon=True
        )
    except Exception:
        print(u"{} | Log: {}".format(to_text(message), log_path))


# ------------------------------------------------------------------------------
# VERSION MARKER & MANIFEST MANAGEMENT
# ------------------------------------------------------------------------------
def get_version_marker_path(extension_root):
    return os.path.join(extension_root, VERSION_MARKER_FILE)


def read_local_marker_data(extension_root):
    marker_path = get_version_marker_path(extension_root)
    if not os.path.isfile(win_long_path(marker_path)):
        return {}
    try:
        data = read_json_utf8(marker_path)
        if isinstance(data, dict):
            return data
    except Exception:
        try:
            with io.open(win_long_path(marker_path), "r", encoding="utf-8") as f:
                txt = f.read().strip()
            if txt:
                return {"sha": txt, "managed_files": []}
        except Exception:
            pass
    return {}


def get_local_git_sha(extension_root):
    git_path = os.path.join(extension_root, ".git")
    if not os.path.exists(git_path):
        return u""
    try:
        proc = subprocess.Popen(
            ["git", "-C", extension_root, "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout_data, _ = proc.communicate()
        if proc.returncode == 0 and stdout_data:
            try:
                stdout_data = stdout_data.decode("ascii")
            except AttributeError:
                pass
            return to_text(stdout_data).strip()
    except Exception:
        pass
    return u""


def get_local_sha(extension_root):
    data = read_local_marker_data(extension_root)
    sha = to_text(data.get("sha", "")).strip()
    if sha:
        return sha
    return get_local_git_sha(extension_root)


def write_marker_data(extension_root, remote_sha, managed_rel_files):
    if not remote_sha:
        return
    payload = {
        "repo": USER_REPO,
        "branch": BRANCH_NAME,
        "sha": to_text(remote_sha),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "managed_files": sorted(list(set(managed_rel_files)))
    }
    try:
        write_json_utf8(get_version_marker_path(extension_root), payload)
    except Exception:
        pass


# ------------------------------------------------------------------------------
# GITHUB API WITH ETAG CACHING & CHANGELOG FETCHING
# ------------------------------------------------------------------------------
def _extract_header(response, header_name):
    try:
        info = response.info()
        if hasattr(info, "getheader"):
            val = info.getheader(header_name)
            if val:
                return to_text(val).strip()
        if hasattr(response, "headers") and response.headers:
            val = response.headers.get(header_name)
            if val:
                return to_text(val).strip()
    except Exception:
        pass
    return u""


def read_remote_cache():
    cache_path = get_temp_path(REMOTE_CACHE_FILE)
    if not os.path.isfile(win_long_path(cache_path)):
        return {}
    try:
        data = read_json_utf8(cache_path)
        if isinstance(data, dict) and data.get("repo") == USER_REPO:
            return data
    except Exception:
        pass
    return {}


def fetch_remote_commit_info(allow_network=True, force_network=False, timeout=6):
    """Return dict {'sha', 'date', 'message', 'etag', 'checked_at'} using ETag."""
    cache_path = get_temp_path(REMOTE_CACHE_FILE)
    cached = read_remote_cache()

    if not allow_network:
        # Offline mode (__selfinit__): NEVER discard last known SHA regardless of age!
        return cached

    if not force_network and cached.get("sha"):
        age = time.time() - float(cached.get("checked_at", 0))
        if age <= BG_CHECK_INTERVAL_SECONDS:
            return cached

    req = urllib2.Request(GITHUB_COMMIT_API_URL)
    req.add_header("User-Agent", HTTP_USER_AGENT)
    req.add_header("Accept", "application/vnd.github+json")
    if cached.get("etag"):
        req.add_header("If-None-Match", str(cached["etag"]))

    resp = None
    try:
        resp = urllib2.urlopen(req, timeout=timeout)
        raw_bytes = resp.read()
        data = json.loads(raw_bytes.decode("utf-8"))
        sha = to_text(data.get("sha") or "").strip()
        commit_obj = data.get("commit") or {}
        author_obj = commit_obj.get("committer") or commit_obj.get("author") or {}
        c_date = to_text(author_obj.get("date") or "").replace("T", " ").replace("Z", "")
        c_msg = to_text(commit_obj.get("message") or "").splitlines()[0] if commit_obj.get("message") else u""
        etag = _extract_header(resp, "ETag")

        if sha:
            updated_cache = {
                "repo": USER_REPO,
                "sha": sha,
                "date": c_date,
                "message": c_msg,
                "etag": etag or cached.get("etag", ""),
                "checked_at": time.time()
            }
            try:
                write_json_utf8(cache_path, updated_cache)
            except Exception:
                pass
            return updated_cache
    except urllib_error.HTTPError as http_err:
        # 304 Not Modified: GitHub confirms zero changes and deducts 0 API quota!
        if getattr(http_err, "code", 0) == 304 and cached.get("sha"):
            cached["checked_at"] = time.time()
            try:
                write_json_utf8(cache_path, cached)
            except Exception:
                pass
            return cached
        write_sync_log(u"GitHub HTTP Warning: {}".format(http_err))
    except Exception as ex:
        write_sync_log(u"GitHub Check Warning: {}".format(ex))
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    return cached


def fetch_changelog_commits(local_sha, remote_sha, timeout=6):
    """Fetch human-readable commit messages between local_sha and remote_sha."""
    if local_sha and remote_sha and local_sha.lower() != remote_sha.lower():
        url = GITHUB_COMPARE_URL_TPL.format(local_sha[:12], remote_sha[:12])
        is_compare = True
    else:
        url = GITHUB_COMMITS_LIST_URL
        is_compare = False

    req = urllib2.Request(url)
    req.add_header("User-Agent", HTTP_USER_AGENT)
    req.add_header("Accept", "application/vnd.github+json")
    resp = None
    items = []
    try:
        resp = urllib2.urlopen(req, timeout=timeout)
        data = json.loads(resp.read().decode("utf-8"))
        commits_raw = data.get("commits", []) if is_compare else (data if isinstance(data, list) else [])
        if is_compare:
            commits_raw = list(reversed(commits_raw))

        for c in commits_raw[:12]:
            c_sha = to_text(c.get("sha") or "")[:7]
            c_info = c.get("commit") or {}
            msg_full = to_text(c_info.get("message") or "").strip()
            first_line = msg_full.splitlines()[0] if msg_full else u"Update"
            au_info = c_info.get("author") or {}
            c_date = to_text(au_info.get("date") or "")[:10]
            items.append(u"[{}] {} ({})".format(c_sha, first_line, c_date))
    except Exception:
        pass
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass
    return items


def compute_sync_status(extension_root, allow_network=True, force_network=False):
    remote_info = fetch_remote_commit_info(allow_network=allow_network, force_network=force_network)
    remote_sha = to_text(remote_info.get("sha") or "").strip()
    local_sha = get_local_sha(extension_root)

    if not remote_sha:
        return STATUS_UNKNOWN, local_sha, remote_sha, remote_info
    if not local_sha:
        return STATUS_OUTDATED, local_sha, remote_sha, remote_info
    if local_sha.lower() == remote_sha.lower():
        return STATUS_LATEST, local_sha, remote_sha, remote_info
    return STATUS_OUTDATED, local_sha, remote_sha, remote_info


# ------------------------------------------------------------------------------
# NON-LOCKING RIBBON ICON & BACKGROUND UPDATER (__selfinit__)
# ------------------------------------------------------------------------------
def load_unlocked_bitmap(icon_path):
    """Load PNG completely into memory (OnLoad + Freeze) so Windows never locks the file."""
    if not icon_path or not os.path.isfile(win_long_path(icon_path)):
        return None
    try:
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.CreateOptions = System.Windows.Media.Imaging.BitmapCreateOptions.IgnoreImageCache
        bmp.UriSource = Uri(strip_long_path(os.path.abspath(icon_path)))
        bmp.EndInit()
        bmp.Freeze()
        return bmp
    except Exception:
        return None


def get_ribbon_targets(ui_button_cmp):
    targets = [ui_button_cmp]
    for attr_name in ["ui_item", "control", "button", "rvtapi_object"]:
        try:
            target = getattr(ui_button_cmp, attr_name, None)
            if target:
                targets.append(target)
        except Exception:
            pass
    return targets


def hide_ribbon_button(ui_button_cmp):
    for target in get_ribbon_targets(ui_button_cmp):
        for attr_name in ["Visible", "visible", "Enabled", "enabled"]:
            try:
                if hasattr(target, attr_name):
                    setattr(target, attr_name, False)
            except Exception:
                pass


def apply_ribbon_visuals(script_cmp, ui_button_cmp, status, local_sha, remote_sha):
    """Set unlocked BitmapImage & status tooltip safely on the Revit UI thread."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    icon_name = STATUS_ICONS.get(status, STATUS_ICONS[STATUS_UNKNOWN])
    try:
        icon_path = script_cmp.get_bundle_file(icon_name) if script_cmp else None
    except Exception:
        icon_path = None
    if not icon_path:
        icon_path = os.path.join(current_dir, icon_name)

    # 1. Prefer memory-cached BitmapImage first so icon PNGs are NEVER locked on disk!
    bitmap = load_unlocked_bitmap(icon_path)
    icon_applied = False
    if bitmap is not None:
        for target in get_ribbon_targets(ui_button_cmp):
            for attr_name in ["LargeImage", "Image"]:
                try:
                    if hasattr(target, attr_name):
                        setattr(target, attr_name, bitmap)
                        icon_applied = True
                except Exception:
                    pass

    if not icon_applied and os.path.isfile(win_long_path(icon_path)):
        for target in [ui_button_cmp, script_cmp]:
            if target is None:
                continue
            for method_name in ["set_icon", "set_icon_file", "set_icon_path"]:
                method = getattr(target, method_name, None)
                if method:
                    try:
                        method(icon_path, icon_size=ribbon.ICON_LARGE)
                    except TypeError:
                        method(icon_path)
                    except Exception:
                        pass
                    break

    # 2. Update Tooltip
    if status == STATUS_LATEST:
        headline = u"[Up to Date] P13.extension matches GitHub main."
    elif status == STATUS_OUTDATED:
        headline = u"[Update Available] Click to review & install latest P13 tools."
    else:
        headline = u"[Status Unchecked] Click to check GitHub for P13 updates."

    loc_lbl = local_sha[:10] if local_sha else u"not recorded"
    rem_lbl = remote_sha[:10] if remote_sha else u"checking..."
    tip_text = u"{}\nInstalled: {}\nLatest GitHub: {}\n\nShift+Click: Maintenance & Force Sync".format(
        headline, loc_lbl, rem_lbl
    )

    for target in get_ribbon_targets(ui_button_cmp):
        for attr_name in ["ToolTip", "tooltip"]:
            try:
                if hasattr(target, attr_name):
                    setattr(target, attr_name, tip_text)
            except Exception:
                pass


def _start_background_ribbon_check(extension_root, script_cmp, ui_button_cmp):
    """Check GitHub asynchronously in background so Revit startup takes 0ms."""
    try:
        app = Application.Current
        dispatcher = app.Dispatcher if app else None
    except Exception:
        dispatcher = None

    if dispatcher is None:
        return

    def _bg_worker(_state):
        try:
            status, l_sha, r_sha, _ = compute_sync_status(
                extension_root, allow_network=True, force_network=False
            )

            def _ui_callback():
                try:
                    apply_ribbon_visuals(script_cmp, ui_button_cmp, status, l_sha, r_sha)
                except Exception:
                    pass

            dispatcher.BeginInvoke(DispatcherPriority.Background, System.Action(_ui_callback))
        except Exception:
            pass

    try:
        ThreadPool.QueueUserWorkItem(WaitCallback(_bg_worker))
    except Exception:
        pass


def __selfinit__(script_cmp, ui_button_cmp, __rvt__):
    if is_admin_user():
        hide_ribbon_button(ui_button_cmp)
        return False

    ext_root = get_extension_root()
    # 1. Instant offline status from persistent cache (0ms latency)
    status, local_sha, remote_sha, cache_info = compute_sync_status(ext_root, allow_network=False)
    apply_ribbon_visuals(script_cmp, ui_button_cmp, status, local_sha, remote_sha)

    # 2. If cache is missing or older than 10 minutes, refresh quietly in background
    age = time.time() - float(cache_info.get("checked_at", 0)) if cache_info else 999999
    if age > BG_CHECK_INTERVAL_SECONDS:
        _start_background_ribbon_check(ext_root, script_cmp, ui_button_cmp)
    return True


# ------------------------------------------------------------------------------
# REVIT-NATIVE WPF CHANGELOG & UPDATE CONFIRMATION DIALOG
# ------------------------------------------------------------------------------
UPDATE_DIALOG_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="P13.extension - Software Update"
        Width="560" Height="420" MinWidth="480" MinHeight="340"
        WindowStartupLocation="CenterScreen"
        Background="#F0F0F0" FontFamily="Segoe UI" FontSize="12"
        UseLayoutRounding="True" SnapsToDevicePixels="True">
    <Grid>
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <Border Grid.Row="0" Background="#FFFFFF" BorderBrush="#D9D9D9" BorderThickness="0,0,0,1" Padding="16,12">
            <StackPanel>
                <StackPanel Orientation="Horizontal">
                    <Border Name="bdr_badge" Width="6" Height="18" Background="#0078D4" CornerRadius="1" Margin="0,0,10,0"/>
                    <TextBlock Name="lbl_headline" Text="New P13.extension Update Available" FontSize="14" FontWeight="Bold" Foreground="#1E1E1E"/>
                </StackPanel>
                <TextBlock Name="lbl_versions" Text="Installed: -   ->   Latest GitHub: -" Foreground="#555555" Margin="16,4,0,0"/>
            </StackPanel>
        </Border>

        <Grid Grid.Row="1" Margin="14,10,14,10">
            <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="*"/>
            </Grid.RowDefinitions>
            <TextBlock Text="Recent Changes on GitHub (Commits):" FontWeight="SemiBold" Foreground="#222222" Margin="0,0,0,6"/>
            <TextBox Name="txt_changelog" Grid.Row="1" IsReadOnly="True" TextWrapping="Wrap"
                     VerticalScrollBarVisibility="Auto" Background="#FFFFFF" BorderBrush="#ABADB3"
                     FontFamily="Consolas, Segoe UI" FontSize="11.5" Padding="8"/>
        </Grid>

        <Border Grid.Row="2" Background="#F0F0F0" BorderBrush="#D6D6D6" BorderThickness="0,1,0,0" Padding="14,10">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <TextBlock Text="pyRevit will reload automatically after updating." Foreground="#666666" FontSize="11" VerticalAlignment="Center"/>
                <StackPanel Grid.Column="1" Orientation="Horizontal">
                    <Button Name="btn_install" Content="Update &amp; Reload" Width="130" Height="26"
                            Background="#006CBE" Foreground="#FFFFFF" BorderBrush="#005499" FontWeight="SemiBold" Margin="0,0,8,0" IsDefault="True"/>
                    <Button Name="btn_cancel" Content="Cancel" Width="80" Height="26"
                            Background="#FBFBFB" BorderBrush="#ABADB3" IsCancel="True"/>
                </StackPanel>
            </Grid>
        </Border>
    </Grid>
</Window>
"""


def show_update_confirmation_dialog(local_sha, remote_sha, remote_info, commits_list, is_force=False):
    """Display Revit-style WPF dialog with commit changelog; return True to proceed."""
    try:
        win = XamlReader.Parse(UPDATE_DIALOG_XAML)
        try:
            hwnd = HOST_APP.uiapp.MainWindowHandle if HOST_APP else System.IntPtr.Zero
            if hwnd != System.IntPtr.Zero:
                WindowInteropHelper(win).Owner = hwnd
        except Exception:
            pass

        lbl_headline = win.FindName("lbl_headline")
        lbl_versions = win.FindName("lbl_versions")
        txt_changelog = win.FindName("txt_changelog")
        btn_install = win.FindName("btn_install")
        btn_cancel = win.FindName("btn_cancel")

        loc_short = local_sha[:10] if local_sha else u"None"
        rem_short = remote_sha[:10] if remote_sha else u"Latest"
        rem_date = to_text(remote_info.get("date") or "")

        if is_force:
            lbl_headline.Text = u"Force Re-Sync & Repair P13.extension"
            btn_install.Content = u"Force Re-Sync"
        lbl_versions.Text = u"Installed: {}    ->    GitHub Latest: {}  ({})".format(
            loc_short, rem_short, rem_date or u"main"
        )

        if commits_list:
            txt_changelog.Text = u"\n".join(u"• " + item for item in commits_list)
        elif remote_info.get("message"):
            txt_changelog.Text = u"• [{}] {}".format(rem_short[:7], to_text(remote_info.get("message")))
        else:
            txt_changelog.Text = u"• Ready to synchronize package files from GitHub ({}).".format(USER_REPO)

        decision = {"proceed": False}

        def _on_ok(_s, _a):
            decision["proceed"] = True
            win.Close()

        def _on_cancel(_s, _a):
            decision["proceed"] = False
            win.Close()

        btn_install.Click += _on_ok
        btn_cancel.Click += _on_cancel
        win.ShowDialog()
        return decision["proceed"]
    except Exception:
        return bool(forms.alert(
            u"New P13.extension update available!\n\nInstalled: {}\nLatest: {}\n\nInstall update and reload pyRevit now?".format(
                local_sha[:10] if local_sha else u"None",
                remote_sha[:10] if remote_sha else u"Latest"
            ),
            title="P13 Sync (Pro)",
            yes=True,
            no=True
        ))


# ------------------------------------------------------------------------------
# ZERO-FREEZE FILE ENGINE (RENAME-ASIDE, ZIP-SLIP GUARD & MANIFEST CLEANUP)
# ------------------------------------------------------------------------------
def purge_old_locked_trash(extension_root):
    """Sweep leftover *.old_locked_* files from previous Revit sessions."""
    for root_dir, _, file_names in os.walk(win_long_path(extension_root)):
        for fname in file_names:
            if LOCKED_SUFFIX_MARKER in fname:
                fpath = os.path.join(root_dir, fname)
                try:
                    os.chmod(fpath, stat.S_IWRITE)
                    os.remove(fpath)
                except Exception:
                    pass


def remove_tree_fast(target_path):
    lp = win_long_path(target_path)
    if not os.path.exists(lp):
        return

    def _on_rm_err(func, p, _exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    if os.path.isdir(lp):
        shutil.rmtree(lp, onerror=_on_rm_err)
    else:
        try:
            os.chmod(lp, stat.S_IWRITE)
            os.remove(lp)
        except Exception:
            pass


def extract_zip_safely(zip_path, extract_dir):
    """Validate archive integrity, block Zip-Slip traversal, and extract with long-path safety."""
    base_lp = win_long_path(extract_dir)
    if not os.path.isdir(base_lp):
        os.makedirs(base_lp)

    with zipfile.ZipFile(win_long_path(zip_path), "r") as zf:
        bad_member = zf.testzip()
        if bad_member:
            raise RuntimeError("Corrupted file inside downloaded ZIP: {}".format(bad_member))

        members = zf.infolist()
        for member in members:
            rel_name = to_text(member.filename).replace("/", os.sep).lstrip(os.sep)
            if not rel_name or ".." in rel_name.split(os.sep):
                continue
            target_lp = win_long_path(os.path.join(strip_long_path(base_lp), rel_name))
            if member.filename.endswith("/"):
                if not os.path.isdir(target_lp):
                    os.makedirs(target_lp)
                continue
            parent_lp = os.path.dirname(target_lp)
            if not os.path.isdir(parent_lp):
                os.makedirs(parent_lp)
            with zf.open(member, "r") as src_f, io.open(target_lp, "wb") as dst_f:
                shutil.copyfileobj(src_f, dst_f)


def get_extracted_extension_root(temp_dir):
    temp_lp = win_long_path(temp_dir)
    subdirs = [
        strip_long_path(os.path.join(temp_lp, name))
        for name in os.listdir(temp_lp)
        if os.path.isdir(os.path.join(temp_lp, name))
    ]
    if len(subdirs) != 1:
        raise RuntimeError("Downloaded archive has an unexpected root structure.")

    extracted_root = subdirs[0]
    for req_item in ["extension.json", "P13.tab"]:
        if not os.path.exists(win_long_path(os.path.join(extracted_root, req_item))):
            raise RuntimeError("Downloaded package is missing '{}'.".format(req_item))
    return extracted_root


def migrate_private_settings(extension_root):
    appdata_path = to_text(os.environ.get("APPDATA") or os.path.expanduser("~"))
    private_root = os.path.join(appdata_path, u"pyRevit", u"P13")
    for rel_src, rel_dst in PRIVATE_SETTING_MIGRATIONS:
        src_lp = win_long_path(os.path.join(extension_root, rel_src))
        dst_lp = win_long_path(os.path.join(private_root, rel_dst))
        if not os.path.isfile(src_lp) or os.path.isfile(dst_lp):
            continue
        dst_dir = os.path.dirname(dst_lp)
        if not os.path.isdir(dst_dir):
            os.makedirs(dst_dir)
        try:
            shutil.copy2(src_lp, dst_lp)
        except Exception:
            pass


def replace_single_file_pro(source_path, target_path, force_overwrite, skipped_files):
    """Copy changed file fast; if locked by Revit, Rename-Aside (.old_locked_) and write new file!"""
    src_lp = win_long_path(source_path)
    dst_lp = win_long_path(target_path)

    if not force_overwrite and os.path.isfile(dst_lp):
        try:
            if filecmp.cmp(src_lp, dst_lp, shallow=False):
                return "unchanged"
        except Exception:
            pass

    parent_lp = os.path.dirname(dst_lp)
    if not os.path.isdir(parent_lp):
        try:
            os.makedirs(parent_lp)
        except Exception as exc:
            skipped_files.append((strip_long_path(dst_lp), to_text(exc)))
            return "skipped"

    last_err = None
    for attempt in range(FAST_FILE_RETRIES):
        try:
            if os.path.isfile(dst_lp):
                os.chmod(dst_lp, stat.S_IWRITE)
            shutil.copy2(src_lp, dst_lp)
            return "updated"
        except Exception as exc:
            last_err = exc
            if attempt < FAST_FILE_RETRIES - 1:
                time.sleep(FAST_FILE_RETRY_WAIT)

    # Rename-Aside fallback for locked DLLs / images on Windows NTFS
    trash_lp = u"{}{}{}_{}".format(dst_lp, LOCKED_SUFFIX_MARKER, os.getpid(), int(time.time()))
    try:
        os.rename(dst_lp, trash_lp)
        shutil.copy2(src_lp, dst_lp)
        return "renamed_aside"
    except Exception:
        skipped_files.append((strip_long_path(dst_lp), to_text(last_err or "Locked by process")))
        return "skipped"


def sync_directory_with_manifest(extracted_root, dest_root, force_overwrite=False, pb=None):
    """Sync all files with progress bar and return stats + new relative file manifest."""
    all_file_pairs = []
    src_base = os.path.abspath(to_text(extracted_root))
    dst_base = os.path.abspath(to_text(dest_root))

    for root_dir, _, file_names in os.walk(win_long_path(src_base)):
        clean_root = strip_long_path(root_dir)
        rel_dir = os.path.relpath(clean_root, src_base)
        for fname in file_names:
            if fname == VERSION_MARKER_FILE or LOCKED_SUFFIX_MARKER in fname:
                continue
            rel_file = fname if rel_dir == "." else os.path.join(rel_dir, fname)
            all_file_pairs.append((
                os.path.join(src_base, rel_file),
                os.path.join(dst_base, rel_file),
                rel_file.replace("\\", "/")
            ))

    stats = {"updated": 0, "unchanged": 0, "renamed_aside": 0}
    skipped_files = []
    new_manifest = []
    total = max(1, len(all_file_pairs))

    for idx, (s_path, d_path, rel_norm) in enumerate(all_file_pairs, 1):
        new_manifest.append(rel_norm)
        res = replace_single_file_pro(s_path, d_path, force_overwrite, skipped_files)
        if res in stats:
            stats[res] += 1
        if pb is not None and (idx % 5 == 0 or idx == total):
            pb.update_progress(50 + int((idx * 45.0) / total), 100)

    return stats, skipped_files, new_manifest


def cleanup_obsolete_and_manifest_diff(extension_root, old_manifest, new_manifest):
    """Remove legacy hardcoded paths AND any tracked GitHub files deleted in the new release."""
    ext_abs = os.path.abspath(to_text(extension_root))

    # 1. Legacy explicit obsolete paths
    for rel_obs in OBSOLETE_RELATIVE_PATHS:
        obs_abs = os.path.abspath(os.path.join(ext_abs, to_text(rel_obs)))
        if obs_abs.lower().startswith(ext_abs.lower()) and obs_abs != ext_abs:
            try:
                remove_tree_fast(obs_abs)
            except Exception:
                pass

    # 2. Automatic Manifest Diff (removes deleted/renamed buttons automatically)
    if old_manifest:
        removed_rels = set(old_manifest) - set(new_manifest)
        for rel_norm in sorted(removed_rels, reverse=True):
            rel_os = to_text(rel_norm).replace("/", os.sep)
            target_abs = os.path.abspath(os.path.join(ext_abs, rel_os))
            if not target_abs.lower().startswith(ext_abs.lower()) or target_abs == ext_abs:
                continue
            target_lp = win_long_path(target_abs)
            if os.path.isfile(target_lp):
                try:
                    os.chmod(target_lp, stat.S_IWRITE)
                    os.remove(target_lp)
                except Exception:
                    try:
                        os.rename(target_lp, u"{}{}{}".format(target_lp, LOCKED_SUFFIX_MARKER, int(time.time())))
                    except Exception:
                        pass

            # Prune empty bundle directories (.pushbutton, .stack, .pulldown, .panel)
            parent_abs = os.path.dirname(target_abs)
            while parent_abs != ext_abs and parent_abs.lower().startswith(ext_abs.lower()):
                parent_lp = win_long_path(parent_abs)
                try:
                    if os.path.isdir(parent_lp) and not os.listdir(parent_lp):
                        os.rmdir(parent_lp)
                        parent_abs = os.path.dirname(parent_abs)
                    else:
                        break
                except Exception:
                    break


# ------------------------------------------------------------------------------
# DOWNLOAD STREAMER & MAIN SYNC CONTROLLER
# ------------------------------------------------------------------------------
def download_zip_archive(target_sha, dest_zip_path, pb=None):
    url = GITHUB_ZIP_SHA_URL_TPL.format(target_sha) if target_sha else GITHUB_ZIP_MAIN_URL
    req = urllib2.Request(url)
    req.add_header("User-Agent", HTTP_USER_AGENT)
    req.add_header("Accept", "application/vnd.github+json")

    resp = urllib2.urlopen(req, timeout=35)
    try:
        total_len_str = _extract_header(resp, "Content-Length")
        total_bytes = int(total_len_str) if total_len_str.isdigit() else 0
        downloaded = 0

        with io.open(win_long_path(dest_zip_path), "wb") as zf:
            while True:
                chunk = resp.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                zf.write(chunk)
                downloaded += len(chunk)
                if pb is not None and total_bytes > 0:
                    pct = min(40, int((downloaded * 40.0) / total_bytes))
                    pb.update_progress(5 + pct, 100)
    finally:
        resp.close()


def execute_sync(force_reinstall=False):
    if is_admin_user():
        forms.alert(
            "Developer Mode (.git detected):\n"
            "Cloud Sync is disabled on this machine to protect your local source repository.",
            title="P13 Sync (Developer Guard)"
        )
        return

    dest_path = get_extension_root()
    purge_old_locked_trash(dest_path)

    status, local_sha, remote_sha, remote_info = compute_sync_status(
        dest_path, allow_network=True, force_network=True
    )

    if not remote_sha:
        forms.alert(
            "Could not reach GitHub API or API rate limit was exceeded.\n"
            "Please check your internet connection and try again in a few minutes.",
            title="P13 Sync (Offline / Rate Limited)",
            warn_icon=True
        )
        return

    if not force_reinstall and status == STATUS_LATEST:
        forms.toast(
            "Installed version ({}) already matches GitHub main.".format(local_sha[:8]),
            title="P13.extension is Up to Date"
        )
        return

    commits_list = fetch_changelog_commits(local_sha, remote_sha)
    if not show_update_confirmation_dialog(local_sha, remote_sha, remote_info, commits_list, is_force=force_reinstall):
        return

    temp_root = to_text(os.environ.get("TEMP") or os.environ.get("TMP") or dest_path)
    token = u"{}_{}".format(os.getpid(), int(time.time()))
    # Keep temp folder name short to maximize Windows path headroom
    temp_zip = os.path.join(temp_root, u"p13_{}.zip".format(token))
    temp_dir = os.path.join(temp_root, u"p13_x_{}".format(token))

    old_marker = read_local_marker_data(dest_path)
    old_manifest = old_marker.get("managed_files", [])

    update_ok = False
    skipped_files = []
    stats = {}

    try:
        with forms.ProgressBar(title="Updating P13.extension from GitHub ({value}%)", cancellable=False) as pb:
            pb.update_progress(5, 100)
            download_zip_archive(remote_sha, temp_zip, pb=pb)

            pb.update_progress(45, 100)
            extract_zip_safely(temp_zip, temp_dir)
            extracted_folder = get_extracted_extension_root(temp_dir)

            pb.update_progress(50, 100)
            migrate_private_settings(dest_path)
            stats, skipped_files, new_manifest = sync_directory_with_manifest(
                extracted_folder, dest_path, force_overwrite=force_reinstall, pb=pb
            )

            pb.update_progress(96, 100)
            cleanup_obsolete_and_manifest_diff(dest_path, old_manifest, new_manifest)

            if not skipped_files:
                write_marker_data(dest_path, remote_sha, new_manifest)
            pb.update_progress(100, 100)
            update_ok = True
    except Exception as exc:
        report_sync_error("P13.extension update failed.", exc)
    finally:
        try:
            remove_tree_fast(temp_zip)
            remove_tree_fast(temp_dir)
        except Exception:
            pass

    if not update_ok:
        return

    if skipped_files:
        msg_lines = [u"Update finished with {} locked file(s):".format(len(skipped_files))]
        for p, reason in skipped_files[:30]:
            msg_lines.append(u"- {}: {}".format(p, reason))
        log_path = write_sync_log(u"\n".join(msg_lines))
        forms.alert(
            u"Update applied, but {} locked file(s) could not be replaced.\n"
            u"Restart Revit and run Update once more.\n\nLog: {}".format(len(skipped_files), log_path),
            title="P13 Sync (Partial Lock)",
            warn_icon=True
        )
    else:
        forms.toast(
            u"Updated {} file(s) ({} unchanged) to commit {}.".format(
                stats.get("updated", 0) + stats.get("renamed_aside", 0),
                stats.get("unchanged", 0),
                remote_sha[:8]
            ),
            title="P13.extension Updated"
        )

    try:
        sessionmgr.reload_pyrevit()
    except Exception as exc:
        log_path = write_sync_log(u"Reload failed:\n{}\n{}".format(exc, traceback.format_exc()))
        forms.alert(
            u"Files updated successfully, but automatic reload failed.\n"
            u"Please click Reload on the pyRevit tab manually.\n\nLog: {}".format(log_path),
            title="P13 Sync"
        )


def run_shift_click_menu():
    ext_root = get_extension_root()
    local_sha = get_local_sha(ext_root)
    options = [
        "1. Force Re-Sync & Repair All Files from GitHub",
        "2. View Recent GitHub Commits (Changelog)",
        "3. Open Diagnostic Sync Log",
        "4. Reset Remote Status Cache"
    ]
    picked = forms.CommandSwitchWindow.show(
        options,
        message="P13 Sync Maintenance (Installed SHA: {})".format(local_sha[:10] if local_sha else "None")
    )
    if not picked:
        return

    if picked.startswith("1."):
        execute_sync(force_reinstall=True)
    elif picked.startswith("2."):
        _, _, rem_sha, _ = compute_sync_status(ext_root, allow_network=True, force_network=True)
        commits = fetch_changelog_commits("", rem_sha)
        forms.alert(
            u"\n".join(commits) if commits else u"No recent commit history available.",
            title="P13 GitHub Recent Commits"
        )
    elif picked.startswith("3."):
        log_p = get_temp_path(SYNC_LOG_FILE)
        if os.path.isfile(win_long_path(log_p)):
            subprocess.Popen(["notepad.exe", strip_long_path(log_p)])
        else:
            forms.alert("No error log recorded yet. Everything is running cleanly!", title="P13 Sync Log")
    elif picked.startswith("4."):
        cache_p = get_temp_path(REMOTE_CACHE_FILE)
        remove_tree_fast(cache_p)
        forms.toast("Cleared GitHub status cache.", title="P13 Sync")


def main():
    is_shift = bool(getattr(EXEC_PARAMS, "config_mode", False)) or bool(globals().get("__shiftclick__", False))
    if is_shift:
        run_shift_click_menu()
    else:
        execute_sync(force_reinstall=False)


if __name__ == "__main__":
    main()