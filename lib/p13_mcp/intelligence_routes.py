# -*- coding: utf-8 -*-
from __future__ import print_function

import logging

from pyrevit import routes, DB

from p13_dimension_intelligence import (
    create_auto_dimension,
    get_id_value,
    make_element_id,
    list_dimension_types,
    prepare_auto_dimension,
    preview_to_data,
    recommend_dimension_type,
    safe_name,
    summarize_dimension_evidence,
)
from p13_mcp.security import write_route_diagnostic
from p13_view_annotation_sync import (
    apply_annotation_sync,
    prepare_annotation_sync,
    preview_to_data as annotation_sync_preview_to_data,
)


logger = logging.getLogger(__name__)


def get_parameter_value(parameter):
    try:
        storage_type = parameter.StorageType
        if storage_type == DB.StorageType.String:
            return parameter.AsString()
        if storage_type == DB.StorageType.Integer:
            return parameter.AsInteger()
        if storage_type == DB.StorageType.Double:
            return {
                "display_value": parameter.AsValueString(),
                "internal_value": parameter.AsDouble(),
            }
        if storage_type == DB.StorageType.ElementId:
            element_id = parameter.AsElementId()
            return get_id_value(element_id)
        return parameter.AsValueString()
    except Exception:
        return None


def resolve_elements(doc, uidoc, raw_ids):
    ids = raw_ids
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


def element_categories(elements):
    result = set()
    for element in elements:
        try:
            if element.Category:
                result.add(element.Category.Name)
        except Exception:
            pass
    return sorted(result)


def register_intelligence_routes(
    api,
    config,
    require_authorized_data,
    make_error,
    element_to_data,
):
    @api.route("/model_summary/", methods=["POST"])
    def model_summary(doc, request):
        data, error = require_authorized_data(request, config)
        if error is not None:
            return error
        if not doc:
            return make_error("No active Revit document.", 409)
        try:
            limit = max(1, min(int(data.get("limit", 100000)), 500000))
        except Exception:
            return make_error("limit must be an integer between 1 and 500000.")

        counts = {}
        total = 0
        collector = DB.FilteredElementCollector(doc).WhereElementIsNotElementType()
        for element in collector:
            if total >= limit:
                break
            total += 1
            category = "Uncategorized"
            try:
                if element.Category:
                    category = element.Category.Name
            except Exception:
                pass
            counts[category] = counts.get(category, 0) + 1
        categories = [
            {"category": name, "element_count": counts[name]}
            for name in sorted(counts, key=lambda key: (-counts[key], key))
        ]
        return routes.make_response(
            data={
                "status": "success",
                "scanned_element_count": total,
                "scan_limit": limit,
                "truncated": total >= limit,
                "category_counts": categories,
            }
        )

    @api.route("/levels/", methods=["POST"])
    def levels(doc, request):
        data, error = require_authorized_data(request, config)
        if error is not None:
            return error
        if not doc:
            return make_error("No active Revit document.", 409)
        result = []
        for level in DB.FilteredElementCollector(doc).OfClass(DB.Level):
            result.append(
                {
                    "level_id": get_id_value(level.Id),
                    "name": safe_name(level),
                    "elevation_internal_feet": level.Elevation,
                }
            )
        result.sort(key=lambda item: item["elevation_internal_feet"])
        return routes.make_response(data={"status": "success", "levels": result})

    @api.route("/views/", methods=["POST"])
    def views(doc, request):
        data, error = require_authorized_data(request, config)
        if error is not None:
            return error
        if not doc:
            return make_error("No active Revit document.", 409)
        include_templates = bool(data.get("include_templates", False))
        result = []
        for view in DB.FilteredElementCollector(doc).OfClass(DB.View):
            if view.IsTemplate and not include_templates:
                continue
            result.append(
                {
                    "view_id": get_id_value(view.Id),
                    "name": safe_name(view),
                    "view_type": str(view.ViewType),
                    "scale": int(getattr(view, "Scale", 0) or 0),
                    "is_template": bool(view.IsTemplate),
                }
            )
        result.sort(key=lambda item: (item["view_type"], item["name"]))
        return routes.make_response(data={"status": "success", "views": result})

    @api.route("/active_view_elements/", methods=["POST"])
    def active_view_elements(doc, request):
        data, error = require_authorized_data(request, config)
        if error is not None:
            return error
        if not doc or not doc.ActiveView:
            return make_error("No active Revit view.", 409)
        try:
            limit = max(1, min(int(data.get("limit", 1000)), 10000))
        except Exception:
            return make_error("limit must be an integer between 1 and 10000.")
        requested_category = str(data.get("category") or "").strip().lower()
        result = []
        total_matching = 0
        collector = (
            DB.FilteredElementCollector(doc, doc.ActiveView.Id)
            .WhereElementIsNotElementType()
        )
        for element in collector:
            category = ""
            try:
                category = element.Category.Name if element.Category else ""
            except Exception:
                pass
            if requested_category and category.lower() != requested_category:
                continue
            total_matching += 1
            if len(result) < limit:
                result.append(element_to_data(doc, element))
        return routes.make_response(
            data={
                "status": "success",
                "total_matching": total_matching,
                "returned_elements": len(result),
                "truncated": total_matching > limit,
                "elements": result,
            }
        )

    @api.route("/element_parameters/", methods=["POST"])
    def element_parameters(doc, request):
        data, error = require_authorized_data(request, config)
        if error is not None:
            return error
        if not doc:
            return make_error("No active Revit document.", 409)
        try:
            element = doc.GetElement(make_element_id(data.get("element_id")))
        except Exception:
            element = None
        if not element:
            return make_error("element_id does not identify an element.")
        parameters = []
        for parameter in element.Parameters:
            try:
                definition = parameter.Definition
                name = definition.Name
            except Exception:
                name = ""
            parameters.append(
                {
                    "name": name,
                    "parameter_id": get_id_value(parameter.Id),
                    "storage_type": str(parameter.StorageType),
                    "is_read_only": bool(parameter.IsReadOnly),
                    "value": get_parameter_value(parameter),
                }
            )
        parameters.sort(key=lambda item: item["name"])
        type_element = None
        try:
            type_element = doc.GetElement(element.GetTypeId())
        except Exception:
            pass
        return routes.make_response(
            data={
                "status": "success",
                "element": element_to_data(doc, element),
                "type_name": safe_name(type_element) if type_element else "",
                "parameters": parameters,
            }
        )

    @api.route("/dimension_types/", methods=["POST"])
    def dimension_types(doc, request):
        data, error = require_authorized_data(request, config)
        if error is not None:
            return error
        if not doc:
            return make_error("No active Revit document.", 409)
        return routes.make_response(
            data={"status": "success", "dimension_types": list_dimension_types(doc)}
        )

    @api.route("/dimension_patterns/", methods=["POST"])
    def dimension_patterns(doc, request):
        data, error = require_authorized_data(request, config)
        if error is not None:
            return error
        if not doc:
            return make_error("No active Revit document.", 409)
        try:
            limit = max(1, min(int(data.get("limit", 5000)), 20000))
            result = summarize_dimension_evidence(doc, doc.ActiveView, limit)
        except Exception as exception:
            write_route_diagnostic("P13 dimension pattern analysis failed", exception)
            return make_error(str(exception), 500)
        result["status"] = "success"
        return routes.make_response(data=result)

    @api.route("/recommend_dimension/", methods=["POST"])
    def recommend_dimension(doc, uidoc, request):
        data, error = require_authorized_data(request, config)
        if error is not None:
            return error
        if not doc or not doc.ActiveView:
            return make_error("No active Revit view.", 409)
        try:
            elements, invalid = resolve_elements(doc, uidoc, data.get("element_ids") or [])
            categories = element_categories(elements)
            requested_type_id = data.get("dimension_type_id")
            recommendation = recommend_dimension_type(
                doc,
                doc.ActiveView,
                categories,
                str(data.get("direction") or "auto").lower(),
                requested_type_id,
            )
        except Exception as exception:
            return make_error(str(exception))
        return routes.make_response(
            data={
                "status": "success",
                "reference_categories": categories,
                "invalid_element_ids": invalid,
                "recommendation": recommendation,
            }
        )

    @api.route("/preview_auto_dimension/", methods=["POST"])
    def preview_auto_dimension(doc, uidoc, request):
        data, error = require_authorized_data(request, config)
        if error is not None:
            return error
        if not doc or not doc.ActiveView:
            return make_error("No active Revit view.", 409)
        try:
            elements, invalid = resolve_elements(doc, uidoc, data.get("element_ids") or [])
            if len(elements) < 2:
                return make_error("Select or provide at least two valid elements.")
            prepared = prepare_auto_dimension(
                doc,
                doc.ActiveView,
                elements,
                data.get("direction") or "auto",
                data.get("reference_side") or "auto",
                data.get("offset_mm", 1000.0),
                data.get("dimension_type_id"),
            )
            result = preview_to_data(prepared)
            result["invalid_element_ids"] = invalid
            result["status"] = "success"
            return routes.make_response(data=result)
        except Exception as exception:
            write_route_diagnostic("P13 auto dimension preview failed", exception)
            return make_error(str(exception))

    @api.route("/apply_auto_dimension/", methods=["POST"])
    def apply_auto_dimension(doc, uidoc, request):
        data, error = require_authorized_data(request, config)
        if error is not None:
            return error
        if not doc or not doc.ActiveView:
            return make_error("No active Revit view.", 409)
        if data.get("confirm_write") is not True:
            return make_error(
                "Write confirmation is required. Set confirm_write to true.",
                409,
            )
        preview_signature = str(data.get("preview_signature") or "")
        if not preview_signature:
            return make_error("preview_signature from preview_auto_dimension is required.", 409)
        try:
            elements, invalid = resolve_elements(doc, uidoc, data.get("element_ids") or [])
            if len(elements) < 2:
                return make_error("Select or provide at least two valid elements.")
            prepared = prepare_auto_dimension(
                doc,
                doc.ActiveView,
                elements,
                data.get("direction") or "auto",
                data.get("reference_side") or "auto",
                data.get("offset_mm", 1000.0),
                data.get("dimension_type_id"),
            )
            if prepared["preview_signature"] != preview_signature:
                return make_error(
                    "Preview no longer matches the requested operation. Run preview_auto_dimension again.",
                    409,
                )
            result = create_auto_dimension(doc, doc.ActiveView, prepared)
            result.update(
                {
                    "status": "success",
                    "workflow_stage": "applied",
                    "invalid_element_ids": invalid,
                    "preview_signature": preview_signature,
                }
            )
            return routes.make_response(data=result)
        except Exception as exception:
            write_route_diagnostic("P13 auto dimension apply failed", exception)
            return make_error(str(exception), 500)

    @api.route("/preview_view_annotation_sync/", methods=["POST"])
    def preview_view_annotation_sync(doc, request):
        data, error = require_authorized_data(request, config)
        if error is not None:
            return error
        if not doc:
            return make_error("No active Revit document.", 409)
        try:
            prepared = prepare_annotation_sync(
                doc,
                data.get("source_view_id"),
                data.get("target_view_id"),
                data.get("mode") or "replace",
                bool(data.get("include_tags", True)),
                bool(data.get("include_dimensions", True)),
                bool(data.get("align_target_scale", False)),
            )
            result = annotation_sync_preview_to_data(prepared)
            result["status"] = "success"
            return routes.make_response(data=result)
        except Exception as exception:
            write_route_diagnostic("P13 view annotation sync preview failed", exception)
            return make_error(str(exception))

    @api.route("/apply_view_annotation_sync/", methods=["POST"])
    def apply_view_annotation_sync(doc, request):
        data, error = require_authorized_data(request, config)
        if error is not None:
            return error
        if not doc:
            return make_error("No active Revit document.", 409)
        if data.get("confirm_write") is not True:
            return make_error(
                "Write confirmation is required. Set confirm_write to true.",
                409,
            )
        preview_signature = str(data.get("preview_signature") or "")
        if not preview_signature:
            return make_error(
                "preview_signature from preview_view_annotation_sync is required.",
                409,
            )
        try:
            prepared = prepare_annotation_sync(
                doc,
                data.get("source_view_id"),
                data.get("target_view_id"),
                data.get("mode") or "replace",
                bool(data.get("include_tags", True)),
                bool(data.get("include_dimensions", True)),
                bool(data.get("align_target_scale", False)),
            )
            if prepared["preview_signature"] != preview_signature:
                return make_error(
                    "Preview no longer matches the requested operation. Run preview_view_annotation_sync again.",
                    409,
                )
            if not prepared["source_rows"]:
                return make_error("The source view has no supported tags or dimensions.", 409)
            if prepared["equality_dimensions"]:
                return make_error(
                    "Source equality-constrained dimensions can move model elements and block this operation.",
                    409,
                )
            result = apply_annotation_sync(doc, prepared)
            result["preview_signature"] = preview_signature
            return routes.make_response(data=result)
        except Exception as exception:
            write_route_diagnostic("P13 view annotation sync apply failed", exception)
            return make_error(str(exception), 500)

    return None
