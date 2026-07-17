# -*- coding: utf-8 -*-
"""Apply any selected line color to elements in the active view."""

from pyrevit import DB, revit
from pyrevit.framework import Forms
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException


def get_target_elements():
    elements = list(revit.get_selection())
    if elements:
        return elements
    try:
        references = revit.uidoc.Selection.PickObjects(
            ObjectType.Element,
            "Select elements to change line color, then click Finish",
        )
        return [revit.doc.GetElement(reference.ElementId) for reference in references]
    except OperationCanceledException:
        return []


def choose_color():
    dialog = Forms.ColorDialog()
    dialog.AllowFullOpen = True
    dialog.FullOpen = True
    if dialog.ShowDialog() != Forms.DialogResult.OK:
        return None
    return DB.Color(dialog.Color.R, dialog.Color.G, dialog.Color.B)


def apply_line_color(elements, color):
    style = DB.OverrideGraphicSettings()
    style.SetProjectionLineColor(color)
    style.SetCutLineColor(color)
    style.SetCutForegroundPatternColor(color)
    style.SetCutBackgroundPatternColor(color)
    with revit.Transaction("Set Line Color"):
        for element in elements:
            revit.active_view.SetElementOverrides(element.Id, style)


elements = get_target_elements()
if elements:
    color = choose_color()
    if color is not None:
        apply_line_color(elements, color)
