# -*- coding: utf-8 -*-
__title__ = "Numbering\nby Manual"
__author__ = "เพิ่มพงษ์ ทวีกุล"
__doc__ = "พิมพ์ชื่อ Parameter เองเพื่อความแม่นยำ (รองรับ Shared / Built-in / Type) + หมวดหมู่ครบ"

from pyrevit import revit, DB, forms, script

doc = revit.doc
cfg = script.get_config()
BIC = DB.BuiltInCategory

# --- ระบบจดจำการตั้งค่า ---
def get_saved_setting(category_name, key, default):
    return cfg.get_option("{}_{}".format(category_name, key), default)

def save_setting(category_name, key, value):
    cfg.set_option("{}_{}".format(category_name, key), str(value))
    script.save_config()

# --- ฟังก์ชันเขียนค่าลง Parameter (พยายามหาทั้ง Instance และ Type) ---
def set_param_value(elem, param_name, value):
    # 1. ลองหาใน Instance ก่อน
    p = elem.LookupParameter(param_name)
    
    # 2. กรณีพิเศษถ้าพิมพ์ว่า Mark ให้ลองใช้ Built-in ID
    if not p and param_name.lower() == "mark":
        p = elem.get_Parameter(DB.BuiltInParameter.ALL_MODEL_MARK)
        
    # 3. ถ้าหาที่ Instance ไม่เจอ ให้ลองไปหาที่ Type
    if not p:
        t_id = elem.GetTypeId()
        if t_id != DB.ElementId.InvalidElementId:
            t_type = doc.GetElement(t_id)
            p = t_type.LookupParameter(param_name)
            # กรณีพิมพ์ว่า Type Mark
            if not p and param_name.lower() == "type mark":
                p = t_type.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_MARK)

    # เมื่อเจอ Parameter แล้วทำการเขียนค่า
    if p and not p.IsReadOnly:
        try:
            if p.StorageType == DB.StorageType.String:
                p.Set(str(value))
            elif p.StorageType == DB.StorageType.Integer:
                p.Set(int(value))
            elif p.StorageType == DB.StorageType.Double:
                p.Set(float(value))
            return True
        except:
            return False
    return False

# --- Main Execution ---
def run_tool():
    # รายการหมวดหมู่ที่รองรับ (ขยายให้ครอบคลุม)
    category_mapping = {
        "Doors": BIC.OST_Doors,
        "Windows": BIC.OST_Windows,
        "Furniture": BIC.OST_Furniture,
        "Rooms": BIC.OST_Rooms,
        "Generic Models": BIC.OST_GenericModel,
        "Viewports": BIC.OST_Viewports,
        # เพิ่มหมวดหมู่เพิ่มเติม
        "Structural Columns": BIC.OST_StructuralColumns,
        "Structural Framing": BIC.OST_StructuralFraming,
        "Structural Foundations": BIC.OST_StructuralFoundation,
        "Walls": BIC.OST_Walls,
        "Floors": BIC.OST_Floors,
        "Roofs": BIC.OST_Roofs,
        "Stairs": BIC.OST_Stairs,
        "Plumbing Fixtures": BIC.OST_PlumbingFixtures,
        "Pipes": BIC.OST_PipeCurves,
        "Mechanical Equipment": BIC.OST_MechanicalEquipment,
        "Electrical Equipment": BIC.OST_ElectricalEquipment,
        "Lighting Fixtures": BIC.OST_LightingFixtures,
        "Ceilings": BIC.OST_Ceilings,
        "Railings": BIC.OST_Railings,
        "Site": BIC.OST_Site,
        "Detail Items": getattr(BIC, "OST_DetailComponents", BIC.OST_DetailItems if hasattr(BIC, "OST_DetailItems") else None),
        "Areas": BIC.OST_Areas,
        "MEP Spaces": BIC.OST_MEPSpaces,
        "เสาเข็ม": BIC.OST_StructuralFoundation  # ใช้สำหรับฐานราก (แต่ตัวกรองจะใช้ฟังก์ชัน has_pile_in_family)
    }

    # กรองหมวดหมู่ที่ไม่มีใน Revit เวอร์ชันปัจจุบัน (เช่น Detail Items ในบางเวอร์ชันอาจไม่มี)
    valid_mapping = {k: v for k, v in category_mapping.items() if v is not None}

    # 1. เลือกหมวดหมู่ก่อน (เพื่อให้โปรแกรมรู้ว่าจะคลิกเลือกอะไรได้บ้าง)
    sel_cat_name = forms.CommandSwitchWindow.show(sorted(valid_mapping.keys()), message="เลือกหมวดหมู่ที่ต้องการทำงาน:")
    if not sel_cat_name: return
    bicat_enum = valid_mapping[sel_cat_name]

    # 2. พิมพ์ชื่อ Parameter เอง (ไม่ต้องเลือกจาก List แล้ว)
    last_p_name = get_saved_setting(sel_cat_name, "manual_param", "Mark")
    selected_param = forms.ask_for_string(
        default=last_p_name,
        title="ระบุชื่อ Parameter",
        prompt="พิมพ์ชื่อ Parameter ที่ต้องการใส่ค่า (Shared / Built-in / Instance / Type):"
    )

    if not selected_param: return
    save_setting(sel_cat_name, "manual_param", selected_param)

    # 3. ตั้งค่าตัวเลข
    digits = forms.ask_for_string(default=get_saved_setting(sel_cat_name, "digits", "3"), prompt="จำนวนหลัก (เช่น 3 คือ 001):")
    if not digits: digits = "1"
    save_setting(sel_cat_name, "digits", digits)

    prefix = forms.ask_for_string(default=get_saved_setting(sel_cat_name, "prefix", ""), prompt="คำนำหน้า (Prefix):")
    if prefix is None: prefix = ""
    save_setting(sel_cat_name, "prefix", prefix)

    # --- เพิ่มฟังก์ชันใหม่: ตั้งค่าหมายเลขเริ่มต้น ---
    start_num_str = forms.ask_for_string(default=get_saved_setting(sel_cat_name, "start_num", "1"), prompt="เริ่มนับจากหมายเลขใด (เช่น 0, 1, 10):")
    if not start_num_str or not start_num_str.lstrip('-').isdigit(): # รองรับกรณีลบหรือกดเว้นว่าง
        start_num = 1
    else:
        start_num = int(start_num_str)
    save_setting(sel_cat_name, "start_num", str(start_num))

    # 4. เริ่มการคลิกเลือกชิ้นงาน
    with revit.TransactionGroup("Renumber " + sel_cat_name):
        counter = start_num # นำหมายเลขเริ่มต้นมาใช้
        while True:
            try:
                # สำหรับหมวดหมู่ "เสาเข็ม" ต้องกรองเฉพาะ element ที่มีคำว่า PILE ใน Family Name
                if sel_cat_name == "เสาเข็ม":
                    # ฟังก์ชันช่วยตรวจสอบว่าเป็นเสาเข็ม
                    def has_pile_in_family(el):
                        try:
                            if hasattr(el, "Symbol") and el.Symbol:
                                fam = el.Symbol.Family
                                if fam and "PILE" in fam.Name.upper():
                                    return True
                        except:
                            pass
                        return False
                    # ใช้ pick_element_by_category แล้วกรองด้วยฟังก์ชัน
                    pick = revit.pick_element_by_category(bicat_enum, "คลิกเลือกเสาเข็ม (กด ESC เพื่อจบ)")
                    if not pick: break
                    if not has_pile_in_family(pick):
                        forms.alert("องค์ประกอบที่เลือกไม่ใช่เสาเข็ม (Family Name ไม่มี PILE)", exits=False)
                        continue
                else:
                    pick = revit.pick_element_by_category(bicat_enum, "คลิกเลือก Object (กด ESC เพื่อจบการทำงาน)")
                    if not pick: break

                # ป้องกันกรณีตัวเลขติดลบเวลาทำ zfill
                if counter >= 0:
                    new_val = "{}{}".format(prefix, str(counter).zfill(int(digits)))
                else:
                    new_val = "{}-{}".format(prefix, str(abs(counter)).zfill(int(digits)))

                with revit.Transaction("Set " + selected_param):
                    if set_param_value(pick, selected_param, new_val):
                        counter += 1
                    else:
                        forms.alert("ไม่พบ Parameter ชื่อ '{}' ในชิ้นงานที่เลือก หรือเป็นค่าที่แก้ไขไม่ได้".format(selected_param), exits=False)
            except:
                # กรณี User กด ESC
                break

if __name__ == "__main__":
    run_tool()