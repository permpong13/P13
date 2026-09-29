# -*- coding: utf-8 -*-
"""Set Base Level Parameter (Supports Base_Level, CNT_Base Level, and Custom Parameters)
Optimized for Revit 2024-2026+ and legacy versions
"""

__title__ = "Base_Level\nParameter"

import os
import tempfile
from System.Collections.Generic import List
from pyrevit import revit, DB, script, forms

doc = revit.doc
app = doc.Application
output = script.get_output()

# =====================================================
# รายการ BuiltInCategory ที่ครอบคลุม
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
    "OST_CurtainPanels", "OST_StairsRailing", "OST_Casework", "OST_Site"
]

MEP_categories = [
    "OST_MechanicalEquipment", "OST_ElectricalEquipment", "OST_PlumbingFixtures",
    "OST_LightingFixtures", "OST_DataDevices", "OST_FireAlarmDevices",
    "OST_CommunicationDevices", "OST_SecurityDevices", "OST_TelephoneDevices",
    "OST_NurseCallDevices", "OST_LightingDevices", "OST_Conduit", "OST_ConduitFitting",
    "OST_CableTray", "OST_CableTrayFitting", "OST_DuctCurves", "OST_DuctFitting",
    "OST_DuctAccessories", "OST_PipeCurves", "OST_PipeFitting", "OST_PipeAccessories",
    "OST_Furniture", "OST_SpecialityEquipment", "OST_ElectricalFixtures", "OST_Sprinklers"
]

all_categories = structural_categories + architectural_categories + MEP_categories

# =====================================================
# ฟังก์ชันดึงค่า ID (รองรับทั้ง Revit เก่าและ 2024+)
# =====================================================
def get_id_value(element_id):
    if not element_id:
        return -1
    try:
        # Revit 2024+
        return int(element_id.Value)
    except AttributeError:
        # Revit <= 2023
        return element_id.IntegerValue

def get_category_ids(category_names):
    ids = set()
    for c in category_names:
        try:
            ids.add(int(getattr(DB.BuiltInCategory, c)))
        except:
            pass
    return ids

struct_cat_ids = get_category_ids(structural_categories)
arch_cat_ids = get_category_ids(architectural_categories)
mep_cat_ids = get_category_ids(MEP_categories)
all_cat_ids = struct_cat_ids | arch_cat_ids | mep_cat_ids

# =====================================================
# 1. UI เลือกพารามิเตอร์เป้าหมาย (Target Parameter)
# =====================================================
param_menu_options = [
    "Base_Level (ค่าเริ่มต้น)",
    "CNT_Base Level (โปรเจค CNT)",
    "🔍 เลือก Parameter อื่นจากในโปรเจค...",
    "✏️ พิมพ์ชื่อ Parameter เอง..."
]

chosen_option = forms.CommandSwitchWindow.show(
    param_menu_options,
    message="เลือก Parameter ที่ต้องการนำค่าความสูง Level ไปบันทึก:"
)

if not chosen_option:
    script.exit()

target_param_name = "Base_Level"

if "Base_Level" in chosen_option:
    target_param_name = "Base_Level"
elif "CNT_Base Level" in chosen_option:
    target_param_name = "CNT_Base Level"
elif "เลือก Parameter อื่น" in chosen_option:
    param_candidates = set()
    
    # ดึงจาก ParameterBindings
    iterator = doc.ParameterBindings.ForwardIterator()
    while iterator.MoveNext():
        param_candidates.add(iterator.Key.Name)
        
    # ดึงจาก SharedParameterElements
    try:
        sp_collector = DB.FilteredElementCollector(doc).OfClass(DB.SharedParameterElement)
        for sp in sp_collector:
            param_candidates.add(sp.Name)
    except:
        pass
        
    # พารามิเตอร์พื้นฐานที่มักใช้งาน
    for p in ["Base_Level", "CNT_Base Level", "Level_Bottom_of_Column", "Level_Top_of_Column", "Base Level", "Bottom Elevation"]:
        param_candidates.add(p)
        
    sorted_candidates = sorted(list(param_candidates))
    selected_p = forms.SelectFromList.show(
        sorted_candidates,
        title="เลือก Parameter ปลายทาง",
        button_name="เลือก",
        multiselect=False
    )
    if not selected_p:
        script.exit()
    target_param_name = selected_p
elif "พิมพ์ชื่อ" in chosen_option:
    custom_name = forms.ask_for_string(
        prompt="ระบุชื่อ Parameter ที่ต้องการบันทึกค่าความสูง Level:",
        default="Base_Level",
        title="กำหนดชื่อ Parameter"
    )
    if not custom_name or not custom_name.strip():
        script.exit()
    target_param_name = custom_name.strip()

# =====================================================
# 2. UI ตรวจสอบการเลือกชิ้นงาน (Selection vs All Elements)
# =====================================================
selection = revit.get_selection()
selected_ids = list(selection.element_ids) if selection else []
scope_mode = "all"
selected_elements = []

if selected_ids:
    for eid in selected_ids:
        el = doc.GetElement(eid)
        if el and el.Category:
            cat_val = get_id_value(el.Category.Id)
            if cat_val in all_cat_ids:
                selected_elements.append(el)
                
    if selected_elements:
        scope_choices = [
            "เฉพาะชิ้นที่เลือกในมุมมอง ({} รายการ)".format(len(selected_elements)),
            "ประมวลผลทั้งโมเดล (ทุก Category ที่รองรับ)"
        ]
        chosen_scope = forms.CommandSwitchWindow.show(
            scope_choices,
            message="ตรวจพบการเลือกชิ้นงาน {} รายการ — เลือกขอบเขตการทำงาน:".format(len(selected_elements))
        )
        if not chosen_scope:
            script.exit()
        if "เฉพาะชิ้นที่เลือก" in chosen_scope:
            scope_mode = "selected"

# =====================================================
# 3. จัดการและตรวจสอบ Parameter อย่างปลอดภัย (ห้ามลบเด็ดขาด)
# =====================================================
def ensure_parameter_binding(doc, app, param_name, all_cat_names):
    """ตรวจสอบการ Bind ของ Parameter หากยังไม่มีหรือ Category ไม่ครบให้เพิ่ม โดยไม่ลบข้อมูลเดิมเด็ดขาด"""
    existing_def = None
    existing_binding = None
    
    iterator = doc.ParameterBindings.ForwardIterator()
    while iterator.MoveNext():
        if iterator.Key.Name == param_name:
            existing_def = iterator.Key
            existing_binding = iterator.Current
            break
            
    if existing_def and existing_binding:
        # หากมีอยู่แล้ว ให้อัปเดต Category Set ให้ครอบคลุมทุกหมวดหมู่ที่ระบุ
        cat_set = existing_binding.Categories
        needs_update = False
        
        for c in all_cat_names:
            try:
                b_cat = getattr(DB.BuiltInCategory, c)
                cat = doc.Settings.Categories.get_Item(b_cat)
                if cat and cat.AllowsBoundParameters and not cat_set.Contains(cat):
                    cat_set.Insert(cat)
                    needs_update = True
            except:
                pass
                
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

    # ถ้ายังไม่มีใน ParameterBindings ให้ลองตรวจสอบ Shared Parameter File เพื่อสร้างใหม่เป็น Length
    sp_file = app.OpenSharedParameterFile()
    original_sp = app.SharedParametersFilename
    
    target_def = None
    if sp_file:
        for group in sp_file.Groups:
            for definition in group.Definitions:
                if definition.Name == param_name:
                    target_def = definition
                    break
            if target_def:
                break
                
    if not sp_file or (sp_file and not target_def):
        temp_dir = tempfile.gettempdir()
        temp_sp_path = os.path.join(temp_dir, "Auto_SharedParams_Revit.txt")
        if not os.path.exists(temp_sp_path):
            with open(temp_sp_path, "w") as f:
                f.write("")
        try:
            app.SharedParametersFilename = temp_sp_path
            sp_file = app.OpenSharedParameterFile()
        except:
            pass
            
    if not sp_file:
        return "not_bound_family_or_custom"
        
    target_def = None
    for group in sp_file.Groups:
        for definition in group.Definitions:
            if definition.Name == param_name:
                target_def = definition
                break
        if target_def:
            break
            
    if not target_def:
        group_name = "Data"
        group = sp_file.Groups.get_Item(group_name)
        if not group:
            group = sp_file.Groups.Create(group_name)
        try:
            # Revit 2022-2026+
            opt = DB.ExternalDefinitionCreationOptions(param_name, DB.SpecTypeId.Length)
            target_def = group.Definitions.Create(opt)
        except AttributeError:
            try:
                # Revit <= 2021
                opt = DB.ExternalDefinitionCreationOptions(param_name, DB.ParameterType.Length)
                target_def = group.Definitions.Create(opt)
            except:
                return "not_bound_family_or_custom"
                
    if original_sp and app.SharedParametersFilename != original_sp:
        try:
            app.SharedParametersFilename = original_sp
        except:
            pass
            
    if not target_def:
        return "not_bound_family_or_custom"
        
    cat_set = app.Create.NewCategorySet()
    for c in all_cat_names:
        try:
            b_cat = getattr(DB.BuiltInCategory, c)
            cat = doc.Settings.Categories.get_Item(b_cat)
            if cat and cat.AllowsBoundParameters:
                cat_set.Insert(cat)
        except:
            pass
            
    if cat_set.IsEmpty:
        return "no_categories"
        
    binding = app.Create.NewInstanceBinding(cat_set)
    t_param = DB.Transaction(doc, "Setup Parameter: {}".format(param_name))
    t_param.Start()
    try:
        try:
            doc.ParameterBindings.Insert(target_def, binding, DB.GroupTypeId.Data)
        except AttributeError:
            doc.ParameterBindings.Insert(target_def, binding, DB.BuiltInParameterGroup.PG_DATA)
        t_param.Commit()
        return "created"
    except:
        t_param.RollBack()
        return "not_bound_family_or_custom"

output.print_md("### **ตรวจสอบ Parameter: `{}`**".format(target_param_name))
param_status = ensure_parameter_binding(doc, app, target_param_name, all_categories)
if param_status == "created":
    output.print_md("✅ **สร้างและผูกพารามิเตอร์ `{}` ให้ทุกหมวดหมู่สำเร็จ**".format(target_param_name))
elif param_status == "updated":
    output.print_md("✅ **อัปเดตหมวดหมู่ที่ผูกกับ `{}` เพิ่มเติมเรียบร้อย**".format(target_param_name))
elif param_status == "exists":
    output.print_md("✅ **พบพารามิเตอร์ `{}` ในระบบ พร้อมทำงาน**".format(target_param_name))
else:
    output.print_md("ℹ️ **ใช้งานพารามิเตอร์ `{}` ระดับ Family/Project ที่มีอยู่แล้วในโมเดล**".format(target_param_name))

# =====================================================
# 4. ค้นหาและเตรียมองค์ประกอบ
# =====================================================
output.print_md("---")
output.print_md("### **กำลังรวบรวมองค์ประกอบ...**")

if scope_mode == "selected":
    raw_elements = selected_elements
    output.print_md("🎯 **ขอบเขตการทำงาน:** เฉพาะชิ้นงานที่เลือก ({} รายการ)".format(len(raw_elements)))
else:
    cat_list = List[DB.BuiltInCategory]()
    for c in all_categories:
        try:
            cat_list.Add(getattr(DB.BuiltInCategory, c))
        except:
            pass
    multi_filter = DB.ElementMulticategoryFilter(cat_list)
    raw_elements = DB.FilteredElementCollector(doc).WherePasses(multi_filter).WhereElementIsNotElementType().ToElements()
    output.print_md("🌐 **ขอบเขตการทำงาน:** ทั้งโมเดล (ทุกหมวดหมู่)")

unique_elements = []
nested_skipped_count = 0
struct_count = 0
arch_count = 0
mep_count = 0

for e in raw_elements:
    if isinstance(e, DB.FamilyInstance) and e.SuperComponent:
        nested_skipped_count += 1
        continue
        
    unique_elements.append(e)
    
    if e.Category:
        cat_val = get_id_value(e.Category.Id)
        if cat_val in struct_cat_ids:
            struct_count += 1
        elif cat_val in arch_cat_ids:
            arch_count += 1
        elif cat_val in mep_cat_ids:
            mep_count += 1

output.print_md("📊 **สรุปจำนวนชิ้นงาน:** โครงสร้าง **{}** | สถาปัตย์ **{}** | ระบบ MEP **{}** (รวมทั้งหมด **{}** รายการ)".format(
    struct_count, arch_count, mep_count, len(unique_elements)
))

if not unique_elements:
    output.print_md("⚠️ ไม่พบชิ้นงานที่ตรงตามเงื่อนไข")
    script.exit()

# =====================================================
# 5. ระบบตรวจจับ Level อัจฉริยะ (Comprehensive Level Resolver)
# =====================================================
# รวบรวม Level ทั้งหมดในโมเดล และเรียงลำดับตาม Elevation
all_levels = list(DB.FilteredElementCollector(doc).OfClass(DB.Level).WhereElementIsNotElementType())
all_levels.sort(key=lambda x: x.Elevation)
level_cache = {lvl.Id: lvl for lvl in all_levels}
level_by_name = {lvl.Name: lvl for lvl in all_levels}

# รายชื่อ BuiltInParameter ที่เกี่ยวข้องกับ Level (ตรวจสอบความปลอดภัยก่อนใช้งาน ไม่ให้เกิด AttributeError)
candidate_level_bips = [
    "FAMILY_LEVEL_PARAM",                 # Lighting Fixtures, Equipment, Generic Models
    "INSTANCE_REFERENCE_LEVEL_PARAM",     # Framing, MEP Fittings/Accessories
    "LEVEL_PARAM",                        # Floors, Ceilings, Furniture, Instances
    "FAMILY_BASE_LEVEL_PARAM",            # Structural Columns
    "WALL_BASE_CONSTRAINT",               # Walls
    "SCHEDULE_LEVEL_PARAM",               # MEP Fixtures/Equipment
    "INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM", # Schedule only level
    "ROOF_BASE_LEVEL_PARAM",              # Roofs
    "ROOF_CONSTRAINT_LEVEL_PARAM",        # Roofs
    "RBS_START_LEVEL_PARAM",              # Conduits, Cable Trays, Ducts, Pipes
    "MULTISTORY_STAIRS_REF_LEVEL",        # Stairs
    "STAIRS_BASE_LEVEL",                  # Stairs
    "STAIRS_RAILING_BASE_LEVEL_PARAM",    # Railings
    "FACEROOF_LEVEL_PARAM"                # Roofs
]

LEVEL_BUILTIN_PARAMS = []
for bip_name in candidate_level_bips:
    if hasattr(DB.BuiltInParameter, bip_name):
        try:
            LEVEL_BUILTIN_PARAMS.append(getattr(DB.BuiltInParameter, bip_name))
        except:
            pass

def get_element_level(element, doc, level_cache, all_levels, level_by_name, depth=0):
    """ตรวจหา DB.Level ของ element รองรับทั้ง MEP, Hosted Family, Structural, Architectural"""
    if depth > 3 or not element:
        return None
        
    # 1. ตรวจสอบผ่าน BuiltInParameters ลำดับต้น (แม่นยำที่สุด)
    for bip in LEVEL_BUILTIN_PARAMS:
        try:
            p = element.get_Parameter(bip)
            if p and p.StorageType == DB.StorageType.ElementId:
                lid = p.AsElementId()
                if lid != DB.ElementId.InvalidElementId:
                    if lid in level_cache:
                        return level_cache[lid]
                    lvl = doc.GetElement(lid)
                    if isinstance(lvl, DB.Level):
                        level_cache[lvl.Id] = lvl
                        return lvl
        except:
            pass

    # 2. ตรวจสอบ element.LevelId
    try:
        if hasattr(element, 'LevelId') and element.LevelId != DB.ElementId.InvalidElementId:
            if element.LevelId in level_cache:
                return level_cache[element.LevelId]
            lvl = doc.GetElement(element.LevelId)
            if isinstance(lvl, DB.Level):
                level_cache[lvl.Id] = lvl
                return lvl
    except:
        pass

    # 3. ตรวจสอบ Host ของ FamilyInstance (สำคัญมากสำหรับชิ้นงาน MEP / Lighting Fixture ที่เกาะบน Level)
    try:
        if isinstance(element, DB.FamilyInstance) and element.Host:
            host = element.Host
            # กรณี 3.1: Host เป็น DB.Level โดยตรง! (เช่น Host: Level : ROAD LEVEL)
            if isinstance(host, DB.Level):
                level_cache[host.Id] = host
                return host
            if hasattr(host, 'Category') and host.Category and get_id_value(host.Category.Id) == int(DB.BuiltInCategory.OST_Levels):
                level_cache[host.Id] = host
                return host
            # กรณี 3.2: Host เป็นวัตถุอื่น (เช่น Floor, Wall, Slab) ที่มี LevelId
            if hasattr(host, 'LevelId') and host.LevelId != DB.ElementId.InvalidElementId:
                if host.LevelId in level_cache:
                    return level_cache[host.LevelId]
                lvl = doc.GetElement(host.LevelId)
                if isinstance(lvl, DB.Level):
                    level_cache[lvl.Id] = lvl
                    return lvl
            # กรณี 3.3: ตรวจสอบ Host ย้อนกลับขึ้นไป
            host_lvl = get_element_level(host, doc, level_cache, all_levels, level_by_name, depth + 1)
            if host_lvl:
                return host_lvl
    except:
        pass

    # 4. ค้นหาตามชื่อ Parameter มาตรฐาน
    for p_name in ["Level", "Reference Level", "Schedule Level", "Base Level", "Base Constraint", "Host Level"]:
        try:
            p = element.LookupParameter(p_name)
            if p:
                if p.StorageType == DB.StorageType.ElementId:
                    lid = p.AsElementId()
                    if lid != DB.ElementId.InvalidElementId:
                        if lid in level_cache:
                            return level_cache[lid]
                        lvl = doc.GetElement(lid)
                        if isinstance(lvl, DB.Level):
                            level_cache[lvl.Id] = lvl
                            return lvl
                elif p.StorageType == DB.StorageType.String:
                    str_name = p.AsString()
                    if str_name and str_name in level_by_name:
                        return level_by_name[str_name]
        except:
            pass

    # 5. Fallback: คำนวณจากระดับความสูงจริง (BoundingBox / LocationPoint Z) เทียบกับ Level ที่อยู่ใกล้ที่สุด
    try:
        z = None
        loc = getattr(element, 'Location', None)
        if loc and hasattr(loc, 'Point') and loc.Point:
            z = loc.Point.Z
        else:
            bb = element.get_BoundingBox(None)
            if bb:
                z = bb.Min.Z
        if z is not None and all_levels:
            best_lvl = all_levels[0]
            for lvl in all_levels:
                if lvl.Elevation <= (z + 0.05):
                    best_lvl = lvl
                else:
                    break
            return best_lvl
    except:
        pass

    return None

# =====================================================
# 6. ฟังก์ชันเขียนค่าลง Parameter อย่างปลอดภัย (Smart Value Setting)
# =====================================================
def set_level_parameter_value(param, level):
    """เขียนค่าความสูงของ Level ลงในพารามิเตอร์ตาม Data Type (Double Length, Number, String, Integer)"""
    if param.IsReadOnly:
        return "read_only"

    raw_elev = level.Elevation       # หน่วยภายในของ Revit (ฟุต)
    elev_m = raw_elev * 0.3048       # หน่วยเมตร

    try:
        if param.StorageType == DB.StorageType.Double:
            # ตรวจสอบว่าเป็น Length หรือ Number
            is_number = False
            try:
                spec_id = param.Definition.GetSpecTypeId()
                if spec_id == DB.SpecTypeId.Number:
                    is_number = True
            except:
                try:
                    if param.Definition.ParameterType == DB.ParameterType.Number:
                        is_number = True
                except:
                    pass

            if is_number:
                success = param.Set(elev_m)
            else:
                # Length: Revit ใช้หน่วยฟุตเป็นฐานภายใน และแสดงผลตามหน่วยโปรเจค (mm หรือ m) อัตโนมัติ
                success = param.Set(raw_elev)
            return "success" if success else "failed"

        elif param.StorageType == DB.StorageType.String:
            # Text Parameter: เขียนค่าระดับเป็นเมตร เช่น "0.000" หรือ "4.650"
            success = param.Set("{:.3f}".format(elev_m))
            return "success" if success else "failed"

        elif param.StorageType == DB.StorageType.Integer:
            # Integer Parameter: เขียนเป็น มม. เช่น 4650
            success = param.Set(int(round(elev_m * 1000.0)))
            return "success" if success else "failed"

    except Exception:
        return "failed"

    return "unsupported_type"

# =====================================================
# 7. Check out Worksets (สำหรับ Central Model)
# ต้องทำก่อนเริ่ม Transaction ใดๆ ทั้งสิ้น
# =====================================================
if doc.IsWorkshared:
    try:
        ws_ids = set()
        for e in unique_elements:
            try:
                if hasattr(e, 'WorksetId') and e.WorksetId != DB.WorksetId.InvalidWorksetId:
                    ws_ids.add(e.WorksetId)
            except:
                pass
        if ws_ids:
            ws_list = List[DB.WorksetId]()
            for w_id in ws_ids:
                ws_list.Add(w_id)
            DB.WorksharingUtils.CheckoutWorksets(doc, ws_list)
            output.print_md("✅ Check out Worksets สำหรับชิ้นงานเรียบร้อยแล้ว")
    except Exception as ex:
        output.print_md("⚠️ ไม่สามารถ Check out Worksets อัตโนมัติได้: {}".format(ex))

# =====================================================
# 8. เริ่มกระบวนการบันทึกค่าพร้อม Progress Bar (ใช้ Transaction เดียว)
# =====================================================
output.print_md("### **กำลังบันทึกค่าลงพารามิเตอร์ `{}`...**".format(target_param_name))

t = DB.Transaction(doc, "Set {} - ST, AR & MEP".format(target_param_name))
t.Start()

try:
    # ตั้งค่าให้พารามิเตอร์ vary ใน model group ได้ (ถ้าเป็นไปได้) ภายใน transaction หลัก
    try:
        iterator = doc.ParameterBindings.ForwardIterator()
        while iterator.MoveNext():
            definition = iterator.Key
            if definition.Name == target_param_name and isinstance(definition, DB.InternalDefinition):
                try:
                    if not definition.VariesAcrossGroups:
                        definition.SetAllowVaryBetweenGroups(doc, True)
                except:
                    pass
                break
    except:
        pass

    success_count = 0
    level_found_count = 0
    read_only_count = 0
    missing_param_count = 0
    struct_success = 0
    arch_success = 0
    mep_success = 0

    total_elements = len(unique_elements)
    is_cancelled = False
    update_step = max(1, total_elements // 100)

    sample_records = []

    with forms.ProgressBar(title='กำลังตั้งค่า {}... ({{value}} จาก {{max_value}})'.format(target_param_name), cancellable=True) as pb:
        for index, e in enumerate(unique_elements):
            if index % update_step == 0:
                if pb.cancelled:
                    is_cancelled = True
                    break
                pb.update_progress(index + 1, total_elements)

            try:
                lvl = get_element_level(e, doc, level_cache, all_levels, level_by_name)
                if not lvl:
                    continue

                level_found_count += 1

                p = e.LookupParameter(target_param_name)
                if not p:
                    missing_param_count += 1
                    continue

                result = set_level_parameter_value(p, lvl)
                if result == "success":
                    success_count += 1
                    cat_val = get_id_value(e.Category.Id) if e.Category else None
                    if cat_val in struct_cat_ids:
                        struct_success += 1
                    elif cat_val in mep_cat_ids:
                        mep_success += 1
                    else:
                        arch_success += 1

                    if len(sample_records) < 5:
                        cat_name = e.Category.Name if e.Category else "Unknown"
                        elem_name = e.Name if hasattr(e, 'Name') else str(get_id_value(e.Id))
                        elev_m = lvl.Elevation * 0.3048
                        if p.StorageType == DB.StorageType.Double:
                            disp_val = "{:.3f} m".format(elev_m)
                        elif p.StorageType == DB.StorageType.String:
                            disp_val = "{} m (Text)".format(p.AsString() or "{:.3f}".format(elev_m))
                        else:
                            disp_val = str(elev_m)
                        sample_records.append({
                            "category": cat_name,
                            "name": elem_name,
                            "level": lvl.Name,
                            "elev_m": elev_m,
                            "val": disp_val
                        })

                elif result == "read_only":
                    read_only_count += 1

            except Exception as ex:
                continue

        pb.update_progress(total_elements, total_elements)

    t.Commit()
except Exception as ex:
    if t.HasStarted() and not t.HasEnded():
        t.RollBack()
    output.print_md("❌ **เกิดข้อผิดพลาดในการบันทึกข้อมูล:** {}".format(ex))
    script.exit()

# =====================================================
# 10. รายงานผลลัพธ์การทำงานอย่างละเอียด
# =====================================================
output.print_md("---")
output.print_md("### **ผลการทำงาน (Parameter: `{}`)**".format(target_param_name))
if is_cancelled:
    output.print_md("🛑 **ผู้ใช้กดยกเลิกกลางคัน (บันทึกเฉพาะส่วนที่เสร็จเรียบร้อยแล้ว)**")

output.print_md("- องค์ประกอบที่ตรวจพบ Level อ้างอิง: **{}** จาก **{}** รายการ".format(level_found_count, total_elements))
output.print_md("#### **บันทึกค่าสำเร็จแยกตามกลุ่มงาน:**")
output.print_md("- งานโครงสร้าง (Structural): **{}** รายการ".format(struct_success))
output.print_md("- งานสถาปัตยกรรม (Architectural): **{}** รายการ".format(arch_success))
output.print_md("- งานระบบ (MEP): **{}** รายการ".format(mep_success))
output.print_md("- 🏆 **รวมบันทึกสำเร็จทั้งหมด:** **{}** รายการ".format(success_count))

if missing_param_count > 0:
    output.print_md("⚠️ ไม่พบ Parameter `{}` ในบางชิ้นงาน: **{}** รายการ (ชิ้นงานเหล่านี้ยังไม่มีพารามิเตอร์ดังกล่าว)".format(target_param_name, missing_param_count))
if read_only_count > 0:
    output.print_md("⚠️ Parameter เป็น Read-only (ไม่สามารถแก้ไขได้): **{}** รายการ".format(read_only_count))
if nested_skipped_count > 0:
    output.print_md("ℹ️ ข้ามชิ้นส่วนที่เป็น Nested Family: **{}** รายการ".format(nested_skipped_count))

if sample_records:
    output.print_md("### **ตัวอย่างค่าที่บันทึกสำเร็จ**")
    for idx, rec in enumerate(sample_records):
        output.print_md("{}. **{}** ({})".format(idx + 1, rec["category"], rec["name"]))
        output.print_md("   - Level อ้างอิง: **{}** (ระดับความสูง: **{:.3f} m**)".format(rec["level"], rec["elev_m"]))
        output.print_md("   - ค่าใน `{}`: **{}**".format(target_param_name, rec["val"]))

output.print_md("---")
output.print_md("✨ **อัปเดตข้อมูลเสร็จสิ้นเรียบร้อยอย่างสมบูรณ์**")
