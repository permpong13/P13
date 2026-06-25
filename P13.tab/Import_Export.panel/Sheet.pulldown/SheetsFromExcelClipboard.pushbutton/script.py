# -*- coding: utf-8 -*-
"""
Batch Create Sheets (Auto-Read Clipboard)
Workflow: Copy in Excel -> Run Script -> Confirm -> Create
Fix: Solves 'Only 1 sheet' issue by reading Clipboard directly
"""
import clr
# เพิ่ม Reference สำหรับการอ่าน Clipboard
clr.AddReference('System.Windows.Forms')
from System.Windows.Forms import Clipboard

from pyrevit import revit, DB, forms, script

# --- ส่วนจัดการความจำ (Memory: Titleblock) ---
my_config = script.get_config()
last_tb_key = "last_selected_titleblock_name"

def get_last_tb_name():
    return my_config.get_option(last_tb_key, "")

def save_last_tb_name(tb_name):
    my_config.set_option(last_tb_key, tb_name)
    script.save_config()

# --- ฟังก์ชันดึงชื่อ Titleblock แบบปลอดภัย ---
def get_tb_names(element):
    try:
        p_fam = element.get_Parameter(DB.BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
        fam_name = p_fam.AsString() if p_fam else "Unknown Family"
        p_name = element.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
        type_name = p_name.AsString() if p_name else "Unknown Type"
        return fam_name, type_name
    except Exception:
        return "Error", "Error"

# --- เริ่มการทำงาน ---
doc = revit.doc

# 1. ตรวจสอบ Clipboard ก่อนเลยว่ามีข้อมูลไหม
if not Clipboard.ContainsText():
    forms.alert("ไม่พบข้อความใน Clipboard!\n\nกรุณา Copy ข้อมูลจาก Excel ก่อนรันคำสั่งครับ", exitscript=True)

raw_text = Clipboard.GetText()

# 2. แปลงข้อมูลใน Clipboard เป็นรายการ Sheet
lines = raw_text.strip().splitlines()
sheets_to_create = []

for line in lines:
    # แยกคอลัมน์ด้วย Tab (Excel default) หรือ Comma
    if "\t" in line:
        parts = line.split("\t")
    elif "," in line:
        parts = line.split(",")
    else:
        parts = line.split(None, 1)

    if len(parts) >= 2:
        s_num = parts[0].strip().replace('"', '') # ลบเครื่องหมายคำพูดถ้ามี
        s_name = parts[1].strip().replace('"', '')
        sheets_to_create.append((s_num, s_name))

# ถ้าไม่เจอข้อมูลที่ใช้ได้
if not sheets_to_create:
    forms.alert("รูปแบบข้อมูลไม่ถูกต้อง\nต้องมีอย่างน้อย 2 คอลัมน์ (Number, Name)", exitscript=True)

# 3. เลือก Titleblock (ระบบจำค่าเดิม)
titleblocks = DB.FilteredElementCollector(doc)\
                .OfCategory(DB.BuiltInCategory.OST_TitleBlocks)\
                .WhereElementIsElementType()\
                .ToElements()

if not titleblocks:
    forms.alert("ไม่พบ Titleblock ในโปรเจกต์นี้", exitscript=True)

tb_dict = {}
for tb in titleblocks:
    f_name, t_name = get_tb_names(tb)
    if f_name != "Error":
        key = "{} : {}".format(f_name, t_name)
        tb_dict[key] = tb

default_tb = get_last_tb_name()
if default_tb not in tb_dict:
    default_tb = None 

selected_tb_name = forms.SelectFromList.show(
    sorted(tb_dict.keys()),
    title='พบ {} รายการใน Clipboard! เลือก Titleblock เพื่อสร้าง:'.format(len(sheets_to_create)),
    default=[default_tb] if default_tb else None,
    multiselect=False
)

if selected_tb_name:
    save_last_tb_name(selected_tb_name)
    selected_tb_id = tb_dict[selected_tb_name].Id

    # 4. เริ่มสร้าง Sheet
    t = DB.Transaction(doc, "Batch Create Sheets")
    t.Start()
    
    created_count = 0
    skipped_list = []
    
    # ดึง Sheet เดิมมาเช็ค (Optimized)
    existing_sheets = DB.FilteredElementCollector(doc)\
                        .OfClass(DB.ViewSheet)\
                        .ToElements()
    existing_sheet_nums = {s.SheetNumber for s in existing_sheets}
    
    for s_num, s_name in sheets_to_create:
        if s_num not in existing_sheet_nums:
            try:
                new_sheet = DB.ViewSheet.Create(doc, selected_tb_id)
                new_sheet.SheetNumber = s_num
                new_sheet.Name = s_name
                created_count += 1
                
                existing_sheet_nums.add(s_num) # เพิ่มเข้า set ทันทีกันซ้ำใน Loop
                print("สร้าง: {} - {}".format(s_num, s_name))
            except Exception as e:
                print("Error {}: {}".format(s_num, e))
        else:
            skipped_list.append(s_num)
    
    t.Commit()
    
    # รายงานผล
    msg = "✅ สร้างเสร็จ: {} แผ่น".format(created_count)
    if skipped_list:
        msg += "\n⚠️ ข้าม (มีแล้ว): {}".format(", ".join(skipped_list))
    
    forms.alert(msg, title="Result")