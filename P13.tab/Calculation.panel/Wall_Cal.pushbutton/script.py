# -*- coding: utf-8 -*-
"""Update Wall Parameters: Top of Wall Fix for Revit 2026"""

__title__ = "Wall Top\nCal"

import os
import tempfile
from pyrevit import revit, DB, script, forms

doc = revit.doc
app = doc.Application
output = script.get_output()

output.print_md("# **อัปเดตพารามิเตอร์ผนัง (Fixed Version)**")

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
# ตรวจสอบและเตรียม Parameters
# =====================================================
output.print_md("### **ตรวจสอบและเตรียม Parameters (ผนัง)**")
cat_walls = ["OST_Walls"]

status_base = setup_parameter(doc, app, "Base_Level", "Text", cat_walls)
status_bottom = setup_parameter(doc, app, "Level_Bottom_of_Column", "Length", cat_walls) # คุณใช้ชื่อนี้กับผนังด้วย จึงคงไว้ให้
status_top = setup_parameter(doc, app, "Top of Wall", "Length", cat_walls)

if status_base == "created": output.print_md("✅ **Base_Level** (Text) ถูกสร้างอัตโนมัติ")
elif status_base in ["exists", "updated"]: output.print_md("✅ พบพารามิเตอร์ **Base_Level** พร้อมใช้งาน")

if status_bottom == "created": output.print_md("✅ **Level_Bottom_of_Column** ถูกสร้างอัตโนมัติ")
if status_top == "created": output.print_md("✅ **Top of Wall** ถูกสร้างอัตโนมัติ")
output.print_md("---")


# =====================================================
# ค้นหาองค์ประกอบผนัง
# =====================================================
walls = DB.FilteredElementCollector(doc)\
          .OfCategory(DB.BuiltInCategory.OST_Walls)\
          .WhereElementIsNotElementType()\
          .ToElements()

if not walls:
    forms.alert("ไม่พบผนังในโมเดล", exitscript=True)

output.print_md("### **ค้นพบผนังทั้งหมด: {} รายการ**".format(len(walls)))


# =====================================================
# เริ่ม Transaction เขียนค่าลงโมเดล
# =====================================================
t = DB.Transaction(doc, "Set Wall Top of Wall")
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

success_count = 0
error_log = []
total_elements = len(walls)
is_cancelled = False

# เริ่มใช้งาน Progress Bar
with forms.ProgressBar(title='กำลังคำนวณพารามิเตอร์ผนัง... ({value} จาก {max_value})', cancellable=True) as pb:
    for index, wall in enumerate(walls):
        if pb.cancelled:
            is_cancelled = True
            break
            
        try:
            # --- 1. ดึง Base Level Elevation ---
            base_lvl_param = wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_CONSTRAINT)
            if not base_lvl_param:
                continue
                
            base_lvl_id = base_lvl_param.AsElementId()
            if base_lvl_id == DB.ElementId.InvalidElementId:
                continue
            
            base_level_el = doc.GetElement(base_lvl_id)
            base_elev = base_level_el.Elevation

            # --- 2. ดึง Base Offset ---
            base_offset_param = wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET)
            base_offset = base_offset_param.AsDouble() if base_offset_param else 0.0

            # --- 3. ดึง Unconnected Height ---
            height_param = wall.LookupParameter("Unconnected Height")
            if not height_param:
                height_param = wall.get_Parameter(DB.BuiltInParameter.WALL_USER_HEIGHT_PARAM)
            
            if not height_param or not height_param.HasValue:
                continue
            
            unconnected_height = height_param.AsDouble()

            # --- 4. เริ่มการคำนวณสูตร ---
            top_of_wall_val = base_elev + base_offset + unconnected_height
            bottom_val = base_elev + base_offset

            # --- 5. เขียนค่าลง Parameter ---
            
            # (A) Base_Level (รองรับชนิด Text เพื่อแก้ปัญหา Group)
            p_base = wall.LookupParameter("Base_Level")
            if p_base and not p_base.IsReadOnly:
                # เช็คสถานะ Group สำหรับพารามิเตอร์ Text
                is_in_group = hasattr(wall, 'GroupId') and wall.GroupId != DB.ElementId.InvalidElementId
                if is_in_group and not varies_across_groups:
                    pass # หากติดล็อก Group ข้ามเฉพาะตัวแปรนี้ไป
                else:
                    if p_base.StorageType == DB.StorageType.String:
                        elev_m = base_elev * 0.3048
                        p_base.Set("{:.3f}".format(elev_m))
                    elif p_base.StorageType == DB.StorageType.Double:
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
            
        pb.update_progress(index + 1, total_elements)

t.Commit()


# =====================================================
# สรุปผลการดำเนินการ
# =====================================================
output.print_md("---")
output.print_md("### **สรุปการดำเนินการ**")

if is_cancelled:
    output.print_md("🛑 **ผู้ใช้กดยกเลิกการทำงานกลางคัน! (บันทึกเฉพาะส่วนที่ทำเสร็จแล้ว)**")

output.print_md("✅ อัปเดตสำเร็จ: **{}** รายการ จากทั้งหมด {} รายการ".format(success_count, total_elements))

if error_log:
    output.print_md("### ⚠️ **ข้อผิดพลาดที่พบ**")
    # แสดงเฉพาะ Error ที่ไม่ซ้ำกันเพื่อลดความยาว
    unique_errors = list(set(error_log))
    for log in unique_errors[:15]:
        output.print_md("- " + log)

output.print_md("\n**เสร็จสิ้น — อัปเดตข้อมูลพารามิเตอร์ผนังเรียบร้อย**")