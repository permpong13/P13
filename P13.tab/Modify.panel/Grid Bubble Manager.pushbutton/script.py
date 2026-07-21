# -*- coding: utf-8 -*-
from __future__ import print_function

__title__ = "Grid Bubble\nManager"
__doc__ = (
    "Manage grid bubbles in the active view by selection, window, continuous pick, "
    "or all visible grids. Supports view-oriented ends, crop-aware smart placement, "
    "arc grids, and multi-segment grids."
)
__author__ = "P13"

from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, DB, forms, script


doc = revit.doc
uidoc = revit.uidoc
view = revit.active_view
UI_FILE = script.get_bundle_file("ui.xaml")

SELECTION_CURRENT = "current"
SELECTION_WINDOW = "window"
SELECTION_ALL_VISIBLE = "all_visible"
SELECTION_CONTINUOUS = "continuous"

ACTION_BOTH = "both"
ACTION_NONE = "none"
ACTION_PRIMARY = "primary"
ACTION_SECONDARY = "secondary"
ACTION_TOGGLE = "toggle"
ACTION_SMART = "smart"

EPSILON = 0.000001


def get_id_value(element_id):
    if hasattr(element_id, "Value"):
        return element_id.Value
    return element_id.IntegerValue


GRID_CATEGORY_ID = get_id_value(DB.ElementId(DB.BuiltInCategory.OST_Grids))


def is_grid_element(element):
    if isinstance(element, DB.Grid):
        return True
    if hasattr(DB, "MultiSegmentGrid") and isinstance(element, DB.MultiSegmentGrid):
        return True
    return False


class GridSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        if not element or not element.Category:
            return False
        return (
            get_id_value(element.Category.Id) == GRID_CATEGORY_ID
            and is_grid_element(element)
        )

    def AllowReference(self, reference, point):
        return False


class GridBubbleManagerWindow(forms.WPFWindow):
    def __init__(self):
        forms.WPFWindow.__init__(self, UI_FILE)
        self.selection_mode = SELECTION_WINDOW
        self.action_mode = ACTION_SMART
        self.orient_by_view = True
        self._load_settings()

    def _load_settings(self):
        config = script.get_config()
        selection_mode = getattr(config, "selection_mode", SELECTION_WINDOW)
        action_mode = getattr(config, "action_mode", ACTION_SMART)
        orient_by_view = getattr(config, "orient_by_view", True)

        selection_controls = {
            SELECTION_CURRENT: self.selectionCurrent,
            SELECTION_WINDOW: self.selectionWindow,
            SELECTION_ALL_VISIBLE: self.selectionAllVisible,
            SELECTION_CONTINUOUS: self.selectionContinuous,
        }
        action_controls = {
            ACTION_BOTH: self.actionBoth,
            ACTION_NONE: self.actionNone,
            ACTION_PRIMARY: self.actionPrimary,
            ACTION_SECONDARY: self.actionSecondary,
            ACTION_TOGGLE: self.actionToggle,
            ACTION_SMART: self.actionSmart,
        }

        selection_controls.get(selection_mode, self.selectionWindow).IsChecked = True
        action_controls.get(action_mode, self.actionSmart).IsChecked = True
        self.orientByView.IsChecked = bool(orient_by_view)

    def _save_settings(self):
        config = script.get_config()
        config.selection_mode = self.selection_mode
        config.action_mode = self.action_mode
        config.orient_by_view = self.orient_by_view
        script.save_config()

    def start_clicked(self, sender, args):
        if self.selectionCurrent.IsChecked:
            self.selection_mode = SELECTION_CURRENT
        elif self.selectionAllVisible.IsChecked:
            self.selection_mode = SELECTION_ALL_VISIBLE
        elif self.selectionContinuous.IsChecked:
            self.selection_mode = SELECTION_CONTINUOUS
        else:
            self.selection_mode = SELECTION_WINDOW

        if self.actionBoth.IsChecked:
            self.action_mode = ACTION_BOTH
        elif self.actionNone.IsChecked:
            self.action_mode = ACTION_NONE
        elif self.actionPrimary.IsChecked:
            self.action_mode = ACTION_PRIMARY
        elif self.actionSecondary.IsChecked:
            self.action_mode = ACTION_SECONDARY
        elif self.actionToggle.IsChecked:
            self.action_mode = ACTION_TOGGLE
        else:
            self.action_mode = ACTION_SMART

        self.orient_by_view = bool(self.orientByView.IsChecked)
        self._save_settings()
        self.DialogResult = True
        self.Close()

    def cancel_clicked(self, sender, args):
        self.DialogResult = False
        self.Close()


def validate_active_view():
    if not doc or not view:
        forms.alert("No active Revit document or view was found.", exitscript=True)

    if view.IsTemplate:
        forms.alert("Open a project view before running Grid Bubble Manager.", exitscript=True)

    invalid_types = [DB.ViewType.Schedule, DB.ViewType.DrawingSheet]
    if hasattr(DB.ViewType, "ProjectBrowser"):
        invalid_types.append(DB.ViewType.ProjectBrowser)
    if view.ViewType in invalid_types:
        forms.alert(
            "Grid bubbles cannot be managed in the active view type.",
            exitscript=True,
        )

    try:
        category_id = DB.ElementId(DB.BuiltInCategory.OST_Grids)
        if view.GetCategoryHidden(category_id):
            forms.alert(
                "The Grids category is hidden in the active view. Show it and run the tool again.",
                exitscript=True,
            )
    except Exception:
        pass


def expand_grid_elements(elements):
    expanded = []
    seen_ids = set()

    for element in elements:
        candidates = []
        if isinstance(element, DB.Grid):
            candidates = [element]
        elif hasattr(DB, "MultiSegmentGrid") and isinstance(element, DB.MultiSegmentGrid):
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


def get_current_selected_grids():
    elements = [doc.GetElement(element_id) for element_id in uidoc.Selection.GetElementIds()]
    return expand_grid_elements(elements)


def pick_grids_by_window():
    elements = uidoc.Selection.PickElementsByRectangle(
        GridSelectionFilter(),
        "Drag a window around the grids to manage.",
    )
    return expand_grid_elements(elements)


def get_all_visible_grids():
    elements = (
        DB.FilteredElementCollector(doc, view.Id)
        .OfCategory(DB.BuiltInCategory.OST_Grids)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    return expand_grid_elements(elements)


def dot_product(vector_a, vector_b):
    return (
        vector_a.X * vector_b.X
        + vector_a.Y * vector_b.Y
        + vector_a.Z * vector_b.Z
    )


def get_view_coordinates(point):
    offset = point - view.Origin
    return (
        dot_product(offset, view.RightDirection),
        dot_product(offset, view.UpDirection),
    )


def get_grid_curve(grid):
    for extent_type in [
        DB.DatumExtentType.ViewSpecific,
        DB.DatumExtentType.Model,
    ]:
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


def get_end_data(grid):
    curve = get_grid_curve(grid)
    if not curve:
        return None

    try:
        point_0 = curve.GetEndPoint(0)
        point_1 = curve.GetEndPoint(1)
    except Exception:
        return None

    u_0, v_0 = get_view_coordinates(point_0)
    u_1, v_1 = get_view_coordinates(point_1)
    horizontal = abs(u_1 - u_0) >= abs(v_1 - v_0)

    return {
        "end_0": DB.DatumEnds.End0,
        "end_1": DB.DatumEnds.End1,
        "u_0": u_0,
        "v_0": v_0,
        "u_1": u_1,
        "v_1": v_1,
        "horizontal": horizontal,
    }


def get_primary_and_secondary_ends(grid, orient_by_view):
    if not orient_by_view:
        return DB.DatumEnds.End0, DB.DatumEnds.End1

    data = get_end_data(grid)
    if not data:
        return DB.DatumEnds.End0, DB.DatumEnds.End1

    if data["horizontal"]:
        end_0_is_primary = data["u_0"] <= data["u_1"]
    else:
        end_0_is_primary = data["v_0"] <= data["v_1"]

    if end_0_is_primary:
        return DB.DatumEnds.End0, DB.DatumEnds.End1
    return DB.DatumEnds.End1, DB.DatumEnds.End0


def get_crop_bounds():
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
                points.append(get_view_coordinates(point))

    if not points:
        return None

    u_values = [point[0] for point in points]
    v_values = [point[1] for point in points]
    return min(u_values), max(u_values), min(v_values), max(v_values)


def get_smart_outside_end(grid, orient_by_view, crop_bounds):
    primary, secondary = get_primary_and_secondary_ends(grid, orient_by_view)
    data = get_end_data(grid)
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


def get_desired_visibility(grid, action_mode, orient_by_view, crop_bounds):
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

    primary, secondary = get_primary_and_secondary_ends(grid, orient_by_view)
    chosen_end = primary
    if action_mode == ACTION_SECONDARY:
        chosen_end = secondary
    elif action_mode == ACTION_SMART:
        chosen_end = get_smart_outside_end(grid, orient_by_view, crop_bounds)

    return (
        chosen_end == DB.DatumEnds.End0,
        chosen_end == DB.DatumEnds.End1,
    )


def set_bubble_visibility(grid, datum_end, visible):
    current = grid.IsBubbleVisibleInView(datum_end, view)
    if current == visible:
        return False

    if visible:
        grid.ShowBubbleInView(datum_end, view)
    else:
        grid.HideBubbleInView(datum_end, view)
    return True


def apply_action_to_grid(grid, action_mode, orient_by_view, crop_bounds):
    if not grid.CanBeVisibleInView(view):
        return "skipped", "Grid cannot be visible in the active view orientation."

    desired_0, desired_1 = get_desired_visibility(
        grid,
        action_mode,
        orient_by_view,
        crop_bounds,
    )
    changed_0 = set_bubble_visibility(grid, DB.DatumEnds.End0, desired_0)
    changed_1 = set_bubble_visibility(grid, DB.DatumEnds.End1, desired_1)
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


def process_grids(grids, action_mode, orient_by_view, transaction_name):
    result = new_result()
    crop_bounds = get_crop_bounds()

    with revit.Transaction(transaction_name):
        for grid in grids:
            subtransaction = DB.SubTransaction(doc)
            try:
                subtransaction.Start()
                status, message = apply_action_to_grid(
                    grid,
                    action_mode,
                    orient_by_view,
                    crop_bounds,
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


def process_continuous_picks(action_mode, orient_by_view):
    result = new_result()
    picked_any = False

    while True:
        try:
            reference = uidoc.Selection.PickObject(
                ObjectType.Element,
                GridSelectionFilter(),
                "Pick a grid to update. Press Esc to finish.",
            )
        except OperationCanceledException:
            break

        element = doc.GetElement(reference.ElementId)
        grids = expand_grid_elements([element])
        if not grids:
            continue

        picked_any = True
        partial_result = process_grids(
            grids,
            action_mode,
            orient_by_view,
            "Manage Grid Bubbles",
        )
        merge_results(result, partial_result)

    return result, picked_any


def show_summary(result):
    lines = [
        "Updated: {}".format(result["updated"]),
        "Unchanged: {}".format(result["unchanged"]),
        "Skipped: {}".format(result["skipped"]),
        "Failed: {}".format(result["failed"]),
    ]

    if result["messages"]:
        lines.append("")
        lines.append("Details:")
        lines.extend(result["messages"][:12])
        remaining = len(result["messages"]) - 12
        if remaining > 0:
            lines.append("...and {} more item(s).".format(remaining))

    forms.alert("\n".join(lines), title="Grid Bubble Manager")


def main():
    validate_active_view()

    options_window = GridBubbleManagerWindow()
    if not options_window.show_dialog():
        script.exit()

    selection_mode = options_window.selection_mode
    action_mode = options_window.action_mode
    orient_by_view = options_window.orient_by_view

    if selection_mode == SELECTION_CONTINUOUS:
        result, picked_any = process_continuous_picks(action_mode, orient_by_view)
        if picked_any:
            show_summary(result)
        return

    try:
        if selection_mode == SELECTION_CURRENT:
            grids = get_current_selected_grids()
        elif selection_mode == SELECTION_ALL_VISIBLE:
            grids = get_all_visible_grids()
        else:
            grids = pick_grids_by_window()
    except OperationCanceledException:
        script.exit()

    if not grids:
        forms.alert(
            "No grids were found in the selected scope.",
            title="Grid Bubble Manager",
            exitscript=True,
        )

    result = process_grids(
        grids,
        action_mode,
        orient_by_view,
        "Manage Grid Bubbles",
    )
    show_summary(result)


if __name__ == "__main__":
    main()
