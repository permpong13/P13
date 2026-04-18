# -*- coding: utf-8 -*-
import os
import urllib2
import zipfile
import shutil
from pyrevit import forms, script
from pyrevit.loader import sessionmgr

# ==========================================
# SETTINGS (Public GitHub Repository)
# ==========================================
USER_REPO = "Permpong13/P13.extension"
GITHUB_API_URL = "https://api.github.com/repos/{}/zipball/main".format(USER_REPO)
ADMIN_USER = "Permpong13"

def sync_tools():
    current_user = os.environ.get('USERNAME')
    
    # 1. ป้องกันเครื่อง Admin รันซ้ำซ้อน
    if current_user == ADMIN_USER:
        forms.alert("โหมด Admin: กรุณาใช้ไฟล์ .bat ที่หน้าจอเพื่อ Push งานครับ", title="Admin Notice")
        return

    # 2. หาตำแหน่งโฟลเดอร์หลัก (P13.extension)
    current_path = os.path.dirname(os.path.abspath(__file__))
    dest_path = current_path
    while not dest_path.endswith("P13.extension"):
        parent = os.path.dirname(dest_path)
        if parent == dest_path: break
        dest_path = parent

    # 3. ยืนยันการอัปเดต (GitHub Cloud เท่านั้น)
    if forms.alert("ต้องการอัปเดตเครื่องมือ BIM จาก GitHub Cloud หรือไม่?", 
                   options=["Update Now", "Cancel"]) != "Update Now":
        return

    try:
        # 4. ดาวน์โหลด Zip จาก GitHub Public Repo (ไม่ต้องใช้ Token)
        temp_zip = os.path.join(os.environ['TEMP'], "P13_update.zip")
        temp_dir = os.path.join(os.environ['TEMP'], "P13_temp_extract")
        
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        
        # รันคำสั่งดาวน์โหลดโดยตรงผ่าน URL
        with forms.ProgressBar(title="กำลังดาวน์โหลดจาก GitHub Cloud...") as pb:
            response = urllib2.urlopen(GITHUB_API_URL)
            with open(temp_zip, 'wb') as f:
                f.write(response.read())
        
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        extracted_folder = os.path.join(temp_dir, os.listdir(temp_dir)[0])
        
        # 5. การก๊อปปี้แบบ Safety (เลี่ยงปัญหา Permission Denied)
        for root, dirs, files in os.walk(extracted_folder):
            rel_path = os.path.relpath(root, extracted_folder)
            target_dir = os.path.join(dest_path, rel_path)
            
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)
            
            for f in files:
                src_file = os.path.join(root, f)
                dst_file = os.path.join(target_dir, f)
                try:
                    shutil.copy2(src_file, dst_file)
                except:
                    # ข้ามไฟล์ที่ติด Lock
                    continue

        forms.alert("อัปเดตจาก GitHub สำเร็จ! หากปุ่มบางปุ่มไม่เปลี่ยน ให้ลองปิด-เปิด Revit ใหม่", title="Success")
        sessionmgr.reload_pyrevit()
        
    except Exception as e:
        forms.alert("เกิดข้อผิดพลาดในการอัปเดต: {}".format(str(e)))

if __name__ == '__main__':
    sync_tools()