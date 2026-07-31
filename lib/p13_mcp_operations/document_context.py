# -*- coding: utf-8 -*-
from __future__ import print_function

from p13_dimension_intelligence import get_id_value, safe_name


def execute(doc, uidoc, payload):
    active_view = doc.ActiveView if doc else None
    selected_ids = []
    if uidoc:
        selected_ids = [get_id_value(item) for item in uidoc.Selection.GetElementIds()]
    return {
        "document": {
            "title": str(doc.Title or "") if doc else "",
            "path": str(doc.PathName or "") if doc else "",
            "is_modified": bool(doc.IsModified) if doc else False,
        },
        "active_view": {
            "view_id": get_id_value(active_view.Id) if active_view else None,
            "name": safe_name(active_view) if active_view else "",
            "view_type": str(active_view.ViewType) if active_view else "",
            "scale": int(active_view.Scale) if active_view else 0,
        },
        "selection": {
            "count": len(selected_ids),
            "element_ids": selected_ids,
        },
        "read_only": True,
    }
