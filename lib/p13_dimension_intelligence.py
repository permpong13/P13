# -*- coding: utf-8 -*-
from __future__ import print_function

"""Adaptive, model-grounded dimension intelligence for P13 MCP.

The module deliberately learns from dimensions already present in the active
Revit model. It never sends model data to an external service and never adds an
EQ constraint, because an EQ constraint can reposition model elements.
"""

import hashlib
import json
import math
import os

from pyrevit import revit, DB

try:
    import clr
    try:
        clr.AddReference("System")
    except Exception:
        pass
    from System import Int64
except Exception:
    try:
        from System import Int64
    except Exception:
        Int64 = None



MIN_REFERENCE_COUNT = 2
PARALLEL_TOLERANCE = 0.70
LINE_EXTENSION_FEET = 2.0
VALID_DIRECTIONS = ("auto", "horizontal", "vertical", "aligned")
VALID_REFERENCE_SIDES = ("auto", "center", "start", "end", "both")


def get_id_value(element_id):
    if element_id is None:
        return None
    if hasattr(element_id, "Value"):
        value = element_id.Value
    else:
        value = element_id.IntegerValue
    # Revit 2026 exposes ElementId.Value as System.Int64.  IronPython's JSON
    # encoder does not serialize the CLR value directly, even though it looks
    # like an integer.  Converting through text guarantees a native Python
    # integer while retaining support for 64-bit Revit element ids.
    try:
        return int(str(value))
    except Exception:
        return int(value)


def make_element_id(value):
    """Create an ElementId for Revit 2026 Int64 with older-version fallback."""
    if Int64 is not None:
        try:
            return DB.ElementId(Int64(int(value)))
        except Exception:
            try:
                return DB.ElementId(Int64.Parse(str(value)))
            except Exception:
                pass
    try:
        import System
        return DB.ElementId(System.Int64(int(value)))
    except Exception:
        pass
    return DB.ElementId(int(value))


def safe_name(element):
    try:
        value = element.Name
        if value:
            return value
    except Exception:
        pass
    try:
        value = DB.Element.Name.GetValue(element)
        if value:
            return value
    except Exception:
        pass
    for built_in_parameter in (
        DB.BuiltInParameter.SYMBOL_NAME_PARAM,
        DB.BuiltInParameter.ALL_MODEL_TYPE_NAME,
    ):
        try:
            parameter = element.get_Parameter(built_in_parameter)
            value = parameter.AsString() if parameter else ""
            if value:
                return value
        except Exception:
            pass
    return ""


def dot_product(vector_a, vector_b):
    return (
        vector_a.X * vector_b.X
        + vector_a.Y * vector_b.Y
        + vector_a.Z * vector_b.Z
    )


def vector_length(vector):
    return math.sqrt(dot_product(vector, vector))


def normalize_vector(vector):
    length = vector_length(vector)
    if length < 0.000001:
        return None
    return DB.XYZ(vector.X / length, vector.Y / length, vector.Z / length)


def project_point_to_view_plane(view, point):
    normal = normalize_vector(view.ViewDirection)
    if not normal:
        return point
    offset = point - view.Origin
    return point - normal.Multiply(dot_product(offset, normal))


def get_bbox(element, view):
    try:
        bbox = element.get_BoundingBox(view)
    except Exception:
        bbox = None
    if not bbox:
        try:
            bbox = element.get_BoundingBox(None)
        except Exception:
            bbox = None
    return bbox


def get_bbox_center(element, view):
    bbox = get_bbox(element, view)
    if not bbox:
        return None
    point = DB.XYZ(
        (bbox.Min.X + bbox.Max.X) * 0.5,
        (bbox.Min.Y + bbox.Max.Y) * 0.5,
        (bbox.Min.Z + bbox.Max.Z) * 0.5,
    )
    return project_point_to_view_plane(view, point)


def get_bbox_side_point(element, view, direction, use_end_side):
    bbox = get_bbox(element, view)
    if not bbox:
        return None
    corners = []
    for x_value in (bbox.Min.X, bbox.Max.X):
        for y_value in (bbox.Min.Y, bbox.Max.Y):
            for z_value in (bbox.Min.Z, bbox.Max.Z):
                corners.append(
                    project_point_to_view_plane(
                        view,
                        DB.XYZ(x_value, y_value, z_value),
                    )
                )
    ordered = sorted(corners, key=lambda point: dot_product(point, direction))
    return ordered[-1] if use_end_side else ordered[0]


def category_name(element):
    try:
        return element.Category.Name if element.Category else ""
    except Exception:
        return ""


def dimension_type_to_data(dimension_type):
    style_type = ""
    try:
        style_type = str(dimension_type.StyleType)
    except Exception:
        pass
    family_name = ""
    try:
        family_name = dimension_type.FamilyName
    except Exception:
        pass
    style_parameters = []
    try:
        parameters = dimension_type.Parameters
    except Exception:
        parameters = []
    for parameter in parameters:
        try:
            parameter_name = parameter.Definition.Name
        except Exception:
            parameter_name = ""
        if not parameter_name:
            continue
        try:
            value = parameter.AsValueString()
            if value is None and parameter.StorageType == DB.StorageType.String:
                value = parameter.AsString()
            if value is None and parameter.StorageType == DB.StorageType.Integer:
                value = parameter.AsInteger()
            if value is None and parameter.StorageType == DB.StorageType.ElementId:
                value = get_id_value(parameter.AsElementId())
        except Exception:
            value = None
        if value is not None:
            style_parameters.append({"name": parameter_name, "value": value})
    style_parameters.sort(key=lambda item: item["name"])
    return {
        "dimension_type_id": get_id_value(dimension_type.Id),
        "name": safe_name(dimension_type),
        "family_name": family_name,
        "style_type": style_type,
        "style_parameters": style_parameters,
    }


def list_dimension_types(doc):
    result = []
    collector = DB.FilteredElementCollector(doc).OfClass(DB.DimensionType)
    for dimension_type in collector:
        result.append(dimension_type_to_data(dimension_type))
    return sorted(result, key=lambda item: (item["style_type"], item["name"]))


def get_dimension_orientation(dimension, view):
    try:
        direction = normalize_vector(dimension.Curve.Direction)
    except Exception:
        direction = None
    if not direction:
        return "unknown"
    right_alignment = abs(dot_product(direction, normalize_vector(view.RightDirection)))
    up_alignment = abs(dot_product(direction, normalize_vector(view.UpDirection)))
    if right_alignment >= 0.92:
        return "horizontal"
    if up_alignment >= 0.92:
        return "vertical"
    return "aligned"


def get_dimension_reference_categories(doc, dimension):
    names = set()
    try:
        references = dimension.References
    except Exception:
        references = []
    for reference in references:
        try:
            element = doc.GetElement(reference.ElementId)
        except Exception:
            element = None
        name = category_name(element) if element else ""
        if name:
            names.add(name)
    return sorted(names)


def get_segment_count(dimension):
    try:
        number = int(dimension.NumberOfSegments)
        return number if number > 0 else 1
    except Exception:
        pass
    try:
        return max(1, int(dimension.Segments.Size))
    except Exception:
        return 1


def collect_dimension_evidence(doc, limit=5000):
    evidence = []
    collector = (
        DB.FilteredElementCollector(doc)
        .OfClass(DB.Dimension)
        .WhereElementIsNotElementType()
    )
    for dimension in collector:
        if len(evidence) >= limit:
            break
        try:
            owner_view = doc.GetElement(dimension.OwnerViewId)
        except Exception:
            owner_view = None
        try:
            dimension_type = doc.GetElement(dimension.GetTypeId())
        except Exception:
            dimension_type = None
        if not owner_view or not dimension_type:
            continue
        evidence.append(
            {
                "dimension_id": get_id_value(dimension.Id),
                "dimension_type_id": get_id_value(dimension_type.Id),
                "dimension_type_name": safe_name(dimension_type),
                "style_type": str(getattr(dimension_type, "StyleType", "")),
                "view_id": get_id_value(owner_view.Id),
                "view_name": safe_name(owner_view),
                "view_type": str(owner_view.ViewType),
                "view_scale": int(getattr(owner_view, "Scale", 0) or 0),
                "orientation": get_dimension_orientation(dimension, owner_view),
                "reference_categories": get_dimension_reference_categories(doc, dimension),
                "segment_count": get_segment_count(dimension),
                "is_equality_constrained": bool(
                    getattr(dimension, "AreSegmentsEqual", False)
                ),
            }
        )
    return evidence


def summarize_dimension_evidence(doc, active_view, limit=5000):
    evidence = collect_dimension_evidence(doc, limit)
    type_summary = {}
    orientation_summary = {}
    category_summary = {}
    equality_count = 0
    active_view_count = 0

    for item in evidence:
        key = str(item["dimension_type_id"])
        if key not in type_summary:
            type_summary[key] = {
                "dimension_type_id": item["dimension_type_id"],
                "name": item["dimension_type_name"],
                "style_type": item["style_type"],
                "usage_count": 0,
            }
        type_summary[key]["usage_count"] += 1
        orientation = item["orientation"]
        orientation_summary[orientation] = orientation_summary.get(orientation, 0) + 1
        for name in item["reference_categories"]:
            category_summary[name] = category_summary.get(name, 0) + 1
        if item["is_equality_constrained"]:
            equality_count += 1
        if active_view and item["view_id"] == get_id_value(active_view.Id):
            active_view_count += 1

    sorted_types = sorted(
        type_summary.values(),
        key=lambda item: (-item["usage_count"], item["name"]),
    )
    sorted_categories = [
        {"category": key, "usage_count": category_summary[key]}
        for key in sorted(category_summary, key=lambda name: (-category_summary[name], name))
    ]
    return {
        "learning_method": "Live inference from dimensions already placed in this Revit model.",
        "dimension_count": len(evidence),
        "active_view_dimension_count": active_view_count,
        "equality_constrained_count": equality_count,
        "type_usage": sorted_types,
        "orientation_usage": orientation_summary,
        "category_usage": sorted_categories,
        "evidence": evidence,
    }


def get_learning_path():
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(appdata, "pyRevit", "P13", "dimension_learning.json")


def load_learning_data():
    path = get_learning_path()
    if not os.path.isfile(path):
        return {"version": 1, "contexts": {}}
    try:
        with open(path, "r") as learning_file:
            result = json.load(learning_file)
        if not isinstance(result, dict):
            raise ValueError("Invalid learning data")
        result.setdefault("version", 1)
        result.setdefault("contexts", {})
        return result
    except Exception:
        return {"version": 1, "contexts": {}}


def save_learning_data(data):
    path = get_learning_path()
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    temporary_path = path + ".tmp"
    with open(temporary_path, "w") as learning_file:
        json.dump(data, learning_file, indent=2, sort_keys=True)
    if os.path.isfile(path):
        os.remove(path)
    os.rename(temporary_path, path)


def document_key(doc):
    source = (doc.PathName or doc.Title or "Untitled").lower()
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]


def learning_context_key(doc, view, categories, direction):
    parts = [
        document_key(doc),
        str(view.ViewType),
        str(int(getattr(view, "Scale", 0) or 0)),
        direction,
        ",".join(sorted(categories)),
    ]
    return "|".join(parts)


def get_default_dimension_type_id(doc):
    try:
        return doc.GetDefaultElementTypeId(DB.ElementTypeGroup.LinearDimensionType)
    except Exception:
        return DB.ElementId.InvalidElementId


def is_linear_dimension_type(dimension_type):
    if not isinstance(dimension_type, DB.DimensionType):
        return False
    try:
        return dimension_type.StyleType == DB.DimensionStyleType.Linear
    except Exception:
        return str(getattr(dimension_type, "StyleType", "")).lower() == "linear"


def recommend_dimension_type(doc, view, categories, direction, requested_type_id=None):
    available = list_dimension_types(doc)
    if requested_type_id is not None:
        requested = doc.GetElement(make_element_id(requested_type_id))
        if is_linear_dimension_type(requested):
            result = dimension_type_to_data(requested)
            result.update(
                {
                    "score": None,
                    "confidence": 1.0,
                    "reason": "Explicitly requested by the caller.",
                    "source": "explicit",
                }
            )
            return result
        raise ValueError("dimension_type_id must identify a linear DimensionType.")

    evidence = collect_dimension_evidence(doc)
    scores = {}
    reasons = {}
    active_view_id = get_id_value(view.Id)
    requested_categories = set(categories)
    for item in evidence:
        type_id = item["dimension_type_id"]
        evidence_type = doc.GetElement(make_element_id(type_id))
        if not is_linear_dimension_type(evidence_type):
            continue
        score = 1.0
        reason_parts = ["used in model"]
        if item["view_id"] == active_view_id:
            score += 8.0
            reason_parts.append("used in active view")
        elif item["view_type"] == str(view.ViewType):
            score += 4.0
            reason_parts.append("same view type")
        if item["view_scale"] == int(getattr(view, "Scale", 0) or 0):
            score += 2.0
            reason_parts.append("same scale")
        overlap = requested_categories.intersection(set(item["reference_categories"]))
        if overlap:
            score += 3.0 * len(overlap)
            reason_parts.append("matching categories")
        if direction != "auto" and item["orientation"] == direction:
            score += 2.0
            reason_parts.append("matching direction")
        scores[type_id] = scores.get(type_id, 0.0) + score
        reasons[type_id] = reason_parts

    context_key = learning_context_key(doc, view, categories, direction)
    learning = load_learning_data()
    learned_counts = learning.get("contexts", {}).get(context_key, {})
    for type_id_text, count in learned_counts.items():
        try:
            type_id = int(type_id_text)
            if not is_linear_dimension_type(doc.GetElement(make_element_id(type_id))):
                continue
            scores[type_id] = scores.get(type_id, 0.0) + (10.0 * int(count))
            reasons.setdefault(type_id, []).append("previously accepted by user")
        except Exception:
            pass

    if not scores:
        default_id = get_default_dimension_type_id(doc)
        if default_id and default_id != DB.ElementId.InvalidElementId:
            type_id = get_id_value(default_id)
            scores[type_id] = 1.0
            reasons[type_id] = ["project default dimension type"]

    if not scores and available:
        for available_item in available:
            available_type = doc.GetElement(
                make_element_id(available_item["dimension_type_id"])
            )
            if is_linear_dimension_type(available_type):
                scores[available_item["dimension_type_id"]] = 0.5
                reasons[available_item["dimension_type_id"]] = [
                    "first available linear dimension type"
                ]
                break

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    if not ranked:
        raise ValueError("No usable DimensionType exists in this document.")
    best_id, best_score = ranked[0]
    dimension_type = doc.GetElement(make_element_id(best_id))
    result = dimension_type_to_data(dimension_type)
    total_score = sum([item[1] for item in ranked])
    confidence = best_score / total_score if total_score > 0 else 0.0
    result.update(
        {
            "score": round(best_score, 2),
            "confidence": round(confidence, 3),
            "reason": ", ".join(reasons.get(best_id, [])),
            "source": "model_and_local_learning",
            "ranked_candidates": [
                {
                    "dimension_type_id": item[0],
                    "score": round(item[1], 2),
                    "name": safe_name(doc.GetElement(make_element_id(item[0]))),
                }
                for item in ranked[:5]
                if doc.GetElement(make_element_id(item[0]))
            ],
        }
    )
    return result


def get_aligned_direction(points):
    if len(points) < 2:
        return None
    first = points[0]
    farthest = None
    farthest_length = 0.0
    for point in points[1:]:
        distance = vector_length(point - first)
        if distance > farthest_length:
            farthest = point
            farthest_length = distance
    return normalize_vector(farthest - first) if farthest else None


def resolve_direction(view, mode, points):
    if mode == "horizontal":
        return normalize_vector(view.RightDirection), "horizontal"
    if mode == "vertical":
        return normalize_vector(view.UpDirection), "vertical"
    aligned = get_aligned_direction(points)
    if mode == "aligned":
        return aligned, "aligned"
    if not aligned:
        return None, "auto"
    right = abs(dot_product(aligned, normalize_vector(view.RightDirection)))
    up = abs(dot_product(aligned, normalize_vector(view.UpDirection)))
    if right >= 0.92:
        return normalize_vector(view.RightDirection), "horizontal"
    if up >= 0.92:
        return normalize_vector(view.UpDirection), "vertical"
    return aligned, "aligned"


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
        instance = geometry_object if isinstance(geometry_object, DB.GeometryInstance) else None
        if instance:
            try:
                nested_geometry = instance.GetSymbolGeometry()
            except Exception:
                nested_geometry = None
            if nested_geometry:
                transform = current_transform.Multiply(instance.Transform)
                for nested_object, nested_transform in iter_geometry_objects(
                    nested_geometry,
                    transform,
                ):
                    yield nested_object, nested_transform


def get_named_family_reference(element, resolved_mode, side):
    names = []
    if side == "center":
        if resolved_mode == "vertical":
            names = ["CenterFrontBack", "CenterLeftRight"]
        else:
            names = ["CenterLeftRight", "CenterFrontBack"]
    elif side == "start":
        names = ["Left", "Front", "Bottom"]
    else:
        names = ["Right", "Back", "Top"]
    for name in names:
        if not hasattr(DB.FamilyInstanceReferenceType, name):
            continue
        try:
            references = element.GetReferences(
                getattr(DB.FamilyInstanceReferenceType, name)
            )
        except Exception:
            references = []
        if references and len(references) > 0:
            return references[0]
    return None


def get_geometry_side_reference(element, view, direction, use_end_side):
    options = DB.Options()
    options.ComputeReferences = True
    options.IncludeNonVisibleObjects = True
    options.View = view
    try:
        geometry = element.get_Geometry(options)
    except Exception:
        geometry = None
    best_reference = None
    best_score = None
    for geometry_object, transform in iter_geometry_objects(geometry):
        face = geometry_object if isinstance(geometry_object, DB.PlanarFace) else None
        if not face or not face.Reference:
            continue
        normal = normalize_vector(transform.OfVector(face.FaceNormal))
        if not normal:
            continue
        alignment = dot_product(normal, direction)
        if use_end_side and alignment < PARALLEL_TOLERANCE:
            continue
        if not use_end_side and alignment > -PARALLEL_TOLERANCE:
            continue
        origin = project_point_to_view_plane(view, transform.OfPoint(face.Origin))
        score = dot_product(origin, direction)
        if (
            best_score is None
            or (use_end_side and score > best_score)
            or (not use_end_side and score < best_score)
        ):
            best_reference = face.Reference
            best_score = score
    return best_reference


def get_element_targets(element, view, direction, resolved_mode, reference_side):
    if isinstance(element, DB.Grid):
        try:
            point = project_point_to_view_plane(view, element.Curve.Evaluate(0.5, True))
            return [(DB.Reference(element), point, "grid")]
        except Exception:
            return []

    if reference_side == "auto":
        center_targets = get_element_targets(
            element,
            view,
            direction,
            resolved_mode,
            "center",
        )
        if center_targets:
            return center_targets
        return get_element_targets(
            element,
            view,
            direction,
            resolved_mode,
            "start",
        )

    requests = [reference_side]
    if reference_side == "both":
        requests = ["start", "end"]
    targets = []
    for side in requests:
        reference = None
        point = None
        if side == "center" and isinstance(element, DB.Wall):
            try:
                reference = DB.Reference(element)
            except Exception:
                reference = None
        if isinstance(element, DB.FamilyInstance):
            reference = get_named_family_reference(element, resolved_mode, side)
        if side == "center":
            point = get_bbox_center(element, view)
        else:
            use_end = side == "end"
            if not reference:
                reference = get_geometry_side_reference(
                    element,
                    view,
                    direction,
                    use_end,
                )
            point = get_bbox_side_point(element, view, direction, use_end)
        if reference and point:
            targets.append((reference, point, side))
    return targets


def millimeters_to_internal(value):
    return DB.UnitUtils.ConvertToInternalUnits(
        float(value),
        DB.UnitTypeId.Millimeters,
    )


def build_dimension_line(view, points, direction, offset_mm):
    normal = normalize_vector(view.ViewDirection)
    perpendicular = normalize_vector(normal.CrossProduct(direction)) if normal else None
    if not perpendicular:
        raise ValueError("Could not calculate a dimension offset direction.")
    origin = points[0]
    direction_values = [dot_product(point - origin, direction) for point in points]
    offset_values = [dot_product(point - origin, perpendicular) for point in points]
    offset_value = max(offset_values) + millimeters_to_internal(offset_mm)
    base = origin + perpendicular.Multiply(offset_value)
    start = base + direction.Multiply(min(direction_values) - LINE_EXTENSION_FEET)
    end = base + direction.Multiply(max(direction_values) + LINE_EXTENSION_FEET)
    return DB.Line.CreateBound(start, end)


def stable_reference_key(doc, reference):
    try:
        stable = reference.ConvertToStableRepresentation(doc)
    except Exception:
        stable = ""
    return "{}|{}".format(get_id_value(reference.ElementId), stable)


def make_preview_signature(
    doc,
    view,
    element_ids,
    direction,
    side,
    offset_mm,
    type_id,
    geometry_fingerprint,
):
    payload = {
        "document": document_key(doc),
        "view_id": get_id_value(view.Id),
        "element_ids": sorted([int(value) for value in element_ids]),
        "direction": direction,
        "reference_side": side,
        "offset_mm": round(float(offset_mm), 4),
        "dimension_type_id": int(type_id),
        "geometry_fingerprint": geometry_fingerprint,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def prepare_auto_dimension(
    doc,
    view,
    elements,
    direction_mode="auto",
    reference_side="center",
    offset_mm=1000.0,
    requested_type_id=None,
):
    invalid_view_types = [DB.ViewType.Schedule, DB.ViewType.DrawingSheet]
    if hasattr(DB.ViewType, "ProjectBrowser"):
        invalid_view_types.append(DB.ViewType.ProjectBrowser)
    if view.ViewType in invalid_view_types or bool(getattr(view, "IsTemplate", False)):
        raise ValueError("Open a non-template model or drafting view before auto-dimensioning.")
    direction_mode = str(direction_mode or "auto").lower()
    reference_side = str(reference_side or "center").lower()
    if direction_mode not in VALID_DIRECTIONS:
        raise ValueError("direction must be one of: {}".format(", ".join(VALID_DIRECTIONS)))
    if reference_side not in VALID_REFERENCE_SIDES:
        raise ValueError(
            "reference_side must be one of: {}".format(
                ", ".join(VALID_REFERENCE_SIDES)
            )
        )
    if float(offset_mm) <= 0 or float(offset_mm) > 100000:
        raise ValueError("offset_mm must be greater than 0 and at most 100000.")
    centers = []
    for element in elements:
        center = get_bbox_center(element, view)
        if center:
            centers.append(center)
    if len(centers) < MIN_REFERENCE_COUNT:
        raise ValueError("At least two selected elements need visible bounding boxes.")
    direction, resolved_mode = resolve_direction(view, direction_mode, centers)
    if not direction:
        raise ValueError("Could not infer a valid dimension direction.")

    targets = []
    supported_ids = []
    unsupported = []
    used_keys = set()
    for element in elements:
        element_targets = get_element_targets(
            element,
            view,
            direction,
            resolved_mode,
            reference_side,
        )
        added = False
        for reference, point, side in element_targets:
            key = stable_reference_key(doc, reference)
            if key in used_keys:
                continue
            targets.append((reference, point, side, element))
            used_keys.add(key)
            added = True
        if added:
            supported_ids.append(get_id_value(element.Id))
        else:
            unsupported.append(
                {
                    "element_id": get_id_value(element.Id),
                    "category": category_name(element),
                    "reason": "No stable dimension reference was found for this direction and side.",
                }
            )
    if len(targets) < MIN_REFERENCE_COUNT:
        raise ValueError(
            "Fewer than two stable references were found. Try start/end, another direction, or families with named reference planes."
        )
    origin = targets[0][1]
    targets = sorted(targets, key=lambda item: dot_product(item[1] - origin, direction))
    points = [item[1] for item in targets]
    line = build_dimension_line(view, points, direction, float(offset_mm))
    categories = sorted(set([category_name(item[3]) for item in targets if category_name(item[3])]))
    recommendation = recommend_dimension_type(
        doc,
        view,
        categories,
        resolved_mode,
        requested_type_id,
    )
    element_ids = [get_id_value(element.Id) for element in elements]
    geometry_fingerprint = {
        "references": [stable_reference_key(doc, item[0]) for item in targets],
        "points": [
            [round(item[1].X, 8), round(item[1].Y, 8), round(item[1].Z, 8)]
            for item in targets
        ],
        "line": [
            [
                round(line.GetEndPoint(0).X, 8),
                round(line.GetEndPoint(0).Y, 8),
                round(line.GetEndPoint(0).Z, 8),
            ],
            [
                round(line.GetEndPoint(1).X, 8),
                round(line.GetEndPoint(1).Y, 8),
                round(line.GetEndPoint(1).Z, 8),
            ],
        ],
    }
    signature = make_preview_signature(
        doc,
        view,
        element_ids,
        resolved_mode,
        reference_side,
        float(offset_mm),
        recommendation["dimension_type_id"],
        geometry_fingerprint,
    )
    return {
        "direction": direction,
        "resolved_direction": resolved_mode,
        "targets": targets,
        "line": line,
        "categories": categories,
        "supported_element_ids": supported_ids,
        "unsupported_elements": unsupported,
        "reference_count": len(targets),
        "recommendation": recommendation,
        "preview_signature": signature,
        "element_ids": element_ids,
        "reference_side": reference_side,
        "offset_mm": float(offset_mm),
    }


def preview_to_data(prepared):
    line = prepared["line"]
    return {
        "workflow_stage": "preview",
        "safe_to_apply": prepared["reference_count"] >= MIN_REFERENCE_COUNT,
        "resolved_direction": prepared["resolved_direction"],
        "reference_side": prepared["reference_side"],
        "offset_mm": prepared["offset_mm"],
        "reference_count": prepared["reference_count"],
        "supported_element_ids": prepared["supported_element_ids"],
        "unsupported_elements": prepared["unsupported_elements"],
        "reference_categories": prepared["categories"],
        "recommended_dimension_type": prepared["recommendation"],
        "dimension_line": {
            "start": [line.GetEndPoint(0).X, line.GetEndPoint(0).Y, line.GetEndPoint(0).Z],
            "end": [line.GetEndPoint(1).X, line.GetEndPoint(1).Y, line.GetEndPoint(1).Z],
            "units": "Revit internal feet",
        },
        "preview_signature": prepared["preview_signature"],
        "movement_policy": "No EQ constraint will be created; source elements keep their current positions.",
    }


def set_equality_formula_display(dimension):
    try:
        parameter = dimension.get_Parameter(DB.BuiltInParameter.DIM_DISPLAY_EQ)
    except Exception:
        parameter = None
    if parameter and not parameter.IsReadOnly:
        try:
            parameter.Set(2)
        except Exception:
            pass


def remember_accepted_type(doc, view, categories, direction, dimension_type_id):
    try:
        learning = load_learning_data()
        context = learning_context_key(doc, view, categories, direction)
        contexts = learning.setdefault("contexts", {})
        counts = contexts.setdefault(context, {})
        key = str(int(dimension_type_id))
        counts[key] = int(counts.get(key, 0)) + 1
        save_learning_data(learning)
        return True
    except Exception:
        return False


def create_auto_dimension(doc, view, prepared):
    references = DB.ReferenceArray()
    for reference, point, side, element in prepared["targets"]:
        references.Append(reference)
    type_id = int(prepared["recommendation"]["dimension_type_id"])
    dimension_type = doc.GetElement(make_element_id(type_id))
    with revit.Transaction("P13 MCP Create Learned Dimension"):
        try:
            dimension = doc.Create.NewDimension(
                view,
                prepared["line"],
                references,
                dimension_type,
            )
        except Exception:
            dimension = doc.Create.NewDimension(view, prepared["line"], references)
            if dimension and dimension.GetTypeId() != dimension_type.Id:
                dimension.ChangeTypeId(dimension_type.Id)
        set_equality_formula_display(dimension)
        doc.Regenerate()
    learning_updated = remember_accepted_type(
        doc,
        view,
        prepared["categories"],
        prepared["resolved_direction"],
        type_id,
    )
    return {
        "dimension_id": get_id_value(dimension.Id),
        "dimension_type_id": type_id,
        "dimension_type_name": safe_name(dimension_type),
        "reference_count": prepared["reference_count"],
        "resolved_direction": prepared["resolved_direction"],
        "equality_constraint_applied": False,
        "source_elements_moved_by_p13": False,
        "learning_updated": learning_updated,
    }
