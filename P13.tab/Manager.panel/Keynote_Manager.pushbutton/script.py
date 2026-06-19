# -*- coding: utf-8 -*-
"""P13 Keynote Manager.

Features:
- Single hierarchical tree (no separate category sidebar)
- Indent / Outdent to promote or demote nodes (Tab / Shift+Tab)
- Move Up / Move Down to reorder siblings (Ctrl+Up / Ctrl+Down)
- Drag-and-drop to reparent across the tree
- Search with smart filters
- Keyboard shortcuts (F2, F5, Ctrl+N, Ctrl+D, Del, Tab, Shift+Tab)

Shift+Click:
Reset window configurations and open.
"""

__title__ = "Keynote\nManager"
__doc__ = "Manage the active project keynote file in a searchable hierarchy."
__author__ = "P13"

# pylint: disable=E0401,W0613,C0111,C0103,C0302,W0703
# pylint: disable=raise-missing-from
import os
import os.path as op
import shutil
import math
import uuid
import re
import datetime
from collections import defaultdict, OrderedDict
from natsort import natsorted

from pyrevit import HOST_APP
from pyrevit import framework
from pyrevit import coreutils
from pyrevit import revit, DB, UI
from pyrevit import forms
from pyrevit import script

from pyrevit.framework import System, Windows
from System.Windows.Interop import WindowInteropHelper
from System.Diagnostics import Process as SysProcess
from System.Windows.Threading import DispatcherTimer
from System import TimeSpan

from pyrevit.runtime.types import DocumentEventUtils

from pyrevit.interop import adc

import keynotesdb as kdb

__persistentengine__ = True

logger = script.get_logger()
output = script.get_output()

# =============================================================================
# SEARCH HIGHLIGHT CONVERTER
# =============================================================================
from System.Windows.Data import IValueConverter
from System.Windows.Controls import TextBlock, CheckBox, TreeViewItem
from System.Windows.Documents import Run
from System.Windows.Media import Brushes, SolidColorBrush, VisualTreeHelper
from System.Windows import FontWeight, FontWeights
import codecs

class SearchHighlightConverter(IValueConverter):
    def __init__(self, window):
        self.window = window
        self.text_primary = SolidColorBrush(System.Windows.Media.Color.FromRgb(0x1D, 0x1D, 0x1F))
        self.text_muted = SolidColorBrush(System.Windows.Media.Color.FromRgb(0x8E, 0x8E, 0x93))

    def Convert(self, value, targetType, parameter, culture):
        if value is None:
            return None
            
        node = value
        text = node.text or ""
        term = self.window.search_term or ""
        
        tb = TextBlock()
        tb.TextTrimming = System.Windows.TextTrimming.CharacterEllipsis
        tb.TextWrapping = System.Windows.TextWrapping.NoWrap
        
        if node.is_category:
            tb.FontWeight = FontWeights.SemiBold
            tb.FontSize = 14
        else:
            tb.FontSize = 13
            
        if node.locked:
            tb.Foreground = self.text_muted
        else:
            tb.Foreground = self.text_primary
            
        if not term or term.startswith(":"):
            tb.Text = text
            return tb
            
        clean_term = term.lower()
        for f in kdb.RKeynoteFilters.get_available_filters():
            clean_term = clean_term.replace(f.code, "").strip()
            
        if not clean_term:
            tb.Text = text
            return tb
            
        idx = text.lower().find(clean_term)
        if idx == -1:
            tb.Text = text
            return tb
            
        before = text[:idx]
        match = text[idx:idx+len(clean_term)]
        after = text[idx+len(clean_term):]
        
        if before:
            tb.Inlines.Add(Run(before))
            
        run_match = Run(match)
        run_match.Background = Brushes.Yellow
        run_match.FontWeight = FontWeights.Bold
        tb.Inlines.Add(run_match)
        
        if after:
            tb.Inlines.Add(Run(after))
            
        return tb

    def ConvertBack(self, value, targetType, parameter, culture):
        return None


# =============================================================================
# AUTO KEY GENERATOR
# =============================================================================
def suggest_next_key(conn, parent_key):
    """Suggest the next logical child key for a parent key based on existing children."""
    if not parent_key:
        return ""
    try:
        children = [k for k in kdb.get_keynotes(conn) if k.parent_key == parent_key]
    except Exception:
        children = []
        
    if not children:
        return "{}-01".format(parent_key)
        
    sibling_keys = [c.key for c in children]
    sorted_keys = natsorted(sibling_keys)
    last_key = sorted_keys[-1]
    
    match = re.match(r"^(.*?)(\d+)$", last_key)
    if match:
        prefix, num_str = match.groups()
        width = len(num_str)
        try:
            next_num = int(num_str) + 1
            return "{}{}".format(prefix, str(next_num).zfill(width))
        except ValueError:
            pass
            
    return "{}-{}".format(parent_key, str(len(sibling_keys) + 1).zfill(2))


def _safe_first(collection):
    """Safely get first element from a .NET collection that may not
    support Python [] subscripting (ReadOnlyList, IList, etc.)."""
    if collection is None:
        return None
    # Try normal indexing first (.NET 8 / CPython)
    try:
        return collection[0]
    except TypeError:
        pass
    # Try .Item[] indexer (.NET Framework generic collections)
    try:
        return collection.Item[0]
    except (TypeError, AttributeError):
        pass
    # Fall back to iteration
    try:
        for item in collection:
            return item
    except TypeError:
        pass
    return None


def _patched_get_item(adc_svc, path):
    """Patched version of adc._get_item that handles ReadOnlyList."""
    import os.path as _op

    path = adc._ensure_local_path(adc_svc, path)
    if not _op.isfile(path):
        raise Exception("Path does not point to a file")
    res = adc_svc.GetItemsByWorkspacePaths([path])
    if not res:
        raise Exception("Cannot find item in any ADC drive")
    first = _safe_first(res)
    if first is None:
        raise Exception("ADC returned empty result for path")
    return first.Item


def _patched_get_item_lockstatus(adc_svc, item):
    """Patched version of adc._get_item_lockstatus."""
    res = adc_svc.GetLockStatus([item.Id])
    if res and res.Status:
        return _safe_first(res.Status)
    return None


def _patched_get_item_property_value(adc_svc, drive, item, prop_name):
    """Patched version of adc._get_item_property_value."""
    for prop_def in adc._get_drive_properties(adc_svc, drive):
        if prop_def.DisplayName == prop_name:
            res = adc_svc.GetProperties([item.Id], [prop_def.Id])
            if res:
                return _safe_first(res.Values)
    return None


def _patched_get_item_property_id_value(adc_svc, drive, item, prop_id):
    """Patched version of adc._get_item_property_id_value."""
    for prop_def in adc._get_drive_properties(adc_svc, drive):
        if prop_def.Id == prop_id:
            res = adc_svc.GetProperties([item.Id], [prop_def.Id])
            if res:
                return _safe_first(res.Values)
    return None


# Apply patches (only on .NET Framework, only once per engine session)
if not HOST_APP.is_newer_than("2024") and not getattr(
    adc, "_readonlylist_patched", False
):
    adc._get_item = _patched_get_item
    adc._get_item_lockstatus = _patched_get_item_lockstatus
    adc._get_item_property_value = _patched_get_item_property_value
    adc._get_item_property_id_value = _patched_get_item_property_id_value
    adc._readonlylist_patched = True


# =============================================================================
# EXTERNAL EVENT HANDLER (for modeless window Revit API access)
# =============================================================================
# Modeless WPF windows cannot start Revit transactions directly.
# All write operations (transactions, PostCommand) are queued here and
# executed on Revit's main thread via ExternalEvent.


class RevitActionHandler(UI.IExternalEventHandler):
    """Queues callables and runs them inside Revit's valid API context."""

    def __init__(self):
        self._queue = []

    def queue(self, action, callback=None, window=None):
        """Add an action (and optional WPF-thread callback) to the queue."""
        self._queue.append((action, callback, window))

    def Execute(self, app):
        """Called by Revit on the main thread when the event fires."""
        while self._queue:
            action, callback, window = self._queue.pop(0)
            try:
                action()
            except Exception as ex:
                logger.error("RevitActionHandler | %s" % ex)
                try:
                    if window and window.IsLoaded:
                        window.Dispatcher.Invoke(
                            System.Action(lambda e=str(ex): forms.alert(e))
                        )
                except Exception as disp_ex:
                    logger.debug("Failed to display error in window | %s" % disp_ex)
            if callback:
                try:
                    if window and window.IsLoaded:
                        window.Dispatcher.Invoke(System.Action(callback))
                    else:
                        callback()
                except Exception as cbex:
                    logger.debug("Callback failed | %s" % cbex)

    def GetName(self):
        return "KeynoteManagerHandler"


# Module-level handler + event (persist across window open/close)
_ext_handler = RevitActionHandler()
_ext_event = UI.ExternalEvent.Create(_ext_handler)

# Singleton - only one keynote manager window at a time
_active_window = None


# =============================================================================
# HELPERS
# =============================================================================


def get_keynote_pcommands():
    return list(
        reversed(
            [
                x
                for x in coreutils.get_enum_values(UI.PostableCommand)
                if str(x).endswith("Keynote")
            ]
        )
    )


def _find_siblings(flat_keynotes, target_parent_key):
    """Return natsorted list of keynotes sharing the same parent_key."""
    return natsorted(
        [k for k in flat_keynotes if k.parent_key == target_parent_key],
        key=lambda x: x.key,
    )


def _find_parent_of(all_categories, all_keynotes, child):
    """Find the RKeynote/category object that is the parent of 'child'."""
    pkey = child.parent_key
    if not pkey:
        return None
    for cat in all_categories:
        if cat.key == pkey:
            return cat
    for kn in all_keynotes:
        if kn.key == pkey:
            return kn
    return None


# =============================================================================
# EDIT RECORD WINDOW (unchanged from pyRevit - works with EditRecord.xaml)
# =============================================================================


class EditRecordWindow(forms.WPFWindow):
    """Dialog for adding/editing a single keynote or category record."""

    def __init__(
        self, owner, conn, mode, rkeynote=None, rkey=None, text=None, pkey=None
    ):
        forms.WPFWindow.__init__(self, "EditRecord.xaml")
        self.Owner = owner
        self._res = None
        self._commited = False
        self._reserved_key = None

        self._conn = conn
        self._mode = mode
        self._cat = False
        self._rkeynote = rkeynote
        self._rkey = rkey
        self._text = text
        self._pkey = pkey

        if self._mode == kdb.EDIT_MODE_ADD_CATEG:
            self._cat = True
            self.hide_element(self.recordParentInput)
            self.Title = "Add Group"
            self.recordKeyTitle.Text = "Create a unique group key"
            self.applyChanges.Content = "Add Group"

        elif self._mode == kdb.EDIT_MODE_EDIT_CATEG:
            self._cat = True
            self.hide_element(self.recordParentInput)
            self.Title = "Edit Group"
            self.recordKeyTitle.Text = "Group key (read-only)"
            self.applyChanges.Content = "Save Changes"
            self.recordKey.IsEnabled = False
            if self._rkeynote and self._rkeynote.key:
                kdb.begin_edit(self._conn, self._rkeynote.key, category=True)

        elif self._mode == kdb.EDIT_MODE_ADD_KEYNOTE:
            self.show_element(self.recordParentInput)
            self.Title = "Add Keynote"
            self.recordKeyTitle.Text = "Create a unique keynote key"
            self.applyChanges.Content = "Add Keynote"

        elif self._mode == kdb.EDIT_MODE_EDIT_KEYNOTE:
            self.show_element(self.recordParentInput)
            self.Title = "Edit Keynote"
            self.recordKeyTitle.Text = "Keynote key (read-only)"
            self.applyChanges.Content = "Save Changes"
            self.recordKey.IsEnabled = False
            self.recordParent.IsEnabled = True
            if self._rkeynote and self._rkeynote.key:
                kdb.begin_edit(self._conn, self._rkeynote.key, category=False)

        if self._rkeynote:
            self.active_key = self._rkeynote.key
            self.active_text = self._rkeynote.text
            self.active_parent_key = self._rkeynote.parent_key
        if self._rkey:
            self.active_key = self._rkey
        if self._text:
            self.active_text = self._text
        if self._pkey:
            self.active_parent_key = self._pkey
            if self._mode == kdb.EDIT_MODE_ADD_KEYNOTE:
                self.active_key = suggest_next_key(self._conn, self._pkey)

        if self._mode == kdb.EDIT_MODE_ADD_CATEG:
            try:
                cats = [c.key for c in kdb.get_categories(self._conn)]
                if cats:
                    last_cat = natsorted(cats)[-1]
                    match = re.match(r"^(.*?)(\d+)$", last_cat)
                    if match:
                        prefix, num_str = match.groups()
                        width = len(num_str)
                        self.active_key = "{}{}".format(prefix, str(int(num_str) + 1).zfill(width))
            except Exception:
                pass

        self.recordText.Focus()
        self.recordText.SelectAll()

    @property
    def active_key(self):
        if self.recordKey.Content and "\u25cf" not in self.recordKey.Content:
            return self.recordKey.Content

    @active_key.setter
    def active_key(self, value):
        self.recordKey.Content = value

    @property
    def active_text(self):
        return self.recordText.Text

    @active_text.setter
    def active_text(self, value):
        self.recordText.Text = value.strip()

    @property
    def active_parent_key(self):
        return self.recordParent.Content

    @active_parent_key.setter
    def active_parent_key(self, value):
        self.recordParent.Content = value

    def commit(self):
        if hasattr(self.Owner, "_save_undo_state"):
            self.Owner._save_undo_state()
        if self._mode == kdb.EDIT_MODE_ADD_CATEG:
            if not self.active_key:
                forms.alert("Please provide a unique key.")
                return False
            if not self.active_text.strip():
                forms.alert("Please provide a title.")
                return False
            try:
                self._res = kdb.add_category(
                    self._conn, self.active_key, self.active_text
                )
                kdb.end_edit(self._conn)
            except System.TimeoutException as toutex:
                forms.alert(toutex.Message)
                return False

        elif self._mode == kdb.EDIT_MODE_EDIT_CATEG:
            if not self.active_text:
                forms.alert("Title cannot be empty.")
                return False
            try:
                if self.active_text != self._rkeynote.text:
                    kdb.update_category_title(
                        self._conn, self.active_key, self.active_text
                    )
                kdb.end_edit(self._conn)
            except System.TimeoutException as toutex:
                forms.alert(toutex.Message)
                return False

        elif self._mode == kdb.EDIT_MODE_ADD_KEYNOTE:
            if not self.active_key:
                forms.alert("Please provide a unique key.")
                return False
            if not self.active_text:
                forms.alert("Please provide keynote text.")
                return False
            if not self.active_parent_key:
                forms.alert("Please select a parent.")
                return False
            try:
                self._res = kdb.add_keynote(
                    self._conn,
                    self.active_key,
                    self.active_text,
                    self.active_parent_key,
                )
                kdb.end_edit(self._conn)
            except System.TimeoutException as toutex:
                forms.alert(toutex.Message)
                return False

        elif self._mode == kdb.EDIT_MODE_EDIT_KEYNOTE:
            if not self.active_text:
                forms.alert("Keynote text cannot be empty.")
                return False
            try:
                if self.active_text != self._rkeynote.text:
                    kdb.update_keynote_text(
                        self._conn, self.active_key, self.active_text
                    )
                if self.active_parent_key != self._rkeynote.parent_key:
                    kdb.move_keynote(
                        self._conn, self.active_key, self.active_parent_key
                    )
                kdb.end_edit(self._conn)
            except System.TimeoutException as toutex:
                forms.alert(toutex.Message)
                return False

        return True

    def show(self):
        self.ShowDialog()
        return self._res

    def pick_key(self, sender, args):
        if self._reserved_key:
            try:
                kdb.release_key(self._conn, self._reserved_key, category=self._cat)
            except System.TimeoutException as toutex:
                forms.alert(toutex.Message)
                return
        try:
            categories = kdb.get_categories(self._conn)
            keynotes = kdb.get_keynotes(self._conn)
            locks = kdb.get_locks(self._conn)
        except System.TimeoutException as toutex:
            forms.alert(toutex.Message)
            return
        reserved_keys = [x.key for x in categories]
        reserved_keys.extend([x.key for x in keynotes])
        reserved_keys.extend([x.LockTargetRecordKey for x in locks])
        new_key = forms.ask_for_unique_string(
            prompt="Enter a unique key:",
            title=self.Title,
            reserved_values=reserved_keys,
            owner=self,
        )
        if new_key:
            try:
                kdb.reserve_key(self._conn, new_key, category=self._cat)
            except System.TimeoutException as toutex:
                forms.alert(toutex.Message)
                return
            self._reserved_key = new_key
            self.active_key = new_key

    def pick_parent(self, sender, args):
        categories = kdb.get_categories(self._conn)
        keynotes = kdb.get_keynotes(self._conn)
        available = [x.key for x in categories]
        available.extend([x.key for x in keynotes])
        if self.active_key in available:
            available.remove(self.active_key)
        new_parent = forms.SelectFromList.show(
            natsorted(available), title="Select Parent", multiselect=False
        )
        if new_parent:
            try:
                kdb.reserve_key(self._conn, self.active_key, category=self._cat)
            except System.TimeoutException as toutex:
                forms.alert(toutex.Message)
                return
            self._reserved_key = self.active_key
            self.active_parent_key = new_parent

    def to_upper(self, sender, args):
        self.active_text = self.active_text.upper()

    def to_lower(self, sender, args):
        self.active_text = self.active_text.lower()

    def to_title(self, sender, args):
        self.active_text = self.active_text.title()

    def to_sentence(self, sender, args):
        self.active_text = self.active_text.capitalize()

    def select_template(self, sender, args):
        template = forms.SelectFromList.show(
            ["RESERVED", "DO NOT USE"], title="Select Template", owner=self
        )
        if template:
            self.active_text = template

    def translate(self, sender, args):
        forms.alert("Translation feature coming soon.")

    def apply_changes(self, sender, args):
        self._commited = self.commit()
        if self._commited:
            self.Close()

    def cancel_changes(self, sender, args):
        self.Close()

    def window_closing(self, sender, args):
        if not self._commited:
            if self._reserved_key:
                try:
                    kdb.release_key(self._conn, self._reserved_key, category=self._cat)
                except Exception:
                    pass
            try:
                kdb.end_edit(self._conn)
            except Exception:
                pass


# =============================================================================
# MAIN KEYNOTE MANAGER WINDOW
# =============================================================================


class KeynoteManagerWindow(forms.WPFWindow):
    """Keynote manager with unified tree and hierarchy controls."""

    def __init__(self, xaml_file_name, reset_config=False):
        forms.WPFWindow.__init__(self, xaml_file_name)

        # Set Revit as the owner window - critical for modeless stability.
        # Without this, WPF's message pump collides with Revit's on focus
        # change, causing hard crashes.
        # NOTE: Commented out for Revit 2026.4 (.NET 8) compatibility.
        # pyRevit's forms.WPFWindow already handles window ownership correctly.
        # try:
        #     wih = WindowInteropHelper(self)
        #     wih.Owner = SysProcess.GetCurrentProcess().MainWindowHandle
        # except Exception as ex:
        #     logger.debug("WindowInteropHelper failed | %s" % ex)

        # Keep the Win32 hook disabled in Revit 2026.4. Subclassing the
        # Revit-owned message loop can terminate Revit without a Python
        # traceback on some Windows/Revit builds.
        self._hwnd_source = None
        self._activation_pending = False


        self._kfile = None
        self._kfile_handler = None
        self._kfile_ext = None
        self._conn = None
        self._multi_selected_keys = set()
        self._multi_select_syncing = False
        self._last_multi_select_key = None

        self._determine_kfile()
        self._connect_kfile()

        self._undo_stack = []

        self._cache = []
        self._needs_update = False
        self._backup_done = False
        self._config = script.get_config()
        self._register_recent_file()
        self._used_keysdict = self.get_used_keynote_elements()

        # drag state
        self._drag_start_point = None
        self._is_dragging = False

        # modeless close state
        self._close_pending = False

        self._search_timer = DispatcherTimer()
        # Wait 300ms after last keystroke before filtering.
        self._search_timer.Interval = TimeSpan.FromMilliseconds(300)
        self._search_timer.Tick += self._on_search_timer_tick

        self.load_config(reset_config)
        self._update_full_tree()
        self._update_status_bar()
        self._update_inspector()
        self.search_tb.Focus()

    # =========================================================================
    # PROPERTIES
    # =========================================================================

    @property
    def window_geom(self):
        return (self.Width, self.Height, self.Top, self.Left)

    @window_geom.setter
    def window_geom(self, geom_tuple):
        w, h, t, l = geom_tuple
        self.Width = self.Width if math.isnan(w) else w
        self.Height = self.Height if math.isnan(h) else h
        self.Top = self.Top if math.isnan(t) else t
        self.Left = self.Left if math.isnan(l) else l

    @property
    def search_term(self):
        return self.search_tb.Text

    @search_term.setter
    def search_term(self, value):
        self.search_tb.Text = value

    @property
    def postable_keynote_command(self):
        return get_keynote_pcommands()[self.postcmd_idx]

    @property
    def postcmd_options(self):
        return [self.userknote_rb, self.materialknote_rb, self.elementknote_rb]

    @property
    def postcmd_idx(self):
        for idx, rb in enumerate(self.postcmd_options):
            if rb.IsChecked:
                return idx
        return 0

    @postcmd_idx.setter
    def postcmd_idx(self, index):
        self.postcmd_options[index if index else 0].IsChecked = True

    @property
    def selected_keynote(self):
        return self.keynotes_tv.SelectedItem

    @property
    def current_keynotes(self):
        return self.keynotes_tv.ItemsSource

    @property
    def all_categories(self):
        try:
            return kdb.get_categories(self._conn)
        except System.TimeoutException as toutex:
            forms.alert(toutex.Message)
            return []

    @property
    def all_keynotes(self):
        try:
            return kdb.get_keynotes(self._conn)
        except System.TimeoutException as toutex:
            forms.alert(toutex.Message)
            return []

    # =========================================================================
    # STATUS BAR
    # =========================================================================

    def _update_status_bar(self):
        if self._kfile:
            fname = op.basename(self._kfile)
            handler = " ( ACC / FORMA )" if self._kfile_handler == "adc" else ""
            dirty = " | Unsaved model update" if self._needs_update else ""
            self.statusLeft.Text = "{}{} - {}{}".format(
                fname, handler, op.dirname(self._kfile)
                if op.dirname(self._kfile) else "", dirty
            )
        else:
            self.statusLeft.Text = "No keynote file loaded"

        try:
            cats = self.all_categories if self._conn else []
            knotes = self.all_keynotes if self._conn else []
            used = len(self._used_keysdict)
            self.statusRight.Text = (
                "{} groups | {} keynotes | {} in use".format(
                    len(cats), len(knotes), used
                )
            )
        except Exception:
            self.statusRight.Text = ""

    def _set_dirty(self, value=True):
        self._needs_update = value
        self._update_status_bar()

    def _register_recent_file(self):
        if not self._kfile:
            return
        recent = list(self._config.get_option("recent_keynote_files", []))
        recent = [x for x in recent if x and op.exists(x) and x != self._kfile]
        recent.insert(0, self._kfile)
        self._config.set_option("recent_keynote_files", recent[:10])
        script.save_config()

    def _timestamp(self):
        return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    def _backup_keynote_file(self, reason="manual"):
        if not self._kfile or not op.exists(self._kfile):
            return None
        backup_dir = op.join(op.dirname(self._kfile), "_P13_Keynote_Backups")
        if not op.exists(backup_dir):
            os.makedirs(backup_dir)
        name, ext = op.splitext(op.basename(self._kfile))
        backup_path = op.join(
            backup_dir, "{}_{}_{}{}".format(name, reason, self._timestamp(), ext)
        )
        shutil.copy2(self._kfile, backup_path)
        return backup_path

    def _backup_once(self, reason="edit"):
        if self._backup_done:
            return
        try:
            self._backup_keynote_file(reason=reason)
            self._backup_done = True
        except Exception as ex:
            logger.debug("Keynote backup failed | %s" % ex)

    def _flat_nodes(self, roots=None):
        roots = roots if roots is not None else self._build_full_tree()
        result = []

        def _walk(node):
            result.append(node)
            for child in list(getattr(node, "children", []) or []):
                _walk(child)

        for root in roots or []:
            _walk(root)
        return result

    def _selected_key_text(self):
        sel = self.selected_keynote
        if not sel:
            return None, None
        return sel.key, sel.text or ""

    def _copy_to_clipboard(self, text):
        try:
            Windows.Clipboard.SetText(text or "")
            self.statusLeft.Text = "Copied to clipboard"
        except Exception as ex:
            forms.alert("Copy failed: {}".format(ex))

    def _next_key_from(self, key):
        match = re.match(r"^(.*?)(\d+)$", key or "")
        if not match:
            return "{}_COPY".format(key)
        prefix, digits = match.groups()
        width = len(digits)
        value = int(digits)
        existing = set([x.key for x in self.all_categories] + [x.key for x in self.all_keynotes])
        while True:
            value += 1
            candidate = "{}{}".format(prefix, str(value).zfill(width))
            if candidate not in existing:
                return candidate

    # =========================================================================
    # REVIT THREAD DISPATCH (for modeless window)
    # =========================================================================

    def _revit_run(self, action, callback=None):
        """Queue an action to execute on Revit's main thread.
        Optional callback runs on the WPF thread after the action."""
        _ext_handler.queue(action, callback, self)
        _ext_event.Raise()

    # =========================================================================
    # TREE STATE PRESERVATION
    # =========================================================================

    def _get_scroll_viewer(self):
        """Walk the visual tree to find the ScrollViewer inside TreeView."""
        tv = self.keynotes_tv
        if not tv or Windows.Media.VisualTreeHelper.GetChildrenCount(tv) == 0:
            return None
        try:
            border = Windows.Media.VisualTreeHelper.GetChild(tv, 0)
            if border and Windows.Media.VisualTreeHelper.GetChildrenCount(border) > 0:
                sv = Windows.Media.VisualTreeHelper.GetChild(border, 0)
                if isinstance(sv, Windows.Controls.ScrollViewer):
                    return sv
        except Exception:
            pass
        return self._find_child_of_type(tv, Windows.Controls.ScrollViewer)

    def _find_child_of_type(self, parent, child_type):
        """Recursively find first child of a given type in the visual tree."""
        try:
            count = Windows.Media.VisualTreeHelper.GetChildrenCount(parent)
        except Exception:
            return None
        for i in range(count):
            child = Windows.Media.VisualTreeHelper.GetChild(parent, i)
            if isinstance(child, child_type):
                return child
            result = self._find_child_of_type(child, child_type)
            if result:
                return result
        return None

    def _get_scroll_offset(self):
        """Get the current vertical scroll offset of the TreeView."""
        sv = self._get_scroll_viewer()
        if sv:
            return sv.VerticalOffset
        return None

    def _set_scroll_offset(self, offset):
        """Restore the vertical scroll offset after a tree rebuild."""

        def _do_scroll():
            sv = self._get_scroll_viewer()
            if sv:
                sv.ScrollToVerticalOffset(offset)

        self.Dispatcher.BeginInvoke(
            System.Action(_do_scroll), Windows.Threading.DispatcherPriority.Loaded
        )

    def _select_keynote_by_key(self, key):
        """Find and select the node with the given key in the new tree."""
        path = self._find_node_path(self.keynotes_tv.ItemsSource, key)
        if not path:
            return

        def _do_select():
            container = None
            parent_container = self.keynotes_tv
            for node in path:
                if container and hasattr(container, "IsExpanded"):
                    container.IsExpanded = True
                    container.UpdateLayout()
                idx = None
                items = parent_container.ItemContainerGenerator
                src = (
                    parent_container.Items
                    if hasattr(parent_container, "Items")
                    else parent_container.ItemsSource
                )
                if src:
                    for i, item in enumerate(src):
                        if hasattr(item, "key") and item.key == node.key:
                            idx = i
                            break
                if idx is not None:
                    container = items.ContainerFromIndex(idx)
                else:
                    container = items.ContainerFromItem(node)
                if container is None:
                    if hasattr(parent_container, "UpdateLayout"):
                        parent_container.UpdateLayout()
                    if idx is not None:
                        container = items.ContainerFromIndex(idx)
                    else:
                        container = items.ContainerFromItem(node)
                if container is None:
                    return
                parent_container = container

            if container and hasattr(container, "IsSelected"):
                container.IsSelected = True
                container.BringIntoView()

        self.Dispatcher.BeginInvoke(
            System.Action(_do_select), Windows.Threading.DispatcherPriority.Loaded
        )

    def _find_node_path(self, roots, target_key):
        """Return the path [root, ..., target] from roots to the node
        matching target_key, or None if not found."""
        if not roots:
            return None
        for root in roots:
            if root.key == target_key:
                return [root]
            if root.children:
                sub = self._find_node_path(root.children, target_key)
                if sub:
                    return [root] + sub
        return None

    # =========================================================================
    # USED KEYNOTE TRACKING
    # =========================================================================

    def get_used_keynote_elements(self):
        used = defaultdict(list)
        try:
            for kn in revit.query.get_used_keynotes(doc=revit.doc):
                if kn is None:
                    continue
                p = kn.Parameter[DB.BuiltInParameter.KEY_VALUE]
                if p:
                    key = p.AsString()
                    if key:
                        used[key].append(kn.Id)
        except Exception as ex:
            logger.debug("get_used_keynotes failed | %s" % ex)
        return used

    # =========================================================================
    # CONFIG
    # =========================================================================

    def save_config(self):
        wg = {}
        for k, v in self._config.get_option("last_window_geom", {}).items():
            if op.exists(k):
                wg[k] = v
        wg[self._kfile] = self.window_geom
        self._config.set_option("last_window_geom", wg)

        pc = {}
        for k, v in self._config.get_option("last_postcmd_idx", {}).items():
            if op.exists(k):
                pc[k] = v
        pc[self._kfile] = self.postcmd_idx
        self._config.set_option("last_postcmd_idx", pc)

        st = {}
        if self.search_term:
            st[self._kfile] = self.search_term
        self._config.set_option("last_search_term", st)

        script.save_config()

    def load_config(self, reset):
        wg = {} if reset else self._config.get_option("last_window_geom", {})
        if wg and self._kfile in wg:
            w, h, t, l = wg[self._kfile]
        else:
            w, h, t, l = (None, None, None, None)
        if all([w, h, t, l]) and coreutils.is_box_visible_on_screens(l, t, w, h):
            self.window_geom = (w, h, t, l)
        else:
            self.WindowStartupLocation = (
                framework.Windows.WindowStartupLocation.CenterScreen
            )

        pc = {} if reset else self._config.get_option("last_postcmd_idx", {})
        self.postcmd_idx = pc.get(self._kfile, 0)

        st = {} if reset else self._config.get_option("last_search_term", {})
        self.search_term = st.get(self._kfile, "")

    # =========================================================================
    # KEYNOTE FILE CONNECTION
    # =========================================================================

    def _determine_kfile(self):
        """Determine the keynote file path for this project.

        Resolution order:
          1. Local keynote file (revit.query.get_local_keynote_file)
          2. External/cloud file via ADC (Autodesk Desktop Connector)
             - Resolve cloud path to local via adc.get_local_path()
             - Graceful degradation for lock/sync on Public API
          3. Alert user if ADC not available
        """
        self._kfile = revit.query.get_local_keynote_file(doc=revit.doc)
        self._kfile_handler = None
        self._kfile_ext = None

        if self._kfile:
            return

        self._kfile_ext = revit.query.get_external_keynote_file(doc=revit.doc)
        self._kfile_handler = "unknown"

        if not self._kfile_ext:
            return

        # CRITICAL: call is_available() FIRST on a clean AppDomain.
        # No legacy DLL probing before this point.
        if adc.is_available():
            self._kfile_handler = "adc"
            self._resolve_adc_keynote()
            return

        forms.alert(
            "{} is not available.\n\n"
            "Please ensure Desktop Connector is running "
            "in the system tray.".format(adc.ADC_NAME),
            exitscript=True,
        )

    def _resolve_adc_keynote(self):
        """Resolve cloud keynote path to local file via ADC."""
        try:
            local_kfile = adc.get_local_path(self._kfile_ext)

            if not local_kfile:
                forms.alert(
                    "Cannot resolve local path via {}.".format(adc.ADC_NAME),
                    exitscript=True,
                )
                return

            try:
                locked, owner = adc.is_locked(self._kfile_ext)
                if locked:
                    forms.alert("File locked by {}.".format(owner), exitscript=True)
                    return
            except Exception:
                pass

            try:
                adc.sync_file(self._kfile_ext)
                adc.lock_file(self._kfile_ext)
            except Exception:
                pass

            self._kfile = local_kfile

            self.Title += " ( ACC / FORMA )"

        except Exception as adcex:
            forms.alert("ADC communication failed.\n{}".format(adcex), exitscript=True)

    def _connect_kfile(self):
        if not self._kfile or not op.exists(self._kfile):
            self._kfile = None
            forms.alert(
                "Keynote file not found.\n\n"
                "Please select a valid keynote file using the 'Change Keynote File' button.",
                title="File Not Found"
            )
            raise Exception("No keynote file set for this project.")

        while True:
            try:
                self._conn = kdb.connect(self._kfile)
                break
            except System.TimeoutException as toutex:
                forms.alert(toutex.Message, exitscript=True)
            except Exception as ex:
                logger.debug("Connection failed | %s" % ex)
                res = forms.alert(
                    "Cannot connect to keynote file.\n"
                    "It may need conversion to the new format.",
                    options=["Convert", "Select Other", "Help"],
                )
                if res == "Convert":
                    try:
                        self._convert_existing()
                        forms.alert("Converted successfully!")
                    except Exception as convex:
                        forms.alert("Conversion failed: %s" % convex, exitscript=True)
                elif res == "Select Other":
                    self.change_keynote_file(None, None)
                    script.exit()
                elif res == "Help":
                    script.open_url(
                        "https://www.notion.so/pyrevitlabs/"
                        "Manage-Keynotes-6f083d6f66fe43d68dc5d5407c8e19da"
                    )
                    script.exit()
                else:
                    forms.alert("No valid keynote file.", exitscript=True)

    def _convert_existing(self):
        temp_bak = script.get_data_file(op.basename(self._kfile), "bak")
        if op.exists(temp_bak):
            script.remove_data_file(temp_bak)
        
        temp_db = script.get_data_file(op.basename(self._kfile), "tmp_db")
        if op.exists(temp_db):
            script.remove_data_file(temp_db)

        try:
            shutil.copy2(self._kfile, temp_bak)
        except Exception as ex:
            raise Exception("Backup of keynote file failed: {}".format(ex))

        try:
            with open(temp_db, "w") as f:
                pass
            
            temp_conn = kdb.connect(temp_db)
            try:
                kdb.import_legacy_keynotes(temp_conn, temp_bak, skip_dup=True)
            finally:
                try:
                    temp_conn.Dispose()
                except Exception:
                    pass

            shutil.copy2(temp_db, self._kfile)

        except Exception as ex:
            try:
                shutil.copy2(temp_bak, self._kfile)
            except Exception:
                pass
            raise ex
        finally:
            if op.exists(temp_bak):
                script.remove_data_file(temp_bak)
            if op.exists(temp_db):
                script.remove_data_file(temp_db)

    # =========================================================================
    # TREE BUILDING - UNIFIED (categories + keynotes in one tree)
    # =========================================================================

    def _build_full_tree(self):
        """Build a single tree: categories at root, keynotes nested by
        parent_key.  Returns the root-level list of RKeynote objects
        with children populated recursively."""
        try:
            categories = kdb.get_categories(self._conn)
            all_knotes = kdb.get_keynotes(self._conn)
        except System.TimeoutException as toutex:
            forms.alert(toutex.Message)
            return []
        except Exception as ex:
            forms.alert("Error loading keynotes:\n%s" % ex, exitscript=True)
            return []

        # Build parent -> children map from keynotes
        cat_keys = set(c.key for c in categories)
        children_map = defaultdict(list)
        for kn in all_knotes:
            if kn.parent_key:
                children_map[kn.parent_key].append(kn)

        # Recursive child population
        def _populate(node):
            node_children = natsorted(
                children_map.get(node.key, []), key=lambda x: x.key
            )
            # Replace the children list (clear first to avoid dupes)
            while node.children:
                node.children.pop()
            for child in node_children:
                _populate(child)
                node.children.append(child)

        # Root-level: categories
        roots = natsorted(categories, key=lambda x: x.key)
        for root in roots:
            _populate(root)

        # Also find keynotes whose parent_key is a category
        # but weren't caught above (edge case: orphans)
        all_parented = set()
        for kids in children_map.values():
            for k in kids:
                all_parented.add(k.key)

        return roots

    def _update_full_tree(self, fast_filter=False, preferred_key=None):
        """Refresh the single unified tree, applying search filter."""
        # Run validation check for banner
        val_res = self._run_validation_check()
        if val_res:
            dups, empty, orphans = val_res
            total_issues = len(dups) + len(empty) + len(orphans)
            if total_issues > 0:
                self.validationBanner.Visibility = Windows.Visibility.Visible
                self.validationBannerText.Text = u"พบปัญหาข้อมูล: คีย์ซ้ำ {} รายการ, ข้อความว่าง {} รายการ, คีย์ไม่มีหมวดแม่ {} รายการ".format(
                    len(dups), len(empty), len(orphans)
                )
                self.validationBannerText.Text = "Data issues found: {} duplicate keys, {} empty text records, {} orphan records.".format(
                    len(dups), len(empty), len(orphans)
                )
            else:
                self.validationBanner.Visibility = Windows.Visibility.Collapsed
        else:
            self.validationBanner.Visibility = Windows.Visibility.Collapsed

        # Save current state before rebuild
        saved_key = None
        saved_scroll = None
        sel = self.selected_keynote
        if sel:
            saved_key = sel.key
        saved_scroll = self._get_scroll_offset()

        keynote_filter = self.search_term if self.search_term else None

        # Update view-only filter keys
        if keynote_filter and kdb.RKeynoteFilters.ViewOnly.code in keynote_filter:
            visible_keys = [
                x.TagText for x in revit.query.get_visible_keynotes(revit.active_view)
            ]
            kdb.RKeynoteFilters.ViewOnly.set_keys(visible_keys)

        if fast_filter and keynote_filter:
            tree = list(self._cache)
        else:
            tree = self._build_full_tree()

        # Mark used
        for node in tree:
            node.update_used(self._used_keysdict)

        # Cache for fast re-filter
        self._cache = list(tree)

        # Apply search filter
        if keynote_filter:
            clean = keynote_filter.lower().strip()
            if clean in ["duplicates", "empty text", "orphans"]:
                if val_res:
                    dups, empty, orphans = val_res
                else:
                    dups, empty, orphans = ([], [], [])
                
                if clean == "duplicates":
                    target_keys = set(dups)
                elif clean == "empty text":
                    target_keys = set(x.key for x in empty)
                else:
                    target_keys = set(x.key for x in orphans)

                def _filter_node(node):
                    node._filter = clean
                    node_pass = node.key in target_keys
                    node._filtered_children = [x for x in node._children if _filter_node(x)]
                    return node_pass or bool(node._filtered_children)

                tree = [n for n in tree if _filter_node(n)]
            else:
                tree = [n for n in tree if n.filter(clean)]

        if hasattr(self, "_multi_selected_keys"):
            self._multi_selected_keys.clear()
            self._last_multi_select_key = None
            for node in self._flat_nodes(tree):
                node.multi_selected = False

        self.keynotes_tv.ItemsSource = tree

        if tree:
            self.emptyStateMsg.Visibility = Windows.Visibility.Collapsed
        else:
            self.emptyStateMsg.Visibility = Windows.Visibility.Visible

        # Restore state after rebuild. If the previous item was removed,
        # prefer the nearest sibling or parent supplied by the caller.
        restore_key = saved_key
        if restore_key and not self._find_node_path(tree, restore_key):
            restore_key = preferred_key
        if not restore_key:
            restore_key = preferred_key
        if restore_key:
            self._select_keynote_by_key(restore_key)
        if saved_scroll is not None:
            self._set_scroll_offset(saved_scroll)

    # =========================================================================
    # BUTTON STATE
    # =========================================================================

    def _update_buttons(self):
        """Enable/disable toolbar buttons based on selection."""
        multi_count = len(getattr(self, "_multi_selected_keys", []))
        if multi_count:
            for btn in [
                self.editKeynoteBtn,
                self.dupKeynoteBtn,
                self.rekeyBtn,
                self.findBtn,
                self.placeBtn,
                self.indentBtn,
                self.outdentBtn,
                self.moveUpBtn,
                self.moveDownBtn,
                self.caseBtn,
                self.copyBtn,
                self.inspectBtn,
            ]:
                btn.IsEnabled = False
            self.removeBtn.IsEnabled = True
            self.undoBtn.IsEnabled = bool(self._undo_stack)
            return

        sel = self.selected_keynote
        if not sel or sel.locked:
            for btn in [
                self.editKeynoteBtn,
                self.dupKeynoteBtn,
                self.rekeyBtn,
                self.removeBtn,
                self.findBtn,
                self.placeBtn,
                self.indentBtn,
                self.outdentBtn,
                self.moveUpBtn,
                self.moveDownBtn,
                self.caseBtn,
                self.copyBtn,
                self.inspectBtn,
            ]:
                btn.IsEnabled = False
            self.undoBtn.IsEnabled = bool(self._undo_stack)
            return

        is_cat = sel.is_category  # top-level group (no parent_key)
        is_kn = bool(sel.parent_key)

        self.editKeynoteBtn.IsEnabled = True
        self.dupKeynoteBtn.IsEnabled = is_kn
        self.rekeyBtn.IsEnabled = True
        self.removeBtn.IsEnabled = True
        self.findBtn.IsEnabled = is_kn
        self.placeBtn.IsEnabled = is_kn
        self.caseBtn.IsEnabled = True
        self.copyBtn.IsEnabled = True
        self.inspectBtn.IsEnabled = is_kn
        self.undoBtn.IsEnabled = bool(self._undo_stack)

        # Hierarchy buttons
        # Indent: can indent if it's a keynote and has a preceding sibling
        can_indent = False
        can_outdent = False
        can_up = False
        can_down = False

        if is_kn:
            siblings = _find_siblings(self.all_keynotes, sel.parent_key)
            idx = next((i for i, s in enumerate(siblings) if s.key == sel.key), -1)
            can_indent = idx > 0  # has a sibling above
            # Can outdent if parent is a keynote (not a category)
            cats = self.all_categories
            cat_keys = set(c.key for c in cats)
            parent_is_keynote = sel.parent_key not in cat_keys
            can_outdent = parent_is_keynote
            can_up = idx > 0
            can_down = idx < len(siblings) - 1
        elif is_cat:
            cats = natsorted(self.all_categories, key=lambda x: x.key)
            idx = next((i for i, c in enumerate(cats) if c.key == sel.key), -1)
            can_up = idx > 0
            can_down = idx < len(cats) - 1

        self.indentBtn.IsEnabled = can_indent
        self.outdentBtn.IsEnabled = can_outdent
        self.moveUpBtn.IsEnabled = can_up
        self.moveDownBtn.IsEnabled = can_down

    # =========================================================================
    # INDENT / OUTDENT - CORE HIERARCHY OPERATIONS
    # =========================================================================

    def indent_keynote(self, sender, args):
        """Indent: make selected node a child of the sibling above it.
        Effectively increases nesting depth by one level."""
        sel = self.selected_keynote
        if not sel or not sel.parent_key or sel.locked:
            return

        siblings = _find_siblings(self.all_keynotes, sel.parent_key)
        idx = next((i for i, s in enumerate(siblings) if s.key == sel.key), -1)
        if idx <= 0:
            return

        new_parent = siblings[idx - 1]
        self._save_undo_state()
        try:
            kdb.move_keynote(self._conn, sel.key, new_parent.key)
            self._backup_once(); self._set_dirty(True)
        except System.TimeoutException as toutex:
            forms.alert(toutex.Message)
            return
        except Exception as ex:
            forms.alert("Indent failed: %s" % ex)
            return

        self._update_full_tree()
        self._update_status_bar()

    def outdent_keynote(self, sender, args):
        """Outdent: promote selected node up one level.
        Moves it to be a sibling of its current parent."""
        sel = self.selected_keynote
        if not sel or not sel.parent_key or sel.locked:
            return

        cats = self.all_categories
        cat_keys = set(c.key for c in cats)

        # Find current parent
        current_parent_key = sel.parent_key
        if current_parent_key in cat_keys:
            # Parent is already a top-level category - can't outdent further
            # (would need to become a category itself, which is a different op)
            forms.alert(
                "Already at the top keynote level.\n"
                "To make this a top-level group, use the Re-Key as "
                "category workflow."
            )
            return

        # Parent is a keynote - find grandparent
        all_kn = self.all_keynotes
        parent = next((k for k in all_kn if k.key == current_parent_key), None)
        if not parent:
            return

        grandparent_key = parent.parent_key
        if not grandparent_key:
            return

        self._save_undo_state()
        try:
            kdb.move_keynote(self._conn, sel.key, grandparent_key)
            self._backup_once(); self._set_dirty(True)
        except System.TimeoutException as toutex:
            forms.alert(toutex.Message)
            return
        except Exception as ex:
            forms.alert("Outdent failed: %s" % ex)
            return

        self._update_full_tree()
        self._update_status_bar()

    # =========================================================================
    # MOVE UP / MOVE DOWN (swap keys with adjacent sibling)
    # =========================================================================

    def move_up(self, sender, args):
        """Swap selected node's key with the sibling above it."""
        self._swap_sibling(-1)

    def move_down(self, sender, args):
        """Swap selected node's key with the sibling below it."""
        self._swap_sibling(1)

    def _swap_sibling(self, direction):
        """Swap keys between the selected node and its adjacent sibling.
        direction: -1 for up, +1 for down."""
        sel = self.selected_keynote
        if not sel or sel.locked:
            return

        is_cat = sel.is_category
        if is_cat:
            siblings = natsorted(self.all_categories, key=lambda x: x.key)
        else:
            siblings = _find_siblings(self.all_keynotes, sel.parent_key)

        idx = next((i for i, s in enumerate(siblings) if s.key == sel.key), -1)
        target_idx = idx + direction
        if target_idx < 0 or target_idx >= len(siblings):
            return

        other = siblings[target_idx]
        if other.locked:
            forms.alert("Adjacent item is locked.")
            return

        self._save_undo_state()
        # Swap keys
        sel_key = sel.key
        other_key = other.key
        temp_key = "__swap_{}__".format(uuid.uuid4().hex[:8])

        try:
            if is_cat:
                kdb.update_category_key(self._conn, sel_key, temp_key)
                kdb.update_category_key(self._conn, other_key, sel_key)
                kdb.update_category_key(self._conn, temp_key, other_key)
                # Update children parent_keys
                with kdb.BulkAction(self._conn):
                    for child in self.all_keynotes:
                        if child.parent_key == sel_key:
                            kdb.move_keynote(self._conn, child.key, other_key)
                        elif child.parent_key == other_key:
                            kdb.move_keynote(self._conn, child.key, sel_key)
            else:
                kdb.update_keynote_key(self._conn, sel_key, temp_key)
                kdb.update_keynote_key(self._conn, other_key, sel_key)
                kdb.update_keynote_key(self._conn, temp_key, other_key)
                # Update children of swapped nodes
                with kdb.BulkAction(self._conn):
                    for child in self.all_keynotes:
                        if child.parent_key == sel_key:
                            kdb.move_keynote(self._conn, child.key, other_key)
                        elif child.parent_key == other_key:
                            kdb.move_keynote(self._conn, child.key, sel_key)

            # Update references in Revit model (async via ExternalEvent)
            sk, ok = sel_key, other_key
            self._revit_run(lambda: self._swap_keynote_refs(sk, ok))
            self._backup_once(); self._set_dirty(True)
        except System.TimeoutException as toutex:
            forms.alert(toutex.Message)
            return
        except Exception as ex:
            forms.alert("Swap failed: %s" % ex)
            return

        self._update_full_tree()
        self._update_status_bar()

    def _swap_keynote_refs(self, key_a, key_b):
        """Swap Revit element references between two keynote keys."""
        temp = "__ref_{}__".format(uuid.uuid4().hex[:8])
        with revit.Transaction("Reorder Keynotes"):
            for kid in self.get_used_keynote_elements().get(key_a, []):
                kel = revit.doc.GetElement(kid)
                if kel:
                    p = kel.Parameter[DB.BuiltInParameter.KEY_VALUE]
                    if p:
                        p.Set(temp)
            for kid in self.get_used_keynote_elements().get(key_b, []):
                kel = revit.doc.GetElement(kid)
                if kel:
                    p = kel.Parameter[DB.BuiltInParameter.KEY_VALUE]
                    if p:
                        p.Set(key_a)
            for kid in self.get_used_keynote_elements().get(key_a, []):
                kel = revit.doc.GetElement(kid)
                if kel:
                    p = kel.Parameter[DB.BuiltInParameter.KEY_VALUE]
                    if p and p.AsString() == temp:
                        p.Set(key_b)

    # =========================================================================
    # KEY PICKER
    # =========================================================================

    def _pick_new_key(self):
        try:
            cats = kdb.get_categories(self._conn)
            kns = kdb.get_keynotes(self._conn)
            locks = kdb.get_locks(self._conn)
        except System.TimeoutException as toutex:
            forms.alert(toutex.Message)
            return
        reserved = [x.key for x in cats]
        reserved.extend([x.key for x in kns])
        reserved.extend([x.LockTargetRecordKey for x in locks])
        return forms.ask_for_unique_string(
            prompt="Enter a unique key:",
            title="Choose Unique Key",
            reserved_values=reserved,
            owner=self,
        )

    def _pick_parent(self):
        """Pick any node (category or keynote) as a parent."""
        cats = self.all_categories
        kns = self.all_keynotes
        items = natsorted(
            ["{} - {}".format(x.key, x.text) for x in cats]
            + ["{} - {}".format(x.key, x.text) for x in kns],
        )
        chosen = forms.SelectFromList.show(
            items, title="Select Parent", multiselect=False, owner=self
        )
        if chosen:
            return chosen.split(" - ")[0].strip()
        return None

    # =========================================================================
    # SEARCH
    # =========================================================================

    def search_txt_changed(self, sender, args):
        if self.search_tb.Text == "":
            self.clrsearch_b.Visibility = Windows.Visibility.Collapsed
        else:
            self.clrsearch_b.Visibility = Windows.Visibility.Visible

        # Stop and restart the timer on every keystroke.
        # The filter won't run until the typing pauses for 300ms.
        if hasattr(self, "_search_timer"):
            self._search_timer.Stop()
            self._search_timer.Start()

    def _on_search_timer_tick(self, sender, args):
        """Fires when the user stops typing."""
        self._search_timer.Stop()
        self._update_full_tree(fast_filter=True)

    def clear_search(self, sender, args):
        self.search_tb.Text = ""
        self.search_tb.Clear()
        self.search_tb.Focus()
        self._update_full_tree(fast_filter=True)

    def custom_filter(self, sender, args):
        sfilter = forms.SelectFromList.show(
            kdb.RKeynoteFilters.get_available_filters(),
            title="Select Filter",
            owner=self,
        )
        if sfilter:
            self.search_term = sfilter.format_term(self.search_term)

    # =========================================================================
    # SELECTION
    # =========================================================================

    def _set_inspector_value(self, name, value):
        try:
            getattr(self, name).Text = value if value is not None else "-"
        except Exception:
            pass

    def _update_inspector(self):
        sel = self.selected_keynote
        if not sel:
            self._set_inspector_value("inspectorKey", "-")
            self._set_inspector_value("inspectorType", "-")
            self._set_inspector_value("inspectorParent", "-")
            self._set_inspector_value("inspectorChildren", "-")
            self._set_inspector_value("inspectorUsed", "-")
            self._set_inspector_value("inspectorLock", "-")
            self._set_inspector_value("inspectorText", "No item selected.")
            return

        key = getattr(sel, "key", "") or "-"
        text = getattr(sel, "text", "") or "-"
        is_category = bool(getattr(sel, "is_category", False))
        parent_key = getattr(sel, "parent_key", None) or "Root"
        children = getattr(sel, "children", [])
        try:
            child_count = len(children)
        except Exception:
            child_count = 0

        try:
            used_count = int(getattr(sel, "used_count", 0) or 0)
        except Exception:
            used_count = 0

        locked = bool(getattr(sel, "locked", False))
        owner = getattr(sel, "owner", "") or "-"

        self._set_inspector_value("inspectorKey", key)
        self._set_inspector_value("inspectorType", "Group" if is_category else "Keynote")
        self._set_inspector_value("inspectorParent", parent_key)
        self._set_inspector_value("inspectorChildren", "{} child records".format(child_count))
        self._set_inspector_value("inspectorUsed", "{} model placements".format(used_count))
        self._set_inspector_value("inspectorLock", "Locked by {}".format(owner) if locked else "Editable")
        self._set_inspector_value("inspectorText", text)

    def _get_sender_node(self, sender):
        try:
            return sender.DataContext
        except Exception:
            return None

    def _is_shift_pressed(self):
        try:
            mods = Windows.Input.Keyboard.Modifiers
            shift = Windows.Input.ModifierKeys.Shift
            return (mods & shift) == shift
        except Exception:
            return False

    def _collect_node_and_children(self, node):
        nodes = []

        def _walk(item):
            if not item:
                return
            nodes.append(item)
            for child in list(getattr(item, "children", []) or []):
                _walk(child)

        _walk(node)
        return nodes

    def _set_multi_selected_node_only(self, node, is_selected):
        if not node or not getattr(node, "key", None):
            return
        node.multi_selected = bool(is_selected)
        if is_selected:
            self._multi_selected_keys.add(node.key)
        else:
            self._multi_selected_keys.discard(node.key)

    def _set_multi_selected_nodes(self, node, is_selected):
        for item in self._collect_node_and_children(node):
            self._set_multi_selected_node_only(item, is_selected)

    def _multi_select_range_nodes(self, start_key, end_key):
        if not start_key or not end_key:
            return []

        nodes = self._flat_nodes(self.current_keynotes)
        start_index = None
        end_index = None
        for index, node in enumerate(nodes):
            if getattr(node, "key", None) == start_key:
                start_index = index
            if getattr(node, "key", None) == end_key:
                end_index = index

        if start_index is None or end_index is None:
            return []

        if start_index > end_index:
            start_index, end_index = end_index, start_index
        return nodes[start_index:end_index + 1]

    def _apply_multi_select_click(self, node, is_selected):
        use_range = (
            self._is_shift_pressed()
            and self._last_multi_select_key
            and self._last_multi_select_key != node.key
        )

        range_nodes = (
            self._multi_select_range_nodes(self._last_multi_select_key, node.key)
            if use_range
            else []
        )

        if range_nodes:
            for item in range_nodes:
                self._set_multi_selected_node_only(item, is_selected)
        else:
            self._set_multi_selected_nodes(node, is_selected)

        self._last_multi_select_key = node.key

    def _iter_visual_children(self, root):
        try:
            count = VisualTreeHelper.GetChildrenCount(root)
        except Exception:
            return
        for index in range(count):
            child = VisualTreeHelper.GetChild(root, index)
            yield child
            for subchild in self._iter_visual_children(child):
                yield subchild

    def _refresh_multi_select_checkboxes(self):
        for element in self._iter_visual_children(self.keynotes_tv):
            try:
                if not isinstance(element, CheckBox):
                    continue
                if getattr(element, "Name", "") != "multiSelectBox":
                    continue
                node = getattr(element, "DataContext", None)
                target_checked = bool(getattr(node, "multi_selected", False))
                if (element.IsChecked == True) != target_checked:
                    element.IsChecked = target_checked
            except Exception:
                continue

    def _update_multi_select_status(self):
        count = len(self._multi_selected_keys)
        if count:
            self.statusLeft.Text = "{} records selected for delete".format(count)
        else:
            self._update_status_bar()

    def multi_select_checked(self, sender, args):
        if self._multi_select_syncing:
            return
        node = self._get_sender_node(sender)
        if not node or not getattr(node, "key", None):
            return
        self._multi_select_syncing = True
        try:
            self._apply_multi_select_click(node, True)
            self._refresh_multi_select_checkboxes()
        finally:
            self._multi_select_syncing = False
        self._update_buttons()
        self._update_multi_select_status()

    def multi_select_unchecked(self, sender, args):
        if self._multi_select_syncing:
            return
        node = self._get_sender_node(sender)
        if not node or not getattr(node, "key", None):
            return
        self._multi_select_syncing = True
        try:
            self._apply_multi_select_click(node, False)
            self._refresh_multi_select_checkboxes()
        finally:
            self._multi_select_syncing = False
        self._update_buttons()
        self._update_multi_select_status()

    def selected_keynote_changed(self, sender, args):
        self._update_buttons()
        self._update_inspector()

    # =========================================================================
    # KEYBOARD SHORTCUTS
    # =========================================================================

    def window_keydown(self, sender, args):
        key = args.Key
        mods = Windows.Input.Keyboard.Modifiers
        ctrl = Windows.Input.ModifierKeys.Control
        shift = Windows.Input.ModifierKeys.Shift

        if key == Windows.Input.Key.F5:
            self.refresh(sender, args)
            args.Handled = True
        elif key == Windows.Input.Key.F2:
            if self.selected_keynote:
                self.edit_keynote(sender, args)
                args.Handled = True
        elif key == Windows.Input.Key.Delete:
            if self.selected_keynote or self._multi_selected_keys:
                self.remove_keynote(sender, args)
                args.Handled = True
        elif key == Windows.Input.Key.N and mods == ctrl:
            self.add_keynote(sender, args)
            args.Handled = True
        elif key == Windows.Input.Key.D and mods == ctrl:
            if self.selected_keynote:
                self.duplicate_keynote(sender, args)
                args.Handled = True
        elif key == Windows.Input.Key.Z and mods == ctrl:
            self.undo_action(sender, args)
            args.Handled = True
        elif key == Windows.Input.Key.V and mods == ctrl:
            self.paste_from_clipboard(sender, args)
            args.Handled = True
        elif key == Windows.Input.Key.I and mods == ctrl:
            self.import_keynotes(sender, args)
            args.Handled = True
        elif key == Windows.Input.Key.Tab and mods == shift:
            self.outdent_keynote(sender, args)
            args.Handled = True
        elif key == Windows.Input.Key.Tab and mods == getattr(
            Windows.Input.ModifierKeys, "None"
        ):
            self.indent_keynote(sender, args)
            args.Handled = True
        elif key == Windows.Input.Key.Up and mods == ctrl:
            self.move_up(sender, args)
            args.Handled = True
        elif key == Windows.Input.Key.Down and mods == ctrl:
            self.move_down(sender, args)
            args.Handled = True
        elif key == Windows.Input.Key.Escape:
            if self.search_term:
                self.clear_search(sender, args)
            else:
                self.Close()
            args.Handled = True

    # =========================================================================
    # DRAG AND DROP
    # =========================================================================

    def _is_ctrl_pressed(self):
        try:
            mods = Windows.Input.Keyboard.Modifiers
            ctrl = Windows.Input.ModifierKeys.Control
            return (mods & ctrl) == ctrl
        except Exception:
            return False

    def _find_tvi_ancestor(self, element):
        try:
            parent = element
            while parent:
                if isinstance(parent, TreeViewItem):
                    return parent
                parent = VisualTreeHelper.GetParent(parent)
        except Exception:
            pass
        return None

    def _is_element_or_parent_of_type(self, element, type_names):
        try:
            parent = element
            while parent:
                if type(parent).__name__ in type_names:
                    return True
                parent = VisualTreeHelper.GetParent(parent)
        except Exception:
            pass
        return False

    def tree_preview_mouse_down(self, sender, args):
        self._drag_start_point = args.GetPosition(sender)

        # Intercept Shift/Ctrl selection on rows
        if self._is_shift_pressed() or self._is_ctrl_pressed():
            # If the click was on scrollbars, expanders, or checkboxes, let WPF handle it natively
            ignored_types = ["CheckBox", "ToggleButton", "ScrollBar", "Thumb", "RepeatButton"]
            if self._is_element_or_parent_of_type(args.OriginalSource, ignored_types):
                return

            tvi = self._find_tvi_ancestor(args.OriginalSource)
            if tvi:
                node = tvi.DataContext
                if node and getattr(node, "key", None):
                    if self._is_shift_pressed():
                        anchor_key = self._last_multi_select_key
                        if not anchor_key and self.selected_keynote:
                            anchor_key = self.selected_keynote.key
                        
                        self._multi_select_syncing = True
                        try:
                            # Clear other selections if Ctrl is NOT pressed
                            if not self._is_ctrl_pressed():
                                for item in self._flat_nodes(self.current_keynotes):
                                    self._set_multi_selected_node_only(item, False)
                            
                            start_key = anchor_key if anchor_key else node.key
                            range_nodes = self._multi_select_range_nodes(start_key, node.key)
                            if range_nodes:
                                for item in range_nodes:
                                    self._set_multi_selected_node_only(item, True)
                            else:
                                self._set_multi_selected_nodes(node, True)
                            self._last_multi_select_key = node.key
                            self._refresh_multi_select_checkboxes()
                        finally:
                            self._multi_select_syncing = False
                        self._update_buttons()
                        self._update_multi_select_status()
                    elif self._is_ctrl_pressed():
                        new_val = not getattr(node, "multi_selected", False)
                        self._multi_select_syncing = True
                        try:
                            self._apply_multi_select_click(node, new_val)
                            self._refresh_multi_select_checkboxes()
                        finally:
                            self._multi_select_syncing = False
                        self._update_buttons()
                        self._update_multi_select_status()
                    
                    # Visually select clicked row
                    tvi.IsSelected = True
                    args.Handled = True

    def tree_preview_mouse_move(self, sender, args):
        if self._drag_start_point is None:
            return
        if args.LeftButton != Windows.Input.MouseButtonState.Pressed:
            self._drag_start_point = None
            return

        pt = args.GetPosition(sender)
        diff = self._drag_start_point - pt
        if (
            abs(diff.X) > System.Windows.SystemParameters.MinimumHorizontalDragDistance
            or abs(diff.Y) > System.Windows.SystemParameters.MinimumVerticalDragDistance
        ):
            sel = self.selected_keynote
            if sel and not sel.locked:
                self._is_dragging = True
                try:
                    data = Windows.DataObject("keynote", sel)
                    Windows.DragDrop.DoDragDrop(
                        self.keynotes_tv, data, Windows.DragDropEffects.Move
                    )
                except Exception as ex:
                    logger.debug("Drag failed | %s" % ex)
                finally:
                    self._is_dragging = False
                    self._drag_start_point = None

    def tree_double_click(self, sender, args):
        if not self._is_dragging and self.selected_keynote:
            if self.selected_keynote.parent_key:
                self.edit_keynote(sender, args)
            else:
                self.edit_category_inline(sender, args)

    def tree_drag_over(self, sender, args):
        args.Effects = getattr(Windows.DragDropEffects, "None")
        if args.Data.GetDataPresent("keynote"):
            args.Effects = Windows.DragDropEffects.Move

    def tree_item_drag_over(self, sender, args):
        args.Effects = getattr(Windows.DragDropEffects, "None")
        if args.Data.GetDataPresent("keynote"):
            args.Effects = Windows.DragDropEffects.Move
            # Visual feedback
            if hasattr(sender, "Background"):
                sender.Background = Windows.Media.SolidColorBrush(
                    Windows.Media.Color.FromArgb(40, 43, 87, 154)
                )
            args.Handled = True

    def tree_item_drag_leave(self, sender, args):
        if hasattr(sender, "Background"):
            sender.Background = None

    def tree_drop(self, sender, args):
        pass

    def tree_item_drop(self, sender, args):
        """Drop handler - reparent the dragged node under the target."""
        if hasattr(sender, "Background"):
            sender.Background = None

        if not args.Data.GetDataPresent("keynote"):
            return
        dragged = args.Data.GetData("keynote")
        if not dragged:
            return

        target = getattr(sender, "DataContext", None)
        if target is None or target == dragged:
            return

        # Determine new parent key
        new_parent_key = target.key

        # Don't allow dropping onto self or own children
        if new_parent_key == dragged.key:
            return

        # Check for circular reference
        def _is_descendant(parent_key, child_key, all_kn):
            """Check if child_key is a descendant of parent_key."""
            visited = set()
            stack = [child_key]
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                for kn in all_kn:
                    if kn.parent_key == current:
                        if kn.key == parent_key:
                            return True
                        stack.append(kn.key)
            return False

        if dragged.parent_key and _is_descendant(
            new_parent_key, dragged.key, self.all_keynotes
        ):
            forms.alert("Cannot drop a parent onto its own descendant.")
            return

        # If dragged is a category, this is more complex - skip for now
        if dragged.is_category:
            forms.alert(
                "Drag top-level groups is not supported.\n"
                "Use Move Up / Move Down to reorder groups."
            )
            return

        if new_parent_key == dragged.parent_key:
            return  # no change

        try:
            kdb.move_keynote(self._conn, dragged.key, new_parent_key)
            self._backup_once(); self._set_dirty(True)
        except System.TimeoutException as toutex:
            forms.alert(toutex.Message)
        except Exception as ex:
            forms.alert("Move failed: %s" % ex)

        self._update_full_tree()
        self._update_status_bar()
        args.Handled = True

    # =========================================================================
    # REFRESH
    # =========================================================================

    def refresh(self, sender, args):
        if self._conn:

            def _query_used():
                self._used_keysdict = self.get_used_keynote_elements()

            def _on_done():
                self._update_full_tree()
                self._update_status_bar()
                self.search_tb.Focus()

            self._revit_run(_query_used, callback=_on_done)
        else:
            self.search_tb.Focus()

    # =========================================================================
    # CATEGORY (GROUP) OPERATIONS
    # =========================================================================

    def add_category(self, sender, args):
        try:
            new_cat = EditRecordWindow(self, self._conn, kdb.EDIT_MODE_ADD_CATEG).show()
            if new_cat:
                self._backup_once(); self._set_dirty(True)
        except Exception as ex:
            forms.alert(str(ex))
        finally:
            self._update_full_tree()
            self._update_status_bar()

    def edit_category_inline(self, sender, args):
        """Edit a category (top-level group) via the edit dialog."""
        sel = self.selected_keynote
        if sel and sel.is_category and not sel.locked:
            try:
                EditRecordWindow(
                    self, self._conn, kdb.EDIT_MODE_EDIT_CATEG, rkeynote=sel
                ).show()
                self._backup_once(); self._set_dirty(True)
            except Exception as ex:
                forms.alert(str(ex))
            finally:
                self._update_full_tree()
                self._update_status_bar()

    # =========================================================================
    # KEYNOTE CRUD
    # =========================================================================

    def add_keynote(self, sender, args):
        parent_key = None
        sel = self.selected_keynote
        if sel:
            parent_key = sel.key if sel.is_category else sel.parent_key
        if not parent_key:
            parent_key = self._pick_parent()
        if parent_key:
            try:
                EditRecordWindow(
                    self, self._conn, kdb.EDIT_MODE_ADD_KEYNOTE, pkey=parent_key
                ).show()
                self._backup_once(); self._set_dirty(True)
            except Exception as ex:
                forms.alert(str(ex))
            finally:
                self._update_full_tree()
                self._update_status_bar()

    def duplicate_keynote(self, sender, args):
        sel = self.selected_keynote
        if sel and sel.parent_key:
            try:
                EditRecordWindow(
                    self,
                    self._conn,
                    kdb.EDIT_MODE_ADD_KEYNOTE,
                    text=sel.text,
                    pkey=sel.parent_key,
                ).show()
                self._backup_once(); self._set_dirty(True)
            except Exception as ex:
                forms.alert(str(ex))
            finally:
                self._update_full_tree()
                self._update_status_bar()

    def edit_keynote(self, sender, args):
        sel = self.selected_keynote
        if not sel:
            return
        if sel.is_category:
            self.edit_category_inline(sender, args)
            return
        try:
            EditRecordWindow(
                self, self._conn, kdb.EDIT_MODE_EDIT_KEYNOTE, rkeynote=sel
            ).show()
            self._backup_once(); self._set_dirty(True)
        except Exception as ex:
            forms.alert(str(ex))
        finally:
            self._update_full_tree()

    def _get_delete_fallback_key(self, sel):
        if not sel:
            return None
        try:
            if sel.is_category:
                siblings = natsorted(self.all_categories, key=lambda x: x.key)
            else:
                siblings = _find_siblings(self.all_keynotes, sel.parent_key)
            idx = next((i for i, item in enumerate(siblings) if item.key == sel.key), -1)
            if idx >= 0:
                if idx + 1 < len(siblings):
                    return siblings[idx + 1].key
                if idx - 1 >= 0:
                    return siblings[idx - 1].key
            if not sel.is_category and sel.parent_key:
                return sel.parent_key
        except Exception:
            pass
        return None

    def remove_keynote(self, sender, args):
        if self._multi_selected_keys:
            if self._remove_multi_selected_keynotes():
                return

        sel = self.selected_keynote
        if not sel:
            return
        fallback_key = self._get_delete_fallback_key(sel)

        if sel.is_category:
            # Removing a category
            if sel.has_children():
                forms.alert("Group '%s' has children. Remove them first." % sel.key)
                return
            if sel.used:
                forms.alert("Group '%s' is in use." % sel.key)
                return
            if forms.alert("Delete group '%s'?" % sel.key, yes=True, no=True):
                self._save_undo_state()
                try:
                    kdb.remove_category(self._conn, sel.key)
                    self._backup_once(); self._set_dirty(True)
                except Exception as ex:
                    forms.alert(str(ex))
        else:
            # Removing a keynote
            if sel.children:
                forms.alert("Keynote '%s' has children. Remove them first." % sel.key)
                return
            if sel.used:
                forms.alert("Keynote '%s' is in use." % sel.key)
                return
            if forms.alert("Delete keynote '%s'?" % sel.key, yes=True, no=True):
                self._save_undo_state()
                try:
                    kdb.remove_keynote(self._conn, sel.key)
                    self._backup_once(); self._set_dirty(True)
                except Exception as ex:
                    forms.alert(str(ex))

        self._update_full_tree(preferred_key=fallback_key)
        self._update_status_bar()

    def _flatten_keynote_tree(self, roots):
        flat = []

        def _walk(node):
            flat.append(node)
            for child in node.children:
                _walk(child)

        for root in roots:
            _walk(root)
        return flat

    def _is_bulk_deletable(self, node):
        return bool(node and not node.locked and not node.used and not node.has_children())

    def _nodes_by_key(self):
        roots = self._build_full_tree()
        for root in roots:
            root.update_used(self._used_keysdict)
        lookup = {}
        for node in self._flatten_keynote_tree(roots):
            lookup[node.key] = node
        return lookup

    def _remove_multi_selected_keynotes(self):
        selected_keys = set(self._multi_selected_keys)
        if not selected_keys:
            return False

        lookup = self._nodes_by_key()
        nodes = [lookup[key] for key in selected_keys if key in lookup]
        deletable = []
        protected = []
        for node in nodes:
            if self._is_bulk_deletable(node):
                deletable.append(node)
            else:
                protected.append(node.key)

        if not deletable:
            forms.alert(
                "No selected records can be deleted.\n\nRecords with children, locks, or model usage are protected."
            )
            return True

        message = "Delete {} selected records?".format(len(deletable))
        if protected:
            message += "\n\n{} selected records are protected and will be skipped.".format(
                len(protected)
            )
        message += "\n\nOnly empty, unused, unlocked records will be deleted."
        if not forms.alert(message, yes=True, no=True):
            return True

        current = self.selected_keynote
        fallback_key = None
        if current:
            if current.key not in selected_keys:
                fallback_key = current.key
            else:
                fallback_key = self._get_delete_fallback_key(current)
                if fallback_key in selected_keys:
                    fallback_key = None

        if not fallback_key:
            for node in deletable:
                if (not node.is_category) and node.parent_key not in selected_keys:
                    fallback_key = node.parent_key
                    break

        self._multi_selected_keys.clear()
        self._delete_nodes(deletable, fallback_key=fallback_key)
        if protected:
            self.statusLeft.Text += " ({} protected skipped)".format(len(protected))
        return True

    def _delete_nodes(self, nodes, fallback_key=None):
        self._save_undo_state()
        deleted_groups = 0
        deleted_keynotes = 0
        errors = []
        for node in nodes:
            try:
                if node.is_category:
                    kdb.remove_category(self._conn, node.key)
                    deleted_groups += 1
                else:
                    kdb.remove_keynote(self._conn, node.key)
                    deleted_keynotes += 1
            except Exception as ex:
                errors.append("{}: {}".format(node.key, ex))

        if deleted_groups or deleted_keynotes:
            self._backup_once()
            self._set_dirty(True)

        self._update_full_tree(preferred_key=fallback_key)
        self._update_status_bar()
        self.statusLeft.Text = "Deleted {} groups and {} keynotes".format(
            deleted_groups, deleted_keynotes
        )

        if errors:
            forms.alert(
                "Some records could not be deleted:\n\n{}".format("\n".join(errors[:12]))
            )

    def rekey_keynote(self, sender, args):
        sel = self.selected_keynote
        if not sel:
            return
        if any(x.locked for x in sel.children):
            forms.alert("Some children are locked - cannot re-key.")
            return
        try:
            from_key = sel.key
            to_key = self._pick_new_key()
            if to_key and to_key != from_key:
                self._save_undo_state()
                if sel.is_category:
                    kdb.update_category_key(self._conn, from_key, to_key)
                    with kdb.BulkAction(self._conn):
                        for child in self.all_keynotes:
                            if child.parent_key == from_key:
                                kdb.move_keynote(self._conn, child.key, to_key)
                else:
                    kdb.update_keynote_key(self._conn, from_key, to_key)
                    with kdb.BulkAction(self._conn):
                        for child in self.all_keynotes:
                            if child.parent_key == from_key:
                                kdb.move_keynote(self._conn, child.key, to_key)
                # Update Revit element refs (async via ExternalEvent)
                fk, tk = from_key, to_key
                self._revit_run(lambda: self._rekey_refs(fk, tk))
                self._backup_once(); self._set_dirty(True)
        except Exception as ex:
            forms.alert(str(ex))

        self._update_full_tree()
        self._update_status_bar()

    def _rekey_refs(self, from_key, to_key):
        with revit.Transaction("Re-Key {}".format(from_key)):
            for kid in self.get_used_keynote_elements().get(from_key, []):
                kel = revit.doc.GetElement(kid)
                if kel:
                    p = kel.Parameter[DB.BuiltInParameter.KEY_VALUE]
                    if p:
                        p.Set(to_key)

    # =========================================================================
    # TEXT CAPITALIZATION (quick apply without opening edit dialog)
    # =========================================================================

    def show_case_menu(self, sender, args):
        """Open the capitalization context menu on the button."""
        self.caseMenu.PlacementTarget = sender
        self.caseMenu.IsOpen = True

    def _apply_case(self, transform_fn):
        """Apply a text transformation to the selected keynote/category."""
        sel = self.selected_keynote
        if not sel or sel.locked:
            return
        new_text = transform_fn(sel.text)
        if new_text == sel.text:
            return
        try:
            if sel.is_category:
                kdb.update_category_title(self._conn, sel.key, new_text)
            else:
                kdb.update_keynote_text(self._conn, sel.key, new_text)
            self._backup_once(); self._set_dirty(True)
        except System.TimeoutException as toutex:
            forms.alert(toutex.Message)
            return
        except Exception as ex:
            forms.alert("Case change failed: %s" % ex)
            return
        self._update_full_tree()

    def to_upper(self, sender, args):
        self._apply_case(lambda t: t.upper())

    def to_lower(self, sender, args):
        self._apply_case(lambda t: t.lower())

    def to_title(self, sender, args):
        self._apply_case(lambda t: t.title())

    def to_sentence(self, sender, args):
        self._apply_case(lambda t: t[:1].upper() + t[1:].lower() if t else t)

    # =========================================================================
    # FIND / PLACE
    # =========================================================================

    def show_keynote(self, sender, args):
        """Show keynote usage in pyRevit output - keeps the window open."""
        sel = self.selected_keynote
        if not sel:
            return
        key = sel.key
        used_snapshot = dict(self._used_keysdict)
        kids = used_snapshot.get(key, [])
        if not kids:
            self.statusLeft.Text = "Keynote '{}' - not placed in model".format(key)
            return

        def _do():
            for kid in kids:
                source = viewname = ""
                kel = revit.doc.GetElement(kid)
                if kel is None:
                    continue
                ehist = revit.query.get_history(kel)
                p = kel.Parameter[DB.BuiltInParameter.KEY_SOURCE_PARAM]
                if p:
                    source = p.AsString()
                vel = revit.doc.GetElement(kel.OwnerViewId)
                if vel:
                    viewname = revit.query.get_name(vel)
                report = "Keynote: {} | Source: {} | View: {}".format(
                    output.linkify(kid), source, viewname
                )
                if ehist:
                    report += " | Last edit: %s" % ehist.last_changed_by
                print(report)

        def _update_status():
            self.statusLeft.Text = (
                "Keynote '{}' - {} placements shown in output".format(key, len(kids))
            )

        self._revit_run(_do, callback=_update_status)

    def place_keynote(self, sender, args):
        sel = self.selected_keynote
        if not sel:
            return
        sel_key = sel.key
        postcmd = self.postable_keynote_command
        self.Close()

        def _do():
            keynotes_cat = revit.query.get_category(DB.BuiltInCategory.OST_KeynoteTags)
            if keynotes_cat:
                def_id = revit.doc.GetDefaultFamilyTypeId(keynotes_cat.Id)
                if revit.doc.GetElement(def_id):
                    DocumentEventUtils.PostCommandAndUpdateNewElementProperties(
                        HOST_APP.uiapp,
                        revit.doc,
                        postcmd,
                        "Update Keynotes",
                        DB.BuiltInParameter.KEY_VALUE,
                        sel_key,
                    )

        self._revit_run(_do)

    # =============================================================================
    # NEW EXTENSION METHODS (Undo, Excel Paste, Validation, Placement Inspector, Report)
    # =============================================================================

    def _save_undo_state(self):
        if self._kfile and op.exists(self._kfile):
            try:
                with codecs.open(self._kfile, "r", "utf_16") as f:
                    self._undo_stack.append(f.read())
                if len(self._undo_stack) > 20:
                    self._undo_stack.pop(0)
            except Exception as ex:
                logger.debug("Save undo failed | %s" % ex)

    def undo_action(self, sender, args):
        if not self._undo_stack:
            self.statusLeft.Text = "Nothing to undo"
            return
            
        state = self._undo_stack.pop()
        try:
            if self._conn:
                try:
                    self._conn.Dispose()
                except Exception:
                    pass
                self._conn = None
                
            with codecs.open(self._kfile, "w", "utf_16") as f:
                f.write(state)
                
            self._conn = kdb.connect(self._kfile)
            self._needs_update = True
            self._update_full_tree()
            self.statusLeft.Text = "Undo completed"
        except Exception as ex:
            forms.alert("Undo failed:\n" + str(ex))
            try:
                self._conn = kdb.connect(self._kfile)
            except Exception:
                pass

    def paste_from_clipboard(self, sender, args):
        try:
            text = Windows.Clipboard.GetText()
        except Exception as ex:
            forms.alert("Cannot read clipboard: {}".format(ex))
            return
            
        if not text or not text.strip():
            forms.alert("Clipboard is empty or does not contain text.")
            return
            
        records = []
        for line in text.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue
            fields = line_str.split("\t")
            if len(fields) >= 1 and fields[0]:
                key = fields[0].strip()
                desc = fields[1].strip() if len(fields) >= 2 else ""
                parent = fields[2].strip() if len(fields) >= 3 else ""
                records.append((key, desc, parent))
                
        if not records:
            forms.alert("No valid tab-separated keynote records found in clipboard.")
            return
            
        res = forms.alert(
            "Found {} keynote records in clipboard.\n"
            "Do you want to import them?".format(len(records)),
            yes=True, no=True
        )
        if not res:
            return
            
        skip_dup = forms.alert(
            "Skip existing duplicate keys in database?\n"
            "(Selecting 'No' will overwrite them)",
            yes=True, no=True
        )
        
        self._save_undo_state()
        self._backup_once("paste")
        
        try:
            with kdb.BulkAction(self._conn):
                existing_cats = set(c.key for c in self.all_categories)
                existing_kns = set(k.key for k in self.all_keynotes)
                
                for key, desc, parent in records:
                    if parent:
                        if key in existing_kns:
                            if not skip_dup:
                                kdb.update_keynote_text(self._conn, key, desc)
                                if parent != kdb.find(self._conn, key).parent_key:
                                    kdb.move_keynote(self._conn, key, parent)
                        else:
                            kdb.add_keynote(self._conn, key, desc, parent)
                            existing_kns.add(key)
                    else:
                        if key in existing_cats:
                            if not skip_dup:
                                kdb.update_category_title(self._conn, key, desc)
                        else:
                            kdb.add_category(self._conn, key, desc)
                            existing_cats.add(key)
            self._set_dirty(True)
            self._update_full_tree()
            self.statusLeft.Text = "Imported {} records from clipboard".format(len(records))
        except Exception as ex:
            forms.alert("Clipboard import failed:\n" + str(ex))

    def _run_validation_check(self):
        if not self._conn:
            return None
        try:
            cats = self.all_categories
            kns = self.all_keynotes
            cat_keys = [x.key for x in cats]
            kn_keys = [x.key for x in kns]
            all_keys = cat_keys + kn_keys
            
            duplicates = sorted([x for x in set(all_keys) if all_keys.count(x) > 1])
            empty_text = [x for x in cats + kns if not (x.text or "").strip()]
            parent_keys = set(cat_keys + kn_keys)
            orphans = [x for x in kns if x.parent_key not in parent_keys]
            
            return duplicates, empty_text, orphans
        except Exception:
            return None

    def fix_validation_issues(self, sender, args):
        val_res = self._run_validation_check()
        if not val_res:
            return
        dups, empty, orphans = val_res
        
        options = []
        if dups:
            options.append("Filter duplicates in Tree")
        if empty:
            options.append("Filter empty text in Tree")
        if orphans:
            options.append("Filter orphans in Tree")
            
        if not options:
            return
            
        choice = forms.SelectFromList.show(
            options,
            title="Validation Fix Tool",
            multiselect=False,
            owner=self
        )
        if choice == "Filter duplicates in Tree":
            self.search_tb.Text = "duplicates"
        elif choice == "Filter empty text in Tree":
            self.search_tb.Text = "empty text"
        elif choice == "Filter orphans in Tree":
            self.search_tb.Text = "orphans"

    def _get_keynote_placements_info(self, keynote_key):
        info = []
        element_ids = self._used_keysdict.get(keynote_key, [])
        for kid in element_ids:
            kel = revit.doc.GetElement(kid)
            if kel is None:
                continue
            owner_view = revit.doc.GetElement(kel.OwnerViewId)
            if not owner_view:
                continue
            view_name = revit.query.get_name(owner_view)
            
            sheet_name = "None"
            if hasattr(owner_view, "SheetNumber") and owner_view.SheetNumber:
                sheet_name = owner_view.SheetNumber
            else:
                try:
                    sheet_param = owner_view.Parameter[DB.BuiltInParameter.VIEWPORT_SHEET_NAME]
                    if sheet_param and sheet_param.AsString():
                        sheet_name = sheet_param.AsString()
                except Exception:
                    pass
            
            info.append({
                "id": kid,
                "view_name": view_name,
                "sheet": sheet_name,
                "element": kel
            })
        return info

    def inspect_placements(self, sender, args):
        sel = self.selected_keynote
        if not sel or sel.is_category:
            return
        
        self.statusLeft.Text = "Querying placements..."
        
        def _query():
            self._placement_info = self._get_keynote_placements_info(sel.key)
            
        def _show_results():
            self.statusLeft.Text = "Query completed"
            if not self._placement_info:
                forms.alert("คีย์ '{}' นี้ยังไม่ได้ถูกใช้งานในโมเดล".format(sel.key))
                return
                
            options = ["View: {} | Sheet: {} (ID: {})".format(x["view_name"], x["sheet"], x["id"].ToString()) for x in self._placement_info]
            selected = forms.SelectFromList.show(
                options,
                title="ตำแหน่งที่จัดวาง Keynote: {}".format(sel.key),
                button_name="เปิดมุมมอง (Go to View)",
                multiselect=False,
                owner=self
            )
            if selected:
                idx = options.index(selected)
                item = self._placement_info[idx]
                
                def _goto():
                    with revit.Transaction("Go to Keynote View"):
                        revit.uidoc.ActiveView = revit.doc.GetElement(item["element"].OwnerViewId)
                        from System.Collections.Generic import List
                        ids = List[DB.ElementId]()
                        ids.Add(item["id"])
                        revit.uidoc.Selection.SetElementIds(ids)
                        revit.uidoc.ShowElements(item["id"])
                self._revit_run(_goto)
                
        self._revit_run(_query, callback=_show_results)

    def export_health_report(self, sender, args):
        kfile = forms.save_file("html")
        if not kfile:
            return
        try:
            cats = self.all_categories
            kns = self.all_keynotes
            dups, empty, orphans = self._run_validation_check()
            used = self._used_keysdict
            
            total_keys = len(cats) + len(kns)
            unused_kns = [x for x in kns if x.key not in used]
            missing_kns = [x for x in used if x not in set(c.key for c in cats + kns)]
            
            # HTML generation
            html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Keynote Health Report</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #F5F5F7; color: #1D1D1F; margin: 0; padding: 40px; }}
    .container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.05); }}
    h1 {{ font-size: 28px; font-weight: 700; margin-top: 0; margin-bottom: 5px; color: #000; }}
    .subtitle {{ color: #636366; font-size: 14px; margin-bottom: 30px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 40px; }}
    .card {{ background: #F5F5F7; padding: 20px; border-radius: 8px; text-align: center; }}
    .card .value {{ font-size: 24px; font-weight: bold; color: #0A84FF; }}
    .card .value.warning {{ color: #FF9F0A; }}
    .card .value.danger {{ color: #FF453A; }}
    .card .label {{ font-size: 12px; color: #636366; margin-top: 5px; text-transform: uppercase; letter-spacing: 0.5px; }}
    h2 {{ font-size: 20px; font-weight: 600; margin-top: 30px; border-bottom: 1px solid #ECECF0; padding-bottom: 8px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
    th {{ text-align: left; padding: 12px; background: #F5F5F7; font-weight: 600; font-size: 13px; color: #636366; border-bottom: 1px solid #D2D2D7; }}
    td {{ padding: 12px; font-size: 13px; border-bottom: 1px solid #ECECF0; }}
    tr:hover {{ background: #FAF9F9; }}
    .badge {{ display: inline-block; padding: 3px 8px; border-radius: 10px; font-size: 11px; font-weight: bold; }}
    .badge.dup {{ background: #FFE5E5; color: #FF453A; }}
    .badge.orphan {{ background: #FFF0D4; color: #FF9F0A; }}
    .badge.missing {{ background: #E2F0D9; color: #385723; }}
</style>
</head>
<body>
<div class="container">
    <h1>Keynote Database Health Report</h1>
    <div class="subtitle">Generated on {date} for project keynote file: {file}</div>
    
    <div class="grid">
        <div class="card">
            <div class="value">{total}</div>
            <div class="label">Total Keys</div>
        </div>
        <div class="card">
            <div class="value warning">{dups}</div>
            <div class="label">Duplicate Keys</div>
        </div>
        <div class="card">
            <div class="value warning">{orphans}</div>
            <div class="label">Orphans</div>
        </div>
        <div class="card">
            <div class="value danger">{missing}</div>
            <div class="label">Missing from File</div>
        </div>
    </div>
    
    <h2>Duplicates &amp; Orphans Summary</h2>
    <table>
        <thead>
            <tr>
                <th>Key</th>
                <th>Issue Type</th>
            </tr>
        </thead>
        <tbody>
""".format(
                date=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                file=op.basename(self._kfile),
                total=total_keys,
                dups=len(dups),
                orphans=len(orphans),
                missing=len(missing_kns)
            )
            
            for d in dups:
                html += "<tr><td>{}</td><td><span class='badge dup'>DUPLICATE KEY</span></td></tr>".format(d)
            for o in orphans:
                html += "<tr><td>{}</td><td><span class='badge orphan'>ORPHAN KEYNOTE</span></td></tr>".format(o.key)
            if not dups and not orphans:
                html += "<tr><td colspan='2'>No duplicates or orphans found.</td></tr>"
                
            html += """
        </tbody>
    </table>
    
    <h2>Model Placements Missing From File</h2>
    <table>
        <thead>
            <tr>
                <th>Key</th>
                <th>Revit Placements Count</th>
            </tr>
        </thead>
        <tbody>
"""
            for m in missing_kns:
                html += "<tr><td>{}</td><td>{}</td></tr>".format(m, len(used[m]))
            if not missing_kns:
                html += "<tr><td colspan='2'>No missing model placements.</td></tr>"
                
            html += """
        </tbody>
    </table>
</div>
</body>
</html>
"""
            with codecs.open(kfile, "w", "utf_8") as f:
                f.write(html)
            self.statusLeft.Text = "Health report exported successfully."
            script.open_url(kfile)
        except Exception as ex:
            forms.alert("Export health report failed:\n" + str(ex))

    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================

    def change_keynote_file(self, sender, args):
        kfile = forms.pick_file("txt")
        if kfile:
            self._open_keynote_file(kfile)

    def show_keynote_file(self, sender, args):
        coreutils.show_entry_in_explorer(self._kfile)

    def import_keynotes(self, sender, args):
        kfile = forms.pick_file("txt")
        if kfile:
            res = forms.alert("Skip duplicate entries?", yes=True, no=True)
            try:
                self._backup_once("import")
                kdb.import_legacy_keynotes(self._conn, kfile, skip_dup=res)
                self._set_dirty(True)
            except Exception as ex:
                forms.alert("Import failed: %s" % ex)
            finally:
                self._update_full_tree()
                self._update_status_bar()

    def export_keynotes(self, sender, args):
        kfile = forms.save_file("txt")
        if kfile:
            try:
                kdb.export_legacy_keynotes(self._conn, kfile)
            except Exception as ex:
                forms.alert(str(ex))

    def export_visible_keynotes(self, sender, args):
        kfile = forms.save_file("txt")
        if kfile:
            include = set()
            for rk in self.current_keynotes or []:
                include.update(rk.collect_keys())
            try:
                kdb.export_legacy_keynotes(self._conn, kfile, include_keys=include)
            except Exception as ex:
                forms.alert(str(ex))

    # =========================================================================
    # P13 PRODUCTIVITY TOOLS
    # =========================================================================

    def backup_keynote_file(self, sender, args):
        try:
            backup_path = self._backup_keynote_file(reason="manual")
            if backup_path:
                self.statusLeft.Text = "Backup created: {}".format(backup_path)
            else:
                forms.alert("No keynote file is loaded.")
        except Exception as ex:
            forms.alert("Backup failed: {}".format(ex))

    def show_recent_files(self, sender, args):
        recent = [
            x for x in self._config.get_option("recent_keynote_files", [])
            if x and op.exists(x)
        ]
        if not recent:
            forms.alert("No recent keynote files found.")
            return
        selected = forms.SelectFromList.show(
            recent,
            title="Recent Keynote Files",
            button_name="Open",
            multiselect=False,
        )
        if selected:
            self._open_keynote_file(selected)

    def _open_keynote_file(self, kfile):
        if not kfile or not op.exists(kfile):
            forms.alert("Keynote file not found.")
            return

        def _set_file():
            with revit.Transaction("Set Keynote File"):
                revit.update.set_keynote_file(kfile, doc=revit.doc)

        def _reload():
            if self._conn:
                try:
                    self._conn.Dispose()
                except Exception:
                    pass
            self._determine_kfile()
            self._connect_kfile()
            self._register_recent_file()
            self._backup_done = False
            self._set_dirty(True)
            self.refresh(None, None)

        self._revit_run(_set_file, callback=_reload)

    def copy_keynote_key(self, sender, args):
        key, _ = self._selected_key_text()
        if key:
            self._copy_to_clipboard(key)

    def copy_keynote_text(self, sender, args):
        _, text = self._selected_key_text()
        if text is not None:
            self._copy_to_clipboard(text)

    def copy_keynote_key_text(self, sender, args):
        key, text = self._selected_key_text()
        if key:
            self._copy_to_clipboard("{}\t{}".format(key, text))

    def filter_used(self, sender, args):
        self.search_term = kdb.RKeynoteFilters.UsedOnly.code
        self._update_full_tree(fast_filter=True)

    def filter_unused(self, sender, args):
        self.search_term = kdb.RKeynoteFilters.UnusedOnly.code
        self._update_full_tree(fast_filter=True)

    def filter_visible_in_view(self, sender, args):
        self.search_term = kdb.RKeynoteFilters.ViewOnly.code
        self._update_full_tree()

    def duplicate_with_next_key(self, sender, args):
        sel = self.selected_keynote
        if not sel or sel.is_category or not sel.parent_key:
            return
        new_key = self._next_key_from(sel.key)
        try:
            self._save_undo_state()
            self._backup_once()
            kdb.add_keynote(self._conn, new_key, sel.text, sel.parent_key)
            self._set_dirty(True)
            self._update_full_tree()
            self._select_keynote_by_key(new_key)
        except Exception as ex:
            forms.alert("Duplicate failed: {}".format(ex))

    def move_to_category(self, sender, args):
        sel = self.selected_keynote
        if not sel or sel.is_category:
            return
        categories = self.all_categories
        options = ["{} - {}".format(x.key, x.text) for x in categories]
        selected = forms.SelectFromList.show(
            options,
            title="Move to Category",
            button_name="Move",
            multiselect=False,
        )
        if not selected:
            return
        target_key = selected.split(" - ")[0].strip()
        if target_key == sel.parent_key:
            return
        try:
            self._save_undo_state()
            self._backup_once()
            kdb.move_keynote(self._conn, sel.key, target_key)
            self._set_dirty(True)
            self._update_full_tree()
            self._select_keynote_by_key(sel.key)
        except Exception as ex:
            forms.alert("Move failed: {}".format(ex))

    def bulk_find_replace(self, sender, args):
        find_text = forms.ask_for_string(
            prompt="Find text in visible keynotes",
            title="Find Text",
        )
        if not find_text:
            return
        replace_text = forms.ask_for_string(
            prompt="Replace with",
            title="Replace Text",
            default="",
        )
        if replace_text is None:
            return

        targets = []
        for node in self._flat_nodes(self.current_keynotes):
            if node.locked:
                continue
            if find_text in (node.text or ""):
                targets.append(node)
        if not targets:
            forms.alert("No visible keynote text matches the search.")
            return
        if not forms.alert(
            "Replace text in {} visible records?".format(len(targets)),
            yes=True,
            no=True,
        ):
            return

        try:
            self._save_undo_state()
            self._backup_once()
            with kdb.BulkAction(self._conn):
                for node in targets:
                    new_text = (node.text or "").replace(find_text, replace_text)
                    if node.is_category:
                        kdb.update_category_title(self._conn, node.key, new_text)
                    else:
                        kdb.update_keynote_text(self._conn, node.key, new_text)
            self._set_dirty(True)
            self._update_full_tree()
            self.statusLeft.Text = "Replaced text in {} records".format(len(targets))
        except Exception as ex:
            forms.alert("Find and replace failed: {}".format(ex))

    def validate_keynotes(self, sender, args):
        cats = self.all_categories
        kns = self.all_keynotes
        cat_keys = [x.key for x in cats]
        kn_keys = [x.key for x in kns]
        all_keys = cat_keys + kn_keys
        duplicates = sorted([x for x in set(all_keys) if all_keys.count(x) > 1])
        empty_text = [x for x in cats + kns if not (x.text or "").strip()]
        parent_keys = set(cat_keys + kn_keys)
        orphans = [x for x in kns if x.parent_key not in parent_keys]
        locked = [x for x in cats + kns if x.locked]

        output.print_md("## P13 Keynote Validation")
        output.print_md("File: `{}`".format(self._kfile))
        output.print_md("- Groups: {}".format(len(cats)))
        output.print_md("- Keynotes: {}".format(len(kns)))
        output.print_md("- Duplicate keys: {}".format(len(duplicates)))
        output.print_md("- Empty text records: {}".format(len(empty_text)))
        output.print_md("- Orphan keynotes: {}".format(len(orphans)))
        output.print_md("- Locked records: {}".format(len(locked)))

        if duplicates:
            output.print_md("### Duplicate Keys")
            for key in duplicates:
                print(key)
        if empty_text:
            output.print_md("### Empty Text")
            for node in empty_text:
                print("{} | {}".format(node.key, node.parent_key or "GROUP"))
        if orphans:
            output.print_md("### Orphan Keynotes")
            for node in orphans:
                print("{} | missing parent {}".format(node.key, node.parent_key))
        if not duplicates and not empty_text and not orphans:
            self.statusLeft.Text = "Validation passed"
        else:
            self.statusLeft.Text = "Validation issues found in output"

    def audit_keynotes(self, sender, args):
        cats = self.all_categories
        kns = self.all_keynotes
        file_keys = set([x.key for x in cats] + [x.key for x in kns])
        used_keys = set(self._used_keysdict.keys())
        unused = sorted([x for x in kns if x.key not in used_keys], key=lambda x: x.key)
        missing = sorted([x for x in used_keys if x not in file_keys])

        output.print_md("## P13 Keynote Usage Audit")
        output.print_md("File: `{}`".format(self._kfile))
        output.print_md("- Used keys in model: {}".format(len(used_keys)))
        output.print_md("- Unused file keynotes: {}".format(len(unused)))
        output.print_md("- Model keys missing from file: {}".format(len(missing)))

        if missing:
            output.print_md("### Model Keys Missing From File")
            for key in missing:
                print("{} | {} placements".format(key, len(self._used_keysdict[key])))
        if unused:
            output.print_md("### Unused File Keynotes")
            for node in unused[:500]:
                print("{} | {}".format(node.key, node.text))
            if len(unused) > 500:
                print("... {} more".format(len(unused) - 500))
        self.statusLeft.Text = "Audit written to pyRevit output"
        if missing:
            res = forms.alert(
                u"พบ {} คีย์ในแบบจำลอง (Model) ที่ไม่มีอยู่ในไฟล์หลัก\nต้องการสร้างคีย์เหล่านี้โดยอัตโนมัติในหมวดหมู่ '_MISSING' หรือไม่?".format(len(missing)),
                yes=True, no=True
            )
            if res:
                self._save_undo_state()
                self._backup_once("audit_recovery")
                try:
                    # Check if category '_MISSING' exists
                    missing_cat = next((c for c in cats if c.key == "_MISSING"), None)
                    if not missing_cat:
                        kdb.add_category(self._conn, "_MISSING", "MISSING MODEL KEYS")
                    
                    with kdb.BulkAction(self._conn):
                        for m_key in missing:
                            kdb.add_keynote(self._conn, m_key, "Auto-created placeholder for missing key {}".format(m_key), "_MISSING")
                    
                    self._set_dirty(True)
                    self._update_full_tree()
                    forms.alert(u"เพิ่มคีย์ที่หายไป {} รายการภายใต้หมวดหมู่ '_MISSING' สำเร็จ".format(len(missing)))
                except Exception as ex:
                    forms.alert("Auto-add missing keys failed: {}".format(ex))

    def select_keynote_instances(self, sender, args):
        sel = self.selected_keynote
        if not sel:
            return
        element_ids = list(self._used_keysdict.get(sel.key, []))
        if not element_ids:
            self.statusLeft.Text = "No model instances found for '{}'".format(sel.key)
            return

        def _do_select():
            from System.Collections.Generic import List
            ids = List[DB.ElementId]()
            for eid in element_ids:
                ids.Add(eid)
            revit.uidoc.Selection.SetElementIds(ids)

        def _done():
            self.statusLeft.Text = "Selected {} instances for '{}'".format(
                len(element_ids), sel.key
            )

        self._revit_run(_do_select, callback=_done)

    # =========================================================================
    # CLOSE
    # =========================================================================

    def update_model(self, sender, args):
        """Queue keynote update transaction and keep window open."""
        if self._needs_update:

            def _do_update():
                with revit.Transaction("Update Keynotes"):
                    revit.update.update_linked_keynotes(doc=revit.doc)

            def _on_update_complete():
                self._set_dirty(False)
                forms.alert("Revit model updated successfully.", title="Success")

            self._revit_run(_do_update, callback=_on_update_complete)
        else:
            forms.alert("The Revit model is already up to date.", title="Up to Date")

    def _finalize_close(self):
        """Called on WPF thread after Revit update completes."""
        self._set_dirty(False)
        self._close_pending = True
        self.Close()

    def window_closing(self, sender, args):
        global _active_window

        # If we haven't synced yet and user closed via X button, ask
        if self._needs_update and not self._close_pending:
            res = forms.alert(
                "Keynote file has been modified.\n"
                "Sync changes to the Revit model before closing?",
                yes=True,
                no=True,
            )
            if res:
                args.Cancel = True

                def _do_update():
                    with revit.Transaction("Update Keynotes"):
                        revit.update.update_linked_keynotes(doc=revit.doc)

                self._close_pending = True
                self._revit_run(_do_update, callback=self._finalize_close)
                return

        if self._kfile_handler == "adc":
            try:
                adc.unlock_file(self._kfile_ext)
            except Exception:
                pass
        try:
            self.save_config()
        except Exception as ex:
            logger.debug("Save config failed | %s" % ex)
        if self._conn:
            try:
                self._conn.Dispose()
            except Exception:
                pass
        _active_window = None


# =============================================================================
# ENTRY POINT
# =============================================================================

def _convert_existing_file(kfile):
    # Create a temp file path for backing up the original keynote file
    temp_bak = script.get_data_file(op.basename(kfile), "bak")
    if op.exists(temp_bak):
        script.remove_data_file(temp_bak)
    
    # Create a temp file path for building the new DB locally
    temp_db = script.get_data_file(op.basename(kfile), "tmp_db")
    if op.exists(temp_db):
        script.remove_data_file(temp_db)

    try:
        shutil.copy2(kfile, temp_bak)
    except Exception as ex:
        raise Exception("Backup of keynote file failed: {}".format(ex))

    try:
        with open(temp_db, "w") as f:
            pass
        
        temp_conn = kdb.connect(temp_db)
        try:
            kdb.import_legacy_keynotes(temp_conn, temp_bak, skip_dup=True)
        finally:
            try:
                temp_conn.Dispose()
            except Exception:
                pass

        shutil.copy2(temp_db, kfile)

    except Exception as ex:
        try:
            shutil.copy2(temp_bak, kfile)
        except Exception:
            pass
        raise ex
    finally:
        if op.exists(temp_bak):
            script.remove_data_file(temp_bak)
        if op.exists(temp_db):
            script.remove_data_file(temp_db)


def _pre_check_keynote_file():
    """Ensure a valid keynote file is set and can be connected to before opening the window.
    This avoids running modal dialogs and transactions inside the WPF constructor,
    preventing native .NET / thread safety crashes in Revit 2026.4 (.NET 8)."""
    kfile = revit.query.get_local_keynote_file(doc=revit.doc)
    
    if not kfile:
        kfile_ext = revit.query.get_external_keynote_file(doc=revit.doc)
        if kfile_ext:
            if adc.is_available():
                try:
                    local_kfile = adc.get_local_path(kfile_ext)
                    if local_kfile and op.exists(local_kfile):
                        kfile = local_kfile
                except Exception:
                    pass

    if not kfile or not op.exists(kfile):
        forms.alert("Keynote file not found. Select a valid file.", title="File Not Found")
        picked = forms.pick_file("txt")
        if not picked:
            return False
            
        try:
            with revit.Transaction("Set Keynote File"):
                revit.update.set_keynote_file(picked, doc=revit.doc)
            kfile = picked
        except Exception as ex:
            forms.alert("Failed to set keynote file:\n" + str(ex))
            return False

    while True:
        try:
            conn = kdb.connect(kfile)
            conn.Dispose()
            return True
        except Exception as ex:
            logger.debug("Pre-check connection failed | %s" % ex)
            res = forms.alert(
                "Cannot connect to keynote file.\n"
                "It may need conversion to the new format.",
                options=["Convert", "Select Other", "Help"],
            )
            if res == "Convert":
                try:
                    _convert_existing_file(kfile)
                    forms.alert("Converted successfully!")
                except Exception as convex:
                    forms.alert("Conversion failed: %s" % convex)
                    return False
            elif res == "Select Other":
                picked = forms.pick_file("txt")
                if picked:
                    try:
                        with revit.Transaction("Set Keynote File"):
                            revit.update.set_keynote_file(picked, doc=revit.doc)
                        kfile = picked
                    except Exception as ex:
                        forms.alert("Failed to set keynote file:\n" + str(ex))
                        return False
                else:
                    return False
            elif res == "Help":
                script.open_url(
                    "https://www.notion.so/pyrevitlabs/"
                    "Manage-Keynotes-6f083d6f66fe43d68dc5d5407c8e19da"
                )
                return False
            else:
                return False


try:
    # Singleton: if already open, bring to front
    if _active_window and _active_window.IsLoaded:
        _active_window.Activate()
        _active_window.WindowState = framework.Windows.WindowState.Normal
    else:
        if _pre_check_keynote_file():
            _active_window = KeynoteManagerWindow(
                xaml_file_name="KeynoteManagerWindow.xaml",
                reset_config=__shiftclick__,  # pylint: disable=undefined-variable
            )
            _active_window.show(modal=False)
except Exception as kmex:
    forms.alert(str(kmex), expanded="Creating keynote manager window")
