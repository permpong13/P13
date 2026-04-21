# -*- coding: utf-8 -*-
__title__ = "Sync MH\nAbsolute Clean"

import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
from pyrevit import forms, revit

doc = revit.doc

def sync_data():
    elements = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralFoundation).WhereElementIsNotElementType()
    
    # กำหนดคู่พารามิเตอร์สำหรับคำนวณและช่องปลายทาง
    config = [
        {"chk": "A", "front": "Front_Invert", "dest": ["C1_INV_TXT", "C1_W_TXT", "C1_H_TXT", "C1_X1_TXT", "C1_X2_TXT"], "src_other": ["W_Front", "H_Front", "X1A", "X2A"]},
        {"chk": "C", "front": "Back_Invert",  "dest": ["C2_INV_TXT", "C2_W_TXT", "C2_H_TXT", "C2_X1_TXT", "C2_X2_TXT"], "src_other": ["W_Beck", "H_Back", "X1C", "X2C"]},
        {"chk": "B", "front": "Right_Invert", "dest": ["C3_INV_TXT", "C3_W_TXT", "C3_H_TXT", "C3_X1_TXT", "C3_X2_TXT"], "src_other": ["W_Right", "H_Right", "X1B", "X2B"]},
        {"chk": "D", "front": "Left_Invert",  "dest": ["C4_INV_TXT", "C4_W_TXT", "C4_H_TXT", "C4_X1_TXT", "C4_X2_TXT"], "src_other": ["W_Left", "H_Left", "X1D", "X2D"]}
    ]

    with revit.Transaction("Sync Top-Front Absolute Clean"):
        for el in elements:
            # ดึงค่า Elevation at Top (ระดับดิน/ฝาบ่อ)
            top_p = el.LookupParameter("Elevation at Top")
            top_val = top_p.AsDouble() if top_p else 0.0

            for side in config:
                # 1. ล้างค่าเก่าในช่อง _TXT ทั้ง 5 ช่องของทิศนี้ให้ "ว่างเปล่า" ก่อนเสมอ
                target_params = []
                for d_name in side["dest"]:
                    p = el.LookupParameter(d_name)
                    if p:
                        p.Set("") # เคลียร์ค่าทิ้ง
                    target_params.append(p)

                # 2. ตรวจสอบ "ตัวติ๊ก"
                chk_p = el.LookupParameter(side["chk"])
                is_checked = (chk_p and chk_p.AsInteger() == 1)

                # 3. ตรวจสอบ "ขนาดท่อ (W)" ว่าไม่ใช่เลข 0 (ป้องกันกรณีติ๊กไว้แต่ไม่ได้ใส่ท่อ)
                w_src_name = side["src_other"][0] # ดึงชื่อ W_Front, W_Beck ฯลฯ
                w_p = el.LookupParameter(w_src_name)
                w_val_str = w_p.AsValueString().replace(" m", "").strip() if w_p else "0"
                has_pipe = w_val_str not in ["0", "0.00", "0.000", "", "m", "0 m"]

                # ** จุดสำคัญ: ต้องติ๊กถูก AND ต้องมีขนาดท่อ (W > 0) ถึงจะยอมให้คำนวณและลงค่า **
                if is_checked and has_pipe:
                    
                    # 1. คำนวณ INV: Top - Front_Invert
                    front_p = el.LookupParameter(side["front"])
                    if front_p and target_params[0]:
                        # สูตร: ระดับบน - ระยะห่าง = ระดับท้องท่อ (Invert)
                        inv_feet = top_val - front_p.AsDouble()
                        inv_m = UnitUtils.ConvertFromInternalUnits(inv_feet, UnitTypeId.Meters)
                        target_params[0].Set("{:.3f}".format(inv_m))

                    # 2. ใส่ค่า W, H, X1, X2
                    for i, src_name in enumerate(side["src_other"], 1):
                        s_p = el.LookupParameter(src_name)
                        d_p = target_params[i]
                        if s_p and d_p:
                            val_str = s_p.AsValueString().replace(" m", "").strip()
                            if val_str not in ["0", "0.00", "0.000", "", "m", "0 m"]:
                                d_p.Set(val_str)
                                
    forms.alert("แก้ไขลอจิกเรียบร้อย! ช่อง INV จะว่างไปพร้อมกับช่องอื่นๆ แล้วครับ", title="Done")

if __name__ == "__main__":
    sync_data()