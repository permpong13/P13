# -*- coding: utf-8 -*-
import os
import subprocess
from pyrevit import forms, script
from pyrevit.loader import sessionmgr

# ==========================================
# 1. SETTINGS (แก้ไขจุดนี้จุดเดียว)
# ==========================================
# หากใช้ชื่อ \\tee แล้วยังติด Error 5 แนะนำให้เปลี่ยนเป็น IP เช่น r"\\192.168.1.xx\P13.extension"
SOURCE_PATH = r"\\tee\P13.extension" 
ADMIN_USER = "Permpong13"

# ==========================================
# 2. DYNAMIC PATH FINDING
# ==========================================
def get_extension_base_path(path):
    """ฟังก์ชันเดินถอยหลังเพื่อหา Root Folder ของ .extension ในเครื่อง User"""
    parent = os.path.dirname(path)
    if parent.lower().endswith(".extension"):
        return parent
    elif len(parent) > 3:
        return get_extension_base_path(parent)
    return None

# หาตำแหน่งปัจจุบันที่ปุ่มนี้ติดตั้งอยู่
current_script_path = os.path.abspath(__file__)
DESTINATION_PATH = get_extension_base_path(current_script_path)

# ==========================================
# 3. MAIN LOGIC
# ==========================================
def sync_tools():
    # ตรวจสอบ Username ปัจจุบันของ Windows
    current_user = os.environ.get('USERNAME')

    # --- เงื่อนไขที่ 1: ป้องกันเครื่องเจ้าของ (Permpong13) ---
    if current_user == ADMIN_USER:
        forms.alert(
            "สวัสดีคุณ Permpong13!\n\n"
            "ระบบตรวจพบว่าคุณคือเจ้าของไฟล์ต้นฉบับ\n"
            "สคริปต์จะไม่ทำการ Sync เพื่อป้องกันการเขียนทับไฟล์ที่คุณกำลังพัฒนาครับ",
            title="Admin Protection"
        )
        return

    # --- เงื่อนไขที่ 2: ตรวจสอบความพร้อมของปลายทาง ---
    if not DESTINATION_PATH:
        forms.alert("ไม่พบตำแหน่งการติดตั้ง .extension ในเครื่องนี้", title="Path Error")
        return

    # --- เงื่อนไขที่ 3: ตรวจสอบการเชื่อมต่อวง LAN (เครื่อง Bim1, OHM ต้องเข้าถึงได้) ---
    if not os.path.exists(SOURCE_PATH):
        forms.alert(
            "ไม่สามารถเข้าถึงเซิร์ฟเวอร์หลักได้ (\\tee)\n\n"
            "กรุณาตรวจสอบว่า:\n"
            "1. เชื่อมต่อ LAN เดียวกันแล้ว\n"
            "2. สิทธิ์การเข้าถึง (Permission) ถูกต้อง\n"
            "3. ลองเปลี่ยนชื่อเครื่องเป็น IP Address ในสคริปต์",
            title="Connection Denied"
        )
        return

    # --- เงื่อนไขที่ 4: ยืนยันและเริ่มการ Copy ---
    msg = "ตรวจพบผู้ใช้งาน: {}\nคุณต้องการอัปเดตเครื่องมือ BIM เป็นเวอร์ชันล่าสุดหรือไม่?".format(current_user)
    res = forms.alert(msg, title="Update Tools", options=["Update Now", "Cancel"])
                      
    if res == "Update Now":
        # /MIR  : Mirror ไฟล์จากต้นทางมา 100%
        # /Z    : Restartable mode (กันเน็ตหลุด)
        # /MT:8 : Multi-threading 8 Core เพื่อความเร็ว
        # /R:1 /W:1 : Retry 1 ครั้ง รอ 1 วินาที (ไม่ให้ค้างนาน)
        cmd = 'robocopy "{}" "{}" /MIR /Z /MT:8 /R:1 /W:1 /XF *.pyc /NFL /NDL /NJH /NJS'.format(SOURCE_PATH, DESTINATION_PATH)
        
        try:
            with forms.ProgressBar(title="กำลังดาวน์โหลดไฟล์จากเครื่องคุณ Tee...") as pb:
                # รัน Robocopy ใน Background
                subprocess.call(cmd, shell=True)
            
            forms.alert("อัปเดตสำเร็จ! ระบบจะทำการรีโหลดเมนู Revit", title="Success")
            
            # สั่งให้ pyRevit รีโหลดตัวเองเพื่ออัปเดตปุ่มบน Ribbon
            sessionmgr.reload_pyrevit()
            
        except Exception as e:
            forms.alert("เกิดข้อผิดพลาดระหว่างการอัปเดต:\n{}".format(str(e)), title="Error")

if __name__ == '__main__':
    sync_tools()