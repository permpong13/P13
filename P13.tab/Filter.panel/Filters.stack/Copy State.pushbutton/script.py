# -*- coding: utf-8 -*-
# pylint: disable=import-error,invalid-name,broad-except
"""Save view-filter definitions and graphic states as portable presets."""
import os
import json
from pyrevit import forms, script, revit, DB

my_config = script.get_config("p13_filter_state")
legacy_config = script.get_config()


def get_export_path():
    """Return the shared preset folder and remember a user-selected fallback."""
    configured_path = getattr(my_config, "export_path", None)
    if not configured_path:
        configured_path = getattr(legacy_config, "export_path", None)
    if configured_path and os.path.isdir(configured_path):
        return configured_path

    selected_path = forms.pick_folder(title="Select a folder for Filter presets")
    if not selected_path:
        return None
    my_config.export_path = selected_path
    script.save_config()
    return selected_path

def get_rgb(color):
    return [int(color.Red), int(color.Green), int(color.Blue)] if color and color.IsValid else None

def get_id_val(eid):
    if eid is None or eid == DB.ElementId.InvalidElementId: return -1
    return int(eid.Value if hasattr(eid, "Value") else eid.IntegerValue)


def get_element_name(doc, element_id):
    """Return a portable resource name for an ElementId-based override."""
    if element_id is None or element_id == DB.ElementId.InvalidElementId:
        return None
    element = doc.GetElement(element_id)
    return element.Name if element else None


def get_document_path(doc):
    """Return the source path when Revit exposes a file-system path."""
    try:
        return doc.PathName or None
    except Exception:
        return None

class FilterCopyAction:
    def copy(self):
        view = revit.active_view
        doc = revit.doc
        export_path = get_export_path()
        if not export_path:
            return
        
        # 1. Name the Preset
        preset_name = forms.ask_for_string(default="Filter_Preset_01", prompt="Enter a name for the Filter preset:", title="Save Filter Preset")
        if not preset_name: return

        # 2. Select Filters to save
        filter_ids = view.GetFilters()
        if not filter_ids:
            forms.alert("No Filters found in the active view.")
            return

        selected_filters = forms.SelectFromList.show(
            [doc.GetElement(fid).Name for fid in filter_ids],
            title="Select Filters to save", multiselect=True
        )
        if not selected_filters: return

        # 3. Collect ordered data
        export_data = []
        for fid in filter_ids:
            f_elem = doc.GetElement(fid)
            if f_elem.Name in selected_filters:
                ovr = view.GetFilterOverrides(fid)
                transparency = ovr.SurfaceTransparency if hasattr(ovr, 'SurfaceTransparency') else ovr.Transparency
                
                filter_data = {
                    "name": f_elem.Name,
                    "source_document_title": doc.Title,
                    "source_document_path": get_document_path(doc),
                    "source_filter_unique_id": f_elem.UniqueId,
                    "source_filter_class": f_elem.GetType().FullName,
                    "is_visible": view.GetFilterVisibility(fid),
                    "is_enabled": view.GetIsFilterEnabled(fid) if hasattr(view, 'GetIsFilterEnabled') else True,
                    "overrides": {
                        "halftone": ovr.Halftone, 
                        "transparency": transparency,
                        
                        "proj_line_color": get_rgb(ovr.ProjectionLineColor), 
                        "proj_line_weight": ovr.ProjectionLineWeight,
                        "proj_line_pattern": get_id_val(ovr.ProjectionLinePatternId),
                        "proj_line_pattern_name": get_element_name(doc, ovr.ProjectionLinePatternId),
                        
                        "surf_fg_pattern_id": get_id_val(ovr.SurfaceForegroundPatternId),
                        "surf_fg_pattern_name": get_element_name(doc, ovr.SurfaceForegroundPatternId),
                        "surf_fg_pattern_color": get_rgb(ovr.SurfaceForegroundPatternColor),
                        "surf_bg_pattern_id": get_id_val(ovr.SurfaceBackgroundPatternId) if hasattr(ovr, 'SurfaceBackgroundPatternId') else -1,
                        "surf_bg_pattern_name": get_element_name(doc, ovr.SurfaceBackgroundPatternId) if hasattr(ovr, 'SurfaceBackgroundPatternId') else None,
                        "surf_bg_pattern_color": get_rgb(ovr.SurfaceBackgroundPatternColor) if hasattr(ovr, 'SurfaceBackgroundPatternColor') else None,
                        
                        "cut_line_color": get_rgb(ovr.CutLineColor), 
                        "cut_line_weight": ovr.CutLineWeight,
                        "cut_line_pattern": get_id_val(ovr.CutLinePatternId),
                        "cut_line_pattern_name": get_element_name(doc, ovr.CutLinePatternId),
                        
                        "cut_fg_pattern_id": get_id_val(ovr.CutForegroundPatternId),
                        "cut_fg_pattern_name": get_element_name(doc, ovr.CutForegroundPatternId),
                        "cut_fg_pattern_color": get_rgb(ovr.CutForegroundPatternColor),
                        "cut_bg_pattern_id": get_id_val(ovr.CutBackgroundPatternId) if hasattr(ovr, 'CutBackgroundPatternId') else -1,
                        "cut_bg_pattern_name": get_element_name(doc, ovr.CutBackgroundPatternId) if hasattr(ovr, 'CutBackgroundPatternId') else None,
                        "cut_bg_pattern_color": get_rgb(ovr.CutBackgroundPatternColor) if hasattr(ovr, 'CutBackgroundPatternColor') else None
                    }
                }
                export_data.append(filter_data)

        # 4. Save to JSON
        file_path = os.path.join(export_path, "{}.json".format(preset_name))
        try:
            with open(file_path, 'w') as f:
                json.dump(export_data, f, indent=4)
            forms.toast("Successfully saved preset: {}".format(preset_name), title="Copy Complete")
        except Exception as e:
            forms.alert("Error saving file: {}".format(e))

if __name__ == "__main__":
    FilterCopyAction().copy()
