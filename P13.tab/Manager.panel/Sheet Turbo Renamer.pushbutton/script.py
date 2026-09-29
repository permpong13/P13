# -*- coding: utf-8 -*-
"""P13 Sheet Turbo Renamer - Batch rename Revit Sheet Numbers and Sheet Names.
Inspired by File Renamer Turbo with live preview, duplicate protection, and Excel-like editing.
"""
from __future__ import print_function, division

__title__ = "Sheet Turbo\nRenamer"
__author__ = "เพิ่มพงษ์ ทวีกุล (P13)"
__doc__ = """Batch rename Sheet Numbers and Sheet Names in Revit.
Features:
- Search & Replace (Exact, Case Sensitive, Whole Word, Regex)
- Insert Text (Prefix, Suffix, or at Character Position)
- Remove & Trim (First/Last N characters, Range, Specific Text, Whitespace Trim)
- Auto-Numbering / Sequence (Start, Step, Zero-Padding, Prefix/Suffix)
- Change Letter Case (UPPERCASE, lowercase, Title Case, Sentence case)
- Direct in-grid editing without exporting to Excel
- Safe two-pass transaction with real-time duplicate collision protection and Ctrl+Z Undo
"""

import os
import re
import uuid
import clr

# .NET References
clr.AddReference("System")
clr.AddReference("System.Drawing")
clr.AddReference("System.Windows.Forms")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

import System
from System import Uri
from System.Collections.ObjectModel import ObservableCollection
from System.Windows import Visibility, RoutedEventHandler
from System.Windows.Controls import CheckBox
from System.Windows.Controls.Primitives import ButtonBase
from System.Windows.Media import SolidColorBrush, ColorConverter
from System.Windows.Media.Imaging import BitmapImage
from System.Windows.Threading import DispatcherTimer

from pyrevit import DB, UI, forms, revit, script

doc = revit.doc
uidoc = revit.uidoc
logger = script.get_logger()

try:
    text_type = unicode
except NameError:
    text_type = str

INVALID_REVIT_CHARS = r'[\\:\{\}\[\]|;<>?\'~]'


def hex_brush(hex_str):
    return SolidColorBrush(ColorConverter.ConvertFromString(hex_str))


# ----------------------------------------------------------------------
# Row Data Item
# ----------------------------------------------------------------------
class SheetRowItem(object):
    """Represents a single Sheet row in the Turbo Renamer DataGrid."""

    def __init__(self, sheet, is_selected=True):
        self.sheet = sheet
        self.Id = sheet.Id
        self.IdValue = sheet.Id.Value if hasattr(sheet.Id, "Value") else sheet.Id.IntegerValue
        self.IsPlaceholder = bool(getattr(sheet, "IsPlaceholder", False))
        self.IsIncluded = is_selected

        self.CurrentNumber = sheet.SheetNumber or ""
        self.CurrentName = sheet.Name or ""

        # Working state (for rule chaining / staging)
        self.WorkingNumber = self.CurrentNumber
        self.WorkingName = self.CurrentName

        # New preview values (bound to DataGrid columns)
        self.NewNumber = self.CurrentNumber
        self.NewName = self.CurrentName

        self.StatusText = "Unchanged"
        self.HasConflict = False
        self.IsModified = False

    def ToString(self):
        """CLR ToString method for Revit Journaling and WPF serialization."""
        return "{} - {}".format(self.CurrentNumber or "", self.CurrentName or "")

    def __str__(self):
        return self.ToString()

    def __repr__(self):
        return self.ToString()


# ----------------------------------------------------------------------
# Main Application Window
# ----------------------------------------------------------------------
class SheetTurboRenamerWindow(forms.WPFWindow):
    """Modern WPF Batch Renaming Window for Revit Sheets."""

    def __init__(self):
        xaml_path = os.path.join(os.path.dirname(__file__), "UI.xaml")
        forms.WPFWindow.__init__(self, xaml_path)

        self.doc = revit.doc
        self.uidoc = revit.uidoc

        self._all_items = []
        self._filtered_items = []
        self._is_updating = False

        # Debounce timer for live preview typing (350ms standard)
        self._preview_timer = DispatcherTimer()
        self._preview_timer.Interval = System.TimeSpan.FromMilliseconds(350)
        self._preview_timer.Tick += self._on_preview_timer_tick

        self._init_events()

    def _init_events(self):
        self.Loaded += self._on_window_loaded

        # Rule Inputs -> Live preview triggers
        rule_inputs = [
            self.TxtFind, self.TxtReplace, self.ChkMatchCase, self.ChkWholeWord, self.ChkRegex,
            self.TxtInsertText, self.RadioInsertPrefix, self.RadioInsertSuffix, self.RadioInsertPos, self.TxtInsertPosition,
            self.RadioRemoveFirstN, self.TxtRemoveFirstN, self.RadioRemoveLastN, self.TxtRemoveLastN,
            self.RadioRemoveRange, self.TxtRemoveRangeFrom, self.TxtRemoveRangeCount,
            self.RadioRemoveText, self.TxtRemoveText, self.ChkTrimSpaces, self.ChkCollapseSpaces,
            self.TxtNumStart, self.TxtNumStep, self.CboNumPadding, self.TxtNumPrefix, self.TxtNumSuffix,
            self.RadioNumReplace, self.RadioNumPrepend, self.RadioNumAppend,
            self.RadioCaseUpper, self.RadioCaseLower, self.RadioCaseTitle, self.RadioCaseSentence,
            self.RadioTargetNumber, self.RadioTargetName, self.RadioTargetBoth,
            self.TabModes
        ]

        for ctrl in rule_inputs:
            if hasattr(ctrl, "TextChanged"):
                ctrl.TextChanged += self._on_rule_input_changed
            if hasattr(ctrl, "Checked"):
                ctrl.Checked += self._on_rule_input_changed
            if hasattr(ctrl, "Unchecked"):
                ctrl.Unchecked += self._on_rule_input_changed
            if hasattr(ctrl, "SelectionChanged"):
                ctrl.SelectionChanged += self._on_rule_input_changed

        # Auto-select corresponding radio button on focus
        self.TxtInsertPosition.GotFocus += lambda s, e: setattr(self.RadioInsertPos, "IsChecked", True)
        self.TxtRemoveFirstN.GotFocus += lambda s, e: setattr(self.RadioRemoveFirstN, "IsChecked", True)
        self.TxtRemoveLastN.GotFocus += lambda s, e: setattr(self.RadioRemoveLastN, "IsChecked", True)
        self.TxtRemoveRangeFrom.GotFocus += lambda s, e: setattr(self.RadioRemoveRange, "IsChecked", True)
        self.TxtRemoveRangeCount.GotFocus += lambda s, e: setattr(self.RadioRemoveRange, "IsChecked", True)
        self.TxtRemoveText.GotFocus += lambda s, e: setattr(self.RadioRemoveText, "IsChecked", True)

        # Action Pipeline Buttons
        self.BtnRefreshPreview.Click += lambda s, e: self._calculate_preview()
        self.BtnStageRule.Click += self._on_stage_rule_click
        self.BtnResetAll.Click += self._on_reset_all_click
        self.BtnSwapNumName.Click += self._on_swap_num_name_click
        self.BtnCopyNumToName.Click += self._on_copy_num_to_name_click
        self.BtnCopyNameToNum.Click += self._on_copy_name_to_num_click

        # Filter & Selection Buttons
        self.TxtSearchFilter.TextChanged += self._on_filter_text_changed
        self.ChkIncludePlaceholders.Checked += self._on_filter_changed
        self.ChkIncludePlaceholders.Unchecked += self._on_filter_changed

        self.BtnCheckHighlighted.Click += self._on_check_highlighted_click
        self.BtnUncheckHighlighted.Click += self._on_uncheck_highlighted_click
        self.BtnSelectAll.Click += lambda s, e: self._set_all_selection(True)
        self.BtnSelectNone.Click += lambda s, e: self._set_all_selection(False)
        self.BtnInvertSelection.Click += self._on_invert_selection_click
        self.BtnSelectRevitActive.Click += self._on_select_revit_active_click
        self.ChkHeaderAll.Click += self._on_header_check_click

        # DataGrid Events (Safe handling without aggressive refresh)
        self.DgSheets.AddHandler(ButtonBase.ClickEvent, RoutedEventHandler(self._on_grid_checkbox_click))
        self.DgSheets.CellEditEnding += self.dg_cell_edit_ending
        self.DgSheets.PreviewKeyDown += self.dg_preview_keydown
        self.DgSheets.SelectionChanged += self._on_dg_selection_changed

        # Bottom Footer Buttons
        self.BtnClose.Click += lambda s, e: self.Close()
        self.BtnApplyToRevit.Click += self._on_apply_to_revit_click

    def _on_window_loaded(self, sender, args):
        # Set icon
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        if os.path.exists(icon_path):
            try:
                bi = BitmapImage()
                bi.BeginInit()
                bi.UriSource = Uri(icon_path)
                bi.EndInit()
                self.ImgAppIcon.Source = bi
            except Exception as ex:
                logger.warning("Could not load icon: {}".format(ex))

        self._load_sheets()
        self._calculate_preview()

    def _load_sheets(self):
        """Query sheets from active Revit document."""
        if not self.doc:
            forms.alert("No active document found.", title="Sheet Turbo Renamer")
            self.Close()
            return

        if self.doc.IsFamilyDocument:
            forms.alert("Sheet Turbo Renamer can only be run in a project document.", title="Sheet Turbo Renamer")
            self.Close()
            return

        collector = DB.FilteredElementCollector(self.doc).OfClass(DB.ViewSheet)
        sheets = [s for s in collector.ToElements() if not s.IsTemplate]

        # Determine Revit selection in Project Browser
        selected_ids = set()
        try:
            sel = self.uidoc.Selection.GetElementIds()
            for eid in sel:
                val = eid.Value if hasattr(eid, "Value") else eid.IntegerValue
                selected_ids.add(val)
        except Exception:
            pass

        has_active_revit_selection = len(selected_ids) > 0

        self._all_items = []
        for s in sheets:
            eid_val = s.Id.Value if hasattr(s.Id, "Value") else s.Id.IntegerValue
            is_checked = (eid_val in selected_ids) if has_active_revit_selection else True
            self._all_items.append(SheetRowItem(s, is_selected=is_checked))

        # Sort naturally by Sheet Number
        self._all_items.sort(key=lambda item: item.CurrentNumber)
        self._apply_filter()

    # ------------------------------------------------------------------
    # Filtering & Table Display
    # ------------------------------------------------------------------
    def _on_filter_text_changed(self, sender, args):
        self._apply_filter()

    def _on_filter_changed(self, sender, args):
        self._apply_filter()

    def _apply_filter(self):
        filter_text = (self.TxtSearchFilter.Text or "").strip().lower()
        include_placeholders = bool(self.ChkIncludePlaceholders.IsChecked)

        filtered = []
        for item in self._all_items:
            if not include_placeholders and item.IsPlaceholder:
                continue

            if filter_text:
                num_match = filter_text in item.CurrentNumber.lower() or filter_text in item.NewNumber.lower()
                name_match = filter_text in item.CurrentName.lower() or filter_text in item.NewName.lower()
                if not (num_match or name_match):
                    continue

            filtered.append(item)

        self._filtered_items = filtered
        self.DgSheets.ItemsSource = ObservableCollection[SheetRowItem](self._filtered_items)
        self._update_header_checkbox_state()
        self._update_stats()

    def _set_all_selection(self, select_val):
        try:
            for item in self._filtered_items:
                item.IsIncluded = select_val
            self._calculate_preview()
            self._update_header_checkbox_state()
            self._update_stats()
        except Exception as ex:
            logger.debug("Error setting selection: {}".format(ex))

    def _on_invert_selection_click(self, sender, args):
        try:
            for item in self._filtered_items:
                item.IsIncluded = not item.IsIncluded
            self._calculate_preview()
            self._update_header_checkbox_state()
            self._update_stats()
        except Exception as ex:
            logger.debug("Error inverting selection: {}".format(ex))

    def _on_select_revit_active_click(self, sender, args):
        try:
            selected_ids = set()
            try:
                sel = self.uidoc.Selection.GetElementIds()
                for eid in sel:
                    val = eid.Value if hasattr(eid, "Value") else eid.IntegerValue
                    selected_ids.add(val)
            except Exception:
                pass

            if not selected_ids:
                forms.alert("No sheets currently selected in Project Browser.", title="Sheet Turbo Renamer")
                return

            for item in self._all_items:
                item.IsIncluded = (item.IdValue in selected_ids)

            self._calculate_preview()
            self._update_header_checkbox_state()
            self._update_stats()
        except Exception as ex:
            logger.debug("Error selecting Revit active: {}".format(ex))

    def _on_header_check_click(self, sender, args):
        try:
            val = bool(self.ChkHeaderAll.IsChecked)
            for item in self._filtered_items:
                item.IsIncluded = val
            self._calculate_preview()
            self._update_stats()
        except Exception as ex:
            logger.debug("Error in header check click: {}".format(ex))

    def _update_header_checkbox_state(self):
        try:
            if not self._filtered_items:
                self.ChkHeaderAll.IsChecked = False
                return
            all_checked = all(i.IsIncluded for i in self._filtered_items)
            none_checked = not any(i.IsIncluded for i in self._filtered_items)
            if all_checked:
                self.ChkHeaderAll.IsChecked = True
            elif none_checked:
                self.ChkHeaderAll.IsChecked = False
            else:
                self.ChkHeaderAll.IsChecked = None  # Indeterminate
        except Exception:
            pass

    def _on_grid_checkbox_click(self, sender, args):
        try:
            if self._is_updating:
                return
            chk = args.OriginalSource
            if not isinstance(chk, CheckBox):
                return
            row = getattr(chk, "DataContext", None)
            if not isinstance(row, SheetRowItem):
                return

            selected_items = list(self.DgSheets.SelectedItems)
            if row in selected_items and len(selected_items) > 1:
                self._is_updating = True
                new_state = bool(chk.IsChecked)
                for item in selected_items:
                    if isinstance(item, SheetRowItem):
                        item.IsIncluded = new_state
                try:
                    self.DgSheets.Items.Refresh()
                except Exception:
                    pass
                self._is_updating = False

            self._calculate_preview()
            self._update_header_checkbox_state()
            self._update_stats()
        except Exception as ex:
            logger.debug("Error in grid checkbox click: {}".format(ex))

    def _on_check_highlighted_click(self, sender, args):
        try:
            selected_items = list(self.DgSheets.SelectedItems)
            if selected_items:
                self._is_updating = True
                for item in selected_items:
                    if isinstance(item, SheetRowItem):
                        item.IsIncluded = True
                try:
                    self.DgSheets.Items.Refresh()
                except Exception:
                    pass
                self._is_updating = False
                self._calculate_preview()
                self._update_header_checkbox_state()
                self._update_stats()
        except Exception as ex:
            logger.debug("Error in check highlighted: {}".format(ex))

    def _on_uncheck_highlighted_click(self, sender, args):
        try:
            selected_items = list(self.DgSheets.SelectedItems)
            if selected_items:
                self._is_updating = True
                for item in selected_items:
                    if isinstance(item, SheetRowItem):
                        item.IsIncluded = False
                try:
                    self.DgSheets.Items.Refresh()
                except Exception:
                    pass
                self._is_updating = False
                self._calculate_preview()
                self._update_header_checkbox_state()
                self._update_stats()
        except Exception as ex:
            logger.debug("Error in uncheck highlighted: {}".format(ex))

    def _on_dg_selection_changed(self, sender, args):
        try:
            self._update_header_checkbox_state()
            self._update_stats()
        except Exception:
            pass

    def dg_cell_edit_ending(self, sender, args):
        try:
            row = args.Row.Item
            if isinstance(row, SheetRowItem):
                row.WorkingNumber = row.NewNumber
                row.WorkingName = row.NewName
            self._validate_all()
            self._update_stats()
        except Exception as ex:
            logger.debug("Error in cell edit ending: {}".format(ex))

    def dg_preview_keydown(self, sender, args):
        try:
            # Allow spacebar to toggle checkbox on selected rows safely
            if args.Key == System.Windows.Input.Key.Space and self.DgSheets.SelectedItems:
                selected_items = list(self.DgSheets.SelectedItems)
                first_val = None
                self._is_updating = True
                for item in selected_items:
                    if isinstance(item, SheetRowItem):
                        if first_val is None:
                            first_val = not item.IsIncluded
                        item.IsIncluded = first_val
                try:
                    self.DgSheets.Items.Refresh()
                except Exception:
                    pass
                self._is_updating = False
                self._calculate_preview()
                self._update_header_checkbox_state()
                self._update_stats()
                args.Handled = True
        except Exception as ex:
            logger.debug("Error in keydown: {}".format(ex))

    # ------------------------------------------------------------------
    # Rule Evaluation Engine
    # ------------------------------------------------------------------
    def _on_rule_input_changed(self, sender, args):
        if self._is_updating:
            return
        if self.ChkLivePreview and self.ChkLivePreview.IsChecked:
            self._preview_timer.Stop()
            self._preview_timer.Start()

    def _on_preview_timer_tick(self, sender, args):
        try:
            self._preview_timer.Stop()
            self._calculate_preview()
        except Exception as ex:
            logger.debug("Error in timer tick: {}".format(ex))

    def _calculate_preview(self):
        if self._is_updating:
            return
        self._is_updating = True

        try:
            target_number = bool(self.RadioTargetNumber.IsChecked or self.RadioTargetBoth.IsChecked)
            target_name = bool(self.RadioTargetName.IsChecked or self.RadioTargetBoth.IsChecked)
            mode_idx = self.TabModes.SelectedIndex

            # Numbering counter setup
            num_start = self._safe_int(self.TxtNumStart.Text, 1)
            num_step = self._safe_int(self.TxtNumStep.Text, 1)
            selected_pad_item = self.CboNumPadding.SelectedItem
            padding = int(selected_pad_item.Tag) if selected_pad_item else 2
            num_prefix = self.TxtNumPrefix.Text or ""
            num_suffix = self.TxtNumSuffix.Text or ""

            counter_idx = 0
            for item in self._all_items:
                if not item.IsIncluded:
                    # Unselected: keep working state
                    item.NewNumber = item.WorkingNumber
                    item.NewName = item.WorkingName
                    continue

                # Calculate for Number
                if target_number:
                    item.NewNumber = self._apply_mode_rule(
                        item.WorkingNumber, mode_idx, counter_idx,
                        num_start, num_step, padding, num_prefix, num_suffix
                    )
                else:
                    item.NewNumber = item.WorkingNumber

                # Calculate for Name
                if target_name:
                    item.NewName = self._apply_mode_rule(
                        item.WorkingName, mode_idx, counter_idx,
                        num_start, num_step, padding, num_prefix, num_suffix
                    )
                else:
                    item.NewName = item.WorkingName

                counter_idx += 1

            self._validate_all()
            self._update_stats()

            # Safely refresh grid items
            try:
                self.DgSheets.Items.Refresh()
            except Exception:
                pass

        except Exception as ex:
            logger.debug("Error calculating preview: {}".format(ex))
        finally:
            self._is_updating = False

    def _apply_mode_rule(self, text, mode_idx, counter_idx, num_start, num_step, padding, num_prefix, num_suffix):
        """Transform a string according to active mode."""
        curr = text or ""

        # Mode 0: Search & Replace
        if mode_idx == 0:
            find_str = self.TxtFind.Text or ""
            replace_str = self.TxtReplace.Text or ""
            match_case = bool(self.ChkMatchCase.IsChecked)
            whole_word = bool(self.ChkWholeWord.IsChecked)
            use_regex = bool(self.ChkRegex.IsChecked)

            if not find_str:
                return curr

            if use_regex:
                flags = 0 if match_case else re.IGNORECASE
                try:
                    return re.sub(find_str, replace_str, curr, flags=flags)
                except Exception:
                    return curr
            else:
                if whole_word:
                    pattern = r'\b' + re.escape(find_str) + r'\b'
                    flags = 0 if match_case else re.IGNORECASE
                    return re.sub(pattern, replace_str, curr, flags=flags)
                else:
                    if match_case:
                        return curr.replace(find_str, replace_str)
                    else:
                        pattern = re.escape(find_str)
                        return re.sub(pattern, replace_str, curr, flags=re.IGNORECASE)

        # Mode 1: Insert Text
        elif mode_idx == 1:
            ins = self.TxtInsertText.Text or ""
            if not ins:
                return curr

            if self.RadioInsertPrefix.IsChecked:
                return ins + curr
            elif self.RadioInsertSuffix.IsChecked:
                return curr + ins
            elif self.RadioInsertPos.IsChecked:
                pos = self._safe_int(self.TxtInsertPosition.Text, 1) - 1
                pos = max(0, min(len(curr), pos))
                return curr[:pos] + ins + curr[pos:]

        # Mode 2: Remove & Trim
        elif mode_idx == 2:
            res = curr
            if self.RadioRemoveFirstN.IsChecked:
                n = self._safe_int(self.TxtRemoveFirstN.Text, 0)
                res = res[n:]
            elif self.RadioRemoveLastN.IsChecked:
                n = self._safe_int(self.TxtRemoveLastN.Text, 0)
                res = res[:-n] if n < len(res) else ""
            elif self.RadioRemoveRange.IsChecked:
                from_idx = self._safe_int(self.TxtRemoveRangeFrom.Text, 1) - 1
                count = self._safe_int(self.TxtRemoveRangeCount.Text, 0)
                from_idx = max(0, min(len(res), from_idx))
                to_idx = max(from_idx, min(len(res), from_idx + count))
                res = res[:from_idx] + res[to_idx:]
            elif self.RadioRemoveText.IsChecked:
                rem = self.TxtRemoveText.Text or ""
                if rem:
                    res = res.replace(rem, "")

            if self.ChkTrimSpaces.IsChecked:
                res = res.strip()
            if self.ChkCollapseSpaces.IsChecked:
                res = re.sub(r'\s+', ' ', res)
            return res

        # Mode 3: Auto-Numbering
        elif mode_idx == 3:
            val = num_start + (counter_idx * num_step)
            num_str = text_type(val)
            if len(num_str) < padding:
                num_str = num_str.zfill(padding)
            formatted = num_prefix + num_str + num_suffix

            if self.RadioNumReplace.IsChecked:
                return formatted
            elif self.RadioNumPrepend.IsChecked:
                return formatted + curr
            elif self.RadioNumAppend.IsChecked:
                return curr + formatted

        # Mode 4: Change Case
        elif mode_idx == 4:
            if self.RadioCaseUpper.IsChecked:
                return curr.upper()
            elif self.RadioCaseLower.IsChecked:
                return curr.lower()
            elif self.RadioCaseTitle.IsChecked:
                return curr.title()
            elif self.RadioCaseSentence.IsChecked:
                return (curr[0].upper() + curr[1:].lower()) if curr else ""

        return curr

    def _safe_int(self, val_str, default=0):
        try:
            return int(val_str)
        except Exception:
            return default

    # ------------------------------------------------------------------
    # Validation & Conflict Detection
    # ------------------------------------------------------------------
    def _validate_all(self):
        """Validate sheet uniqueness, empty names, and invalid characters."""
        # 1. Count occurrences of proposed NewNumber across all items
        number_counts = {}
        for item in self._all_items:
            num = (item.NewNumber or "").strip()
            number_counts[num] = number_counts.get(num, 0) + 1

        for item in self._all_items:
            num = (item.NewNumber or "").strip()
            name = (item.NewName or "").strip()

            is_modified = (item.NewNumber != item.CurrentNumber) or (item.NewName != item.CurrentName)
            item.IsModified = is_modified

            # Check Empty Sheet Number
            if not num:
                item.StatusText = "⚠ Empty Number"
                item.HasConflict = True
                continue

            # Check Invalid Revit Characters in Number or Name
            if re.search(INVALID_REVIT_CHARS, num) or re.search(INVALID_REVIT_CHARS, name):
                item.StatusText = "⚠ Invalid Char"
                item.HasConflict = True
                continue

            # Check Duplicate Number
            if number_counts.get(num, 0) > 1:
                if is_modified:
                    item.StatusText = "⚠ Duplicate: " + num
                    item.HasConflict = True
                    continue
                else:
                    item.StatusText = "⚠ Dup (Existing)"
                    item.HasConflict = False
                    continue

            item.HasConflict = False
            if is_modified:
                item.StatusText = "Modified ✓"
            else:
                item.StatusText = "Unchanged"

    def _update_stats(self):
        try:
            total = len(self._all_items)
            selected = sum(1 for i in self._all_items if i.IsIncluded)
            modified = sum(1 for i in self._all_items if i.IsModified)
            conflicts = sum(1 for i in self._all_items if i.HasConflict)

            self.TxtStatTotal.Text = str(total)
            self.TxtStatSelected.Text = str(selected)
            self.TxtStatModified.Text = str(modified)
            self.TxtStatConflicts.Text = str(conflicts)

            if conflicts > 0:
                self.BorderConflicts.Background = hex_brush("#FEE2E2")
                self.TxtStatConflicts.Foreground = hex_brush("#DC2626")
                self.TxtFooterStatus.Text = "⚠ Conflicts detected! Please resolve duplicate or invalid numbers."
                self.TxtFooterStatus.Foreground = hex_brush("#DC2626")
                self.BtnApplyToRevit.IsEnabled = False
            else:
                self.BorderConflicts.Background = hex_brush("#FEF2F2")
                self.TxtStatConflicts.Foreground = hex_brush("#991B1B")
                if modified > 0:
                    self.TxtFooterStatus.Text = "Ready • {} sheet(s) will be updated in Revit".format(modified)
                    self.TxtFooterStatus.Foreground = hex_brush("#047857")
                    self.BtnApplyToRevit.IsEnabled = True
                else:
                    self.TxtFooterStatus.Text = "Ready • No changes made yet"
                    self.TxtFooterStatus.Foreground = hex_brush("#0F172A")
                    self.BtnApplyToRevit.IsEnabled = False
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Staging & Pipeline Actions
    # ------------------------------------------------------------------
    def _on_stage_rule_click(self, sender, args):
        """Stage the current preview as the new working base for chaining."""
        try:
            for item in self._all_items:
                item.WorkingNumber = item.NewNumber
                item.WorkingName = item.NewName

            self._validate_all()
            self._update_stats()
            try:
                self.DgSheets.Items.Refresh()
            except Exception:
                pass

            forms.alert(
                "Rule applied to working list!\nYou can now configure another rule to chain on top of this.",
                title="Sheet Turbo Renamer"
            )
        except Exception as ex:
            logger.debug("Error staging rule: {}".format(ex))

    def _on_reset_all_click(self, sender, args):
        """Reset all working and preview values back to current Revit sheet values."""
        try:
            for item in self._all_items:
                item.WorkingNumber = item.CurrentNumber
                item.WorkingName = item.CurrentName
                item.NewNumber = item.CurrentNumber
                item.NewName = item.CurrentName

            self._validate_all()
            self._update_stats()
            try:
                self.DgSheets.Items.Refresh()
            except Exception:
                pass
        except Exception as ex:
            logger.debug("Error resetting all: {}".format(ex))

    def _on_swap_num_name_click(self, sender, args):
        """Swap Number and Name for selected rows."""
        try:
            for item in self._all_items:
                if item.IsIncluded:
                    item.WorkingNumber, item.WorkingName = item.WorkingName, item.WorkingNumber
                    item.NewNumber, item.NewName = item.WorkingNumber, item.WorkingName

            self._validate_all()
            self._update_stats()
            try:
                self.DgSheets.Items.Refresh()
            except Exception:
                pass
        except Exception as ex:
            logger.debug("Error swapping: {}".format(ex))

    def _on_copy_num_to_name_click(self, sender, args):
        try:
            for item in self._all_items:
                if item.IsIncluded:
                    item.WorkingName = item.WorkingNumber
                    item.NewName = item.WorkingNumber

            self._validate_all()
            self._update_stats()
            try:
                self.DgSheets.Items.Refresh()
            except Exception:
                pass
        except Exception as ex:
            logger.debug("Error copying num to name: {}".format(ex))

    def _on_copy_name_to_num_click(self, sender, args):
        try:
            for item in self._all_items:
                if item.IsIncluded:
                    item.WorkingNumber = item.WorkingName
                    item.NewNumber = item.WorkingName

            self._validate_all()
            self._update_stats()
            try:
                self.DgSheets.Items.Refresh()
            except Exception:
                pass
        except Exception as ex:
            logger.debug("Error copying name to num: {}".format(ex))

    # ------------------------------------------------------------------
    # Commit to Revit
    # ------------------------------------------------------------------
    def _on_apply_to_revit_click(self, sender, args):
        """Commit modified Sheet Numbers and Names to Revit using Two-Pass Atomic Transaction."""
        modified_items = [i for i in self._all_items if i.IsModified]
        if not modified_items:
            forms.alert("No sheets have been modified.", title="Sheet Turbo Renamer")
            return

        conflicts = [i for i in self._all_items if i.HasConflict]
        if conflicts:
            forms.alert(
                "Cannot apply changes while conflicts exist. Please resolve duplicate or empty numbers.",
                title="Sheet Turbo Renamer"
            )
            return

        # Confirm with user
        msg = "Are you sure you want to rename {} sheet(s) in Revit?".format(len(modified_items))
        if not forms.alert(msg, yes=True, no=True, title="P13 Sheet Turbo Renamer"):
            return

        success_count = 0
        try:
            with revit.Transaction("P13 Sheet Turbo Renamer"):
                # Pass 1: Assign unique temporary numbers to avoid Revit duplicate number collision during swap
                temp_map = {}
                for idx, item in enumerate(modified_items):
                    if item.NewNumber != item.CurrentNumber:
                        temp_num = "__TMP_TURBO_{}_{}__".format(str(uuid.uuid4())[:8], idx)
                        item.sheet.SheetNumber = temp_num
                        temp_map[item] = item.NewNumber

                # Pass 2: Set final Sheet Numbers
                for item, final_num in temp_map.items():
                    item.sheet.SheetNumber = final_num

                # Pass 3: Set final Sheet Names
                for item in modified_items:
                    if item.NewName != item.CurrentName:
                        item.sheet.Name = item.NewName

                success_count = len(modified_items)

            # Update working state to new values
            for item in modified_items:
                item.CurrentNumber = item.sheet.SheetNumber or ""
                item.CurrentName = item.sheet.Name or ""
                item.WorkingNumber = item.CurrentNumber
                item.WorkingName = item.CurrentName
                item.NewNumber = item.CurrentNumber
                item.NewName = item.CurrentName

            self._validate_all()
            self._update_stats()
            try:
                self.DgSheets.Items.Refresh()
            except Exception:
                pass

            forms.alert(
                "Successfully renamed {} sheet(s) in Revit!\nPress Ctrl+Z in Revit anytime if you wish to undo.".format(success_count),
                title="Sheet Turbo Renamer"
            )

        except Exception as ex:
            logger.error("Error renaming sheets: {}".format(ex))
            forms.alert("An error occurred while renaming sheets:\n{}".format(ex), title="Sheet Turbo Renamer")


# ----------------------------------------------------------------------
# Script Entry Point
# ----------------------------------------------------------------------
if __name__ == "__main__":
    app = SheetTurboRenamerWindow()
    app.ShowDialog()
