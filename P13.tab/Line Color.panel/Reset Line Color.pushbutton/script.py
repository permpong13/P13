# -*- coding: utf-8 -*-
"""Clear line color overrides from elements in the active view."""

from pyrevit import DB, revit
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException


def get_target_elements():
    elements = list(revit.get_selection())
    if elements:
        return elements
    try:
        references = revit.uidoc.Selection.PickObjects(
            ObjectType.Element,
            "Select elements to reset line color, then click Finish",
        )
        return [revit.doc.GetElement(reference.ElementId) for reference in references]
    except OperationCanceledException:
        return []


elements = get_target_elements()
if elements:
    empty_style = DB.OverrideGraphicSettings()
    with revit.Transaction("Reset Line Color"):
        for element in elements:
            revit.active_view.SetElementOverrides(element.Id, empty_style)
