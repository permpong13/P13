# -*- coding: utf-8 -*-
__title__ = "ImportCAD\nManager"
__author__ = "เพิ่มพงษ์ ทวีกุล"
__doc__ = "Manage CAD Imports - Explode, Delete, Open View (Fixed for Revit 2025/2026)"

import clr
clr.AddReference("System")
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

import System
from pyrevit import revit, DB
from System.Windows import Window, Thickness
from System.Windows.Controls import (
    Grid, RowDefinition, ColumnDefinition, DataGrid, DataGridTextColumn, 
    Button, StackPanel, Label, ProgressBar, TextBox, DataGridLength, DataGridLengthUnitType
)
from System.Windows.Data import Binding
from System.Windows.Media import Brushes, FontFamily
from System.Windows.Input import MouseButtonEventHandler, Key
from System.Collections.ObjectModel import ObservableCollection
import time

doc = revit.doc
uidoc = revit.uidoc

# ---------------------------------------------------------------------------
# CAD ITEM CLASS
# ---------------------------------------------------------------------------
class CADItem(object):
    def __init__(self, element_id, cad_name, view_name, view_type, status, element_obj, cad_path=""):
        self.element_id = element_id
        self.cad_name = cad_name
        self.view_name = view_name
        self.view_type = view_type
        self.status = status
        self.selected = False
        self.element_obj = element_obj
        self.cad_path = cad_path

# ---------------------------------------------------------------------------
# MAIN WINDOW
# ---------------------------------------------------------------------------
class CADImportWindow(Window):
    def __init__(self):
        Window.__init__(self)
        self.cad_data = ObservableCollection[CADItem]()
        self.all_cad_data = []
        self.Title = "CAD Import Manager - pyRevit (2025/2026 Compatible)"
        self.Width = 1100
        self.Height = 700
        self.WindowStartupLocation = System.Windows.WindowStartupLocation.CenterScreen
        self.last_search_time = 0
        self.search_delay = 0.3

        self.InitializeComponent()
        self.find_all_cad_imports()
        self.load_data()

    # =========================================================================
    # UI INITIALIZATION (Restored Original Layout)
    # =========================================================================
    def InitializeComponent(self):
        main_grid = Grid()
        self.Content = main_grid

        # Row Definitions
        row_heights = [(40, 0), (40, 0), (1, 1), (35, 0), (30, 0), (60, 0)]
        for h, t in row_heights:
            rd = RowDefinition()
            rd.Height = System.Windows.GridLength(h, System.Windows.GridUnitType.Pixel if t==0 else System.Windows.GridUnitType.Star)
            main_grid.RowDefinitions.Add(rd)

        # Column Definitions
        for i in range(3):
            cd = ColumnDefinition()
            if i == 0: cd.Width = System.Windows.GridLength(80, System.Windows.GridUnitType.Pixel)
            elif i == 1: cd.Width = System.Windows.GridLength(1, System.Windows.GridUnitType.Star)
            else: cd.Width = System.Windows.GridLength(180, System.Windows.GridUnitType.Pixel)
            main_grid.ColumnDefinitions.Add(cd)

        # Title
        title_label = Label()
        title_label.Content = "📁 CAD Import Manager (2025 Fixed)"
        title_label.FontSize = 16
        title_label.FontWeight = System.Windows.FontWeights.Bold
        title_label.Foreground = Brushes.DarkBlue
        title_label.HorizontalContentAlignment = System.Windows.HorizontalAlignment.Center
        title_label.VerticalContentAlignment = System.Windows.VerticalAlignment.Center
        title_label.Background = Brushes.LightSkyBlue
        Grid.SetRow(title_label, 0)
        Grid.SetColumnSpan(title_label, 3)
        main_grid.Children.Add(title_label)

        # Search Panel
        search_label = Label()
        search_label.Content = "ค้นหา:"
        search_label.FontWeight = System.Windows.FontWeights.Bold
        search_label.HorizontalContentAlignment = System.Windows.HorizontalAlignment.Right
        search_label.VerticalContentAlignment = System.Windows.VerticalAlignment.Center
        Grid.SetRow(search_label, 1)
        Grid.SetColumn(search_label, 0)
        main_grid.Children.Add(search_label)

        self.search_textbox = TextBox()
        self.search_textbox.Margin = Thickness(5)
        self.search_textbox.FontSize = 14
        self.search_textbox.VerticalContentAlignment = System.Windows.VerticalAlignment.Center
        self.search_textbox.TextChanged += self.on_search_text_changed
        self.search_textbox.KeyDown += self.on_search_key_down
        Grid.SetRow(self.search_textbox, 1)
        Grid.SetColumn(self.search_textbox, 1)
        main_grid.Children.Add(self.search_textbox)

        search_btn_panel = StackPanel()
        search_btn_panel.Orientation = System.Windows.Controls.Orientation.Horizontal
        
        btn_search = Button()
        btn_search.Content = "ค้นหา"
        btn_search.Width = 60; btn_search.Height = 25; btn_search.Margin = Thickness(5,0,0,0)
        btn_search.Click += self.search_click
        search_btn_panel.Children.Add(btn_search)

        btn_clear = Button()
        btn_clear.Content = "ล้าง"
        btn_clear.Width = 60; btn_clear.Height = 25; btn_clear.Margin = Thickness(5,0,0,0)
        btn_clear.Click += self.clear_search_click
        search_btn_panel.Children.Add(btn_clear)

        Grid.SetRow(search_btn_panel, 1)
        Grid.SetColumn(search_btn_panel, 2)
        main_grid.Children.Add(search_btn_panel)

        # DataGrid
        self.data_grid = DataGrid()
        self.data_grid.AutoGenerateColumns = False
        self.data_grid.IsReadOnly = True
        self.data_grid.SelectionMode = System.Windows.Controls.DataGridSelectionMode.Extended
        self.data_grid.MouseDoubleClick += MouseButtonEventHandler(self.open_cad_view)
        
        columns = [
            ("ID", "element_id", 80),
            ("Name", "cad_name", 200),
            ("View", "view_name", 150),
            ("Type", "view_type", 100),
            ("Status", "status", 100),
            ("Path", "cad_path", 250)
        ]
        for h, b, w in columns:
            col = DataGridTextColumn()
            col.Header = h
            col.Binding = Binding(b)
            col.Width = DataGridLength(w, DataGridLengthUnitType.Pixel)
            self.data_grid.Columns.Add(col)

        Grid.SetRow(self.data_grid, 2)
        Grid.SetColumnSpan(self.data_grid, 3)
        main_grid.Children.Add(self.data_grid)

        # Summary
        self.summary_label = Label()
        self.summary_label.Content = "Ready"
        self.summary_label.Background = Brushes.LightGray
        self.summary_label.HorizontalContentAlignment = System.Windows.HorizontalAlignment.Center
        self.summary_label.VerticalContentAlignment = System.Windows.VerticalAlignment.Center
        Grid.SetRow(self.summary_label, 3)
        Grid.SetColumnSpan(self.summary_label, 3)
        main_grid.Children.Add(self.summary_label)

        # Progress
        self.progress_bar = ProgressBar()
        self.progress_bar.Height = 20
        self.progress_bar.Margin = Thickness(5)
        Grid.SetRow(self.progress_bar, 4)
        Grid.SetColumnSpan(self.progress_bar, 3)
        main_grid.Children.Add(self.progress_bar)

        # Action Buttons
        btn_panel = StackPanel()
        btn_panel.Orientation = System.Windows.Controls.Orientation.Horizontal
        btn_panel.HorizontalAlignment = System.Windows.HorizontalAlignment.Center
        btn_panel.Margin = Thickness(5)

        actions = [
            ("Select All", Brushes.LightGreen, self.select_all_click),
            ("Clear Sel", Brushes.LightYellow, self.clear_selection_click),
            ("Explode Sel", Brushes.Orange, self.explode_selected_click),
            ("Delete Sel", Brushes.LightCoral, self.delete_selected_click),
            ("Explode All", Brushes.Gold, self.explode_all_click),
            ("Delete All", Brushes.Red, self.delete_all_click),
            ("Refresh", Brushes.LightBlue, self.refresh_click)
        ]

        for txt, col, func in actions:
            b = Button()
            b.Content = txt
            b.Background = col
            b.Width = 100; b.Height = 35; b.Margin = Thickness(2)
            b.Click += func
            btn_panel.Children.Add(b)

        Grid.SetRow(btn_panel, 5)
        Grid.SetColumnSpan(btn_panel, 3)
        main_grid.Children.Add(btn_panel)

    # =========================================================================
    # DATA & LOGIC (FIXED FOR 2025)
    # =========================================================================
    def get_safe_param(self, element, built_in_param_enum):
        """
        Safe method to get parameter string. 
        Handles missing Enum attributes in Revit 2025/Python environment.
        """
        try:
            # Try to get the parameter object
            param = element.get_Parameter(built_in_param_enum)
            if param and param.HasValue:
                return param.AsString()
        except Exception:
            # If Enum doesn't exist or any other error, return None quietly
            return None
        return None

    def get_cad_name_path(self, cad):
        cad_name = "N/A"
        cad_path = ""
        try:
            # Attempt to get Type
            elem_type = doc.GetElement(cad.GetTypeId())
            
            # 1. Get Name (Try Type name first)
            if elem_type:
                cad_name = elem_type.Name
            
            # 2. Get Path (Using Try/Except to bypass 'AttributeError')
            try:
                # Direct check for IMPORT_SYMBOL_FILENAME
                # If this line causes AttributeError, it will jump to except
                path_val = self.get_safe_param(cad, DB.BuiltInParameter.IMPORT_SYMBOL_FILENAME)
                if path_val:
                    cad_path = path_val
            except AttributeError:
                cad_path = "Path Access Error" # Enum Missing
            except Exception:
                pass

        except Exception as e:
            print("Error getting info: " + str(e))
            pass
        return cad_name, cad_path

    def find_all_cad_imports(self):
        self.all_cad_data = []
        self.cad_data.Clear()
        
        # Collect ImportInstance
        col = DB.FilteredElementCollector(doc).OfClass(DB.ImportInstance).WhereElementIsNotElementType()
        
        for cad in col:
            try:
                cad_name, cad_path = self.get_cad_name_path(cad)
                
                view_name, view_type = "Project-wide", "Project-wide"
                if cad.OwnerViewId != DB.ElementId.InvalidElementId:
                    v = doc.GetElement(cad.OwnerViewId)
                    if v:
                        view_name = v.Name
                        view_type = str(v.ViewType)

                # FIXED: Universal ID access (Works for 2024, 2025, 2026)
                # Use .ToString() to get the integer value safely as string
                id_str = str(cad.Id).replace("ElementId(Value=", "").replace(")", "")
                # Fallback if ToString format is different
                if not id_str.isdigit():
                     # Try property access if ToString fails
                     if hasattr(cad.Id, "Value"): id_str = str(cad.Id.Value)
                     elif hasattr(cad.Id, "IntegerValue"): id_str = str(cad.Id.IntegerValue)

                item = CADItem(id_str, cad_name, view_name, view_type, "Ready", cad, cad_path)
                self.all_cad_data.append(item)
                self.cad_data.Add(item)
            except Exception as e:
                print("Skip item: {}".format(str(e)))
                pass
        
        self.update_summary()

    # =========================================================================
    # SEARCH & UPDATE
    # =========================================================================
    def on_search_text_changed(self, sender, e):
        curr = time.time()
        if curr - self.last_search_time > self.search_delay:
            self.last_search_time = curr
            self.perform_search()

    def on_search_key_down(self, sender, e):
        if e.Key == Key.Enter: self.perform_search()
        elif e.Key == Key.Escape: self.clear_search_click(None, None)

    def search_click(self, sender, e): self.perform_search()
    
    def clear_search_click(self, sender, e):
        self.search_textbox.Text = ""
        self.load_full_data()

    def perform_search(self):
        txt = self.search_textbox.Text.lower().strip()
        if not txt:
            self.load_full_data()
            return
        
        filtered = []
        for x in self.all_cad_data:
            if (txt in str(x.cad_name).lower() or 
                txt in str(x.view_name).lower() or 
                txt in str(x.cad_path).lower() or 
                txt in str(x.element_id)):
                filtered.append(x)
        
        self.cad_data.Clear()
        for i in filtered: self.cad_data.Add(i)
        self.update_summary()

    def load_full_data(self):
        self.cad_data.Clear()
        for i in self.all_cad_data: self.cad_data.Add(i)
        self.update_summary()

    def load_data(self):
        self.data_grid.ItemsSource = self.cad_data
        self.update_summary()

    def update_summary(self):
        total = len(self.all_cad_data)
        curr = self.cad_data.Count
        sel = len(self.data_grid.SelectedItems) if self.data_grid.SelectedItems else 0
        self.summary_label.Content = "Total: {} | Shown: {} | Selected: {}".format(total, curr, sel)

    # =========================================================================
    # OPERATIONS (FIXED FOR 64-BIT ID)
    # =========================================================================
    def select_all_click(self, sender, e): self.data_grid.SelectAll(); self.update_summary()
    def clear_selection_click(self, sender, e): self.data_grid.UnselectAll(); self.update_summary()

    def explode_item(self, item):
        try:
            # FIXED: Int64 for Revit 2025
            eid = DB.ElementId(System.Int64(item.element_id))
            cad = doc.GetElement(eid)
            if cad:
                with DB.Transaction(doc, "Explode CAD") as t:
                    t.Start()
                    cad.Explode()
                    t.Commit()
                    item.status = "Exploded"
        except Exception as e: item.status = "Err: {}".format(e)

    def delete_item(self, item):
        try:
            eid = DB.ElementId(System.Int64(item.element_id))
            with DB.Transaction(doc, "Delete CAD") as t:
                t.Start()
                doc.Delete(eid)
                t.Commit()
                item.status = "Deleted"
        except Exception as e: item.status = "Err: {}".format(e)

    def _process(self, func, items):
        self.progress_bar.Maximum = len(items)
        self.progress_bar.Value = 0
        for i, item in enumerate(items):
            func(item)
            self.progress_bar.Value = i + 1
        self.refresh_click(None, None)

    def explode_selected_click(self, sender, e): self._process(self.explode_item, list(self.data_grid.SelectedItems))
    def delete_selected_click(self, sender, e): self._process(self.delete_item, list(self.data_grid.SelectedItems))
    
    def explode_all_click(self, sender, e): 
        # Process all visible items
        self._process(self.explode_item, list(self.cad_data))

    def delete_all_click(self, sender, e): 
        self._process(self.delete_item, list(self.cad_data))

    def refresh_click(self, sender, e):
        self.find_all_cad_imports()
        self.load_data()

    def open_cad_view(self, sender, e):
        if self.data_grid.SelectedItem:
            item = self.data_grid.SelectedItem
            if item.element_obj.OwnerViewId != DB.ElementId.InvalidElementId:
                uidoc.ActiveView = doc.GetElement(item.element_obj.OwnerViewId)

if __name__ == "__main__":
    CADImportWindow().ShowDialog()