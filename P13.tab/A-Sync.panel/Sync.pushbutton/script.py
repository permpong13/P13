# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import shutil
import urllib2
import zipfile

from pyrevit.loader import sessionmgr
try:
    from pyrevit import HOST_APP
except Exception:
    HOST_APP = None


USER_REPO = "Permpong13/P13"
GITHUB_API_URL = "https://api.github.com/repos/{}/zipball/main".format(USER_REPO)
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


def __selfinit__(script_cmp, ui_button_cmp, __rvt__):
    if is_admin_user():
        hide_ribbon_button(ui_button_cmp)
        return False
    return True


def find_extension_root(start_path):
    current_path = start_path
    while not os.path.basename(current_path).startswith("P13.extension"):
        parent_path = os.path.dirname(current_path)
        if parent_path == current_path:
            break
        current_path = parent_path
    return current_path


def sync_tools():
    if is_admin_user():
        print("Admin mode: sync update is hidden for this user.")
        return

    current_path = os.path.dirname(os.path.abspath(__file__))
    dest_path = find_extension_root(current_path)

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
