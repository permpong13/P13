# -*- coding: utf-8 -*-
from __future__ import print_function

import os

from pyrevit.api import AdWindows


ADMIN_USERS = ["Permpong13"]
TAB_TITLE = "P13"
PANEL_TITLE = "A-Sync"


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


hide_admin_sync_panel()
