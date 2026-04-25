# -*- coding: utf-8 -*-
__title__ = "Sync MH\nAbsolute Clean (v3)"

import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
from pyrevit import forms, revit

doc = revit.doc

def get_p(element, param_name):
    """
    ฟังก์ชันตัวช่วยสำหรับดึง Parameter 
    โดยเช็คจาก Instance ก่อน หากไม่พบให้ค้นหาจาก Type
    """
    # 1. ค้นหาจาก Instance
    p = element.LookupParameter(param_name)
    if p:
        return p
        
    # 2. ค้นหาจาก Type
    type_id = element.GetTypeId()
    if type_id != ElementId.InvalidElementId:
        type_el = doc.GetElement(type_id)
        if type_el:
            return type_el.LookupParameter(param_name)
            
    return None

def sync_data():
    # ดึง Elements ทั้งหมดในหมวด Structural Foundations
    elements = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralFoundation).WhereElementIsNotElementType().ToElements()
    count = len(elements)
    
    if count == 0:
        forms.alert("ไม่พบ Element ในหมวด Structural Foundation", title="Warning")
        return

    # กำหนดคู่พารามิเตอร์ (คงไว้ตามต้นฉบับเดิมทั้งหมด)
    config = [
        {"chk": "A", "front": "Front_Invert", "dest": ["C1_INV_TXT", "C1_W_TXT", "C1_H_TXT", "C1_X1_TXT", "C1_X2_TXT"], "src_other": ["W_Front", "H_Front", "X1A", "X2A"]},
        {"chk": "C", "front": "Back_Invert",  "dest": ["C2_INV_TXT", "C2_W_TXT", "C2_H_TXT", "C2_X1_TXT", "C2_X2_TXT"], "src_other": ["W_Beck", "H_Back", "X1C", "X2C"]},
        {"chk": "B", "front": "Right_Invert", "dest": ["C3_INV_TXT", "C3_W_TXT", "C3_H_TXT", "C3_X1_TXT", "C3_X2_TXT"], "src_other": ["W_Right", "H_Right", "X1B", "X2B"]},
        {"chk": "D", "front": "Left_Invert",  "dest": ["C4_INV_TXT", "C4_W_TXT", "C4_H_TXT", "C4_X1_TXT", "C4_X2_TXT"], "src_other": ["W_Left", "H_Left", "X1D", "X2D"]}
    ]

    # ใช้ Progress Bar เพื่อแสดงสถานะการทำงาน (ฟีเจอร์จาก v2)
    with forms.ProgressBar(title="กำลัง Sync ข้อมูล MH... ({value}/{max})", step=1, cancellable=True) as pb:
        with revit.Transaction("Sync Top-Front Absolute Clean"):
            for el in elements:
                # ตรวจสอบการกดยกเลิก
                if pb.cancelled:
                    break
                
                # ดึงค่า Elevation at Top โดยใช้ get_p
                top_p = get_p(el, "Elevation at Top")
                top_val = top_p.AsDouble() if top_p else 0.0

                for side in config:
                    # 1. ล้างค่าเก่าในช่อง _TXT ทั้ง 5 ช่อง (Absolute Clean)
                    target_params = []
                    for d_name in side["dest"]:
                        p = get_p(el, d_name)
                        if p and not p.IsReadOnly: # เช็คเพิ่มเติมเพื่อป้องกัน Error หาก Type Parameter โดนล็อค
                            p.Set("") 
                        target_params.append(p)

                    # 2. ตรวจสอบการติ๊กถูก (Checkbox)
                    chk_p = get_p(el, side["chk"])
                    is_checked = (chk_p and chk_p.AsInteger() == 1)

                    # 3. ตรวจสอบขนาดท่อ (W) ไม่เป็น 0
                    w_src_name = side["src_other"][0]
                    w_p = get_p(el, w_src_name)
                    w_val_str = w_p.AsValueString().replace(" m", "").strip() if w_p else "0"
                    has_pipe = w_val_str not in ["0", "0.00", "0.000", "", "m", "0 m"]

                    # ตรรกะเดิม: ต้องติ๊กถูก AND มีขนาดท่อ ถึงจะลงค่า
                    if is_checked and has_pipe:
                        # คำนวณ INV
                        front_p = get_p(el, side["front"])
                        if front_p and target_params[0] and not target_params[0].IsReadOnly:
                            inv_feet = top_val - front_p.AsDouble()
                            inv_m = UnitUtils.ConvertFromInternalUnits(inv_feet, UnitTypeId.Meters)
                            target_params[0].Set("{:.3f}".format(inv_m))

                        # ใส่ค่า W, H, X1, X2
                        for i, src_name in enumerate(side["src_other"], 1):
                            s_p = get_p(el, src_name)
                            d_p = target_params[i]
                            if s_p and d_p and not d_p.IsReadOnly:
                                val_str = s_p.AsValueString().replace(" m", "").strip()
                                if val_str not in ["0", "0.00", "0.000", "", "m", "0 m"]:
                                    d_p.Set(val_str)
                
                pb.update_progress()

    forms.alert("Sync ข้อมูลเรียบร้อยแล้ว รองรับทั้ง Type และ Instance!", title="Done")

if __name__ == "__main__":
    sync_data()