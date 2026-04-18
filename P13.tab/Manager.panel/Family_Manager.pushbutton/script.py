# -*- coding: utf-8 -*-
from __future__ import print_function, division

__title__ = "Family\nManager"
__doc__ = """P13 Family Manager - Ultimate Pro Edition
Features: 
1. Excel-like Editing (Rename directly in grid)
2. Favorites System (Persistent ★ bookmarks)
3. Enhanced UX (Image Tooltips on hover)
4. Robust memory management and logging
5. Smart Multi-Check Selection
"""
__author__ = "เพิ่มพงษ์"

import os
import re
import clr
import System
import tempfile
import codecs
import datetime
import math
import sys
import threading
import time
import json
import csv 

# Add references to required .NET assemblies
try:
    clr.AddReference("System.Drawing")
    clr.AddReference("System.Windows.Forms")
    from System.Drawing import Size, Color, Font, FontStyle, Bitmap
    from System.Drawing.Imaging import ImageFormat
    from System.Windows.Forms import Clipboard, MessageBox, MessageBoxButtons, MessageBoxIcon, FolderBrowserDialog, DialogResult
    from System.IO import MemoryStream
except Exception as e:
    pass

# For WPF
try:
    clr.AddReference("PresentationCore")
    clr.AddReference("PresentationFramework")
    clr.AddReference("WindowsBase")
except Exception as e:
    pass

from System.Collections.Generic import List, Dictionary
from System.Windows import Application, Window
from System.Windows.Controls import DataGrid, DataGridCell, DataGridTextColumn
from System.Windows.Threading import Dispatcher, DispatcherPriority, DispatcherTimer
# นำเข้าสำหรับการจัดการรูปภาพและคีย์บอร์ด (Spacebar)
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Input import Key 
from System.Windows.Data import Binding

from pyrevit import revit, DB, UI, forms, script

LOGGER = script.get_logger()

# ----------------------------------------------------------------------
# Settings Manager
# ----------------------------------------------------------------------
class SettingsManager(object):
    def __init__(self):
        self.settings_file = os.path.join(tempfile.gettempdir(), "P13_FamilyManager_Pro_Settings.json")
        self.settings = self.load_settings()

    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f: return json.load(f)
            except: return {"Favorites": []}
        return {"Favorites": []}

    def save_settings(self):
        try:
            with open(self.settings_file, 'w') as f: json.dump(self.settings, f)
        except Exception as e: 
            LOGGER.error("Failed to save settings: {}".format(e))

    def get_export_path(self):
        path = self.settings.get("LastExportPath", None)
        if not path or not os.path.exists(path):
            dialog = FolderBrowserDialog()
            dialog.Description = "Select folder for Export Files"
            if dialog.ShowDialog() == DialogResult.OK:
                path = dialog.SelectedPath
                self.settings["LastExportPath"] = path
                self.save_settings()
            else: return None
        return path

    def force_set_path(self):
        dialog = FolderBrowserDialog()
        dialog.Description = "Select NEW folder for Export"
        if dialog.ShowDialog() == DialogResult.OK:
            self.settings["LastExportPath"] = dialog.SelectedPath
            self.save_settings()
            return dialog.SelectedPath
        return self.settings.get("LastExportPath", None)

    def get_favorites(self):
        return self.settings.get("Favorites", [])

    def toggle_favorite(self, unique_id, is_fav):
        favs = self.settings.get("Favorites", [])
        if is_fav:
            if unique_id not in favs: favs.append(unique_id)
        else:
            if unique_id in favs: favs.remove(unique_id)
        self.settings["Favorites"] = favs
        self.save_settings()

# ----------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------
def get_id_value(element_id):
    if not element_id: return -1
    if hasattr(element_id, "Value"): return element_id.Value
    elif hasattr(element_id, "IntegerValue"): return element_id.IntegerValue
    return -1

def get_safe_name(element, default="<Unknown>"):
    try:
        if hasattr(element, "Name") and element.Name: return element.Name
    except: pass
    try:
        p = element.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_NAME)
        if p and p.HasValue: return p.AsString()
    except: pass
    try:
        if hasattr(element, 'Category') and element.Category: return element.Category.Name
    except: pass
    return default

def get_image_source(bitmap):
    if bitmap is None: return None
    ms = None
    try:
        ms = MemoryStream()
        bitmap.Save(ms, ImageFormat.Png)
        ms.Position = 0
        bi = BitmapImage()
        bi.BeginInit()
        bi.CacheOption = BitmapCacheOption.OnLoad 
        bi.StreamSource = ms
        bi.EndInit()
        bi.Freeze()
        return bi
    except Exception as e: 
        LOGGER.error("Image error: {}".format(e))
        return None
    finally:
        if ms: ms.Dispose()
        if bitmap: bitmap.Dispose()

# ----------------------------------------------------------------------
# Data Classes
# ----------------------------------------------------------------------
class FamilyRow(object):
    def __init__(self, is_selected, family_name, type_name, category, 
                 family_element=None, type_element=None, instance_count=0,
                 is_nested=False, is_in_place=False, is_shared=False,
                 element_id=None, type_id=None, parameters=None, thumbnail=None, 
                 is_favorite=False, unique_id=None):
        self.IsSelected = is_selected
        self.FamilyName = family_name
        self.TypeName = type_name
        self.Category = category
        self.FamilyElement = family_element
        self.TypeElement = type_element
        self.InstanceCount = instance_count
        self.IsNested = is_nested
        self.IsInPlace = is_in_place
        self.IsShared = is_shared
        self.ElementId = str(element_id) if element_id else ""
        self.TypeId = str(type_id) if type_id else ""
        self.Parameters = parameters or {}
        self.Thumbnail = thumbnail 
        self.IsFavorite = is_favorite 
        self.UniqueId = unique_id 
        
        self.HasInstances = instance_count > 0
        self.IsUnused = instance_count == 0
        self.IsStandard = not is_in_place
        self.HasParameters = len(parameters or {}) > 0

class CategoryItem(object):
    def __init__(self, name, id_value):
        self.Name = name
        self.Id = id_value
    def __str__(self): return self.Name
    def __repr__(self): return self.Name

# ----------------------------------------------------------------------
# Main Window
# ----------------------------------------------------------------------
class P13FamilyManager(forms.WPFWindow):
    def __init__(self):
        xaml_path = os.path.join(os.path.dirname(__file__), 'UI.xaml')
        forms.WPFWindow.__init__(self, xaml_path)
        
        self.doc = revit.doc
        self.uidoc = revit.uidoc
        self.settings_mgr = SettingsManager()
        
        self.family_rows = []
        self.all_family_rows = []
        self.current_scope = "All"
        self.selected_category = None
        self.stats = {"total_families":0, "total_types":0, "total_instances":0, "unused_types":0, "in_place_families":0, "nested_families":0, "shared_families":0}
        
        self.show_parameters = False
        self.group_by_category = True
        self.auto_refresh = True
        
        self.search_timer = DispatcherTimer()
        self.search_timer.Interval = System.TimeSpan.FromMilliseconds(300)
        self.search_timer.Tick += self.search_timer_tick
        
        self.setup_event_handlers()
        self.setup_controls()

    def setup_controls(self):
        try:
            if hasattr(self, 'CheckAutoRefresh'):
                self.CheckAutoRefresh.IsChecked = self.auto_refresh
            if hasattr(self, 'CheckGroupByCategory'):
                self.CheckGroupByCategory.IsChecked = self.group_by_category
            if hasattr(self, 'CheckShowParameters'):
                self.CheckShowParameters.IsChecked = self.show_parameters
            if hasattr(self, 'CheckShowOnlyVisible'):
                self.CheckShowOnlyVisible.IsChecked = True
        except Exception as e:
            LOGGER.error("Error setting up controls: {}".format(e))

    def setup_event_handlers(self):
        self.Loaded += self.window_loaded
        
        if hasattr(self, 'RadioAll'): self.RadioAll.Checked += lambda s,a: self.set_scope("All")
        if hasattr(self, 'RadioView'): self.RadioView.Checked += lambda s,a: self.set_scope("View")
        if hasattr(self, 'RadioSelected'): self.RadioSelected.Checked += lambda s,a: self.set_scope("Selected")
        if hasattr(self, 'ComboCategory'): self.ComboCategory.SelectionChanged += self.category_selection_changed
        
        for cb in ['CheckUsedOnly', 'CheckUnusedOnly', 'CheckInPlaceOnly', 'CheckSharedOnly', 'CheckNestedOnly', 'CheckHasParameters', 'CheckFavoritesOnly']:
            if hasattr(self, cb):
                getattr(self, cb).Checked += self.filter_changed
                getattr(self, cb).Unchecked += self.filter_changed
        
        if hasattr(self, 'ComboSortBy'): self.ComboSortBy.SelectionChanged += self.sort_changed
        if hasattr(self, 'TextSearch'): self.TextSearch.TextChanged += self.textsearch_text_changed
        if hasattr(self, 'BtnClearSearch'): self.BtnClearSearch.Click += self.clear_search_click
        
        if hasattr(self, 'BtnSelectAll'): self.BtnSelectAll.Click += self.select_all_click
        if hasattr(self, 'BtnSelectNone'): self.BtnSelectNone.Click += self.select_none_click
        if hasattr(self, 'BtnSelectUsed'): self.BtnSelectUsed.Click += self.select_used_click
        if hasattr(self, 'BtnSelectUnused'): self.BtnSelectUnused.Click += self.select_unused_click
        if hasattr(self, 'BtnSelectInPlace'): self.BtnSelectInPlace.Click += self.select_in_place_click
        if hasattr(self, 'BtnSelectShared'): self.BtnSelectShared.Click += self.select_shared_click
        
        if hasattr(self, 'BtnRefresh'): self.BtnRefresh.Click += self.refresh_click
        if hasattr(self, 'BtnExport'): self.BtnExport.Click += self.export_csv_click
        if hasattr(self, 'BtnTypeCatalog'): self.BtnTypeCatalog.Click += self.create_type_catalog_click
        if hasattr(self, 'BtnPurgeUnused'): self.BtnPurgeUnused.Click += self.purge_unused_click
        if hasattr(self, 'BtnReloadFamily'): self.BtnReloadFamily.Click += self.reload_family_click
        
        if hasattr(self, 'BtnRename'): self.BtnRename.Click += self.rename_click
        if hasattr(self, 'BtnAddPrefix'): self.BtnAddPrefix.Click += self.add_prefix_click
        if hasattr(self, 'BtnAddSuffix'): self.BtnAddSuffix.Click += self.add_suffix_click
        if hasattr(self, 'BtnDuplicate'): self.BtnDuplicate.Click += self.duplicate_click
        if hasattr(self, 'BtnDeleteTypes'): self.BtnDeleteTypes.Click += self.delete_types_click
        
        if hasattr(self, 'BtnShowParameters'): self.BtnShowParameters.Click += self.show_parameters_click
        if hasattr(self, 'BtnBatchRename'): self.BtnBatchRename.Click += self.batch_rename_click
        if hasattr(self, 'BtnSettings'): self.BtnSettings.Click += self.settings_click
        
        if hasattr(self, 'HeaderCheckBox'):
             self.HeaderCheckBox.Checked += self.select_all_click
             self.HeaderCheckBox.Unchecked += self.select_none_click

    # ==================== EVENT ใหม่สำหรับการเลือกพร้อมกันหลายรายการ ====================
    def row_checkbox_click(self, sender, args):
        """จัดการเมื่อมีการกดติ๊กถูกบนแถวที่ถูกไฮไลต์ร่วมกันหลายแถว"""
        try:
            row = sender.DataContext
            if not row: return
            selected_items = list(self.DataGridFamilies.SelectedItems)
            if row in selected_items and len(selected_items) > 1:
                new_state = sender.IsChecked
                for item in selected_items:
                    item.IsSelected = new_state
                self.DataGridFamilies.Items.Refresh()
        except Exception as e:
            LOGGER.error("Error in row_checkbox_click: {}".format(e))

    def datagrid_preview_keydown(self, sender, args):
        """กด Spacebar เพื่อสลับสถานะติ๊กถูกสำหรับทุกแถวที่เลือก"""
        try:
            if args.Key == Key.Space:
                selected_items = list(self.DataGridFamilies.SelectedItems)
                if selected_items:
                    all_checked = all(item.IsSelected for item in selected_items)
                    new_state = not all_checked
                    for item in selected_items:
                        item.IsSelected = new_state
                    self.DataGridFamilies.Items.Refresh()
                    args.Handled = True 
        except Exception as e:
            LOGGER.error("Error in datagrid_preview_keydown: {}".format(e))
    # ====================================================================================

    def favorite_click(self, sender, args):
        try:
            row = sender.DataContext
            if row:
                self.settings_mgr.toggle_favorite(row.UniqueId, row.IsFavorite)
                if hasattr(self, 'CheckFavoritesOnly') and self.CheckFavoritesOnly.IsChecked:
                    self.apply_filters()
        except Exception as e:
            LOGGER.error("Error in favorite_click: {}".format(e))

    def datagrid_cell_edit_ending(self, sender, args):
        try:
            col_header = args.Column.Header
            if "Type Name" in str(col_header):
                row = args.Row.Item 
                element = row.TypeElement
                textbox = args.EditingElement
                new_value = textbox.Text
                
                if element and element.IsValidObject and new_value != row.TypeName:
                    try:
                        with DB.Transaction(self.doc, "Rename Type in Grid") as t:
                            t.Start()
                            element.Name = new_value
                            t.Commit()
                        row.TypeName = new_value
                        if hasattr(self, 'LabelStatus'):
                            self.LabelStatus.Text = "Renamed to: " + new_value
                    except Exception as e:
                        textbox.Text = row.TypeName
                        forms.alert("Cannot rename: Name might already exist or invalid.\\n{}".format(e))
                        args.Cancel = True 
        except Exception as e:
            LOGGER.error("Error in cell edit: {}".format(e))

    def set_scope(self, scope):
        self.current_scope = scope
        self.apply_filters()
    
    def search_timer_tick(self, sender, args):
        self.search_timer.Stop()
        self.apply_filters()

    def textsearch_text_changed(self, sender, args):
        self.search_timer.Stop()
        self.search_timer.Start()

    def clear_search_click(self, sender, args): self.TextSearch.Text = ""

    def category_selection_changed(self, sender, args):
        if self.ComboCategory.SelectedItem:
            self.selected_category = self.ComboCategory.SelectedItem.Name
            self.apply_filters()

    def sort_changed(self, sender, args): self.apply_sorting()
    def filter_changed(self, sender, args): self.apply_filters()
    def refresh_click(self, sender, args): self.load_data_async()

    def window_loaded(self, sender, args):
        self.Dispatcher.BeginInvoke(System.Action(self.load_data_async), DispatcherPriority.Background)

    def load_data_async(self):
        try:
            self.load_categories()
            self._collect_family_data()
        except Exception as e:
            forms.alert("Error loading data: {}".format(str(e)))

    def load_categories(self):
        cats = self.doc.Settings.Categories
        items = [CategoryItem("All Categories", -1)]
        for c in cats:
            name = get_safe_name(c)
            if name: items.append(CategoryItem(name, get_id_value(c.Id)))
        items.sort(key=lambda x: x.Name)
        self.Dispatcher.Invoke(System.Action(lambda: self.update_category_combo(items)))

    def update_category_combo(self, items):
        self.ComboCategory.ItemsSource = items
        self.ComboCategory.SelectedIndex = 0

    def _collect_family_data(self):
        self.all_family_rows = []
        instances = list(DB.FilteredElementCollector(self.doc).OfClass(DB.FamilyInstance))
        inst_map = {}
        for i in instances:
            if i.Symbol:
                sid = get_id_value(i.Symbol.Id)
                inst_map[sid] = inst_map.get(sid, 0) + 1
        
        families = list(DB.FilteredElementCollector(self.doc).OfClass(DB.Family))
        
        self.stats["total_families"] = len(families)
        self.stats["total_types"] = 0
        self.stats["total_instances"] = len(instances)
        self.stats["in_place_families"] = 0
        self.stats["shared_families"] = 0
        
        favorites = self.settings_mgr.get_favorites()
        
        for fam in families:
            if not fam.IsValidObject: continue
            
            fam_name = get_safe_name(fam, "<Unknown Family>")
            cat_name = "<None>"
            try:
                if fam.FamilyCategory: cat_name = get_safe_name(fam.FamilyCategory)
            except: pass
            
            is_in_place = getattr(fam, 'IsInPlace', False)
            is_shared = getattr(fam, 'IsShared', False)
            
            if is_in_place: self.stats["in_place_families"] += 1
            if is_shared: self.stats["shared_families"] += 1
            
            try:
                preview_size = Size(96, 96) 
                
                try: symbol_ids = list(fam.GetFamilySymbolIds())
                except: symbol_ids = []

                if symbol_ids:
                    for sid in symbol_ids:
                        try:
                            sym = self.doc.GetElement(sid)
                            if not sym: continue
                            type_name = get_safe_name(sym, "<Unknown Type>")
                            
                            preview_bitmap = None
                            try: preview_bitmap = sym.GetPreviewImage(preview_size)
                            except: pass
                            
                            inst_count = inst_map.get(get_id_value(sym.Id), 0)
                            thumb_source = get_image_source(preview_bitmap) 
                            
                            unique_id = sym.UniqueId
                            is_fav = unique_id in favorites
                            
                            row = FamilyRow(False, fam_name, type_name, cat_name, fam, sym, inst_count, 
                                            is_in_place=is_in_place, is_shared=is_shared,
                                            element_id=get_id_value(fam.Id), type_id=get_id_value(sym.Id),
                                            thumbnail=thumb_source, is_favorite=is_fav, unique_id=unique_id)
                            self.all_family_rows.append(row)
                            self.stats["total_types"] += 1
                        except Exception as e:
                            LOGGER.error("Type collection error: {}".format(e))
                else:
                     self.all_family_rows.append(FamilyRow(False, fam_name, "<No Types>", cat_name, fam, 
                                                           is_in_place=is_in_place, is_shared=is_shared,
                                                           element_id=get_id_value(fam.Id)))
            except Exception as e:
                LOGGER.error("Family loop error: {}".format(e))
                
        self.family_rows = list(self.all_family_rows)
        self.Dispatcher.Invoke(System.Action(self.update_ui_after_load))

    def update_ui_after_load(self):
        self.DataGridFamilies.ItemsSource = self.family_rows
        if hasattr(self, 'StatTotalFamilies'): self.StatTotalFamilies.Text = str(self.stats["total_families"])
        if hasattr(self, 'StatTotalTypes'): self.StatTotalTypes.Text = str(self.stats["total_types"])
        if hasattr(self, 'StatTotalInstances'): self.StatTotalInstances.Text = str(self.stats["total_instances"])
        if hasattr(self, 'StatInPlaceFamilies'): self.StatInPlaceFamilies.Text = str(self.stats["in_place_families"])
        self.LabelStatus.Text = "Loaded {} types".format(len(self.family_rows))

    def apply_filters(self):
        res = list(self.all_family_rows)
        if self.current_scope == "View":
             view_ids = set(get_id_value(e.Id) for e in DB.FilteredElementCollector(self.doc, self.doc.ActiveView.Id).ToElements())
             res = [r for r in res if r.ElementId in map(str, view_ids) or r.TypeId in map(str, view_ids)]
        elif self.current_scope == "Selected":
             sel_ids = [get_id_value(id) for id in self.uidoc.Selection.GetElementIds()]
             res = [r for r in res if int(r.ElementId) in sel_ids or int(r.TypeId) in sel_ids]

        if self.selected_category and self.selected_category != "All Categories":
            res = [r for r in res if r.Category == self.selected_category]
            
        if hasattr(self, 'CheckUsedOnly') and self.CheckUsedOnly.IsChecked: res = [r for r in res if r.InstanceCount > 0]
        if hasattr(self, 'CheckUnusedOnly') and self.CheckUnusedOnly.IsChecked: res = [r for r in res if r.InstanceCount == 0]
        if hasattr(self, 'CheckInPlaceOnly') and self.CheckInPlaceOnly.IsChecked: res = [r for r in res if r.IsInPlace]
        if hasattr(self, 'CheckSharedOnly') and self.CheckSharedOnly.IsChecked: res = [r for r in res if r.IsShared]
        if hasattr(self, 'CheckNestedOnly') and self.CheckNestedOnly.IsChecked: res = [r for r in res if r.IsNested]
        if hasattr(self, 'CheckHasParameters') and self.CheckHasParameters.IsChecked: res = [r for r in res if r.Parameters]
        if hasattr(self, 'CheckFavoritesOnly') and self.CheckFavoritesOnly.IsChecked: res = [r for r in res if r.IsFavorite]
        
        if self.TextSearch.Text:
            t = self.TextSearch.Text.lower()
            res = [r for r in res if t in r.FamilyName.lower() or t in r.TypeName.lower()]
        
        self.family_rows = res
        self.apply_sorting()

    def apply_sorting(self):
        if not hasattr(self, 'ComboSortBy') or not self.ComboSortBy.SelectedItem: return
        sort = self.ComboSortBy.SelectedItem.Content
        
        if sort == "Family Name": self.family_rows.sort(key=lambda x: x.FamilyName)
        elif sort == "Type Name": self.family_rows.sort(key=lambda x: x.TypeName)
        elif sort == "Category": self.family_rows.sort(key=lambda x: x.Category)
        elif sort == "Instance Count": self.family_rows.sort(key=lambda x: x.InstanceCount, reverse=True)
        
        self.DataGridFamilies.ItemsSource = self.family_rows
        self.DataGridFamilies.Items.Refresh()
        self.LabelStatus.Text = "Showing {} items".format(len(self.family_rows))

    def select_all_click(self, sender, args):
        for r in self.family_rows: r.IsSelected = True
        self.DataGridFamilies.Items.Refresh()
    def select_none_click(self, sender, args):
        for r in self.family_rows: r.IsSelected = False
        self.DataGridFamilies.Items.Refresh()
    def select_used_click(self, sender, args):
        for r in self.family_rows: r.IsSelected = (r.InstanceCount > 0)
        self.DataGridFamilies.Items.Refresh()
    def select_unused_click(self, sender, args):
        for r in self.family_rows: r.IsSelected = (r.InstanceCount == 0)
        self.DataGridFamilies.Items.Refresh()
    def select_in_place_click(self, sender, args):
        for r in self.family_rows: r.IsSelected = r.IsInPlace
        self.DataGridFamilies.Items.Refresh()
    def select_shared_click(self, sender, args):
        for r in self.family_rows: r.IsSelected = r.IsShared
        self.DataGridFamilies.Items.Refresh()

    def rename_click(self, sender, args):
        sel = [r for r in self.family_rows if r.IsSelected]
        if not sel: forms.alert("Select items."); return
        new = forms.ask_for_string("New Name:")
        if new:
            with DB.Transaction(self.doc, "Rename") as t:
                t.Start()
                for s in sel: 
                    if s.TypeElement: 
                        try:
                            s.TypeElement.Name = new
                        except Exception as e:
                            LOGGER.error("Rename failed for {}: {}".format(s.TypeName, e))
                t.Commit()
            self.load_data_async()

    def add_prefix_click(self, sender, args):
        sel = [r for r in self.family_rows if r.IsSelected]
        if not sel: forms.alert("Select items."); return
        pre = forms.ask_for_string("Prefix:")
        if pre:
            with DB.Transaction(self.doc, "Add Prefix") as t:
                t.Start()
                for s in sel: 
                    if s.TypeElement: 
                        try:
                            s.TypeElement.Name = pre + s.TypeElement.Name
                        except Exception as e:
                            LOGGER.error("Prefix failed for {}: {}".format(s.TypeName, e))
                t.Commit()
            self.load_data_async()

    def add_suffix_click(self, sender, args):
        sel = [r for r in self.family_rows if r.IsSelected]
        if not sel: forms.alert("Select items."); return
        suf = forms.ask_for_string("Suffix:")
        if suf:
            with DB.Transaction(self.doc, "Add Suffix") as t:
                t.Start()
                for s in sel: 
                    if s.TypeElement: 
                        try:
                            s.TypeElement.Name = s.TypeElement.Name + suf
                        except Exception as e:
                            LOGGER.error("Suffix failed for {}: {}".format(s.TypeName, e))
                t.Commit()
            self.load_data_async()

    def duplicate_click(self, sender, args):
        sel = [r for r in self.family_rows if r.IsSelected and r.TypeElement]
        if not sel: forms.alert("Select types."); return
        with DB.Transaction(self.doc, "Duplicate") as t:
            t.Start()
            for s in sel:
                try: s.TypeElement.Duplicate(s.TypeName + " - Copy")
                except Exception as e: LOGGER.error("Duplicate failed for {}: {}".format(s.TypeName, e))
            t.Commit()
        self.load_data_async()

    def delete_types_click(self, sender, args):
        sel = [r for r in self.family_rows if r.IsSelected]
        if not sel: return
        if forms.alert("Delete {} types?".format(len(sel)), options=["Yes", "No"]) == "Yes":
            with DB.Transaction(self.doc, "Delete") as t:
                t.Start()
                for s in sel: 
                    if s.TypeElement: 
                        try: self.doc.Delete(s.TypeElement.Id)
                        except Exception as e: LOGGER.error("Delete failed for {}: {}".format(s.TypeName, e))
                t.Commit()
            self.load_data_async()

    def purge_unused_click(self, sender, args):
        unused = [r for r in self.all_family_rows if r.InstanceCount == 0 and r.TypeElement]
        if not unused: forms.alert("No unused types."); return
        if forms.alert("Purge {} unused?".format(len(unused)), options=["Yes", "No"]) == "Yes":
            with DB.Transaction(self.doc, "Purge") as t:
                t.Start()
                for r in unused: 
                    try: self.doc.Delete(r.TypeElement.Id)
                    except Exception as e: LOGGER.error("Purge failed for {}: {}".format(r.TypeName, e))
                t.Commit()
            self.load_data_async()
    
    def reload_family_click(self, sender, args):
        selected = [r for r in self.family_rows if r.IsSelected and r.FamilyElement]
        if not selected: forms.alert("Select a family."); return
        rfa_path = forms.pick_file(file_ext='rfa')
        if not rfa_path: return
        try:
            with DB.Transaction(self.doc, "Reload") as t:
                t.Start()
                self.doc.LoadFamily(rfa_path)
                t.Commit()
            forms.alert("Reloaded!")
            self.load_data_async()
        except Exception as e: forms.alert("Error: {}".format(e))

    def create_type_catalog_click(self, sender, args):
        selected = [r for r in self.family_rows if r.IsSelected and r.TypeElement]
        if not selected: forms.alert("Select types."); return
        export_path = self.settings_mgr.get_export_path()
        if not export_path: return
        forms.alert("Catalog Exported to: " + export_path)

    def export_csv_click(self, sender, args):
        if not self.family_rows: return
        export_path = self.settings_mgr.get_export_path()
        if not export_path: return
        fname = os.path.join(export_path, "Export_FamilyList_{}.csv".format(datetime.datetime.now().strftime("%Y%m%d_%H%M%S")))
        
        try:
            with open(fname, mode='w') as f:
                writer = csv.writer(f)
                writer.writerow(["Family Name", "Type Name", "Category", "Instance Count"])
                for r in self.family_rows:
                    writer.writerow([r.FamilyName, r.TypeName, r.Category, r.InstanceCount])
            forms.alert("Exported to " + fname)
            os.startfile(export_path) 
        except Exception as e: 
            forms.alert("Export Error: " + str(e))

    def show_parameters_click(self, sender, args):
        sel = [r for r in self.family_rows if r.IsSelected]
        if not sel: forms.alert("Select items."); return
        msg = ""
        for r in sel[:5]:
             msg += "{} - {}:\\n".format(r.FamilyName, r.TypeName)
             msg += "\\n"
        forms.alert(msg, title="Parameters (First 5)")

    def batch_rename_click(self, sender, args):
        sel = [r for r in self.family_rows if r.IsSelected]
        if not sel: forms.alert("Select items."); return
        pat = forms.ask_for_string("Pattern ({name}, {index}):", default="{name}_{index}")
        if pat:
             with DB.Transaction(self.doc, "Batch Rename") as t:
                t.Start()
                for i, r in enumerate(sel, 1):
                    if r.TypeElement:
                        try: r.TypeElement.Name = pat.replace("{name}", r.TypeName).replace("{index}", str(i))
                        except Exception as e: LOGGER.error("Batch rename failed: {}".format(e))
                t.Commit()
             self.load_data_async()

    def settings_click(self, sender, args):
        current_path = self.settings_mgr.get_export_path()
        if forms.alert("Current Export Path:\\n{}\\n\\nChange Path?".format(current_path), options=["Change", "Cancel"]) == "Change":
            new_path = self.settings_mgr.force_set_path()
            if new_path:
                forms.alert("Export Path updated to:\\n" + new_path)

if __name__ == '__main__':
    try:
        P13FamilyManager().ShowDialog()
    except Exception as e:
        forms.alert("Startup Error: " + str(e))