# -*- coding: utf-8 -*-
import sys
import os
import codecs
import csv
from re import split
from math import fabs
from random import randint
from os.path import exists, isfile, dirname
from traceback import extract_tb
from unicodedata import normalize
from unicodedata import category as unicode_category
from pyrevit.framework import Forms
from pyrevit.framework import Drawing
from pyrevit.framework import System
from pyrevit import HOST_APP, revit, DB, UI
from pyrevit.framework import List
from pyrevit.compat import get_elementid_value_func
from pyrevit.script import get_logger
from pyrevit import script as pyrevit_script
from pyrevit import forms
import clr

clr.AddReference("System.Data")
clr.AddReference("System")
from System.Data import DataTable

# Categories to exclude
CAT_EXCLUDED = (
    int(DB.BuiltInCategory.OST_RoomSeparationLines),
    int(DB.BuiltInCategory.OST_Cameras),
    int(DB.BuiltInCategory.OST_CurtainGrids),
    int(DB.BuiltInCategory.OST_Elev),
    int(DB.BuiltInCategory.OST_Grids),
    int(DB.BuiltInCategory.OST_IOSModelGroups),
    int(DB.BuiltInCategory.OST_Views),
    int(DB.BuiltInCategory.OST_SitePropertyLineSegment),
    int(DB.BuiltInCategory.OST_SectionBox),
    int(DB.BuiltInCategory.OST_ShaftOpening),
    int(DB.BuiltInCategory.OST_BeamAnalytical),
    int(DB.BuiltInCategory.OST_StructuralFramingOpening),
    int(DB.BuiltInCategory.OST_MEPSpaceSeparationLines),
    int(DB.BuiltInCategory.OST_DuctSystem),
    int(DB.BuiltInCategory.OST_Lines),
    int(DB.BuiltInCategory.OST_PipingSystem),
    int(DB.BuiltInCategory.OST_Matchline),
    int(DB.BuiltInCategory.OST_CenterLines),
    int(DB.BuiltInCategory.OST_CurtainGridsRoof),
    int(DB.BuiltInCategory.OST_SWallRectOpening),
    -2000278,
    -1,
)

logger = get_logger()

class SubscribeView(UI.IExternalEventHandler):
    def __init__(self):
        self.registered = 1

    def Execute(self, uiapp):
        try:
            if self.registered == 1:
                self.registered = 0
                uiapp.ViewActivated += self.view_changed
            else:
                self.registered = 1
                uiapp.ViewActivated -= self.view_changed
        except Exception:
            external_event_trace()

    def view_changed(self, sender, e):
        wndw = SubscribeView._wndw
        if wndw and wndw.IsOpen == 1:
            if self.registered == 0:
                new_doc = e.Document
                if new_doc:
                    if wndw:
                        try:
                            current_doc = revit.DOCS.doc
                            if not new_doc.Equals(current_doc):
                                wndw.Close()
                        except (AttributeError, RuntimeError):
                            pass
                new_view = get_active_view(e.Document)
                if new_view != 0:
                    wndw.list_box2.SelectionChanged -= wndw.list_selected_index_changed
                    wndw.crt_view = new_view
                    categ_inf_used_up = get_used_categories_parameters(
                        CAT_EXCLUDED, wndw.crt_view, new_doc
                    )
                    wndw.table_data = DataTable("Data")
                    wndw.table_data.Columns.Add("Key", System.String)
                    wndw.table_data.Columns.Add("Value", System.Object)
                    names = [x.name for x in categ_inf_used_up]
                    
                    select_category_text = wndw.get_locale_string("Spectrum.Messages.SelectCategory")
                    if not select_category_text: select_category_text = wndw.get_locale_string("ColorSplasher.Messages.SelectCategory")
                    if not select_category_text: select_category_text = "Select Category"
                    
                    wndw.table_data.Rows.Add(select_category_text, 0)
                    for key_, value_ in zip(names, categ_inf_used_up):
                        wndw.table_data.Rows.Add(key_, value_)
                    wndw._categories.ItemsSource = wndw.table_data.DefaultView
                    if wndw._categories.Items.Count > 0:
                        wndw._categories.SelectedIndex = 0
                    wndw._table_data_3 = DataTable("Data")
                    wndw._table_data_3.Columns.Add("Key", System.String)
                    wndw._table_data_3.Columns.Add("Value", System.Object)
                    wndw.list_box2.ItemsSource = wndw._table_data_3.DefaultView
                    wndw._update_placeholder_visibility()

    def GetName(self):
        return "Subscribe View Changed Event"


class ApplyColors(UI.IExternalEventHandler):
    def __init__(self):
        pass

    def Execute(self, uiapp):
        try:
            new_doc = uiapp.ActiveUIDocument.Document
            view = get_active_view(new_doc)
            if not view: return
            wndw = ApplyColors._wndw
            if not wndw: return
            
            apply_line_color = wndw._chk_line_color.IsChecked
            apply_foreground_pattern_color = wndw._chk_foreground_pattern.IsChecked
            apply_background_pattern_color = wndw._chk_background_pattern.IsChecked
            
            transparency_val = 0
            if hasattr(wndw, '_slider_transparency'):
                transparency_val = int(wndw._slider_transparency.Value)

            if (not apply_line_color and not apply_foreground_pattern_color and not apply_background_pattern_color):
                apply_foreground_pattern_color = True
            solid_fill_id = solid_fill_pattern_id()

            if wndw._categories.SelectedItem is None: return
            sel_cat_row = wndw._categories.SelectedItem
            row = wndw._get_data_row_from_item(sel_cat_row, wndw._categories.SelectedIndex)
            if row is None: return
            sel_cat = row["Value"]
            if sel_cat == 0: return

            if (wndw._list_box1.SelectedIndex == -1 or wndw._list_box1.SelectedIndex == 0):
                if wndw._list_box1.SelectedIndex == 0:
                    sel_param_row = wndw._list_box1.SelectedItem
                    if sel_param_row is not None:
                        param_row = wndw._get_data_row_from_item(sel_param_row, 0)
                        if param_row is not None and param_row["Value"] == 0:
                            return
                return
                
            sel_param_row = wndw._list_box1.SelectedItem
            param_row = wndw._get_data_row_from_item(sel_param_row, wndw._list_box1.SelectedIndex)
            if param_row is None: return
            checked_param = param_row["Value"]

            refreshed_values = get_range_values(sel_cat, checked_param, view)

            color_map = {}
            for indx in range(wndw.list_box2.Items.Count):
                try:
                    item = wndw.list_box2.Items[indx]
                    row = wndw._get_data_row_from_item(item, indx)
                    if row is None: continue
                    value_item = row["Value"]
                    color_map[value_item.value] = (value_item.n1, value_item.n2, value_item.n3)
                except Exception:
                    continue

            with revit.Transaction("Apply colors to elements"):
                get_elementid_value = get_elementid_value_func()
                version = int(HOST_APP.version)
                if get_elementid_value(sel_cat.cat.Id) in (
                    int(DB.BuiltInCategory.OST_Rooms),
                    int(DB.BuiltInCategory.OST_MEPSpaces),
                    int(DB.BuiltInCategory.OST_Areas),
                ):
                    if version > 2021:
                        if wndw.crt_view.GetColorFillSchemeId(sel_cat.cat.Id).ToString() == "-1":
                            color_schemes = DB.FilteredElementCollector(new_doc).OfClass(DB.ColorFillScheme).ToElements()
                            if len(color_schemes) > 0:
                                for sch in color_schemes:
                                    if sch.CategoryId == sel_cat.cat.Id and len(sch.GetEntries()) > 0:
                                        wndw.crt_view.SetColorFillSchemeId(sel_cat.cat.Id, sch.Id)
                                        break
                    else:
                        from System.Windows import Visibility
                        if hasattr(wndw, '_txt_block5'): wndw._txt_block5.Visibility = Visibility.Visible
                else:
                    from System.Windows import Visibility
                    if hasattr(wndw, '_txt_block5'): wndw._txt_block5.Visibility = Visibility.Collapsed

                for val_info in refreshed_values:
                    if val_info.value in color_map:
                        ogs = DB.OverrideGraphicSettings()
                        r, g, b = color_map[val_info.value]
                        base_color = DB.Color(r, g, b)
                        line_color, foreground_color, background_color = get_color_shades(
                            base_color, apply_line_color, apply_foreground_pattern_color, apply_background_pattern_color
                        )
                        
                        if transparency_val > 0:
                            ogs.SetSurfaceTransparency(transparency_val)

                        if apply_line_color:
                            ogs.SetProjectionLineColor(line_color)
                            ogs.SetCutLineColor(line_color)
                        if apply_foreground_pattern_color:
                            ogs.SetSurfaceForegroundPatternColor(foreground_color)
                            ogs.SetCutForegroundPatternColor(foreground_color)
                            if solid_fill_id is not None:
                                ogs.SetSurfaceForegroundPatternId(solid_fill_id)
                                ogs.SetCutForegroundPatternId(solid_fill_id)
                        if apply_background_pattern_color and version >= 2019:
                            ogs.SetSurfaceBackgroundPatternColor(background_color)
                            ogs.SetCutBackgroundPatternColor(background_color)
                            if solid_fill_id is not None:
                                ogs.SetSurfaceBackgroundPatternId(solid_fill_id)
                                ogs.SetCutBackgroundPatternId(solid_fill_id)
                        for idt in val_info.ele_id:
                            view.SetElementOverrides(idt, ogs)
        except Exception:
            external_event_trace()

    def GetName(self):
        return "Set colors to elements"


class ResetColors(UI.IExternalEventHandler):
    def __init__(self):
        pass

    def Execute(self, uiapp):
        try:
            new_doc = revit.DOCS.doc
            view = get_active_view(new_doc)
            if view == 0: return
            wndw = ResetColors._wndw
            if not wndw: return
            
            ogs = DB.OverrideGraphicSettings()
            collector = DB.FilteredElementCollector(new_doc, view.Id).WhereElementIsNotElementType().WhereElementIsViewIndependent().ToElementIds()
            
            if wndw._categories.SelectedItem is None:
                sel_cat = 0
            else:
                sel_cat_row = wndw._categories.SelectedItem
                if hasattr(sel_cat_row, "Row"):
                    sel_cat = sel_cat_row.Row["Value"]
                else:
                    sel_cat = wndw._categories.SelectedItem["Value"]

            if sel_cat == 0:
                task_title = wndw.get_locale_string("Spectrum.TaskDialog.Title") or wndw.get_locale_string("ColorSplasher.TaskDialog.Title") or "Spectrum"
                task_no_cat = UI.TaskDialog(task_title)
                
                main_inst = wndw.get_locale_string("Spectrum.Messages.NoCategorySelected") or wndw.get_locale_string("ColorSplasher.Messages.NoCategorySelected") or "Please select a category."
                task_no_cat.MainInstruction = main_inst
                
                wndw.Topmost = False
                task_no_cat.Show()
                wndw.Topmost = True
                return
                
            with revit.Transaction("Reset colors in elements"):
                try:
                    filter_prefix = sel_cat.name + " "
                    sel_par_row = wndw._list_box1.SelectedItem
                    if sel_par_row is not None:
                        par_row = wndw._get_data_row_from_item(sel_par_row, wndw._list_box1.SelectedIndex)
                        if par_row is not None and par_row["Value"] != 0:
                            sel_par = par_row["Value"]
                            filter_prefix = sel_cat.name + " " + sel_par.name + " - "

                    filters = view.GetFilters()
                    for filt_id in filters:
                        filt_ele = new_doc.GetElement(filt_id)
                        if filt_ele.Name.StartsWith(filter_prefix) or filt_ele.Name.StartsWith(sel_cat.name + "/"):
                            view.RemoveFilter(filt_id)
                            try: new_doc.Delete(filt_id)
                            except Exception: pass
                except Exception: pass
                for i in collector: view.SetElementOverrides(i, ogs)
        except Exception:
            external_event_trace()

    def GetName(self):
        return "Reset colors in elements"


class CreateLegend(UI.IExternalEventHandler):
    def __init__(self):
        pass

    def Execute(self, uiapp):
        try:
            new_doc = uiapp.ActiveUIDocument.Document
            wndw = CreateLegend._wndw
            if not wndw: return
            
            apply_line_color = wndw._chk_line_color.IsChecked
            apply_foreground_pattern_color = wndw._chk_foreground_pattern.IsChecked
            apply_background_pattern_color = wndw._chk_background_pattern.IsChecked
            if not apply_line_color and not apply_foreground_pattern_color and not apply_background_pattern_color:
                apply_foreground_pattern_color = True
                
            collector = DB.FilteredElementCollector(new_doc).OfClass(DB.View).ToElements()
            legends = [vw for vw in collector if vw.ViewType == DB.ViewType.Legend]

            task_title = wndw.get_locale_string("Spectrum.TaskDialog.Title") or wndw.get_locale_string("ColorSplasher.TaskDialog.Title") or "Spectrum"

            if len(legends) == 0:
                task2 = UI.TaskDialog(task_title)
                main_inst = wndw.get_locale_string("Spectrum.Messages.NoLegendView") or wndw.get_locale_string("ColorSplasher.Messages.NoLegendView") or "Please create a legend view first."
                task2.MainInstruction = main_inst
                wndw.Topmost = False
                task2.Show()
                wndw.Topmost = True
                return

            if wndw.list_box2.Items.Count == 0:
                task2 = UI.TaskDialog(task_title)
                main_inst = wndw.get_locale_string("Spectrum.Messages.NoItemsForLegend") or wndw.get_locale_string("ColorSplasher.Messages.NoItemsForLegend") or "No items to create a legend."
                task2.MainInstruction = main_inst
                wndw.Topmost = False
                task2.Show()
                wndw.Topmost = True
                return

            t = DB.Transaction(new_doc, "Create Legend")
            t.Start()

            try:
                new_id_legend = legends[0].Duplicate(DB.ViewDuplicateOption.Duplicate)
                new_legend = new_doc.GetElement(new_id_legend)
                sel_cat_row = wndw._categories.SelectedItem
                sel_par_row = wndw._list_box1.SelectedItem
                cat_row = wndw._get_data_row_from_item(sel_cat_row, wndw._categories.SelectedIndex)
                par_row = wndw._get_data_row_from_item(sel_par_row, wndw._list_box1.SelectedIndex)
                if cat_row is None or par_row is None: return
                
                sel_cat, sel_par = cat_row["Value"], par_row["Value"]
                cat_name, par_name = strip_accents(sel_cat.name), strip_accents(sel_par.name)
                
                for char_to_remove in ["{", "}", "[", "]", ":", "\\", "|", "?", "/", "<", ">", "*", ";", '"', "'", "`", "~"]:
                    cat_name = cat_name.replace(char_to_remove, "-")
                    par_name = par_name.replace(char_to_remove, "-")
                
                renamed = False
                legend_prefix = wndw.get_locale_string("Spectrum.LegendNamePrefix") or wndw.get_locale_string("ColorSplasher.LegendNamePrefix") or "Spectrum - "
                
                try:
                    new_legend.Name = legend_prefix + cat_name + " - " + par_name
                    renamed = True
                except Exception: pass
                
                if not renamed:
                    for i in range(1000):
                        try:
                            new_legend.Name = legend_prefix + cat_name + " - " + par_name + " - " + str(i)
                            break
                        except Exception:
                            if i == 999: raise Exception("Could not rename legend view")

                old_all_ele = DB.FilteredElementCollector(new_doc, legends[0].Id).ToElements()
                ele_id_type = None
                for ele in old_all_ele:
                    if ele.Id != new_legend.Id and ele.Category is not None:
                        if isinstance(ele, DB.TextNote):
                            ele_id_type = ele.GetTypeId()
                            break
                get_elementid_value = get_elementid_value_func()
                if not ele_id_type:
                    all_text_notes = DB.FilteredElementCollector(new_doc).OfClass(DB.TextNoteType).ToElements()
                    for ele in all_text_notes:
                        ele_id_type = ele.Id
                        break
                if get_elementid_value(ele_id_type) == 0:
                    raise Exception("No text note type found in the model")
                    
                filled_type = None
                filled_region_types = DB.FilteredElementCollector(new_doc).OfClass(DB.FilledRegionType).ToElements()
                for f_type in filled_region_types:
                    pattern = new_doc.GetElement(f_type.ForegroundPatternId)
                    if pattern is not None and pattern.GetFillPattern().IsSolidFill and f_type.ForegroundPatternColor.IsValid:
                        filled_type = f_type
                        break
                        
                if not filled_type and filled_region_types:
                    new_type = filled_region_types[0].Duplicate("Fill Region Custom")
                    new_pattern = DB.FillPattern("Fill Pattern Solid", DB.FillPatternTarget.Drafting, DB.FillPatternHostOrientation.ToView, float(0), float(0.00001))
                    new_ele_pat = DB.FillPatternElement.Create(new_doc, new_pattern)
                    new_type.ForegroundPatternId = new_ele_pat.Id
                    filled_type = new_type

                if filled_type is None: raise Exception("Could not find or create a fill region type")

                list_max_x, list_y, list_text_heights = [], [], []
                y_pos, spacing = 0, 0
                for index, vw_item in enumerate(wndw.list_box2.Items):
                    row = wndw._get_data_row_from_item(vw_item, index)
                    if row is None: continue
                    item = row["Value"]
                    text_line = cat_name + " / " + par_name + " - " + str(item.value)
                    new_text = DB.TextNote.Create(new_doc, new_legend.Id, DB.XYZ(0, y_pos, 0), text_line, ele_id_type)
                    new_doc.Regenerate()
                    prev_bbox = new_text.get_BoundingBox(new_legend)
                    height = prev_bbox.Max.Y - prev_bbox.Min.Y
                    spacing = height * 0.25
                    list_max_x.append(prev_bbox.Max.X)
                    list_y.append(prev_bbox.Min.Y)
                    list_text_heights.append(height)
                    y_pos = prev_bbox.Min.Y - (height + spacing)
                    
                ini_x = max(list_max_x) + spacing
                solid_fill_id = solid_fill_pattern_id() if apply_foreground_pattern_color else None
                
                for indx, y in enumerate(list_y):
                    try:
                        vw_item = wndw.list_box2.Items[indx]
                        row = wndw._get_data_row_from_item(vw_item, indx)
                        if row is None: continue
                        item = row["Value"]
                        height = list_text_heights[indx]
                        rect_width = height * 2

                        p0, p1, p2, p3 = DB.XYZ(ini_x, y, 0), DB.XYZ(ini_x, y + height, 0), DB.XYZ(ini_x + rect_width, y + height, 0), DB.XYZ(ini_x + rect_width, y, 0)
                        curve_loops = DB.CurveLoop()
                        curve_loops.Append(DB.Line.CreateBound(p0, p1))
                        curve_loops.Append(DB.Line.CreateBound(p1, p2))
                        curve_loops.Append(DB.Line.CreateBound(p2, p3))
                        curve_loops.Append(DB.Line.CreateBound(p3, p0))
                        
                        reg = DB.FilledRegion.Create(new_doc, filled_type.Id, new_legend.Id, List[DB.CurveLoop]([curve_loops]))
                        ogs = DB.OverrideGraphicSettings()
                        base_color = DB.Color(item.n1, item.n2, item.n3)
                        line_color, foreground_color, background_color = get_color_shades(base_color, apply_line_color, apply_foreground_pattern_color, apply_background_pattern_color)
                        
                        if apply_line_color:
                            ogs.SetProjectionLineColor(line_color)
                            ogs.SetCutLineColor(line_color)
                        if apply_foreground_pattern_color:
                            ogs.SetSurfaceForegroundPatternColor(foreground_color)
                            ogs.SetCutForegroundPatternColor(foreground_color)
                            if solid_fill_id: ogs.SetSurfaceForegroundPatternId(solid_fill_id)
                        elif apply_background_pattern_color:
                            ogs.SetSurfaceBackgroundPatternColor(background_color)
                            ogs.SetCutBackgroundPatternColor(background_color)
                            if solid_fill_id: ogs.SetSurfaceBackgroundPatternId(solid_fill_id)
                        new_legend.SetElementOverrides(reg.Id, ogs)
                    except Exception:
                        continue

                t.Commit()
                task2 = UI.TaskDialog(task_title)
                success_msg = wndw.get_locale_string("Spectrum.Messages.LegendCreated") or wndw.get_locale_string("ColorSplasher.Messages.LegendCreated") or "Legend created successfully: {0}"
                task2.MainInstruction = success_msg.replace("{0}", new_legend.Name)
                wndw.Topmost = False
                task2.Show()
                wndw.Topmost = True

            except Exception as e:
                if t.HasStarted() and not t.HasEnded(): t.RollBack()
                task2 = UI.TaskDialog(task_title)
                error_msg = wndw.get_locale_string("Spectrum.Messages.LegendFailed") or wndw.get_locale_string("ColorSplasher.Messages.LegendFailed") or "Failed to create legend: {0}"
                task2.MainInstruction = error_msg.replace("{0}", str(e))
                wndw.Topmost = False
                task2.Show()
                wndw.Topmost = True
        except Exception:
            external_event_trace()

    def GetName(self):
        return "Create Legend"


class CreateFilters(UI.IExternalEventHandler):
    def __init__(self):
        pass

    def Execute(self, uiapp):
        try:
            new_doc = uiapp.ActiveUIDocument.Document
            view = get_active_view(new_doc)
            if view != 0:
                wndw = CreateFilters._wndw
                if not wndw: return
                
                apply_line_color = wndw._chk_line_color.IsChecked
                apply_foreground_pattern_color = wndw._chk_foreground_pattern.IsChecked
                apply_background_pattern_color = wndw._chk_background_pattern.IsChecked
                transparency_val = 0
                if hasattr(wndw, '_slider_transparency'):
                    transparency_val = int(wndw._slider_transparency.Value)

                if not apply_line_color and not apply_foreground_pattern_color and not apply_background_pattern_color:
                    apply_foreground_pattern_color = True
                    
                with revit.Transaction("Create View Filters"):
                    sel_cat_row = wndw._categories.SelectedItem
                    sel_par_row = wndw._list_box1.SelectedItem
                    cat_row = wndw._get_data_row_from_item(sel_cat_row, wndw._categories.SelectedIndex)
                    par_row = wndw._get_data_row_from_item(sel_par_row, wndw._list_box1.SelectedIndex)
                    if cat_row is None or par_row is None: return
                    
                    sel_cat, sel_par = cat_row["Value"], par_row["Value"]
                    parameter_id = sel_par.rl_par.Id
                    param_storage_type = sel_par.rl_par.StorageType
                    categories = List[DB.ElementId]()
                    categories.Add(sel_cat.cat.Id)
                    solid_fill_id = solid_fill_pattern_id()
                    version = int(HOST_APP.version)
                    elementid_value = get_elementid_value_func()
                    
                    # --- NEW: Filter Compatibility Resolution ---
                    # ใช้ Try/Except ดักจับความแตกต่างของ Revit API (รับ 2 ค่าสำหรับ Revit รุ่นใหม่ / 1 ค่าสำหรับรุ่นเก่า)
                    try:
                        filterable_ids = DB.ParameterFilterUtilities.GetFilterableParametersInCommon(new_doc, categories)
                    except TypeError:
                        filterable_ids = DB.ParameterFilterUtilities.GetFilterableParametersInCommon(categories)
                    
                    if parameter_id not in filterable_ids:
                        resolved_id = None
                        for f_id in filterable_ids:
                            f_name = ""
                            id_val = elementid_value(f_id)
                            if id_val < 0:
                                try:
                                    bip = System.Enum.ToObject(DB.BuiltInParameter, id_val)
                                    f_name = DB.LabelUtils.GetLabelFor(bip)
                                except Exception: pass
                            else:
                                try:
                                    p_ele = new_doc.GetElement(f_id)
                                    if p_ele: f_name = p_ele.Name
                                except Exception: pass
                            
                            if f_name and strip_accents(f_name) == sel_par.name:
                                resolved_id = f_id
                                break
                        
                        if not resolved_id:
                            if "Type" in sel_par.name or "Type Name" in sel_par.name:
                                fbips = [int(DB.BuiltInParameter.ALL_MODEL_TYPE_NAME), int(DB.BuiltInParameter.ELEM_TYPE_PARAM), int(DB.BuiltInParameter.ALL_MODEL_MARK)]
                                for fbip in fbips:
                                    for f_id in filterable_ids:
                                        if elementid_value(f_id) == fbip:
                                            resolved_id = f_id
                                            break
                                    if resolved_id: break
                                    
                        if resolved_id is not None:
                            parameter_id = resolved_id
                            sample_ele = DB.FilteredElementCollector(new_doc).OfCategoryId(sel_cat.cat.Id).WhereElementIsNotElementType().FirstElement()
                            if sample_ele:
                                # ค้นหา Parameter จาก Element โดยไม่ต้องอิง GetParameter
                                test_param = None
                                for p in sample_ele.Parameters:
                                    if p.Id == parameter_id:
                                        test_param = p
                                        break
                                if not test_param:
                                    typ_ele = new_doc.GetElement(sample_ele.GetTypeId())
                                    if typ_ele:
                                        for p in typ_ele.Parameters:
                                            if p.Id == parameter_id:
                                                test_param = p
                                                break
                                if test_param:
                                    param_storage_type = test_param.StorageType

                    try:
                        filter_prefix = sel_cat.name + " " + sel_par.name + " - "
                        filters = view.GetFilters()
                        for filt_id in filters:
                            filt_ele = new_doc.GetElement(filt_id)
                            if filt_ele.Name.StartsWith(filter_prefix) or filt_ele.Name.StartsWith(sel_cat.name + "/"):
                                view.RemoveFilter(filt_id)
                                try: new_doc.Delete(filt_id)
                                except Exception: pass
                    except Exception: pass
                    
                    dict_filters = {new_doc.GetElement(f_id).Name: f_id for f_id in view.GetFilters()}
                    dict_rules = {}
                    iterator = DB.FilteredElementCollector(new_doc).OfClass(DB.ParameterFilterElement).GetElementIterator()
                    while iterator.MoveNext():
                        ele = iterator.Current
                        dict_rules[ele.Name] = ele.Id
                    
                    created_count = 0
                    error_list = []
                    
                    for i in range(wndw.list_box2.Items.Count):
                        row = wndw._get_data_row_from_item(wndw.list_box2.Items[i], i)
                        if row is None: continue
                        item = row["Value"]
                        ogs = DB.OverrideGraphicSettings()
                        base_color = DB.Color(item.n1, item.n2, item.n3)
                        line_color, foreground_color, background_color = get_color_shades(base_color, apply_line_color, apply_foreground_pattern_color, apply_background_pattern_color)
                        
                        if transparency_val > 0:
                            ogs.SetSurfaceTransparency(transparency_val)

                        if apply_line_color:
                            ogs.SetProjectionLineColor(line_color)
                            ogs.SetCutLineColor(line_color)
                        if apply_foreground_pattern_color:
                            ogs.SetSurfaceForegroundPatternColor(foreground_color)
                            ogs.SetCutForegroundPatternColor(foreground_color)
                            if solid_fill_id is not None:
                                ogs.SetSurfaceForegroundPatternId(solid_fill_id)
                                ogs.SetCutForegroundPatternId(solid_fill_id)
                        if apply_background_pattern_color and version >= 2019:
                            ogs.SetSurfaceBackgroundPatternColor(background_color)
                            ogs.SetCutBackgroundPatternColor(background_color)
                            if solid_fill_id is not None:
                                ogs.SetSurfaceBackgroundPatternId(solid_fill_id)
                                ogs.SetCutBackgroundPatternId(solid_fill_id)
                                
                        filter_name = sel_cat.name + " " + sel_par.name + " - " + str(item.value)
                        
                        for char_to_remove in ["{", "}", "[", "]", ":", "\\", "|", "?", "/", "<", ">", "*", ";", '"', "'", "`", "~"]:
                            filter_name = filter_name.replace(char_to_remove, "")
                        filter_name = filter_name[:150]
                            
                        if filter_name in dict_filters or filter_name in dict_rules:
                            if filter_name in dict_rules and filter_name not in dict_filters:
                                view.AddFilter(dict_rules[filter_name])
                                view.SetFilterOverrides(dict_rules[filter_name], ogs)
                            else:
                                view.SetFilterOverrides(dict_filters[filter_name], ogs)
                            created_count += 1
                        else:
                            equals_rule = None
                            try:
                                if param_storage_type == DB.StorageType.Double:
                                    if item.value == "None" or len(item.values_double) == 0:
                                        try:
                                            equals_rule = DB.ParameterFilterRuleFactory.CreateHasNoValueParameterRule(parameter_id)
                                        except Exception: pass
                                    else:
                                        minimo = min(item.values_double)
                                        maximo = max(item.values_double)
                                        avg_values = (maximo + minimo) / 2.0
                                        try:
                                            equals_rule = DB.ParameterFilterRuleFactory.CreateEqualsRule(parameter_id, avg_values, fabs(avg_values - minimo) + 0.001)
                                        except TypeError:
                                            equals_rule = DB.ParameterFilterRuleFactory.CreateEqualsRule(parameter_id, avg_values)
                                elif param_storage_type == DB.StorageType.ElementId:
                                    if item.value == "None":
                                        prevalue = DB.ElementId.InvalidElementId
                                    else:
                                        try: prevalue = item.par.AsElementId()
                                        except Exception: continue
                                    equals_rule = DB.ParameterFilterRuleFactory.CreateEqualsRule(parameter_id, prevalue)
                                elif param_storage_type == DB.StorageType.Integer:
                                    if item.value == "None":
                                        prevalue = 0
                                    else:
                                        try: prevalue = item.par.AsInteger()
                                        except Exception: continue
                                    equals_rule = DB.ParameterFilterRuleFactory.CreateEqualsRule(parameter_id, prevalue)
                                elif param_storage_type == DB.StorageType.String:
                                    prevalue = "" if item.value == "None" else str(item.value)
                                    try:
                                        equals_rule = DB.ParameterFilterRuleFactory.CreateEqualsRule(parameter_id, prevalue, True)
                                    except TypeError:
                                        equals_rule = DB.ParameterFilterRuleFactory.CreateEqualsRule(parameter_id, prevalue)
                                        
                                if equals_rule is not None:
                                    elem_filter = DB.ElementParameterFilter(equals_rule)
                                    fltr = DB.ParameterFilterElement.Create(new_doc, filter_name, categories, elem_filter)
                                    view.AddFilter(fltr.Id)
                                    view.SetFilterOverrides(fltr.Id, ogs)
                                    dict_rules[filter_name] = fltr.Id
                                    dict_filters[filter_name] = fltr.Id
                                    created_count += 1
                                else:
                                    error_list.append("Invalid value format for rule: " + filter_name)
                            except Exception as rule_err:
                                error_list.append("{}: {}".format(filter_name, str(rule_err)))
                                continue 
                                
                    if created_count > 0:
                        msg = "Successfully processed {} View Filters.".format(created_count)
                        if error_list:
                            msg += "\n\nNote: Some rules failed ({}):\n".format(len(error_list)) + "\n".join(set(error_list))[:500]
                        task_title = wndw.get_locale_string("Spectrum.TaskDialog.Title") or wndw.get_locale_string("ColorSplasher.TaskDialog.Title") or "Spectrum"
                        task = UI.TaskDialog(task_title)
                        task.MainInstruction = msg
                        wndw.Topmost = False
                        task.Show()
                        wndw.Topmost = True
                    elif error_list:
                        task_title = wndw.get_locale_string("Spectrum.TaskDialog.Title") or wndw.get_locale_string("ColorSplasher.TaskDialog.Title") or "Spectrum"
                        task = UI.TaskDialog(task_title)
                        task.MainInstruction = "Failed to create filters. Check compatibility of parameter."
                        task.MainContent = "\n".join(set(error_list))[:1000]
                        wndw.Topmost = False
                        task.Show()
                        wndw.Topmost = True

        except Exception as ex:
            external_event_trace()
            if getattr(CreateFilters, "_wndw", None):
                CreateFilters._wndw.Topmost = False
                UI.TaskDialog.Show("Filter Creation Error", str(ex))
                CreateFilters._wndw.Topmost = True

    def GetName(self):
        return "Create Filters"


class ValuesInfo:
    def __init__(self, para, val, idt, num1, num2, num3):
        self.par = para
        self.value = val
        self.name = strip_accents(para.Definition.Name)
        self.ele_id = List[DB.ElementId]()
        self.ele_id.Add(idt)
        self.n1, self.n2, self.n3 = num1, num2, num3
        self.colour = Drawing.Color.FromArgb(self.n1, self.n2, self.n3)
        self.values_double = []
        if para.StorageType == DB.StorageType.Double:
            self.values_double.append(para.AsDouble())
        elif para.StorageType == DB.StorageType.ElementId:
            self.values_double.append(para.AsElementId())


class ParameterInfo:
    def __init__(self, param_type, para):
        self.param_type = param_type
        self.rl_par = para
        self.par = para.Definition
        self.name = strip_accents(para.Definition.Name)


class CategoryInfo:
    def __init__(self, category, param):
        self.name = strip_accents(category.Name)
        self.cat = category
        self.int_id = get_elementid_value_func()(category.Id)
        self.par = param


class SpectrumWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name, categories, ext_ev, uns_ev, s_view, reset_event, ev_legend, ev_filters):
        forms.WPFWindow.__init__(self, xaml_file_name)
        self.IsOpen = 1
        self.filter_ev, self.legend_ev, self.reset_ev = ev_filters, ev_legend, reset_event
        self.crt_view, self.event, self.uns_event = s_view, ext_ev, uns_ev
        self.uns_event.Raise()
        self.categs = categories
        self.table_data = DataTable("Data")
        self.table_data.Columns.Add("Key", System.String)
        self.table_data.Columns.Add("Value", System.Object)
        names = [x.name for x in self.categs]
        
        select_category_text = self.get_locale_string("Spectrum.Messages.SelectCategory") or self.get_locale_string("ColorSplasher.Messages.SelectCategory") or "Select Category"
        
        self.table_data.Rows.Add(select_category_text, 0)
        for key_, value_ in zip(names, self.categs): self.table_data.Rows.Add(key_, value_)
        
        self.out = []
        self._filtered_parameters, self._all_parameters = [], []
        self._config = pyrevit_script.get_config()

        self._table_data_3 = DataTable("Data")
        self._table_data_3.Columns.Add("Key", System.String)
        self._table_data_3.Columns.Add("Value", System.Object)

        self.Closed += self.closed
        pyrevit_script.restore_window_position(self)
        self._setup_ui()

    def closed(self, sender, args):
        pyrevit_script.save_window_position(self)

    def _get_data_row_from_item(self, item, item_index=None):
        from System.Data import DataRowView
        if isinstance(item, DataRowView) or hasattr(item, "Row"):
            return item.Row
        elif item_index is not None and hasattr(self, "_table_data_3") and self._table_data_3:
            if item_index < self._table_data_3.Rows.Count:
                return self._table_data_3.Rows[item_index]
        return None

    def _update_placeholder_visibility(self):
        from System.Windows import Visibility
        if self.list_box2.ItemsSource is None or self.list_box2.Items.Count == 0:
            self._txt_placeholder_values.Visibility = Visibility.Visible
        else:
            self._txt_placeholder_values.Visibility = Visibility.Collapsed

    def _setup_ui(self):
        from System.Windows.Media import Brushes
        placeholder_text = self.get_locale_string("Spectrum.Placeholders.SearchParameters") or self.get_locale_string("ColorSplasher.Placeholders.SearchParameters") or "Search Parameters..."
        self._search_box.Text = placeholder_text
        self._search_box.Foreground = Brushes.Gray

        self._categories.ItemsSource = self.table_data.DefaultView
        self._categories.SelectionChanged += self.update_filter
        self._categories.SelectedIndex = 0

        self._chk_line_color.IsChecked = self._config.get_option("Spectrum_ApplyLineColor", False)
        self._chk_foreground_pattern.IsChecked = self._config.get_option("Spectrum_ApplyForegroundPattern", True)
        
        saved_transparency = self._config.get_option("Spectrum_Transparency", 0)
        if hasattr(self, '_slider_transparency'):
            self._slider_transparency.Value = saved_transparency
        if hasattr(self, '_txt_transparency_val'):
            self._txt_transparency_val.Text = "{}%".format(saved_transparency)

        if HOST_APP.is_newer_than(2019, or_equal=True):
            self._chk_background_pattern.IsChecked = self._config.get_option("Spectrum_ApplyBackgroundPattern", False)
            self._chk_background_pattern.IsEnabled = True
        else:
            self._chk_background_pattern.IsChecked = False
            self._chk_background_pattern.IsEnabled = False

        self.list_box2.SelectionChanged += self.list_selected_index_changed
        self.list_box2.MouseDown += self.list_box2_mouse_down
        self._shift_pressed_on_click = False
        self.list_box2.ItemsSource = self._table_data_3.DefaultView
        self._update_placeholder_visibility()

        if getattr(self, "_table_data_2", None) is None:
            self._table_data_2 = DataTable("Data")
            self._table_data_2.Columns.Add("Key", System.String)
            self._table_data_2.Columns.Add("Value", System.Object)
            
            select_parameter_text = self.get_locale_string("Spectrum.Messages.SelectParameter") or self.get_locale_string("ColorSplasher.Messages.SelectParameter") or "Select Parameter"
            
            self._table_data_2.Rows.Add(select_parameter_text, 0)
            self._list_box1.ItemsSource = self._table_data_2.DefaultView
            self._list_box1.SelectedIndex = 0

        try:
            from System.Windows.Controls import ScrollViewer
            ScrollViewer.SetHorizontalScrollBarVisibility(self.list_box2, System.Windows.Controls.ScrollBarVisibility.Auto)
        except Exception: pass

        self.Closing += self.closing_event

    def search_box_enter(self, sender, e):
        try:
            from System.Windows.Media import Brushes
            placeholder_text = self.get_locale_string("Spectrum.Placeholders.SearchParameters") or self.get_locale_string("ColorSplasher.Placeholders.SearchParameters") or "Search Parameters..."
            
            if self._search_box.Text == placeholder_text:
                self._search_box.Text = ""
                self._search_box.Foreground = Brushes.Black
        except Exception: pass

    def search_box_leave(self, sender, e):
        try:
            from System.Windows.Media import Brushes
            placeholder_text = self.get_locale_string("Spectrum.Placeholders.SearchParameters") or self.get_locale_string("ColorSplasher.Placeholders.SearchParameters") or "Search Parameters..."
            
            if self._search_box.Text == "":
                self._search_box.Text = placeholder_text
                self._search_box.Foreground = Brushes.Gray
        except Exception: pass

    def on_search_text_changed(self, sender, e):
        try:
            placeholder_text = self.get_locale_string("Spectrum.Placeholders.SearchParameters") or self.get_locale_string("ColorSplasher.Placeholders.SearchParameters") or "Search Parameters..."
            
            if self._search_box.Text == placeholder_text:
                return
                
            search_text = self._search_box.Text.lower()

            filtered_table = DataTable("Data")
            filtered_table.Columns.Add("Key", System.String)
            filtered_table.Columns.Add("Value", System.Object)

            select_parameter_text = self.get_locale_string("Spectrum.Messages.SelectParameter") or self.get_locale_string("ColorSplasher.Messages.SelectParameter") or "Select Parameter"
            
            filtered_table.Rows.Add(select_parameter_text, 0)

            if len(self._all_parameters) > 0:
                for key_, value_ in self._all_parameters:
                    if search_text == "" or search_text in key_.lower():
                        filtered_table.Rows.Add(key_, value_)

            selected_item_value = None
            if self._list_box1.SelectedIndex > 0 and self._list_box1.SelectedIndex < self._list_box1.Items.Count:
                sel_item = self._list_box1.SelectedItem
                row = self._get_data_row_from_item(sel_item, self._list_box1.SelectedIndex)
                if row is not None:
                    selected_item_value = row["Value"]

            self._list_box1.ItemsSource = filtered_table.DefaultView

            if selected_item_value is not None:
                for indx in range(self._list_box1.Items.Count):
                    item = self._list_box1.Items[indx]
                    row = self._get_data_row_from_item(item, indx)
                    if row is not None:
                        item_value = row["Value"]
                        if item_value == selected_item_value:
                            self._list_box1.SelectedIndex = indx
                            break
        except Exception:
            external_event_trace()

    def checkbox_changed(self, sender, e):
        self._config.set_option("Spectrum_ApplyLineColor", self._chk_line_color.IsChecked)
        self._config.set_option("Spectrum_ApplyForegroundPattern", self._chk_foreground_pattern.IsChecked)
        if HOST_APP.is_newer_than(2019, or_equal=True):
            self._config.set_option("Spectrum_ApplyBackgroundPattern", self._chk_background_pattern.IsChecked)
        pyrevit_script.save_config()

    def slider_transparency_changed(self, sender, e):
        val = int(sender.Value)
        if hasattr(self, '_txt_transparency_val'):
            self._txt_transparency_val.Text = "{}%".format(val)
        self._config.set_option("Spectrum_Transparency", val)
        pyrevit_script.save_config()

    def button_click_set_colors(self, sender, e):
        if self.list_box2.Items.Count > 0: self.event.Raise()

    def button_click_reset(self, sender, e):
        self.reset_ev.Raise()
        
    def button_click_select_all(self, sender, e):
        try:
            if self.list_box2.Items.Count <= 0: return
            uidoc = HOST_APP.uiapp.ActiveUIDocument or __revit__.ActiveUIDocument
            all_element_ids = List[DB.ElementId]()
            for i in range(self.list_box2.Items.Count):
                row = self._get_data_row_from_item(self.list_box2.Items[i], i)
                if row is None: continue
                value_item = row["Value"]
                if hasattr(value_item, "ele_id") and value_item.ele_id:
                    for ele_id in value_item.ele_id: all_element_ids.Add(ele_id)
            if all_element_ids.Count > 0:
                uidoc.Selection.SetElementIds(all_element_ids)
                uidoc.RefreshActiveView()
        except Exception: pass

    def button_click_select_none(self, sender, e):
        try:
            uidoc = HOST_APP.uiapp.ActiveUIDocument or __revit__.ActiveUIDocument
            uidoc.Selection.SetElementIds(List[DB.ElementId]())
            uidoc.RefreshActiveView()
        except Exception: pass

    def button_click_apply_theme(self, sender, e):
        if not hasattr(self, '_combo_themes'): return
        theme = self._combo_themes.Text
        number_items = self.list_box2.Items.Count
        if number_items <= 0: return
        
        self.list_box2.SelectionChanged -= self.list_selected_index_changed
        try:
            for indx in range(number_items):
                item = self.list_box2.Items[indx]
                row = self._get_data_row_from_item(item, indx)
                if row is None: continue
                value = row["Value"]
                
                if theme == "Pastel Theme":
                    r, g, b = int((randint(0, 255) + 255) / 2), int((randint(0, 255) + 255) / 2), int((randint(0, 255) + 255) / 2)
                elif theme == "Vibrant Theme":
                    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255), (255, 128, 0)]
                    r, g, b = colors[indx % len(colors)]
                elif theme == "Dark Theme":
                    r, g, b = randint(0, 80), randint(0, 80), randint(0, 80)
                else: 
                    r, g, b = randint(100, 180), randint(80, 140), randint(40, 100)
                
                value.n1, value.n2, value.n3 = r, g, b
                value.colour = Drawing.Color.FromArgb(r, g, b)

            self.list_box2.ItemsSource = None
            self.list_box2.ItemsSource = self._table_data_3.DefaultView
            self._update_listbox_colors_async()
        except Exception: pass
        finally:
            self.list_box2.SelectionChanged += self.list_selected_index_changed

    def button_click_random_colors(self, sender, e):
        try:
            if self._list_box1.SelectedIndex != -1:
                sel_index = self._list_box1.SelectedIndex
                self._list_box1.SelectedIndex = -1
                self._list_box1.SelectedIndex = sel_index
        except Exception: pass

    def button_click_gradient_colors(self, sender, e):
        self.list_box2.SelectionChanged -= self.list_selected_index_changed
        try:
            number_items = self.list_box2.Items.Count
            if number_items <= 2: return
            
            row_start = self._get_data_row_from_item(self.list_box2.Items[0], 0)
            row_end = self._get_data_row_from_item(self.list_box2.Items[number_items - 1], number_items - 1)
            if row_start is None or row_end is None: return
            
            start_color = row_start["Value"].colour
            end_color = row_end["Value"].colour
            list_colors = self.get_gradient_colors(start_color, end_color, number_items)
            
            for indx in range(number_items):
                row = self._get_data_row_from_item(self.list_box2.Items[indx], indx)
                if row is None: continue
                value = row["Value"]
                value.n1, value.n2, value.n3 = abs(list_colors[indx][1]), abs(list_colors[indx][2]), abs(list_colors[indx][3])
                value.colour = Drawing.Color.FromArgb(value.n1, value.n2, value.n3)

            self.list_box2.ItemsSource = None
            self.list_box2.ItemsSource = self._table_data_3.DefaultView
            self._update_listbox_colors_async()
        except Exception: pass
        finally:
            self.list_box2.SelectionChanged += self.list_selected_index_changed

    def button_click_create_legend(self, sender, e):
        if self.list_box2.Items.Count > 0: self.legend_ev.Raise()

    def button_click_create_view_filters(self, sender, e):
        if self.list_box2.Items.Count > 0:
            self.filter_ev.Raise()

    def save_load_color_scheme(self, sender, e):
        saveform = FormSaveLoadScheme()
        saveform.Show()

    def get_gradient_colors(self, start_color, end_color, steps):
        a_step, r_step, g_step, b_step = float((end_color.A - start_color.A)/steps), float((end_color.R - start_color.R)/steps), float((end_color.G - start_color.G)/steps), float((end_color.B - start_color.B)/steps)
        color_list = []
        for i in range(steps):
            color_list.append([max(start_color.A + int(a_step * i) - 1, 0), max(start_color.R + int(r_step * i) - 1, 0), max(start_color.G + int(g_step * i) - 1, 0), max(start_color.B + int(b_step * i) - 1, 0)])
        return color_list

    def closing_event(self, sender, e):
        self.IsOpen = 0
        self.uns_event.Raise()

    def list_box2_mouse_down(self, sender, e):
        from System.Windows.Input import ModifierKeys, Keyboard, Key
        from System.Windows.Media import VisualTreeHelper
        from System.Windows.Controls import ListBoxItem

        hit_on_item = False
        try:
            pos = e.GetPosition(self.list_box2)
            element = VisualTreeHelper.HitTest(self.list_box2, pos).VisualHit
            while element:
                if isinstance(element, ListBoxItem):
                    hit_on_item = True
                    break
                element = VisualTreeHelper.GetParent(element)
        except Exception: pass

        if not hit_on_item:
            self._shift_pressed_on_click = False
            e.Handled = True
            return
        self._shift_pressed_on_click = ((e.KeyboardDevice.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift) or Keyboard.IsKeyDown(Key.LeftShift) or Keyboard.IsKeyDown(Key.RightShift)

    def list_selected_index_changed(self, sender, e):
        if sender.SelectedIndex == -1 or sender.SelectedItem is None:
            self._shift_pressed_on_click = False
            return

        from System.Windows.Input import Keyboard, Key
        shift_pressed = Keyboard.IsKeyDown(Key.LeftShift) or Keyboard.IsKeyDown(Key.RightShift) or getattr(self, "_shift_pressed_on_click", False)

        if shift_pressed:
            try:
                row = self._get_data_row_from_item(sender.SelectedItem, sender.SelectedIndex)
                if row and hasattr(row["Value"], "ele_id"):
                    uidoc = HOST_APP.uiapp.ActiveUIDocument or __revit__.ActiveUIDocument
                    uidoc.Selection.SetElementIds(row["Value"].ele_id)
                    uidoc.RefreshActiveView()
            except Exception: pass
            finally:
                try: self.list_box2.SelectionChanged -= self.list_selected_index_changed
                except Exception: pass
                sender.SelectedIndex = -1
                self.list_box2.SelectionChanged += self.list_selected_index_changed
                self._shift_pressed_on_click = False
        else:
            clr_dlg = Forms.ColorDialog()
            clr_dlg.AllowFullOpen = True
            if clr_dlg.ShowDialog() == Forms.DialogResult.OK:
                row = self._get_data_row_from_item(sender.SelectedItem, sender.SelectedIndex)
                if row:
                    value_item = row["Value"]
                    value_item.n1, value_item.n2, value_item.n3 = clr_dlg.Color.R, clr_dlg.Color.G, clr_dlg.Color.B
                    value_item.colour = Drawing.Color.FromArgb(clr_dlg.Color.R, clr_dlg.Color.G, clr_dlg.Color.B)
                    self._update_listbox_colors()
            try: self.list_box2.SelectionChanged -= self.list_selected_index_changed
            except Exception: pass
            sender.SelectedIndex = -1
            self.list_box2.SelectionChanged += self.list_selected_index_changed
            self._shift_pressed_on_click = False

    def _update_listbox_colors_async(self):
        from System.Windows.Threading import DispatcherTimer, DispatcherPriority
        timer = DispatcherTimer(DispatcherPriority.Loaded)
        timer.Interval = System.TimeSpan.FromMilliseconds(100)
        def update_colors(s, ev):
            self._update_listbox_colors()
            timer.Stop()
        timer.Tick += update_colors
        timer.Start()

    def _update_listbox_colors(self):
        from System.Windows.Media import SolidColorBrush, Color
        if getattr(self, "_table_data_3", None) is None: return
        for i in range(self.list_box2.Items.Count):
            try:
                row = self._get_data_row_from_item(self.list_box2.Items[i], i)
                if not row or not hasattr(row["Value"], "colour"): continue
                color_obj = row["Value"].colour
                brush = SolidColorBrush(Color.FromArgb(color_obj.A, color_obj.R, color_obj.G, color_obj.B))
                listbox_item = self.list_box2.ItemContainerGenerator.ContainerFromIndex(i)
                if listbox_item:
                    listbox_item.Background = brush
                    brightness = (color_obj.R * 299 + color_obj.G * 587 + color_obj.B * 114) / 1000
                    listbox_item.Foreground = SolidColorBrush(Color.FromRgb(0,0,0) if brightness > 128 else Color.FromRgb(255,255,255))
            except Exception: continue

    def check_item(self, sender, e):
        try:
            try: self.list_box2.SelectionChanged -= self.list_selected_index_changed
            except Exception: pass

            if self._categories.SelectedItem is None: return
            row_cat = self._get_data_row_from_item(self._categories.SelectedItem, self._categories.SelectedIndex)
            if row_cat is None: return
            sel_cat = row_cat["Value"]

            if sel_cat is None or sel_cat == 0 or sender.SelectedIndex <= 0:
                self._table_data_3 = DataTable("Data")
                self._table_data_3.Columns.Add("Key", System.String)
                self._table_data_3.Columns.Add("Value", System.Object)
                self.list_box2.ItemsSource = self._table_data_3.DefaultView
                self._update_placeholder_visibility()
                return

            row = self._get_data_row_from_item(sender.SelectedItem, sender.SelectedIndex)
            if row is None: return
            sel_param = row["Value"]

            self._table_data_3 = DataTable("Data")
            self._table_data_3.Columns.Add("Key", System.String)
            self._table_data_3.Columns.Add("Value", System.Object)

            rng_val = get_range_values(sel_cat, sel_param, self.crt_view)
            for val in rng_val: self._table_data_3.Rows.Add(val.value, val)

            self.list_box2.ItemsSource = self._table_data_3.DefaultView
            self.list_box2.SelectedIndex = -1
            self._update_placeholder_visibility()
            self.list_box2.UpdateLayout()
            self.list_box2.SelectionChanged += self.list_selected_index_changed
            self._update_listbox_colors_async()
        except Exception:
            external_event_trace()

    def update_filter(self, sender, e):
        try:
            if sender.SelectedItem is None: return
            
            row = self._get_data_row_from_item(sender.SelectedItem, sender.SelectedIndex)
            if row is None: return
            sel_cat = row["Value"]

            self._table_data_2 = DataTable("Data")
            self._table_data_2.Columns.Add("Key", System.String)
            self._table_data_2.Columns.Add("Value", System.Object)
            self._table_data_3 = DataTable("Data")
            self._table_data_3.Columns.Add("Key", System.String)
            self._table_data_3.Columns.Add("Value", System.Object)

            select_parameter_text = self.get_locale_string("Spectrum.Messages.SelectParameter") or self.get_locale_string("ColorSplasher.Messages.SelectParameter") or "Select Parameter"
            
            self._table_data_2.Rows.Add(select_parameter_text, 0)

            if sel_cat != 0 and sender.SelectedIndex != 0:
                names_par = [x.name for x in sel_cat.par]
                for key_, value_ in zip(names_par, sel_cat.par):
                    self._table_data_2.Rows.Add(key_, value_)
                self._all_parameters = [(key_, value_) for key_, value_ in zip(names_par, sel_cat.par)]
                
                self._list_box1.ItemsSource = self._table_data_2.DefaultView
                self._list_box1.SelectedIndex = 0
                
                from System.Windows.Media import Brushes
                placeholder_text = self.get_locale_string("Spectrum.Placeholders.SearchParameters") or self.get_locale_string("ColorSplasher.Placeholders.SearchParameters") or "Search Parameters..."
                
                self._search_box.Text = placeholder_text
                self._search_box.Foreground = Brushes.Gray
                self.list_box2.ItemsSource = self._table_data_3.DefaultView
                self._update_placeholder_visibility()
            else:
                self._all_parameters = []
                self._list_box1.ItemsSource = self._table_data_2.DefaultView
                self._list_box1.SelectedIndex = 0
                self.list_box2.ItemsSource = self._table_data_3.DefaultView
                self._update_placeholder_visibility()
        except Exception:
            external_event_trace()


class FormSaveLoadScheme(Forms.Form):
    def __init__(self):
        self.Font = Drawing.Font(self.Font.FontFamily, 9, Drawing.FontStyle.Regular, Drawing.GraphicsUnit.Pixel)
        self.TopMost = True
        self.InitializeComponent()

    def InitializeComponent(self):
        self._btn_save = Forms.Button()
        self._btn_load = Forms.Button()
        self._txt_ifloading = Forms.Label()
        self._radio_by_value = Forms.RadioButton()
        self._radio_by_pos = Forms.RadioButton()
        self.tooltip1 = Forms.ToolTip()
        self._spr_top = Forms.Label()
        self.SuspendLayout()
        
        self._spr_top.Anchor = Forms.AnchorStyles.Top | Forms.AnchorStyles.Left | Forms.AnchorStyles.Right
        self._spr_top.Location = Drawing.Point(0, 0)
        self._spr_top.Size = Drawing.Size(500, 2)
        self._spr_top.BackColor = Drawing.Color.FromArgb(82, 53, 239)
        
        self._txt_ifloading.Location = Drawing.Point(12, 10)
        self._txt_ifloading.Text = "If Loading a Color Scheme:"
        self._txt_ifloading.Size = Drawing.Size(239, 23)
        
        self._radio_by_value.Location = Drawing.Point(19, 35)
        self._radio_by_value.Text = "Load by Parameter Value."
        self._radio_by_value.Size = Drawing.Size(230, 25)
        self._radio_by_value.Checked = True
        
        self._radio_by_pos.Location = Drawing.Point(250, 35)
        self._radio_by_pos.Text = "Load by Position in Window."
        self._radio_by_pos.Size = Drawing.Size(239, 25)
        
        self._btn_save.Location = Drawing.Point(13, 70)
        self._btn_save.Size = Drawing.Size(236, 25)
        self._btn_save.Text = "Save Color Scheme"
        self._btn_save.Cursor = Forms.Cursors.Hand
        self._btn_save.Click += self.specify_path_save
        
        self._btn_load.Location = Drawing.Point(253, 70)
        self._btn_load.Size = Drawing.Size(236, 25)
        self._btn_load.Text = "Load Color Scheme"
        self._btn_load.Cursor = Forms.Cursors.Hand
        self._btn_load.Click += self.specify_path_load
        
        self.Controls.Add(self._txt_ifloading)
        self.Controls.Add(self._radio_by_value)
        self.Controls.Add(self._radio_by_pos)
        self.Controls.Add(self._btn_save)
        self.Controls.Add(self._btn_load)
        self.Controls.Add(self._spr_top)
        self.ClientSize = Drawing.Size(500, 105)
        self.Text = "Save / Load Color Scheme"
        self.FormBorderStyle = Forms.FormBorderStyle.FixedSingle
        self.CenterToScreen()
        self.ResumeLayout(False)

    def specify_path_save(self, sender, e):
        config = pyrevit_script.get_config()
        export_path = config.get_option("Spectrum_ExportPath", "")

        with Forms.SaveFileDialog() as sfd:
            wndw = getattr(SpectrumWindow, "_current_wndw", None)
            
            title_text = "Save Scheme"
            if wndw:
                title_temp = wndw.get_locale_string("Spectrum.SaveLoadDialog.SaveTitle")
                if not title_temp: title_temp = wndw.get_locale_string("ColorSplasher.SaveLoadDialog.SaveTitle")
                if title_temp: title_text = title_temp
                
            sfd.Title = title_text
            sfd.Filter = "Color Scheme (*.cschn)|*.cschn|CSV File (*.csv)|*.csv"
            sfd.RestoreDirectory = True
            sfd.OverwritePrompt = True
            sfd.FileName = "Color Scheme.cschn"
            sfd.InitialDirectory = export_path if export_path and exists(export_path) else System.Environment.GetFolderPath(System.Environment.SpecialFolder.Desktop)

            if not wndw or wndw.list_box2.Items.Count == 0:
                self.Close()
                UI.TaskDialog.Show("No Colors Detected", "The list of values in the main window is empty.")
            elif sfd.ShowDialog() == Forms.DialogResult.OK:
                config.set_option("Spectrum_ExportPath", dirname(sfd.FileName))
                pyrevit_script.save_config()
                self.save_path_to_file(sfd.FileName)
                self.Close()

    def save_path_to_file(self, new_path):
        wndw = getattr(SpectrumWindow, "_current_wndw", None)
        if not wndw: return
        is_csv = new_path.lower().endswith('.csv')
        
        cat_name = ""
        par_name = ""
        if wndw._categories.SelectedIndex > 0:
            row = wndw._get_data_row_from_item(wndw._categories.SelectedItem, wndw._categories.SelectedIndex)
            if row: cat_name = row["Key"]
        if wndw._list_box1.SelectedIndex > 0:
            row = wndw._get_data_row_from_item(wndw._list_box1.SelectedItem, wndw._list_box1.SelectedIndex)
            if row: par_name = row["Key"]

        try:
            if is_csv:
                with open(new_path, "wb") as f:
                    writer = csv.writer(f, lineterminator='\n')
                    writer.writerow(["Category", "Parameter", "Value", "R", "G", "B"])
                    for i in range(wndw.list_box2.Items.Count):
                        row = wndw._get_data_row_from_item(wndw.list_box2.Items[i], i)
                        if row is None: continue
                        c = row["Value"].colour
                        
                        k = row["Key"]
                        cat_name_str = cat_name.encode('utf-8') if hasattr(cat_name, 'encode') else str(cat_name)
                        par_name_str = par_name.encode('utf-8') if hasattr(par_name, 'encode') else str(par_name)
                        k_str = k.encode('utf-8') if hasattr(k, 'encode') else str(k)
                        
                        writer.writerow([cat_name_str, par_name_str, k_str, c.R, c.G, c.B])
            else:
                with codecs.open(new_path, "w", encoding='utf-8') as f:
                    f.write(u"#Category::{}\n".format(cat_name))
                    f.write(u"#Parameter::{}\n".format(par_name))
                    for i in range(wndw.list_box2.Items.Count):
                        row = wndw._get_data_row_from_item(wndw.list_box2.Items[i], i)
                        if row is None: continue
                        c = row["Value"].colour
                        f.write(u"{}::R{}G{}B{}\n".format(row["Key"], c.R, c.G, c.B))
        except Exception as ex:
            UI.TaskDialog.Show("Error", str(ex))

    def specify_path_load(self, sender, e):
        config = pyrevit_script.get_config()
        export_path = config.get_option("Spectrum_ExportPath", "")

        with Forms.OpenFileDialog() as ofd:
            wndw = getattr(SpectrumWindow, "_current_wndw", None)
            
            title_text = "Load Scheme"
            if wndw:
                title_temp = wndw.get_locale_string("Spectrum.SaveLoadDialog.LoadTitle")
                if not title_temp: title_temp = wndw.get_locale_string("ColorSplasher.SaveLoadDialog.LoadTitle")
                if title_temp: title_text = title_temp
                
            ofd.Title = title_text
            ofd.Filter = "Color Scheme (*.cschn)|*.cschn|CSV File (*.csv)|*.csv"
            ofd.RestoreDirectory = True
            ofd.InitialDirectory = export_path if export_path and exists(export_path) else System.Environment.GetFolderPath(System.Environment.SpecialFolder.Desktop)

            if ofd.ShowDialog() == Forms.DialogResult.OK:
                config.set_option("Spectrum_ExportPath", dirname(ofd.FileName))
                pyrevit_script.save_config()
                self.Close()
                self.load_path_from_file(ofd.FileName)

    def load_path_from_file(self, path):
        wndw = getattr(SpectrumWindow, "_current_wndw", None)
        if not isfile(path) or not wndw: return
        is_csv = path.lower().endswith('.csv')
        
        cat_name = None
        par_name = None
        data_rows = []
        
        try:
            if is_csv:
                with open(path, "rb") as f:
                    reader = list(csv.reader(f))
                    if not reader: return
                    header = reader[0]
                    has_meta = len(header) >= 6 and header[0] == "Category"
                    
                    if has_meta and len(reader) > 1:
                        cat_name = reader[1][0].decode('utf-8') if hasattr(reader[1][0], 'decode') else str(reader[1][0])
                        par_name = reader[1][1].decode('utf-8') if hasattr(reader[1][1], 'decode') else str(reader[1][1])
                    
                    start_idx = 1 if (header[0] in ["Value", "Category"]) else 0
                    for row in reader[start_idx:]:
                        if has_meta and len(row) >= 6:
                            val = row[2].decode('utf-8') if hasattr(row[2], 'decode') else str(row[2])
                            data_rows.append({"val": val, "rgb": [row[3], row[4], row[5]]})
                        elif not has_meta and len(row) >= 4:
                            val = row[0].decode('utf-8') if hasattr(row[0], 'decode') else str(row[0])
                            data_rows.append({"val": val, "rgb": [row[1], row[2], row[3]]})
            else:
                with codecs.open(path, "r", encoding='utf-8') as file:
                    for line in file.readlines():
                        line = line.strip()
                        if not line: continue
                        if line.startswith(u"#Category::"):
                            cat_name = line.split(u"::")[1]
                        elif line.startswith(u"#Parameter::"):
                            par_name = line.split(u"::")[1]
                        elif u"::R" in line:
                            line_val = line.split(u"::R")
                            rgb_result = split(r"[RGB]", line_val[1])
                            data_rows.append({"val": line_val[0], "rgb": rgb_result})
            
            if cat_name and par_name:
                cat_idx = -1
                for i in range(wndw._categories.Items.Count):
                    row = wndw._get_data_row_from_item(wndw._categories.Items[i], i)
                    if row and row["Key"] == cat_name:
                        cat_idx = i
                        break
                
                if cat_idx != -1:
                    wndw._categories.SelectedIndex = cat_idx
                    par_idx = -1
                    for i in range(wndw._list_box1.Items.Count):
                        row = wndw._get_data_row_from_item(wndw._list_box1.Items[i], i)
                        if row and row["Key"] == par_name:
                            par_idx = i
                            break
                    
                    if par_idx != -1:
                        wndw._list_box1.SelectedIndex = par_idx
                    else:
                        UI.TaskDialog.Show("Warning", "Saved Parameter '{}' not found in current view.".format(par_name))
                        return
                else:
                    UI.TaskDialog.Show("Warning", "Saved Category '{}' not found in current view.".format(cat_name))
                    return
            else:
                if wndw.list_box2.Items.Count == 0:
                    UI.TaskDialog.Show("Missing Selection", "Old scheme detected. Please select a category and parameter manually first.")
                    return

            for ind, data in enumerate(data_rows):
                if self._radio_by_value.Checked:
                    for item in wndw._table_data_3.Rows:
                        if item["Key"] == data["val"]:
                            self.apply_color_to_item(data["rgb"], item)
                            break
                else:
                    if ind < len(wndw._table_data_3.Rows):
                        self.apply_color_to_item(data["rgb"], wndw._table_data_3.Rows[ind])
            
            wndw._update_listbox_colors()
            
        except Exception as ex:
            UI.TaskDialog.Show("Error Loading Scheme", str(ex))

    def apply_color_to_item(self, rgb_result, item):
        r, g, b = int(rgb_result[0]), int(rgb_result[1]), int(rgb_result[2])
        item["Value"].n1, item["Value"].n2, item["Value"].n3 = r, g, b
        item["Value"].colour = Drawing.Color.FromArgb(r, g, b)


def get_active_view(ac_doc):
    uidoc = HOST_APP.uiapp.ActiveUIDocument
    selected_view = ac_doc.ActiveView
    if selected_view.ViewType in (DB.ViewType.ProjectBrowser, DB.ViewType.SystemBrowser):
        selected_view = ac_doc.GetElement(uidoc.GetOpenUIViews()[0].ViewId)
    if not selected_view.CanUseTemporaryVisibilityModes():
        UI.TaskDialog.Show("Error", "Visibility settings cannot be modified in this view type.")
        return 0
    return selected_view

def get_parameter_value(para):
    if not para.HasValue: return "None"
    if para.StorageType == DB.StorageType.Double: return get_double_value(para)
    if para.StorageType == DB.StorageType.ElementId: return get_elementid_value(para)
    if para.StorageType == DB.StorageType.Integer: return get_integer_value(para)
    if para.StorageType == DB.StorageType.String: return para.AsString()
    return "None"

def get_double_value(para):
    return para.AsValueString()

def get_elementid_value(para, doc_param=None):
    if doc_param is None: doc_param = revit.DOCS.doc
    id_val = para.AsElementId()
    if get_elementid_value_func()(id_val) >= 0:
        return DB.Element.Name.GetValue(doc_param.GetElement(id_val))
    return "None"

def get_integer_value(para):
    version = int(HOST_APP.version)
    if version > 2021:
        return "True" if para.AsInteger() == 1 else "False" if DB.SpecTypeId.Boolean.YesNo == para.Definition.GetDataType() else para.AsValueString()
    else:
        return "True" if para.AsInteger() == 1 else "False" if DB.ParameterType.YesNo == para.Definition.ParameterType else para.AsValueString()

def strip_accents(text):
    return "".join(char for char in normalize("NFKD", text) if unicode_category(char) != "Mn")

def random_color():
    return randint(0, 230), randint(0, 230), randint(0, 230)

def get_range_values(category, param, new_view):
    doc_param = new_view.Document
    for sample_bic in System.Enum.GetValues(DB.BuiltInCategory):
        if category.int_id == int(sample_bic):
            bic = sample_bic
            break
    collector = DB.FilteredElementCollector(doc_param, new_view.Id).OfCategory(bic).WhereElementIsNotElementType().WhereElementIsViewIndependent().ToElements()
    list_values, used_colors = [], set()
    
    for ele in collector:
        ele_par = ele if param.param_type != 1 else doc_param.GetElement(ele.GetTypeId())
        if not ele_par: continue
        for pr in ele_par.Parameters:
            if pr.Definition.Name == param.par.Name:
                value = get_parameter_value(pr) or "None"
                match = [x for x in list_values if x.value == value]
                if match:
                    match[0].ele_id.Add(ele.Id)
                    if pr.StorageType == DB.StorageType.Double:
                        match[0].values_double.Add(pr.AsDouble())
                else:
                    while True:
                        r, g, b = random_color()
                        if (r, g, b) not in used_colors:
                            used_colors.add((r, g, b))
                            list_values.append(ValuesInfo(pr, value, ele.Id, r, g, b))
                            break
                break
    
    none_values = [x for x in list_values if x.value == "None"]
    list_values = [x for x in list_values if x.value != "None"]
    list_values = sorted(list_values, key=lambda x: x.value, reverse=False)
    
    if len(list_values) > 1:
        try:
            first_value = list_values[0].value
            indx_del = get_index_units(first_value)
            if indx_del == 0:
                list_values = sorted(list_values, key=lambda x: safe_float(x.value))
            elif 0 < indx_del < len(first_value):
                list_values = sorted(list_values, key=lambda x: safe_float(x.value[:-indx_del]))
        except Exception: pass
        
    if none_values and any(len(x.ele_id) > 0 for x in none_values):
        list_values.extend(none_values)
    return list_values

def safe_float(value):
    try: return float(value)
    except ValueError: return float("inf")

def get_used_categories_parameters(cat_exc, acti_view, doc_param=None):
    try:
        if doc_param is None:
            doc_param = acti_view.Document
    except (AttributeError, RuntimeError):
        doc_param = revit.DOCS.doc
    collector = (
        DB.FilteredElementCollector(doc_param, acti_view.Id)
        .WhereElementIsNotElementType()
        .WhereElementIsViewIndependent()
        .ToElements()
    )
    list_cat = []
    elementid_value_getter = get_elementid_value_func()
    
    for ele in collector:
        if ele.Category is None:
            continue
        current_int_cat_id = elementid_value_getter(ele.Category.Id)
        if (
            current_int_cat_id in cat_exc
            or current_int_cat_id >= -1
            or any(x.int_id == current_int_cat_id for x in list_cat)
        ):
            continue
            
        list_parameters = []
        seen_param_names = set() 
        
        typ = ele.Document.GetElement(ele.GetTypeId())
        if typ:
            for par in typ.Parameters:
                if par.Definition.BuiltInParameter not in (
                    DB.BuiltInParameter.ELEM_CATEGORY_PARAM,
                    DB.BuiltInParameter.ELEM_CATEGORY_PARAM_MT,
                ):
                    p_info = ParameterInfo(1, par)
                    if p_info.name not in seen_param_names: 
                        list_parameters.append(p_info)
                        seen_param_names.add(p_info.name)

        for par in ele.Parameters:
            if par.Definition.BuiltInParameter not in (
                DB.BuiltInParameter.ELEM_CATEGORY_PARAM,
                DB.BuiltInParameter.ELEM_CATEGORY_PARAM_MT,
            ):
                p_info = ParameterInfo(0, par)
                if p_info.name not in seen_param_names: 
                    list_parameters.append(p_info)
                    seen_param_names.add(p_info.name)
                        
        list_parameters = sorted(list_parameters, key=lambda x: x.name.upper())
        list_cat.append(CategoryInfo(ele.Category, list_parameters))
        
    list_cat = sorted(list_cat, key=lambda x: x.name)
    return list_cat

def solid_fill_pattern_id():
    doc_param = revit.DOCS.doc
    for pat in DB.FilteredElementCollector(doc_param).OfClass(DB.FillPatternElement):
        if pat.GetFillPattern().IsSolidFill: return pat.Id
    return None

def external_event_trace():
    exc_type, exc_value, exc_traceback = sys.exc_info()
    logger.debug("Exception type: %s", exc_type)
    for tb in extract_tb(exc_traceback):
        logger.debug("File: %s, Line: %s, Function: %s", tb[0], tb[1], tb[2])

def get_index_units(str_value):
    for let in str_value[::-1]:
        if let.isdigit(): return str_value[::-1].index(let)
    return -1

def get_color_shades(base_color, apply_line, apply_foreground, apply_background):
    r, g, b = base_color.Red, base_color.Green, base_color.Blue
    if apply_line and (apply_foreground or apply_background):
        line_r = max(0, min(255, int(r + (255 - r) * 0.6)))
        line_g = max(0, min(255, int(g + (255 - g) * 0.6)))
        line_b = max(0, min(255, int(b + (255 - b) * 0.6)))
        gray = (line_r + line_g + line_b) / 3
        return DB.Color(int(line_r * 0.7 + gray * 0.3), int(line_g * 0.7 + gray * 0.3), int(line_b * 0.7 + gray * 0.3)), base_color, base_color
    return base_color, base_color, base_color

def launch_spectrum():
    """Main entry point for Spectrum tool."""
    try:
        doc = revit.DOCS.doc
        if doc is None:
            raise AttributeError("Revit document is not available")
    except (AttributeError, RuntimeError, Exception):
        error_msg = UI.TaskDialog("Spectrum Error")
        error_msg.MainInstruction = "Unable to access Revit document"
        error_msg.MainContent = "Please ensure you have a Revit project open and try again."
        error_msg.Show()
        return

    sel_view = get_active_view(doc)
    if sel_view != 0:
        categ_inf_used = get_used_categories_parameters(CAT_EXCLUDED, sel_view, doc)
        
        event_handler = ApplyColors()
        ext_event = UI.ExternalEvent.Create(event_handler)

        event_handler_uns = SubscribeView()
        ext_event_uns = UI.ExternalEvent.Create(event_handler_uns)

        event_handler_filters = CreateFilters()
        ext_event_filters = UI.ExternalEvent.Create(event_handler_filters)

        event_handler_reset = ResetColors()
        ext_event_reset = UI.ExternalEvent.Create(event_handler_reset)

        event_handler_Legend = CreateLegend()
        ext_event_legend = UI.ExternalEvent.Create(event_handler_Legend)

        # ค้นหาไฟล์ .xaml แบบครอบคลุมทั้ง 2 ชื่อ ป้องกัน Error หาไฟล์ไม่เจอ 100%
        xaml_file = __file__.replace("script.py", "SpectrumWindow.xaml")
        if not os.path.exists(xaml_file):
            xaml_file = __file__.replace("script.py", "ColorSplasherWindow.xaml")
            if not os.path.exists(xaml_file):
                UI.TaskDialog.Show("Error", "Could not find SpectrumWindow.xaml or ColorSplasherWindow.xaml in the folder.")
                return
        
        wndw = SpectrumWindow(
            xaml_file,
            categ_inf_used,
            ext_event,
            ext_event_uns,
            sel_view,
            ext_event_reset,
            ext_event_legend,
            ext_event_filters,
        )
        
        if wndw._categories.Items.Count > 0:
            wndw._categories.SelectedIndex = 0
            
        wndw.show()

        SubscribeView._wndw = wndw
        ApplyColors._wndw = wndw
        ResetColors._wndw = wndw
        CreateLegend._wndw = wndw
        CreateFilters._wndw = wndw
        SpectrumWindow._current_wndw = wndw

if __name__ == "__main__":
    launch_spectrum()