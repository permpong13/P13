# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import json
import shutil
import subprocess
import time
import urllib2
import zipfile

from pyrevit.coreutils import ribbon
from pyrevit.loader import sessionmgr
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
]
ADMIN_USERS = [
    "Permpong13",
    "TEE\\Permpong13",
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
    current_keys = get_current_user_keys()
    admin_keys = set([name.lower() for name in ADMIN_USERS])
    return bool(current_keys.intersection(admin_keys))


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


def get_json_from_url(url, timeout=5):
    response = urllib2.urlopen(url, timeout=timeout)
    return json.loads(response.read())


def get_cached_remote_sha():
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


def get_local_sha(extension_root):
    return read_marker_sha(extension_root) or get_local_git_sha(extension_root)


def get_update_status(extension_root):
    remote_sha = get_cached_remote_sha()
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
    status, local_sha, remote_sha = get_update_status(extension_root)
    set_status_icon(script_cmp, ui_button_cmp, status)
    set_ribbon_tooltip(ui_button_cmp, status, local_sha, remote_sha)
    return True


def sync_tools():
    if is_admin_user():
        print("Admin mode: sync update is hidden for this user.")
        return

    current_path = os.path.dirname(os.path.abspath(__file__))
    dest_path = find_extension_root(current_path)
    remote_sha = get_cached_remote_sha()

    temp_zip = os.path.join(os.environ["TEMP"], "P13_update.zip")
    temp_dir = os.path.join(os.environ["TEMP"], "P13_temp_extract")

    try:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

        response = urllib2.urlopen(GITHUB_API_URL)
        with open(temp_zip, "wb") as zip_file:
            zip_file.write(response.read())

        with zipfile.ZipFile(temp_zip, "r") as zip_ref:
            zip_ref.extractall(temp_dir)

        extracted_folder = os.path.join(temp_dir, os.listdir(temp_dir)[0])

        for root, dirs, files in os.walk(extracted_folder):
            rel_path = os.path.relpath(root, extracted_folder)
            target_dir = os.path.join(dest_path, rel_path)

            if not os.path.exists(target_dir):
                os.makedirs(target_dir)

            for file_name in files:
                src_file = os.path.join(root, file_name)
                dst_file = os.path.join(target_dir, file_name)
                try:
                    shutil.copy2(src_file, dst_file)
                except Exception:
                    continue

        cleanup_obsolete_paths(dest_path)
        write_marker_sha(dest_path, remote_sha)
        sessionmgr.reload_pyrevit()

    except Exception as exc:
        print("Update error: {}".format(exc))

    finally:
        try:
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
        except Exception:
            pass


if __name__ == "__main__":
    sync_tools()
