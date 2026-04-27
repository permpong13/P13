# -*- coding: utf-8 -*-
import os
from pyrevit import forms

def fix_folder_structure():
    """
    ฟังก์ชันสำหรับแก้ปัญหาโฟลเดอร์ซ้อน (P13.extension.extension) 
    โดยจะเปลี่ยนชื่อให้กลับเป็น P13.extension เพียงชั้นเดียว
    """
    current_file_path = os.path.abspath(__file__)
    check_path = current_file_path
    ext_folder_path = None
    
    # 1. ไล่หาโฟลเดอร์ระดับ .extension
    for _ in range(5): 
        check_path = os.path.dirname(check_path)
        if os.path.basename(check_path).endswith(".extension"):
            ext_folder_path = check_path
            break
            
    if not ext_folder_path:
        return

    # 2. ตรวจสอบชื่อโฟลเดอร์ปัจจุบัน
    current_name = os.path.basename(ext_folder_path)
    parent_dir = os.path.dirname(ext_folder_path)

    # 3. Logic แก้ไขปัญหาชื่อโฟลเดอร์ซ้อนกัน (เช่น P13.extension.extension)
    # หรือกรณีที่มีชื่อซ้ำซ้อนกันจากการแตกไฟล์ผิดพลาด
    if current_name.count('.extension') > 1:
        new_name = current_name.split('.extension')[0] + ".extension"
        new_path = os.path.join(parent_dir, new_name)

        # ตรวจสอบว่าชื่อใหม่ไม่ซ้ำกับที่มีอยู่แล้วก่อนเปลี่ยนชื่อ
        if not os.path.exists(new_path):
            try:
                os.rename(ext_folder_path, new_path)
                forms.alert(
                    "พบข้อผิดพลาดของชื่อโฟลเดอร์และได้รับการแก้ไขแล้ว:\n\n"
                    "จาก: {}\n"
                    "เป็น: {}\n\n"
                    "กรุณา Restart Revit เพื่อให้เครื่องมือกลับมาใช้งานได้ปกติ".format(current_name, new_name),
                    title="Folder Structure Fixed"
                )
            except Exception as e:
                print("Cannot rename folder: {}".format(e))

# รันฟังก์ชันทันทีเมื่อเปิด Revit
if __name__ == "__main__":
    fix_folder_structure()