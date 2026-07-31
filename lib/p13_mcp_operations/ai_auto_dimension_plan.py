# -*- coding: utf-8 -*-
from __future__ import print_function

"""Plan, preview, apply, and verify a safe learned dimension in a plan view."""

import datetime
import json
import os

from pyrevit import revit, DB

from p13_dimension_intelligence import (
    category_name,
    dot_product,
    get_id_value,
    make_element_id,
    prepare_auto_dimension,
    preview_to_data as dimension_preview_to_data,
    remember_accepted_type,
    safe_name,
    set_equality_formula_display,
    stable_reference_key,
)


PLAN_VIEW_NAMES = (
    "FloorPlan",
    "CeilingPlan",
    "EngineeringPlan",
    "AreaPlan",
)
MOVEMENT_TOLERANCE_FEET = 0.000001
ZERO_GAP_TOLERANCE_FEET = 0.000001


def _is_plan_view(view):
    return str(getattr(view, "ViewType", "")) in PLAN_VIEW_NAMES


def _resolve_elements(doc, uidoc, raw_ids):
    ids = raw_ids or []
    if not ids and uidoc:
        ids = [get_id_value(item) for item in uidoc.Selection.GetElementIds()]
    if not isinstance(ids, list):
        raise ValueError("element_ids must be a list of integers.")
    elements = []
    invalid = []
    for raw_id in ids:
        try:
            element = doc.GetElement(make_element_id(raw_id))
        except Exception:
            element = None
        if element:
            elements.append(element)
        else:
            invalid.append(raw_id)
    return elements, invalid


def _dimension_reference_keys(doc, dimension):
    keys = []
    try:
        references = dimension.References
    except Exception:
        references = []
    for reference in references:
        try:
            keys.append(stable_reference_key(doc, reference))
        except Exception:
            pass
    return sorted(set(keys))


def _dimension_reference_element_ids(dimension):
    element_ids = []
    try:
        references = dimension.References
    except Exception:
        references = []
    for reference in references:
        try:
            element_ids.append(get_id_value(reference.ElementId))
        except Exception:
            pass
    return sorted(set(element_ids))


def _find_exact_duplicates(
    doc,
    view,
    proposed_keys,
    proposed_element_ids,
    allow_element_id_fallback=False,
):
    duplicates = []
    collector = (
        DB.FilteredElementCollector(doc, view.Id)
        .OfClass(DB.Dimension)
        .WhereElementIsNotElementType()
    )
    expected = sorted(set(proposed_keys))
    expected_element_ids = sorted(set(proposed_element_ids))
    for dimension in collector:
        key_match = _dimension_reference_keys(doc, dimension) == expected
        # Revit can normalize a Grid's stable representation when the
        # Dimension is created. Grid references are element-level references,
        # so an identical Grid id set is an exact fallback. Face-based Wall and
        # Family references intentionally continue to require stable-key match.
        grid_id_match = bool(
            allow_element_id_fallback
            and _dimension_reference_element_ids(dimension) == expected_element_ids
        )
        if key_match or grid_id_match:
            duplicates.append(get_id_value(dimension.Id))
    return sorted(duplicates)


def _point_data(point):
    return [round(point.X, 9), round(point.Y, 9), round(point.Z, 9)]


def _location_snapshot(element):
    location = getattr(element, "Location", None)
    if isinstance(location, DB.LocationPoint):
        return {"kind": "point", "point": _point_data(location.Point)}
    if isinstance(location, DB.LocationCurve):
        curve = location.Curve
        return {
            "kind": "curve",
            "start": _point_data(curve.GetEndPoint(0)),
            "end": _point_data(curve.GetEndPoint(1)),
        }
    return {"kind": "untracked"}


def _source_snapshot(elements):
    return dict(
        (str(get_id_value(element.Id)), _location_snapshot(element))
        for element in elements
    )


def _coordinates_changed(before, after):
    if before.get("kind") != after.get("kind"):
        return True
    if before.get("kind") == "untracked":
        return False
    before_values = []
    after_values = []
    for key in ("point", "start", "end"):
        before_values.extend(before.get(key, []))
        after_values.extend(after.get(key, []))
    if len(before_values) != len(after_values):
        return True
    return any(
        abs(float(first) - float(second)) > MOVEMENT_TOLERANCE_FEET
        for first, second in zip(before_values, after_values)
    )


def _moved_element_ids(before, after):
    moved = []
    for element_id, before_value in before.items():
        after_value = after.get(element_id, {"kind": "missing"})
        if _coordinates_changed(before_value, after_value):
            moved.append(int(element_id))
    return sorted(moved)


def _intervals(prepared):
    origin = prepared["targets"][0][1]
    direction = prepared["direction"]
    positions = sorted(
        [dot_product(target[1] - origin, direction) for target in prepared["targets"]]
    )
    gaps = []
    for index in range(1, len(positions)):
        gap = positions[index] - positions[index - 1]
        gaps.append(gap)
    millimeters = [
        round(DB.UnitUtils.ConvertFromInternalUnits(value, DB.UnitTypeId.Millimeters), 3)
        for value in gaps
    ]
    unequal = False
    if len(gaps) > 1:
        unequal = (max(gaps) - min(gaps)) > ZERO_GAP_TOLERANCE_FEET
    return gaps, millimeters, unequal


def _audit_path():
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(appdata, "pyRevit", "P13", "audit", "ai_auto_dimension.jsonl")


def _write_audit(record):
    try:
        path = _audit_path()
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(path, "a") as audit_file:
            audit_file.write(json.dumps(record, sort_keys=True) + "\n")
        return True, path
    except Exception:
        return False, ""


def _create_dimension_without_learning(doc, view, prepared):
    references = DB.ReferenceArray()
    for reference, point, side, element in prepared["targets"]:
        references.Append(reference)
    type_id = int(prepared["recommendation"]["dimension_type_id"])
    dimension_type = doc.GetElement(make_element_id(type_id))
    with revit.Transaction("P13 AI Create Verified Dimension"):
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
    return dimension, {
        "dimension_id": get_id_value(dimension.Id),
        "dimension_type_id": type_id,
        "dimension_type_name": safe_name(dimension_type),
        "reference_count": prepared["reference_count"],
        "resolved_direction": prepared["resolved_direction"],
        "equality_constraint_applied": False,
        "source_elements_moved_by_p13": False,
    }


def prepare(doc, uidoc, payload):
    if not doc or not doc.ActiveView:
        raise ValueError("No active Revit view is available.")
    view = doc.ActiveView
    if not _is_plan_view(view):
        raise ValueError("P13 AI Auto Dimension currently supports plan views only.")
    elements, invalid = _resolve_elements(doc, uidoc, payload.get("element_ids") or [])
    if len(elements) < 2:
        raise ValueError("Select or provide at least two valid elements.")

    prepared_dimension = prepare_auto_dimension(
        doc,
        view,
        elements,
        payload.get("direction") or "auto",
        payload.get("reference_side") or "auto",
        payload.get("offset_mm", 1000.0),
        payload.get("dimension_type_id"),
    )
    proposed_keys = [
        stable_reference_key(doc, target[0])
        for target in prepared_dimension["targets"]
    ]
    target_element_ids = [
        get_id_value(target[3].Id)
        for target in prepared_dimension["targets"]
    ]
    all_targets_are_grids = all(
        isinstance(target[3], DB.Grid)
        for target in prepared_dimension["targets"]
    )
    duplicates = _find_exact_duplicates(
        doc,
        view,
        proposed_keys,
        target_element_ids,
        all_targets_are_grids,
    )
    gaps, intervals_mm, unequal = _intervals(prepared_dimension)
    zero_gap_count = len([gap for gap in gaps if abs(gap) <= ZERO_GAP_TOLERANCE_FEET])
    skip_duplicates = bool(payload.get("skip_duplicates", True))
    return {
        "doc": doc,
        "view": view,
        "elements": elements,
        "invalid_element_ids": invalid,
        "dimension": prepared_dimension,
        "duplicate_dimension_ids": duplicates,
        "skip_duplicates": skip_duplicates,
        "intervals_mm": intervals_mm,
        "has_unequal_spacing": unequal,
        "zero_gap_count": zero_gap_count,
        "source_snapshot": _source_snapshot(elements),
    }


def preview_to_data(prepared):
    dimension_data = dimension_preview_to_data(prepared["dimension"])
    duplicates = prepared["duplicate_dimension_ids"]
    zero_gap_count = prepared["zero_gap_count"]
    will_skip = bool(duplicates and prepared["skip_duplicates"])
    safe_to_apply = bool(dimension_data.get("safe_to_apply")) and zero_gap_count == 0
    action = "skip_existing" if will_skip else "create_dimension"
    if duplicates and not prepared["skip_duplicates"]:
        safe_to_apply = False
        action = "blocked_duplicate"
    if zero_gap_count:
        action = "blocked_coincident_references"

    recommendation = dimension_data["recommended_dimension_type"]
    plan = [
        {
            "step": 1,
            "action": "inspect_context",
            "detail": "Use the active plan view and the selected or supplied elements.",
        },
        {
            "step": 2,
            "action": "resolve_references",
            "detail": "Use {} stable references in {} order.".format(
                dimension_data["reference_count"],
                dimension_data["resolved_direction"],
            ),
        },
        {
            "step": 3,
            "action": "select_style",
            "detail": "Use DimensionType '{}' from {}.".format(
                recommendation.get("name") or recommendation.get("dimension_type_id"),
                recommendation.get("source") or "project evidence",
            ),
        },
        {
            "step": 4,
            "action": action,
            "detail": "Do not create EQ constraints and do not move source elements.",
        },
        {
            "step": 5,
            "action": "verify",
            "detail": "Verify the dimension, equality state, references, and source locations.",
        },
    ]
    dimension_data.update(
        {
            "engine": "P13 AI Auto Dimension Plan",
            "engine_version": 1,
            "safe_to_apply": safe_to_apply,
            "planned_action": action,
            "plan": plan,
            "duplicate_dimension_ids": duplicates,
            "skip_duplicates": prepared["skip_duplicates"],
            "intervals_mm": prepared["intervals_mm"],
            "has_unequal_spacing": prepared["has_unequal_spacing"],
            "unequal_spacing_policy": "Preserve every measured interval; never apply EQ.",
            "zero_gap_count": zero_gap_count,
            "invalid_element_ids": prepared["invalid_element_ids"],
            "verification_checks": [
                "dimension_created_or_existing_duplicate_confirmed",
                "equality_constraint_is_false",
                "reference_count_matches_preview",
                "source_element_locations_unchanged",
            ],
        }
    )
    return dimension_data


def apply(doc, uidoc, payload, prepared):
    duplicates = prepared["duplicate_dimension_ids"]
    if duplicates and prepared["skip_duplicates"]:
        result = {
            "status": "success",
            "workflow_stage": "verified",
            "result": "no_change",
            "reason": "An exact dimension already exists in the active view.",
            "existing_dimension_ids": duplicates,
            "source_elements_moved_by_p13": False,
            "verification": {
                "passed": True,
                "duplicate_confirmed": True,
                "model_write_performed": False,
            },
        }
        audit_written, audit_path = _write_audit(
            {
                "timestamp_utc": datetime.datetime.utcnow().isoformat() + "Z",
                "operation": "ai_auto_dimension_plan",
                "result": "no_change",
                "view_id": get_id_value(prepared["view"].Id),
                "existing_dimension_ids": duplicates,
            }
        )
        result["audit_written"] = audit_written
        result["audit_path"] = audit_path
        return result

    before = prepared["source_snapshot"]
    group = DB.TransactionGroup(doc, "P13 AI Auto Dimension Plan")
    group.Start()
    try:
        dimension, created = _create_dimension_without_learning(
            doc,
            prepared["view"],
            prepared["dimension"],
        )
        if not dimension:
            raise ValueError("The created dimension could not be verified.")
        equality_applied = bool(getattr(dimension, "AreSegmentsEqual", False))
        actual_reference_count = len(_dimension_reference_keys(doc, dimension))
        after = _source_snapshot(prepared["elements"])
        moved_ids = _moved_element_ids(before, after)
        reference_matches = actual_reference_count == prepared["dimension"]["reference_count"]
        if equality_applied or moved_ids or not reference_matches:
            group.RollBack()
            raise ValueError(
                "Verification failed; the complete operation was rolled back. "
                "equality_applied={}, moved_element_ids={}, reference_matches={}.".format(
                    equality_applied,
                    moved_ids,
                    reference_matches,
                )
            )
        group.Assimilate()
    except Exception:
        try:
            if group.GetStatus() == DB.TransactionStatus.Started:
                group.RollBack()
        except Exception:
            pass
        raise

    learning_updated = remember_accepted_type(
        doc,
        prepared["view"],
        prepared["dimension"]["categories"],
        prepared["dimension"]["resolved_direction"],
        created["dimension_type_id"],
    )

    result = dict(created)
    result.update(
        {
            "status": "success",
            "workflow_stage": "verified",
            "result": "dimension_created",
            "has_unequal_spacing": prepared["has_unequal_spacing"],
            "intervals_mm": prepared["intervals_mm"],
            "learning_updated": learning_updated,
            "verification": {
                "passed": True,
                "dimension_exists": True,
                "equality_constraint_is_false": True,
                "reference_count_matches_preview": True,
                "source_element_locations_unchanged": True,
                "moved_element_ids": [],
            },
        }
    )
    audit_written, audit_path = _write_audit(
        {
            "timestamp_utc": datetime.datetime.utcnow().isoformat() + "Z",
            "operation": "ai_auto_dimension_plan",
            "result": "dimension_created",
            "document_title": str(doc.Title or ""),
            "view_id": get_id_value(prepared["view"].Id),
            "view_name": str(prepared["view"].Name or ""),
            "dimension_id": created["dimension_id"],
            "dimension_type_id": created["dimension_type_id"],
            "source_element_ids": prepared["dimension"]["element_ids"],
            "intervals_mm": prepared["intervals_mm"],
            "verification_passed": True,
        }
    )
    result["audit_written"] = audit_written
    result["audit_path"] = audit_path
    return result
