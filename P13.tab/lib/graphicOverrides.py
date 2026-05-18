# -*- coding: utf-8 -*- 
from pyrevit import revit, DB, forms
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

# overrides lines and patterns in view
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
                # หากผู้ใช้กด ESC หรือ Cancel ให้จบการทำงานเงียบๆ
                return
        
        # 3. นำ Element ที่ได้ไปเปลี่ยนสีตามฟังก์ชันต้นฉบับทั้งหมด
        if elements:
            with revit.Transaction('Line Color'):
                src_style = DB.OverrideGraphicSettings()
                
                # constructing RGB value from list
                color = DB.Color(r, g, b)
                src_style.SetProjectionLineColor(color)
                src_style.SetCutLineColor(color)
                src_style.SetCutForegroundPatternColor(color)
                src_style.SetCutBackgroundPatternColor(color)

                if strong:
                    src_style.SetSurfaceBackgroundPatternColor(color)
                    src_style.SetCutBackgroundPatternColor(color)

                    # 4 is ElementId of Solid Fill Pattern
                    src_style.SetSurfaceBackgroundPatternId(DB.ElementId(4))
                    src_style.SetCutBackgroundPatternId(DB.ElementId(4))

                for element in elements:
                    revit.active_view.SetElementOverrides(element.Id, src_style)
    except Exception as e:
        print("Error: " + str(e))