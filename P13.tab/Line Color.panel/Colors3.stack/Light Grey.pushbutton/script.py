# -*- coding: utf-8 -*-
from pyrevit import revit, DB, forms
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

__title__ = "."
__doc__ = 'Quicker override Projection Line Color of Elements.'
__author__ = "David Vadkerti"

def setProjLines(r, g, b, strong=False):
    try:
        # 1. ตรวจสอบว่ามีการเลือก Element ไว้ก่อนรันสคริปต์หรือไม่ (Pre-selection)
        selection = revit.get_selection()
        elements = list(selection)
        
        # 2. ถ้ายกเลิกการเลือกไว้ (ไม่มีอะไรถูกเลือก) ให้เปิดโหมดเลือกวัตถุ (Post-selection)
        if not elements:
            try:
                # แสดงหน้าต่างให้เลือกวัตถุ
                references = revit.uidoc.Selection.PickObjects(ObjectType.Element, "Select elements to override line color, then click Finish")
                # แปลงค่า Reference ที่ได้มาเป็น Element
                elements = [revit.doc.GetElement(ref) for ref in references]
            except OperationCanceledException:
                # หากผู้ใช้กด ESC หรือ Cancel ให้จบการทำงานเงียบๆ ไม่ต้องแสดง Error
                return
        
        # 3. นำ Element ที่ได้ (ไม่ว่าจะเลือกก่อนหรือหลัง) ไปเปลี่ยนสี
        if elements:
            with revit.Transaction('Line Color'):
                src_style = DB.OverrideGraphicSettings()
                color = DB.Color(r, g, b)
                
                # ฟังก์ชันเดิมทั้งหมดถูกรักษาไว้
                src_style.SetProjectionLineColor(color)
                src_style.SetCutLineColor(color)
                src_style.SetCutForegroundPatternColor(color)
                src_style.SetCutBackgroundPatternColor(color)

                if strong:
                    src_style.SetSurfaceBackgroundPatternColor(color)
                    src_style.SetCutBackgroundPatternColor(color)
                    src_style.SetSurfaceBackgroundPatternId(DB.ElementId(4))
                    src_style.SetCutBackgroundPatternId(DB.ElementId(4))

                for element in elements:
                    revit.active_view.SetElementOverrides(element.Id, src_style)
                    
    except Exception as e:
        print("Error: " + str(e))

# เรียกใช้งานฟังก์ชันด้วยรหัสสี
setProjLines(192,192,192)