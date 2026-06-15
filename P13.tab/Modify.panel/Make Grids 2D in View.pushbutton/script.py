# -*- coding: utf-8 -*-
from Autodesk.Revit.DB import *
from pyrevit import revit

doc = revit.doc
view = revit.active_view

# ดึง Grid ทั้งหมดในวิวปัจจุบัน
grids = FilteredElementCollector(doc, view.Id).OfClass(Grid).ToElements()

with revit.Transaction("Change Grids to 2D"):
    for grid in grids:
        # เปลี่ยน Datum Mode เป็น 2D สำหรับวิวนั้นๆ
        grid.SetDatumExtentType(DatumEnds.End0, view, DatumExtentType.ViewSpecific)
        grid.SetDatumExtentType(DatumEnds.End1, view, DatumExtentType.ViewSpecific)
