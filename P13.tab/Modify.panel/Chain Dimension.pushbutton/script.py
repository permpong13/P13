# -*- coding: utf-8 -*-
from __future__ import print_function

__title__ = "Chain\nDimension"
__doc__ = "Create one chained dimension from picked references or window-selected family instances."
__author__ = "P13"

import math

from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from System.Collections.Generic import List
from pyrevit import revit, DB, forms, script

doc = revit.doc
uidoc = revit.uidoc
view = revit.active_view

MIN_REFERENCE_COUNT = 2
LINE_EXTENSION_FEET = 5.0
PARALLEL_TOLERANCE = 0.70
UI_FILE = script.get_bundle_file("ui.xaml")


def get_model_categories_in_view(doc, view):
    collector = DB.FilteredElementCollector(doc, view.Id)
    elements = collector.WhereElementIsNotElementType().ToElements()
    
    categories = {}
    for elem in elements:
        category = elem.Category
        if isinstance(elem, DB.Grid):
            category = elem.Category
            if not category:
                try:
                    category = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Grids)
                except Exception:
                    pass

        if category:
            is_model = category.CategoryType == DB.CategoryType.Model
            is_grid = get_id_value(category.Id) == get_id_value(DB.ElementId(DB.BuiltInCategory.OST_Grids))
            if is_model or is_grid:
                category_name = category.Name
                category_id = get_id_value(category.Id)
                categories[category_name] = category_id
            
    return categories


class CategorySelectionFilter(ISelectionFilter):
    def __init__(self, allowed_category_ids):
        self.allowed_category_ids = allowed_category_ids

    def AllowElement(self, element):
        if isinstance(element, DB.Grid):
            grid_category_id = get_id_value(DB.ElementId(DB.BuiltInCategory.OST_Grids))
            return grid_category_id in self.allowed_category_ids

        if not element.Category:
            return False
        return get_id_value(element.Category.Id) in self.allowed_category_ids

    def AllowReference(self, reference, point):
        return False


class ChainDimensionWindow(forms.WPFWindow):
    def __init__(self):
        forms.WPFWindow.__init__(self, UI_FILE)
        self.selection_mode = None
        self.direction_mode = None
        self.target_mode = None
        self.selected_category_ids = []
        self.apply_equality = True

        # Collect model categories present in the active view
        self.categories_map = get_model_categories_in_view(doc, view)
        self.categories_list = sorted(self.categories_map.keys())
        self.CategoriesList.ItemsSource = self.categories_list
        self.CategoriesList.UnselectAll()

        self.selection_changed(None, None)

    def selection_changed(self, sender, args):
        if self.selectionManual.IsChecked:
            self.targetPanel.IsEnabled = False
            self.targetPanel.Opacity = 0.42
            self.categoriesPanel.IsEnabled = False
            self.categoriesPanel.Opacity = 0.42
        else:
            self.targetPanel.IsEnabled = True
            self.targetPanel.Opacity = 1.0
            self.categoriesPanel.IsEnabled = True
            self.categoriesPanel.Opacity = 1.0

    def select_all_categories(self, sender, args):
        self.CategoriesList.SelectAll()

    def clear_all_categories(self, sender, args):
        self.CategoriesList.UnselectAll()

    def start_clicked(self, sender, args):
        self.selection_mode = (
            "Pick References Manually"
            if self.selectionManual.IsChecked
            else "Window Select Families"
        )

        if self.directionVertical.IsChecked:
            self.direction_mode = "Vertical"
        elif self.directionAligned.IsChecked:
            self.direction_mode = "Aligned"
        else:
            self.direction_mode = "Horizontal"

        if self.targetEnd.IsChecked:
            self.target_mode = "End side of each family"
        elif self.targetBoth.IsChecked:
            self.target_mode = "Both sides of each family"
        else:
            self.target_mode = "Start side of each family"

        # Capture selected category IDs
        self.selected_category_ids = []
        for item in self.CategoriesList.SelectedItems:
            if item in self.categories_map:
                self.selected_category_ids.append(self.categories_map[item])

        if self.selection_mode == "Window Select Families" and len(self.selected_category_ids) == 0:
            forms.alert("Please select at least one category to measure.", title="Warning")
            return

        # Capture equality checkbox state
        self.apply_equality = self.applyEquality.IsChecked

        self.DialogResult = True
        self.Close()

    def cancel_clicked(self, sender, args):
        self.DialogResult = False
        self.Close()


def dot_product(vector_a, vector_b):
    return (
        vector_a.X * vector_b.X
        + vector_a.Y * vector_b.Y
        + vector_a.Z * vector_b.Z
    )


def get_id_value(element_id):
    if hasattr(element_id, "Value"):
        return element_id.Value
    return element_id.IntegerValue


def vector_length(vector):
    return math.sqrt(dot_product(vector, vector))


def normalize_vector(vector):
    length = vector_length(vector)
    if length < 0.000001:
        return None
    return DB.XYZ(vector.X / length, vector.Y / length, vector.Z / length)


def project_point_to_view_plane(point):
    origin = view.Origin
    normal = normalize_vector(view.ViewDirection)
    if not normal:
        return point

    offset = point - origin
    distance = dot_product(offset, normal)
    return point - normal.Multiply(distance)


def get_element_reference_point(reference):
    global_point = None
    try:
        global_point = reference.GlobalPoint
    except Exception:
        global_point = None

    if global_point:
        return project_point_to_view_plane(global_point)

    element = doc.GetElement(reference.ElementId)
    if not element:
        return None

    bbox = element.get_BoundingBox(view)
    if not bbox:
        bbox = element.get_BoundingBox(None)
    if not bbox:
        return None

    center = DB.XYZ(
        (bbox.Min.X + bbox.Max.X) * 0.5,
        (bbox.Min.Y + bbox.Max.Y) * 0.5,
        (bbox.Min.Z + bbox.Max.Z) * 0.5,
    )
    return project_point_to_view_plane(center)


def get_aligned_direction(points):
    first_point = points[0]
    farthest_point = None
    farthest_distance = 0.0

    for point in points[1:]:
        candidate = project_point_to_view_plane(point)
        distance = vector_length(candidate - first_point)
        if distance > farthest_distance:
            farthest_point = candidate
            farthest_distance = distance

    if not farthest_point:
        return None

    return normalize_vector(farthest_point - first_point)


def get_dimension_direction(mode, points):
    if mode == "Horizontal":
        return normalize_vector(view.RightDirection)
    if mode == "Vertical":
        return normalize_vector(view.UpDirection)
    return get_aligned_direction(points)


def get_bbox_center(element):
    bbox = element.get_BoundingBox(view)
    if not bbox:
        bbox = element.get_BoundingBox(None)
    if not bbox:
        return None

    return project_point_to_view_plane(
        DB.XYZ(
            (bbox.Min.X + bbox.Max.X) * 0.5,
            (bbox.Min.Y + bbox.Max.Y) * 0.5,
            (bbox.Min.Z + bbox.Max.Z) * 0.5,
        )
    )


def get_bbox_side_point(element, dimension_direction, use_end_side):
    bbox = element.get_BoundingBox(view)
    if not bbox:
        bbox = element.get_BoundingBox(None)
    if not bbox:
        return None

    corners = [
        DB.XYZ(bbox.Min.X, bbox.Min.Y, bbox.Min.Z),
        DB.XYZ(bbox.Min.X, bbox.Min.Y, bbox.Max.Z),
        DB.XYZ(bbox.Min.X, bbox.Max.Y, bbox.Min.Z),
        DB.XYZ(bbox.Min.X, bbox.Max.Y, bbox.Max.Z),
        DB.XYZ(bbox.Max.X, bbox.Min.Y, bbox.Min.Z),
        DB.XYZ(bbox.Max.X, bbox.Min.Y, bbox.Max.Z),
        DB.XYZ(bbox.Max.X, bbox.Max.Y, bbox.Min.Z),
        DB.XYZ(bbox.Max.X, bbox.Max.Y, bbox.Max.Z),
    ]
    projected = [project_point_to_view_plane(corner) for corner in corners]
    sorted_corners = sorted(
        projected,
        key=lambda point: dot_product(point, dimension_direction),
    )

    if use_end_side:
        side_value = dot_product(sorted_corners[-1], dimension_direction)
    else:
        side_value = dot_product(sorted_corners[0], dimension_direction)

    side_points = [
        point for point in projected
        if abs(dot_product(point, dimension_direction) - side_value) < 0.0001
    ]
    average_x = sum([point.X for point in side_points]) / len(side_points)
    average_y = sum([point.Y for point in side_points]) / len(side_points)
    average_z = sum([point.Z for point in side_points]) / len(side_points)
    return DB.XYZ(average_x, average_y, average_z)


def build_dimension_line(points, placement_point, dimension_direction):
    projected_placement = project_point_to_view_plane(placement_point)
    reference_origin = points[0]
    normal = normalize_vector(view.ViewDirection)

    if not normal:
        raise Exception("Active view does not provide a valid view direction.")

    offset_vector = projected_placement - reference_origin
    perpendicular_direction = normalize_vector(
        normal.CrossProduct(dimension_direction)
    )

    if not perpendicular_direction:
        raise Exception("Could not calculate a valid dimension offset direction.")

    offset_distance = dot_product(offset_vector, perpendicular_direction)
    base_point = reference_origin + perpendicular_direction.Multiply(offset_distance)

    projected_values = [dot_product(point - reference_origin, dimension_direction) for point in points]
    start_value = min(projected_values) - LINE_EXTENSION_FEET
    end_value = max(projected_values) + LINE_EXTENSION_FEET

    start_point = base_point + dimension_direction.Multiply(start_value)
    end_point = base_point + dimension_direction.Multiply(end_value)
    return DB.Line.CreateBound(start_point, end_point)


def sort_references(reference_points, dimension_direction):
    origin = reference_points[0][1]
    return sorted(
        reference_points,
        key=lambda item: dot_product(item[1] - origin, dimension_direction),
    )


def get_family_reference_type_names(mode, use_end_side):
    if mode == "Horizontal":
        return ["Right"] if use_end_side else ["Left"]
    if mode == "Vertical":
        return ["Back", "Top"] if use_end_side else ["Front", "Bottom"]
    return []


def get_first_family_reference(element, mode, use_end_side):
    for reference_type_name in get_family_reference_type_names(mode, use_end_side):
        if not hasattr(DB.FamilyInstanceReferenceType, reference_type_name):
            continue

        reference_type = getattr(DB.FamilyInstanceReferenceType, reference_type_name)
        try:
            references = element.GetReferences(reference_type)
        except Exception:
            references = []

        if references and len(references) > 0:
            return references[0]

    return None


def iter_geometry_objects(geometry_element, current_transform=None):
    if not geometry_element:
        return

    if not current_transform:
        current_transform = DB.Transform.Identity

    for geometry_object in geometry_element:
        yield geometry_object, current_transform

        solid = geometry_object if isinstance(geometry_object, DB.Solid) else None
        if solid and solid.Faces and solid.Faces.Size > 0:
            for face in solid.Faces:
                yield face, current_transform

        geometry_instance = geometry_object if isinstance(geometry_object, DB.GeometryInstance) else None
        if geometry_instance:
            try:
                symbol_geometry = geometry_instance.GetSymbolGeometry()
            except Exception:
                symbol_geometry = None

            if symbol_geometry:
                nested_transform = current_transform.Multiply(geometry_instance.Transform)
                for nested_object, nested_object_transform in iter_geometry_objects(
                    symbol_geometry,
                    nested_transform,
                ):
                    yield nested_object, nested_object_transform


def get_geometry_side_reference(element, dimension_direction, use_end_side):
    options = DB.Options()
    options.ComputeReferences = True
    options.IncludeNonVisibleObjects = True
    options.View = view

    try:
        geometry_element = element.get_Geometry(options)
    except Exception:
        geometry_element = None

    best_reference = None
    best_score = None

    for geometry_object, geometry_transform in iter_geometry_objects(geometry_element):
        face = geometry_object if isinstance(geometry_object, DB.PlanarFace) else None
        if not face or not face.Reference:
            continue

        face_normal = normalize_vector(geometry_transform.OfVector(face.FaceNormal))
        if not face_normal:
            continue

        normal_alignment = dot_product(face_normal, dimension_direction)
        if use_end_side:
            if normal_alignment < PARALLEL_TOLERANCE:
                continue
        else:
            if normal_alignment > -PARALLEL_TOLERANCE:
                continue

        face_origin = project_point_to_view_plane(geometry_transform.OfPoint(face.Origin))
        face_score = dot_product(face_origin, dimension_direction)

        if best_score is None:
            best_reference = face.Reference
            best_score = face_score
        elif use_end_side and face_score > best_score:
            best_reference = face.Reference
            best_score = face_score
        elif not use_end_side and face_score < best_score:
            best_reference = face.Reference
            best_score = face_score

    return best_reference


def get_family_side_reference(element, mode, dimension_direction, use_end_side):
    family_reference = get_first_family_reference(element, mode, use_end_side)
    if family_reference:
        return family_reference

    return get_geometry_side_reference(element, dimension_direction, use_end_side)


def get_unique_reference_key(reference):
    stable_text = ""
    try:
        stable_text = reference.ConvertToStableRepresentation(doc)
    except Exception:
        stable_text = ""

    return "{}|{}".format(get_id_value(reference.ElementId), stable_text)


def pick_reference_points():
    picked_refs = uidoc.Selection.PickObjects(
        ObjectType.PointOnElement,
        "Pick dimension references in order or any order. Press Finish when done.",
    )

    if not picked_refs or len(picked_refs) < MIN_REFERENCE_COUNT:
        forms.alert("Pick at least two references.", exitscript=True)

    reference_points = []
    used_keys = set()

    for picked_ref in picked_refs:
        key = get_unique_reference_key(picked_ref)
        if key in used_keys:
            continue

        point = get_element_reference_point(picked_ref)
        if point:
            reference_points.append((picked_ref, point))
            used_keys.add(key)

    if len(reference_points) < MIN_REFERENCE_COUNT:
        forms.alert("Could not read enough valid references from the selection.", exitscript=True)

    return reference_points


def pick_elements_by_rectangle(category_ids):
    selected_elements = uidoc.Selection.PickElementsByRectangle(
        CategorySelectionFilter(category_ids),
        "Drag a window around the elements to dimension.",
    )

    elements = []
    for element in selected_elements:
        if isinstance(element, DB.Grid):
            grid_category_id = get_id_value(DB.ElementId(DB.BuiltInCategory.OST_Grids))
            if grid_category_id in category_ids:
                elements.append(element)
        elif element.Category and get_id_value(element.Category.Id) in category_ids:
            elements.append(element)

    if len(elements) < MIN_REFERENCE_COUNT:
        forms.alert("Select at least two elements.", exitscript=True)

    return elements


def get_element_dimension_targets(elements, mode, dimension_direction, target_mode):
    reference_points = []

    for element in elements:
        # Handle Gridlines explicitly
        if isinstance(element, DB.Grid):
            try:
                reference = DB.Reference(element)
                curve = element.Curve
                if curve:
                    point = project_point_to_view_plane(curve.Evaluate(0.5, True))
                else:
                    point = get_bbox_center(element)
                if reference and point:
                    reference_points.append((reference, point))
            except Exception:
                pass
            continue

        side_requests = []
        if target_mode == "Start side of each family":
            side_requests = [False]
        elif target_mode == "End side of each family":
            side_requests = [True]
        else:
            side_requests = [False, True]

        for use_end_side in side_requests:
            reference = get_family_side_reference(
                element,
                mode,
                dimension_direction,
                use_end_side,
            )
            point = get_bbox_side_point(element, dimension_direction, use_end_side)
            if reference and point:
                reference_points.append((reference, point))

    if len(reference_points) < MIN_REFERENCE_COUNT:
        forms.alert(
            "Could not find enough dimension references on the selected elements. "
            "Use Pick References Manually, or add named reference planes to the families.",
            exitscript=True,
        )

    return reference_points


def create_reference_array(sorted_reference_points):
    ref_array = DB.ReferenceArray()
    for reference, point in sorted_reference_points:
        ref_array.Append(reference)
    return ref_array


def is_dimension_category_hidden():
    try:
        category_id = DB.ElementId(DB.BuiltInCategory.OST_Dimensions)
        return view.GetCategoryHidden(category_id)
    except Exception:
        return False


def select_and_show_element(element):
    if not element:
        return

    element_ids = List[DB.ElementId]([element.Id])
    uidoc.Selection.SetElementIds(element_ids)
    try:
        uidoc.ShowElements(element.Id)
    except Exception:
        pass


def apply_equality_formula_display(dimension):
    if not dimension:
        return

    try:
        dimension.AreSegmentsEqual = True
    except Exception:
        pass

    equality_display_param = None
    try:
        equality_display_param = dimension.get_Parameter(DB.BuiltInParameter.DIM_DISPLAY_EQ)
    except Exception:
        equality_display_param = None

    if not equality_display_param and hasattr(DB, "ParameterTypeId"):
        try:
            equality_display_param = dimension.GetParameter(DB.ParameterTypeId.DimDisplayEq)
        except Exception:
            equality_display_param = None

    if equality_display_param and not equality_display_param.IsReadOnly:
        try:
            equality_display_param.Set(2)
        except Exception:
            pass


def main():
    if not doc:
        forms.alert("No open Revit document found.", exitscript=True)

    invalid_view_types = [
        DB.ViewType.Schedule,
        DB.ViewType.DrawingSheet,
    ]
    if hasattr(DB.ViewType, "ProjectBrowser"):
        invalid_view_types.append(DB.ViewType.ProjectBrowser)

    if view.ViewType in invalid_view_types:
        forms.alert("Open a model or drafting view before running this tool.", exitscript=True)

    if is_dimension_category_hidden():
        forms.alert("Dimensions are hidden in the active view. Turn on the Dimensions category and run again.", exitscript=True)

    options_window = ChainDimensionWindow()
    if not options_window.show_dialog():
        script.exit()

    selection_mode = options_window.selection_mode
    mode = options_window.direction_mode
    target_mode = options_window.target_mode
    selected_category_ids = options_window.selected_category_ids
    apply_equality = options_window.apply_equality

    if selection_mode == "Window Select Families":
        try:
            elements = pick_elements_by_rectangle(selected_category_ids)
        except OperationCanceledException:
            script.exit()

        element_centers = []
        for element in elements:
            center = get_bbox_center(element)
            if center:
                element_centers.append(center)

        if len(element_centers) < MIN_REFERENCE_COUNT:
            forms.alert("Could not read enough selected element locations.", exitscript=True)

        dimension_direction = get_dimension_direction(mode, element_centers)
        if not dimension_direction:
            forms.alert("Could not calculate a valid dimension direction.", exitscript=True)

        reference_points = get_element_dimension_targets(
            elements,
            mode,
            dimension_direction,
            target_mode,
        )
    else:
        try:
            reference_points = pick_reference_points()
        except OperationCanceledException:
            script.exit()

        points = [item[1] for item in reference_points]
        dimension_direction = get_dimension_direction(mode, points)
        if not dimension_direction:
            forms.alert("Could not calculate a valid dimension direction.", exitscript=True)

    try:
        placement_point = uidoc.Selection.PickPoint(
            "Pick the dimension line placement point."
        )
    except OperationCanceledException:
        script.exit()

    sorted_reference_points = sort_references(reference_points, dimension_direction)
    sorted_points = [item[1] for item in sorted_reference_points]
    dimension_line = build_dimension_line(sorted_points, placement_point, dimension_direction)
    ref_array = create_reference_array(sorted_reference_points)

    try:
        with revit.Transaction("Create Chain Dimension"):
            dimension = doc.Create.NewDimension(view, dimension_line, ref_array)
            if apply_equality:
                apply_equality_formula_display(dimension)
            doc.Regenerate()
    except Exception as create_error:
        forms.alert(
            "Revit could not create a dimension from the picked references.\n\n{}".format(create_error),
            exitscript=True,
        )

    if not dimension:
        forms.alert("Revit could not create a dimension from the picked references.", exitscript=True)

    select_and_show_element(dimension)


if __name__ == "__main__":
    main()
