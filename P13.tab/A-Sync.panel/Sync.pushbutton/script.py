# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import json
import shutil
import stat
import subprocess
import time
import traceback
import zipfile

try:
    import urllib2
except ImportError:
    # IronPython 3 exposes the Python 3 module name instead of urllib2.
    from urllib import request as urllib2

from pyrevit.coreutils import ribbon
from pyrevit.loader import sessionmgr
from pyrevit import forms
try:
    from pyrevit import HOST_APP
except Exception:
    HOST_APP = None


USER_REPO = "Permpong13/P13"
GITHUB_API_URL = "https://api.github.com/repos/{}/zipball/main".format(USER_REPO)
GITHUB_COMMIT_API_URL = "https://api.github.com/repos/{}/commits/main".format(USER_REPO)
VERSION_MARKER_FILE = ".p13_sync_version"
REMOTE_CACHE_FILE = "P13_sync_remote_status.json"
REMOTE_CACHE_SECONDS = 300
FILE_OPERATION_RETRIES = 12
FILE_OPERATION_RETRY_SECONDS = 0.75
SYNC_LOG_FILE = "P13_sync_error.log"
HTTP_USER_AGENT = "P13-pyRevit-Sync/1.0 (+https://github.com/{})".format(USER_REPO)
STATUS_LATEST = "latest"
STATUS_OUTDATED = "outdated"
STATUS_UNKNOWN = "unknown"
STATUS_ICONS = {
    STATUS_LATEST: "icon.latest.png",
    STATUS_OUTDATED: "icon.outdated.png",
    STATUS_UNKNOWN: "icon.unknown.png",
}
OBSOLETE_RELATIVE_PATHS = [
    os.path.join(
        "P13.tab",
        "Import_Export.panel",
        "SheetTools.stack",
        "CopySheets.pushbutton"
    ),
    os.path.join(
        "P13.tab",
        "Import_Export.panel",
        "SheetTools.stack",
        "Sheet_from_Excel.pushbutton"
    ),
    os.path.join(
        "P13.tab",
        "Import_Export.panel",
        "SheetTools.stack"
    ),
]
PRIVATE_SETTING_MIGRATIONS = [
    (
        os.path.join(
            "P13.tab", "Manager.panel", "SuperSheet.pushbutton",
            "p13_supersheet_config.json"
        ),
        os.path.join("SuperSheet", "profiles.json"),
    ),
    (
        os.path.join(
            "P13.tab", "Manager.panel", "SuperSheet.pushbutton",
            "p13_last_settings.json"
        ),
        os.path.join("SuperSheet", "last_settings.json"),
    ),
    (
        os.path.join(
            "P13.tab", "Manager.panel", "SuperSheet.pushbutton",
            "Google_profiles_backup.json"
        ),
        os.path.join("SuperSheet", "Legacy", "Google_profiles_backup.json"),
    ),
    (
        os.path.join(
            "P13.tab", "Manager.panel", "SuperSheet.pushbutton", "OHM2.json"
        ),
        os.path.join("SuperSheet", "Legacy", "OHM2.json"),
    ),
    (
        os.path.join(
            "P13.tab", "Manager.panel", "SuperSheet.pushbutton", "OHM COCO.xml"
        ),
        os.path.join("SuperSheet", "Legacy", "OHM COCO.xml"),
    ),
    (
        os.path.join(
            "P13.tab", "Manager.panel", "SuperSheet.pushbutton", "profiles.json"
        ),
        os.path.join("SuperSheet", "Legacy", "profiles.json"),
    ),
]
def get_current_username():
    return (os.environ.get("USERNAME") or os.environ.get("USER") or "").strip()


def get_current_user_keys():
    keys = set()

    username = get_current_username()
    if username:
        keys.add(username.lower())

    userdomain = (os.environ.get("USERDOMAIN") or "").strip()
    if userdomain and username:
        keys.add("{}\\{}".format(userdomain, username).lower())

    userprofile = (os.environ.get("USERPROFILE") or "").strip()
    if userprofile:
        profile_name = os.path.basename(userprofile)
        if profile_name:
            keys.add(profile_name.lower())

    try:
        revit_username = (HOST_APP.username or "").strip() if HOST_APP else ""
        if revit_username:
            keys.add(revit_username.lower())
    except Exception:
        pass

    return keys


def is_admin_user():
    # Treat source checkouts as development installations without publishing a
    # developer's Windows username or domain. Release packages omit .git.
    return os.path.isdir(os.path.join(get_extension_root(), ".git"))


def hide_ribbon_button(ui_button_cmp):
    for attr_name in ["Visible", "visible", "Enabled", "enabled"]:
        try:
            if hasattr(ui_button_cmp, attr_name):
                setattr(ui_button_cmp, attr_name, False)
        except Exception:
            pass

    for nested_attr in ["ui_item", "control", "button"]:
        try:
            nested_item = getattr(ui_button_cmp, nested_attr, None)
            if nested_item and hasattr(nested_item, "Visible"):
                nested_item.Visible = False
            if nested_item and hasattr(nested_item, "Enabled"):
                nested_item.Enabled = False
        except Exception:
            pass


def find_extension_root(start_path):
    current_path = start_path
    while not os.path.basename(current_path).startswith("P13.extension"):
        parent_path = os.path.dirname(current_path)
        if parent_path == current_path:
            break
        current_path = parent_path
    return current_path


def get_extension_root():
    current_path = os.path.dirname(os.path.abspath(__file__))
    return find_extension_root(current_path)


def get_temp_path(file_name):
    temp_dir = os.environ.get("TEMP") or os.environ.get("TMP") or get_extension_root()
    return os.path.join(temp_dir, file_name)


def write_sync_log(message):
    log_path = get_temp_path(SYNC_LOG_FILE)
    try:
        with open(log_path, "a") as log_file:
            log_file.write("\n[{0}]\n{1}\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except Exception:
        pass
    return log_path


def report_sync_error(message, exception):
    details = "{0}\n{1}\n{2}".format(message, exception, traceback.format_exc())
    log_path = write_sync_log(details)
    print("{0} Log: {1}".format(message, log_path))
    exception_text = str(exception).strip()
    if len(exception_text) > 240:
        exception_text = exception_text[:237] + "..."
    try:
        forms.alert(
            "{0}\n\nReason: {1}\n\nDiagnostic log: {2}".format(
                message,
                exception_text or "Unknown error",
                log_path,
            ),
            title="P13 Sync",
            warn_icon=True,
        )
    except Exception:
        pass


def get_json_from_url(url, timeout=5):
    request = urllib2.Request(url)
    request.add_header("User-Agent", HTTP_USER_AGENT)
    request.add_header("Accept", "application/vnd.github+json")
    response = None
    try:
        response = urllib2.urlopen(request, timeout=timeout)
        return json.loads(response.read())
    finally:
        if response is not None:
            response.close()


def get_cached_remote_sha(allow_network=True):
    cache_path = get_temp_path(REMOTE_CACHE_FILE)
    try:
        if os.path.exists(cache_path):
            age_seconds = time.time() - os.path.getmtime(cache_path)
            if age_seconds <= REMOTE_CACHE_SECONDS:
                with open(cache_path, "r") as cache_file:
                    cached_data = json.load(cache_file)
                cached_sha = (cached_data.get("sha") or "").strip()
                if cached_sha:
                    return cached_sha
    except Exception:
        pass

    if not allow_network:
        return ""

    try:
        remote_data = get_json_from_url(GITHUB_COMMIT_API_URL)
        remote_sha = (remote_data.get("sha") or "").strip()
        if remote_sha:
            try:
                with open(cache_path, "w") as cache_file:
                    json.dump({"repo": USER_REPO, "sha": remote_sha, "checked_at": time.time()}, cache_file)
            except Exception:
                pass
        return remote_sha
    except Exception:
        return ""


def get_local_git_sha(extension_root):
    git_path = os.path.join(extension_root, ".git")
    if not os.path.exists(git_path):
        return ""

    try:
        process = subprocess.Popen(
            ["git", "-C", extension_root, "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout_data, _ = process.communicate()
        if process.returncode == 0:
            return stdout_data.strip()
    except Exception:
        pass

    return ""


def get_version_marker_path(extension_root):
    return os.path.join(extension_root, VERSION_MARKER_FILE)


def read_marker_sha(extension_root):
    marker_path = get_version_marker_path(extension_root)
    if not os.path.exists(marker_path):
        return ""

    try:
        with open(marker_path, "r") as marker_file:
            marker_data = json.load(marker_file)
        return (marker_data.get("sha") or "").strip()
    except Exception:
        try:
            with open(marker_path, "r") as marker_file:
                return marker_file.read().strip()
        except Exception:
            return ""


def write_marker_sha(extension_root, remote_sha):
    if not remote_sha:
        return

    marker_data = {
        "repo": USER_REPO,
        "branch": "main",
        "sha": remote_sha,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        with open(get_version_marker_path(extension_root), "w") as marker_file:
            json.dump(marker_data, marker_file, indent=2)
    except Exception:
        pass


def cleanup_obsolete_paths(extension_root):
    extension_root = os.path.abspath(extension_root)

    for relative_path in OBSOLETE_RELATIVE_PATHS:
        target_path = os.path.abspath(os.path.join(extension_root, relative_path))
        if not target_path.startswith(extension_root):
            continue

        try:
            if os.path.isdir(target_path):
                shutil.rmtree(target_path)
            elif os.path.isfile(target_path):
                os.remove(target_path)
        except Exception:
            pass


def migrate_private_settings(extension_root):
    """Preserve legacy user data before replacing the extension directory."""
    appdata_path = os.environ.get("APPDATA") or os.path.expanduser("~")
    private_root = os.path.join(appdata_path, "pyRevit", "P13")
    for relative_source, relative_target in PRIVATE_SETTING_MIGRATIONS:
        source_path = os.path.join(extension_root, relative_source)
        target_path = os.path.join(private_root, relative_target)
        if not os.path.isfile(source_path) or os.path.isfile(target_path):
            continue
        target_directory = os.path.dirname(target_path)
        if not os.path.isdir(target_directory):
            os.makedirs(target_directory)
        shutil.copy2(source_path, target_path)


def get_local_sha(extension_root):
    return read_marker_sha(extension_root) or get_local_git_sha(extension_root)


def get_update_status(extension_root, allow_network=True):
    remote_sha = get_cached_remote_sha(allow_network=allow_network)
    local_sha = get_local_sha(extension_root)

    if not remote_sha:
        return STATUS_UNKNOWN, local_sha, remote_sha

    if not local_sha:
        return STATUS_OUTDATED, local_sha, remote_sha

    if local_sha.lower() == remote_sha.lower():
        return STATUS_LATEST, local_sha, remote_sha

    return STATUS_OUTDATED, local_sha, remote_sha


def get_bitmap_source(icon_path):
    try:
        from System import Uri
        from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption

        bitmap = BitmapImage()
        bitmap.BeginInit()
        bitmap.CacheOption = BitmapCacheOption.OnLoad
        bitmap.UriSource = Uri(icon_path)
        bitmap.EndInit()
        bitmap.Freeze()
        return bitmap
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


def set_ribbon_icon(script_cmp, ui_button_cmp, icon_path):
    if not os.path.exists(icon_path):
        return False

    for target in [ui_button_cmp, script_cmp]:
        for method_name in ["set_icon", "set_icon_file", "set_icon_path"]:
            try:
                method = getattr(target, method_name, None)
                if method:
                    try:
                        method(icon_path, icon_size=ribbon.ICON_LARGE)
                    except TypeError:
                        method(icon_path)
                    return True
            except Exception:
                pass

    bitmap = get_bitmap_source(icon_path)
    if not bitmap:
        return False

    changed = False
    for target in get_ribbon_targets(ui_button_cmp):
        for attr_name in ["LargeImage", "Image"]:
            try:
                if hasattr(target, attr_name):
                    setattr(target, attr_name, bitmap)
                    changed = True
            except Exception:
                pass

    return changed


def set_ribbon_tooltip(ui_button_cmp, status, local_sha, remote_sha):
    if status == STATUS_LATEST:
        status_text = "P13.extension is up to date."
    elif status == STATUS_OUTDATED:
        status_text = "P13.extension update is available."
    else:
        status_text = "P13.extension update status could not be checked."

    local_label = local_sha[:12] if local_sha else "not recorded"
    remote_label = remote_sha[:12] if remote_sha else "not available"
    tooltip_text = "{}\nLocal: {}\nLatest: {}".format(status_text, local_label, remote_label)

    for target in get_ribbon_targets(ui_button_cmp):
        for attr_name in ["ToolTip", "tooltip"]:
            try:
                if hasattr(target, attr_name):
                    setattr(target, attr_name, tooltip_text)
            except Exception:
                pass


def set_status_icon(script_cmp, ui_button_cmp, status):
    current_path = os.path.dirname(os.path.abspath(__file__))
    icon_name = STATUS_ICONS.get(status, STATUS_ICONS[STATUS_UNKNOWN])
    try:
        icon_path = script_cmp.get_bundle_file(icon_name)
    except Exception:
        icon_path = os.path.join(current_path, icon_name)
    return set_ribbon_icon(script_cmp, ui_button_cmp, icon_path)


def __selfinit__(script_cmp, ui_button_cmp, __rvt__):
    if is_admin_user():
        hide_ribbon_button(ui_button_cmp)
        return False

    extension_root = get_extension_root()
    # Do not perform a network request while Revit is loading the ribbon.
    # A cached result is still used when available; the explicit Sync command
    # performs the live GitHub check.
    status, local_sha, remote_sha = get_update_status(extension_root, allow_network=False)
    set_status_icon(script_cmp, ui_button_cmp, status)
    set_ribbon_tooltip(ui_button_cmp, status, local_sha, remote_sha)
    return True


def get_extracted_extension_root(temp_dir):
    extracted_roots = [
        os.path.join(temp_dir, item_name)
        for item_name in os.listdir(temp_dir)
        if os.path.isdir(os.path.join(temp_dir, item_name))
    ]

    if len(extracted_roots) != 1:
        raise RuntimeError("The downloaded update has an invalid folder structure.")

    extracted_root = extracted_roots[0]
    required_paths = [
        os.path.join(extracted_root, "extension.json"),
        os.path.join(extracted_root, "P13.tab"),
    ]
    if not all(os.path.exists(required_path) for required_path in required_paths):
        raise RuntimeError("The downloaded update is not a valid P13.extension package.")

    return extracted_root


def remove_readonly_path(function, target_path, exception_info):
    try:
        os.chmod(target_path, stat.S_IWRITE)
        function(target_path)
    except Exception:
        raise exception_info[1]


def remove_path_with_retries(target_path):
    if not os.path.exists(target_path):
        return

    for attempt in range(FILE_OPERATION_RETRIES):
        try:
            if os.path.isdir(target_path):
                shutil.rmtree(target_path, onerror=remove_readonly_path)
            else:
                os.chmod(target_path, stat.S_IWRITE)
                os.remove(target_path)
            return
        except Exception:
            if attempt == FILE_OPERATION_RETRIES - 1:
                raise
            time.sleep(FILE_OPERATION_RETRY_SECONDS * (attempt + 1))


def move_path_with_retries(source_path, target_path):
    for attempt in range(FILE_OPERATION_RETRIES):
        try:
            # Both paths are siblings, so rename is atomic and never falls back
            # to a partial copy/delete operation when Windows denies access.
            os.rename(source_path, target_path)
            return
        except Exception:
            if attempt == FILE_OPERATION_RETRIES - 1:
                raise
            time.sleep(FILE_OPERATION_RETRY_SECONDS * (attempt + 1))


def prepare_staging_extension(extracted_root, staging_path):
    remove_path_with_retries(staging_path)
    shutil.copytree(extracted_root, staging_path)


def replace_extension(staging_path, dest_path, backup_path):
    remove_path_with_retries(backup_path)

    old_extension_moved = False
    try:
        if os.path.exists(dest_path):
            move_path_with_retries(dest_path, backup_path)
            old_extension_moved = True

        move_path_with_retries(staging_path, dest_path)
    except Exception:
        try:
            if old_extension_moved and os.path.exists(backup_path):
                if os.path.exists(dest_path):
                    remove_path_with_retries(dest_path)
                move_path_with_retries(backup_path, dest_path)
        except Exception as rollback_error:
            print("Update rollback error: {}".format(rollback_error))
        raise

    if os.path.exists(backup_path):
        try:
            remove_path_with_retries(backup_path)
        except Exception as cleanup_error:
            print("Update cleanup warning: {}".format(cleanup_error))


def sync_tools():
    if is_admin_user():
        print("Admin mode: sync update is hidden for this user.")
        return

    current_path = os.path.dirname(os.path.abspath(__file__))
    dest_path = find_extension_root(current_path)
    remote_sha = get_cached_remote_sha()

    temp_root = os.environ.get("TEMP") or os.environ.get("TMP")
    if not temp_root:
        print("Update error: A temporary folder could not be found.")
        return

    temp_zip = os.path.join(temp_root, "P13_update.zip")
    temp_dir = os.path.join(temp_root, "P13_temp_extract")
    extension_parent = os.path.dirname(dest_path)
    staging_path = os.path.join(extension_parent, "P13.update-staging")
    backup_path = os.path.join(extension_parent, "P13.update-backup")

    update_completed = False
    try:
        remove_path_with_retries(temp_dir)
        if os.path.exists(temp_zip):
            remove_path_with_retries(temp_zip)

        request = urllib2.Request(GITHUB_API_URL)
        request.add_header("User-Agent", HTTP_USER_AGENT)
        request.add_header("Accept", "application/vnd.github+json")
        response = urllib2.urlopen(request, timeout=30)
        try:
            with open(temp_zip, "wb") as zip_file:
                zip_file.write(response.read())
        finally:
            response.close()

        with zipfile.ZipFile(temp_zip, "r") as zip_ref:
            invalid_file = zip_ref.testzip()
            if invalid_file:
                raise RuntimeError("The downloaded update archive is corrupted.")
            zip_ref.extractall(temp_dir)

        extracted_folder = get_extracted_extension_root(temp_dir)
        prepare_staging_extension(extracted_folder, staging_path)
        migrate_private_settings(dest_path)
        replace_extension(staging_path, dest_path, backup_path)
        write_marker_sha(dest_path, remote_sha)
        update_completed = True

    except Exception as exc:
        report_sync_error("Update failed.", exc)

    finally:
        try:
            if os.path.exists(temp_zip):
                remove_path_with_retries(temp_zip)
            if os.path.exists(temp_dir):
                remove_path_with_retries(temp_dir)
        except Exception:
            pass

    if not update_completed:
        return

    try:
        sessionmgr.reload_pyrevit()
    except Exception as exc:
        log_path = write_sync_log(
            "Update completed, but pyRevit reload failed.\n{0}\n{1}".format(
                exc,
                traceback.format_exc(),
            )
        )
        print(
            "Update completed. Reload pyRevit manually. Log: {0}".format(log_path)
        )


if __name__ == "__main__":
    sync_tools()
