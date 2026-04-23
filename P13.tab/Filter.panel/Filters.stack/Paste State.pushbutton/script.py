# -*- coding: utf-8 -*-
# pylint: disable=import-error,invalid-name,broad-except
"""Advanced Paste State: วางสถานะ Filters ลงหลาย Views และ View Templates พร้อมจัดลำดับ (Auto-Load)"""
import os
import time
import json
import System
from pyrevit import forms, script, revit, DB

my_config = script.get_config()
# ป้องกันปัญหา Permission Denied หากไม่พบ config
default_safe_path = System.Environment.GetFolderPath(System.Environment.SpecialFolder.MyDocuments)
export_path = getattr(my_config, 'export_path', default_safe_path)

def set_id(val):
    return DB.ElementId(System.Int64(val)) if val and val != -1 else DB.ElementId.InvalidElementId

class FilterPasteAction:
    def paste(self):
        doc = revit.doc
        
        # 1. ระบบ Auto-Load: ค้นหาไฟล์ที่เพิ่ง Copy ไว้ในระยะเวลาไม่เกิน 5 นาที (300 วินาที)
        json_file = None
        try:
            if os.path.exists(export_path):
                # ดึงรายการไฟล์ .json ทั้งหมดในโฟลเดอร์
                json_files = [os.path.join(export_path, f) for f in os.listdir(export_path) if f.endswith('.json')]
                if json_files:
                    # หาไฟล์ที่แก้ไขล่าสุด
                    latest_file = max(json_files, key=os.path.getmtime)
                    # เช็คว่าอายุไฟล์เกิน 5 นาที (300 วินาที) หรือไม่
                    if time.time() - os.path.getmtime(latest_file) <= 300:
                        json_file = latest_file
                        forms.toast("Auto-loaded recent state: {}".format(os.path.basename(latest_file)))
        except Exception:
            pass
        
        # ถ้าไม่มีไฟล์ใน 5 นาทีที่ผ่านมา หรือไม่พบไฟล์ ให้แสดงหน้าต่างให้ผู้ใช้เลือกเอง
        if not json_file:
            json_file = forms.pick_file(file_ext='json', init_dir=export_path)
            
        if not json_file: return
        
        with open(json_file, 'r') as f:
            data = json.load(f)

        # 2. ค้นหา Views และ View Templates ทั้งหมดเพื่อจัดกลุ่มแสดงผล
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

        # 3. แสดงหน้าต่างเลือกเป้าหมายแบบจัดกลุ่ม (เลือกได้ทั้ง View และ View Template)
        target_views = forms.SelectFromList.show(
            options_dict, 
            title="เลือก Views หรือ View Templates ที่ต้องการวาง Filters", 
            name_attr='Name', 
            multiselect=True
        )
        
        if not target_views: return

        # 4. เลือก Filters จากในไฟล์ที่จะวาง
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
                            # สร้าง Object การตั้งค่าใหม่ (ค่าเริ่มต้นจะเป็น ไม่มีสี ไม่มีลายเส้น)
                            new_ovr = DB.OverrideGraphicSettings()
                            
                            # จัดการค่า Transparency
                            t_val = int(ovs["transparency"])
                            if hasattr(new_ovr, 'SetSurfaceTransparency'): new_ovr.SetSurfaceTransparency(t_val)
                            else: new_ovr.SetTransparency(t_val)
                            
                            # จัดการค่า Halftone
                            new_ovr.SetHalftone(bool(ovs["halftone"]))
                            
                            # === ตรวจสอบและยัดค่าสี (ทำเฉพาะตัวที่มีสีบันทึกมา) ===
                            if ovs.get("proj_line_color"):
                                new_ovr.SetProjectionLineColor(DB.Color(ovs["proj_line_color"][0], ovs["proj_line_color"][1], ovs["proj_line_color"][2]))
                            if ovs.get("surf_fg_pattern_color"):
                                new_ovr.SetSurfaceForegroundPatternColor(DB.Color(ovs["surf_fg_pattern_color"][0], ovs["surf_fg_pattern_color"][1], ovs["surf_fg_pattern_color"][2]))
                            if ovs.get("cut_line_color"):
                                new_ovr.SetCutLineColor(DB.Color(ovs["cut_line_color"][0], ovs["cut_line_color"][1], ovs["cut_line_color"][2]))
                            if ovs.get("cut_fg_pattern_color"):
                                new_ovr.SetCutForegroundPatternColor(DB.Color(ovs["cut_fg_pattern_color"][0], ovs["cut_fg_pattern_color"][1], ovs["cut_fg_pattern_color"][2]))
                                
                            # === ความหนาเส้น (ทำเฉพาะค่าที่มีการ Override) ===
                            if ovs.get("proj_line_weight") and int(ovs["proj_line_weight"]) > 0:
                                new_ovr.SetProjectionLineWeight(int(ovs["proj_line_weight"]))
                            if ovs.get("cut_line_weight") and int(ovs["cut_line_weight"]) > 0:
                                new_ovr.SetCutLineWeight(int(ovs["cut_line_weight"]))
                                
                            # === รูปแบบเส้น (Patterns) ===
                            new_ovr.SetProjectionLinePatternId(set_id(ovs["proj_line_pattern"]))
                            new_ovr.SetSurfaceForegroundPatternId(set_id(ovs["surf_fg_pattern_id"]))
                            new_ovr.SetCutLinePatternId(set_id(ovs["cut_line_pattern"]))
                            new_ovr.SetCutForegroundPatternId(set_id(ovs["cut_fg_pattern_id"]))
                            
                            # เขียนค่าทับลงไป
                            v.SetFilterOverrides(fid, new_ovr)

            tg.Assimilate()
            forms.toast("Applied filters to {} views/templates successfully!".format(len(target_views)))
        except Exception as e:
            tg.RollBack()
            forms.alert("Error: {}".format(e))

if __name__ == "__main__":
    FilterPasteAction().paste()