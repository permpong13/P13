# -*- coding: utf-8 -*-
from __future__ import print_function

"""Shared Grid Bubble Manager logic for P13 UI commands and MCP routes."""

from pyrevit import revit, DB


ACTION_BOTH = "both"
ACTION_NONE = "none"
ACTION_PRIMARY = "primary"
ACTION_SECONDARY = "secondary"
ACTION_TOGGLE = "toggle"
ACTION_SMART = "smart"
VALID_ACTIONS = [
    ACTION_BOTH,
    ACTION_NONE,
    ACTION_PRIMARY,
    ACTION_SECONDARY,
    ACTION_TOGGLE,
    ACTION_SMART,
]
EPSILON = 0.000001


def get_id_value(element_id):
    if hasattr(element_id, "Value"):
        return element_id.Value
    return element_id.IntegerValue


def is_grid_element(element):
    if isinstance(element, DB.Grid):
        return True
    return (
        hasattr(DB, "MultiSegmentGrid")
        and isinstance(element, DB.MultiSegmentGrid)
    )


def expand_grid_elements(doc, elements):
    expanded = []
    seen_ids = set()

    for element in elements:
        candidates = []
        if isinstance(element, DB.Grid):
            candidates = [element]
        elif (
            hasattr(DB, "MultiSegmentGrid")
            and isinstance(element, DB.MultiSegmentGrid)
        ):
            try:
                candidates = [doc.GetElement(grid_id) for grid_id in element.GetGridIds()]
            except Exception:
                candidates = []

        for candidate in candidates:
            if not isinstance(candidate, DB.Grid):
                continue
            id_value = get_id_value(candidate.Id)
            if id_value in seen_ids:
                continue
            expanded.append(candidate)
            seen_ids.add(id_value)

    return expanded


def get_all_visible_grids(doc, view):
    elements = (
        DB.FilteredElementCollector(doc, view.Id)
        .OfCategory(DB.BuiltInCategory.OST_Grids)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    return expand_grid_elements(doc, elements)


def dot_product(vector_a, vector_b):
    return (
        vector_a.X * vector_b.X
        + vector_a.Y * vector_b.Y
        + vector_a.Z * vector_b.Z
    )


def get_view_coordinates(view, point):
    offset = point - view.Origin
    return (
        dot_product(offset, view.RightDirection),
        dot_product(offset, view.UpDirection),
    )


def get_grid_curve(grid, view):
    for extent_type in [DB.DatumExtentType.ViewSpecific, DB.DatumExtentType.Model]:
        try:
            curves = list(grid.GetCurvesInView(extent_type, view))
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


def get_end_data(grid, view):
    curve = get_grid_curve(grid, view)
    if not curve:
        return None

    try:
        point_0 = curve.GetEndPoint(0)
        point_1 = curve.GetEndPoint(1)
    except Exception:
        return None

    u_0, v_0 = get_view_coordinates(view, point_0)
    u_1, v_1 = get_view_coordinates(view, point_1)
    return {
        "u_0": u_0,
        "v_0": v_0,
        "u_1": u_1,
        "v_1": v_1,
        "horizontal": abs(u_1 - u_0) >= abs(v_1 - v_0),
    }


def get_primary_and_secondary_ends(grid, view, orient_by_view):
    if not orient_by_view:
        return DB.DatumEnds.End0, DB.DatumEnds.End1

    data = get_end_data(grid, view)
    if not data:
        return DB.DatumEnds.End0, DB.DatumEnds.End1

    if data["horizontal"]:
        end_0_is_primary = data["u_0"] <= data["u_1"]
    else:
        end_0_is_primary = data["v_0"] <= data["v_1"]

    if end_0_is_primary:
        return DB.DatumEnds.End0, DB.DatumEnds.End1
    return DB.DatumEnds.End1, DB.DatumEnds.End0


def get_crop_bounds(view):
    try:
        crop_box = view.CropBox
    except Exception:
        crop_box = None
    if not crop_box:
        return None

    points = []
    for x_value in [crop_box.Min.X, crop_box.Max.X]:
        for y_value in [crop_box.Min.Y, crop_box.Max.Y]:
            for z_value in [crop_box.Min.Z, crop_box.Max.Z]:
                point = DB.XYZ(x_value, y_value, z_value)
                try:
                    point = crop_box.Transform.OfPoint(point)
                except Exception:
                    pass
                points.append(get_view_coordinates(view, point))

    u_values = [point[0] for point in points]
    v_values = [point[1] for point in points]
    return min(u_values), max(u_values), min(v_values), max(v_values)


def get_smart_outside_end(grid, view, orient_by_view, crop_bounds):
    primary, secondary = get_primary_and_secondary_ends(
        grid, view, orient_by_view
    )
    data = get_end_data(grid, view)
    if not data or not crop_bounds:
        return primary

    min_u, max_u, min_v, max_v = crop_bounds
    if data["horizontal"]:
        distance_0 = min(abs(data["u_0"] - min_u), abs(max_u - data["u_0"]))
        distance_1 = min(abs(data["u_1"] - min_u), abs(max_u - data["u_1"]))
    else:
        distance_0 = min(abs(data["v_0"] - min_v), abs(max_v - data["v_0"]))
        distance_1 = min(abs(data["v_1"] - min_v), abs(max_v - data["v_1"]))

    if abs(distance_0 - distance_1) <= EPSILON:
        return primary
    if distance_0 < distance_1:
        return DB.DatumEnds.End0
    return DB.DatumEnds.End1


def get_desired_visibility(grid, view, action_mode, orient_by_view, crop_bounds):
    end_0_visible = grid.IsBubbleVisibleInView(DB.DatumEnds.End0, view)
    end_1_visible = grid.IsBubbleVisibleInView(DB.DatumEnds.End1, view)

    if action_mode == ACTION_BOTH:
        return True, True
    if action_mode == ACTION_NONE:
        return False, False
    if action_mode == ACTION_TOGGLE:
        if end_0_visible and end_1_visible:
            return True, False
        if end_0_visible and not end_1_visible:
            return False, False
        if not end_0_visible and not end_1_visible:
            return False, True
        return True, True

    primary, secondary = get_primary_and_secondary_ends(
        grid, view, orient_by_view
    )
    chosen_end = primary
    if action_mode == ACTION_SECONDARY:
        chosen_end = secondary
    elif action_mode == ACTION_SMART:
        chosen_end = get_smart_outside_end(
            grid, view, orient_by_view, crop_bounds
        )

    return (
        chosen_end == DB.DatumEnds.End0,
        chosen_end == DB.DatumEnds.End1,
    )


def set_bubble_visibility(grid, view, datum_end, visible):
    current = grid.IsBubbleVisibleInView(datum_end, view)
    if current == visible:
        return False
    if visible:
        grid.ShowBubbleInView(datum_end, view)
    else:
        grid.HideBubbleInView(datum_end, view)
    return True


def apply_action_to_grid(grid, view, action_mode, orient_by_view, crop_bounds):
    if not grid.CanBeVisibleInView(view):
        return "skipped", "Grid cannot be visible in the active view orientation."

    desired_0, desired_1 = get_desired_visibility(
        grid, view, action_mode, orient_by_view, crop_bounds
    )
    changed_0 = set_bubble_visibility(
        grid, view, DB.DatumEnds.End0, desired_0
    )
    changed_1 = set_bubble_visibility(
        grid, view, DB.DatumEnds.End1, desired_1
    )
    if changed_0 or changed_1:
        return "updated", ""
    return "unchanged", ""


def new_result():
    return {
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "failed": 0,
        "messages": [],
    }


def merge_results(target, source):
    for key in ["updated", "unchanged", "skipped", "failed"]:
        target[key] += source[key]
    target["messages"].extend(source["messages"])


def get_grid_label(grid):
    try:
        return "Grid {}".format(grid.Name)
    except Exception:
        return "Grid ID {}".format(get_id_value(grid.Id))


def process_grids(doc, view, grids, action_mode, orient_by_view, transaction_name):
    if action_mode not in VALID_ACTIONS:
        raise ValueError("Unsupported grid bubble action: {}".format(action_mode))

    result = new_result()
    crop_bounds = get_crop_bounds(view)
    with revit.Transaction(transaction_name):
        for grid in grids:
            subtransaction = DB.SubTransaction(doc)
            try:
                subtransaction.Start()
                status, message = apply_action_to_grid(
                    grid, view, action_mode, orient_by_view, crop_bounds
                )
                subtransaction.Commit()
                result[status] += 1
                if message:
                    result["messages"].append(
                        "{}: {}".format(get_grid_label(grid), message)
                    )
            except Exception as error:
                try:
                    subtransaction.RollBack()
                except Exception:
                    pass
                result["failed"] += 1
                result["messages"].append(
                    "{}: {}".format(get_grid_label(grid), error)
                )
    return result
