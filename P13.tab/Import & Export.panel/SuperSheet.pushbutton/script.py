# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function

import os
import re
import json
import traceback
import clr
import datetime

# Import WPF Libraries
clr.AddReference('System.Windows.Forms')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from pyrevit import revit, DB, forms, output
from System.Collections.ObjectModel import ObservableCollection
from System.Collections.Generic import List
from System.Windows import (
    Window, WindowStartupLocation, GridLength, GridUnitType, 
    Thickness, VerticalAlignment, HorizontalAlignment, FontWeight, FontWeights, Visibility
)
from System.Windows.Data import Binding
from System.Windows.Controls import (
    Grid, RowDefinition, ColumnDefinition, GroupBox, StackPanel, Border,
    TextBlock, TextBox, Button, DataGrid, DataGridCheckBoxColumn, 
    DataGridTextColumn, Orientation, DataGridLength, DataGridLengthUnitType, 
    ComboBox, ListBox, CheckBox, DataGridSelectionMode, Expander, WrapPanel
)
from System.Windows.Media import Brushes, Color, ColorConverter

doc = revit.doc
THIS_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(THIS_DIR, 'p13_supersheet_config.json')
LAST_SETTING_FILE = os.path.join(THIS_DIR, 'p13_last_settings.json')

# --- DATA CLASS ---
class ExportItem(object):
    def __init__(self, obj):
        self.Include = False
        self.item_obj = obj
        self.Id = obj.Id
        self.Number = obj.SheetNumber or ""
        self.Name = obj.Name or ""
        self.Revision = self._get_rev()
        self.PreviewName = "" 

    def _get_rev(self):
        try:
            p = self.item_obj.get_Parameter(DB.BuiltInParameter.SHEET_CURRENT_REVISION)
            val = p.AsString() or p.AsValueString()
            return val if val else ""
        except: return ""

    def get_param_val(self, p_name):
        mapping = {"SheetNumber": DB.BuiltInParameter.SHEET_NUMBER, "SheetName": DB.BuiltInParameter.SHEET_NAME, "Current Revision": DB.BuiltInParameter.SHEET_CURRENT_REVISION}
        p = self.item_obj.get_Parameter(mapping[p_name]) if p_name in mapping else self.item_obj.LookupParameter(p_name.strip("{} "))
        if not p: p = doc.ProjectInformation.LookupParameter(p_name.strip("{} "))
        return p.AsValueString() or p.AsString() or "" if p else ""

# --- MAIN APP ---
class SuperSheetsUltimate(Window):
    def __init__(self):
        self.Title = "P13 SuperSheets 2026 | Professional Edition"
        self.Width = 1400 
        self.Height = 1050
        self.WindowStartupLocation = WindowStartupLocation.CenterScreen
        self.Background = Brushes.White
        self.FontSize = 13
        
        self._all_items = []
        self._profiles = {}
        self._all_params = []
        self._ignore_events = False 

        self._setup_ui()
        self.ContentRendered += self._initial_load
        self.Closing += lambda s, e: self._save_current_as_last()

    def _setup_ui(self):
        root_grid = Grid()
        root_grid.RowDefinitions.Add(RowDefinition(Height=GridLength.Auto)) 
        root_grid.RowDefinitions.Add(RowDefinition(Height=GridLength(1, GridUnitType.Star))) 
        root_grid.RowDefinitions.Add(RowDefinition(Height=GridLength.Auto)) 
        self.Content = root_grid

        # 1. HEADER (Soft Tone)
        header_border = Border(Background=Brushes.GhostWhite, Padding=Thickness(20, 15, 20, 15), 
                               BorderBrush=Brushes.LightGray, BorderThickness=Thickness(0,0,0,1))
        header_sp = StackPanel(Orientation=Orientation.Horizontal)
        
        header_sp.Children.Add(TextBlock(Text="🖨️ P13 SUPERSHEETS", FontWeight=FontWeights.Bold, 
                                        FontSize=18, Foreground=Brushes.SlateGray, 
                                        VerticalAlignment=VerticalAlignment.Center, Margin=Thickness(0,0,25,0)))
        
        header_sp.Children.Add(TextBlock(Text="Profile: ", VerticalAlignment=VerticalAlignment.Center))
        self.cboProfile = ComboBox(Width=180, Height=30, VerticalContentAlignment=VerticalAlignment.Center)
        self.cboProfile.SelectionChanged += self._on_profile_select
        header_sp.Children.Add(self.cboProfile)
        
        self.txtProfileName = TextBox(Width=120, Height=30, Margin=Thickness(10,0,0,0), VerticalContentAlignment=VerticalAlignment.Center)
        header_sp.Children.Add(self.txtProfileName)
        
        btn_save = Button(Content="Save", Width=60, Margin=Thickness(5,0,0,0), Background=Brushes.AliceBlue)
        btn_save.Click += self._on_save_profile
        header_sp.Children.Add(btn_save)
        
        btn_del = Button(Content="Delete", Width=60, Margin=Thickness(5,0,0,0), Background=Brushes.MistyRose)
        btn_del.Click += self._on_delete_profile
        header_sp.Children.Add(btn_del)

        btn_exp_p = Button(Content="Export Config", Width=90, Margin=Thickness(20,0,0,0), Background=Brushes.White)
        btn_exp_p.Click += self._on_export_config
        header_sp.Children.Add(btn_exp_p)

        btn_imp_p = Button(Content="Import Config", Width=90, Margin=Thickness(5,0,0,0), Background=Brushes.White)
        btn_imp_p.Click += self._on_import_config
        header_sp.Children.Add(btn_imp_p)
        
        header_border.Child = header_sp
        Grid.SetRow(header_border, 0); root_grid.Children.Add(header_border)

        # 2. MAIN
        main_layout = Grid(Margin=Thickness(20))
        for h in ["Auto", "Auto", "Auto", "*"]:
            main_layout.RowDefinitions.Add(RowDefinition(Height=GridLength.Auto if h == "Auto" else GridLength(1, GridUnitType.Star)))
        Grid.SetRow(main_layout, 1); root_grid.Children.Add(main_layout)

        # -- Export Settings --
        gb_format = GroupBox(Header="Export Settings", Padding=Thickness(10), Margin=Thickness(0,0,0,10), Foreground=Brushes.SlateGray)
        
        # Main format panel
        main_format_panel = StackPanel()
        
        # Format checkboxes row
        sp_f = StackPanel(Orientation=Orientation.Horizontal, Margin=Thickness(0,0,0,10))
        self.chkPDF = CheckBox(Content="PDF", IsChecked=True, VerticalAlignment=VerticalAlignment.Center, Margin=Thickness(0,0,15,0))
        self.chkDWG = CheckBox(Content="DWG", VerticalAlignment=VerticalAlignment.Center, Margin=Thickness(0,0,15,0))
        self.chkIFC = CheckBox(Content="IFC", VerticalAlignment=VerticalAlignment.Center, Margin=Thickness(0,0,15,0), Visibility=Visibility.Collapsed)
        self.chkNWC = CheckBox(Content="NWC", VerticalAlignment=VerticalAlignment.Center, Margin=Thickness(0,0,15,0), Visibility=Visibility.Collapsed)
        sp_f.Children.Add(self.chkPDF); sp_f.Children.Add(self.chkDWG); sp_f.Children.Add(self.chkIFC); sp_f.Children.Add(self.chkNWC)
        
        sp_f.Children.Add(TextBlock(Text="| Color: ", VerticalAlignment=VerticalAlignment.Center, Margin=Thickness(10,0,5,0)))
        self.cboColor = ComboBox(Width=90, Height=28); self.cboColor.Items.Add("Color"); self.cboColor.Items.Add("B&W"); self.cboColor.SelectedIndex = 0
        sp_f.Children.Add(self.cboColor)
        
        self.chkCombine = CheckBox(Content="Combine PDF", Margin=Thickness(20,0,0,0), VerticalAlignment=VerticalAlignment.Center)
        self.chkCombine.Checked += self._toggle_ui; self.chkCombine.Unchecked += self._toggle_ui
        sp_f.Children.Add(self.chkCombine)
        main_format_panel.Children.Add(sp_f)
        
        # PDF Advanced Options (ตามรูป)
        pdf_expander = Expander(Header="PDF Advanced Options", Margin=Thickness(0,5,0,0), 
                                Foreground=Brushes.SlateGray, FontWeight=FontWeights.SemiBold)
        pdf_options_panel = WrapPanel(Margin=Thickness(10,10,0,10))
        
        self.chkViewLinks = CheckBox(Content="View links in blue (Color prints only)", 
                                     Margin=Thickness(0,0,20,5), VerticalAlignment=VerticalAlignment.Center)
        pdf_options_panel.Children.Add(self.chkViewLinks)
        
        self.chkHideRefWorksets = CheckBox(Content="Hide ref/workspaces", 
                                           Margin=Thickness(0,0,20,5), VerticalAlignment=VerticalAlignment.Center)
        pdf_options_panel.Children.Add(self.chkHideRefWorksets)
        
        self.chkHideUnrefViewTags = CheckBox(Content="Hide unreferenced view tags", 
                                             Margin=Thickness(0,0,20,5), VerticalAlignment=VerticalAlignment.Center)
        pdf_options_panel.Children.Add(self.chkHideUnrefViewTags)
        
        self.chkHideScopeBoxes = CheckBox(Content="Hide scope boxes", 
                                          Margin=Thickness(0,0,20,5), VerticalAlignment=VerticalAlignment.Center)
        pdf_options_panel.Children.Add(self.chkHideScopeBoxes)
        
        self.chkHideCropBoundaries = CheckBox(Content="Hide crop boundaries", 
                                              Margin=Thickness(0,0,20,5), VerticalAlignment=VerticalAlignment.Center)
        pdf_options_panel.Children.Add(self.chkHideCropBoundaries)
        
        self.chkReplaceHalftone = CheckBox(Content="Replace halftone with thin lines", 
                                           Margin=Thickness(0,0,20,5), VerticalAlignment=VerticalAlignment.Center)
        pdf_options_panel.Children.Add(self.chkReplaceHalftone)
        
        self.chkRegionEdgesMask = CheckBox(Content="Region edges mask coincident lines", 
                                           Margin=Thickness(0,0,20,5), VerticalAlignment=VerticalAlignment.Center)
        pdf_options_panel.Children.Add(self.chkRegionEdgesMask)
        
        pdf_expander.Content = pdf_options_panel
        main_format_panel.Children.Add(pdf_expander)
        
        gb_format.Content = main_format_panel
        Grid.SetRow(gb_format, 0); main_layout.Children.Add(gb_format)

        # -- Naming --
        gb_name = GroupBox(Header="Naming & Destination", Padding=Thickness(10), Margin=Thickness(0,0,0,10), Foreground=Brushes.SlateGray)
        grid_n = Grid()
        grid_n.ColumnDefinitions.Add(ColumnDefinition(Width=GridLength(1.5, GridUnitType.Star)))
        grid_n.ColumnDefinitions.Add(ColumnDefinition(Width=GridLength(1, GridUnitType.Star)))
        
        sp_n_left = StackPanel(Margin=Thickness(0,0,15,0))
        sp_path = StackPanel(Orientation=Orientation.Horizontal, Margin=Thickness(0,0,0,8))
        sp_path.Children.Add(TextBlock(Text="Folder: ", Width=60, VerticalAlignment=VerticalAlignment.Center))
        self.txtPath = TextBox(Width=350, Height=28, VerticalContentAlignment=VerticalAlignment.Center)
        btn_br = Button(Content="...", Width=30, Margin=Thickness(5,0,0,0)); btn_br.Click += self._on_browse
        btn_op = Button(Content="Open", Width=45, Margin=Thickness(5,0,0,0)); btn_op.Click += self._on_open_folder
        sp_path.Children.Add(self.txtPath); sp_path.Children.Add(btn_br); sp_path.Children.Add(btn_op); sp_n_left.Children.Add(sp_path)
        
        sp_pre = StackPanel(Orientation=Orientation.Horizontal, Margin=Thickness(0,0,0,8))
        self.txtPrefix = TextBox(Width=80, Height=24, VerticalContentAlignment=VerticalAlignment.Center)
        self.txtSuffix = TextBox(Width=80, Height=24, VerticalContentAlignment=VerticalAlignment.Center)
        self.txtPrefix.TextChanged += self._on_text_change; self.txtSuffix.TextChanged += self._on_text_change
        sp_pre.Children.Add(TextBlock(Text="Prefix: ", Width=60, VerticalAlignment=VerticalAlignment.Center))
        sp_pre.Children.Add(self.txtPrefix)
        sp_pre.Children.Add(TextBlock(Text="  Suffix: ", VerticalAlignment=VerticalAlignment.Center))
        sp_pre.Children.Add(self.txtSuffix)
        sp_n_left.Children.Add(sp_pre)

        self.spSingle = StackPanel()
        sp_pat = StackPanel(Orientation=Orientation.Horizontal)
        sp_pat.Children.Add(TextBlock(Text="Pattern: ", Width=60, VerticalAlignment=VerticalAlignment.Center))
        self.txtPattern = TextBox(Width=415, Height=28, VerticalContentAlignment=VerticalAlignment.Center); self.txtPattern.TextChanged += self._on_text_change
        sp_pat.Children.Add(self.txtPattern); self.spSingle.Children.Add(sp_pat); sp_n_left.Children.Add(self.spSingle)

        self.spCombine = StackPanel(Visibility=Visibility.Collapsed)
        sp_c = StackPanel(Orientation=Orientation.Horizontal)
        sp_c.Children.Add(TextBlock(Text="Filename: ", Width=65, FontWeight=FontWeights.Bold, VerticalAlignment=VerticalAlignment.Center))
        self.txtCombineName = TextBox(Width=410, Height=28, VerticalContentAlignment=VerticalAlignment.Center)
        sp_c.Children.Add(self.txtCombineName); self.spCombine.Children.Add(sp_c); sp_n_left.Children.Add(self.spCombine)
        
        sp_opt = StackPanel(Orientation=Orientation.Horizontal, Margin=Thickness(0,8,0,0))
        self.chkAutoFolder = CheckBox(Content="Auto Create Folders", IsChecked=True, Margin=Thickness(0,0,15,0), VerticalAlignment=VerticalAlignment.Center)
        self.chkExcel = CheckBox(Content="Excel Transmittal", Foreground=Brushes.SeaGreen, FontWeight=FontWeights.Bold, VerticalAlignment=VerticalAlignment.Center)
        sp_opt.Children.Add(self.chkAutoFolder); sp_opt.Children.Add(self.chkExcel); sp_n_left.Children.Add(sp_opt)

        Grid.SetColumn(sp_n_left, 0); grid_n.Children.Add(sp_n_left)
        
        sp_p_right = StackPanel()
        self.txtPSearch = TextBox(Height=24, Margin=Thickness(0,0,0,2)); self.txtPSearch.TextChanged += self._filter_params
        self.lstP = ListBox(Height=105); sp_p_right.Children.Add(self.txtPSearch); sp_p_right.Children.Add(self.lstP)
        btn_add_p = Button(Content="+ Insert Parameter", Height=24, Margin=Thickness(0,2,0,0)); btn_add_p.Click += self._add_param
        sp_p_right.Children.Add(btn_add_p)
        Grid.SetColumn(sp_p_right, 1); grid_n.Children.Add(sp_p_right)
        
        gb_name.Content = grid_n; Grid.SetRow(gb_name, 1); main_layout.Children.Add(gb_name)

        # -- Filter Bar --
        sp_filter = StackPanel(Orientation=Orientation.Horizontal, Margin=Thickness(0,5,0,10))
        self.cboSets = ComboBox(Width=180, Height=30); self.cboSets.SelectionChanged += self._on_set_select
        sp_filter.Children.Add(self.cboSets)
        self.txtSearch = TextBox(Width=180, Height=30, Margin=Thickness(10,0,0,0), VerticalContentAlignment=VerticalAlignment.Center); self.txtSearch.TextChanged += self._filter_grid
        sp_filter.Children.Add(self.txtSearch)
        
        btn_all = Button(Content="Check All", Height=30, Margin=Thickness(20,0,0,0), Padding=Thickness(10,0,10,0)); btn_all.Click += lambda s,e: self._set_all(True)
        btn_none = Button(Content="Uncheck All", Height=30, Margin=Thickness(5,0,0,0), Padding=Thickness(10,0,10,0)); btn_none.Click += lambda s,e: self._set_all(False)
        
        btn_chk_hi = Button(Content="Check Selected", Height=30, Margin=Thickness(20,0,0,0), Background=Brushes.LightCyan, Padding=Thickness(10,0,10,0)); btn_chk_hi.Click += self._on_check_high
        btn_un_hi = Button(Content="Uncheck Selected", Height=30, Margin=Thickness(5,0,0,0), Background=Brushes.MistyRose, Padding=Thickness(10,0,10,0)); btn_un_hi.Click += self._on_uncheck_high
        
        sp_filter.Children.Add(btn_all); sp_filter.Children.Add(btn_none); sp_filter.Children.Add(btn_chk_hi); sp_filter.Children.Add(btn_un_hi)
        Grid.SetRow(sp_filter, 2); main_layout.Children.Add(sp_filter)

        # -- DataGrid --
        self.dg = DataGrid(AutoGenerateColumns=False, CanUserAddRows=False, RowHeight=28, GridLinesVisibility=0, SelectionMode=DataGridSelectionMode.Extended)
        self.dg.Columns.Add(DataGridCheckBoxColumn(Header="X", Binding=Binding("Include")))
        self.dg.Columns.Add(DataGridTextColumn(Header="Number", Binding=Binding("Number"), IsReadOnly=True))
        
        self.dg.Columns.Add(DataGridTextColumn(Header="Sheet Name", Binding=Binding("Name"), Width=DataGridLength(1, DataGridLengthUnitType.Star), IsReadOnly=True))
        self.dg.Columns.Add(DataGridTextColumn(Header="Revision", Binding=Binding("Revision"), Width=DataGridLength(100), IsReadOnly=True))
        self.dg.Columns.Add(DataGridTextColumn(Header="Preview Filename", Binding=Binding("PreviewName"), IsReadOnly=True, Width=DataGridLength(350), Foreground=Brushes.RoyalBlue))
        
        Grid.SetRow(self.dg, 3); main_layout.Children.Add(self.dg)

        # 3. FOOTER
        btn_run = Button(Content="START MULTI-EXPORT", Height=55, Background=Brushes.SeaGreen, 
                         Foreground=Brushes.White, FontWeight=FontWeights.Bold, FontSize=16)
        btn_run.Click += self._on_run
        Grid.SetRow(btn_run, 2); root_grid.Children.Add(btn_run)

    # --- LOGIC ---
    def _initial_load(self, s, e):
        self._refresh_data()
        self._load_profiles_from_disk()
        self._load_project_params_list()
        self._load_all_params()
        self._load_print_sets()
        self._load_last_settings() 
        self._update_all_previews()

    def _on_save_profile(self, s, e):
        n = self.txtProfileName.Text.strip()
        if not n: return
        self._profiles[n] = {
            'prefix': self.txtPrefix.Text, 'suffix': self.txtSuffix.Text, 'pattern': self.txtPattern.Text, 
            'path': self.txtPath.Text, 'color': self.cboColor.SelectedIndex, 
            'pdf': self.chkPDF.IsChecked, 'dwg': self.chkDWG.IsChecked, 'ifc': self.chkIFC.IsChecked, 'nwc': self.chkNWC.IsChecked,
            'combine': self.chkCombine.IsChecked, 'combine_name': self.txtCombineName.Text,
            'excel': self.chkExcel.IsChecked, 'auto_folder': self.chkAutoFolder.IsChecked,
            # PDF Advanced Options
            'view_links': self.chkViewLinks.IsChecked,
            'hide_ref_worksets': self.chkHideRefWorksets.IsChecked,
            'hide_unref_view_tags': self.chkHideUnrefViewTags.IsChecked,
            'hide_scope_boxes': self.chkHideScopeBoxes.IsChecked,
            'hide_crop_boundaries': self.chkHideCropBoundaries.IsChecked,
            'replace_halftone': self.chkReplaceHalftone.IsChecked,
            'region_edges_mask': self.chkRegionEdgesMask.IsChecked
        }
        with open(CONFIG_FILE, 'w') as f: json.dump(self._profiles, f)
        self._load_profiles_from_disk()
        self._ignore_events = True
        self.cboProfile.SelectedItem = n
        self._ignore_events = False
        self._toast("Saved Profile: " + n)

    def _on_delete_profile(self, s, e):
        n = self.cboProfile.SelectedItem
        if n in self._profiles:
            del self._profiles[n]
            with open(CONFIG_FILE, 'w') as f: json.dump(self._profiles, f)
            self._load_profiles_from_disk(); self.txtProfileName.Text = ""
            self._toast("Deleted")

    def _on_export_config(self, s, e):
        dest = forms.save_file(file_ext='json', default_name='p13_profiles_backup')
        if dest:
            with open(dest, 'w') as f: json.dump(self._profiles, f)
            self._toast("Config Exported!")

    def _on_import_config(self, s, e):
        src = forms.pick_file(file_ext='json')
        if src:
            try:
                with open(src, 'r') as f: self._profiles.update(json.load(f))
                with open(CONFIG_FILE, 'w') as f: json.dump(self._profiles, f)
                self._load_profiles_from_disk()
                self._toast("Config Imported!")
            except: self._toast("Import Error!")

    def _on_profile_select(self, s, e):
        if self._ignore_events: return
        n = self.cboProfile.SelectedItem
        if n in self._profiles:
            self._ignore_events = True
            p = self._profiles[n]
            self.txtProfileName.Text = n
            self.txtPrefix.Text = p.get('prefix', '')
            self.txtSuffix.Text = p.get('suffix', '')
            self.txtPattern.Text = p.get('pattern', '')
            self.txtPath.Text = p.get('path', '')
            self.cboColor.SelectedIndex = p.get('color', 0)
            self.chkPDF.IsChecked = p.get('pdf', True)
            self.chkDWG.IsChecked = p.get('dwg', False)
            self.chkIFC.IsChecked = p.get('ifc', False)
            self.chkNWC.IsChecked = p.get('nwc', False)
            self.chkCombine.IsChecked = p.get('combine', False)
            self.txtCombineName.Text = p.get('combine_name', 'Combined_Set')
            self.chkExcel.IsChecked = p.get('excel', False)
            self.chkAutoFolder.IsChecked = p.get('auto_folder', True)
            
            # PDF Advanced Options
            self.chkViewLinks.IsChecked = p.get('view_links', False)
            self.chkHideRefWorksets.IsChecked = p.get('hide_ref_worksets', False)
            self.chkHideUnrefViewTags.IsChecked = p.get('hide_unref_view_tags', False)
            self.chkHideScopeBoxes.IsChecked = p.get('hide_scope_boxes', False)
            self.chkHideCropBoundaries.IsChecked = p.get('hide_crop_boundaries', False)
            self.chkReplaceHalftone.IsChecked = p.get('replace_halftone', False)
            self.chkRegionEdgesMask.IsChecked = p.get('region_edges_mask', False)
            
            self._ignore_events = False
            self._toggle_ui(None, None); self._update_all_previews()

    def _save_current_as_last(self):
        try:
            data = {
                'last_profile': self.cboProfile.SelectedItem,
                'path': self.txtPath.Text, 
                'pattern': self.txtPattern.Text,
                'prefix': self.txtPrefix.Text,
                'suffix': self.txtSuffix.Text,
                'color': self.cboColor.SelectedIndex,
                'pdf': self.chkPDF.IsChecked,
                'dwg': self.chkDWG.IsChecked,
                'ifc': self.chkIFC.IsChecked,
                'nwc': self.chkNWC.IsChecked,
                'combine': self.chkCombine.IsChecked,
                'combine_name': self.txtCombineName.Text,
                'excel': self.chkExcel.IsChecked,
                'auto_folder': self.chkAutoFolder.IsChecked,
                # PDF Advanced Options
                'view_links': self.chkViewLinks.IsChecked,
                'hide_ref_worksets': self.chkHideRefWorksets.IsChecked,
                'hide_unref_view_tags': self.chkHideUnrefViewTags.IsChecked,
                'hide_scope_boxes': self.chkHideScopeBoxes.IsChecked,
                'hide_crop_boundaries': self.chkHideCropBoundaries.IsChecked,
                'replace_halftone': self.chkReplaceHalftone.IsChecked,
                'region_edges_mask': self.chkRegionEdgesMask.IsChecked
            }
            with open(LAST_SETTING_FILE, 'w') as f: json.dump(data, f)
        except: pass

    def _load_last_settings(self):
        if os.path.exists(LAST_SETTING_FILE):
            try:
                with open(LAST_SETTING_FILE, 'r') as f: d = json.load(f)
                
                self._ignore_events = True
                
                self.txtPath.Text = d.get('path', '')
                self.txtPattern.Text = d.get('pattern', '{SheetNumber}_{SheetName}')
                self.txtPrefix.Text = d.get('prefix', '')
                self.txtSuffix.Text = d.get('suffix', '')
                self.cboColor.SelectedIndex = d.get('color', 0)
                self.chkPDF.IsChecked = d.get('pdf', True)
                self.chkDWG.IsChecked = d.get('dwg', False)
                self.chkIFC.IsChecked = d.get('ifc', False)
                self.chkNWC.IsChecked = d.get('nwc', False)
                self.chkCombine.IsChecked = d.get('combine', False)
                self.txtCombineName.Text = d.get('combine_name', 'Combined_Set')
                self.chkExcel.IsChecked = d.get('excel', False)
                self.chkAutoFolder.IsChecked = d.get('auto_folder', True)
                
                # PDF Advanced Options
                self.chkViewLinks.IsChecked = d.get('view_links', False)
                self.chkHideRefWorksets.IsChecked = d.get('hide_ref_worksets', False)
                self.chkHideUnrefViewTags.IsChecked = d.get('hide_unref_view_tags', False)
                self.chkHideScopeBoxes.IsChecked = d.get('hide_scope_boxes', False)
                self.chkHideCropBoundaries.IsChecked = d.get('hide_crop_boundaries', False)
                self.chkReplaceHalftone.IsChecked = d.get('replace_halftone', False)
                self.chkRegionEdgesMask.IsChecked = d.get('region_edges_mask', False)
                
                lp = d.get('last_profile')
                if lp and lp in self._profiles:
                    self.cboProfile.SelectedItem = lp
                    self.txtProfileName.Text = lp
                    
                self._ignore_events = False
                self._toggle_ui(None, None)
            except: 
                self._ignore_events = False

    def _refresh_data(self):
        sheets = DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet).ToElements()
        self._all_items = [ExportItem(s) for s in sheets if not s.IsPlaceholder]
        self._all_items.sort(key=lambda x: x.Number)
        self.dg.ItemsSource = ObservableCollection[ExportItem](self._all_items)

    def _load_profiles_from_disk(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f: self._profiles = json.load(f)
            self.cboProfile.Items.Clear()
            for k in sorted(self._profiles.keys()): self.cboProfile.Items.Add(k)

    def _load_project_params_list(self):
        for p in ["SheetNumber", "SheetName", "Current Revision", "Drawn By", "Checked By", "Approved By"]: self.lstP.Items.Add(p)

    def _update_all_previews(self):
        if self._ignore_events: return
        pat = self.txtPattern.Text; pre = self.txtPrefix.Text; suf = self.txtSuffix.Text
        for item in self._all_items:
            fn = pre + pat + suf
            fn = fn.replace("{SheetNumber}", item.Number).replace("{SheetName}", item.Name).replace("{Current Revision}", item.Revision)
            if "{" in fn:
                for p_name in [x.strip("{}") for x in re.findall(r'\{.*?\}', fn)]:
                    val = item.get_param_val(p_name)
                    fn = fn.replace("{" + p_name + "}", val)
            item.PreviewName = self._sanitize(fn)
        self.dg.Items.Refresh()

    def _on_check_high(self, s, e):
        for i in self.dg.SelectedItems: i.Include = True
        self.dg.Items.Refresh()

    def _on_uncheck_high(self, s, e):
        for i in self.dg.SelectedItems: i.Include = False
        self.dg.Items.Refresh()

    def _toggle_ui(self, s, e):
        self.spCombine.Visibility = Visibility.Visible if self.chkCombine.IsChecked else Visibility.Collapsed
        self.spSingle.Visibility = Visibility.Collapsed if self.chkCombine.IsChecked else Visibility.Visible

    def _on_text_change(self, s, e): self._update_all_previews()

    def _on_browse(self, s, e):
        p = forms.pick_folder()
        if p: self.txtPath.Text = p

    def _on_open_folder(self, s, e):
        if os.path.exists(self.txtPath.Text): os.startfile(self.txtPath.Text)

    def _set_all(self, val):
        for i in self.dg.ItemsSource: i.Include = val
        self.dg.Items.Refresh()

    def _filter_grid(self, s, e):
        t = self.txtSearch.Text.lower()
        self.dg.ItemsSource = ObservableCollection[ExportItem]([i for i in self._all_items if t in i.Number.lower() or t in i.Name.lower()])

    def _load_print_sets(self):
        self.cboSets.Items.Add("- Sheet Set -")
        for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheetSet): self.cboSets.Items.Add(s.Name)
        self.cboSets.SelectedIndex = 0

    def _on_set_select(self, s, e):
        n = self.cboSets.SelectedItem
        if n and n != "- Sheet Set -":
            vset = next((x for x in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheetSet) if x.Name == n), None)
            if vset:
                ids = [v.Id for v in vset.Views]
                for i in self._all_items: i.Include = i.Id in ids
                self.dg.Items.Refresh()

    def _add_param(self, s, e):
        if self.lstP.SelectedItem:
            tk = "{" + self.lstP.SelectedItem + "}"
            if self.chkCombine.IsChecked: self.txtCombineName.AppendText(tk)
            else: self.txtPattern.AppendText(tk); self._update_all_previews()

    def _filter_params(self, s, e):
        t = self.txtPSearch.Text.lower()
        self.lstP.Items.Clear()
        for p in self._all_params:
            if t in p.lower(): self.lstP.Items.Add(p)

    def _load_all_params(self):
        p_names = set()
        if self._all_items:
            for p in self._all_items[0].item_obj.Parameters:
                if p.Definition: p_names.add(p.Definition.Name)
        for p in doc.ProjectInformation.Parameters:
            if p.Definition: p_names.add(p.Definition.Name)
        self._all_params = sorted(list(p_names))
        self._filter_params(None, None)

    def _toast(self, msg):
        try: output.get_output().toast(msg)
        except: pass

    def _sanitize(self, name):
        return re.sub(r'[\\/*?:"<>|]', "_", name).strip()

    def _create_excel(self, items, folder):
        try:
            csv_p = os.path.join(folder, "Transmittal_{}.csv".format(datetime.datetime.now().strftime("%Y%m%d")))
            with open(csv_p, 'w') as f:
                f.write("Number,Name,Revision,Date\n")
                for i in items: f.write("{},{},{},{}\n".format(i.Number, i.Name, i.Revision, datetime.datetime.now().date()))
        except: pass

    def _apply_pdf_options(self, opt):
        """Apply PDF advanced options to PDFExportOptions"""
        # View links in blue (Color prints only)
        try:
            if self.chkViewLinks.IsChecked:
                opt.ViewLinksInBlue = True
        except: pass
        
        # Hide reference/workspaces
        try:
            if self.chkHideRefWorksets.IsChecked:
                opt.HideReferenceWorksets = True
        except: pass
        
        # Hide unreferenced view tags
        try:
            if self.chkHideUnrefViewTags.IsChecked:
                opt.HideUnreferencedViewTags = True
        except: pass
        
        # Hide scope boxes
        try:
            if self.chkHideScopeBoxes.IsChecked:
                opt.HideScopeBoxes = True
        except: pass
        
        # Hide crop boundaries
        try:
            if self.chkHideCropBoundaries.IsChecked:
                opt.HideCropBoundaries = True
        except: pass
        
        # Replace halftone with thin lines
        try:
            if self.chkReplaceHalftone.IsChecked:
                opt.ReplaceHalftoneWithThinLines = True
        except: pass
        
        # Region edges mask coincident lines
        try:
            if self.chkRegionEdgesMask.IsChecked:
                opt.RegionEdgesMaskCoincidentLines = True
        except: pass

    def _on_run(self, s, e):
        selected = [i for i in self.dg.ItemsSource if i.Include]
        if not selected: 
            self._toast("Please select at least one sheet.")
            return

        # เปิดหน้าต่างเลือกโฟลเดอร์อัตโนมัติหากยังไม่ได้ใส่ค่า Path
        if not self.txtPath.Text:
            p = forms.pick_folder(title="Please select export destination folder")
            if p:
                self.txtPath.Text = p
            else:
                return 
        
        self._save_current_as_last()
        folder = self.txtPath.Text

        # ตรวจสอบว่ามีตำแหน่ง Drive/Folder นี้อยู่จริงหรือไม่
        if not os.path.exists(folder):
            forms.alert("ไม่พบตำแหน่งโฟลเดอร์ปลายทาง หรือไดร์ฟอาจไม่พร้อมใช้งาน:\n{}".format(folder), title="Path Not Found")
            return
        
        pdf_path = os.path.join(folder, "PDF") if self.chkAutoFolder.IsChecked else folder
        dwg_path = os.path.join(folder, "DWG") if self.chkAutoFolder.IsChecked else folder
        
        # ป้องกัน Error ตอนสร้างโฟลเดอร์
        if self.chkAutoFolder.IsChecked:
            try:
                for d in [pdf_path, dwg_path]: 
                    if not os.path.exists(d): os.makedirs(d)
            except Exception as ex:
                forms.alert("ไม่สามารถสร้างโฟลเดอร์ย่อยในตำแหน่งที่เลือกได้ กรุณาตรวจสอบสิทธิ์การเข้าถึง:\n" + str(ex), title="Folder Error")
                return

        try:
            total = len(selected) * (int(self.chkPDF.IsChecked) + int(self.chkDWG.IsChecked) + int(self.chkIFC.IsChecked) + int(self.chkNWC.IsChecked))
            if self.chkCombine.IsChecked: total += 1

            with forms.ProgressBar(title="Working...", total=total) as pb:
                c = 0
                if self.chkCombine.IsChecked and self.chkPDF.IsChecked:
                    try:
                        raw_c_name = self.txtCombineName.Text
                        if "{" in raw_c_name and selected:
                            for p_name in [x.strip("{}") for x in re.findall(r'\{.*?\}', raw_c_name)]:
                                val = selected[0].get_param_val(p_name)
                                raw_c_name = raw_c_name.replace("{" + p_name + "}", val)
                        
                        final_c_name = self._sanitize(raw_c_name)
                        
                        opt = DB.PDFExportOptions()
                        opt.Combine = True
                        opt.FileName = final_c_name
                        opt.ColorDepth = DB.ColorDepthType.BlackLine if self.cboColor.SelectedIndex == 1 else DB.ColorDepthType.Color
                        
                        # Apply PDF advanced options
                        self._apply_pdf_options(opt)
                        
                        doc.Export(pdf_path, List[DB.ElementId]([i.Id for i in selected]), opt)
                    except Exception as ex: 
                        print("Combine Error: " + str(ex))
                    c += 1
                    pb.update_progress(c, total)

                for item in selected:
                    fn = self._sanitize(item.PreviewName)
                    
                    if self.chkPDF.IsChecked and not self.chkCombine.IsChecked:
                        try:
                            opt = DB.PDFExportOptions()
                            opt.FileName = fn
                            opt.ColorDepth = DB.ColorDepthType.BlackLine if self.cboColor.SelectedIndex == 1 else DB.ColorDepthType.Color
                            
                            # Apply PDF advanced options
                            self._apply_pdf_options(opt)
                            
                            doc.Export(pdf_path, List[DB.ElementId]([item.Id]), opt)
                        except Exception as ex:
                            print("PDF Error {}: {}".format(fn, ex))
                        c += 1
                        pb.update_progress(c, total)
                    
                    if self.chkDWG.IsChecked:
                        try:
                            clean_fn = fn.replace(".dwg", "")
                            opt_dwg = DB.DWGExportOptions()
                            opt_dwg.MergedViews = True 
                            doc.Export(dwg_path, clean_fn, List[DB.ElementId]([item.Id]), opt_dwg)
                        except Exception as ex: 
                            print("DWG Error {}: {}".format(fn, ex))
                        c += 1
                        pb.update_progress(c, total)

                    if self.chkIFC.IsChecked:
                        try: 
                            doc.Export(folder, fn, DB.IFCExportOptions())
                        except Exception as ex:
                            print("IFC Error {}: {}".format(fn, ex))
                        c += 1
                        pb.update_progress(c, total)
                        
                    if self.chkNWC.IsChecked:
                        try: 
                            doc.Export(folder, fn, DB.NavisworksExportOptions())
                        except Exception as ex:
                            print("NWC Error {}: {}".format(fn, ex))
                        c += 1
                        pb.update_progress(c, total)
            
            if self.chkExcel.IsChecked: 
                self._create_excel(selected, folder)
            self.Close()
            os.startfile(folder)
            self._toast("Done!")
        except Exception as ex: 
            forms.alert("Critical Error:\n" + str(ex))
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    SuperSheetsUltimate().ShowDialog()