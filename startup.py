# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import shutil

from pyrevit.api import AdWindows


ADMIN_USERS = ["Permpong13"]
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
    current_user = get_current_username().lower()
    return current_user in [name.lower() for name in ADMIN_USERS]


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


cleanup_obsolete_paths()
hide_admin_sync_panel()
