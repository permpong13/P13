# -*- coding: utf-8 -*-
"""Set Column Levels Parameters"""

__title__ = "Column Levels\nParameters"

from pyrevit import revit, DB, script

doc = revit.doc
output = script.get_output()

output.print_md("## **Column Levels Parameters**")

# ฟังก์ชันหาค่า Parameter
def get_parameter_value(element, param_name):
    """ดึงค่าจากพารามิเตอร์โดยชื่อ"""
    param = element.LookupParameter(param_name)
    if param:
        if param.StorageType == DB.StorageType.Double:
            return param.AsDouble()
        elif param.StorageType == DB.StorageType.ElementId:
            return param.AsElementId()
    return None

# ทำงานเฉพาะกับ Structural Columns
output.print_md("### **ค้นหาโครงสร้างเสา**")

try:
    collector = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType()
    structural_columns = list(collector)
    output.print_md("- **OST_StructuralColumns**: {} elements".format(len(structural_columns)))
    
except Exception as e:
    output.print_md("❌ **Error accessing structural columns**: {}".format(str(e)))
    structural_columns = []

if not structural_columns:
    output.print_md("❌ **ไม่พบโครงสร้างเสา**")
    script.exit()

# เริ่ม Transaction
t = DB.Transaction(doc, "Set Column Levels")
t.Start()

success_bottom_level = 0
success_top_level = 0
success_base_level = 0

for column in structural_columns:
    try:
        # ดึงค่า Base Level, Base Offset, Top Level, Top Offset
        base_level_id = get_parameter_value(column, "Base Level")
        base_offset = get_parameter_value(column, "Base Offset")
        top_level_id = get_parameter_value(column, "Top Level")
        top_offset = get_parameter_value(column, "Top Offset")
        
        # คำนวณ Level_Bottom_of_Column = Base Level Elevation + Base Offset
        if base_level_id and isinstance(base_level_id, DB.ElementId) and base_level_id != DB.ElementId.InvalidElementId and base_offset is not None:
            base_level = doc.GetElement(base_level_id)
            if base_level and isinstance(base_level, DB.Level):
                bottom_level_value = base_level.Elevation + base_offset
                
                # ตั้งค่า Level_Bottom_of_Column
                bottom_param = column.LookupParameter("Level_Bottom_of_Column")
                if bottom_param and bottom_param.StorageType == DB.StorageType.Double:
                    bottom_param.Set(bottom_level_value)
                    success_bottom_level += 1
                
                # ตั้งค่า Base_Level ด้วยค่า Base Level Elevation
                base_elevation_param = column.LookupParameter("Base_Level")
                if base_elevation_param and base_elevation_param.StorageType == DB.StorageType.Double:
                    base_elevation_param.Set(base_level.Elevation)
                    success_base_level += 1
        
        # คำนวณ Level_Top_of_Column = Top Level Elevation + Top Offset
        if top_level_id and isinstance(top_level_id, DB.ElementId) and top_level_id != DB.ElementId.InvalidElementId and top_offset is not None:
            top_level = doc.GetElement(top_level_id)
            if top_level and isinstance(top_level, DB.Level):
                top_level_value = top_level.Elevation + top_offset
                
                # ตั้งค่า Level_Top_of_Column
                top_param = column.LookupParameter("Level_Top_of_Column")
                if top_param and top_param.StorageType == DB.StorageType.Double:
                    top_param.Set(top_level_value)
                    success_top_level += 1
                    
    except Exception as e:
        continue

t.Commit()

output.print_md("### **ผลลัพธ์**")
output.print_md("**โครงสร้างเสาทั้งหมด:** {} รายการ".format(len(structural_columns)))
output.print_md("✅ **ตั้งค่า Base_Level สำเร็จ:** {} รายการ".format(success_base_level))
output.print_md("✅ **ตั้งค่า Level_Top_of_Column สำเร็จ:** {} รายการ".format(success_top_level))
output.print_md("✅ **ตั้งค่า Level_Bottom_of_Column สำเร็จ:** {} รายการ".format(success_bottom_level))

# แสดงตัวอย่างการคำนวณ
if success_bottom_level > 0 or success_top_level > 0:
    sample_columns = []
    for column in structural_columns[:3]:  # แสดง 3 ตัวอย่างแรก
        try:
            base_level_id = get_parameter_value(column, "Base Level")
            base_offset = get_parameter_value(column, "Base Offset")
            top_level_id = get_parameter_value(column, "Top Level")
            top_offset = get_parameter_value(column, "Top Offset")
            
            base_level = None
            top_level = None
            
            if base_level_id and isinstance(base_level_id, DB.ElementId) and base_level_id != DB.ElementId.InvalidElementId:
                base_level = doc.GetElement(base_level_id)
            
            if top_level_id and isinstance(top_level_id, DB.ElementId) and top_level_id != DB.ElementId.InvalidElementId:
                top_level = doc.GetElement(top_level_id)
                
            if (base_level and base_offset is not None) or (top_level and top_offset is not None):
                sample_columns.append((column, base_level, base_offset, top_level, top_offset))
                
                if len(sample_columns) >= 3:
                    break
        except:
            continue
    
    output.print_md("### **ตัวอย่างการคำนวณ**")
    for i, (column, base_level, base_offset, top_level, top_offset) in enumerate(sample_columns):
        output.print_md("{}. **Structural Column** (ID: {})".format(i+1, column.Id))
        
        if base_level and base_offset is not None:
            bottom_value = base_level.Elevation + base_offset
            output.print_md("   - Base Level: {} ({:.3f} ฟุต)".format(base_level.Name, base_level.Elevation))
            output.print_md("   - Base Offset: {:.3f} ฟุต".format(base_offset))
            output.print_md("   - **Level_Bottom_of_Column:** {:.3f} + {:.3f} = {:.3f} ฟุต".format(
                base_level.Elevation, base_offset, bottom_value))
        
        if top_level and top_offset is not None:
            top_value = top_level.Elevation + top_offset
            output.print_md("   - Top Level: {} ({:.3f} ฟุต)".format(top_level.Name, top_level.Elevation))
            output.print_md("   - Top Offset: {:.3f} ฟุต".format(top_offset))
            output.print_md("   - **Level_Top_of_Column:** {:.3f} + {:.3f} = {:.3f} ฟุต".format(
                top_level.Elevation, top_offset, top_value))

# แสดงเสาที่ไม่สามารถคำนวณได้
total_possible = len(structural_columns)
failed_bottom = total_possible - success_bottom_level
failed_top = total_possible - success_top_level
failed_base = total_possible - success_base_level

if failed_bottom > 0 or failed_top > 0 or failed_base > 0:
    output.print_md("### **เสาที่ไม่สามารถคำนวณได้**")
    
    if failed_bottom > 0:
        output.print_md("❌ **ไม่สามารถคำนวณ Level_Bottom_of_Column:** {} รายการ".format(failed_bottom))
        
    if failed_top > 0:
        output.print_md("❌ **ไม่สามารถคำนวณ Level_Top_of_Column:** {} รายการ".format(failed_top))
        
    if failed_base > 0:
        output.print_md("❌ **ไม่สามารถตั้งค่า Base_Level:** {} รายการ".format(failed_base))
    
    # แสดงตัวอย่างสาเหตุ
    failed_samples = 0
    for column in structural_columns:
        if failed_samples >= 3:
            break
            
        missing_params = []
        base_level_id = get_parameter_value(column, "Base Level")
        base_offset = get_parameter_value(column, "Base Offset")
        top_level_id = get_parameter_value(column, "Top Level")
        top_offset = get_parameter_value(column, "Top Offset")
        
        if not base_level_id or base_level_id == DB.ElementId.InvalidElementId:
            missing_params.append("Base Level")
        if base_offset is None:
            missing_params.append("Base Offset")
        if not top_level_id or top_level_id == DB.ElementId.InvalidElementId:
            missing_params.append("Top Level")
        if top_offset is None:
            missing_params.append("Top Offset")
            
        if missing_params:
            output.print_md("- **ID {}**: ขาดพารามิเตอร์ {}".format(column.Id, ", ".join(missing_params)))
            failed_samples += 1