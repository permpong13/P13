# -*- coding: utf-8 -*-
from __future__ import print_function

import logging

from pyrevit import routes, DB

from p13_grid_bubbles import (
    VALID_ACTIONS,
    expand_grid_elements,
    get_id_value,
    process_grids,
)
from p13_mcp import API_NAME, API_VERSION
from p13_mcp.security import (
    ensure_config,
    is_authorized,
    parse_request_data,
    write_route_diagnostic,
)
from p13_dimension_intelligence import make_element_id


logger = logging.getLogger(__name__)


def make_error(message, status=400):
    return routes.make_response(
        data={"status": "error", "error": message},
        status=status,
    )


def require_authorized_data(request, config):
    try:
        data = parse_request_data(request)
    except Exception:
        return None, make_error("Request body must contain valid JSON.", 400)
    if not is_authorized(data, config):
        return None, make_error("Unauthorized P13 MCP request.", 401)
    return data, None


def safe_name(element):
    try:
        return element.Name
    except Exception:
        return ""


def element_to_data(doc, element):
    category = element.Category
    category_name = category.Name if category else ""
    category_id = get_id_value(category.Id) if category else None
    type_id = None
    try:
        raw_type_id = element.GetTypeId()
        if raw_type_id and raw_type_id != DB.ElementId.InvalidElementId:
            type_id = get_id_value(raw_type_id)
    except Exception:
        pass

    return {
        "element_id": get_id_value(element.Id),
        "unique_id": element.UniqueId,
        "name": safe_name(element),
        "class_name": element.GetType().Name,
        "category": category_name,
        "category_id": category_id,
        "type_id": type_id,
    }


def register_routes(api):
    config = ensure_config()

    @api.route("/status/", methods=["GET"])
    def status(doc):
        return routes.make_response(
            data={
                "status": "active",
                "api_name": API_NAME,
                "api_version": API_VERSION,
                "document_open": bool(doc),
            }
        )

    @api.route("/document_info/", methods=["POST"])
    def document_info(doc, request):
        data, error_response = require_authorized_data(request, config)
        if error_response is not None:
            return error_response
        if not doc:
            return make_error("No active Revit document.", 409)

        return routes.make_response(
            data={
                "status": "success",
                "title": doc.Title if config.get("share_document_title") else None,
                "path": doc.PathName if config.get("share_document_path") else None,
                "privacy": {
                    "document_title_shared": bool(config.get("share_document_title")),
                    "document_path_shared": bool(config.get("share_document_path")),
                },
                "is_family_document": doc.IsFamilyDocument,
                "is_workshared": doc.IsWorkshared,
                "is_modified": doc.IsModified,
                "active_view_id": get_id_value(doc.ActiveView.Id),
                "active_view_name": safe_name(doc.ActiveView),
            }
        )

    @api.route("/active_view/", methods=["POST"])
    def active_view(doc, request):
        data, error_response = require_authorized_data(request, config)
        if error_response is not None:
            return error_response
        if not doc or not doc.ActiveView:
            return make_error("No active Revit view.", 409)

        active = doc.ActiveView
        return routes.make_response(
            data={
                "status": "success",
                "view_id": get_id_value(active.Id),
                "name": safe_name(active),
                "view_type": str(active.ViewType),
                "scale": active.Scale,
                "is_template": active.IsTemplate,
                "crop_box_active": getattr(active, "CropBoxActive", False),
                "detail_level": str(getattr(active, "DetailLevel", "")),
            }
        )

    @api.route("/selected_elements/", methods=["POST"])
    def selected_elements(doc, uidoc, request):
        data, error_response = require_authorized_data(request, config)
        if error_response is not None:
            return error_response
        if not doc or not uidoc:
            return make_error("No active Revit UI document.", 409)

        try:
            limit = max(1, min(int(data.get("limit", 500)), 5000))
        except Exception:
            return make_error("limit must be an integer between 1 and 5000.")

        element_ids = list(uidoc.Selection.GetElementIds())
        elements = []
        for element_id in element_ids[:limit]:
            element = doc.GetElement(element_id)
            if element:
                elements.append(element_to_data(doc, element))

        return routes.make_response(
            data={
                "status": "success",
                "total_selected": len(element_ids),
                "returned_elements": len(elements),
                "truncated": len(element_ids) > limit,
                "elements": elements,
            }
        )

    @api.route("/grid_bubbles/", methods=["POST"])
    def grid_bubbles(doc, uidoc, request):
        data, error_response = require_authorized_data(request, config)
        if error_response is not None:
            return error_response
        if not doc or not uidoc or not doc.ActiveView:
            return make_error("No active Revit UI document or view.", 409)
        if data.get("confirm_write") is not True:
            return make_error(
                "Write confirmation is required. Set confirm_write to true.",
                409,
            )

        action = str(data.get("action") or "")
        if action not in VALID_ACTIONS:
            return make_error(
                "action must be one of: {}".format(", ".join(VALID_ACTIONS))
            )

        raw_ids = data.get("element_ids") or []
        if not isinstance(raw_ids, list) or not raw_ids:
            return make_error("element_ids must be a non-empty list of integers.")

        elements = []
        invalid_ids = []
        for raw_id in raw_ids:
            try:
                element = doc.GetElement(make_element_id(raw_id))
            except Exception:
                element = None
            if element:
                elements.append(element)
            else:
                invalid_ids.append(raw_id)

        grids = expand_grid_elements(doc, elements)
        if not grids:
            return make_error("No valid grids were found in element_ids.")

        try:
            result = process_grids(
                doc,
                doc.ActiveView,
                grids,
                action,
                bool(data.get("orient_by_view", True)),
                "P13 MCP Manage Grid Bubbles",
            )
        except Exception as error:
            write_route_diagnostic("P13 MCP grid bubble operation failed", error)
            return make_error(str(error), 500)

        result["status"] = "success"
        result["processed_grid_ids"] = [get_id_value(grid.Id) for grid in grids]
        result["invalid_element_ids"] = invalid_ids
        return routes.make_response(data=result)

    from p13_mcp.intelligence_routes import register_intelligence_routes
    register_intelligence_routes(
        api,
        config,
        require_authorized_data,
        make_error,
        element_to_data,
    )

    from p13_mcp.hot_routes import register_hot_routes
    register_hot_routes(
        api,
        config,
        require_authorized_data,
        make_error,
    )

    return None
