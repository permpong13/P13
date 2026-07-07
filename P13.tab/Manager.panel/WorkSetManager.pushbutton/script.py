# -*- coding: utf-8 -*-
"""Workset Manager Tool"""
__title__ = 'Workset\nManager'
__author__ = 'เพิ่มพงษ์'

import clr
import os
import json
import traceback
from collections import defaultdict
from datetime import datetime

# CLR references
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
clr.AddReference('System')

from System import EventArgs
from System.ComponentModel import BackgroundWorker
from System.Windows.Forms import (
    DialogResult, SaveFileDialog, OpenFileDialog,
    Form, Button, Label, ComboBox, GroupBox, CheckBox, Panel,
    ListView, View, ColumnHeader, TabControl, TabPage,
    MessageBox, MessageBoxButtons, MessageBoxIcon,
    BorderStyle, AnchorStyles, SelectionMode,
    TextBox, FormStartPosition, ComboBoxStyle,
    ColumnHeaderStyle, HorizontalAlignment, ProgressBar,
    ProgressBarStyle, FlatStyle, Cursors
)
from System.Collections.Generic import List, HashSet
from System.Drawing import (
    Point, Size, Font, FontStyle, Color, SystemColors,
    ContentAlignment
)

# pyRevit / Revit API
from pyrevit import revit, DB, UI
from pyrevit import forms
from pyrevit import script

doc = revit.doc
uidoc = revit.uidoc
logger = script.get_logger()
output = script.get_output()

def get_id_value(identifier):
    """Return an ElementId/WorksetId value across Revit API versions."""
    try:
        return identifier.Value
    except Exception:
        return identifier.IntegerValue

class WorksetManager:
    """Workset Manager Core Logic"""

    @staticmethod
    def get_all_worksets():
        """Get all worksets in the project"""
        try:
            if not doc.IsWorkshared:
                return []

            worksets = []
            workset_table = doc.GetWorksetTable()

            # Get all workset IDs
            workset_ids = DB.FilteredWorksetCollector(doc).ToWorksets()

            for workset in workset_ids:
                if workset.Kind == DB.WorksetKind.UserWorkset:
                    worksets.append(workset)

            return worksets
        except Exception as e:
            logger.error("Error getting worksets: {}".format(e))
            return []

    @staticmethod
    def get_element_count_by_workset():
        """Count elements in each workset"""
        element_count = defaultdict(int)
        try:
            # Use native workset filters so an 800k+ element cloud model is not
            # expanded into hundreds of thousands of managed API wrappers.
            for workset in WorksetManager.get_all_worksets():
                try:
                    workset_filter = DB.ElementWorksetFilter(workset.Id)
                    count = (DB.FilteredElementCollector(doc)
                             .WherePasses(workset_filter)
                             .WhereElementIsNotElementType()
                             .GetElementCount())
                    element_count[get_id_value(workset.Id)] = count
                except Exception:
                    continue

        except Exception as e:
            logger.error("Error counting elements: {}".format(e))

        return element_count

    @staticmethod
    def get_elements_in_workset(workset):
        """Get all elements in a specific workset"""
        elements = []
        try:
            workset_filter = DB.ElementWorksetFilter(workset.Id)
            all_elements = (DB.FilteredElementCollector(doc)
                            .WherePasses(workset_filter)
                            .WhereElementIsNotElementType())
            for element in all_elements:
                try:
                    if get_id_value(element.WorksetId) == get_id_value(workset.Id):
                        elements.append(element)
                except:
                    continue

        except Exception as e:
            logger.error("Error getting elements in workset: {}".format(e))

        return elements

    @staticmethod
    def move_elements_to_workset(elements, target_workset):
        """Move elements to target workset"""
        success_count = 0
        failed_count = 0
        failed_elements = []

        try:
            with revit.Transaction("Move Elements to Workset"):
                for element in elements:
                    try:
                        # Check if element can change workset
                        if element.WorksetId != target_workset.Id:
                            param = element.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM)
                            if param and not param.IsReadOnly:
                                param.Set(get_id_value(target_workset.Id))
                                success_count += 1
                            else:
                                failed_count += 1
                                failed_elements.append(element)
                    except Exception as e:
                        failed_count += 1
                        failed_elements.append(element)
                        logger.error("Error moving element: {}".format(e))

        except Exception as e:
            logger.error("Error in move transaction: {}".format(e))

        return success_count, failed_count, failed_elements

    @staticmethod
    def create_workset(name):
        """Create new workset"""
        try:
            with revit.Transaction("Create Workset"):
                new_workset = DB.Workset.Create(doc, name)
                return new_workset is not None
        except Exception as e:
            logger.error("Error creating workset: {}".format(e))
            return False

    @staticmethod
    def delete_workset(workset):
        """Delete workset - UPDATED VERSION WITH DIFFERENT ATTRIBUTE NAMES"""
        try:
            with revit.Transaction("Delete Workset"):
                # สร้าง DeleteWorksetSettings object
                settings = DB.DeleteWorksetSettings()
                
                # ลองใช้ชื่อ attribute ที่ต่างกัน
                # สำหรับ Revit 2020+ อาจใช้ชื่อเหล่านี้:
                if hasattr(settings, 'AllowDeletingLastWorkset'):
                    settings.AllowDeletingLastWorkset = False  # ไม่ลบ Workset สุดท้าย
                elif hasattr(settings, 'DeleteLastWorkset'):
                    settings.DeleteLastWorkset = False  # ไม่ลบ Workset สุดท้าย
                
                if hasattr(settings, 'AllowDeletingWorksetWithElements'):
                    settings.AllowDeletingWorksetWithElements = False  # ไม่ลบ Workset ที่มีองค์ประกอบ
                elif hasattr(settings, 'DeleteWorksetWithElements'):
                    settings.DeleteWorksetWithElements = False  # ไม่ลบ Workset ที่มีองค์ประกอบ
                
                # ใช้ static method ของ WorksetTable ด้วย DeleteWorksetSettings
                DB.WorksetTable.DeleteWorkset(doc, workset.Id, settings)
                return True
        except Exception as e:
            logger.error("Error deleting workset: {}".format(e))
            return False

    @staticmethod
    def can_delete_workset(workset):
        """Check if workset can be deleted - SIMPLIFIED VERSION"""
        try:
            # วิธีที่ง่ายที่สุด - ตรวจสอบว่า workset ว่างและไม่ใช่ workset เริ่มต้น
            workset_table = doc.GetWorksetTable()
            element_counts = WorksetManager.get_element_count_by_workset()
            default_workset = WorksetManager.get_default_workset()

            # ตรวจสอบจำนวนองค์ประกอบ
            element_count = element_counts.get(get_id_value(workset.Id), 0)
            if element_count > 0:
                return False, "Workset contains elements"

            # ตรวจสอบว่าเป็น workset เริ่มต้นหรือไม่
            if default_workset and get_id_value(workset.Id) == get_id_value(default_workset.Id):
                return False, "The active Workset cannot be deleted"

            # ตรวจสอบว่าเป็น workset สุดท้ายหรือไม่
            all_worksets = WorksetManager.get_all_worksets()
            user_worksets = [w for w in all_worksets if w.Kind == DB.WorksetKind.UserWorkset]
            if len(user_worksets) <= 1:
                return False, "The last Workset cannot be deleted"

            return True, "Can be deleted"

        except Exception as e:
            logger.error("Error checking if workset can be deleted: {}".format(e))
            return False, "Validation failed"

    @staticmethod
    def rename_workset(workset, new_name):
        """Rename workset"""
        try:
            with revit.Transaction("Rename Workset"):
                workset_table = doc.GetWorksetTable()
                workset_table.RenameWorkset(workset.Id, new_name)
                return True
        except Exception as e:
            logger.error("Error renaming workset: {}".format(e))
            return False

    @staticmethod
    def set_default_workset(workset):
        """Set default workset for new elements"""
        try:
            workset_table = doc.GetWorksetTable()
            workset_table.SetActiveWorksetId(workset.Id)
            return True
        except Exception as e:
            logger.error("Error setting default workset: {}".format(e))
            return False

    @staticmethod
    def get_default_workset():
        """Get current default workset"""
        try:
            workset_table = doc.GetWorksetTable()
            active_workset_id = workset_table.GetActiveWorksetId()
            return workset_table.GetWorkset(active_workset_id)
        except Exception as e:
            logger.error("Error getting default workset: {}".format(e))
            return None

    @staticmethod
    def select_elements_in_workset(workset):
        """Select all elements in workset"""
        try:
            elements = WorksetManager.get_elements_in_workset(workset)
            if elements:
                element_ids = [element.Id for element in elements]
                uidoc.Selection.SetElementIds(DB.List[DB.ElementId](element_ids))
                return len(elements)
            return 0
        except Exception as e:
            logger.error("Error selecting elements in workset: {}".format(e))
            return 0

    @staticmethod
    def move_selected_elements_to_workset(workset):
        """Move currently selected elements to workset"""
        try:
            selected_elements = [doc.GetElement(id) for id in uidoc.Selection.GetElementIds()]
            if not selected_elements:
                return 0, 0, []

            return WorksetManager.move_elements_to_workset(selected_elements, workset)
        except Exception as e:
            logger.error("Error moving selected elements: {}".format(e))
            return 0, 0, []

    @staticmethod
    def set_workset_visibility(view, workset, visible):
        """Set workset visibility in view"""
        try:
            workset_id = workset.Id
            workset_visibility = view.GetWorksetVisibility(workset_id)

            if visible:
                if workset_visibility == DB.WorksetVisibility.Hidden:
                    view.SetWorksetVisibility(workset_id, DB.WorksetVisibility.Visible)
            else:
                if workset_visibility == DB.WorksetVisibility.Visible:
                    view.SetWorksetVisibility(workset_id, DB.WorksetVisibility.Hidden)

            return True
        except Exception as e:
            logger.error("Error setting workset visibility: {}".format(e))
            return False

    @staticmethod
    def get_unused_worksets():
        """Get worksets that are not used (no elements and not default)"""
        try:
            all_worksets = WorksetManager.get_all_worksets()
            element_counts = WorksetManager.get_element_count_by_workset()
            default_workset = WorksetManager.get_default_workset()

            unused_worksets = []
            for workset in all_worksets:
                element_count = element_counts.get(get_id_value(workset.Id), 0)
                is_default = default_workset and get_id_value(workset.Id) == get_id_value(default_workset.Id)

                if element_count == 0 and not is_default:
                    unused_worksets.append(workset)

            return unused_worksets
        except Exception as e:
            logger.error("Error getting unused worksets: {}".format(e))
            return []

    @staticmethod
    def get_editable_items(enabled_groups=None):
        """Return Revit internal worksets shown in the native Worksets dialog."""
        enabled_groups = enabled_groups or set([
            "User-Created", "Families", "Project Standards", "Views"])
        items = []
        kind_groups = {
            DB.WorksetKind.UserWorkset: "User-Created",
            DB.WorksetKind.FamilyWorkset: "Families",
            DB.WorksetKind.StandardWorkset: "Project Standards",
            DB.WorksetKind.ViewWorkset: "Views"
        }
        for workset in DB.FilteredWorksetCollector(doc).ToWorksets():
            group = kind_groups.get(workset.Kind)
            if not group or group not in enabled_groups:
                continue
            name_parts = [part.strip() for part in workset.Name.split(":")]
            descriptor = {
                "group": group,
                "class": "{}Workset".format(group.replace("-", "").replace(" ", "")),
                "category": name_parts[0] if name_parts else group,
                "family": name_parts[1] if group == "Families" and len(name_parts) > 1 else "",
                "name": workset.Name
            }
            items.append((workset, descriptor))
        items.sort(key=lambda x: (
            x[1].get("group", "").lower(),
            x[1].get("category", "").lower(),
            x[1].get("family", "").lower(),
            x[1].get("name", "").lower()))
        return items

    @staticmethod
    def describe_editable_item(element, forced_group=None):
        category = "Uncategorized"
        try:
            if element.Category:
                category = element.Category.Name
        except Exception:
            pass
        name = ""
        try:
            name = element.Name or ""
        except Exception:
            pass
        family = ""
        if forced_group == "Families":
            family = name
        else:
            try:
                family = element.FamilyName or ""
            except Exception:
                pass
        runtime_class = element.GetType().Name
        group = forced_group or "Project Standards"
        if runtime_class in ("Family", "FamilySymbol"):
            group = "Families"
        elif forced_group == "Views":
            try:
                group = "Project Standards" if element.IsTemplate else "Views"
            except Exception:
                group = "Views"
        return {
            "group": group,
            "class": runtime_class,
            "category": category,
            "family": family,
            "name": name
        }

    @staticmethod
    def get_checkout_status(element_id):
        try:
            status = DB.WorksharingUtils.GetCheckoutStatus(doc, element_id)
            if status == DB.CheckoutStatus.OwnedByCurrentUser:
                return "Owned by me"
            if status == DB.CheckoutStatus.OwnedByOtherUser:
                tooltip = DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, element_id)
                owner = tooltip.Owner if tooltip else "another user"
                return "Owned by {}".format(owner or "another user")
            return "Available"
        except Exception:
            return "Unknown"

    @staticmethod
    def get_item_checkout_status(item, descriptor):
        if descriptor.get("class", "").endswith("Workset"):
            try:
                if item.IsEditable:
                    return "Owned by me"
                return "Owned by {}".format(item.Owner) if item.Owner else "Available"
            except Exception:
                return "Unknown"
        return WorksetManager.get_checkout_status(item.Id)

    @staticmethod
    def get_project_families():
        """Return loadable project families without expanding their symbols."""
        families = []
        collector = DB.FilteredElementCollector(doc).OfClass(DB.Family)
        for family in collector:
            try:
                if family.IsValidObject and family.Name:
                    families.append(family)
            except Exception:
                continue
        families.sort(key=lambda family: family.Name.lower())
        return families

    @staticmethod
    def get_family_type_items(family):
        """Resolve symbols only for one selected family."""
        items = []
        category = "Uncategorized"
        try:
            if family.FamilyCategory:
                category = family.FamilyCategory.Name
        except Exception:
            pass
        for symbol_id in family.GetFamilySymbolIds():
            try:
                symbol = doc.GetElement(symbol_id)
                if not symbol or not symbol.IsValidObject:
                    continue
                type_name = ""
                try:
                    type_name = symbol.Name or ""
                except Exception:
                    name_parameter = symbol.get_Parameter(
                        DB.BuiltInParameter.SYMBOL_NAME_PARAM)
                    if name_parameter:
                        type_name = name_parameter.AsString() or ""
                if not type_name:
                    continue
                descriptor = {
                    "group": "Family Types",
                    "class": "FamilySymbol",
                    "category": category,
                    "family": family.Name,
                    "name": type_name
                }
                items.append((symbol, descriptor))
            except Exception:
                continue
        items.sort(key=lambda item: item[1].get("name", "").lower())
        return items

    @staticmethod
    def checkout_items(elements):
        """Borrow only the supplied elements. Returns (owned ids, failed ids)."""
        requested = List[DB.ElementId]()
        requested_worksets = HashSet[DB.WorksetId]()
        item_ids = []
        for item, descriptor in elements:
            if descriptor.get("class", "").endswith("Workset"):
                requested_worksets.Add(item.Id)
                item_ids.append(("workset", get_id_value(item.Id)))
            else:
                requested.Add(item.Id)
                item_ids.append(("element", get_id_value(item.Id)))
        owned = set()
        if requested.Count:
            try:
                checked_out = DB.WorksharingUtils.CheckoutElements(doc, requested)
                for eid in checked_out:
                    owned.add(("element", get_id_value(eid)))
            except Exception as ex:
                logger.error("Element checkout failed: {}".format(ex))
        if requested_worksets.Count:
            try:
                checked_out_worksets = DB.WorksharingUtils.CheckoutWorksets(
                    doc, requested_worksets)
                for wid in checked_out_worksets:
                    owned.add(("workset", get_id_value(wid)))
            except Exception as ex:
                logger.error("Workset checkout failed: {}".format(ex))
        failed = [item_id for item_id in item_ids if item_id not in owned]
        return owned, failed

class WorksetManagerForm(Form):
    def __init__(self):
        self.Text = "Workset Manager"
        self.Size = Size(1240, 860)
        self.StartPosition = FormStartPosition.CenterScreen
        self.Font = Font("Microsoft Sans Serif", 9)
        self.BackColor = Color.FromArgb(242, 245, 247)
        self.MinimumSize = Size(1180, 860)

        # Data
        self.all_worksets = []
        self.worksets_with_elements = []
        self.empty_worksets = []
        self.element_counts = {}
        self.editable_items = []
        self.profile_rules = []
        self.ownership_checked_keys = set()
        self.ownership_status_cache = {}
        self.updating_ownership_list = False
        self.ownership_loaded = False
        self.project_families = []
        self.family_type_items = {}
        self.current_family_type_items = []
        self.family_type_checked_keys = set()
        self.family_type_status_cache = {}
        self.updating_family_types = False
        self.settings_path = os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")),
            "pyRevit", "P13", "WorksetManager.settings.json")

        # Search boxes
        self.search_box_all = None
        self.search_box_with = None
        self.search_box_empty = None

        # Initialize UI
        self.InitializeComponents()

        # Load data
        self.LoadWorksets()

    def InitializeComponents(self):
        # Application header
        header = Panel()
        header.Location = Point(0, 0)
        header.Size = Size(1240, 72)
        header.BackColor = Color.FromArgb(31, 55, 78)
        header.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
        self.Controls.Add(header)

        title_label = Label()
        title_label.Text = "WORKSET MANAGER"
        title_label.Location = Point(24, 10)
        title_label.Size = Size(500, 30)
        title_label.Font = Font("Microsoft Sans Serif", 16, FontStyle.Bold)
        title_label.ForeColor = Color.White
        header.Controls.Add(title_label)

        subtitle = Label()
        subtitle.Text = "Worksets, element placement, and granular ownership profiles"
        subtitle.Location = Point(26, 41)
        subtitle.Size = Size(620, 20)
        subtitle.ForeColor = Color.FromArgb(205, 220, 232)
        header.Controls.Add(subtitle)

        close_header = Button()
        close_header.Text = "Close"
        close_header.Location = Point(1125, 19)
        close_header.Size = Size(82, 34)
        close_header.Anchor = AnchorStyles.Top | AnchorStyles.Right
        close_header.FlatStyle = FlatStyle.Flat
        close_header.FlatAppearance.BorderColor = Color.FromArgb(120, 145, 165)
        close_header.ForeColor = Color.White
        close_header.BackColor = Color.FromArgb(45, 75, 100)
        close_header.Click += self.CloseForm
        header.Controls.Add(close_header)

        # Main Tab Control
        self.tab_control = TabControl()
        self.tab_control.Location = Point(20, 88)
        self.tab_control.Size = Size(1185, 500)
        self.tab_control.Anchor = (AnchorStyles.Top | AnchorStyles.Left |
                                   AnchorStyles.Right)

        # Tab 1: All Worksets
        self.tab_all = TabPage()
        self.tab_all.Text = "All Worksets"
        self.tab_all.BackColor = Color.White

        # Tab 2: Worksets with Elements
        self.tab_with_elements = TabPage()
        self.tab_with_elements.Text = "Worksets with Elements"
        self.tab_with_elements.BackColor = Color.White

        # Tab 3: Empty Worksets
        self.tab_empty = TabPage()
        self.tab_empty.Text = "Empty Worksets"
        self.tab_empty.BackColor = Color.White

        self.tab_ownership = TabPage()
        self.tab_ownership.Text = "Item Ownership"
        self.tab_ownership.BackColor = Color.White

        self.tab_family_types = TabPage()
        self.tab_family_types.Text = "Family Type Ownership"
        self.tab_family_types.BackColor = Color.White

        self.tab_control.Controls.Add(self.tab_all)
        self.tab_control.Controls.Add(self.tab_with_elements)
        self.tab_control.Controls.Add(self.tab_empty)
        self.tab_control.Controls.Add(self.tab_ownership)
        self.tab_control.Controls.Add(self.tab_family_types)
        self.tab_control.SelectedIndexChanged += self.OnMainTabChanged
        self.Controls.Add(self.tab_control)

        # Initialize tabs
        self.InitializeAllWorksetsTab()
        self.InitializeWithElementsTab()
        self.InitializeEmptyWorksetsTab()
        self.InitializeOwnershipTab()
        self.InitializeFamilyTypeTab()

        # Action buttons
        self.InitializeActionButtons()
        self.ApplyButtonStyles(self)

    def ApplyButtonStyles(self, parent):
        """Apply a consistent compact style without changing semantic colors."""
        for control in parent.Controls:
            if isinstance(control, Button):
                control.FlatStyle = FlatStyle.Flat
                control.FlatAppearance.BorderColor = Color.FromArgb(165, 177, 188)
                control.FlatAppearance.BorderSize = 1
                if control.BackColor == SystemColors.Control:
                    control.BackColor = Color.FromArgb(248, 249, 250)
            if control.Controls.Count:
                self.ApplyButtonStyles(control)

    def InitializeAllWorksetsTab(self):
        # Filter section
        filter_group = GroupBox()
        filter_group.Text = "Filter"
        filter_group.Location = Point(20, 20)
        filter_group.Size = Size(1135, 60)
        self.tab_all.Controls.Add(filter_group)

        # Search box
        search_label = Label()
        search_label.Text = "Search:"
        search_label.Location = Point(20, 25)
        search_label.Size = Size(50, 20)
        filter_group.Controls.Add(search_label)

        self.search_box_all = TextBox()
        self.search_box_all.Location = Point(80, 22)
        self.search_box_all.Size = Size(200, 25)
        self.search_box_all.Tag = "all"
        self.search_box_all.TextChanged += self.OnSearchTextChanged
        filter_group.Controls.Add(self.search_box_all)

        # Refresh button
        refresh_btn = Button()
        refresh_btn.Text = "Refresh"
        refresh_btn.Location = Point(300, 20)
        refresh_btn.Size = Size(80, 30)
        refresh_btn.Click += self.RefreshWorksets
        filter_group.Controls.Add(refresh_btn)

        # Clear search button
        clear_btn = Button()
        clear_btn.Text = "Clear"
        clear_btn.Location = Point(390, 20)
        clear_btn.Size = Size(80, 30)
        clear_btn.Tag = "all"
        clear_btn.Click += self.OnClearSearchClicked
        filter_group.Controls.Add(clear_btn)

        # Default workset info
        self.default_workset_label = Label()
        self.default_workset_label.Location = Point(510, 25)
        self.default_workset_label.Size = Size(560, 20)
        self.default_workset_label.Text = "Loading..."
        filter_group.Controls.Add(self.default_workset_label)

        # Worksets list
        self.all_worksets_list = ListView()
        self.all_worksets_list.Location = Point(20, 90)
        self.all_worksets_list.Size = Size(1135, 325)
        self.all_worksets_list.View = View.Details
        self.all_worksets_list.FullRowSelect = True
        self.all_worksets_list.GridLines = True
        self.all_worksets_list.MultiSelect = True
        self.all_worksets_list.CheckBoxes = True

        # Add columns
        self.all_worksets_list.Columns.Add("Select", 50)
        self.all_worksets_list.Columns.Add("Workset Name", 400)
        self.all_worksets_list.Columns.Add("Element Count", 130)
        self.all_worksets_list.Columns.Add("Status", 130)
        self.all_worksets_list.Columns.Add("Owner", 250)
        self.all_worksets_list.Columns.Add("ID", 100)

        self.tab_all.Controls.Add(self.all_worksets_list)

        # Selection buttons
        select_all_btn = Button()
        select_all_btn.Text = "Select All"
        select_all_btn.Location = Point(20, 425)
        select_all_btn.Size = Size(100, 30)
        select_all_btn.Click += lambda s, e: self.SelectAllItems(self.all_worksets_list)
        self.tab_all.Controls.Add(select_all_btn)

        select_none_btn = Button()
        select_none_btn.Text = "Select None"
        select_none_btn.Location = Point(130, 425)
        select_none_btn.Size = Size(100, 30)
        select_none_btn.Click += lambda s, e: self.SelectNoneItems(self.all_worksets_list)
        self.tab_all.Controls.Add(select_none_btn)

    def InitializeWithElementsTab(self):
        # Filter section
        filter_group = GroupBox()
        filter_group.Text = "Filter"
        filter_group.Location = Point(20, 20)
        filter_group.Size = Size(1135, 60)
        self.tab_with_elements.Controls.Add(filter_group)

        search_label = Label()
        search_label.Text = "Search:"
        search_label.Location = Point(20, 25)
        search_label.Size = Size(50, 20)
        filter_group.Controls.Add(search_label)

        self.search_box_with = TextBox()
        self.search_box_with.Location = Point(80, 22)
        self.search_box_with.Size = Size(200, 25)
        self.search_box_with.Tag = "with"
        self.search_box_with.TextChanged += self.OnSearchTextChanged
        filter_group.Controls.Add(self.search_box_with)

        clear_btn = Button()
        clear_btn.Text = "Clear"
        clear_btn.Location = Point(300, 20)
        clear_btn.Size = Size(80, 30)
        clear_btn.Tag = "with"
        clear_btn.Click += self.OnClearSearchClicked
        filter_group.Controls.Add(clear_btn)

        # Worksets with elements list
        self.with_elements_list = ListView()
        self.with_elements_list.Location = Point(20, 90)
        self.with_elements_list.Size = Size(1135, 325)
        self.with_elements_list.View = View.Details
        self.with_elements_list.FullRowSelect = True
        self.with_elements_list.GridLines = True
        self.with_elements_list.MultiSelect = True
        self.with_elements_list.CheckBoxes = True

        self.with_elements_list.Columns.Add("Select", 50)
        self.with_elements_list.Columns.Add("Workset Name", 400)
        self.with_elements_list.Columns.Add("Element Count", 130)
        self.with_elements_list.Columns.Add("Status", 130)
        self.with_elements_list.Columns.Add("Owner", 250)
        self.with_elements_list.Columns.Add("ID", 100)

        self.tab_with_elements.Controls.Add(self.with_elements_list)

        # Selection buttons
        select_all_btn = Button()
        select_all_btn.Text = "Select All"
        select_all_btn.Location = Point(20, 425)
        select_all_btn.Size = Size(100, 30)
        select_all_btn.Click += lambda s, e: self.SelectAllItems(self.with_elements_list)
        self.tab_with_elements.Controls.Add(select_all_btn)

        select_none_btn = Button()
        select_none_btn.Text = "Select None"
        select_none_btn.Location = Point(130, 425)
        select_none_btn.Size = Size(100, 30)
        select_none_btn.Click += lambda s, e: self.SelectNoneItems(self.with_elements_list)
        self.tab_with_elements.Controls.Add(select_none_btn)

    def InitializeEmptyWorksetsTab(self):
        # Filter section
        filter_group = GroupBox()
        filter_group.Text = "Filter"
        filter_group.Location = Point(20, 20)
        filter_group.Size = Size(1135, 60)
        self.tab_empty.Controls.Add(filter_group)

        search_label = Label()
        search_label.Text = "Search:"
        search_label.Location = Point(20, 25)
        search_label.Size = Size(50, 20)
        filter_group.Controls.Add(search_label)

        self.search_box_empty = TextBox()
        self.search_box_empty.Location = Point(80, 22)
        self.search_box_empty.Size = Size(200, 25)
        self.search_box_empty.Tag = "empty"
        self.search_box_empty.TextChanged += self.OnSearchTextChanged
        filter_group.Controls.Add(self.search_box_empty)

        clear_btn = Button()
        clear_btn.Text = "Clear"
        clear_btn.Location = Point(300, 20)
        clear_btn.Size = Size(80, 30)
        clear_btn.Tag = "empty"
        clear_btn.Click += self.OnClearSearchClicked
        filter_group.Controls.Add(clear_btn)

        # Empty worksets list
        self.empty_worksets_list = ListView()
        self.empty_worksets_list.Location = Point(20, 90)
        self.empty_worksets_list.Size = Size(1135, 325)
        self.empty_worksets_list.View = View.Details
        self.empty_worksets_list.FullRowSelect = True
        self.empty_worksets_list.GridLines = True
        self.empty_worksets_list.MultiSelect = True
        self.empty_worksets_list.CheckBoxes = True

        self.empty_worksets_list.Columns.Add("Select", 50)
        self.empty_worksets_list.Columns.Add("Workset Name", 500)
        self.empty_worksets_list.Columns.Add("Status", 150)
        self.empty_worksets_list.Columns.Add("Owner", 300)
        self.empty_worksets_list.Columns.Add("ID", 100)

        self.tab_empty.Controls.Add(self.empty_worksets_list)

        # Selection buttons
        select_all_btn = Button()
        select_all_btn.Text = "Select All"
        select_all_btn.Location = Point(20, 425)
        select_all_btn.Size = Size(100, 30)
        select_all_btn.Click += lambda s, e: self.SelectAllItems(self.empty_worksets_list)
        self.tab_empty.Controls.Add(select_all_btn)

        select_none_btn = Button()
        select_none_btn.Text = "Select None"
        select_none_btn.Location = Point(130, 425)
        select_none_btn.Size = Size(100, 30)
        select_none_btn.Click += lambda s, e: self.SelectNoneItems(self.empty_worksets_list)
        self.tab_empty.Controls.Add(select_none_btn)

    def InitializeOwnershipTab(self):
        info = Label()
        info.Text = ("Borrow individual project items without owning their entire Workset. "
                     "Filter by category, family, type name, or class.")
        info.Location = Point(20, 15)
        info.Size = Size(970, 35)
        self.tab_ownership.Controls.Add(info)

        search_label = Label()
        search_label.Text = "Search items"
        search_label.Location = Point(20, 49)
        search_label.Size = Size(90, 22)
        self.tab_ownership.Controls.Add(search_label)

        self.ownership_search = TextBox()
        self.ownership_search.Location = Point(110, 47)
        self.ownership_search.Size = Size(290, 25)
        self.ownership_search.TextChanged += self.OnOwnershipSearchChanged
        self.tab_ownership.Controls.Add(self.ownership_search)

        refresh = Button()
        refresh.Text = "Load / Refresh Items"
        refresh.Location = Point(412, 44)
        refresh.Size = Size(140, 30)
        refresh.Click += self.RefreshOwnershipItems
        self.tab_ownership.Controls.Add(refresh)

        show_group = GroupBox()
        show_group.Text = "Show"
        show_group.Location = Point(565, 32)
        show_group.Size = Size(570, 48)
        self.tab_ownership.Controls.Add(show_group)

        self.ownership_group_checks = {}
        group_names = ["User-Created", "Families", "Project Standards", "Views"]
        group_widths = [115, 90, 150, 80]
        x_pos = 10
        for index, group_name in enumerate(group_names):
            checkbox = CheckBox()
            checkbox.Text = group_name
            checkbox.Location = Point(x_pos, 17)
            checkbox.Size = Size(group_widths[index], 22)
            checkbox.Checked = group_name in ("User-Created", "Families")
            checkbox.Tag = group_name
            checkbox.CheckedChanged += self.OnOwnershipGroupChanged
            show_group.Controls.Add(checkbox)
            self.ownership_group_checks[group_name] = checkbox
            x_pos += group_widths[index] + 5

        self.ownership_list = ListView()
        self.ownership_list.Location = Point(20, 88)
        self.ownership_list.Size = Size(1135, 315)
        self.ownership_list.View = View.Details
        self.ownership_list.FullRowSelect = True
        self.ownership_list.GridLines = True
        self.ownership_list.CheckBoxes = True
        self.ownership_list.ItemCheck += self.OnOwnershipItemCheck
        self.ownership_list.Columns.Add("Select", 55)
        self.ownership_list.Columns.Add("Group", 125)
        self.ownership_list.Columns.Add("Category", 145)
        self.ownership_list.Columns.Add("Family", 165)
        self.ownership_list.Columns.Add("Name", 200)
        self.ownership_list.Columns.Add("Class", 120)
        self.ownership_list.Columns.Add("Ownership", 145)
        self.tab_ownership.Controls.Add(self.ownership_list)

        checkout = Button()
        checkout.Text = "Borrow Checked Items"
        checkout.Location = Point(20, 415)
        checkout.Size = Size(160, 32)
        checkout.BackColor = Color.LightGreen
        checkout.Click += self.CheckoutOwnershipItems
        self.tab_ownership.Controls.Add(checkout)

        export_btn = Button()
        export_btn.Text = "Export Profile"
        export_btn.Location = Point(195, 415)
        export_btn.Size = Size(120, 32)
        export_btn.Click += self.ExportOwnershipProfile
        self.tab_ownership.Controls.Add(export_btn)

        import_btn = Button()
        import_btn.Text = "Import Profile"
        import_btn.Location = Point(325, 415)
        import_btn.Size = Size(120, 32)
        import_btn.Click += self.ImportOwnershipProfile
        self.tab_ownership.Controls.Add(import_btn)

        select_all = Button()
        select_all.Text = "Check Visible"
        select_all.Location = Point(460, 415)
        select_all.Size = Size(110, 32)
        select_all.Click += lambda s, e: self.SelectAllItems(self.ownership_list)
        self.tab_ownership.Controls.Add(select_all)

        select_none = Button()
        select_none.Text = "Clear Checks"
        select_none.Location = Point(580, 415)
        select_none.Size = Size(110, 32)
        select_none.Click += lambda s, e: self.SelectNoneItems(self.ownership_list)
        self.tab_ownership.Controls.Add(select_none)

    def InitializeFamilyTypeTab(self):
        info = Label()
        info.Text = ("Borrow individual Family Types. This protects type names and type parameters; "
                     "family geometry remains controlled by Family ownership.")
        info.Location = Point(20, 15)
        info.Size = Size(1110, 32)
        self.tab_family_types.Controls.Add(info)

        family_label = Label()
        family_label.Text = "Family Search"
        family_label.Location = Point(20, 54)
        family_label.Size = Size(85, 22)
        self.tab_family_types.Controls.Add(family_label)

        self.family_search = TextBox()
        self.family_search.Location = Point(108, 51)
        self.family_search.Size = Size(220, 25)
        self.family_search.TextChanged += self.OnFamilySearchChanged
        self.tab_family_types.Controls.Add(self.family_search)

        load_families = Button()
        load_families.Text = "Load Families"
        load_families.Location = Point(338, 48)
        load_families.Size = Size(120, 30)
        load_families.Click += self.LoadProjectFamilies
        self.tab_family_types.Controls.Add(load_families)

        type_search_label = Label()
        type_search_label.Text = "Type Search"
        type_search_label.Location = Point(655, 54)
        type_search_label.Size = Size(75, 22)
        self.tab_family_types.Controls.Add(type_search_label)

        self.family_type_search = TextBox()
        self.family_type_search.Location = Point(735, 51)
        self.family_type_search.Size = Size(300, 25)
        self.family_type_search.TextChanged += self.OnFamilyTypeSearchChanged
        self.tab_family_types.Controls.Add(self.family_type_search)

        self.family_list = ListView()
        self.family_list.Location = Point(20, 88)
        self.family_list.Size = Size(340, 315)
        self.family_list.View = View.Details
        self.family_list.FullRowSelect = True
        self.family_list.GridLines = True
        self.family_list.MultiSelect = False
        self.family_list.HideSelection = False
        self.family_list.SelectedIndexChanged += self.OnFamilySelectionChanged
        self.family_list.Columns.Add("Family", 235)
        self.family_list.Columns.Add("Category", 100)
        self.tab_family_types.Controls.Add(self.family_list)

        self.family_type_list = ListView()
        self.family_type_list.Location = Point(375, 88)
        self.family_type_list.Size = Size(780, 315)
        self.family_type_list.View = View.Details
        self.family_type_list.FullRowSelect = True
        self.family_type_list.GridLines = True
        self.family_type_list.CheckBoxes = True
        self.family_type_list.ItemCheck += self.OnFamilyTypeItemCheck
        self.family_type_list.Columns.Add("Select", 55)
        self.family_type_list.Columns.Add("Category", 140)
        self.family_type_list.Columns.Add("Family", 220)
        self.family_type_list.Columns.Add("Type", 220)
        self.family_type_list.Columns.Add("Ownership", 140)
        self.tab_family_types.Controls.Add(self.family_type_list)

        borrow = Button()
        borrow.Text = "Borrow Checked Types"
        borrow.Location = Point(20, 415)
        borrow.Size = Size(170, 32)
        borrow.BackColor = Color.LightGreen
        borrow.Click += self.CheckoutFamilyTypes
        self.tab_family_types.Controls.Add(borrow)

        export_btn = Button()
        export_btn.Text = "Export Type Profile"
        export_btn.Location = Point(205, 415)
        export_btn.Size = Size(145, 32)
        export_btn.Click += self.ExportFamilyTypeProfile
        self.tab_family_types.Controls.Add(export_btn)

        import_btn = Button()
        import_btn.Text = "Import Type Profile"
        import_btn.Location = Point(360, 415)
        import_btn.Size = Size(145, 32)
        import_btn.Click += self.ImportFamilyTypeProfile
        self.tab_family_types.Controls.Add(import_btn)

        check_all = Button()
        check_all.Text = "Check Visible"
        check_all.Location = Point(520, 415)
        check_all.Size = Size(110, 32)
        check_all.Click += lambda s, e: self.SelectAllItems(self.family_type_list)
        self.tab_family_types.Controls.Add(check_all)

        clear = Button()
        clear.Text = "Clear Checks"
        clear.Location = Point(640, 415)
        clear.Size = Size(110, 32)
        clear.Click += lambda s, e: self.SelectNoneItems(self.family_type_list)
        self.tab_family_types.Controls.Add(clear)

    def InitializeActionButtons(self):
        # Action group
        action_group = GroupBox()
        action_group.Text = "Workset Actions"
        action_group.Location = Point(20, 600)
        action_group.Size = Size(1185, 190)
        action_group.Anchor = AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Bottom
        self.Controls.Add(action_group)

        # Row 1 - Basic Actions
        self.create_btn = Button()
        self.create_btn.Text = "Create Workset"
        self.create_btn.Location = Point(20, 28)
        self.create_btn.Size = Size(135, 34)
        self.create_btn.Click += self.CreateWorkset
        action_group.Controls.Add(self.create_btn)

        self.delete_btn = Button()
        self.delete_btn.Text = "Delete Workset"
        self.delete_btn.Location = Point(165, 28)
        self.delete_btn.Size = Size(135, 34)
        self.delete_btn.Click += self.DeleteWorksets
        action_group.Controls.Add(self.delete_btn)

        self.rename_btn = Button()
        self.rename_btn.Text = "Rename Workset"
        self.rename_btn.Location = Point(310, 28)
        self.rename_btn.Size = Size(135, 34)
        self.rename_btn.Click += self.RenameWorkset
        action_group.Controls.Add(self.rename_btn)

        # Row 2 - Element Actions
        self.select_elements_btn = Button()
        self.select_elements_btn.Text = "Select Elements in Workset"
        self.select_elements_btn.Location = Point(20, 70)
        self.select_elements_btn.Size = Size(190, 34)
        self.select_elements_btn.BackColor = Color.LightBlue
        self.select_elements_btn.Click += self.SelectElementsInWorkset
        action_group.Controls.Add(self.select_elements_btn)

        self.move_selected_btn = Button()
        self.move_selected_btn.Text = "Move Selected Elements"
        self.move_selected_btn.Location = Point(220, 70)
        self.move_selected_btn.Size = Size(190, 34)
        self.move_selected_btn.BackColor = Color.LightGreen
        self.move_selected_btn.Click += self.MoveSelectedElementsToWorkset
        action_group.Controls.Add(self.move_selected_btn)

        # Row 3 - Settings
        self.set_default_btn = Button()
        self.set_default_btn.Text = "Set Active Workset"
        self.set_default_btn.Location = Point(455, 28)
        self.set_default_btn.Size = Size(155, 34)
        self.set_default_btn.Click += self.SetDefaultWorkset
        action_group.Controls.Add(self.set_default_btn)

        self.cleanup_btn = Button()
        self.cleanup_btn.Text = "Clean Worksets"
        self.cleanup_btn.Location = Point(620, 28)
        self.cleanup_btn.Size = Size(145, 34)
        self.cleanup_btn.BackColor = Color.LightYellow
        self.cleanup_btn.Click += self.CleanupUnusedWorksets
        action_group.Controls.Add(self.cleanup_btn)

        # Row 4 - Move Elements
        self.move_btn = Button()
        self.move_btn.Text = "Move Between Worksets"
        self.move_btn.Location = Point(420, 70)
        self.move_btn.Size = Size(190, 34)
        self.move_btn.BackColor = Color.LightGreen
        self.move_btn.Click += self.MoveElementsBetweenWorksets
        action_group.Controls.Add(self.move_btn)

        # Status label
        self.status_label = Label()
        self.status_label.Location = Point(20, 116)
        self.status_label.Size = Size(1145, 25)
        self.status_label.BorderStyle = BorderStyle.FixedSingle
        self.status_label.Text = "Ready"
        self.status_label.TextAlign = ContentAlignment.MiddleLeft
        action_group.Controls.Add(self.status_label)

        # Progress bar for move operation
        self.progress_bar = ProgressBar()
        self.progress_bar.Location = Point(20, 148)
        self.progress_bar.Size = Size(1145, 14)
        self.progress_bar.Visible = False
        action_group.Controls.Add(self.progress_bar)

        # Progress label
        self.progress_label = Label()
        self.progress_label.Location = Point(20, 164)
        self.progress_label.Size = Size(1145, 18)
        self.progress_label.Text = ""
        self.progress_label.TextAlign = ContentAlignment.MiddleLeft
        action_group.Controls.Add(self.progress_label)

    def LoadProjectFamilies(self, sender=None, args=None):
        try:
            self.Cursor = Cursors.WaitCursor
            self.status_label.Text = "Loading project families..."
            self.status_label.Refresh()
            self.project_families = WorksetManager.get_project_families()
            self.UpdateFamilyList()
            if self.family_list.Items.Count:
                self.family_list.Items[0].Selected = True
                self.family_list.Items[0].Focused = True
            self.status_label.Text = "Loaded {} project families.".format(
                len(self.project_families))
        except Exception as ex:
            logger.error("Unable to load project families: {}".format(ex))
            forms.alert("Unable to load project families:\n{}".format(ex),
                        title="Family Load Failed")
        finally:
            self.Cursor = Cursors.Default

    def OnFamilySearchChanged(self, sender, args):
        self.UpdateFamilyList()

    def UpdateFamilyList(self):
        if not hasattr(self, "family_list"):
            return
        search = (self.family_search.Text or "").strip().lower()
        self.family_list.BeginUpdate()
        try:
            self.family_list.Items.Clear()
            for family in self.project_families:
                category = "Uncategorized"
                try:
                    if family.FamilyCategory:
                        category = family.FamilyCategory.Name
                except Exception:
                    pass
                searchable = "{} {}".format(family.Name, category).lower()
                if search and search not in searchable:
                    continue
                row = self.family_list.Items.Add(family.Name)
                row.SubItems.Add(category)
                row.Tag = family
        finally:
            self.family_list.EndUpdate()

    def OnFamilySelectionChanged(self, sender, args):
        if self.family_list.SelectedItems.Count != 1:
            return
        try:
            family = self.family_list.SelectedItems[0].Tag
            self.current_family_type_items = WorksetManager.get_family_type_items(family)
            for item in self.current_family_type_items:
                self.family_type_items[self._descriptor_key(item[1])] = item
            self.UpdateFamilyTypeList()
            self.status_label.Text = "Loaded {} types from '{}'.".format(
                len(self.current_family_type_items), family.Name)
        except Exception as ex:
            logger.error("Unable to load family types: {}".format(ex))
            forms.alert("Unable to load family types:\n{}".format(ex),
                        title="Type Load Failed")

    def OnFamilyTypeSearchChanged(self, sender, args):
        self.UpdateFamilyTypeList()

    def OnFamilyTypeItemCheck(self, sender, args):
        if self.updating_family_types:
            return
        try:
            tagged = self.family_type_list.Items[args.Index].Tag
            key = self._descriptor_key(tagged[1])
            if int(args.NewValue) == 1:
                self.family_type_checked_keys.add(key)
            else:
                self.family_type_checked_keys.discard(key)
        except Exception as ex:
            logger.warning("Unable to update Family Type selection: {}".format(ex))

    def UpdateFamilyTypeList(self):
        self.updating_family_types = True
        self.family_type_list.BeginUpdate()
        try:
            self.family_type_list.Items.Clear()
            search = (self.family_type_search.Text or "").strip().lower()
            for symbol, descriptor in self.current_family_type_items:
                key = self._descriptor_key(descriptor)
                searchable = " ".join([
                    descriptor.get("category", ""), descriptor.get("family", ""),
                    descriptor.get("name", "")]).lower()
                if search and search not in searchable:
                    continue
                row = self.family_type_list.Items.Add("")
                row.SubItems.Add(descriptor.get("category", ""))
                row.SubItems.Add(descriptor.get("family", ""))
                row.SubItems.Add(descriptor.get("name", ""))
                row.SubItems.Add(self.family_type_status_cache.get(
                    key, "Not checked (borrow to verify)"))
                row.Tag = (symbol, descriptor)
                row.Checked = key in self.family_type_checked_keys
        finally:
            self.family_type_list.EndUpdate()
            self.updating_family_types = False

    def CheckoutFamilyTypes(self, sender, args):
        selected = [self.family_type_items[key]
                    for key in self.family_type_checked_keys
                    if key in self.family_type_items]
        if not selected:
            forms.alert("Check at least one Family Type to borrow.",
                        title="No Types Selected")
            return
        owned, failed = WorksetManager.checkout_items(selected)
        for symbol, descriptor in selected:
            result_key = ("element", get_id_value(symbol.Id))
            self.family_type_status_cache[self._descriptor_key(descriptor)] = (
                "Owned by me" if result_key in owned else "Unavailable")
        self.UpdateFamilyTypeList()
        message = "Owned by current user: {}\nUnavailable or failed: {}".format(
            len(owned), len(failed))
        self.status_label.Text = message.replace("\n", " | ")
        forms.alert(message, title="Family Type Ownership Result")

    def ExportFamilyTypeProfile(self, sender, args):
        selected = [self.family_type_items[key][1]
                    for key in self.family_type_checked_keys
                    if key in self.family_type_items]
        if not selected:
            forms.alert("Check at least one Family Type to export.",
                        title="No Types Selected")
            return
        dialog = SaveFileDialog()
        dialog.Title = "Export Family Type Ownership Profile"
        dialog.Filter = "Workset Manager Profile (*.json)|*.json"
        dialog.DefaultExt = "json"
        dialog.AddExtension = True
        initial = self._read_settings().get("profile_folder", "")
        if initial and os.path.isdir(initial):
            dialog.InitialDirectory = initial
        safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in doc.Title)
        dialog.FileName = "{}_family_types.json".format(safe_title)
        if dialog.ShowDialog() != DialogResult.OK:
            return
        payload = {
            "schema": "P13.WorksetManager.OwnershipProfile",
            "version": 2,
            "profile_type": "Family Types",
            "source_project": doc.Title,
            "exported_at": datetime.now().isoformat(),
            "items": selected
        }
        with open(dialog.FileName, "w") as profile_file:
            json.dump(payload, profile_file, indent=2)
        self._remember_profile_folder(os.path.dirname(dialog.FileName))
        self.status_label.Text = "Exported {} Family Type rules.".format(len(selected))

    def ImportFamilyTypeProfile(self, sender, args):
        dialog = OpenFileDialog()
        dialog.Title = "Import Family Type Ownership Profile"
        dialog.Filter = "Workset Manager Profile (*.json)|*.json"
        initial = self._read_settings().get("profile_folder", "")
        if initial and os.path.isdir(initial):
            dialog.InitialDirectory = initial
        if dialog.ShowDialog() != DialogResult.OK:
            return
        try:
            with open(dialog.FileName, "r") as profile_file:
                payload = json.load(profile_file)
            rules = [rule for rule in payload.get("items", [])
                     if self._descriptor_group(rule) == "Family Types"]
            if not self.project_families:
                self.LoadProjectFamilies()
            families_by_name = dict((family.Name, family)
                                    for family in self.project_families)
            matched = 0
            first_family_name = None
            for family_name in sorted(set(rule.get("family", "") for rule in rules)):
                family = families_by_name.get(family_name)
                if not family:
                    continue
                if first_family_name is None:
                    first_family_name = family_name
                for item in WorksetManager.get_family_type_items(family):
                    key = self._descriptor_key(item[1])
                    self.family_type_items[key] = item
            for rule in rules:
                key = self._descriptor_key(rule)
                if key in self.family_type_items:
                    self.family_type_checked_keys.add(key)
                    matched += 1
            if first_family_name:
                self.family_search.Text = ""
                self.UpdateFamilyList()
                for row in self.family_list.Items:
                    if row.Text == first_family_name:
                        row.Selected = True
                        row.Focused = True
                        row.EnsureVisible()
                        break
            self.UpdateFamilyTypeList()
            self._remember_profile_folder(os.path.dirname(dialog.FileName))
            forms.alert("Matched: {}\nNot found: {}".format(
                matched, len(rules) - matched), title="Family Type Profile Imported")
        except Exception as ex:
            logger.error("Family Type profile import failed: {}".format(ex))
            forms.alert("Unable to import Family Type profile:\n{}".format(ex),
                        title="Import Failed")

    def _read_settings(self):
        try:
            if os.path.isfile(self.settings_path):
                with open(self.settings_path, "r") as settings_file:
                    return json.load(settings_file)
        except Exception as ex:
            logger.warning("Unable to read Workset Manager settings: {}".format(ex))
        return {}

    def _remember_profile_folder(self, folder):
        try:
            parent = os.path.dirname(self.settings_path)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            settings = self._read_settings()
            settings["profile_folder"] = folder
            with open(self.settings_path, "w") as settings_file:
                json.dump(settings, settings_file, indent=2)
        except Exception as ex:
            logger.warning("Unable to save Workset Manager settings: {}".format(ex))

    def OnMainTabChanged(self, sender, args):
        """Do not query the Revit database from the WinForms tab event."""
        if self.tab_control.SelectedTab == self.tab_ownership and not self.ownership_loaded:
            self.status_label.Text = (
                "Select ownership groups, then click Load / Refresh Items.")
        elif (self.tab_control.SelectedTab == self.tab_family_types and
              not self.project_families):
            self.status_label.Text = (
                "Click Load Families, select a Family, then check the Types to borrow.")

    def RefreshOwnershipItems(self, sender=None, args=None):
        enabled_groups = set(
            name for name, checkbox in self.ownership_group_checks.items()
            if checkbox.Checked)
        if not enabled_groups:
            forms.alert("Select at least one Show group.", title="No Groups Selected")
            return
        try:
            self.status_label.Text = "Loading selected ownership groups..."
            self.Cursor = Cursors.WaitCursor
            self.status_label.Refresh()
            self.Refresh()
            self.editable_items = WorksetManager.get_editable_items(enabled_groups)
            self.ownership_loaded = True
            self.status_label.Text = "Displaying {} ownership items...".format(
                len(self.editable_items))
            self.status_label.Refresh()
            self.UpdateOwnershipList()
            group_counts = defaultdict(int)
            for item, descriptor in self.editable_items:
                group_counts[descriptor.get("group", "Unknown")] += 1
            summary = ", ".join(
                "{}: {}".format(group_name, group_counts.get(group_name, 0))
                for group_name in sorted(enabled_groups))
            self.status_label.Text = "Loaded {} items ({})".format(
                len(self.editable_items), summary)
            if not self.editable_items:
                forms.alert(
                    "No ownership items matched the selected Show groups.",
                    title="No Ownership Items")
        except Exception as ex:
            logger.error("Unable to load ownership items: {}".format(ex))
            self.status_label.Text = "Ownership items could not be loaded."
            forms.alert("Unable to load ownership items:\n{}".format(ex),
                        title="Ownership Load Failed")
        finally:
            self.Cursor = Cursors.Default

    def OnOwnershipSearchChanged(self, sender, args):
        self.UpdateOwnershipList()

    def OnOwnershipGroupChanged(self, sender, args):
        self.UpdateOwnershipList()
        if self.ownership_loaded:
            self.status_label.Text = (
                "Show groups changed. Click Load / Refresh Items to load newly enabled groups.")

    def OnOwnershipItemCheck(self, sender, args):
        if self.updating_ownership_list:
            return
        try:
            tagged = self.ownership_list.Items[args.Index].Tag
            if not tagged:
                return
            key = self._descriptor_key(tagged[1])
            if int(args.NewValue) == 1:
                self.ownership_checked_keys.add(key)
            else:
                self.ownership_checked_keys.discard(key)
        except Exception as ex:
            logger.warning("Unable to update ownership selection: {}".format(ex))

    def UpdateOwnershipList(self):
        self.updating_ownership_list = True
        self.ownership_list.BeginUpdate()
        try:
            self.ownership_list.Items.Clear()
            search = (self.ownership_search.Text or "").strip().lower()
            visible_groups = set(
                name for name, checkbox in self.ownership_group_checks.items()
                if checkbox.Checked)
            for element, descriptor in self.editable_items:
                if descriptor.get("group", "Project Standards") not in visible_groups:
                    continue
                key = self._descriptor_key(descriptor)
                searchable = " ".join([
                    descriptor.get("group", ""),
                    descriptor.get("category", ""), descriptor.get("family", ""),
                    descriptor.get("name", ""), descriptor.get("class", "")]).lower()
                if search and search not in searchable:
                    continue
                row = self.ownership_list.Items.Add("")
                row.SubItems.Add(descriptor.get("group", "Project Standards"))
                row.SubItems.Add(descriptor.get("category", ""))
                row.SubItems.Add(descriptor.get("family", ""))
                row.SubItems.Add(descriptor.get("name", ""))
                row.SubItems.Add(descriptor.get("class", ""))
                if descriptor.get("class", "").endswith("Workset"):
                    status_text = WorksetManager.get_item_checkout_status(
                        element, descriptor)
                else:
                    status_text = self.ownership_status_cache.get(
                        key, "Not checked (borrow to verify)")
                row.SubItems.Add(status_text)
                row.Tag = (element, descriptor)
                row.Checked = key in self.ownership_checked_keys
        finally:
            self.ownership_list.EndUpdate()
            self.updating_ownership_list = False

    def _descriptor_key(self, descriptor):
        return "|".join([
            self._descriptor_group(descriptor), descriptor.get("class", ""),
            descriptor.get("category", ""),
            descriptor.get("family", ""), descriptor.get("name", "")])

    def _descriptor_group(self, descriptor):
        group = descriptor.get("group", "")
        if group:
            return group
        class_name = descriptor.get("class", "")
        if class_name == "UserWorkset":
            return "User-Created"
        if class_name in ("Family", "FamilySymbol"):
            return "Families"
        if class_name.endswith("View") or class_name in ("View", "ViewSheet"):
            return "Views"
        return "Project Standards"

    def _checked_ownership_items(self):
        return [item for item in self.editable_items
                if self._descriptor_key(item[1]) in self.ownership_checked_keys]

    def CheckoutOwnershipItems(self, sender, args):
        selected = self._checked_ownership_items()
        if not selected:
            forms.alert("Check at least one item to borrow.", title="No Items Selected")
            return
        owned, failed = WorksetManager.checkout_items(selected)
        for item, descriptor in selected:
            item_kind = ("workset" if descriptor.get("class", "").endswith("Workset")
                         else "element")
            item_key = (item_kind, get_id_value(item.Id))
            self.ownership_status_cache[self._descriptor_key(descriptor)] = (
                "Owned by me" if item_key in owned else "Unavailable")
        self.UpdateOwnershipList()
        message = "Owned by current user: {}\nUnavailable or failed: {}".format(
            len(owned), len(failed))
        self.status_label.Text = message.replace("\n", " | ")
        forms.alert(message, title="Item Ownership Result")

    def ExportOwnershipProfile(self, sender, args):
        selected = self._checked_ownership_items()
        if not selected:
            forms.alert("Check at least one item to export.", title="No Items Selected")
            return
        settings = self._read_settings()
        dialog = SaveFileDialog()
        dialog.Title = "Export Item Ownership Profile"
        dialog.Filter = "Workset Manager Profile (*.json)|*.json"
        dialog.DefaultExt = "json"
        dialog.AddExtension = True
        initial = settings.get("profile_folder", "")
        if initial and os.path.isdir(initial):
            dialog.InitialDirectory = initial
        safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in doc.Title)
        dialog.FileName = "{}_ownership.json".format(safe_title)
        if dialog.ShowDialog() != DialogResult.OK:
            return
        payload = {
            "schema": "P13.WorksetManager.OwnershipProfile",
            "version": 1,
            "source_project": doc.Title,
            "exported_at": datetime.now().isoformat(),
            "items": [item[1] for item in selected]
        }
        with open(dialog.FileName, "w") as profile_file:
            json.dump(payload, profile_file, indent=2)
        self._remember_profile_folder(os.path.dirname(dialog.FileName))
        self.status_label.Text = "Exported {} ownership rules.".format(len(selected))

    def ImportOwnershipProfile(self, sender, args):
        settings = self._read_settings()
        dialog = OpenFileDialog()
        dialog.Title = "Import Item Ownership Profile"
        dialog.Filter = "Workset Manager Profile (*.json)|*.json"
        initial = settings.get("profile_folder", "")
        if initial and os.path.isdir(initial):
            dialog.InitialDirectory = initial
        if dialog.ShowDialog() != DialogResult.OK:
            return
        try:
            with open(dialog.FileName, "r") as profile_file:
                payload = json.load(profile_file)
            if payload.get("schema") != "P13.WorksetManager.OwnershipProfile":
                raise ValueError("The selected file is not a Workset Manager ownership profile.")
            self.profile_rules = payload.get("items", [])
            profile_groups = set(self._descriptor_group(rule)
                                 for rule in self.profile_rules)
            for group_name, checkbox in self.ownership_group_checks.items():
                checkbox.Checked = group_name in profile_groups
            self.editable_items = WorksetManager.get_editable_items(profile_groups)
            self.ownership_loaded = True
            available = set(self._descriptor_key(x[1]) for x in self.editable_items)
            self.ownership_checked_keys = set(
                self._descriptor_key(rule) for rule in self.profile_rules)
            matched = len([r for r in self.profile_rules if self._descriptor_key(r) in available])
            self.UpdateOwnershipList()
            self._remember_profile_folder(os.path.dirname(dialog.FileName))
            self.status_label.Text = "Imported profile: {} of {} rules matched.".format(
                matched, len(self.profile_rules))
            forms.alert(
                "Matched: {}\nNot found in this project: {}\n\nReview the checked items, then click Borrow Checked Items.".format(
                    matched, len(self.profile_rules) - matched),
                title="Ownership Profile Imported")
        except Exception as ex:
            logger.error("Ownership profile import failed: {}".format(ex))
            forms.alert("Unable to import profile:\n{}".format(ex), title="Import Failed")

    def LoadWorksets(self):
        """Load all worksets and their element counts"""
        try:
            self.status_label.Text = "Loading Worksets..."

            # Get all worksets
            self.all_worksets = WorksetManager.get_all_worksets()

            # Get element counts
            self.element_counts = WorksetManager.get_element_count_by_workset()

            # Categorize worksets
            self.worksets_with_elements = []
            self.empty_worksets = []

            for workset in self.all_worksets:
                element_count = self.element_counts.get(get_id_value(workset.Id), 0)
                if element_count > 0:
                    self.worksets_with_elements.append(workset)
                else:
                    self.empty_worksets.append(workset)

            # Update UI
            self.UpdateAllLists()

            # Update default workset info
            self.UpdateDefaultWorksetInfo()

            self.status_label.Text = "Loaded {} Worksets.".format(len(self.all_worksets))

        except Exception as e:
            logger.error("Error loading worksets: {}".format(e))
            self.status_label.Text = "Unable to load Worksets."

    def UpdateDefaultWorksetInfo(self):
        """Update default workset information"""
        try:
            default_workset = WorksetManager.get_default_workset()
            if default_workset:
                self.default_workset_label.Text = "Active Workset: {}".format(default_workset.Name)
                self.default_workset_label.ForeColor = Color.DarkGreen
            else:
                self.default_workset_label.Text = "No active Workset found"
                self.default_workset_label.ForeColor = Color.DarkRed
        except Exception as e:
            logger.error("Error updating default workset info: {}".format(e))
            self.default_workset_label.Text = "Unable to load active Workset"

    def UpdateAllLists(self):
        """Update all list views"""
        self.UpdateAllWorksetsList()
        self.UpdateWithElementsList()
        self.UpdateEmptyWorksetsList()

    def _match_search(self, workset, search_text):
        """Return True if workset matches search_text (by name, owner, or ID)"""
        if not search_text:
            return True
        search_text = search_text.lower()
        owner = workset.Owner if workset.Owner else ""
        ws_id = str(get_id_value(workset.Id))
        combined = u"{} {} {}".format(workset.Name, owner, ws_id).lower()
        return search_text in combined

    def UpdateAllWorksetsList(self):
        """Update the all worksets list view"""
        self.all_worksets_list.Items.Clear()

        default_workset = WorksetManager.get_default_workset()
        search_text = ""
        if self.search_box_all and self.search_box_all.Text:
            search_text = self.search_box_all.Text.strip()

        for workset in self.all_worksets:
            if not self._match_search(workset, search_text):
                continue

            element_count = self.element_counts.get(get_id_value(workset.Id), 0)
            status = "Editable" if workset.IsEditable else "Not Editable"
            is_default = default_workset and get_id_value(workset.Id) == get_id_value(default_workset.Id)

            item = self.all_worksets_list.Items.Add("")
            item.SubItems.Add(workset.Name)
            item.SubItems.Add(str(element_count))

            if is_default:
                item.SubItems.Add("Active")
                item.BackColor = Color.LightGreen
            else:
                item.SubItems.Add(status)

            item.SubItems.Add(workset.Owner if workset.Owner else "N/A")
            item.SubItems.Add(str(get_id_value(workset.Id)))
            item.Tag = workset

    def UpdateWithElementsList(self):
        """Update the worksets with elements list view"""
        self.with_elements_list.Items.Clear()

        search_text = ""
        if self.search_box_with and self.search_box_with.Text:
            search_text = self.search_box_with.Text.strip()

        for workset in self.worksets_with_elements:
            if not self._match_search(workset, search_text):
                continue

            element_count = self.element_counts.get(get_id_value(workset.Id), 0)
            status = "Editable" if workset.IsEditable else "Not Editable"

            item = self.with_elements_list.Items.Add("")
            item.SubItems.Add(workset.Name)
            item.SubItems.Add(str(element_count))
            item.SubItems.Add(status)
            item.SubItems.Add(workset.Owner if workset.Owner else "N/A")
            item.SubItems.Add(str(get_id_value(workset.Id)))
            item.Tag = workset

    def UpdateEmptyWorksetsList(self):
        """Update the empty worksets list view"""
        self.empty_worksets_list.Items.Clear()

        search_text = ""
        if self.search_box_empty and self.search_box_empty.Text:
            search_text = self.search_box_empty.Text.strip()

        for workset in self.empty_worksets:
            if not self._match_search(workset, search_text):
                continue

            status = "Editable" if workset.IsEditable else "Not Editable"

            item = self.empty_worksets_list.Items.Add("")
            item.SubItems.Add(workset.Name)
            item.SubItems.Add(status)
            item.SubItems.Add(workset.Owner if workset.Owner else "N/A")
            item.SubItems.Add(str(get_id_value(workset.Id)))
            item.Tag = workset

    def GetSelectedWorksets(self, list_view):
        """Get selected worksets from a list view"""
        selected = []
        for item in list_view.CheckedItems:
            if item.Tag:
                selected.append(item.Tag)
        return selected

    def GetCurrentListView(self):
        """Get the currently active list view based on selected tab"""
        current_tab = self.tab_control.SelectedTab
        if current_tab == self.tab_all:
            return self.all_worksets_list
        elif current_tab == self.tab_with_elements:
            return self.with_elements_list
        elif current_tab == self.tab_empty:
            return self.empty_worksets_list
        return None

    def SelectAllItems(self, list_view):
        """Select all items in a list view"""
        for item in list_view.Items:
            item.Checked = True

    def SelectNoneItems(self, list_view):
        """Deselect all items in a list view"""
        for item in list_view.Items:
            item.Checked = False

    # Event handlers
    def OnSearchTextChanged(self, sender, args):
        """Handle search text changes - shared for all tabs"""
        tag = getattr(sender, "Tag", None)
        if tag == "all":
            self.UpdateAllWorksetsList()
        elif tag == "with":
            self.UpdateWithElementsList()
        elif tag == "empty":
            self.UpdateEmptyWorksetsList()
        else:
            self.UpdateAllLists()

    def OnClearSearchClicked(self, sender, args):
        """Clear search text for the corresponding tab"""
        tag = getattr(sender, "Tag", None)
        if tag == "all" and self.search_box_all:
            self.search_box_all.Text = ""
        elif tag == "with" and self.search_box_with:
            self.search_box_with.Text = ""
        elif tag == "empty" and self.search_box_empty:
            self.search_box_empty.Text = ""

    def RefreshWorksets(self, sender, args):
        """Refresh worksets data"""
        self.LoadWorksets()

    def CreateWorkset(self, sender, args):
        """Create a new workset"""
        try:
            workset_name = forms.ask_for_string(
                prompt="Enter a new Workset name:",
                title="Create Workset"
            )

            if workset_name:
                if WorksetManager.create_workset(workset_name):
                    self.status_label.Text = "Created Workset '{}'.".format(workset_name)
                    self.LoadWorksets()
                else:
                    self.status_label.Text = "Unable to create Workset '{}'.".format(workset_name)
        except Exception as e:
            logger.error("Error in CreateWorkset: {}".format(e))
            forms.alert("Unable to create the Workset.", title="Error")

    def DeleteWorksets(self, sender, args):
        """Delete selected worksets - CORRECTED VERSION"""
        list_view = self.GetCurrentListView()
        if not list_view:
            return

        selected_worksets = self.GetSelectedWorksets(list_view)
        if not selected_worksets:
            forms.alert("Select at least one Workset to delete.", title="No Selection")
            return

        # Filter out worksets that have elements or are default
        deletable_worksets = []
        non_deletable_worksets = []

        default_workset = WorksetManager.get_default_workset()

        for workset in selected_worksets:
            element_count = self.element_counts.get(get_id_value(workset.Id), 0)
            is_default = default_workset and get_id_value(workset.Id) == get_id_value(default_workset.Id)

            if element_count == 0 and not is_default:
                deletable_worksets.append(workset)
            else:
                if element_count > 0:
                    non_deletable_worksets.append("{} (contains {} elements)".format(workset.Name, element_count))
                elif is_default:
                    non_deletable_worksets.append("{} (active Workset)".format(workset.Name))

        if non_deletable_worksets:
            forms.alert("These Worksets cannot be deleted:\n{}".format(
                "\n".join(non_deletable_worksets)), title="Error")

        if not deletable_worksets:
            return

        # ใช้ options แทน yes/no
        result = forms.alert(
            "Delete {} Worksets?".format(len(deletable_worksets)),
            options=["Yes", "No"],
            title="Confirm Delete"
        )

        if result == "Yes":
            success_count = 0
            failed_worksets = []

            for workset in deletable_worksets:
                try:
                    # ตรวจสอบว่าสามารถลบได้ก่อน
                    can_delete, reason = WorksetManager.can_delete_workset(workset)
                    if can_delete:
                        if WorksetManager.delete_workset(workset):
                            success_count += 1
                        else:
                            failed_worksets.append("{} (delete failed)".format(workset.Name))
                    else:
                        failed_worksets.append("{} ({})".format(workset.Name, reason))
                except Exception as e:
                    logger.error("Error deleting workset {}: {}".format(workset.Name, e))
                    failed_worksets.append("{} (error: {})".format(workset.Name, str(e)))

            if failed_worksets:
                forms.alert("Deleted: {}\nFailed: {}\n{}".format(
                    success_count, len(failed_worksets), "\n".join(failed_worksets)), title="Delete Result")
            else:
                forms.alert("Deleted {} Worksets.".format(success_count), title="Success")
                self.status_label.Text = "Deleted {} Worksets.".format(success_count)

            self.LoadWorksets()

    def RenameWorkset(self, sender, args):
        """Rename selected workset"""
        list_view = self.GetCurrentListView()
        if not list_view:
            return

        selected_worksets = self.GetSelectedWorksets(list_view)
        if not selected_worksets:
            forms.alert("กรุณาเลือก Workset ที่ต้องการเปลี่ยนชื่อ", title="ไม่มีการเลือก")
            return

        if len(selected_worksets) > 1:
            forms.alert("กรุณาเลือกเพียงหนึ่ง Workset เท่านั้น", title="ข้อผิดพลาด")
            return

        workset = selected_worksets[0]

        # แก้ไขการเรียกใช้ ask_for_string
        try:
            # ใช้ prompt อย่างเดียว
            new_name = forms.ask_for_string(
                prompt="ระบุชื่อใหม่:\n(ชื่อเดิม: {})".format(workset.Name),
                title="เปลี่ยนชื่อ Workset"
            )

            if not new_name:
                return

        except Exception as e:
            logger.error("Error getting new name: {}".format(e))
            forms.alert("เกิดข้อผิดพลาดในการรับชื่อใหม่", title="ข้อผิดพลาด")
            return

        if new_name and new_name != workset.Name:
            if WorksetManager.rename_workset(workset, new_name):
                self.status_label.Text = "เปลี่ยนชื่อ Workset เป็น '{}' สำเร็จ".format(new_name)
                self.LoadWorksets()
            else:
                self.status_label.Text = "ไม่สามารถเปลี่ยนชื่อ Workset ได้"

    def SelectElementsInWorkset(self, sender, args):
        """Select all elements in selected workset"""
        list_view = self.GetCurrentListView()
        if not list_view:
            return

        selected_worksets = self.GetSelectedWorksets(list_view)
        if not selected_worksets:
            forms.alert("กรุณาเลือก Workset ที่ต้องการเลือกองค์ประกอบ", title="ไม่มีการเลือก")
            return

        if len(selected_worksets) > 1:
            forms.alert("กรุณาเลือกเพียงหนึ่ง Workset เท่านั้น", title="ข้อผิดพลาด")
            return

        workset = selected_worksets[0]
        element_count = WorksetManager.select_elements_in_workset(workset)

        if element_count > 0:
            self.status_label.Text = "เลือกองค์ประกอบใน Workset '{}' สำเร็จ: {} องค์ประกอบ".format(
                workset.Name, element_count)
            forms.alert("เลือกองค์ประกอบ {} รายการใน Workset '{}'".format(
                element_count, workset.Name), title="สำเร็จ")
        else:
            self.status_label.Text = "ไม่พบองค์ประกอบใน Workset '{}'".format(workset.Name)
            forms.alert("ไม่พบองค์ประกอบใน Workset '{}'".format(workset.Name), title="ไม่พบข้อมูล")

    def MoveSelectedElementsToWorkset(self, sender, args):
        """Move currently selected elements to selected workset"""
        list_view = self.GetCurrentListView()
        if not list_view:
            return

        selected_worksets = self.GetSelectedWorksets(list_view)
        if not selected_worksets:
            forms.alert("กรุณาเลือก Workset ปลายทาง", title="ไม่มีการเลือก")
            return

        if len(selected_worksets) > 1:
            forms.alert("กรุณาเลือกเพียงหนึ่ง Workset เท่านั้น", title="ข้อผิดพลาด")
            return

        target_workset = selected_worksets[0]

        # Get selected elements count
        selected_element_ids = uidoc.Selection.GetElementIds()
        if not selected_element_ids or selected_element_ids.Count == 0:
            forms.alert("กรุณาเลือกองค์ประกอบใน Revit ก่อน", title="ไม่มีการเลือก")
            return

        # ใช้ options แทน yes/no  
        result = forms.alert(
            "ย้ายองค์ประกอบที่เลือก {} รายการไปยัง Workset '{}'?".format(
                selected_element_ids.Count, target_workset.Name), 
            options=["ใช่", "ไม่"]
        )

        if result == "ใช่":
            success_count, failed_count, failed_elements = WorksetManager.move_selected_elements_to_workset(target_workset)

            result_msg = "ย้ายองค์ประกอบสำเร็จ: {} รายการ\nย้ายไม่สำเร็จ: {} รายการ".format(
                success_count, failed_count)

            if failed_count > 0:
                result_msg += "\n\nองค์ประกอบที่ย้ายไม่สำเร็จอาจเป็นประเภทที่ไม่สามารถเปลี่ยน Workset ได้"

            forms.alert(result_msg, title="ผลการย้ายองค์ประกอบ")
            self.status_label.Text = "ย้ายองค์ประกอบ {} รายการไปยัง Workset '{}'".format(
                success_count, target_workset.Name)

            self.LoadWorksets()

    def SetDefaultWorkset(self, sender, args):
        """Set selected workset as default"""
        list_view = self.GetCurrentListView()
        if not list_view:
            return

        selected_worksets = self.GetSelectedWorksets(list_view)
        if not selected_worksets:
            forms.alert("กรุณาเลือก Workset ที่ต้องการกำหนดเป็นค่าเริ่มต้น", title="ไม่มีการเลือก")
            return

        if len(selected_worksets) > 1:
            forms.alert("กรุณาเลือกเพียงหนึ่ง Workset เท่านั้น", title="ข้อผิดพลาด")
            return

        workset = selected_worksets[0]

        if WorksetManager.set_default_workset(workset):
            self.status_label.Text = "กำหนด Workset '{}' เป็นค่าเริ่มต้นสำเร็จ".format(workset.Name)
            self.UpdateDefaultWorksetInfo()
            forms.alert("กำหนด Workset '{}' เป็นค่าเริ่มต้นสำหรับองค์ประกอบใหม่สำเร็จ".format(
                workset.Name), title="สำเร็จ")
        else:
            self.status_label.Text = "ไม่สามารถกำหนด Workset เป็นค่าเริ่มต้นได้"

    def CleanupUnusedWorksets(self, sender, args):
        """Clean up unused worksets"""
        unused_worksets = WorksetManager.get_unused_worksets()

        if not unused_worksets:
            forms.alert("ไม่พบ Workset ที่ไม่ได้ใช้งาน", title="ผลการตรวจสอบ")
            return

        # Show unused worksets
        output.print_md("# **Workset ที่ไม่ได้ใช้งาน**")
        output.print_md("**พบ {} Workset ที่ไม่ได้ใช้งาน**".format(len(unused_worksets)))

        for i, workset in enumerate(unused_worksets, 1):
            output.print_md("{}. **{}** (ID: {})".format(i, workset.Name, get_id_value(workset.Id)))

        # ใช้ options แทน yes/no
        result = forms.alert(
            "ต้องการลบ Workset ที่ไม่ได้ใช้งาน {} รายการหรือไม่?".format(len(unused_worksets)), 
            options=["ใช่", "ไม่"], 
            title="ยืนยันการทำความสะอาด"
        )

        if result == "ใช่":
            success_count = 0
            failed_worksets = []

            for workset in unused_worksets:
                try:
                    # ตรวจสอบว่าสามารถลบได้ก่อน
                    can_delete, reason = WorksetManager.can_delete_workset(workset)
                    if can_delete:
                        if WorksetManager.delete_workset(workset):
                            success_count += 1
                        else:
                            failed_worksets.append("{} (ลบไม่สำเร็จ)".format(workset.Name))
                    else:
                        failed_worksets.append("{} ({})".format(workset.Name, reason))
                except Exception as e:
                    logger.error("Error deleting unused workset {}: {}".format(workset.Name, e))
                    failed_worksets.append("{} (ข้อผิดพลาด: {})".format(workset.Name, str(e)))

            if failed_worksets:
                forms.alert("ลบ Workset ที่ไม่ได้ใช้งานสำเร็จ {} รายการ\nลบไม่สำเร็จ {} รายการ:\n{}".format(
                    success_count, len(failed_worksets), "\n".join(failed_worksets)), title="ผลการทำความสะอาด")
            else:
                forms.alert("ลบ Workset ที่ไม่ได้ใช้งานสำเร็จ {} รายการ".format(success_count), title="สำเร็จ")

            self.status_label.Text = "ทำความสะอาด Workset ที่ไม่ได้ใช้งานสำเร็จ {} รายการ".format(success_count)
            self.LoadWorksets()

    def MoveElementsBetweenWorksets(self, sender, args):
        """Move elements from one workset to another"""
        try:
            # ถ้าไม่มี worksets
            if not self.all_worksets:
                forms.alert("ไม่พบ Workset ในโปรเจค", title="ข้อผิดพลาด")
                return

            # ----- เลือก Workset ต้นทาง -----
            # สร้างรายการชื่อ worksets สำหรับ dropdown
            source_names = []
            source_dict = {}
            for ws in self.all_worksets:
                element_count = self.element_counts.get(get_id_value(ws.Id), 0)
                display_name = "{} ({} elements)".format(ws.Name, element_count)
                source_names.append(display_name)
                source_dict[display_name] = ws

            source_display = forms.ask_for_one_item(
                source_names,
                title="เลือก Workset ต้นทาง",
                prompt="เลือก Workset ต้นทาง:"
            )

            if not source_display:
                return
                
            source_ws = source_dict[source_display]

            # ----- เลือก Workset ปลายทาง -----
            # กรองออก workset ต้นทาง
            target_names = []
            target_dict = {}
            for ws in self.all_worksets:
                if get_id_value(ws.Id) != get_id_value(source_ws.Id):
                    element_count = self.element_counts.get(get_id_value(ws.Id), 0)
                    display_name = "{} ({} elements)".format(ws.Name, element_count)
                    target_names.append(display_name)
                    target_dict[display_name] = ws

            if not target_names:
                forms.alert("ไม่มี Workset อื่นให้เลือกเป็นปลายทาง", title="ข้อผิดพลาด")
                return

            target_display = forms.ask_for_one_item(
                target_names,
                title="เลือก Workset ปลายทาง",
                prompt="เลือก Workset ปลายทาง:"
            )

            if not target_display:
                return
                
            target_ws = target_dict[target_display]

            # ----- ดึงรายการ Element ใน Workset ต้นทาง -----
            elements = WorksetManager.get_elements_in_workset(source_ws)
            if not elements:
                forms.alert("ไม่พบองค์ประกอบใน Workset ต้นทาง '{}'".format(source_ws.Name))
                return

            # ----- คอนเฟิร์ม -----
            confirm = forms.alert(
                "ต้องการย้ายองค์ประกอบ {} รายการ\nจาก '{}' ไปยัง '{}' ?".format(
                    len(elements), source_ws.Name, target_ws.Name),
                options=["ย้าย", "ยกเลิก"]
            )

            if confirm != "ย้าย":
                return

            # ----- เริ่มย้าย -----
            with revit.Transaction("Move Elements Between Worksets"):
                success = 0
                fail = 0

                for element in elements:
                    try:
                        param = element.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM)
                        if param and not param.IsReadOnly:
                            param.Set(get_id_value(target_ws.Id))
                            success += 1
                        else:
                            fail += 1
                    except:
                        fail += 1
                        continue

            # ----- แสดงผล -----
            msg = ("ย้ายองค์ประกอบเสร็จสิ้น\n"
                   "จาก Workset: {}\n"
                   "ไปยัง: {}\n\n"
                   "สำเร็จ: {}\n"
                   "ไม่สำเร็จ: {}").format(
                source_ws.Name, target_ws.Name, success, fail
            )

            forms.alert(msg, title="ผลการย้ายองค์ประกอบ")

            # รีเฟรชข้อมูล
            self.LoadWorksets()

        except Exception as e:
            logger.error("Error in MoveElementsBetweenWorksets: {}".format(e))
            forms.alert("เกิดข้อผิดพลาดระหว่างย้ายองค์ประกอบ:\n{}".format(str(e)), title="ข้อผิดพลาด")

    def CloseForm(self, sender, args):
        """Close the form"""
        self.DialogResult = DialogResult.OK
        self.Close()

def main():
    try:
        # Check if worksharing is enabled
        if not doc.IsWorkshared:
            forms.alert("โปรเจคนี้ไม่ได้เปิดใช้งาน Worksharing\nไม่สามารถใช้ Workset Manager ได้", 
                       title="ข้อผิดพลาด")
            return

        # Check if there are any worksets
        worksets = WorksetManager.get_all_worksets()
        if not worksets:
            forms.alert("ไม่พบ Workset ในโปรเจคนี้", title="ข้อผิดพลาด")
            return

        form = WorksetManagerForm()
        form.ShowDialog()

    except Exception as e:
        logger.error("Error in Workset Manager: {}".format(traceback.format_exc()))
        forms.alert("ข้อผิดพลาดในการเปิด Workset Manager:\n{}".format(str(e)), title="ข้อผิดพลาด")

if __name__ == "__main__":
    main()
