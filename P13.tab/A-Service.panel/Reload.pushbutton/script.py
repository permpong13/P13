# -*- coding: utf-8 -*-
import os
import urllib2  # สำหรับ pyRevit (IronPython) จะใช้ urllib2
import zipfile
import shutil
from pyrevit import forms, script
from pyrevit.loader import sessionmgr

# ==========================================
# SETTINGS
# ==========================================
# ใช้ Token ที่คุณให้มา ([REDACTED_GITHUB_TOKEN])
TOKEN = "[REDACTED_GITHUB_TOKEN]"
USER_REPO = "Permpong13/P13.extension"
# URL สำหรับดาวน์โหลด Zip จาก GitHub API
GITHUB_API_URL = "https://api.github.com/repos/{}/zipball/main".format(USER_REPO)

SOURCE_LAN = r"\\tee\P13.extension" 
ADMIN_USER = "Permpong13"

def sync_tools():
    current_user = os.environ.get('USERNAME')
    
    # 1. โหมด Admin (ตัวคุณ Tee เอง) ไม่ต้องรันซ้ำ
    if current_user == ADMIN_USER:
        forms.alert("โหมด Admin: ระบบจะไม่ Sync ทับไฟล์งานของคุณครับ", title="Admin Notice")
        return

    # 2. หาตำแหน่งที่ติดตั้งโปรแกรมในเครื่องลูก
    current_path = os.path.dirname(os.path.abspath(__file__))
    dest_path = current_path
    while not dest_path.endswith("P13.extension"):
        parent = os.path.dirname(dest_path)
        if parent == dest_path: break
        dest_path = parent

    # 3. เลือกช่องทาง (LAN vs Cloud)
    lan_available = os.path.exists(SOURCE_LAN)
    mode = "LAN (Direct)" if lan_available else "GitHub Cloud (Private)"

    if forms.alert("ตรวจพบช่องทาง: {}\nต้องการอัปเดตเครื่องมือหรือไม่?".format(mode), 
                   options=["Update Now", "Cancel"]) != "Update Now":
        return

    try:
        if lan_available:
            # ใช้ Robocopy ถ้าต่อ LAN (เร็วที่สุด)
            os.system('robocopy "{}" "{}" /MIR /Z /MT:8 /R:1 /W:1 /XF *.pyc'.format(SOURCE_LAN, dest_path))
        else:
            # ดาวน์โหลดผ่าน GitHub API โดยใช้ Token
            temp_zip = os.path.join(os.environ['TEMP'], "P13_update.zip")
            temp_dir = os.path.join(os.environ['TEMP'], "P13_temp_extract")
            
            # ลบโฟลเดอร์ชั่วคราวเก่า (ถ้ามี)
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
            
            # สร้าง Request และใส่ Authorization Header
            request = urllib2.Request(GITHUB_API_URL)
            request.add_header('Authorization', 'token {}'.format(TOKEN))
            
            # เริ่มดาวน์โหลด
            with forms.ProgressBar(title="กำลังดาวน์โหลดจาก GitHub Cloud...") as pb:
                response = urllib2.urlopen(request)
                with open(temp_zip, 'wb') as f:
                    f.write(response.read())
            
            # แตกไฟล์
            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            
            # หาโฟลเดอร์ที่แตกออกมา (GitHub จะตั้งชื่อยาวๆ เช่น Permpong13-P13.extension-xxxx)
            extracted_folder = os.path.join(temp_dir, os.listdir(temp_dir)[0])
            
            # ก๊อปปี้ไฟล์ทับ
            for item in os.listdir(extracted_folder):
                s = os.path.join(extracted_folder, item)
                d = os.path.join(dest_path, item)
                if os.path.isdir(s):
                    if os.path.exists(d): shutil.rmtree(d)
                    shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)

        forms.alert("อัปเดตจาก Cloud สำเร็จ!", title="Success")
        sessionmgr.reload_pyrevit()
        
    except Exception as e:
        forms.alert("เกิดข้อผิดพลาด: {}".format(str(e)))

if __name__ == '__main__':
    sync_tools()