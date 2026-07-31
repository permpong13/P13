# -*- coding: utf-8 -*-
from __future__ import print_function

__title__ = "Grid\nDimension"
__doc__ = (
    "Automatically group and dimension parallel gridlines in the active view "
    "or from a selection, placing dimension chains at a specified offset."
)
__author__ = "P13"

import math
from Autodesk.Revit.UI.Selection import ISelectionFilter
from pyrevit import revit, DB, forms, script

doc = revit.doc
view = revit.active_view
uidoc = revit.uidoc


class GridSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        return isinstance(element, DB.Grid)

    def AllowReference(self, reference, point):
        return False


def dot_product(vector_a, vector_b):
    return (
        vector_a.X * vector_b.X
        + vector_a.Y * vector_b.Y
        + vector_a.Z * vector_b.Z
    )


def normalize_vector(vector):
    length = math.sqrt(dot_product(vector, vector))
    if length < 0.000001:
        return None
    return DB.XYZ(vector.X / length, vector.Y / length, vector.Z / length)


def get_grid_curve(grid, active_view):
    for extent_type in [DB.DatumExtentType.ViewSpecific, DB.DatumExtentType.Model]:
        try:
            curves = list(grid.GetCurvesInView(extent_type, active_view))
        except Exception:
            curves = []
        if curves:
            try:
                return sorted(curves, key=lambda curve: curve.Length, reverse=True)[0]
            except Exception:
                return curves[0]
    try:
        return grid.Curve
    except Exception:
        return None


def normalize_grid_direction(v):
    # Ensure direction vector points generally to the right or up
    if v.X < -0.001:
        return DB.XYZ(-v.X, -v.Y, -v.Z)
    elif abs(v.X) <= 0.001 and v.Y < -0.001:
        return DB.XYZ(-v.X, -v.Y, -v.Z)
    return v


def get_linear_dimension_type(doc_element):
    try:
        type_id = doc_element.GetDefaultElementTypeId(DB.ElementTypeGroup.LinearDimensionType)
        if type_id and type_id != DB.ElementId.InvalidElementId:
            return doc_element.GetElement(type_id)
    except Exception:
        pass
    collector = DB.FilteredElementCollector(doc_element).OfClass(DB.DimensionType)
    for dt in collector:
        try:
            if dt.StyleType == DB.DimensionStyleType.Linear:
                return dt
        except Exception:
            pass
    return None


def select_grids():
    # 1. Check pre-selection
    selected_ids = uidoc.Selection.GetElementIds()
    pre_selected = []
    for el_id in selected_ids:
        el = doc.GetElement(el_id)
        if isinstance(el, DB.Grid):
            pre_selected.append(el)

    if len(pre_selected) >= 2:
        return pre_selected

    # 2. Offer selection options
    choice = forms.CommandSwitchWindow.show(
        ["All Visible Grids in View", "Select Grids by Window"],
        message="Choose grid selection method:"
    )
    if not choice:
        script.exit()

    if choice == "Select Grids by Window":
        try:
            picked = uidoc.Selection.PickElementsByRectangle(
                GridSelectionFilter(),
                "Drag a window around the grids to dimension."
            )
            return list(picked)
        except Exception:
            script.exit()
    else:
        # All visible grids in the active view
        collector = (
            DB.FilteredElementCollector(doc, view.Id)
            .OfClass(DB.Grid)
            .WhereElementIsNotElementType()
        )
        return list(collector)


def main():
    if not doc or not view:
        forms.alert("Please open a project and active 2D view first.", exitscript=True)

    if view.IsTemplate:
        forms.alert("This command cannot be run on view templates.", exitscript=True)

    invalid_types = [DB.ViewType.Schedule, DB.ViewType.DrawingSheet]
    if hasattr(DB.ViewType, "ProjectBrowser"):
        invalid_types.append(DB.ViewType.ProjectBrowser)
    if view.ViewType in invalid_types:
        forms.alert("Gridlines cannot be dimensioned in this view type.", exitscript=True)

    # 1. Get grids
    raw_grids = select_grids()
    if not raw_grids or len(raw_grids) < 2:
        forms.alert("Please select at least 2 grids to dimension.", exitscript=True)

    # 2. Filter for straight line grids and get their direction
    grids_with_lines = []
    for g in raw_grids:
        curve = get_grid_curve(g, view)
        if isinstance(curve, DB.Line):
            grids_with_lines.append((g, curve))

    if len(grids_with_lines) < 2:
        forms.alert("At least 2 straight gridlines are required.", exitscript=True)

    # 3. Choose placement option
    placement = forms.CommandSwitchWindow.show(
        ["Both Sides", "Top / Right Side Only", "Bottom / Left Side Only"],
        message="Select Dimension Placement:"
    )
    if not placement:
        script.exit()

    # 4. Choose offset in mm
    offset_str = forms.ask_for_string(
        default="1000",
        prompt="Dimension line offset from grid ends (in millimeters):",
        title="Grid Dimension Offset"
    )
    if not offset_str:
        script.exit()

    try:
        offset_mm = float(offset_str)
    except ValueError:
        forms.alert("Offset must be a valid number.", exitscript=True)

    if offset_mm <= 0 or offset_mm > 100000:
        forms.alert("Offset must be positive and less than 100,000 mm.", exitscript=True)

    # Convert offset to internal feet
    try:
        offset_feet = DB.UnitUtils.ConvertToInternalUnits(offset_mm, DB.UnitTypeId.Millimeters)
    except AttributeError:
        offset_feet = offset_mm / 304.8

    # 5. Group grids by direction
    groups = []  # List of dict: { "dir": XYZ, "grids": [(grid, curve)] }
    for g, curve in grids_with_lines:
        g_dir = normalize_vector(curve.Direction)
        if not g_dir:
            continue
        g_dir_normalized = normalize_grid_direction(g_dir)

        # Check if it fits in an existing group
        matched_group = None
        for group in groups:
            # Check dot product of directions
            dot = abs(dot_product(group["dir"], g_dir_normalized))
            if dot > 0.999:
                matched_group = group
                break

        if matched_group:
            matched_group["grids"].append((g, curve))
        else:
            groups.append({
                "dir": g_dir_normalized,
                "grids": [(g, curve)]
            })

    # Get linear dimension type
    dim_type = get_linear_dimension_type(doc)
    if not dim_type:
        forms.alert("No linear DimensionType found in this document.", exitscript=True)

    created_count = 0

    # 6. Create dimensions for each group
    with revit.Transaction("Auto Dimension Grids"):
        for group in groups:
            grids_in_group = group["grids"]
            if len(grids_in_group) < 2:
                continue

            grid_dir = group["dir"]
            # Perpendicular direction for dimension line
            dim_dir = normalize_vector(DB.XYZ(-grid_dir.Y, grid_dir.X, 0.0))
            if not dim_dir:
                continue

            # Sort grids by their projection on dim_dir
            # Map grid -> projection coordinate
            grids_with_proj = []
            for g, curve in grids_in_group:
                midpoint = curve.Evaluate(0.5, True)
                proj_d = dot_product(midpoint, dim_dir)
                grids_with_proj.append((g, curve, proj_d))

            grids_with_proj.sort(key=lambda item: item[2])

            # Filter out duplicate/collinear grids (closer than 1mm along dim_dir)
            unique_grids = []
            last_proj = None
            for g, curve, proj_d in grids_with_proj:
                if last_proj is None or abs(proj_d - last_proj) > 0.003:  # approx 1mm
                    unique_grids.append((g, curve, proj_d))
                    last_proj = proj_d

            if len(unique_grids) < 2:
                continue

            # Calculate bounds
            # For each grid, find min and max projection along grid_dir
            proj_g_values = []
            proj_d_values = []
            for g, curve, proj_d in unique_grids:
                p0 = curve.GetEndPoint(0)
                p1 = curve.GetEndPoint(1)
                proj_g_values.extend([dot_product(p0, grid_dir), dot_product(p1, grid_dir)])
                proj_d_values.append(proj_d)

            min_g = min(proj_g_values)
            max_g = max(proj_g_values)
            min_d = min(proj_d_values)
            max_d = max(proj_d_values)

            # Determine where to place the dimension line
            placements_to_create = []
            if placement == "Both Sides":
                placements_to_create.extend([
                    max_g + offset_feet,
                    min_g - offset_feet
                ])
            elif placement == "Top / Right Side Only":
                placements_to_create.append(max_g + offset_feet)
            elif placement == "Bottom / Left Side Only":
                placements_to_create.append(min_g - offset_feet)

            # Create dimensions
            for g_coord in placements_to_create:
                start_pt = grid_dir.Multiply(g_coord) + dim_dir.Multiply(min_d)
                end_pt = grid_dir.Multiply(g_coord) + dim_dir.Multiply(max_d)

                dim_line = DB.Line.CreateBound(start_pt, end_pt)

                ref_array = DB.ReferenceArray()
                for g, curve, proj_d in unique_grids:
                    ref_array.Append(DB.Reference(g))

                try:
                    doc.Create.NewDimension(view, dim_line, ref_array, dim_type)
                    created_count += 1
                except Exception as e:
                    # Fallback without explicit type
                    try:
                        doc.Create.NewDimension(view, dim_line, ref_array)
                        created_count += 1
                    except Exception as e_inner:
                        print("Failed to create dimension for group: {}".format(e_inner))

    forms.alert("Successfully created {} dimension chain(s).".format(created_count))


if __name__ == "__main__":
    main()
