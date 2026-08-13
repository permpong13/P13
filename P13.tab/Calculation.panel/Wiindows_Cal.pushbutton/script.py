# -*- coding: utf-8 -*-
"""Update Window Parameters: Top of Windows & Bottom of Windows for Revit 2026"""

__title__ = "Window Top\nCal"

import os
import tempfile
from pyrevit import revit, DB, script, forms

doc = revit.doc
app = doc.Application
output = script.get_output()

WINDOW_TAG_FILE_NAME = "Windows_Tag_By_P13.rfa"
WINDOW_TAG_CONFIG_NAME = "WindowsCal"
WINDOW_TAG_CONFIG_KEY = "window_tag_family_path"


def tag_element_id_value(element_id):
    """Return a stable ElementId value for Revit 2026 and older builds."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def normalize_tag_name(value):
    """Normalize family names so spaces and underscores do not affect matching."""
    if not value:
        return ""
    return "".join(character for character in str(value).lower()
                   if character.isalnum())


def get_tag_element_name(element, fallback):
    """Read an element or type name safely through IronPython wrappers."""
    try:
        name = getattr(element, "Name", None)
        if name:
            return str(name)
    except Exception:
        pass

    try:
        name = DB.Element.Name.GetValue(element)
        if name:
            return str(name)
    except Exception:
        pass

    try:
        name_parameter = element.get_Parameter(
            DB.BuiltInParameter.SYMBOL_NAME_PARAM
        )
        if name_parameter and name_parameter.HasValue:
            name = name_parameter.AsString()
            if name:
                return str(name)
    except Exception:
        pass

    return fallback


def is_p13_window_tag_family(family):
    """Identify the bundled family while tolerating internal name variations."""
    if not family:
        return False

    try:
        category = family.FamilyCategory
        category_id = DB.ElementId(DB.BuiltInCategory.OST_WindowTags)
        if (not category or
                tag_element_id_value(category.Id) !=
                tag_element_id_value(category_id)):
            return False
    except Exception:
        return False

    family_name = normalize_tag_name(get_tag_element_name(family, ""))
    target_name = normalize_tag_name(os.path.splitext(WINDOW_TAG_FILE_NAME)[0])
    return (target_name in family_name or
            ("window" in family_name and
             "tag" in family_name and
             "p13" in family_name))


def find_p13_window_tag_family(document):
    for family in DB.FilteredElementCollector(document).OfClass(DB.Family):
        if is_p13_window_tag_family(family):
            return family
    return None


def find_window_tag_symbol(document, family):
    """Return a valid type from the supplied window tag family."""
    if not family:
        return None

    category_id = DB.ElementId(DB.BuiltInCategory.OST_WindowTags)
    for symbol_id in family.GetFamilySymbolIds():
        symbol = document.GetElement(symbol_id)
        try:
            if (symbol and symbol.Category and
                    tag_element_id_value(symbol.Category.Id) ==
                    tag_element_id_value(category_id)):
                return symbol
        except Exception:
            continue
    return None


def get_window_tag_file_path():
    """Resolve the bundled RFA and remember a user-selected fallback path."""
    bundled_path = os.path.join(os.path.dirname(__file__), WINDOW_TAG_FILE_NAME)
    if os.path.isfile(bundled_path):
        return bundled_path

    config = script.get_config(WINDOW_TAG_CONFIG_NAME)
    saved_path = config.get_option(WINDOW_TAG_CONFIG_KEY, "")
    if saved_path and os.path.isfile(saved_path):
        return saved_path

    selected_path = forms.pick_file(
        file_ext="rfa",
        title="Select {}".format(WINDOW_TAG_FILE_NAME)
    )
    if not selected_path:
        return None

    config.set_option(WINDOW_TAG_CONFIG_KEY, selected_path)
    script.save_config()
    return selected_path


def ensure_p13_window_tag_default(document):
    """Load the P13 window tag and set one of its types as project default."""
    family = find_p13_window_tag_family(document)

    if not family:
        family_path = get_window_tag_file_path()
        if not family_path:
            return "missing_file", None

        existing_family_ids = set(
            tag_element_id_value(item.Id)
            for item in DB.FilteredElementCollector(document).OfClass(DB.Family)
        )

        load_transaction = DB.Transaction(
            document, "Load P13 Window Tag Family"
        )
        load_transaction.Start()
        try:
            document.LoadFamily(family_path)
            load_transaction.Commit()
        except Exception as error:
            if load_transaction.HasStarted() and not load_transaction.HasEnded():
                load_transaction.RollBack()
            return "load_failed: {}".format(error), None

        family = find_p13_window_tag_family(document)
        if not family:
            category_id = DB.ElementId(DB.BuiltInCategory.OST_WindowTags)
            for candidate in DB.FilteredElementCollector(document).OfClass(DB.Family):
                try:
                    is_new = (
                        tag_element_id_value(candidate.Id) not in existing_family_ids
                    )
                    is_window_tag = (
                        candidate.FamilyCategory and
                        tag_element_id_value(candidate.FamilyCategory.Id) ==
                        tag_element_id_value(category_id)
                    )
                    if is_new and is_window_tag:
                        family = candidate
                        break
                except Exception:
                    continue

    if not family:
        return "family_not_found_after_load", None

    symbol = find_window_tag_symbol(document, family)
    if not symbol:
        return "type_not_found", None

    category_id = DB.ElementId(DB.BuiltInCategory.OST_WindowTags)
    try:
        current_default_id = document.GetDefaultFamilyTypeId(category_id)
        if (tag_element_id_value(current_default_id) ==
                tag_element_id_value(symbol.Id)):
            return "already_default", symbol
    except Exception as error:
        return "default_check_failed: {}".format(error), symbol

    default_transaction = DB.Transaction(
        document, "Set P13 Window Tag as Project Default"
    )
    default_transaction.Start()
    try:
        document.SetDefaultFamilyTypeId(category_id, symbol.Id)
        default_transaction.Commit()
        return "set_default", symbol
    except Exception as error:
        if default_transaction.HasStarted() and not default_transaction.HasEnded():
            default_transaction.RollBack()
        return "default_set_failed: {}".format(error), symbol


window_tag_status, window_tag_symbol = ensure_p13_window_tag_default(doc)
if window_tag_status == "set_default":
    output.print_md(
        "- Loaded **{}** and set type **{}** as the project window tag default.".format(
            WINDOW_TAG_FILE_NAME,
            get_tag_element_name(window_tag_symbol, "Unnamed Window Tag")
        )
    )
elif window_tag_status == "already_default":
    output.print_md(
        "- **{}** is already the project window tag default.".format(
            get_tag_element_name(window_tag_symbol, "P13 Window Tag")
        )
    )
else:
    output.print_md(
        "- **Window tag setup warning:** {}. Window calculation will continue.".format(
            window_tag_status
        )
    )

output.print_md("# **อัปเดตพารามิเตอร์หน้าต่าง (Fixed Version)**")

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
output.print_md("### **ตรวจสอบและเตรียม Parameters (หน้าต่าง)**")
cat_windows = ["OST_Windows"]

status_base   = setup_parameter(doc, app, "Base_Level",        "Text",   cat_windows)
status_bottom = setup_parameter(doc, app, "Bottom of Windows", "Length", cat_windows)
status_top    = setup_parameter(doc, app, "Top of Windows",    "Length", cat_windows)

if status_base == "created":   output.print_md("✅ **Base_Level** (Text) ถูกสร้างอัตโนมัติ")
elif status_base in ["exists", "updated"]: output.print_md("✅ พบพารามิเตอร์ **Base_Level** พร้อมใช้งาน")

if status_bottom == "created": output.print_md("✅ **Bottom of Windows** ถูกสร้างอัตโนมัติ")
elif status_bottom in ["exists", "updated"]: output.print_md("✅ พบพารามิเตอร์ **Bottom of Windows** พร้อมใช้งาน")

if status_top == "created":    output.print_md("✅ **Top of Windows** ถูกสร้างอัตโนมัติ")
elif status_top in ["exists", "updated"]: output.print_md("✅ พบพารามิเตอร์ **Top of Windows** พร้อมใช้งาน")

output.print_md("---")


# =====================================================
# ค้นหาองค์ประกอบหน้าต่าง
# =====================================================
windows = DB.FilteredElementCollector(doc)\
            .OfCategory(DB.BuiltInCategory.OST_Windows)\
            .WhereElementIsNotElementType()\
            .ToElements()

if not windows:
    forms.alert("ไม่พบหน้าต่างในโมเดล", exitscript=True)

output.print_md("### **ค้นพบหน้าต่างทั้งหมด: {} รายการ**".format(len(windows)))


# =====================================================
# เริ่ม Transaction เขียนค่าลงโมเดล
# =====================================================
t = DB.Transaction(doc, "Set Window Top & Bottom Parameters")
t.Start()

def get_element_id_value(element_id):
    if hasattr(element_id, "Value"):
        return element_id.Value
    return element_id.IntegerValue


def is_element_in_group(element):
    try:
        group_id = getattr(element, "GroupId", DB.ElementId.InvalidElementId)
        return group_id and group_id != DB.ElementId.InvalidElementId
    except Exception:
        return False


def allow_vary_between_groups(doc, parameter_names):
    vary_status = dict((name, False) for name in parameter_names)
    iterator = doc.ParameterBindings.ForwardIterator()
    while iterator.MoveNext():
        definition = iterator.Key
        if definition.Name in vary_status and isinstance(definition, DB.InternalDefinition):
            try:
                if not definition.VariesAcrossGroups:
                    definition.SetAllowVaryBetweenGroups(doc, True)
                vary_status[definition.Name] = definition.VariesAcrossGroups
            except Exception:
                vary_status[definition.Name] = getattr(definition, "VariesAcrossGroups", False)
    return vary_status


group_vary_status = allow_vary_between_groups(
    doc,
    ["Base_Level", "Bottom of Windows", "Top of Windows"]
)

success_count = 0
error_log = []
skipped_group_count = 0
total_elements = len(windows)
is_cancelled = False

# เริ่มใช้งาน Progress Bar
with forms.ProgressBar(title='กำลังคำนวณพารามิเตอร์หน้าต่าง... ({value} จาก {max_value})', cancellable=True) as pb:
    for index, win in enumerate(windows):
        if pb.cancelled:
            is_cancelled = True
            break

        try:
            is_in_group = is_element_in_group(win)

            # --- 1. ดึง Base Level Elevation ---
            # หน้าต่างใช้ FAMILY_LEVEL_PARAM (level ที่ติดตั้ง)
            lvl_param = win.get_Parameter(DB.BuiltInParameter.FAMILY_LEVEL_PARAM)
            if not lvl_param:
                error_log.append("Window ID {}: ไม่พบ Level Parameter".format(win.Id.Value))
                continue

            lvl_id = lvl_param.AsElementId()
            if lvl_id == DB.ElementId.InvalidElementId:
                error_log.append("Window ID {}: Level ID ไม่ถูกต้อง".format(win.Id.Value))
                continue

            base_level_el = doc.GetElement(lvl_id)
            base_elev = base_level_el.Elevation  # หน่วย Internal (feet)

            # --- 2. ดึง Sill Height ---
            # INSTANCE_SILL_HEIGHT_PARAM = ระยะจาก Level ถึงขอบล่างหน้าต่าง (Instance)
            sill_param = win.get_Parameter(DB.BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM)
            if not sill_param or not sill_param.HasValue:
                sill_param = win.LookupParameter("Sill Height")

            # Fallback: ดึง Default Sill Height จาก Element Type (กรณีเป็น Type Parameter)
            if not sill_param or not sill_param.HasValue:
                win_type_for_sill = doc.GetElement(win.GetTypeId())
                if win_type_for_sill:
                    sill_param = win_type_for_sill.LookupParameter("Default Sill Height")
                    if not sill_param or not sill_param.HasValue:
                        sill_param = win_type_for_sill.LookupParameter("Sill Height")

            sill_height = sill_param.AsDouble() if (sill_param and sill_param.HasValue) else 0.0

            # --- 3. ดึง Window Height ---
            # ลองดึงจาก Instance ก่อน แล้ว fallback ไป Type (กรณี Height เป็น Type Parameter)
            height_param = win.get_Parameter(DB.BuiltInParameter.FAMILY_HEIGHT_PARAM)
            if not height_param or not height_param.HasValue:
                height_param = win.LookupParameter("Height")

            # Fallback: ดึงจาก Element Type (Symbol) เมื่อ Height เป็น Type Parameter
            if not height_param or not height_param.HasValue:
                win_type = doc.GetElement(win.GetTypeId())
                if win_type:
                    height_param = win_type.get_Parameter(DB.BuiltInParameter.FAMILY_HEIGHT_PARAM)
                    if not height_param or not height_param.HasValue:
                        height_param = win_type.LookupParameter("Height")

            # Fallback สุดท้าย: สแกนหา Length Parameter ที่มีคำว่า "height" / "ht" ใน Type
            if not height_param or not height_param.HasValue:
                win_type2 = doc.GetElement(win.GetTypeId())
                candidates = []
                if win_type2:
                    for p in win_type2.Parameters:
                        if p.StorageType == DB.StorageType.Double and p.HasValue:
                            n = p.Definition.Name.lower()
                            if "height" in n or n in ("ht", "h"):
                                candidates.append(p)
                # เลือกตัวที่ไม่ใช่ sill (เพื่อให้ได้ความสูงกรอบหน้าต่าง)
                for cp in candidates:
                    if "sill" not in cp.Definition.Name.lower():
                        height_param = cp
                        break
                if not height_param and candidates:
                    height_param = candidates[0]

            if not height_param or not height_param.HasValue:
                # วินิจฉัย: แสดง Length parameters ทั้งหมดที่มีใน Type เพื่อช่วย debug
                win_type3 = doc.GetElement(win.GetTypeId())
                diag_names = []
                if win_type3:
                    for p in win_type3.Parameters:
                        if p.StorageType == DB.StorageType.Double and p.HasValue:
                            diag_names.append("'{}' = {:.1f}".format(
                                p.Definition.Name, p.AsDouble() * 304.8))
                error_log.append(
                    "Window ID {} [Type: {}]: ไม่พบ Height — Length params ที่มี: [{}]".format(
                        win.Id.Value,
                        get_tag_element_name(
                            doc.GetElement(win.GetTypeId()), "Unknown Window Type"
                        ) if doc.GetElement(win.GetTypeId()) else "Unknown Window Type",
                        ", ".join(diag_names[:8]) if diag_names else "ไม่มี"
                    )
                )
                continue

            win_height = height_param.AsDouble()

            # --- 4. คำนวณสูตร ---
            # Bottom of Windows = Base_Level + Sill Height
            bottom_val = base_elev + sill_height
            # Top of Windows   = Base_Level + Sill Height + Height
            top_val    = base_elev + sill_height + win_height

            # --- 5. เขียนค่าลง Parameter ---

            if is_in_group:
                skipped_group_count += 1
                error_log.append(
                    "Window ID {}: skipped because it is inside a model group.".format(
                        get_element_id_value(win.Id)
                    )
                )
                continue

            # (A) Base_Level (Text)
            p_base = win.LookupParameter("Base_Level")
            if p_base and not p_base.IsReadOnly:
                if p_base.StorageType == DB.StorageType.String:
                    elev_m = base_elev * 0.3048
                    p_base.Set("{:.3f}".format(elev_m))
                elif p_base.StorageType == DB.StorageType.Double:
                    p_base.Set(base_elev)

            # (B) Bottom of Windows
            p_bottom = win.LookupParameter("Bottom of Windows")
            if p_bottom and not p_bottom.IsReadOnly:
                p_bottom.Set(bottom_val)

            # (C) Top of Windows (เป้าหมายหลัก)
            p_top = win.LookupParameter("Top of Windows")
            if p_top and not p_top.IsReadOnly:
                p_top.Set(top_val)
                success_count += 1
            elif not p_top:
                error_log.append("Window ID {}: ไม่พบ Parameter 'Top of Windows'".format(win.Id.Value))

        except Exception as e:
            error_log.append("Window ID {}: {}".format(win.Id.Value, str(e)))

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

if skipped_group_count:
    output.print_md("### Grouped Windows")
    output.print_md(
        "Skipped **{}** grouped windows to prevent Revit from forcing the Ungroup workflow.".format(
            skipped_group_count
        )
    )

if error_log:
    output.print_md("### ⚠️ **ข้อผิดพลาดที่พบ**")
    unique_errors = list(set(error_log))
    for log in unique_errors[:15]:
        output.print_md("- " + log)

output.print_md("\n**เสร็จสิ้น — อัปเดตข้อมูลพารามิเตอร์หน้าต่างเรียบร้อย**")
