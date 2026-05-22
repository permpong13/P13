# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import shutil
import urllib2
import zipfile

from pyrevit.loader import sessionmgr


USER_REPO = "Permpong13/P13"
GITHUB_API_URL = "https://api.github.com/repos/{}/zipball/main".format(USER_REPO)
ADMIN_USERS = ["Permpong13"]


def get_current_username():
    return (os.environ.get("USERNAME") or os.environ.get("USER") or "").strip()


def is_admin_user():
    current_user = get_current_username().lower()
    return current_user in [name.lower() for name in ADMIN_USERS]


def __selfinit__(script_cmp, ui_button_cmp, __rvt__):
    return not is_admin_user()


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
