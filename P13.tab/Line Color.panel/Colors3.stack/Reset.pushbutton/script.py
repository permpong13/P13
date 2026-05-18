# -*- coding: utf-8 -*-
from pyrevit import revit, DB, forms
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

__title__ = "."
__doc__ = 'Quicker override Projection Line Color of Elements.'
__author__ = "David Vadkerti"

# ไม่ต้องเรียกใช้ฟังก์ชัน setProjLines เพราะเป้าหมายคือการล้างค่า (Clear Overrides)

try:
    # 1. ตรวจสอบว่ามีการเลือก Element ไว้ก่อนรันสคริปต์หรือไม่ (Pre-selection)
    selection = revit.get_selection()
    elements = list(selection)
    
    # 2. ถ้ายกเลิกการเลือกไว้ (ไม่มีอะไรถูกเลือก) ให้เปิดโหมดเลือกวัตถุ (Post-selection)
    if not elements:
        try:
            # แสดงหน้าต่างให้เลือกวัตถุ
            references = revit.uidoc.Selection.PickObjects(ObjectType.Element, "Select elements to clear overrides, then click Finish")
            # แปลงค่า Reference ที่ได้มาเป็น Element
            elements = [revit.doc.GetElement(ref) for ref in references]
        except OperationCanceledException:
            # หากผู้ใช้กด ESC หรือ Cancel ให้จบการทำงานเงียบๆ ไม่ต้องแสดง Error
            pass
    
    # 3. นำ Element ที่ได้ไปลบการตั้งค่าสี (Clear overrides)
    if elements:
        with revit.Transaction('Clear Line Color'):
            # สร้างการตั้งค่ากราฟิกแบบเริ่มต้น (ค่าว่างๆ ที่ไม่มีการ Override)
            src_style = DB.OverrideGraphicSettings()
            
            # นำค่าว่างๆ กลับไปทับ Element ที่เลือก เพื่อเป็นการล้างค่า
            for element in elements:
                revit.active_view.SetElementOverrides(element.Id, src_style)
                
except Exception as e:
    print("Error: " + str(e))