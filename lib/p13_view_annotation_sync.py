# -*- coding: utf-8 -*-
from __future__ import print_function

"""Safe preview/apply workflow for copying tags and dimensions between views."""

import hashlib
import json

from System.Collections.Generic import List
from pyrevit import DB

from p13_dimension_intelligence import get_id_value, make_element_id, safe_name


VALID_MODES = ("replace",)


def resolve_view(doc, view_id):
    try:
        view = doc.GetElement(make_element_id(view_id))
    except Exception:
        view = None
    if not isinstance(view, DB.View) or bool(getattr(view, "IsTemplate", False)):
        raise ValueError("view_id must identify a non-template Revit view.")
    return view


def _owner_matches_view(element, view):
    try:
        owner_id = element.OwnerViewId
        return get_id_value(owner_id) == get_id_value(view.Id)
    except Exception:
        return False


def annotation_kind(element):
    class_name = element.GetType().Name
    if isinstance(element, DB.Dimension) or class_name in (
        "Dimension",
        "LinearDimension",
        "SpotDimension",
        "MultiReferenceAnnotation",
    ):
        return "dimensions"
    if isinstance(element, DB.IndependentTag) or class_name.endswith("Tag"):
        return "tags"
    return ""


def collect_annotations(view, include_tags=True, include_dimensions=True):
    doc = view.Document
    result = []
    collector = DB.FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType()
    for element in collector:
        if not _owner_matches_view(element, view):
            continue
        kind = annotation_kind(element)
        if kind == "tags" and include_tags:
            result.append(element)
        elif kind == "dimensions" and include_dimensions:
            result.append(element)
    return sorted(result, key=lambda item: get_id_value(item.Id))


def has_equality_constraint(element):
    if annotation_kind(element) != "dimensions":
        return False
    for attribute_name in ("AreSegmentsEqual", "IsEquality"):
        try:
            if bool(getattr(element, attribute_name)):
                return True
        except Exception:
            pass
    return False


def _category_name(element):
    try:
        return element.Category.Name if element.Category else ""
    except Exception:
        return ""


def _type_name(doc, element):
    try:
        type_element = doc.GetElement(element.GetTypeId())
        return safe_name(type_element) if type_element else ""
    except Exception:
        return ""


def annotation_data(doc, element):
    type_id = None
    try:
        type_id = get_id_value(element.GetTypeId())
    except Exception:
        pass
    return {
        "element_id": get_id_value(element.Id),
        "unique_id": str(element.UniqueId),
        "kind": annotation_kind(element),
        "category": _category_name(element),
        "class_name": element.GetType().Name,
        "type_id": type_id,
        "type_name": _type_name(doc, element),
        "has_equality_constraint": has_equality_constraint(element),
    }


def _summary(rows):
    groups = {}
    for row in rows:
        key = (
            row["kind"],
            row["category"],
            row["class_name"],
            row["type_id"],
            row["type_name"],
        )
        groups[key] = groups.get(key, 0) + 1
    result = []
    for key, count in groups.items():
        result.append(
            {
                "kind": key[0],
                "category": key[1],
                "class_name": key[2],
                "type_id": key[3],
                "type_name": key[4],
                "count": count,
            }
        )
    return sorted(
        result,
        key=lambda item: (
            item["kind"],
            item["category"],
            item["type_name"],
            item["class_name"],
        ),
    )


def _signature_payload(
    source_view,
    target_view,
    mode,
    include_tags,
    include_dimensions,
    align_target_scale,
    source_rows,
    target_rows,
):
    return {
        "source_view_id": get_id_value(source_view.Id),
        "target_view_id": get_id_value(target_view.Id),
        "mode": mode,
        "include_tags": bool(include_tags),
        "include_dimensions": bool(include_dimensions),
        "align_target_scale": bool(align_target_scale),
        "source_scale": int(getattr(source_view, "Scale", 0) or 0),
        "target_scale": int(getattr(target_view, "Scale", 0) or 0),
        "source": [
            [row["element_id"], row["unique_id"], row["type_id"]]
            for row in source_rows
        ],
        "target": [
            [row["element_id"], row["unique_id"], row["type_id"]]
            for row in target_rows
        ],
    }


def _make_signature(payload):
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def prepare_annotation_sync(
    doc,
    source_view_id,
    target_view_id,
    mode="replace",
    include_tags=True,
    include_dimensions=True,
    align_target_scale=False,
):
    mode = str(mode or "replace").lower()
    if mode not in VALID_MODES:
        raise ValueError("mode must be one of: {}".format(", ".join(VALID_MODES)))
    if not include_tags and not include_dimensions:
        raise ValueError("At least one of include_tags or include_dimensions must be true.")
    source_view = resolve_view(doc, source_view_id)
    target_view = resolve_view(doc, target_view_id)
    if get_id_value(source_view.Id) == get_id_value(target_view.Id):
        raise ValueError("Source and target views must be different.")
    if source_view.ViewType != target_view.ViewType:
        raise ValueError("Source and target views must have the same Revit view type.")
    source_scale = int(getattr(source_view, "Scale", 0) or 0)
    target_scale = int(getattr(target_view, "Scale", 0) or 0)
    if source_scale != target_scale and not align_target_scale:
        raise ValueError(
            "Source and target views must have the same scale, or align_target_scale must be true."
        )

    source_elements = collect_annotations(source_view, include_tags, include_dimensions)
    target_elements = collect_annotations(target_view, include_tags, include_dimensions)
    source_rows = [annotation_data(doc, element) for element in source_elements]
    target_rows = [annotation_data(doc, element) for element in target_elements]
    equality_dimensions = [row for row in source_rows if row["has_equality_constraint"]]
    payload = _signature_payload(
        source_view,
        target_view,
        mode,
        include_tags,
        include_dimensions,
        align_target_scale,
        source_rows,
        target_rows,
    )
    return {
        "source_view": source_view,
        "target_view": target_view,
        "source_elements": source_elements,
        "target_elements": target_elements,
        "source_rows": source_rows,
        "target_rows": target_rows,
        "equality_dimensions": equality_dimensions,
        "mode": mode,
        "include_tags": bool(include_tags),
        "include_dimensions": bool(include_dimensions),
        "align_target_scale": bool(align_target_scale),
        "source_scale": source_scale,
        "target_scale": target_scale,
        "preview_signature": _make_signature(payload),
    }


def preview_to_data(prepared):
    source_rows = prepared["source_rows"]
    target_rows = prepared["target_rows"]
    equality_dimensions = prepared["equality_dimensions"]
    return {
        "workflow_stage": "preview",
        "safe_to_apply": bool(source_rows) and not equality_dimensions,
        "source_view": {
            "view_id": get_id_value(prepared["source_view"].Id),
            "name": safe_name(prepared["source_view"]),
        },
        "target_view": {
            "view_id": get_id_value(prepared["target_view"].Id),
            "name": safe_name(prepared["target_view"]),
        },
        "mode": prepared["mode"],
        "include_tags": prepared["include_tags"],
        "include_dimensions": prepared["include_dimensions"],
        "align_target_scale": prepared["align_target_scale"],
        "source_scale": prepared["source_scale"],
        "target_scale": prepared["target_scale"],
        "target_scale_after_apply": (
            prepared["source_scale"] if prepared["align_target_scale"] else prepared["target_scale"]
        ),
        "source_annotation_count": len(source_rows),
        "target_annotation_count": len(target_rows),
        "source_summary": _summary(source_rows),
        "target_summary": _summary(target_rows),
        "source_element_ids": [row["element_id"] for row in source_rows],
        "target_element_ids_to_replace": [row["element_id"] for row in target_rows],
        "equality_constraint_dimensions": equality_dimensions,
        "preview_signature": prepared["preview_signature"],
        "movement_policy": (
            "Only target view-owned tags and dimensions are replaced. "
            "Model elements are not moved. Source dimensions with equality constraints block apply."
        ),
    }


def apply_annotation_sync(doc, prepared):
    transaction = DB.Transaction(doc, "P13 MCP Sync View Tags and Dimensions")
    transaction.Start()
    try:
        deleted_ids = []
        scale_changed = False
        if prepared["align_target_scale"] and prepared["source_scale"] != prepared["target_scale"]:
            prepared["target_view"].Scale = prepared["source_scale"]
            scale_changed = True

        if prepared["target_elements"]:
            delete_list = List[DB.ElementId]()
            for element in prepared["target_elements"]:
                delete_list.Add(element.Id)
                deleted_ids.append(get_id_value(element.Id))
            doc.Delete(delete_list)

        copy_ids = List[DB.ElementId]()
        for element in prepared["source_elements"]:
            copy_ids.Add(element.Id)
        options = DB.CopyPasteOptions()
        copied = DB.ElementTransformUtils.CopyElements(
            prepared["source_view"],
            copy_ids,
            prepared["target_view"],
            DB.Transform.Identity,
            options,
        )
        copied_ids = [get_id_value(element_id) for element_id in copied]
        transaction.Commit()
    except Exception:
        if transaction.GetStatus() == DB.TransactionStatus.Started:
            transaction.RollBack()
        raise
    return {
        "workflow_stage": "applied",
        "status": "success",
        "source_view_id": get_id_value(prepared["source_view"].Id),
        "target_view_id": get_id_value(prepared["target_view"].Id),
        "deleted_target_annotation_ids": deleted_ids,
        "copied_annotation_ids": copied_ids,
        "deleted_count": len(deleted_ids),
        "copied_count": len(copied_ids),
        "target_scale_before": prepared["target_scale"],
        "target_scale_after": int(getattr(prepared["target_view"], "Scale", 0) or 0),
        "target_scale_changed": scale_changed,
        "movement_policy": (
            "Only target view-owned tags and dimensions were replaced; model elements were not moved."
        ),
    }
