# -*- coding: utf-8 -*-
# pylint: disable=import-error,invalid-name,broad-except
"""Advanced Paste State: Active View/List Prompt & Auto-Pull Missing Filters"""
import os
import time
import json
import System
from pyrevit import forms, script, revit, DB, HOST_APP

my_config = script.get_config()
default_safe_path = System.Environment.GetFolderPath(System.Environment.SpecialFolder.MyDocuments)
export_path = getattr(my_config, 'export_path', default_safe_path)

def set_id(val):
    return DB.ElementId(System.Int64(val)) if val and val != -1 else DB.ElementId.InvalidElementId

def safe_drafting_pattern_id(doc, val):
    if val is None or val == -1: return DB.ElementId.InvalidElementId
    pid = DB.ElementId(System.Int64(val))
    pat_elem = doc.GetElement(pid)
    if pat_elem and isinstance(pat_elem, DB.FillPatternElement):
        if pat_elem.GetFillPattern().Target == DB.FillPatternTarget.Drafting:
            return pid
    return DB.ElementId.InvalidElementId

class FilterPasteAction:
    def paste(self):
        doc = revit.doc
        app = HOST_APP.app # ใช้ HOST_APP แทน revit.app เพื่อดึง Application Services
        
        # 1. โหลดไฟล์ JSON
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
        
        if not json_file: json_file = forms.pick_file(file_ext='json', init_dir=export_path)
        if not json_file: return
        with open(json_file, 'r') as f: data = json.load(f)

        # 2. เลือกปลายทาง
        paste_mode = forms.CommandSwitchWindow.show(
            ["1. Paste to Active View", "2. Select from list (Views or Templates)"],
            message="Select paste destination:"
        )
        if not paste_mode: return

        target_views = []
        if paste_mode.startswith("1"):
            if revit.active_view: target_views.append(revit.active_view)
            else: return forms.alert("Active View not found.")
        else:
            all_views = DB.FilteredElementCollector(doc).OfClass(DB.View).WhereElementIsNotElementType().ToElements()
            options_dict = {"1. View Templates": []}
            for v in all_views:
                if v.IsTemplate: options_dict["1. View Templates"].append(v)
                elif v.ViewType not in [DB.ViewType.ProjectBrowser, DB.ViewType.SystemBrowser, DB.ViewType.Internal, DB.ViewType.DrawingSheet]:
                    group_name = "2. Views ({})".format(v.ViewType)
                    if group_name not in options_dict: options_dict[group_name] = []
                    options_dict[group_name].append(v)
            target_views = forms.SelectFromList.show(options_dict, title="Select target Views", name_attr='Name', multiselect=True)
            if not target_views: return

        # 3. เลือก Filters
        sel_names = forms.SelectFromList.show([f["name"] for f in data], title="Select Filters to paste", multiselect=True)
        if not sel_names: return

        tg = DB.TransactionGroup(doc, "Multi-View Filter Paste (With Auto-Pull)")
        tg.Start()
        try:
            # --- ระบบ Auto-Pull ดึงโครงสร้างข้ามไฟล์ ---
            all_proj_filters = {f.Name: f.Id for f in DB.FilteredElementCollector(doc).OfClass(DB.ParameterFilterElement)}
            missing_names = [n for n in sel_names if n not in all_proj_filters]
            
            if missing_names:
                open_docs = [d for d in app.Documents if not d.IsLinked and d.Title != doc.Title]
                pulled_count = 0
                for missing_name in list(missing_names):
                    for other_doc in open_docs:
                        other_filter = next((f for f in DB.FilteredElementCollector(other_doc).OfClass(DB.ParameterFilterElement) if f.Name == missing_name), None)
                        if other_filter:
                            try:
                                copied_ids = DB.ElementTransformUtils.CopyElements(
                                    other_doc, 
                                    System.Collections.Generic.List[DB.ElementId]([other_filter.Id]), 
                                    doc, 
                                    DB.Transform.Identity, 
                                    DB.CopyPasteOptions()
                                )
                                if copied_ids:
                                    all_proj_filters[missing_name] = copied_ids[0]
                                    pulled_count += 1
                                    break
                            except Exception: pass
                
                if pulled_count > 0:
                    forms.toast("Auto-pulled {} missing filter(s) from other open files!".format(pulled_count))
            # ----------------------------------------

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
                            
                            if ovs.get("proj_line_color"): new_ovr.SetProjectionLineColor(DB.Color(*ovs["proj_line_color"]))
                            if ovs.get("surf_fg_pattern_color"): new_ovr.SetSurfaceForegroundPatternColor(DB.Color(*ovs["surf_fg_pattern_color"]))
                            if ovs.get("surf_bg_pattern_color") and hasattr(new_ovr, 'SetSurfaceBackgroundPatternColor'): new_ovr.SetSurfaceBackgroundPatternColor(DB.Color(*ovs["surf_bg_pattern_color"]))
                            if ovs.get("cut_line_color"): new_ovr.SetCutLineColor(DB.Color(*ovs["cut_line_color"]))
                            if ovs.get("cut_fg_pattern_color"): new_ovr.SetCutForegroundPatternColor(DB.Color(*ovs["cut_fg_pattern_color"]))
                            if ovs.get("cut_bg_pattern_color") and hasattr(new_ovr, 'SetCutBackgroundPatternColor'): new_ovr.SetCutBackgroundPatternColor(DB.Color(*ovs["cut_bg_pattern_color"]))
                            
                            if ovs.get("proj_line_weight") and int(ovs.get("proj_line_weight", 0)) > 0: new_ovr.SetProjectionLineWeight(int(ovs["proj_line_weight"]))
                            if ovs.get("cut_line_weight") and int(ovs.get("cut_line_weight", 0)) > 0: new_ovr.SetCutLineWeight(int(ovs["cut_line_weight"]))
                                
                            try: new_ovr.SetProjectionLinePatternId(set_id(ovs.get("proj_line_pattern", -1)))
                            except Exception: pass
                            try: new_ovr.SetCutLinePatternId(set_id(ovs.get("cut_line_pattern", -1)))
                            except Exception: pass

                            new_ovr.SetSurfaceForegroundPatternId(safe_drafting_pattern_id(doc, ovs.get("surf_fg_pattern_id", -1)))
                            if hasattr(new_ovr, 'SetSurfaceBackgroundPatternId'): new_ovr.SetSurfaceBackgroundPatternId(safe_drafting_pattern_id(doc, ovs.get("surf_bg_pattern_id", -1)))
                            new_ovr.SetCutForegroundPatternId(safe_drafting_pattern_id(doc, ovs.get("cut_fg_pattern_id", -1)))
                            if hasattr(new_ovr, 'SetCutBackgroundPatternId'): new_ovr.SetCutBackgroundPatternId(safe_drafting_pattern_id(doc, ovs.get("cut_bg_pattern_id", -1)))
                            
                            v.SetFilterOverrides(fid, new_ovr)

            tg.Assimilate()
            forms.toast("Applied filters successfully!", title="Paste Complete")
        except Exception as e:
            tg.RollBack()
            forms.alert("Error: {}".format(e))

if __name__ == "__main__":
    FilterPasteAction().paste()