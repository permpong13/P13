# -*- coding: utf-8 -*-
# pylint: disable=import-error,invalid-name,broad-except
"""Apply portable view-filter presets, including cross-project filters."""
import os
import time
import json
import System
from pyrevit import forms, script, revit, DB, HOST_APP

my_config = script.get_config("p13_filter_state")
legacy_config = script.get_config()


def get_export_path():
    """Return the shared preset folder and remember a user-selected fallback."""
    configured_path = getattr(my_config, "export_path", None)
    if not configured_path:
        configured_path = getattr(legacy_config, "export_path", None)
    if configured_path and os.path.isdir(configured_path):
        return configured_path

    selected_path = forms.pick_folder(title="Select the folder containing Filter presets")
    if not selected_path:
        return None
    my_config.export_path = selected_path
    script.save_config()
    return selected_path

def safe_drafting_pattern_id(doc, val):
    if val is None or val == -1: return DB.ElementId.InvalidElementId
    pid = DB.ElementId(System.Int64(val))
    pat_elem = doc.GetElement(pid)
    if pat_elem and isinstance(pat_elem, DB.FillPatternElement):
        if pat_elem.GetFillPattern().Target == DB.FillPatternTarget.Drafting:
            return pid
    return DB.ElementId.InvalidElementId


def find_line_pattern_id(doc, pattern_name, legacy_id):
    """Resolve line patterns by name across projects, with legacy-ID fallback."""
    if pattern_name:
        for element in DB.FilteredElementCollector(doc).OfClass(DB.LinePatternElement):
            if element.Name == pattern_name:
                return element.Id
    if legacy_id not in (None, -1):
        candidate = doc.GetElement(DB.ElementId(System.Int64(legacy_id)))
        if candidate and isinstance(candidate, DB.LinePatternElement):
            return candidate.Id
    return DB.ElementId.InvalidElementId


def find_drafting_pattern_id(doc, pattern_name, legacy_id):
    """Resolve drafting fill patterns by name across projects."""
    if pattern_name:
        for element in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement):
            fill_pattern = element.GetFillPattern()
            if element.Name == pattern_name and fill_pattern.Target == DB.FillPatternTarget.Drafting:
                return element.Id
    return safe_drafting_pattern_id(doc, legacy_id)


def collect_project_filters(doc):
    """Collect every view-filter element supported by this Revit build."""
    filters_by_name = {}
    filter_classes = [DB.ParameterFilterElement]
    if hasattr(DB, "SelectionFilterElement"):
        filter_classes.append(DB.SelectionFilterElement)
    for filter_class in filter_classes:
        for filter_element in DB.FilteredElementCollector(doc).OfClass(filter_class):
            filters_by_name[filter_element.Name] = filter_element.Id
    return filters_by_name


def find_source_document(app, current_doc, filter_data):
    """Find the exact open source document recorded by Copy-F."""
    source_path = filter_data.get("source_document_path")
    source_title = filter_data.get("source_document_title")
    fallback_documents = []
    for candidate in app.Documents:
        if candidate.IsLinked or candidate.Equals(current_doc):
            continue
        fallback_documents.append(candidate)
        try:
            if source_path and candidate.PathName and candidate.PathName.lower() == source_path.lower():
                return candidate
        except Exception:
            pass
        if source_title and candidate.Title == source_title:
            return candidate

    # Preserve compatibility with presets created before source metadata existed.
    filter_name = filter_data.get("name")
    filter_classes = [DB.ParameterFilterElement]
    if hasattr(DB, "SelectionFilterElement"):
        filter_classes.append(DB.SelectionFilterElement)
    for candidate in fallback_documents:
        for filter_class in filter_classes:
            for filter_element in DB.FilteredElementCollector(candidate).OfClass(filter_class):
                if filter_element.Name == filter_name:
                    return candidate
    return None


def find_source_filter(source_doc, filter_data):
    """Find a source filter by stable UniqueId, falling back to its name."""
    unique_id = filter_data.get("source_filter_unique_id")
    if unique_id:
        try:
            source_filter = source_doc.GetElement(unique_id)
            if source_filter:
                return source_filter
        except Exception:
            pass
    filter_name = filter_data.get("name")
    filter_classes = [DB.ParameterFilterElement]
    if hasattr(DB, "SelectionFilterElement"):
        filter_classes.append(DB.SelectionFilterElement)
    for filter_class in filter_classes:
        for source_filter in DB.FilteredElementCollector(source_doc).OfClass(filter_class):
            if source_filter.Name == filter_name:
                return source_filter
    return None


def copy_missing_filter(source_doc, source_filter, target_doc):
    """Copy a filter definition inside a real target-document transaction."""
    transaction = DB.Transaction(target_doc, "Copy Filter from Source Project")
    transaction.Start()
    try:
        source_ids = System.Collections.Generic.List[DB.ElementId]()
        source_ids.Add(source_filter.Id)
        copied_ids = DB.ElementTransformUtils.CopyElements(
            source_doc,
            source_ids,
            target_doc,
            DB.Transform.Identity,
            DB.CopyPasteOptions()
        )
        transaction.Commit()
        if copied_ids and copied_ids.Count > 0:
            return copied_ids[0]
    except Exception:
        if transaction.GetStatus() == DB.TransactionStatus.Started:
            transaction.RollBack()
        raise
    return None

class FilterPasteAction:
    def paste(self):
        doc = revit.doc
        export_path = get_export_path()
        if not export_path:
            return
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
            all_proj_filters = collect_project_filters(doc)
            missing_names = [n for n in sel_names if n not in all_proj_filters]
            
            if missing_names:
                pulled_count = 0
                pull_errors = []
                selected_data = [item for item in data if item.get("name") in missing_names]
                for filter_data in selected_data:
                    missing_name = filter_data.get("name")
                    source_doc = find_source_document(app, doc, filter_data)
                    if not source_doc:
                        pull_errors.append("{}: source project is not open".format(missing_name))
                        continue
                    source_filter = find_source_filter(source_doc, filter_data)
                    if not source_filter:
                        pull_errors.append("{}: filter was not found in source project".format(missing_name))
                        continue
                    try:
                        copied_id = copy_missing_filter(source_doc, source_filter, doc)
                        if copied_id:
                            all_proj_filters[missing_name] = copied_id
                            pulled_count += 1
                    except Exception as copy_error:
                        pull_errors.append("{}: {}".format(missing_name, copy_error))
                
                if pulled_count > 0:
                    forms.toast("Copied {} missing filter(s) from the source project.".format(pulled_count))
                if pull_errors:
                    forms.alert(
                        "Some filters could not be copied:\n\n{}\n\nKeep the source project open and try again."
                        .format("\n".join(pull_errors)),
                        title="Cross-Project Filter Copy"
                    )
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
                                
                            try: new_ovr.SetProjectionLinePatternId(find_line_pattern_id(doc, ovs.get("proj_line_pattern_name"), ovs.get("proj_line_pattern", -1)))
                            except Exception: pass
                            try: new_ovr.SetCutLinePatternId(find_line_pattern_id(doc, ovs.get("cut_line_pattern_name"), ovs.get("cut_line_pattern", -1)))
                            except Exception: pass

                            new_ovr.SetSurfaceForegroundPatternId(find_drafting_pattern_id(doc, ovs.get("surf_fg_pattern_name"), ovs.get("surf_fg_pattern_id", -1)))
                            if hasattr(new_ovr, 'SetSurfaceBackgroundPatternId'): new_ovr.SetSurfaceBackgroundPatternId(find_drafting_pattern_id(doc, ovs.get("surf_bg_pattern_name"), ovs.get("surf_bg_pattern_id", -1)))
                            new_ovr.SetCutForegroundPatternId(find_drafting_pattern_id(doc, ovs.get("cut_fg_pattern_name"), ovs.get("cut_fg_pattern_id", -1)))
                            if hasattr(new_ovr, 'SetCutBackgroundPatternId'): new_ovr.SetCutBackgroundPatternId(find_drafting_pattern_id(doc, ovs.get("cut_bg_pattern_name"), ovs.get("cut_bg_pattern_id", -1)))
                            
                            v.SetFilterOverrides(fid, new_ovr)

            tg.Assimilate()
            forms.toast("Applied filters successfully!", title="Paste Complete")
        except Exception as e:
            tg.RollBack()
            forms.alert("Error: {}".format(e))

if __name__ == "__main__":
    FilterPasteAction().paste()
