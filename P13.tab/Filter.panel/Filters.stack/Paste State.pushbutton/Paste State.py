# -*- coding: utf-8 -*-
# pylint: disable=import-error,invalid-name,broad-except
"""Advanced Paste State: วางสถานะ Filters ลงหลาย Views พร้อมจัดลำดับ"""
import os
import json
import System
from pyrevit import forms, script, revit, DB

my_config = script.get_config()
export_path = getattr(my_config, 'export_path', r'C:\\')

def set_rgb(rgb_list):
    return DB.Color(rgb_list[0], rgb_list[1], rgb_list[2]) if rgb_list else DB.Color.InvalidColor

def set_id(val):
    return DB.ElementId(System.Int64(val)) if val and val != -1 else DB.ElementId.InvalidElementId

class FilterPasteAction:
    def paste(self):
        doc = revit.doc
        # 1. เลือกไฟล์ Preset
        json_file = forms.pick_file(file_ext='json', init_dir=export_path)
        if not json_file: return
        with open(json_file, 'r') as f:
            data = json.load(f)

        # 2. เลือก Views เป้าหมาย
        target_views = forms.select_views(title="เลือก Views ที่ต้องการวาง Filters")
        if not target_views: return

        # 3. เลือก Filters จากในไฟล์ที่จะวาง
        sel_names = forms.SelectFromList.show([f["name"] for f in data], title="เลือก Filters ที่จะวาง", multiselect=True)
        if not sel_names: return

        tg = DB.TransactionGroup(doc, "Multi-View Filter Paste")
        tg.Start()
        try:
            all_proj_filters = {f.Name: f.Id for f in DB.FilteredElementCollector(doc).OfClass(DB.ParameterFilterElement)}
            
            for v in target_views:
                with revit.Transaction("Apply Filters to {}".format(v.Name)):
                    # ลบรายการที่ซ้ำออกก่อนเพื่อจัดลำดับใหม่
                    for fid in v.GetFilters():
                        if doc.GetElement(fid).Name in sel_names: v.RemoveFilter(fid)
                    
                    # วางข้อมูลตามลำดับที่บันทึกมา
                    for f_data in data:
                        name = f_data["name"]
                        if name in sel_names and name in all_proj_filters:
                            fid = all_proj_filters[name]
                            if fid not in v.GetFilters(): v.AddFilter(fid)
                            
                            v.SetFilterVisibility(fid, f_data["is_visible"])
                            if hasattr(v, 'SetIsFilterEnabled'): v.SetIsFilterEnabled(fid, f_data["is_enabled"])
                            
                            ovs = f_data["overrides"]
                            new_ovr = DB.OverrideGraphicSettings()
                            # รองรับ Revit 2024-2026
                            t_val = int(ovs["transparency"])
                            if hasattr(new_ovr, 'SetSurfaceTransparency'): new_ovr.SetSurfaceTransparency(t_val)
                            else: new_ovr.SetTransparency(t_val)
                            
                            new_ovr.SetHalftone(bool(ovs["halftone"]))
                            new_ovr.SetProjectionLineColor(set_rgb(ovs["proj_line_color"]))
                            new_ovr.SetProjectionLineWeight(int(ovs["proj_line_weight"]) if ovs["proj_line_weight"] > 0 else -1)
                            new_ovr.SetProjectionLinePatternId(set_id(ovs["proj_line_pattern"]))
                            new_ovr.SetSurfaceForegroundPatternId(set_id(ovs["surf_fg_pattern_id"]))
                            new_ovr.SetSurfaceForegroundPatternColor(set_rgb(ovs["surf_fg_pattern_color"]))
                            new_ovr.SetCutLineColor(set_rgb(ovs["cut_line_color"]))
                            new_ovr.SetCutLineWeight(int(ovs["cut_line_weight"]) if ovs["cut_line_weight"] > 0 else -1)
                            new_ovr.SetCutLinePatternId(set_id(ovs["cut_line_pattern"]))
                            new_ovr.SetCutForegroundPatternId(set_id(ovs["cut_fg_pattern_id"]))
                            new_ovr.SetCutForegroundPatternColor(set_rgb(ovs["cut_fg_pattern_color"]))
                            v.SetFilterOverrides(fid, new_ovr)

            tg.Assimilate()
            forms.toast("Applied filters to {} views successfully!".format(len(target_views)))
        except Exception as e:
            tg.RollBack()
            forms.alert("Error: {}".format(e))

FilterPasteAction().paste()