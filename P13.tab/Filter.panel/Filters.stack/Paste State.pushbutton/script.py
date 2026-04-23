# -*- coding: utf-8 -*-
# pylint: disable=import-error,invalid-name,broad-except
"""Advanced Paste State: วางสถานะ Filters ลงหลาย Views (รองรับ Background Colors)"""
import os
import time
import json
import System
from pyrevit import forms, script, revit, DB

my_config = script.get_config()
default_safe_path = System.Environment.GetFolderPath(System.Environment.SpecialFolder.MyDocuments)
export_path = getattr(my_config, 'export_path', default_safe_path)

def set_id(val):
    return DB.ElementId(System.Int64(val)) if val and val != -1 else DB.ElementId.InvalidElementId

def safe_drafting_pattern_id(doc, val):
    """ระบบตรวจลายเส้น: อนุญาตเฉพาะ Drafting Pattern เท่านั้น หากไม่มีให้ปล่อยว่าง (ป้องกันการบังสีพื้นหลัง)"""
    if val is None or val == -1:
        return DB.ElementId.InvalidElementId
    
    pid = DB.ElementId(System.Int64(val))
    pat_elem = doc.GetElement(pid)
    
    # อนุญาตเฉพาะ Drafting Pattern หากเป็น Model หรือไม่พบ ให้คืนค่า Invalid (ว่างเปล่า) แทน
    if pat_elem and isinstance(pat_elem, DB.FillPatternElement):
        if pat_elem.GetFillPattern().Target == DB.FillPatternTarget.Drafting:
            return pid
            
    return DB.ElementId.InvalidElementId

class FilterPasteAction:
    def paste(self):
        doc = revit.doc
        
        # 1. ระบบ Auto-Load: 5 นาที
        json_file = None
        try:
            if os.path.exists(export_path):
                json_files = [os.path.join(export_path, f) for f in os.listdir(export_path) if f.endswith('.json')]
                if json_files:
                    latest_file = max(json_files, key=os.path.getmtime)
                    if time.time() - os.path.getmtime(latest_file) <= 300:
                        json_file = latest_file
                        forms.toast("Auto-loaded recent state: {}".format(os.path.basename(latest_file)))
        except Exception: pass
        
        if not json_file:
            json_file = forms.pick_file(file_ext='json', init_dir=export_path)
            
        if not json_file: return
        
        with open(json_file, 'r') as f:
            data = json.load(f)

        # 2. จัดกลุ่ม View และ Template
        all_views = DB.FilteredElementCollector(doc).OfClass(DB.View).WhereElementIsNotElementType().ToElements()
        options_dict = {"1. View Templates": []}
        
        for v in all_views:
            if v.IsTemplate:
                options_dict["1. View Templates"].append(v)
            elif v.ViewType not in [DB.ViewType.ProjectBrowser, DB.ViewType.SystemBrowser, DB.ViewType.Internal, DB.ViewType.DrawingSheet]:
                group_name = "2. Views ({})".format(v.ViewType)
                if group_name not in options_dict:
                    options_dict[group_name] = []
                options_dict[group_name].append(v)

        target_views = forms.SelectFromList.show(
            options_dict, 
            title="เลือก Views หรือ View Templates ที่ต้องการวาง Filters", 
            name_attr='Name', 
            multiselect=True
        )
        if not target_views: return

        sel_names = forms.SelectFromList.show([f["name"] for f in data], title="เลือก Filters ที่จะวาง", multiselect=True)
        if not sel_names: return

        tg = DB.TransactionGroup(doc, "Multi-View Filter Paste")
        tg.Start()
        try:
            all_proj_filters = {f.Name: f.Id for f in DB.FilteredElementCollector(doc).OfClass(DB.ParameterFilterElement)}
            
            for v in target_views:
                with revit.Transaction("Apply Filters to {}".format(v.Name)):
                    for fid in v.GetFilters():
                        if doc.GetElement(fid).Name in sel_names: v.RemoveFilter(fid)
                    
                    for f_data in data:
                        name = f_data["name"]
                        if name in sel_names and name in all_proj_filters:
                            fid = all_proj_filters[name]
                            if fid not in v.GetFilters(): v.AddFilter(fid)
                            
                            v.SetFilterVisibility(fid, f_data["is_visible"])
                            if hasattr(v, 'SetIsFilterEnabled'): v.SetIsFilterEnabled(fid, f_data["is_enabled"])
                            
                            ovs = f_data["overrides"]
                            new_ovr = DB.OverrideGraphicSettings()
                            
                            t_val = int(ovs.get("transparency", 0))
                            if hasattr(new_ovr, 'SetSurfaceTransparency'): new_ovr.SetSurfaceTransparency(t_val)
                            else: new_ovr.SetTransparency(t_val)
                            
                            new_ovr.SetHalftone(bool(ovs.get("halftone", False)))
                            
                            # === ยัดค่าสี (ครอบคลุมทั้ง Foreground และ Background) ===
                            if ovs.get("proj_line_color"):
                                new_ovr.SetProjectionLineColor(DB.Color(*ovs["proj_line_color"]))
                                
                            if ovs.get("surf_fg_pattern_color"):
                                new_ovr.SetSurfaceForegroundPatternColor(DB.Color(*ovs["surf_fg_pattern_color"]))
                            if ovs.get("surf_bg_pattern_color") and hasattr(new_ovr, 'SetSurfaceBackgroundPatternColor'):
                                new_ovr.SetSurfaceBackgroundPatternColor(DB.Color(*ovs["surf_bg_pattern_color"]))
                                
                            if ovs.get("cut_line_color"):
                                new_ovr.SetCutLineColor(DB.Color(*ovs["cut_line_color"]))
                                
                            if ovs.get("cut_fg_pattern_color"):
                                new_ovr.SetCutForegroundPatternColor(DB.Color(*ovs["cut_fg_pattern_color"]))
                            if ovs.get("cut_bg_pattern_color") and hasattr(new_ovr, 'SetCutBackgroundPatternColor'):
                                new_ovr.SetCutBackgroundPatternColor(DB.Color(*ovs["cut_bg_pattern_color"]))
                                
                            # === ความหนาเส้น ===
                            if ovs.get("proj_line_weight") and int(ovs.get("proj_line_weight", 0)) > 0:
                                new_ovr.SetProjectionLineWeight(int(ovs["proj_line_weight"]))
                            if ovs.get("cut_line_weight") and int(ovs.get("cut_line_weight", 0)) > 0:
                                new_ovr.SetCutLineWeight(int(ovs["cut_line_weight"]))
                                
                            # === รูปแบบเส้น (Line Patterns) ===
                            try: new_ovr.SetProjectionLinePatternId(set_id(ovs.get("proj_line_pattern", -1)))
                            except Exception: pass
                            
                            try: new_ovr.SetCutLinePatternId(set_id(ovs.get("cut_line_pattern", -1)))
                            except Exception: pass

                            # === รูปแบบลาย (Fill Patterns ครอบคลุมทั้ง FG และ BG) ===
                            new_ovr.SetSurfaceForegroundPatternId(safe_drafting_pattern_id(doc, ovs.get("surf_fg_pattern_id", -1)))
                            if hasattr(new_ovr, 'SetSurfaceBackgroundPatternId'):
                                new_ovr.SetSurfaceBackgroundPatternId(safe_drafting_pattern_id(doc, ovs.get("surf_bg_pattern_id", -1)))
                                    
                            new_ovr.SetCutForegroundPatternId(safe_drafting_pattern_id(doc, ovs.get("cut_fg_pattern_id", -1)))
                            if hasattr(new_ovr, 'SetCutBackgroundPatternId'):
                                new_ovr.SetCutBackgroundPatternId(safe_drafting_pattern_id(doc, ovs.get("cut_bg_pattern_id", -1)))
                            
                            # เขียนค่าทับลงไป
                            v.SetFilterOverrides(fid, new_ovr)

            tg.Assimilate()
            forms.toast("Applied filters to {} views/templates successfully!".format(len(target_views)))
        except Exception as e:
            tg.RollBack()
            forms.alert("Error: {}".format(e))

if __name__ == "__main__":
    FilterPasteAction().paste()