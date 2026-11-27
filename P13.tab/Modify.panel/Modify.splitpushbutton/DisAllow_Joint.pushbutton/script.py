# -*- coding: utf-8 -*-
__title__ = 'DisAllow\nBeam-Joint'
__author__ = 'เพิ่มพงษ์ ทวีกุล'
__doc__ = 'Disallow หัว (Start)", "Disallow ท้าย (End'

from pyrevit import revit, DB, script, forms

# รับ options จากผู้ใช้
options = []

if forms.alert("ต้องการ Disallow ที่หัว (Start) หรือไม่?", yes=True, no=True):
    options.append("Start")

if forms.alert("ต้องการ Disallow ที่ท้าย (End) หรือไม่?", yes=True, no=True):
    options.append("End")

if not options:
    script.exit()

uidoc = revit.uidoc
doc = revit.doc

selection_ids = uidoc.Selection.GetElementIds()
if not selection_ids:
    forms.alert("กรุณาเลือก Beam หรือ Brace ก่อน", exitscript=True)

# เก็บเฉพาะ Structural Framing elements
structural_elements = []

for element_id in selection_ids:
    element = doc.GetElement(element_id)
    
    # ตรวจสอบว่าเป็น Structural Framing
    if element.Category and element.Category.Id.IntegerValue == int(DB.BuiltInCategory.OST_StructuralFraming):
        structural_elements.append(element)

print("พบ Structural Framing: {} รายการ".format(len(structural_elements)))

if not structural_elements:
    forms.alert("ไม่พบ Structural Framing ใน selection ที่เลือก", exitscript=True)

with revit.Transaction("Disallow Joint"):
    success_count = 0
    
    for element in structural_elements:
        try:
            element_id = element.Id
            
            # ใช้ StructuralFramingUtils สำหรับ Disallow Join
            # Start (0)
            if "Start" in options:
                if not DB.Structure.StructuralFramingUtils.IsJoinAllowedAtEnd(element, 0):
                    print("Join already disallowed at Start for element: {}".format(element_id))
                else:
                    DB.Structure.StructuralFramingUtils.DisallowJoinAtEnd(element, 0)
                    print("Disallowed Start for element: {}".format(element_id))
            
            # End (1)
            if "End" in options:
                if not DB.Structure.StructuralFramingUtils.IsJoinAllowedAtEnd(element, 1):
                    print("Join already disallowed at End for element: {}".format(element_id))
                else:
                    DB.Structure.StructuralFramingUtils.DisallowJoinAtEnd(element, 1)
                    print("Disallowed End for element: {}".format(element_id))
            
            success_count += 1
            
        except Exception as ex:
            print("Error with element {}: {}".format(element_id, ex))
            continue

forms.alert("Disallowed Join on {} elements".format(success_count))
uidoc.RefreshActiveView()