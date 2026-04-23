# -*- coding: utf-8 -*-
# pylint: disable=import-error,invalid-name,broad-except
"""Advanced Copy State: บันทึก Filters ครบทุกช่อง (Foreground & Background) รองรับ Revit 2024-2026"""
import os
import json
import System
from pyrevit import forms, script, revit, DB

my_config = script.get_config()
default_safe_path = System.Environment.GetFolderPath(System.Environment.SpecialFolder.MyDocuments)
export_path = getattr(my_config, 'export_path', default_safe_path)

def get_rgb(color):
    return [int(color.Red), int(color.Green), int(color.Blue)] if color and color.IsValid else None

def get_id_val(eid):
    if eid is None or eid == DB.ElementId.InvalidElementId: return -1
    return int(eid.Value if hasattr(eid, "Value") else eid.IntegerValue)

class FilterCopyAction:
    def copy(self):
        view = revit.active_view
        doc = revit.doc
        
        preset_name = forms.ask_for_string(default="QuickCopy_State", prompt="ตั้งชื่อชุดข้อมูล Filters:\n(กด Enter เพื่อใช้ชื่อเดิมเขียนทับได้เลย)", title="Save Filter Preset")
        if not preset_name: return

        filter_ids = view.GetFilters()
        if not filter_ids:
            forms.alert("ไม่พบ Filters ในมุมมองนี้")
            return

        selected_filters = forms.SelectFromList.show(
            [doc.GetElement(fid).Name for fid in filter_ids],
            title="เลือก Filters ที่จะบันทึก", multiselect=True
        )
        if not selected_filters: return

        export_data = []
        for fid in filter_ids:
            f_elem = doc.GetElement(fid)
            if f_elem.Name in selected_filters:
                ovr = view.GetFilterOverrides(fid)
                transparency = ovr.SurfaceTransparency if hasattr(ovr, 'SurfaceTransparency') else ovr.Transparency
                
                # เก็บข้อมูลครอบคลุมทั้ง FG และ BG
                export_data.append({
                    "name": f_elem.Name,
                    "is_visible": view.GetFilterVisibility(fid),
                    "is_enabled": view.GetIsFilterEnabled(fid) if hasattr(view, 'GetIsFilterEnabled') else True,
                    "overrides": {
                        "halftone": ovr.Halftone, 
                        "transparency": transparency,
                        
                        "proj_line_color": get_rgb(ovr.ProjectionLineColor), 
                        "proj_line_weight": ovr.ProjectionLineWeight,
                        "proj_line_pattern": get_id_val(ovr.ProjectionLinePatternId),
                        
                        "surf_fg_pattern_id": get_id_val(ovr.SurfaceForegroundPatternId),
                        "surf_fg_pattern_color": get_rgb(ovr.SurfaceForegroundPatternColor),
                        "surf_bg_pattern_id": get_id_val(ovr.SurfaceBackgroundPatternId) if hasattr(ovr, 'SurfaceBackgroundPatternId') else -1,
                        "surf_bg_pattern_color": get_rgb(ovr.SurfaceBackgroundPatternColor) if hasattr(ovr, 'SurfaceBackgroundPatternColor') else None,
                        
                        "cut_line_color": get_rgb(ovr.CutLineColor), 
                        "cut_line_weight": ovr.CutLineWeight,
                        "cut_line_pattern": get_id_val(ovr.CutLinePatternId),
                        
                        "cut_fg_pattern_id": get_id_val(ovr.CutForegroundPatternId),
                        "cut_fg_pattern_color": get_rgb(ovr.CutForegroundPatternColor),
                        "cut_bg_pattern_id": get_id_val(ovr.CutBackgroundPatternId) if hasattr(ovr, 'CutBackgroundPatternId') else -1,
                        "cut_bg_pattern_color": get_rgb(ovr.CutBackgroundPatternColor) if hasattr(ovr, 'CutBackgroundPatternColor') else None
                    }
                })

        if not os.path.exists(export_path):
            os.makedirs(export_path)
            
        file_path = os.path.join(export_path, "{}.json".format(preset_name))
        with open(file_path, 'w') as f:
            json.dump(export_data, f, indent=4)
        forms.toast("บันทึก Filter Preset: {} เรียบร้อย".format(preset_name))

if __name__ == "__main__":
    FilterCopyAction().copy()