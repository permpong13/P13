# -*- coding: utf-8 -*-
"""Update Lighting Fixtures Parameters: Top of Lighting_Fixtures Fix for Revit 2026"""

__title__ = "Lighting\nTop Cal"

import os
import tempfile
from pyrevit import revit, DB, script, forms

doc = revit.doc
app = doc.Application
output = script.get_output()

output.print_md("# **อัปเดตพารามิเตอร์ดวงโคม (Lighting Fixtures Version)**")

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
output.print_md("### **ตรวจสอบและเตรียม Parameters (Lighting)**")
# รวม Lighting Fixtures และ Lighting Devices เพื่อไม่ให้ตกหล่น
cat_lighting = ["OST_LightingFixtures", "OST_LightingDevices"]

status_base = setup_parameter(doc, app, "Base_Level", "Text", cat_lighting)
status_bottom = setup_parameter(doc, app, "Level_Bottom_of_Column", "Length", cat_lighting)
status_top = setup_parameter(doc, app, "Top of Lighting_Fixtures", "Length", cat_lighting)

if status_base == "created": output.print_md("✅ **Base_Level** (Text) ถูกสร้างอัตโนมัติ")
elif status_base in ["exists", "updated"]: output.print_md("✅ พบพารามิเตอร์ **Base_Level** พร้อมใช้งาน")

if status_bottom == "created": output.print_md("✅ **Level_Bottom_of_Column** ถูกสร้างอัตโนมัติ")
if status_top == "created": output.print_md("✅ **Top of Lighting_Fixtures** ถูกสร้างอัตโนมัติ")
output.print_md("---")


# =====================================================
# ค้นหาองค์ประกอบดวงโคม
# =====================================================
# ใช้ FilteredElementCollector ดึงทั้ง 2 หมวดหมู่
collector = DB.FilteredElementCollector(doc).WhereElementIsNotElementType()
filter_fixtures = DB.ElementCategoryFilter(DB.BuiltInCategory.OST_LightingFixtures)
filter_devices = DB.ElementCategoryFilter(DB.BuiltInCategory.OST_LightingDevices)
or_filter = DB.LogicalOrFilter(filter_fixtures, filter_devices)

fixtures = collector.WherePasses(or_filter).ToElements()

if not fixtures:
    forms.alert("ไม่พบ Lighting Fixtures หรือ Lighting Devices ในโมเดล", exitscript=True)

output.print_md("### **ค้นพบดวงโคมและอุปกรณ์ทั้งหมด: {} รายการ**".format(len(fixtures)))


# =====================================================
# เริ่ม Transaction เขียนค่าลงโมเดล
# =====================================================
t = DB.Transaction(doc, "Set Top of Lighting Fixtures")
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
total_elements = len(fixtures)
is_cancelled = False

# เริ่มใช้งาน Progress Bar
with forms.ProgressBar(title='กำลังคำนวณพารามิเตอร์ดวงโคม... ({value} จาก {max_value})', cancellable=True) as pb:
    for index, item in enumerate(fixtures):
        if pb.cancelled:
            is_cancelled = True
            break
            
        try:
            base_elev = 0.0
            top_val = 0.0
            
            # --- 1. พยายามหาค่าระดับอ้างอิง (Base Level Elevation) ---
            level_id = item.LevelId
            if level_id == DB.ElementId.InvalidElementId:
                # ลองหาจาก Schedule Level
                sched_param = item.get_Parameter(DB.BuiltInParameter.SCHEDULE_LEVEL_PARAM)
                if sched_param: level_id = sched_param.AsElementId()
                
            if level_id != DB.ElementId.InvalidElementId:
                lvl_el = doc.GetElement(level_id)
                if lvl_el: base_elev = lvl_el.Elevation

            # --- 2. คำนวณหาตำแหน่งความสูงจริง (Top Value) ---
            # ดวงโคมส่วนใหญ่เป็น Point Location
            loc = item.Location
            if isinstance(loc, DB.LocationPoint):
                top_val = loc.Point.Z
            else:
                # กรณีหา LocationPoint ไม่ได้ ให้ใช้ Base Level + Elevation/Offset param
                offset_param = item.get_Parameter(DB.BuiltInParameter.INSTANCE_ELEVATION_PARAM)
                if not offset_param:
                    offset_param = item.get_Parameter(DB.BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM)
                
                offset_val = offset_param.AsDouble() if offset_param else 0.0
                top_val = base_elev + offset_val

            # --- 3. เขียนค่าลง Parameter ---
            
            # (A) Base_Level
            p_base = item.LookupParameter("Base_Level")
            if p_base and not p_base.IsReadOnly:
                is_in_group = hasattr(item, 'GroupId') and item.GroupId != DB.ElementId.InvalidElementId
                if is_in_group and not varies_across_groups:
                    pass 
                else:
                    if p_base.StorageType == DB.StorageType.String:
                        elev_m = base_elev * 0.3048
                        p_base.Set("{:.3f}".format(elev_m))
                    elif p_base.StorageType == DB.StorageType.Double:
                        p_base.Set(base_elev)

            # (B) Level_Bottom_of_Column (ใช้ค่าระดับ Level ของดวงโคม)
            p_bottom = item.LookupParameter("Level_Bottom_of_Column")
            if p_bottom and not p_bottom.IsReadOnly:
                p_bottom.Set(base_elev)

            # (C) Top of Lighting_Fixtures (เป้าหมายหลัก)
            p_top = item.LookupParameter("Top of Lighting_Fixtures")
            if p_top and not p_top.IsReadOnly:
                p_top.Set(top_val)
                success_count += 1
            elif not p_top:
                error_log.append("ID {}: ไม่พบ Parameter 'Top of Lighting_Fixtures'".format(item.Id.Value))

        except Exception as e:
            error_log.append("ID {}: {}".format(item.Id.Value, str(e)))
            
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
    unique_errors = list(set(error_log))
    for log in unique_errors[:15]:
        output.print_md("- " + log)

output.print_md("\n**เสร็จสิ้น — อัปเดตข้อมูลพารามิเตอร์ Lighting เรียบร้อย**")