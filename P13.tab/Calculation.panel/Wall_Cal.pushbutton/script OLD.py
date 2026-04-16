# -*- coding: utf-8 -*-
"""Update Wall Parameters: Top of Wall Fix for Revit 2026"""

__title__ = "Wall Top\nCal"

from pyrevit import revit, DB, script, forms

doc = revit.doc
output = script.get_output()

# รวบรวมผนังทั้งหมด
walls = DB.FilteredElementCollector(doc)\
          .OfCategory(DB.BuiltInCategory.OST_Walls)\
          .WhereElementIsNotElementType()\
          .ToElements()

if not walls:
    forms.alert("ไม่พบผนังในโมเดล", exitscript=True)

output.print_md("# **อัปเดตพารามิเตอร์ผนัง (Fixed Version)**")

# เริ่ม Transaction
with revit.Transaction("Set Wall Top of Wall"):
    success_count = 0
    error_log = []

    for wall in walls:
        try:
            # --- 1. ดึง Base Level Elevation ---
            # ลองดึงจากพารามิเตอร์มาตรฐานของผนัง
            base_lvl_param = wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_CONSTRAINT)
            if not base_lvl_param:
                continue
                
            base_lvl_id = base_lvl_param.AsElementId()
            if base_lvl_id == DB.ElementId.InvalidElementId:
                continue
            
            base_level_el = doc.GetElement(base_lvl_id)
            base_elev = base_level_el.Elevation

            # --- 2. ดึง Base Offset ---
            # ใช้ BuiltInParameter ที่ถูกต้องสำหรับ Walls
            base_offset = wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET).AsDouble()

            # --- 3. ดึง Unconnected Height (แก้ไขจุดที่ Error) ---
            # ลองดึงจากพารามิเตอร์ "Unconnected Height" โดยตรง
            height_param = wall.LookupParameter("Unconnected Height")
            if not height_param:
                # ถ้าหาไม่เจอ ให้ลองดึงจาก BuiltIn (ชื่อเต็มใน API)
                height_param = wall.get_Parameter(DB.BuiltInParameter.WALL_USER_HEIGHT_PARAM)
            
            if not height_param or not height_param.HasValue:
                continue
            
            unconnected_height = height_param.AsDouble()

            # --- 4. เริ่มการคำนวณสูตร ---
            # สูตร: Top of Wall = Base Level + Base Offset + Unconnected Height
            top_of_wall_val = base_elev + base_offset + unconnected_height
            bottom_val = base_elev + base_offset

            # --- 5. เขียนค่าลง Parameter ---
            
            # (A) Base_Level
            p_base = wall.LookupParameter("Base_Level")
            if p_base and not p_base.IsReadOnly:
                p_base.Set(base_elev)

            # (B) Level_Bottom_of_Column
            p_bottom = wall.LookupParameter("Level_Bottom_of_Column")
            if p_bottom and not p_bottom.IsReadOnly:
                p_bottom.Set(bottom_val)

            # (C) Top of Wall (เป้าหมายหลัก)
            p_top = wall.LookupParameter("Top of Wall")
            if p_top and not p_top.IsReadOnly:
                p_top.Set(top_of_wall_val)
                success_count += 1
            elif not p_top:
                error_log.append("Wall ID {}: ไม่พบ Parameter 'Top of Wall'".format(wall.Id.Value))

        except Exception as e:
            error_log.append("Wall ID {}: {}".format(wall.Id.Value, str(e)))

# --- สรุปผล ---
output.print_md("---")
output.print_md("### **สรุปการดำเนินการ**")
output.print_md("✅ อัปเดตสำเร็จ: **{}** รายการ".format(success_count))

if error_log:
    output.print_md("### ⚠️ **ข้อผิดพลาดที่พบ**")
    # แสดงเฉพาะ Error ที่ไม่ซ้ำกันเพื่อลดความยาว
    unique_errors = list(set(error_log))
    for log in unique_errors[:15]:
        output.print_md("- " + log)