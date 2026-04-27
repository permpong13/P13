# -*- coding: utf-8 -*-
import os
import urllib2
import zipfile
import shutil
from pyrevit.loader import sessionmgr

# ==========================================
# SETTINGS (Public GitHub Repository)
# ==========================================
USER_REPO = "Permpong13/P13.extension"
GITHUB_API_URL = "https://api.github.com/repos/{}/zipball/main".format(USER_REPO)
ADMIN_USER = "Permpong13"

def sync_tools():
    current_user = os.environ.get('USERNAME')
    
    # 1. ป้องกันเครื่อง Admin รันซ้ำซ้อน (พิมพ์ลง Console แทน จะได้ไม่ต้องกดปิด)
    if current_user == ADMIN_USER:
        print("Admin Mode: Please use the .bat file on your desktop to Push.")
        return

    # 2. หาตำแหน่งโฟลเดอร์หลัก (รองรับทั้ง P13.extension และ P13.extension.extension)
    current_path = os.path.dirname(os.path.abspath(__file__))
    dest_path = current_path
    
    # [แก้ไขจุดนี้] เปลี่ยนมาใช้ startswith เพื่อเช็คชื่อจากด้านหน้า
    while not os.path.basename(dest_path).startswith("P13.extension"):
        parent = os.path.dirname(dest_path)
        if parent == dest_path: break
        dest_path = parent

    try:
        # 3. ดาวน์โหลด Zip จาก GitHub แบบเงียบๆ (ไม่มี Progress Bar)
        temp_zip = os.path.join(os.environ['TEMP'], "P13_update.zip")
        temp_dir = os.path.join(os.environ['TEMP'], "P13_temp_extract")
        
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        
        response = urllib2.urlopen(GITHUB_API_URL)
        with open(temp_zip, 'wb') as f:
            f.write(response.read())
        
        # แตกไฟล์
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # ค้นหาโฟลเดอร์ที่แตกออกมา (ปกติ GitHub จะสร้างโฟลเดอร์ชื่อ Repo ครอบไว้ 1 ชั้น)
        extracted_folder = os.path.join(temp_dir, os.listdir(temp_dir)[0])
        
        # --- [เพิ่ม Logic วิธี B] ป้องกันโฟลเดอร์ซ้อนกัน ---
        # ตรวจสอบว่าข้างในมีโฟลเดอร์ P13.extension ซ่อนอยู่อีกชั้นหรือไม่
        # ถ้ามี ให้ขยับเข้าไปใช้โฟลเดอร์ชั้นในแทน เพื่อไม่ให้เวลา Copy แล้วกลายเป็น .extension.extension
        inner_folder = os.path.join(extracted_folder, "P13.extension")
        if os.path.exists(inner_folder):
            extracted_folder = inner_folder
        # ------------------------------------------------
        
        # 4. การก๊อปปี้แบบ Safety
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
                    # ข้ามไฟล์ที่ติด Lock แบบเงียบๆ
                    continue

        # 5. ลบไฟล์ Temp ขยะทิ้งหลังจากอัปเดตเสร็จ 
        try:
            if os.path.exists(temp_zip): os.remove(temp_zip)
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        except:
            pass

        # 6. Reload pyRevit เพื่อให้เครื่องมือใหม่พร้อมใช้ทันที
        sessionmgr.reload_pyrevit()
        
    except Exception as e:
        # หากมี Error จะแสดงในหน้าต่าง Console ของ pyRevit แทนการเด้ง Popup แจ้งเตือน
        print("Error Update: {}".format(str(e)))

if __name__ == '__main__':
    sync_tools()