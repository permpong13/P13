# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import shutil
import sys

from pyrevit.api import AdWindows


TAB_TITLE = "P13"
PANEL_TITLE = "A-Sync"
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
def get_current_username():
    return (os.environ.get("USERNAME") or os.environ.get("USER") or "").strip()


def is_admin_user():
    # A Git checkout is a development installation. Release packages do not
    # contain .git, so end users retain the normal update controls without a
    # hardcoded developer username or Windows domain in public source code.
    extension_root = find_extension_root(os.path.dirname(os.path.abspath(__file__)))
    return os.path.isdir(os.path.join(extension_root, ".git"))


def hide_admin_sync_panel():
    if not is_admin_user():
        return

    ribbon = AdWindows.ComponentManager.Ribbon
    if not ribbon:
        return

    for tab in ribbon.Tabs:
        if tab.Title != TAB_TITLE:
            continue

        for panel in tab.Panels:
            try:
                panel_title = panel.Source.Title
            except Exception:
                panel_title = ""

            if panel_title == PANEL_TITLE:
                panel.IsVisible = False
                return


def find_extension_root(start_path):
    current_path = os.path.abspath(start_path)
    while not os.path.basename(current_path).startswith("P13.extension"):
        parent_path = os.path.dirname(current_path)
        if parent_path == current_path:
            break
        current_path = parent_path
    return current_path


def cleanup_obsolete_paths():
    extension_root = find_extension_root(os.path.dirname(os.path.abspath(__file__)))

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


def ensure_extension_lib_path():
    extension_root = find_extension_root(os.path.dirname(os.path.abspath(__file__)))
    library_path = os.path.join(extension_root, "lib")
    if os.path.isdir(library_path) and library_path not in sys.path:
        sys.path.insert(0, library_path)


cleanup_obsolete_paths()
hide_admin_sync_panel()
ensure_extension_lib_path()
