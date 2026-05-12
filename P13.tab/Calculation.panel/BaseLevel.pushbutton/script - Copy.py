# -*- coding: utf-8 -*-
"""Set Base Level - Text Parameter (Optimized for Revit 2024+)"""

__title__ = "Base_Level\nParameter"

import os
import tempfile
from System.Collections.Generic import List
from pyrevit import revit, DB, script, forms

doc = revit.doc
app = doc.Application
output = script.get_output()

output.print_md("## **Base Level - งานโครงสร้าง สถาปัตย์ และงานระบบ MEP**")

# =====================================================
# รายการ BuiltInCategory
# =====================================================
structural_categories = [
    "OST_StructuralColumns", "OST_StructuralFraming", "OST_StructuralFoundation",
    "OST_StructuralRebar", "OST_StructuralConnections", "OST_StructuralStiffener",
    "OST_StructuralTrusses", "OST_StructuralBracing", "OST_AreaRein",
    "OST_PathRein", "OST_FabricReinforcement", "OST_StructuralAnchor"
]

architectural_categories = [
    "OST_Walls", "OST_Floors", "OST_Doors", "OST_Windows", "OST_Stairs",
    "OST_Railings", "OST_Ramps", "OST_Ceilings", "OST_Roofs", "OST_Furniture",
    "OST_GenericModel", "OST_Columns", "OST_CurtainWallMullions",
    "OST_CurtainPanels", "OST_StairsRailing"
]

MEP_categories = [
    "OST_MechanicalEquipment", "OST_ElectricalEquipment", "OST_PlumbingFixtures",
    "OST_LightingFixtures", "OST_DataDevices", "OST_FireAlarmDevices",
    "OST_CommunicationDevices", "OST_Conduit", "OST_ConduitFitting",
    "OST_CableTray", "OST_CableTrayFitting", "OST_DuctCurves",
    "OST_DuctFitting", "OST_DuctAccessories", "OST_PipeCurves",
    "OST_PipeFitting", "OST_PipeAccessories", "OST_Furniture",
    "OST_SpecialityEquipment", "OST_ElectricalFixtures", "OST_Sprinklers"
]

all_categories = structural_categories + architectural_categories + MEP_categories

# =====================================================
# ฟังก์ชันดึงค่า ID (รองรับทั้ง Revit เก่าและ 2024+)
# =====================================================
def get_id_value(element_id):
    try:
        # สำหรับ Revit 2024, 2025, 2026+
        return int(element_id.Value)
    except AttributeError:
        # สำหรับ Revit 2023 ลงไป
        return element_id.IntegerValue

# ⭐️ OPTIMIZATION 1: สร้าง Mapping สำหรับ Category เพื่อลดเวลาค้นหา
def get_category_ids(category_names):
    ids = set()
    for c in category_names:
        try: ids.add(int(getattr(DB.BuiltInCategory, c)))
        except: pass
    return ids

struct_cat_ids = get_category_ids(structural_categories)
arch_cat_ids = get_category_ids(architectural_categories)
mep_cat_ids = get_category_ids(MEP_categories)

# =====================================================
# จัดการ/สร้าง/อัปเดต Shared Parameter (ชนิด TEXT)
# =====================================================
def setup_base_level_parameter(doc, app, all_cat_names):
    param_name = "Base_Level"
    existing_def = None
    existing_binding = None
    
    iterator = doc.ParameterBindings.ForwardIterator()
    while iterator.MoveNext():
        if iterator.Key.Name == param_name:
            existing_def = iterator.Key
            existing_binding = iterator.Current
            break
            
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
            t_rebind = DB.Transaction(doc, "Update Base_Level Categories")
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
            opt = DB.ExternalDefinitionCreationOptions(param_name, DB.SpecTypeId.String.Text)
            target_def = group.Definitions.Create(opt)
        except AttributeError:
            opt = DB.ExternalDefinitionCreationOptions(param_name, DB.ParameterType.Text)
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
    t_param = DB.Transaction(doc, "Setup Parameter: Base_Level")
    t_param.Start()
    try:
        try: doc.ParameterBindings.Insert(target_def, binding, DB.GroupTypeId.Data)
        except AttributeError: doc.ParameterBindings.Insert(target_def, binding, DB.BuiltInParameterGroup.PG_DATA)
        t_param.Commit()
        return "created"
    except:
        t_param.RollBack()
        return "bind_error"

output.print_md("### **ตรวจสอบ Parameter**")
param_status = setup_base_level_parameter(doc, app, all_categories)
if param_status == "created": output.print_md("✅ **ระบบได้สร้างพารามิเตอร์ 'Base_Level' เป็นชนิด TEXT สำเร็จ**")
elif param_status == "updated": output.print_md("✅ **พบพารามิเตอร์ 'Base_Level' และอัปเดต Category เพิ่มเติมแล้ว**")
elif param_status == "exists": output.print_md("✅ **พบพารามิเตอร์ 'Base_Level' พร้อมใช้งาน**")
else: output.print_md("⚠️ **ไม่สามารถสร้างพารามิเตอร์อัตโนมัติได้ (Status: {})**".format(param_status))

# =====================================================
# ค้นหาและเตรียมข้อมูล (Fast Filter)
# =====================================================
output.print_md("---")
output.print_md("### **ค้นหาองค์ประกอบในทุกหมวดหมู่ (โปรดรอสักครู่...)**")

cat_list = List[DB.BuiltInCategory]()
for c in all_categories:
    try: cat_list.Add(getattr(DB.BuiltInCategory, c))
    except: pass

multi_filter = DB.ElementMulticategoryFilter(cat_list)
collector = DB.FilteredElementCollector(doc).WherePasses(multi_filter).WhereElementIsNotElementType()

unique_elements = []
nested_skipped_count = 0
struct_count = 0
arch_count = 0
mep_count = 0

# ⭐️ OPTIMIZATION 2: ลดขั้นตอนการวนหา Category Name และใช้ get_id_value เพื่อกัน Error
for e in collector:
    if isinstance(e, DB.FamilyInstance) and e.SuperComponent:
        nested_skipped_count += 1
        continue
        
    unique_elements.append(e)
    
    if e.Category:
        cat_val = get_id_value(e.Category.Id)
        if cat_val in struct_cat_ids: struct_count += 1
        elif cat_val in arch_cat_ids: arch_count += 1
        elif cat_val in mep_cat_ids: mep_count += 1

output.print_md("### **สรุป**")
output.print_md("**รวมงานโครงสร้าง:** {} รายการ".format(struct_count))
output.print_md("**รวมงานสถาปัตย์:** {} รายการ".format(arch_count))
output.print_md("**รวมงานระบบ MEP:** {} รายการ".format(mep_count))
output.print_md("**องค์ประกอบทั้งหมด (พร้อมทำงาน):** {} รายการ".format(len(unique_elements)))

if not unique_elements:
    script.exit()

# =====================================================
# ระบบดึง Level แบบ Caching
# =====================================================
def get_element_level_id(element):
    try:
        if hasattr(element, 'LevelId') and element.LevelId != DB.ElementId.InvalidElementId:
            return element.LevelId
        level_param = element.get_Parameter(DB.BuiltInParameter.LEVEL_PARAM)
        if level_param and level_param.AsElementId() != DB.ElementId.InvalidElementId:
            return level_param.AsElementId()
        if isinstance(element, DB.FamilyInstance) and element.Host:
            host = element.Host
            if hasattr(host, 'LevelId') and host.LevelId != DB.ElementId.InvalidElementId:
                return host.LevelId
    except: pass
    return None

# =====================================================
# เริ่มตั้งค่า Base_Level พร้อม Progress Bar
# =====================================================
output.print_md("### **กำลังตั้งค่า Base_Level ให้ทุกรายการ...**")

# ⭐️ OPTIMIZATION 4: ทำการ Check out Worksets ล่วงหน้าเพื่อป้องกัน Error "You are trying to checkout a large number of elements"
if doc.IsWorkshared:
    try:
        output.print_md("⏳ **กำลัง Check out Worksets ที่เกี่ยวข้องอัตโนมัติจาก Central Model...**")
        ws_ids = set()
        for e in unique_elements:
            try:
                if hasattr(e, 'WorksetId') and e.WorksetId != DB.WorksetId.InvalidWorksetId:
                    ws_ids.add(e.WorksetId)
            except: pass
            
        if ws_ids:
            ws_list = List[DB.WorksetId]()
            for w_id in ws_ids:
                ws_list.Add(w_id)
            DB.WorksharingUtils.CheckoutWorksets(doc, ws_list)
            output.print_md("✅ **Check out Worksets ล่วงหน้าสำเร็จเรียบร้อย**")
    except Exception as ex:
        output.print_md("⚠️ **ไม่สามารถ Check out Worksets อัตโนมัติได้ (อาจติดสิทธิ์ของผู้อื่น): {}**".format(ex))

t = DB.Transaction(doc, "Set Base Level - ST, AR & MEP")
t.Start()

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
level_count = 0
read_only_count = 0
group_skipped_count = 0
struct_success = 0
arch_success = 0
MEP_success = 0

total_elements = len(unique_elements)
is_cancelled = False

# ⭐️ OPTIMIZATION 3: Caching ข้อมูล Level เพื่อลดการอ่านซ้ำ (ช่วยลด RAM และเวลา)
level_cache = {} 
update_step = max(1, total_elements // 100) # อัปเดต Progress ทุกๆ 1% แทนที่จะอัปเดตทุกชิ้น

with forms.ProgressBar(title='กำลังตั้งค่า Base_Level... ({value} จาก {max_value})', cancellable=True) as pb:
    for index, e in enumerate(unique_elements):
        
        # อัปเดต Progress Bar เป็นระยะๆ เพื่อป้องกัน UI ค้าง
        if index % update_step == 0:
            if pb.cancelled:
                is_cancelled = True
                break
            pb.update_progress(index + 1, total_elements)
            
        try:
            if hasattr(e, 'GroupId') and e.GroupId != DB.ElementId.InvalidElementId:
                if not varies_across_groups:
                    group_skipped_count += 1
                    continue

            lvl_id = get_element_level_id(e)
            if not lvl_id: continue

            # ดึงข้อมูล Level จาก Cache ถ้ามีอยู่แล้ว
            if lvl_id not in level_cache:
                lvl_elem = doc.GetElement(lvl_id)
                if isinstance(lvl_elem, DB.Level):
                    level_cache[lvl_id] = {
                        "elev_m": lvl_elem.Elevation * 0.3048,
                        "raw_elev": lvl_elem.Elevation,
                        "name": lvl_elem.Name
                    }
                else:
                    level_cache[lvl_id] = None

            lvl_data = level_cache[lvl_id]
            if not lvl_data: continue

            level_count += 1
            p = e.LookupParameter("Base_Level")
            if not p: continue
            
            if not p.IsReadOnly:
                cat_val = get_id_value(e.Category.Id) if e.Category else None
                
                if p.StorageType == DB.StorageType.String:
                    p.Set("{:.3f}".format(lvl_data["elev_m"]))
                    success_count += 1
                elif p.StorageType == DB.StorageType.Double:
                    p.Set(lvl_data["raw_elev"])
                    success_count += 1
                    
                if success_count > 0:
                    if cat_val in struct_cat_ids: struct_success += 1
                    elif cat_val in mep_cat_ids: MEP_success += 1
                    else: arch_success += 1
            else:
                read_only_count += 1
        except:
            continue
            
    pb.update_progress(total_elements, total_elements) # อัปเดตครั้งสุดท้ายให้เต็ม 100%

t.Commit()

# =====================================================
# แสดงผลลัพธ์
# =====================================================
output.print_md("### **ผลการตั้ง Base_Level**")
if is_cancelled: output.print_md("🛑 **ผู้ใช้กดยกเลิกการทำงานกลางคัน! (บันทึกเฉพาะส่วนที่ทำเสร็จแล้ว)**")

output.print_md("- องค์ประกอบที่มี Level ให้อ้างอิง: {}".format(level_count))
output.print_md("---")
output.print_md("#### **ตั้งค่า Base_Level สำเร็จ:**")
output.print_md("- งานโครงสร้าง: **{}** รายการ".format(struct_success))
output.print_md("- งานสถาปัตย์: **{}** รายการ".format(arch_success))
output.print_md("- งานระบบ MEP: **{}** รายการ".format(MEP_success))
output.print_md("- รวมทั้งหมด: **{}** รายการ".format(success_count))

if read_only_count > 0: output.print_md("⚠️ Base_Level เป็น Read-only: {} รายการ".format(read_only_count))
if group_skipped_count > 0: output.print_md("⚠️ ข้ามชิ้นส่วนใน Group (ระบบไม่อนุญาตให้แก้ไข): {} รายการ".format(group_skipped_count))
if nested_skipped_count > 0: output.print_md("ℹ️ ข้ามชิ้นส่วนที่เป็น Nested Family: {} รายการ".format(nested_skipped_count))

# =====================================================
# ตัวอย่างค่าที่ตั้ง (หน่วย "เมตร")
# =====================================================
output.print_md("### **ตัวอย่างค่าที่ตั้ง Base_Level (แสดงเป็นเมตร)**")

shown = 0
for e in unique_elements:
    if shown >= 3: break
    lvl_id = get_element_level_id(e)
    p = e.LookupParameter("Base_Level")
    
    if not (lvl_id and p): continue
    if lvl_id not in level_cache or not level_cache[lvl_id]: continue

    lvl_data = level_cache[lvl_id]
    
    if p.StorageType == DB.StorageType.String: base_val = p.AsString()
    elif p.StorageType == DB.StorageType.Double: base_val = "{:.3f}".format(p.AsDouble() * 0.3048)
    else: base_val = "N/A"

    output.print_md("{}. **{}**".format(shown+1, e.Category.Name))
    output.print_md("   - Level: {}".format(lvl_data["name"]))
    output.print_md("   - Elevation: {:.3f} m".format(lvl_data["elev_m"]))
    output.print_md("   - Base_Level: {} m".format(base_val))
    shown += 1

output.print_md("---")
output.print_md("**เสร็จสิ้น — อัปเดตข้อมูลเรียบร้อย**")