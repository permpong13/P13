# -*- coding: utf-8 -*-
"""Set Column Levels Parameters"""

__title__ = "Column Levels\nParameters"

import os
import tempfile
from pyrevit import revit, DB, script, forms

doc = revit.doc
app = doc.Application
output = script.get_output()

output.print_md("## **Column Levels Parameters**")

# =====================================================
# ฟังก์ชันหาค่า Parameter
# =====================================================
def get_parameter_value(element, param_name):
    """ดึงค่าจากพารามิเตอร์โดยชื่อ"""
    param = element.LookupParameter(param_name)
    if param:
        if param.StorageType == DB.StorageType.Double:
            return param.AsDouble()
        elif param.StorageType == DB.StorageType.ElementId:
            return param.AsElementId()
    return None

# =====================================================
# ฟังก์ชันตรวจสอบและสร้าง Shared Parameter อัตโนมัติ
# =====================================================
def setup_parameter(doc, app, param_name, param_type, all_cat_names):
    existing_def = None
    existing_binding = None
    
    iterator = doc.ParameterBindings.ForwardIterator()
    while iterator.MoveNext():
        if iterator.Key.Name == param_name:
            existing_def = iterator.Key
            existing_binding = iterator.Current
            break
            
    # ถ้ามี Parameter อยู่แล้ว เช็คและอัปเดต Categories ให้ครอบคลุม
    if existing_def and existing_binding:
        cat_set = existing_binding.Categories
        needs_update = False
        for c in all_cat_names:
            try:
                b_cat = getattr(DB.BuiltInCategory, c)
                cat = doc.Settings.Categories.get_Item(b_cat)
                if cat and cat.AllowsBoundParameters and not cat_set.Contains(cat):
                    cat_set.Insert(cat)
                    needs_update = True
            except: pass
            
        if needs_update:
            t_rebind = DB.Transaction(doc, "Update {} Categories".format(param_name))
            t_rebind.Start()
            try:
                new_binding = app.Create.NewInstanceBinding(cat_set)
                doc.ParameterBindings.ReInsert(existing_def, new_binding)
                t_rebind.Commit()
                return "updated"
            except:
                t_rebind.RollBack()
                return "exists"
        return "exists"
            
    # หากไม่มี ให้สร้าง Shared Parameter ขึ้นมาใหม่
    sp_file = app.OpenSharedParameterFile()
    original_sp = app.SharedParametersFilename
    
    if not sp_file:
        temp_dir = tempfile.gettempdir()
        temp_sp_path = os.path.join(temp_dir, "Auto_SharedParams_Revit.txt")
        if not os.path.exists(temp_sp_path):
            with open(temp_sp_path, "w") as f: f.write("") 
        try:
            app.SharedParametersFilename = temp_sp_path
            sp_file = app.OpenSharedParameterFile()
        except: pass
            
    if not sp_file: return "sp_error"
        
    target_def = None
    for group in sp_file.Groups:
        for definition in group.Definitions:
            if definition.Name == param_name:
                target_def = definition
                break
        if target_def: break
            
    if not target_def:
        group_name = "Data"
        group = sp_file.Groups.get_Item(group_name)
        if not group: group = sp_file.Groups.Create(group_name)
        try:
            if param_type == "Text":
                opt = DB.ExternalDefinitionCreationOptions(param_name, DB.SpecTypeId.String.Text)
            else:
                opt = DB.ExternalDefinitionCreationOptions(param_name, DB.SpecTypeId.Length)
            target_def = group.Definitions.Create(opt)
        except AttributeError:
            if param_type == "Text":
                opt = DB.ExternalDefinitionCreationOptions(param_name, DB.ParameterType.Text)
            else:
                opt = DB.ExternalDefinitionCreationOptions(param_name, DB.ParameterType.Length)
            target_def = group.Definitions.Create(opt)
            
    if original_sp and app.SharedParametersFilename != original_sp:
        try: app.SharedParametersFilename = original_sp
        except: pass
            
    if not target_def: return "def_not_found"
        
    cat_set = app.Create.NewCategorySet()
    for c in all_cat_names:
        try:
            b_cat = getattr(DB.BuiltInCategory, c)
            cat = doc.Settings.Categories.get_Item(b_cat)
            if cat and cat.AllowsBoundParameters:
                cat_set.Insert(cat)
        except: pass
            
    if cat_set.IsEmpty: return "no_categories"
        
    binding = app.Create.NewInstanceBinding(cat_set)
    t_param = DB.Transaction(doc, "Setup Parameter: {}".format(param_name))
    t_param.Start()
    try:
        try: doc.ParameterBindings.Insert(target_def, binding, DB.GroupTypeId.Data)
        except AttributeError: doc.ParameterBindings.Insert(target_def, binding, DB.BuiltInParameterGroup.PG_DATA)
        t_param.Commit()
        return "created"
    except:
        t_param.RollBack()
        return "bind_error"

# =====================================================
# เริ่มการทำงานหลัก
# =====================================================
output.print_md("### **ตรวจสอบและเตรียม Parameters**")
cat_columns = ["OST_StructuralColumns"]

# สร้าง/ตรวจสอบ พารามิเตอร์ทั้ง 3 ตัว
status_base = setup_parameter(doc, app, "Base_Level", "Text", cat_columns)
status_bottom = setup_parameter(doc, app, "Level_Bottom_of_Column", "Length", cat_columns)
status_top = setup_parameter(doc, app, "Level_Top_of_Column", "Length", cat_columns)

if status_base == "created": output.print_md("✅ **Base_Level** (Text) ถูกสร้างอัตโนมัติ")
elif status_base in ["exists", "updated"]: output.print_md("✅ พบพารามิเตอร์ **Base_Level** พร้อมใช้งาน")

if status_bottom == "created": output.print_md("✅ **Level_Bottom_of_Column** ถูกสร้างอัตโนมัติ")
if status_top == "created": output.print_md("✅ **Level_Top_of_Column** ถูกสร้างอัตโนมัติ")

output.print_md("---")
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

# =====================================================
# เริ่ม Transaction เขียนค่าลงโมเดล
# =====================================================
t = DB.Transaction(doc, "Set Column Levels")
t.Start()

# เปิดอนุญาตให้ Base_Level เขียนค่าลงใน Group ได้ทันที
varies_across_groups = False
iterator = doc.ParameterBindings.ForwardIterator()
while iterator.MoveNext():
    definition = iterator.Key
    if definition.Name == "Base_Level" and isinstance(definition, DB.InternalDefinition):
        try:
            if not definition.VariesAcrossGroups: definition.SetAllowVaryBetweenGroups(doc, True)
            varies_across_groups = definition.VariesAcrossGroups
        except:
            varies_across_groups = getattr(definition, 'VariesAcrossGroups', False)
        break

success_bottom_level = 0
success_top_level = 0
success_base_level = 0
total_elements = len(structural_columns)

# ทำงานผ่าน Progress Bar
with forms.ProgressBar(title='กำลังตั้งค่า Column Levels... ({value} จาก {max_value})', cancellable=True) as pb:
    for index, column in enumerate(structural_columns):
        if pb.cancelled:
            break
            
        try:
            base_level_id = get_parameter_value(column, "Base Level")
            base_offset = get_parameter_value(column, "Base Offset")
            top_level_id = get_parameter_value(column, "Top Level")
            top_offset = get_parameter_value(column, "Top Offset")
            
            # คำนวณ Level_Bottom_of_Column = Base Level Elevation + Base Offset
            if base_level_id and isinstance(base_level_id, DB.ElementId) and base_level_id != DB.ElementId.InvalidElementId and base_offset is not None:
                base_level = doc.GetElement(base_level_id)
                if base_level and isinstance(base_level, DB.Level):
                    bottom_level_value = base_level.Elevation + base_offset
                    
                    bottom_param = column.LookupParameter("Level_Bottom_of_Column")
                    if bottom_param and bottom_param.StorageType == DB.StorageType.Double and not bottom_param.IsReadOnly:
                        try:
                            bottom_param.Set(bottom_level_value)
                            success_bottom_level += 1
                        except: pass
                    
                    # ตั้งค่า Base_Level (รองรับทั้ง Double และ String เพื่อกัน Error)
                    base_elevation_param = column.LookupParameter("Base_Level")
                    if base_elevation_param and not base_elevation_param.IsReadOnly:
                        try:
                            if base_elevation_param.StorageType == DB.StorageType.String:
                                elev_m = base_level.Elevation * 0.3048
                                base_elevation_param.Set("{:.3f}".format(elev_m))
                                success_base_level += 1
                            elif base_elevation_param.StorageType == DB.StorageType.Double:
                                base_elevation_param.Set(base_level.Elevation)
                                success_base_level += 1
                        except: pass
            
            # คำนวณ Level_Top_of_Column = Top Level Elevation + Top Offset
            if top_level_id and isinstance(top_level_id, DB.ElementId) and top_level_id != DB.ElementId.InvalidElementId and top_offset is not None:
                top_level = doc.GetElement(top_level_id)
                if top_level and isinstance(top_level, DB.Level):
                    top_level_value = top_level.Elevation + top_offset
                    
                    top_param = column.LookupParameter("Level_Top_of_Column")
                    if top_param and top_param.StorageType == DB.StorageType.Double and not top_param.IsReadOnly:
                        try:
                            top_param.Set(top_level_value)
                            success_top_level += 1
                        except: pass
                        
        except Exception as e:
            continue
            
        pb.update_progress(index + 1, total_elements)

t.Commit()

# =====================================================
# สรุปผลลัพธ์การทำงาน (ฟังก์ชันเดิมของคุณ)
# =====================================================
output.print_md("### **ผลลัพธ์**")
output.print_md("**โครงสร้างเสาทั้งหมด:** {} รายการ".format(total_elements))
output.print_md("✅ **ตั้งค่า Base_Level สำเร็จ:** {} รายการ".format(success_base_level))
output.print_md("✅ **ตั้งค่า Level_Top_of_Column สำเร็จ:** {} รายการ".format(success_top_level))
output.print_md("✅ **ตั้งค่า Level_Bottom_of_Column สำเร็จ:** {} รายการ".format(success_bottom_level))

if success_bottom_level > 0 or success_top_level > 0:
    sample_columns = []
    for column in structural_columns[:3]:  
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

failed_bottom = total_elements - success_bottom_level
failed_top = total_elements - success_top_level
failed_base = total_elements - success_base_level

if failed_bottom > 0 or failed_top > 0 or failed_base > 0:
    output.print_md("### **เสาที่ไม่สามารถคำนวณได้**")
    
    if failed_bottom > 0:
        output.print_md("❌ **ไม่สามารถคำนวณ Level_Bottom_of_Column:** {} รายการ".format(failed_bottom))
        
    if failed_top > 0:
        output.print_md("❌ **ไม่สามารถคำนวณ Level_Top_of_Column:** {} รายการ".format(failed_top))
        
    if failed_base > 0:
        output.print_md("❌ **ไม่สามารถตั้งค่า Base_Level:** {} รายการ".format(failed_base))
    
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