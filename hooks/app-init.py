# -*- coding: utf-8 -*-
import os
import urllib2
import zipfile
import shutil
import json
from pyrevit.loader import sessionmgr

# ==========================================
# SETTINGS
# ==========================================
USER_REPO = "Permpong13/P13.extension"
GITHUB_API_URL = "https://api.github.com/repos/{}/zipball/main".format(USER_REPO)
GITHUB_COMMIT_API = "https://api.github.com/repos/{}/commits/main".format(USER_REPO)
ADMIN_USER = "Permpong13"

def silent_auto_update():
    current_user = os.environ.get('USERNAME')
    
    # 1. ข้ามการทำงานทันทีถ้าเป็นเครื่อง Admin
    if current_user == ADMIN_USER:
        return

    # 2. เตรียมไฟล์สำหรับเช็คเวอร์ชัน และหาโฟลเดอร์หลัก (P13.extension)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    version_file = os.path.join(current_dir, "last_commit.txt")
    
    dest_path = current_dir
    while not dest_path.endswith("P13.extension"):
        parent = os.path.dirname(dest_path)
        if parent == dest_path: break
        dest_path = parent

    try:
        # 3. เช็ค Commit ล่าสุดแบบเงียบๆ
        request = urllib2.Request(GITHUB_COMMIT_API)
        request.add_header('User-Agent', 'pyRevit-SilentUpdate')
        response = urllib2.urlopen(request, timeout=5)
        data = json.loads(response.read())
        latest_sha = data['sha']

        # 4. อ่านเวอร์ชันเดิมในเครื่อง
        local_sha = ""
        if os.path.exists(version_file):
            with open(version_file, 'r') as f:
                local_sha = f.read().strip()

        # 5. ถ้ามีอัปเดตใหม่ ให้ดาวน์โหลดและทับไฟล์ทันที
        if latest_sha != local_sha:
            temp_zip = os.path.join(os.environ['TEMP'], "P13_update.zip")
            temp_dir = os.path.join(os.environ['TEMP'], "P13_temp_extract")
            
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
            
            # ดาวน์โหลด
            response_zip = urllib2.urlopen(GITHUB_API_URL)
            with open(temp_zip, 'wb') as f:
                f.write(response_zip.read())
            
            # แตกไฟล์
            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            
            extracted_folder = os.path.join(temp_dir, os.listdir(temp_dir)[0])
            
            # ก๊อปปี้ไฟล์แบบข้ามไฟล์ที่ถูก Lock (เงียบๆ ไม่เก็บ Log กวนใจ)
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
                        continue

            # ลบไฟล์ขยะ
            try:
                if os.path.exists(temp_zip): os.remove(temp_zip)
                if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
            except:
                pass
            
            # บันทึกเวอร์ชันใหม่
            with open(version_file, 'w') as f:
                f.write(latest_sha)

            # โหลด pyRevit ใหม่เงียบๆ เพื่อให้เครื่องมือใหม่พร้อมใช้
            sessionmgr.reload_pyrevit()

    except Exception:
        # หากไม่มีเน็ต หรือเกิด Error ใดๆ ให้ปล่อยผ่านไปเลย User จะได้ทำงานต่อได้
        pass

if __name__ == '__main__':
    silent_auto_update()