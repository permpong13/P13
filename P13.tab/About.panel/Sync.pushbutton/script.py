# -*- coding: utf-8 -*-
# pylint: disable=import-error,invalid-name,broad-except,too-many-lines
"""P13.extension Cloud Sync & Updater (Pro Edition v2.3 - Enterprise)."""
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
import xml.etree.ElementTree as ET

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
from System.Diagnostics import Process
from System.IO import FileStream
from System.IO import FileMode
from System.IO import FileAccess
from System.IO import FileShare
from System.IO import StreamReader
from System.Net import WebRequest
from System.Net import WebException
from System.Net import HttpStatusCode
from System.Net import CredentialCache
from System.Net import ServicePointManager
from System.Net import SecurityProtocolType
from System.Text import Encoding
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

# Enable TLS 1.2+ and bind Windows Default Corporate Proxy Credentials
try:
    ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12
except Exception:
    pass

try:
    if WebRequest.DefaultWebProxy is not None:
        WebRequest.DefaultWebProxy.Credentials = CredentialCache.DefaultCredentials
except Exception:
    pass


# ------------------------------------------------------------------------------
# CONSTANTS & CONFIGURATION
# ------------------------------------------------------------------------------
USER_REPO = "Permpong13/P13"
BRANCH_NAME = "main"

API_BASE = "https://api.github.com/repos/{}".format(USER_REPO)
GITHUB_COMMIT_API_URL = "{}/commits/{}".format(API_BASE, BRANCH_NAME)
GITHUB_COMMITS_LIST_URL = "{}/commits?sha={}&per_page=10".format(API_BASE, BRANCH_NAME)
GITHUB_COMPARE_URL_TPL = API_BASE + "/compare/{}...{}"

# Zero-Rate-Limit Endpoints (Atom Feed & GitHub CDN Archive)
GITHUB_ATOM_FEED_URL = "https://github.com/{}/commits/{}.atom".format(USER_REPO, BRANCH_NAME)
CODELOAD_ZIP_SHA_TPL = "https://codeload.github.com/{}/zip/{}".format(USER_REPO, "{}")
CODELOAD_ZIP_BRANCH_URL = "https://codeload.github.com/{}/zip/refs/heads/{}".format(USER_REPO, BRANCH_NAME)
GITHUB_ARCHIVE_SHA_TPL = "https://github.com/{}/archive/{}.zip".format(USER_REPO, "{}")
GITHUB_API_ZIP_SHA_TPL = API_BASE + "/zipball/{}"

VERSION_MARKER_FILE = ".p13_sync_version"
LOCAL_DEV_LOCK_FILE = ".p13_dev_lock"
ACTIVE_UPDATE_LOCK_FILE = ".p13_updating.lock"
APPDATA_DEV_LOCK_NAME = "dev_mode.lock"
REMOTE_CACHE_FILE = "P13_sync_remote_status.json"
SYNC_LOG_FILE = "P13_sync_error.log"

BG_CHECK_INTERVAL_SECONDS = 600
ACTIVE_LOCK_STALE_SECONDS = 180
DOWNLOAD_CHUNK_SIZE = 65536
FAST_FILE_RETRIES = 2
FAST_FILE_RETRY_WAIT = 0.15
LOCKED_SUFFIX_MARKER = ".old_locked_"
SUBPROCESS_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

HTTP_USER_AGENT = "P13-pyRevit-Sync-Pro/2.3 (+https://github.com/{})".format(USER_REPO)

STATUS_LATEST = "latest"
STATUS_OUTDATED = "outdated"
STATUS_UNKNOWN = "unknown"
STATUS_ICONS = {
    STATUS_LATEST: "icon.latest.png",
    STATUS_OUTDATED: "icon.outdated.png",
    STATUS_UNKNOWN: "icon.unknown.png",
}

MIRRORED_TOP_DIRS = ("P13.tab", "lib", "hooks")
USER_CONFIG_EXTS = (".json", ".xml", ".ini", ".cfg", ".user", ".sqlite", ".db")
SYSTEM_CONFIG_FILENAMES = ("extension.json", "package.json")
BUNDLE_DIR_SUFFIXES = (
    ".pushbutton",
    ".pulldown",
    ".splitbutton",
    ".splitpushbutton",
    ".smartbutton",
    ".urlbutton",
    ".invokebutton",
    ".content",
)

PY2 = sys.version_info[0] < 3
TEXT_TYPE = unicode if PY2 else str  # noqa: F821

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


def get_p13_appdata_dir():
    appdata_path = to_text(os.environ.get("APPDATA") or os.path.expanduser("~"))
    return os.path.join(appdata_path, u"pyRevit", u"P13")


def get_temp_path(file_name):
    temp_dir = to_text(os.environ.get("TEMP") or os.environ.get("TMP") or get_extension_root())
    return os.path.join(temp_dir, to_text(file_name))


def write_json_utf8(file_path, payload):
    raw = json.dumps(payload, indent=2, ensure_ascii=False)
    if PY2 and isinstance(raw, str):
        raw = raw.decode("utf-8")
    tmp_p = to_text(file_path) + u".tmp_{}".format(os.getpid())
    parent_lp = os.path.dirname(win_long_path(file_path))
    if parent_lp and not os.path.isdir(parent_lp):
        os.makedirs(parent_lp)
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
# MULTI-REVIT PROCESS LOCK & DEVELOPER GUARD
# ------------------------------------------------------------------------------
def is_pid_running(pid):
    if not pid or pid <= 0:
        return False
    try:
        proc = Process.GetProcessById(int(pid))
        if proc is not None and not proc.HasExited:
            return True
    except Exception:
        pass
    return False


def get_active_update_lock_path(extension_root):
    return os.path.join(extension_root, ACTIVE_UPDATE_LOCK_FILE)


def acquire_update_process_lock(extension_root):
    """Prevent concurrent updates when multiple Revit instances are open."""
    lock_path = get_active_update_lock_path(extension_root)
    lock_lp = win_long_path(lock_path)
    my_pid = os.getpid()

    if os.path.isfile(lock_lp):
        try:
            data = read_json_utf8(lock_path)
            other_pid = int(data.get("pid", 0))
            started_at = float(data.get("started_at", 0))
            age = time.time() - started_at
            if other_pid != my_pid and age < ACTIVE_LOCK_STALE_SECONDS and is_pid_running(other_pid):
                return False, other_pid, int(max(1, age))
        except Exception:
            pass

    try:
        write_json_utf8(lock_path, {
            "pid": my_pid,
            "started_at": time.time(),
            "started_str": time.strftime("%Y-%m-%d %H:%M:%S")
        })
    except Exception:
        pass
    return True, my_pid, 0


def release_update_process_lock(extension_root):
    lock_lp = win_long_path(get_active_update_lock_path(extension_root))
    try:
        if os.path.isfile(lock_lp):
            os.remove(lock_lp)
    except Exception:
        pass


def get_machine_dev_lock_path():
    return os.path.join(get_p13_appdata_dir(), APPDATA_DEV_LOCK_NAME)


def is_dev_guard_locked(extension_root=None):
    ext_root = extension_root or get_extension_root()
    if os.path.isfile(win_long_path(get_machine_dev_lock_path())):
        return True
    if os.path.isfile(win_long_path(os.path.join(ext_root, LOCAL_DEV_LOCK_FILE))):
        return True
    return False


def set_dev_guard_locked(enabled):
    lock_path = get_machine_dev_lock_path()
    lock_lp = win_long_path(lock_path)
    if enabled:
        parent_lp = os.path.dirname(lock_lp)
        if not os.path.isdir(parent_lp):
            os.makedirs(parent_lp)
        with io.open(lock_lp, "w", encoding="utf-8") as f:
            f.write(u"P13 Developer Guard enabled at {}\n".format(time.strftime("%Y-%m-%d %H:%M:%S")))
    else:
        if os.path.isfile(lock_lp):
            os.remove(lock_lp)
        legacy_lock = win_long_path(os.path.join(get_extension_root(), LOCAL_DEV_LOCK_FILE))
        if os.path.isfile(legacy_lock):
            os.remove(legacy_lock)


def run_git_command_quiet(extension_root, args_list):
    try:
        cmd = ["git", "-C", strip_long_path(extension_root)] + list(args_list)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=SUBPROCESS_NO_WINDOW
        )
        stdout_data, _ = proc.communicate()
        out_txt = to_text(stdout_data).strip() if stdout_data else u""
        return proc.returncode, out_txt
    except Exception:
        return -1, u""


def detect_unpushed_dev_work(extension_root):
    """Warn ONLY if local .git has unpushed commits or uncommitted dev work."""
    git_dir = os.path.join(extension_root, ".git")
    if not os.path.exists(win_long_path(git_dir)):
        return u""

    rc_ahead, out_ahead = run_git_command_quiet(
        extension_root, ["rev-list", "--count", "@{u}..HEAD"]
    )
    if rc_ahead == 0 and out_ahead.isdigit() and int(out_ahead) > 0:
        return u"{} unpushed local Git commit(s) detected.".format(out_ahead)

    marker_exists = os.path.isfile(win_long_path(os.path.join(extension_root, VERSION_MARKER_FILE)))
    if marker_exists:
        return u""

    rc_st, out_st = run_git_command_quiet(
        extension_root, ["status", "--porcelain", "--untracked-files=no"]
    )
    if rc_st == 0 and out_st:
        changed = []
        ignored_markers = (VERSION_MARKER_FILE, LOCAL_DEV_LOCK_FILE, ACTIVE_UPDATE_LOCK_FILE, LOCKED_SUFFIX_MARKER)
        for line in out_st.splitlines():
            clean_line = line.strip()
            if not clean_line or any(m in clean_line for m in ignored_markers):
                continue
            changed.append(clean_line)
        if changed:
            preview = u"\n".join(changed[:5])
            if len(changed) > 5:
                preview += u"\n... (+{} more)".format(len(changed) - 5)
            return u"Uncommitted local file edits detected:\n{}".format(preview)

    return u""


# ------------------------------------------------------------------------------
# CORPORATE PROXY-AWARE HTTP ENGINE (.NET WebRequest + urllib2 Fallback)
# ------------------------------------------------------------------------------
def _prepare_dotnet_request(url, accept_header=None, etag=None, timeout_sec=10):
    req = WebRequest.Create(str(url))
    req.Method = "GET"
    req.Timeout = int(timeout_sec * 1000)
    try:
        req.ReadWriteTimeout = int(max(15, timeout_sec) * 1000)
        req.AllowAutoRedirect = True
        req.UserAgent = HTTP_USER_AGENT
        if accept_header:
            req.Accept = str(accept_header)
    except Exception:
        pass

    try:
        proxy = WebRequest.DefaultWebProxy
        if proxy is not None:
            proxy.Credentials = CredentialCache.DefaultCredentials
            req.Proxy = proxy
        req.Credentials = CredentialCache.DefaultCredentials
    except Exception:
        pass

    if etag:
        try:
            req.Headers.Add("If-None-Match", str(etag))
        except Exception:
            pass
    return req


def http_get_text(url, accept_header=None, etag=None, timeout_sec=8):
    """Fetch UTF-8 text via corporate-proxy-aware .NET WebRequest with urllib2 fallback.
    Returns tuple: (status_code, body_text, response_etag)
    """
    # 1. Primary: .NET HttpWebRequest (uses Windows Cert Store + Corporate NTLM Proxy)
    resp = None
    try:
        req = _prepare_dotnet_request(url, accept_header=accept_header, etag=etag, timeout_sec=timeout_sec)
        resp = req.GetResponse()
        resp_etag = u""
        try:
            raw_etag = resp.Headers.Get("ETag")
            if raw_etag:
                resp_etag = to_text(raw_etag).strip()
        except Exception:
            pass
        reader = StreamReader(resp.GetResponseStream(), Encoding.UTF8)
        try:
            text_body = to_text(reader.ReadToEnd())
        finally:
            reader.Close()
        return 200, text_body, resp_etag
    except WebException as wex:
        wresp = getattr(wex, "Response", None)
        if wresp is not None:
            try:
                if wresp.StatusCode == HttpStatusCode.NotModified:
                    return 304, u"", to_text(etag or "")
                try:
                    code_int = int(wresp.StatusCode)
                except Exception:
                    code_int = 500
                return code_int, u"", u""
            finally:
                try:
                    wresp.Close()
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        if resp is not None:
            try:
                resp.Close()
            except Exception:
                pass

    # 2. Fallback: Python urllib2
    py_resp = None
    try:
        py_req = urllib2.Request(url)
        py_req.add_header("User-Agent", HTTP_USER_AGENT)
        if accept_header:
            py_req.add_header("Accept", accept_header)
        if etag:
            py_req.add_header("If-None-Match", str(etag))
        py_resp = urllib2.urlopen(py_req, timeout=timeout_sec)
        raw_bytes = py_resp.read()
        resp_etag = u""
        try:
            info = py_resp.info()
            val = info.getheader("ETag") if hasattr(info, "getheader") else py_resp.headers.get("ETag")
            if val:
                resp_etag = to_text(val).strip()
        except Exception:
            pass
        return 200, raw_bytes.decode("utf-8", "replace"), resp_etag
    except urllib_error.HTTPError as herr:
        code = getattr(herr, "code", 500)
        if code == 304:
            return 304, u"", to_text(etag or "")
        return code, u"", u""
    finally:
        if py_resp is not None:
            try:
                py_resp.Close()
            except Exception:
                try:
                    py_resp.close()
                except Exception:
                    pass


def http_download_stream(url, dest_file_path, timeout_sec=40, pb=None):
    """Stream binary file via .NET WebRequest (corporate proxy safe) with urllib2 fallback."""
    clean_dest = strip_long_path(os.path.abspath(dest_file_path))
    parent_lp = win_long_path(os.path.dirname(clean_dest))
    if not os.path.isdir(parent_lp):
        os.makedirs(parent_lp)

    # 1. Primary: .NET HttpWebRequest + .NET FileStream (zero marshaling overhead)
    resp = None
    fs = None
    try:
        req = _prepare_dotnet_request(url, accept_header="*/*", timeout_sec=timeout_sec)
        resp = req.GetResponse()
        total_bytes = int(resp.ContentLength) if resp.ContentLength > 0 else 0
        net_stream = resp.GetResponseStream()
        fs = FileStream(clean_dest, FileMode.Create, FileAccess.Write, FileShare.None)
        buf = System.Array.CreateInstance(System.Byte, DOWNLOAD_CHUNK_SIZE)
        downloaded = 0
        while True:
            read_cnt = net_stream.Read(buf, 0, DOWNLOAD_CHUNK_SIZE)
            if read_cnt <= 0:
                break
            fs.Write(buf, 0, read_cnt)
            downloaded += read_cnt
            if pb is not None and total_bytes > 0:
                pct = min(40, int((downloaded * 40.0) / total_bytes))
                pb.update_progress(5 + pct, 100)
        fs.Flush()
        return True
    except Exception as dotnet_err:
        write_sync_log(u".NET stream fallback triggered for {}: {}".format(url, dotnet_err))
    finally:
        if fs is not None:
            try:
                fs.Close()
            except Exception:
                pass
        if resp is not None:
            try:
                resp.Close()
            except Exception:
                pass

    # 2. Fallback: urllib2
    py_req = urllib2.Request(url)
    py_req.add_header("User-Agent", HTTP_USER_AGENT)
    py_resp = urllib2.urlopen(py_req, timeout=timeout_sec)
    try:
        total_bytes = 0
        try:
            info = py_resp.info()
            clen = info.getheader("Content-Length") if hasattr(info, "getheader") else py_resp.headers.get("Content-Length")
            if clen and str(clen).isdigit():
                total_bytes = int(clen)
        except Exception:
            pass

        downloaded = 0
        with io.open(win_long_path(dest_file_path), "wb") as zf:
            while True:
                chunk = py_resp.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                zf.write(chunk)
                downloaded += len(chunk)
                if pb is not None and total_bytes > 0:
                    pct = min(40, int((downloaded * 40.0) / total_bytes))
                    pb.update_progress(5 + pct, 100)
        return True
    finally:
        py_resp.close()


# ------------------------------------------------------------------------------
# VERSION MARKER & PURE-PYTHON GIT SHA READER
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


def read_git_sha_pure_python(extension_root):
    git_dir = os.path.join(extension_root, ".git")
    head_file = win_long_path(os.path.join(git_dir, "HEAD"))
    if not os.path.isfile(head_file):
        return u""
    try:
        with io.open(head_file, "r", encoding="utf-8") as f:
            head_txt = f.read().strip()
        if not head_txt.startswith(u"ref:"):
            return head_txt if len(head_txt) >= 7 else u""

        ref_rel = head_txt.split(u":", 1)[1].strip().replace(u"/", os.sep)
        ref_file = win_long_path(os.path.join(git_dir, ref_rel))
        if os.path.isfile(ref_file):
            with io.open(ref_file, "r", encoding="utf-8") as rf:
                sha = rf.read().strip()
                if sha:
                    return sha

        packed_file = win_long_path(os.path.join(git_dir, "packed-refs"))
        ref_posix = head_txt.split(u":", 1)[1].strip()
        if os.path.isfile(packed_file):
            with io.open(packed_file, "r", encoding="utf-8") as pf:
                for line in pf:
                    line = line.strip()
                    if not line or line.startswith(u"#") or line.startswith(u"^"):
                        continue
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] == ref_posix:
                        return parts[0]
    except Exception:
        pass
    return u""


def get_local_git_sha(extension_root):
    sha = read_git_sha_pure_python(extension_root)
    if sha:
        return sha
    git_path = os.path.join(extension_root, ".git")
    if not os.path.exists(win_long_path(git_path)):
        return u""
    rc, out = run_git_command_quiet(extension_root, ["rev-parse", "HEAD"])
    return out if rc == 0 else u""


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
# GITHUB API + ZERO-RATE-LIMIT ATOM FEED FALLBACK
# ------------------------------------------------------------------------------
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


def parse_atom_feed_commits(xml_text):
    """Parse GitHub Atom XML feed into [{'sha', 'date', 'message'}, ...] (0 API quota!)."""
    results = []
    if not xml_text:
        return results
    try:
        raw_utf8 = to_text(xml_text).encode("utf-8")
        root = ET.fromstring(raw_utf8)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("a:entry", ns):
            sha = u""
            id_el = entry.find("a:id", ns)
            if id_el is not None and id_el.text and "/" in id_el.text:
                cand = to_text(id_el.text).rsplit("/", 1)[-1].strip()
                if len(cand) >= 7:
                    sha = cand
            if not sha:
                link_el = entry.find("a:link", ns)
                href = to_text(link_el.attrib.get("href", "")) if link_el is not None else u""
                if "/commit/" in href:
                    sha = href.rsplit("/commit/", 1)[-1].strip()

            title_el = entry.find("a:title", ns)
            msg = to_text(title_el.text).strip() if (title_el is not None and title_el.text) else u"Update"
            upd_el = entry.find("a:updated", ns)
            dt = to_text(upd_el.text).strip().replace("T", " ").replace("Z", "") if (upd_el is not None and upd_el.text) else u""
            if sha:
                results.append({"sha": sha, "date": dt, "message": msg})
    except Exception as ex:
        write_sync_log(u"Atom XML parse warning: {}".format(ex))
    return results


def fetch_atom_commits(timeout=8):
    code, xml_body, _ = http_get_text(
        GITHUB_ATOM_FEED_URL,
        accept_header="application/atom+xml, application/xml, text/xml",
        timeout_sec=timeout
    )
    if code == 200 and xml_body:
        return parse_atom_feed_commits(xml_body)
    return []


def fetch_remote_commit_info(allow_network=True, force_network=False, timeout=7):
    """Fetch latest commit via ETag API; auto-fallback to Atom feed if office IP hits rate limit."""
    cache_path = get_temp_path(REMOTE_CACHE_FILE)
    cached = read_remote_cache()

    if not allow_network:
        return cached

    if not force_network and cached.get("sha"):
        age = time.time() - float(cached.get("checked_at", 0))
        if age <= BG_CHECK_INTERVAL_SECONDS:
            return cached

    # 1. Try GitHub REST API with ETag (304 Not Modified = 0 quota cost)
    code, body_txt, new_etag = http_get_text(
        GITHUB_COMMIT_API_URL,
        accept_header="application/vnd.github+json",
        etag=cached.get("etag"),
        timeout_sec=timeout
    )

    if code == 304 and cached.get("sha"):
        cached["checked_at"] = time.time()
        try:
            write_json_utf8(cache_path, cached)
        except Exception:
            pass
        return cached

    if code == 200 and body_txt:
        try:
            data = json.loads(body_txt)
            sha = to_text(data.get("sha") or "").strip()
            commit_obj = data.get("commit") or {}
            author_obj = commit_obj.get("committer") or commit_obj.get("author") or {}
            c_date = to_text(author_obj.get("date") or "").replace("T", " ").replace("Z", "")
            c_msg = to_text(commit_obj.get("message") or "").splitlines()[0] if commit_obj.get("message") else u""
            if sha:
                updated_cache = {
                    "repo": USER_REPO,
                    "sha": sha,
                    "date": c_date,
                    "message": c_msg,
                    "etag": new_etag or cached.get("etag", ""),
                    "checked_at": time.time()
                }
                try:
                    write_json_utf8(cache_path, updated_cache)
                except Exception:
                    pass
                return updated_cache
        except Exception as ex:
            write_sync_log(u"API JSON parse warning: {}".format(ex))

    # 2. Zero-Rate-Limit Fallback: GitHub Atom Feed (works even when API 403/429 rate limited!)
    atom_entries = fetch_atom_commits(timeout=timeout)
    if atom_entries:
        top = atom_entries[0]
        updated_cache = {
            "repo": USER_REPO,
            "sha": top["sha"],
            "date": top["date"],
            "message": top["message"],
            "etag": cached.get("etag", ""),
            "checked_at": time.time()
        }
        try:
            write_json_utf8(cache_path, updated_cache)
        except Exception:
            pass
        return updated_cache

    return cached


def fetch_changelog_commits(local_sha, remote_sha, timeout=7):
    """Fetch human-readable changelog via GitHub API with automatic Atom Feed fallback."""
    if local_sha and remote_sha and local_sha.lower() != remote_sha.lower():
        url = GITHUB_COMPARE_URL_TPL.format(local_sha[:12], remote_sha[:12])
        is_compare = True
    else:
        url = GITHUB_COMMITS_LIST_URL
        is_compare = False

    items = []
    code, body_txt, _ = http_get_text(
        url,
        accept_header="application/vnd.github+json",
        timeout_sec=timeout
    )
    if code == 200 and body_txt:
        try:
            data = json.loads(body_txt)
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
            if items:
                return items
        except Exception:
            pass

    # Fallback to Atom Feed if API rate-limited
    atom_entries = fetch_atom_commits(timeout=timeout)
    loc_prefix = local_sha[:7].lower() if local_sha else u""
    for entry in atom_entries[:12]:
        e_sha = entry["sha"]
        if loc_prefix and e_sha.lower().startswith(loc_prefix):
            break
        items.append(u"[{}] {} ({})".format(e_sha[:7], entry["message"], entry["date"][:10]))
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
# NON-LOCKING RIBBON ICON & LIVE RIBBON REFRESH
# ------------------------------------------------------------------------------
def load_unlocked_bitmap(icon_path):
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
    try:
        getter = getattr(ui_button_cmp, "get_rvtapi_object", None)
        if callable(getter):
            rvt_obj = getter()
            if rvt_obj is not None:
                targets.append(rvt_obj)
    except Exception:
        pass

    for attr_name in ["_rvtapi_object", "rvtapi_object", "ui_item", "control", "button"]:
        try:
            target = getattr(ui_button_cmp, attr_name, None)
            if target is not None and target not in targets:
                targets.append(target)
        except Exception:
            pass
    return targets


def apply_ribbon_visuals(script_cmp, ui_button_cmp, status, local_sha, remote_sha, pending_reload=False):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    icon_name = STATUS_ICONS.get(status, STATUS_ICONS[STATUS_UNKNOWN])
    try:
        icon_path = script_cmp.get_bundle_file(icon_name) if script_cmp else None
    except Exception:
        icon_path = None
    if not icon_path:
        icon_path = os.path.join(current_dir, icon_name)

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

    dev_locked = is_dev_guard_locked()
    if dev_locked:
        headline = u"[Developer Guard ON] Cloud Sync locked on this PC."
    elif pending_reload:
        headline = u"[Updated - Pending Reload] Files updated; reload pyRevit when ready."
    elif status == STATUS_LATEST:
        headline = u"[Up to Date] P13.extension matches GitHub main."
    elif status == STATUS_OUTDATED:
        headline = u"[Update Available] Click to review & install latest P13 tools."
    else:
        headline = u"[Status Unchecked] Click to check GitHub for P13 updates."

    loc_lbl = local_sha[:10] if local_sha else u"not recorded"
    rem_lbl = remote_sha[:10] if remote_sha else u"checking..."
    tip_text = u"{}\nInstalled: {}\nLatest GitHub: {}\n\nShift+Click: Maintenance & Developer Guard".format(
        headline, loc_lbl, rem_lbl
    )

    for target in get_ribbon_targets(ui_button_cmp):
        for attr_name in ["ToolTip", "tooltip"]:
            try:
                if hasattr(target, attr_name):
                    setattr(target, attr_name, tip_text)
            except Exception:
                pass


def refresh_live_ribbon_button(status, local_sha, remote_sha, pending_reload=False):
    """Find live Update button on P13 ribbon and update its icon immediately without reloading."""
    try:
        for tab in ribbon.get_current_ui():
            if to_text(getattr(tab, "name", "")).lower() != u"p13":
                continue
            for panel in getattr(tab, "panels", []):
                for item in getattr(panel, "items", []):
                    if to_text(getattr(item, "name", "")).lower() == u"update":
                        apply_ribbon_visuals(None, item, status, local_sha, remote_sha, pending_reload=pending_reload)
                        return
    except Exception:
        pass


def _start_background_ribbon_check(extension_root, script_cmp, ui_button_cmp):
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
    ext_root = get_extension_root()
    status, local_sha, remote_sha, cache_info = compute_sync_status(ext_root, allow_network=False)
    apply_ribbon_visuals(script_cmp, ui_button_cmp, status, local_sha, remote_sha)

    if not is_dev_guard_locked(ext_root):
        age = time.time() - float(cache_info.get("checked_at", 0)) if cache_info else 999999
        if age > BG_CHECK_INTERVAL_SECONDS:
            _start_background_ribbon_check(ext_root, script_cmp, ui_button_cmp)
    return True


# ------------------------------------------------------------------------------
# REVIT-NATIVE WPF CHANGELOG DIALOG (WITH "RELOAD NOW" vs "RELOAD LATER")
# ------------------------------------------------------------------------------
UPDATE_DIALOG_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="P13.extension - Software Update"
        Width="610" Height="430" MinWidth="540" MinHeight="350"
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
                <TextBlock Text="Tip: Choose 'Update Only' if working in a heavy model." Foreground="#666666" FontSize="11" VerticalAlignment="Center"/>
                <StackPanel Grid.Column="1" Orientation="Horizontal">
                    <Button Name="btn_reload_now" Content="Update &amp; Reload" Width="128" Height="27"
                            Background="#006CBE" Foreground="#FFFFFF" BorderBrush="#005499" FontWeight="SemiBold" Margin="0,0,8,0" IsDefault="True"/>
                    <Button Name="btn_reload_later" Content="Update Only (Reload Later)" Width="166" Height="27"
                            Background="#FFFFFF" Foreground="#005A9E" BorderBrush="#006CBE" Margin="0,0,8,0"/>
                    <Button Name="btn_cancel" Content="Cancel" Width="74" Height="27"
                            Background="#FBFBFB" BorderBrush="#ABADB3" IsCancel="True"/>
                </StackPanel>
            </Grid>
        </Border>
    </Grid>
</Window>
"""


def show_update_confirmation_dialog(local_sha, remote_sha, remote_info, commits_list, is_force=False):
    """Return 'reload', 'later', or None."""
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
        btn_reload_now = win.FindName("btn_reload_now")
        btn_reload_later = win.FindName("btn_reload_later")
        btn_cancel = win.FindName("btn_cancel")

        loc_short = local_sha[:10] if local_sha else u"None"
        rem_short = remote_sha[:10] if remote_sha else u"Latest"
        rem_date = to_text(remote_info.get("date") or "")

        if is_force:
            lbl_headline.Text = u"Force Re-Sync & Repair P13.extension"
            btn_reload_now.Content = u"Re-Sync & Reload"
        lbl_versions.Text = u"Installed: {}    ->    GitHub Latest: {}  ({})".format(
            loc_short, rem_short, rem_date or u"main"
        )

        bullet = u"\u2022 "
        if commits_list:
            txt_changelog.Text = u"\n".join(bullet + item for item in commits_list)
        elif remote_info.get("message"):
            txt_changelog.Text = u"{}[{}] {}".format(bullet, rem_short[:7], to_text(remote_info.get("message")))
        else:
            txt_changelog.Text = u"{}Ready to synchronize package files from GitHub ({}).".format(bullet, USER_REPO)

        decision = {"mode": None}

        def _on_reload_now(_s, _a):
            decision["mode"] = "reload"
            win.Close()

        def _on_reload_later(_s, _a):
            decision["mode"] = "later"
            win.Close()

        def _on_cancel(_s, _a):
            decision["mode"] = None
            win.Close()

        btn_reload_now.Click += _on_reload_now
        btn_reload_later.Click += _on_reload_later
        btn_cancel.Click += _on_cancel
        win.ShowDialog()
        return decision["mode"]
    except Exception:
        ok = forms.alert(
            u"New P13.extension update available!\n\nInstalled: {}\nLatest: {}\n\nInstall update and reload pyRevit now?".format(
                local_sha[:10] if local_sha else u"None",
                remote_sha[:10] if remote_sha else u"Latest"
            ),
            title="P13 Sync (Pro)",
            yes=True,
            no=True
        )
        return "reload" if ok else None


# ------------------------------------------------------------------------------
# ZERO-FREEZE FILE ENGINE + SMART USER CONFIG PRESERVATION & AUTO-RELOCATE
# ------------------------------------------------------------------------------
def purge_old_locked_trash(extension_root):
    for root_dir, dir_names, file_names in os.walk(win_long_path(extension_root)):
        if ".git" in dir_names:
            dir_names.remove(".git")
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
    base_lp = win_long_path(extract_dir)
    if not os.path.isdir(base_lp):
        os.makedirs(base_lp)

    with zipfile.ZipFile(win_long_path(zip_path), "r") as zf:
        bad_member = zf.testzip()
        if bad_member:
            raise RuntimeError("Corrupted file inside downloaded ZIP: {}".format(bad_member))

        for member in zf.infolist():
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
    private_root = get_p13_appdata_dir()
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

    trash_lp = u"{}{}{}_{}".format(dst_lp, LOCKED_SUFFIX_MARKER, os.getpid(), int(time.time()))
    try:
        os.rename(dst_lp, trash_lp)
        shutil.copy2(src_lp, dst_lp)
        return "renamed_aside"
    except Exception:
        skipped_files.append((strip_long_path(dst_lp), to_text(last_err or "Locked by process")))
        return "skipped"


def sync_directory_with_manifest(extracted_root, dest_root, force_overwrite=False, pb=None):
    all_file_pairs = []
    src_base = os.path.abspath(to_text(extracted_root))
    dst_base = os.path.abspath(to_text(dest_root))
    ignored_names = (VERSION_MARKER_FILE, LOCAL_DEV_LOCK_FILE, ACTIVE_UPDATE_LOCK_FILE)

    for root_dir, dir_names, file_names in os.walk(win_long_path(src_base)):
        if ".git" in dir_names:
            dir_names.remove(".git")
        clean_root = strip_long_path(root_dir)
        rel_dir = os.path.relpath(clean_root, src_base)
        for fname in file_names:
            if fname in ignored_names or LOCKED_SUFFIX_MARKER in fname:
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


def _build_new_tree_indexes(new_manifest):
    """Build fast lookup sets for active files, active directories, and relocated bundles."""
    new_files_lower = set()
    new_dirs_lower = set()
    bundle_leaf_map = {}

    for rel_posix in new_manifest:
        norm_l = rel_posix.lower()
        new_files_lower.add(norm_l)
        parts = rel_posix.split("/")
        for depth in range(1, len(parts)):
            dir_posix = "/".join(parts[:depth])
            dir_lower = dir_posix.lower()
            new_dirs_lower.add(dir_lower)
            leaf_name = parts[depth - 1].lower()
            if leaf_name.endswith(BUNDLE_DIR_SUFFIXES):
                bucket = bundle_leaf_map.setdefault(leaf_name, set())
                bucket.add(dir_posix)

    return new_files_lower, new_dirs_lower, bundle_leaf_map


def _backup_and_relocate_user_config(extension_root, src_file_abs, rel_posix, bundle_leaf_map):
    """Backup user config to %APPDATA% AND copy to moved bundle if uniquely relocated."""
    src_lp = win_long_path(src_file_abs)
    if not os.path.isfile(src_lp):
        return

    # 1. Always keep a safe backup under %APPDATA%\pyRevit\P13\Backup_Configs
    backup_abs = os.path.join(get_p13_appdata_dir(), u"Backup_Configs", rel_posix.replace("/", os.sep))
    backup_lp = win_long_path(backup_abs)
    try:
        b_parent = os.path.dirname(backup_lp)
        if not os.path.isdir(b_parent):
            os.makedirs(b_parent)
        shutil.copy2(src_lp, backup_lp)
    except Exception:
        pass

    # 2. If parent bundle was moved (e.g. Manager.panel/X.pushbutton -> Manager.panel/Menu.pulldown/X.pushbutton),
    # automatically copy the user's local preset/settings file to its new home!
    parts = rel_posix.split("/")
    if len(parts) >= 2:
        parent_leaf_lower = parts[-2].lower()
        fname = parts[-1]
        candidates = list(bundle_leaf_map.get(parent_leaf_lower, []))
        if len(candidates) == 1:
            new_dir_rel = candidates[0].replace("/", os.sep)
            relocated_abs = os.path.join(extension_root, new_dir_rel, fname)
            relocated_lp = win_long_path(relocated_abs)
            if not os.path.exists(relocated_lp):
                try:
                    r_parent = os.path.dirname(relocated_lp)
                    if not os.path.isdir(r_parent):
                        os.makedirs(r_parent)
                    shutil.copy2(src_lp, relocated_lp)
                except Exception:
                    pass


def _delete_or_rename_locked_file(file_abs):
    target_lp = win_long_path(file_abs)
    if not os.path.isfile(target_lp):
        return
    try:
        os.chmod(target_lp, stat.S_IWRITE)
        os.remove(target_lp)
    except Exception:
        try:
            os.rename(target_lp, u"{}{}{}_{}".format(target_lp, LOCKED_SUFFIX_MARKER, os.getpid(), int(time.time())))
        except Exception:
            pass


def _prune_empty_parents(start_dir_abs, stop_root_abs):
    curr = os.path.abspath(to_text(start_dir_abs))
    stop = os.path.abspath(to_text(stop_root_abs))
    while curr != stop and curr.lower().startswith(stop.lower()):
        curr_lp = win_long_path(curr)
        try:
            if os.path.isdir(curr_lp) and not os.listdir(curr_lp):
                os.rmdir(curr_lp)
                curr = os.path.dirname(curr)
            else:
                break
        except Exception:
            break


def cleanup_obsolete_and_mirror_tab(extension_root, old_manifest, new_manifest):
    """Mirror P13.tab/lib/hooks cleanly while preserving local user configs in active tools."""
    ext_abs = os.path.abspath(to_text(extension_root))
    new_files_lower, new_dirs_lower, bundle_leaf_map = _build_new_tree_indexes(new_manifest)
    old_files_lower = set(to_text(p).lower() for p in (old_manifest or []))

    # 1. Explicit legacy obsolete paths
    for rel_obs in OBSOLETE_RELATIVE_PATHS:
        obs_abs = os.path.abspath(os.path.join(ext_abs, to_text(rel_obs)))
        if obs_abs.lower().startswith(ext_abs.lower()) and obs_abs != ext_abs:
            try:
                remove_tree_fast(obs_abs)
            except Exception:
                pass

    # 2. Manifest Diff for root-level files outside MIRRORED_TOP_DIRS
    if old_files_lower:
        removed_rels = old_files_lower - new_files_lower
        for rel_lower in sorted(removed_rels, reverse=True):
            if rel_lower.startswith(".git/") or rel_lower == ".git":
                continue
            target_abs = os.path.abspath(os.path.join(ext_abs, rel_lower.replace("/", os.sep)))
            if target_abs.lower().startswith(ext_abs.lower()) and target_abs != ext_abs:
                _delete_or_rename_locked_file(target_abs)
                _prune_empty_parents(os.path.dirname(target_abs), ext_abs)

    # 3. Direct Directory Mirroring for P13.tab, lib, and hooks (works even with no prior manifest!)
    ignored_names = (VERSION_MARKER_FILE, LOCAL_DEV_LOCK_FILE, ACTIVE_UPDATE_LOCK_FILE)
    for top_folder in MIRRORED_TOP_DIRS:
        top_abs = os.path.join(ext_abs, top_folder)
        if not os.path.isdir(win_long_path(top_abs)):
            continue

        for root_dir, dir_names, file_names in os.walk(win_long_path(top_abs), topdown=False):
            clean_root = strip_long_path(root_dir)
            base_folder_name = os.path.basename(clean_root)
            if base_folder_name == ".git":
                continue

            # Clean __pycache__ automatically if parent bundle was removed
            rel_dir_posix = os.path.relpath(clean_root, ext_abs).replace("\\", "/")
            rel_dir_lower = rel_dir_posix.lower()

            for fname in file_names:
                if fname in ignored_names or LOCKED_SUFFIX_MARKER in fname:
                    continue
                file_abs = os.path.join(clean_root, fname)
                rel_file_posix = (fname if rel_dir_posix == "." else (rel_dir_posix + "/" + fname))
                rel_file_lower = rel_file_posix.lower()

                if rel_file_lower in new_files_lower:
                    continue

                fname_lower = fname.lower()
                is_user_cfg = (
                    fname_lower.endswith(USER_CONFIG_EXTS)
                    and fname_lower not in SYSTEM_CONFIG_FILENAMES
                )
                was_github_tracked = rel_file_lower in old_files_lower
                parent_still_active = rel_dir_lower in new_dirs_lower

                # Keep user's runtime config files untouched inside active buttons!
                if is_user_cfg and (not was_github_tracked) and parent_still_active:
                    continue

                # Keep .pyc cache inside active folders so startup stays fast
                if fname_lower.endswith(".pyc") and (
                    parent_still_active or (
                        base_folder_name == "__pycache__"
                        and os.path.dirname(rel_dir_lower) in new_dirs_lower
                    )
                ):
                    continue

                # If button was moved/retired and has user config, back up & auto-relocate before deleting!
                if is_user_cfg:
                    _backup_and_relocate_user_config(ext_abs, file_abs, rel_file_posix, bundle_leaf_map)

                _delete_or_rename_locked_file(file_abs)

            _prune_empty_parents(clean_root, ext_abs)


# ------------------------------------------------------------------------------
# ZERO-RATE-LIMIT DOWNLOADER & MAIN SYNC CONTROLLER
# ------------------------------------------------------------------------------
def download_zip_archive(target_sha, dest_zip_path, pb=None):
    """Download ZIP from GitHub CDN (0 API quota!) first, with API zipball fallback."""
    candidate_urls = []
    if target_sha:
        candidate_urls.append(CODELOAD_ZIP_SHA_TPL.format(target_sha))
        candidate_urls.append(GITHUB_ARCHIVE_SHA_TPL.format(target_sha))
        candidate_urls.append(GITHUB_API_ZIP_SHA_TPL.format(target_sha))
    else:
        candidate_urls.append(CODELOAD_ZIP_BRANCH_URL)

    last_err = None
    for url in candidate_urls:
        try:
            if http_download_stream(url, dest_zip_path, timeout_sec=45, pb=pb):
                if os.path.isfile(win_long_path(dest_zip_path)) and os.path.getsize(win_long_path(dest_zip_path)) > 512:
                    return
        except Exception as exc:
            last_err = exc
            write_sync_log(u"Download mirror failed ({}): {}".format(url, exc))

    raise RuntimeError("All GitHub download mirrors failed. Last error: {}".format(last_err))


def execute_sync(force_reinstall=False):
    dest_path = get_extension_root()

    # 1. Per-PC Developer Guard Lock
    if is_dev_guard_locked(dest_path):
        forms.alert(
            "Developer Guard is enabled on this PC.\n"
            "Cloud Sync is locked to protect your local development repository.\n\n"
            "Tip: Shift+Click the Update button to toggle Developer Guard off if needed.",
            title="P13 Sync (Developer Guard)"
        )
        return

    # 2. Multi-Revit Concurrent Update Guard
    lock_acquired, lock_pid, lock_age = acquire_update_process_lock(dest_path)
    if not lock_acquired:
        forms.alert(
            "Another Autodesk Revit window (PID: {}, started {}s ago) is currently updating P13.extension.\n\n"
            "Please wait for that update to finish, then click Reload in pyRevit.".format(lock_pid, lock_age),
            title="P13 Sync (Update in Progress)",
            warn_icon=True
        )
        return

    try:
        # 3. Smart Git Worktree Check
        dev_warning = detect_unpushed_dev_work(dest_path)
        if dev_warning:
            proceed_anyway = forms.alert(
                u"{}\n\n"
                u"Updating from GitHub will overwrite modified files in P13.extension.\n"
                u"Do you want to overwrite local changes and update anyway?".format(dev_warning),
                title="P13 Sync - Local Changes Detected",
                yes=True,
                no=True,
                warn_icon=True
            )
            if not proceed_anyway:
                return

        purge_old_locked_trash(dest_path)

        status, local_sha, remote_sha, remote_info = compute_sync_status(
            dest_path, allow_network=True, force_network=True
        )

        if not remote_sha:
            forms.alert(
                "Could not connect to GitHub (both REST API and Atom Feed were unreachable).\n"
                "Please check your internet or corporate proxy connection and try again.",
                title="P13 Sync (Connection Error)",
                warn_icon=True
            )
            return

        if not force_reinstall and status == STATUS_LATEST:
            refresh_live_ribbon_button(STATUS_LATEST, local_sha, remote_sha)
            forms.toast(
                "Installed version ({}) already matches GitHub main.".format(local_sha[:8]),
                title="P13.extension is Up to Date"
            )
            return

        commits_list = fetch_changelog_commits(local_sha, remote_sha)
        action_mode = show_update_confirmation_dialog(
            local_sha, remote_sha, remote_info, commits_list, is_force=force_reinstall
        )
        if not action_mode:
            return

        temp_root = to_text(os.environ.get("TEMP") or os.environ.get("TMP") or dest_path)
        token = u"{}_{}".format(os.getpid(), int(time.time()))
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
                cleanup_obsolete_and_mirror_tab(dest_path, old_manifest, new_manifest)

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

        changed_count = stats.get("updated", 0) + stats.get("renamed_aside", 0)
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

        # Handle 'Update Only (Reload Later)' cleanly without interrupting active work
        if action_mode == "later":
            refresh_live_ribbon_button(STATUS_LATEST, remote_sha, remote_sha, pending_reload=True)
            forms.toast(
                u"Updated {} file(s) to {}. Changes will load on next pyRevit Reload or Revit restart.".format(
                    changed_count, remote_sha[:8]
                ),
                title="P13.extension Updated (Reload Later)"
            )
            return

        if not skipped_files:
            forms.toast(
                u"Updated {} file(s) ({} unchanged) to commit {}.".format(
                    changed_count,
                    stats.get("unchanged", 0),
                    remote_sha[:8]
                ),
                title="P13.extension Updated"
            )
    finally:
        release_update_process_lock(dest_path)

    # Reload pyRevit AFTER releasing process lock
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
    locked_now = is_dev_guard_locked(ext_root)
    toggle_label = (
        "5. Disable Developer Guard on This PC (Currently: ON)"
        if locked_now else
        "5. Enable Developer Guard on This PC (Protect Local Dev Code)"
    )

    options = [
        "1. Force Re-Sync & Repair All Files from GitHub",
        "2. View Recent GitHub Commits (Changelog)",
        "3. Open Diagnostic Sync Log",
        "4. Reset Remote Status Cache & Clear Stuck Lock",
        toggle_label,
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
        remove_tree_fast(get_temp_path(REMOTE_CACHE_FILE))
        release_update_process_lock(ext_root)
        forms.toast("Cleared GitHub status cache and process lock.", title="P13 Sync")
    elif picked.startswith("5."):
        new_state = not locked_now
        set_dev_guard_locked(new_state)
        state_txt = "ENABLED (Cloud Sync locked on this PC)" if new_state else "DISABLED (Cloud Sync allowed)"
        refresh_live_ribbon_button(STATUS_UNKNOWN, local_sha, u"")
        forms.alert(
            "Developer Guard is now {}.\n\nLock file path:\n{}".format(
                state_txt, get_machine_dev_lock_path()
            ),
            title="P13 Developer Guard"
        )


def main():
    is_shift = bool(getattr(EXEC_PARAMS, "config_mode", False)) or bool(globals().get("__shiftclick__", False))
    if is_shift:
        run_shift_click_menu()
    else:
        execute_sync(force_reinstall=False)


if __name__ == "__main__":
    main()