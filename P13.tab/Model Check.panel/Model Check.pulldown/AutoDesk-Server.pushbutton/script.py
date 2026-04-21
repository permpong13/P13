# -*- coding: utf-8 -*-
__title__ = "AutoDesk\nCheck Server"
__author__ = "Tee_เพิ่มพงษ์"
__doc__ = "pyRevit Script สำหรับตรวจสอบสถานะ Autodesk พร้อมระบบบันทึก Log และ UI แบบใหม่"

import os
import requests
import re
import time
from datetime import datetime
from pyrevit import forms
from pyrevit import script

target_service = "Revit Cloud Worksharing / Cloud Models"

# ใช้ระบบ Config ของ pyRevit สำหรับจดจำการตั้งค่า
cfg = script.get_config()


def get_service_status(html_content, service_name):
    """ตรวจสอบสถานะบริการจาก HTML (ฟังก์ชันเดิมของคุณ)"""
    try:
        pattern = (
            r'(?:<span[^>]*class="name"|<div[^>]*class="component-name")[^>]*>\s*'
            + re.escape(service_name)
            + r'\s*</(?:span|div)>[\s\S]*?(?:<span|<div)[^>]*class="component-status[^"]*"[^>]*>([\s\S]*?)</(?:span|div)>'
        )
        match = re.search(pattern, html_content, re.IGNORECASE)
        if match:
            status = re.sub(r'\s+', ' ', match.group(1)).strip()
            return status
        return "ไม่พบข้อมูล"
    except Exception as e:
        return "ข้อผิดพลาด: " + str(e)


def get_thai_time():
    """คืนค่าเวลาปัจจุบันในรูปแบบภาษาไทย (ฟังก์ชันเดิมของคุณ)"""
    now = datetime.now()
    thai_months = [
        "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน",
        "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม",
        "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
    ]
    return "วันที่ {} {} พ.ศ. {} เวลา {}".format(
        now.day, thai_months[now.month - 1], now.year + 543, now.strftime("%H:%M:%S")
    )


def get_or_set_export_path():
    """ฟังก์ชันใหม่: ดึงค่า Export Path เดิม หรือเปิดหน้าต่างให้เลือกถ้ายังไม่มี"""
    # ใช้ getattr แทน get_option เพื่อป้องกัน Error ใน pyRevit บางเวอร์ชัน
    export_path = getattr(cfg, 'autodesk_status_export_path', None)
    
    # หากไม่มีการตั้งค่า หรือ โฟลเดอร์เดิมถูกลบไปแล้ว ให้เด้งหน้าต่างให้เลือกใหม่
    if not export_path or not os.path.exists(export_path):
        export_path = forms.pick_folder(title="เลือกโฟลเดอร์สำหรับบันทึกรายงานสถานะ (Export Path)")
        if export_path:
            # บันทึกการตั้งค่าไว้ใช้ครั้งต่อไป
            cfg.autodesk_status_export_path = export_path
            script.save_config()
        else:
            return None # กรณีผู้ใช้กดกากบาท หรือยกเลิก
            
    return export_path


def save_log(export_path, status1, status2, status_pair):
    """ฟังก์ชันใหม่: บันทึกประวัติสถานะลงไฟล์ Text"""
    if not export_path:
        return
    
    log_file = os.path.join(export_path, "Autodesk_Server_Status_Log.txt")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = "[{}] Service: {} | Status: {} -> {} ({})\n".format(
        timestamp, target_service, status1, status2, status_pair
    )
    
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print("ไม่สามารถบันทึกไฟล์ Log ได้: {}".format(e))


def main():
    output = script.get_output()
    
    # เพิ่ม CSS สไตล์ให้ Output หน้าตาดูเป็น Dashboard มากขึ้น
    output.print_html("""
    <meta charset='utf-8'>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; }
        .card { background-color: #f9f9f9; border-left: 5px solid #0078d7; padding: 12px; margin-bottom: 12px; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .status-text { font-size: 1.1em; }
    </style>
    """)

    try:
        # ตรวจสอบการตั้งค่า Path ก่อนเริ่มการทำงาน
        export_path = get_or_set_export_path()
        if export_path:
            output.print_html("<p style='color:gray; font-size:12px;'>📁 บันทึกข้อมูลไปที่: {}</p>".format(export_path))
        else:
            output.print_html("<p style='color:orange; font-size:12px;'>⚠️ ข้ามการบันทึกข้อมูล (คุณไม่ได้เลือกโฟลเดอร์)</p>")

        output.print_html("<div class='card'><strong>🔍 กำลังตรวจสอบสถานะเซิร์ฟเวอร์ Autodesk...</strong></div>")

        # ตรวจสอบสถานะครั้งแรก
        response1 = requests.get("https://health.autodesk.com/", timeout=15)
        response1.raise_for_status()
        status1 = get_service_status(response1.text, target_service)
        output.print_html("<p class='status-text'>📊 สถานะเริ่มต้น: <strong>{}</strong></p>".format(status1))

        # รอตรวจสอบครั้งที่สอง (เปลี่ยนจาก Sleep 10 วิเป็น Progress Bar ป้องกัน Revit ค้าง)
        output.print_html("<p>⏳ รอตรวจสอบอีกครั้ง...</p>")
        with forms.ProgressBar(title='กำลังรอตรวจสอบสถานะรอบที่สอง... ({value}%)') as pb:
            for i in range(1, 11):
                time.sleep(1)
                pb.update_progress(i, 10)

        # ตรวจสอบสถานะครั้งที่สอง
        response2 = requests.get("https://health.autodesk.com/", timeout=15)
        response2.raise_for_status()
        status2 = get_service_status(response2.text, target_service)
        output.print_html("<p class='status-text'>📊 สถานะล่าสุด: <strong>{}</strong></p>".format(status2))

        status_pair = "{}-{}".format(status1, status2)
        thai_time = get_thai_time()
        message_template = "{}\n\nบริการ: {}\nสถานะ: {}\n\n{}"

        # ---------------- เงื่อนไขแจ้งเตือนเดิมทั้งหมด ----------------
        if status_pair == "Operational-Operational":
            forms.alert(
                msg=message_template.format("บริการทำงานปกติ", target_service, status2, thai_time),
                title="✅ สถานะปกติ"
            )
            output.print_html("<div class='card' style='border-left-color: #28a745;'><p style='color:green; margin:0;'>✅ บริการทำงานปกติ</p></div>")

        elif status_pair == "Operational-Outage":
            forms.alert(
                msg=message_template.format(
                    "แจ้งเตือน: บริการหยุดทำงาน\n\nบริการกำลังประสบปัญหา ทำให้ไม่สามารถใช้งานได้ชั่วคราว",
                    target_service, status2, thai_time
                ),
                title="🚨 การหยุดทำงานของบริการ"
            )
            output.print_html("<div class='card' style='border-left-color: #dc3545;'><p style='color:red; margin:0;'>🚨 บริการหยุดทำงาน</p></div>")

        elif status_pair == "Outage-Operational":
            forms.alert(
                msg=message_template.format(
                    "แจ้งเตือน: บริการกลับมาใช้งานได้แล้ว", target_service, status2, thai_time
                ),
                title="✅ การกู้คืนบริการ"
            )
            output.print_html("<div class='card' style='border-left-color: #28a745;'><p style='color:green; margin:0;'>✅ บริการกลับมาใช้งานได้แล้ว</p></div>")

        elif status_pair == "Operational-Degraded Performance":
            forms.alert(
                msg=message_template.format(
                    "แจ้งเตือน: ประสิทธิภาพบริการลดลง\n\nบริการยังใช้งานได้แต่ทำงานช้ากว่าปกติ",
                    target_service, status2, thai_time
                ),
                title="⚠️ ประสิทธิภาพลดลง"
            )
            output.print_html("<div class='card' style='border-left-color: #ffc107;'><p style='color:orange; margin:0;'>⚠️ ประสิทธิภาพบริการลดลง</p></div>")

        elif status_pair == "Degraded Performance-Operational":
            forms.alert(
                msg=message_template.format(
                    "แจ้งเตือน: บริการกลับมาทำงานด้วยประสิทธิภาพปกติ",
                    target_service, status2, thai_time
                ),
                title="✅ การกู้คืนประสิทธิภาพ"
            )
            output.print_html("<div class='card' style='border-left-color: #28a745;'><p style='color:green; margin:0;'>✅ ประสิทธิภาพบริการกลับสู่ปกติ</p></div>")

        else:
            forms.alert(
                msg=message_template.format(
                    "แจ้งเตือน: สถานะบริการเปลี่ยนจาก {} เป็น {}".format(status1, status2),
                    target_service,
                    "{} → {}".format(status1, status2),
                    thai_time
                ),
                title="📝 การเปลี่ยนแปลงสถานะ"
            )
            output.print_html(
                "<div class='card' style='border-left-color: #17a2b8;'><p style='margin:0;'>📝 สถานะเปลี่ยนแปลงจาก <strong>{}</strong> เป็น <strong>{}</strong></p></div>".format(status1, status2)
            )

        # บันทึกสถานะลงไฟล์ Log
        save_log(export_path, status1, status2, status_pair)

        # ✅ ปุ่มเปิดลิงก์ภายนอก (คำสั่งเดิมของคุณ)
        output.print_html("<br><b>🔗 เปิดหน้าเว็บสถานะ Autodesk ด้านล่าง:</b><br>")
        if forms.alert(
            msg="ต้องการเปิดหน้า Autodesk Health Dashboard ในเบราว์เซอร์หรือไม่?",
            title="เปิดหน้าเว็บ Autodesk",
            options=["เปิดในเบราว์เซอร์", "ยกเลิก"]
        ) == "เปิดในเบราว์เซอร์":
            script.open_url("https://health.autodesk.com/")

    except requests.RequestException as e:
        msg = "ไม่สามารถเชื่อมต่อเพื่อตรวจสอบสถานะได้\n\nข้อผิดพลาด: {}".format(str(e))
        forms.alert(msg=msg, title="❌ ข้อผิดพลาดในการเชื่อมต่อ")
        output.print_html("<p style='color:red;'>❌ ข้อผิดพลาด: {}</p>".format(str(e)))

    except Exception as e:
        msg = "เกิดข้อผิดพลาดที่ไม่คาดคิด\n\nรายละเอียด: {}".format(str(e))
        forms.alert(msg=msg, title="❌ ข้อผิดพลาด")
        output.print_html("<p style='color:red;'>❌ ข้อผิดพลาด: {}</p>".format(str(e)))


if __name__ == "__main__":
    main()