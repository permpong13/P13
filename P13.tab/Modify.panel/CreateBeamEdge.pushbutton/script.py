# -*- coding: utf-8 -*-
import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.DB.Structure import StructuralType
import sys

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

def create_beams_on_edges():
    # 1. ค้นหา Family ของคาน (Structural Framing) ที่อยู่ในโปรเจกต์
    collector = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralFraming).WhereElementIsElementType()
    beam_symbol = collector.FirstElement()

    if not beam_symbol:
        TaskDialog.Show("แจ้งเตือน", "ไม่พบ Family คาน (Structural Framing) ในโปรเจกต์ กรุณาโหลดก่อนครับ")
        return

    # 2. หาระดับอ้างอิง (Level) จาก View ปัจจุบัน
    level = doc.ActiveView.GenLevel
    if not level:
        level_collector = FilteredElementCollector(doc).OfClass(Level)
        level = level_collector.FirstElement()

    # 3. ให้ผู้ใช้เลือกเส้นขอบ (Edge)
    try:
        # เลือกได้หลายเส้นพร้อมกัน ทั้งเส้นตรง โค้ง หรือสโลปต่างระดับ กด Finish เมื่อเลือกเสร็จ
        references = uidoc.Selection.PickObjects(ObjectType.Edge, "คลิ๊กเลือกเส้นขอบที่ต้องการสร้างคาน (กด Finish มุมซ้ายบนเมื่อเสร็จ)")
    except Autodesk.Revit.Exceptions.OperationCanceledException:
        # หากผู้ใช้กด Esc ให้ยกเลิกการทำงานอย่างเงียบๆ
        sys.exit()

    # 4. เริ่มขั้นตอนการสร้างโมเดล
    t = Transaction(doc, "Create Beams on Edges")
    t.Start()

    # เปิดการใช้งาน Family Symbol หากยังไม่ Active
    if not beam_symbol.IsActive:
        beam_symbol.Activate()

    success_count = 0
    error_count = 0

    for ref in references:
        element = doc.GetElement(ref)
        geometry_object = element.GetGeometryObjectFromReference(ref)

        if isinstance(geometry_object, Edge):
            curve = geometry_object.AsCurve()
            
            try:
                # คำสั่งสร้างคานตามเส้น Curve (จะวิ่งขึ้น-ลงตามเส้น หรือโค้งตามเส้นอัตโนมัติ)
                doc.Create.NewFamilyInstance(curve, beam_symbol, level, StructuralType.Beam)
                success_count += 1
            except Exception as e:
                error_count += 1
                pass # ข้ามเส้นที่เรขาคณิตซับซ้อนเกินไป

    t.Commit()
    
    # สรุปผลการทำงาน
    msg = "สร้างคานสำเร็จจำนวน {} ชิ้น\n".format(success_count)
    if error_count > 0:
        msg += "มีเส้นที่ไม่สามารถสร้างได้ {} ชิ้น (อาจมีความโค้งหรือมุมหักศอกที่ซับซ้อนเกินไป)".format(error_count)
        
    TaskDialog.Show("สรุปผลการทำงาน", msg)

# เรียกใช้งานฟังก์ชัน
create_beams_on_edges()