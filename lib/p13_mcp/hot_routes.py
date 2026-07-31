# -*- coding: utf-8 -*-
from __future__ import print_function

from pyrevit import routes

from p13_mcp.hot_dispatch import (
    apply_write,
    execute_read,
    list_operations,
    preview_write,
)
from p13_mcp.security import write_route_diagnostic


def register_hot_routes(api, config, require_authorized_data, make_error):
    @api.route("/hot_operations/", methods=["POST"])
    def hot_operations(doc, request):
        data, error = require_authorized_data(request, config)
        if error is not None:
            return error
        try:
            return routes.make_response(data=list_operations())
        except Exception as exception:
            write_route_diagnostic("P13 hot-operation listing failed", exception)
            return make_error(str(exception), 500)

    @api.route("/hot_dispatch/", methods=["POST"])
    def hot_dispatch(doc, uidoc, request):
        data, error = require_authorized_data(request, config)
        if error is not None:
            return error
        if not doc:
            return make_error("No active Revit document.", 409)
        action = str(data.get("action") or "execute").lower()
        operation = str(data.get("operation") or "")
        payload = data.get("payload") or {}
        try:
            if action == "execute":
                result = execute_read(doc, uidoc, operation, payload)
            elif action == "preview":
                result = preview_write(doc, uidoc, operation, payload)
            elif action == "apply":
                if data.get("confirm_write") is not True:
                    return make_error(
                        "Write confirmation is required. Set confirm_write to true.",
                        409,
                    )
                if not data.get("preview_signature"):
                    return make_error("preview_signature is required for apply.", 409)
                result = apply_write(
                    doc,
                    uidoc,
                    operation,
                    payload,
                    data.get("preview_signature"),
                )
            else:
                return make_error("action must be execute, preview, or apply.")
            return routes.make_response(data=result)
        except Exception as exception:
            write_route_diagnostic("P13 hot operation failed", exception)
            status = 409 if action == "apply" else 400
            return make_error(str(exception), status)
