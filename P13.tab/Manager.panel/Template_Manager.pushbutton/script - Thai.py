# -*- coding: utf-8 -*-
"""View Template Manager - Ultimate Pro (Full Version)"""
__title__ = "จัดการ View Template (All-in-One)"
__author__ = "Permpong & Gemini"

import clr
import os
import csv
import codecs
from datetime import datetime

clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
from pyrevit import forms, script

doc = __revit__.ActiveUIDocument.Document
output = script.get_output()
cfg = script.get_config() # สำหรับจดจำค่าการตั้งค่า

# --------------------------------------------------------
# ⚙️ CORE ENGINE (วิเคราะห์ข้อมูล)
# --------------------------------------------------------

def get_template_data():
    """วิเคราะห์ Template ทั้งหมดและแยกกลุ่มตามการใช้งานจริง"""
    all_tpls = [v for v in FilteredElementCollector(doc).OfClass(View) if v.IsTemplate]
    used_list, unused_list = [], []

    if not all_tpls:
        return [], []

    with forms.ProgressBar(title="กำลังวิเคราะห์การใช้งาน...", cancellable=True) as pb:
        for i, tpl in enumerate(all_tpls):
            if pb.cancelled: break
            pb.update_progress(i + 1, len(all_tpls))

            # ใช้ Filter หา View ที่ผูกกับ Template นี้
            rule = ParameterFilterRuleFactory.CreateEqualsRule(ElementId(BuiltInParameter.VIEW_TEMPLATE), tpl.Id)
            count = FilteredElementCollector(doc).OfClass(View).WherePasses(ElementParameterFilter(rule)).GetElementCount()

            data = {'el': tpl, 'name': tpl.Name, 'count': count, 'id': tpl.Id}
            if count > 0:
                used_list.append(data)
            else:
                unused_list.append(data)
    
    return used_list, unused_list

# --------------------------------------------------------
# 🛠️ TOOLS (ฟังก์ชันจัดการเพิ่มเติม)
# --------------------------------------------------------

def bulk_rename(all_tpls):
    """เปลี่ยนชื่อ Template แบบกลุ่ม (Prefix / Find & Replace)"""
    prefix = forms.ask_for_string(default="", prompt="ใส่คำนำหน้า (Prefix):", title="Bulk Rename")
    find_str = forms.ask_for_string(default="", prompt="คำที่ต้องการหา (Find):", title="Bulk Rename")
    replace_str = forms.ask_for_string(default="", prompt="คำที่ต้องการแทนที่ (Replace):", title="Bulk Rename")

    t = Transaction(doc, "Bulk Rename Templates")
    t.Start()
    for tpl in all_tpls:
        new_name = tpl['name']
        if find_str: new_name = new_name.replace(find_str, replace_str)
        if prefix: new_name = prefix + new_name
        
        try: tpl['el'].Name = new_name
        except: pass
    t.Commit()
    forms.alert("เปลี่ยนชื่อเรียบร้อยแล้ว")

def duplicate_templates(selected_tpls):
    """คัดลอก Template ที่เลือกพร้อมตั้งชื่อใหม่"""
    suffix = forms.ask_for_string(default="_Copy", prompt="ใส่คำต่อท้ายชื่อ:", title="Duplicate")
    
    t = Transaction(doc, "Duplicate Templates")
    t.Start()
    for tpl in selected_tpls:
        try:
            new_tpl_id = tpl['el'].Duplicate(ViewDuplicateOption.Duplicate)
            doc.GetElement(new_tpl_id).Name = tpl['name'] + suffix
        except: pass
    t.Commit()
    forms.alert("คัดลอกสำเร็จ")

# --------------------------------------------------------
# 📊 EXPORT SYSTEM (ระบบส่งออกรายงาน)
# --------------------------------------------------------

def export_to_excel(all_data):
    """ส่งออกรายชื่อ Template เป็น CSV โดยจดจำโฟลเดอร์ล่าสุด"""
    export_dir = getattr(cfg, "export_path", None)
    
    # หากไม่มีการตั้งค่า Path หรือ Path เดิมหายไป ให้เลือกใหม่
    if not export_dir or not os.path.exists(export_dir):
        export_dir = forms.pick_folder(title="เลือก Folder สำหรับ Export (ระบบจะจำค่านี้ไว้)")
        if export_dir:
            cfg.export_path = export_dir
            script.save_config()
        else: return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = os.path.join(export_dir, "ViewTemplate_Report_{}.csv".format(timestamp))
    
    try:
        with codecs.open(file_path, 'w', 'utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["Template Name", "Status", "Usage Count", "Element ID"])
            for tpl in sorted(all_data, key=lambda k: k['name']):
                status = "Active" if tpl['count'] > 0 else "Unused"
                writer.writerow([tpl['name'], status, tpl['count'], tpl['id'].IntegerValue])
                
        if forms.alert("ส่งออกสำเร็จที่:\n{}\n\nเปิดโฟลเดอร์เลยไหม?".format(file_path), yes=True, no=True):
            os.startfile(export_dir)
    except Exception as e:
        forms.alert("Error: {}".format(str(e)))

# --------------------------------------------------------
# 🎨 UI & DASHBOARD
# --------------------------------------------------------

def print_dashboard(used, unused):
    """สร้างตารางรายงาน (ลบ output.clear() เพื่อป้องกัน Error ใน Revit 2026)"""
    output.print_md("# 🏢 View Template Pro Dashboard")
    output.insert_divider()
    
    header = ["สถานะการใช้งาน", "จำนวน", "ข้อแนะนำ"]
    table_data = [
        ["✅ ถูกใช้งานอยู่ (Active)", str(len(used)), "ข้อมูลสำคัญ ห้ามลบ"],
        ["⚠️ ไม่ได้ใช้งาน (Unused)", str(len(unused)), "ลบเพื่อลดขนาดไฟล์ได้"]
    ]
    output.print_table(table_data, columns=header)
    output.print_md("> **รวมทั้งหมด:** {} รายการ".format(len(used) + len(unused)))
    output.insert_divider()

# --------------------------------------------------------
# 🚀 MAIN COMMANDS
# --------------------------------------------------------

def run_manager():
    used, unused = get_template_data()
    all_data = used + unused
    
    if not all_data:
        forms.alert("ไม่พบ View Template ในโปรเจคนี้", exitscript=True)

    print_dashboard(used, unused)

    ops = {
        "1. ดูรายละเอียด Template ที่ใช้งานอยู่": "SHOW_USED",
        "2. คัดลอก Template (Duplicate)": "DUPLICATE",
        "3. เปลี่ยนชื่อกลุ่ม (Bulk Rename)": "RENAME",
        "4. เลือกและลบ Template ที่ไม่ได้ใช้ (Cleanup)": "DELETE_UNUSED",
        "5. 📊 ส่งออกรายงานเป็นไฟล์ Excel (CSV)": "EXPORT",
        "6. ⚙️ ตั้งค่า Folder สำหรับ Export ใหม่": "SET_PATH",
        "7. ปิดโปรแกรม": "EXIT"
    }
    
    choice = forms.CommandSwitchWindow.show(ops.keys(), title="เลือกการดำเนินการ (View Template Pro)")
    
    if not choice or ops[choice] == "EXIT": return

    if ops[choice] == "SHOW_USED":
        display = sorted(["🔹 {} (ใช้ใน {} views)".format(i['name'], i['count']) for i in used])
        forms.SelectFromList.show(display, title="รายการที่ใช้งานอยู่", button_name="รับทราบ")
        run_manager()

    elif ops[choice] == "DUPLICATE":
        selected = forms.SelectFromList.show([i['name'] for i in all_data], multiselect=True, title="เลือก Template ที่จะ Copy")
        if selected:
            to_dup = [i for i in all_data if i['name'] in selected]
            duplicate_templates(to_dup)
        run_manager()

    elif ops[choice] == "RENAME":
        selected = forms.SelectFromList.show([i['name'] for i in all_data], multiselect=True, title="เลือก Template ที่จะเปลี่ยนชื่อ")
        if selected:
            to_rename = [i for i in all_data if i['name'] in selected]
            bulk_rename(to_rename)
        run_manager()

    elif ops[choice] == "DELETE_UNUSED":
        if not unused:
            forms.alert("ไม่มีรายการที่ไม่ได้ใช้งาน")
        else:
            unused_names = sorted([i['name'] for i in unused])
            selected = forms.SelectFromList.show(unused_names, title="ลบ Unused Templates", multiselect=True)
            if selected and forms.alert("ยืนยันการลบ {} รายการ?".format(len(selected)), yes=True, no=True):
                to_del = [i['el'] for i in unused if i['name'] in selected]
                with Transaction(doc, "Cleanup Unused Templates") as t:
                    t.Start()
                    for tpl in to_del: doc.Delete(tpl.Id)
                    t.Commit()
        run_manager()
        
    elif ops[choice] == "EXPORT":
        export_to_excel(all_data)
        run_manager()

    elif ops[choice] == "SET_PATH":
        new_dir = forms.pick_folder(title="เลือก Folder ใหม่สำหรับบันทึกไฟล์")
        if new_dir:
            cfg.export_path = new_dir
            script.save_config()
            forms.alert("อัปเดต Path เรียบร้อย!")
        run_manager()

if __name__ == "__main__":
    run_manager()