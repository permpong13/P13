# -*- coding: utf-8 -*-
# pylint: disable=import-error,invalid-name,broad-except
"""Save view-filter definitions and graphic states as portable presets."""
import os
import json
import tempfile
from pyrevit import forms, script, revit, DB

my_config = script.get_config("p13_filter_state")
legacy_config = script.get_config()


def _is_writable_preset_folder(path):
    """Return True only for an existing, non-root folder that accepts writes."""
    if not path:
        return False

    try:
        normalized_path = os.path.abspath(os.path.normpath(path))
        if not os.path.isdir(normalized_path):
            return False

        # Never treat a drive/UNC root as a preset folder. Revit/Windows may
        # allow reading it while still denying creation of files there.
        if os.path.dirname(normalized_path) == normalized_path:
            return False

        probe_fd, probe_path = tempfile.mkstemp(
            prefix=".p13_filter_state_write_test_",
            suffix=".tmp",
            dir=normalized_path
        )
        os.close(probe_fd)
        try:
            os.remove(probe_path)
        except Exception:
            pass
        return True
    except Exception:
        return False


def _save_export_path(path):
    """Persist a validated preset folder without changing old config fields."""
    my_config.export_path = path
    try:
        script.save_config()
    except Exception:
        # The selected folder is still usable for this run. A later run will
        # ask again if pyRevit cannot persist the preference.
        pass


def get_export_path():
    """Return the shared preset folder and remember a user-selected fallback."""
    configured_paths = [
        getattr(my_config, "export_path", None),
        getattr(legacy_config, "export_path", None)
    ]
    for configured_path in configured_paths:
        if _is_writable_preset_folder(configured_path):
            return os.path.abspath(os.path.normpath(configured_path))

    selected_path = forms.pick_folder(title="Select a folder for Filter presets")
    if not selected_path:
        return None
    if not _is_writable_preset_folder(selected_path):
        forms.alert(
            "The selected location is not a writable folder. "
            "Please select a normal project folder, such as Documents or Desktop.",
            title="Invalid preset folder"
        )
        return None

    selected_path = os.path.abspath(os.path.normpath(selected_path))
    _save_export_path(selected_path)
    return selected_path


def get_preset_file_path(export_path, preset_name):
    """Build a safe JSON filename while preserving named-preset overwrite behavior."""
    name = preset_name.strip()
    if name.lower().endswith(".json"):
        name = name[:-5].strip()
    if not name or name in (".", ".."):
        return None
    if any(character in name for character in '<>:"/\\|?*'):
        return None
    return os.path.join(export_path, "{}.json".format(name))

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
        file_path = get_preset_file_path(export_path, preset_name)
        if not file_path:
            forms.alert(
                "The preset name contains invalid filename characters. "
                "Use a simple name without \\/:*?\"<>|.",
                title="Invalid preset name"
            )
            return
        try:
            with open(file_path, 'w') as f:
                json.dump(export_data, f, indent=4)
            forms.toast("Successfully saved preset: {}".format(os.path.basename(file_path)), title="Copy Complete")
        except Exception as e:
            forms.alert(
                "Error saving file:\n{}\n\nFolder: {}\n\n"
                "Choose a writable folder and try again.".format(e, export_path),
                title="Copy State"
            )

if __name__ == "__main__":
    FilterCopyAction().copy()
