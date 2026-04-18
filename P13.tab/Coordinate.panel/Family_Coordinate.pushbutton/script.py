# -*- coding: utf-8 -*-
__title__ = "Update\nCoordinates"
__doc__ = """Calculate and update coordinates (meters) into N/E_Coordinate parameters.
- Supports Revit 2024/2025/2026+
- Number parameter → Value in meters
- Text parameter → "736.241"
- Project Base Point reports both meters and feet.
- Prevents accidental feet value assignment in Number parameters."""
__author__ = "เพิ่มพงษ์"

from pyrevit import forms, script, DB, HOST_APP
import math
import sys
import os
import tempfile
import codecs

# ================================================================
# 1. MATHEMATICAL LOGIC
# ================================================================

def rotate(x, y, theta):
    """หมุนพิกัดตามมุม (Radians)"""
    rotated_x = math.cos(theta) * x + math.sin(theta) * y
    rotated_y = -math.sin(theta) * x + math.cos(theta) * y
    return (rotated_x, rotated_y)

def find_cord(x, y, theta, bp_ew, bp_ns):
    """
    คำนวณพิกัดจริง
    x, y : เมตร (ตำแหน่งใน Project)
    theta : มุมหมุน (Radians)
    bp_ew, bp_ns : ค่า Offset ของ Base Point (เมตร)
    คืนค่า (North, East) หน่วยเมตร
    """
    rotated_x, rotated_y = rotate(x, y, theta)
    actual_east = rotated_x + bp_ew
    actual_north = rotated_y + bp_ns
    return (actual_north, actual_east)

def feet_to_meters(value):
    return value * 0.3048

class WarningSwallower(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, failuresAccessor):
        fails = failuresAccessor.GetFailureMessages()
        for f in fails:
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                failuresAccessor.DeleteWarning(f)
        return DB.FailureProcessingResult.Continue

# ================================================================
# ฟังก์ชันตรวจสอบและสร้าง Shared Parameter อัตโนมัติ (Smart Setup)
# ================================================================
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


# ================================================================
# 2. CONFIG & SETUP
# ================================================================

config = script.get_config()
export_path = getattr(config, "export_path", "")

# ตรวจสอบและตั้งค่า Export Path หากยังไม่มี
if not export_path or not os.path.exists(export_path):
    selected_folder = forms.pick_folder(title="📁 Please select a folder for the Export Path")
    if selected_folder:
        config.export_path = selected_folder
        export_path = selected_folder
        script.save_config()

# ดึงค่าการตั้งค่าหมวดหมู่ที่เคยเลือกไว้
prev_selections = getattr(config, "selected_categories", [])

# ================================================================
# 3. MAIN SCRIPT
# ================================================================

doc = __revit__.ActiveUIDocument.Document
app = doc.Application
output = script.get_output()

# --- STEP 1: UI Selection ---
options_category = {
    '❄️ Mechanical Equipment': DB.BuiltInCategory.OST_MechanicalEquipment,
    '⚡ Electrical Equipment': DB.BuiltInCategory.OST_ElectricalEquipment,
    '🚽 Plumbing Fixtures': DB.BuiltInCategory.OST_PlumbingFixtures,
    '💡 Lighting Fixtures': DB.BuiltInCategory.OST_LightingFixtures,
    '🔌 Data Devices': DB.BuiltInCategory.OST_DataDevices,
    '🔔 Fire Alarm Devices': DB.BuiltInCategory.OST_FireAlarmDevices,
    '📡 Communication Devices': DB.BuiltInCategory.OST_CommunicationDevices,
    '💨 Air Terminals': DB.BuiltInCategory.OST_DuctTerminal,
    '🔧 Pipe Fittings': DB.BuiltInCategory.OST_PipeFitting,
    '⚙️ Pipe Accessories': DB.BuiltInCategory.OST_PipeAccessory,
    '🌬️ Duct Fittings': DB.BuiltInCategory.OST_DuctFitting,
    '🚪 Doors': DB.BuiltInCategory.OST_Doors,
    '🪟 Windows': DB.BuiltInCategory.OST_Windows,
    '🏛️ Columns': DB.BuiltInCategory.OST_Columns,
    '🏗️ Structural Columns': DB.BuiltInCategory.OST_StructuralColumns,
    '🧱 Structural Foundations': DB.BuiltInCategory.OST_StructuralFoundation,
    '🪑 Furniture': DB.BuiltInCategory.OST_Furniture,
    '🧩 Generic Models': DB.BuiltInCategory.OST_GenericModel,
    '📝 Detail Components': DB.BuiltInCategory.OST_DetailComponents,
    '🪧 Signage': DB.BuiltInCategory.OST_Signage,
}

class CategoryOption(forms.TemplateListItem):
    @property
    def name(self):
        return self.item

# สร้างตัวเลือกและติ๊กถูกให้อัตโนมัติจากประวัติการใช้งาน
options = []
for k in sorted(options_category.keys()):
    opt = CategoryOption(k)
    if k in prev_selections:
        opt.state = True
    options.append(opt)

selected = forms.SelectFromList.show(
    options,
    multiselect=True,
    title="Select Categories to Update N/E Coordinates",
    button_name="🚀 Start Calculation"
)

if not selected:
    sys.exit()

selected_keys = [opt.name if hasattr(opt, 'name') else str(opt) for opt in selected]
config.selected_categories = selected_keys
script.save_config()

# รวบรวม Elements
elements = []
for key in selected_keys:
    if key in options_category:
        bic = options_category[key]
        col = DB.FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType().ToElements()
        elements.extend(list(col))

if not elements:
    forms.alert("❌ No elements found in the selected categories.")
    sys.exit()

# --- STEP 2: ตรวจสอบและสร้าง Parameters (Smart Automation) ---
output.print_md("### **Checking and Preparing Parameters**")

cat_names_for_setup = [options_category[key].ToString() for key in selected_keys if key in options_category]

# สร้างเป็น Text เสมอ เพื่อให้แก้ค่าชิ้นส่วนใน Group ได้
status_n = setup_parameter(doc, app, "N_Coordinate", "Text", cat_names_for_setup)
status_e = setup_parameter(doc, app, "E_Coordinate", "Text", cat_names_for_setup)

if status_n == "created": output.print_md("✅ **N_Coordinate** (Text) auto-created.")
elif status_n in ["exists", "updated"]: output.print_md("✅ **N_Coordinate** parameter is ready.")

if status_e == "created": output.print_md("✅ **E_Coordinate** (Text) auto-created.")
elif status_e in ["exists", "updated"]: output.print_md("✅ **E_Coordinate** parameter is ready.")

output.print_md("---")

# --- STEP 3: Get Base Point Info ---
angle = 0.0
bp_ewest_m = 0.0
bp_nsouth_m = 0.0
base_point_info = "Default"

base_points = DB.FilteredElementCollector(doc).OfClass(DB.BasePoint).ToElements()
for bp in base_points:
    if not bp.IsShared:   # Project Base Point
        angle_param = bp.get_Parameter(DB.BuiltInParameter.BASEPOINT_ANGLETON_PARAM)
        if angle_param:
            angle = angle_param.AsDouble()
        
        raw_ns = bp.get_Parameter(DB.BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM).AsDouble()
        raw_ew = bp.get_Parameter(DB.BuiltInParameter.BASEPOINT_EASTWEST_PARAM).AsDouble()
        
        rot_x, rot_y = rotate(bp.Position.X, bp.Position.Y, angle)
        
        bp_nsouth_ft = raw_ns - rot_y
        bp_ewest_ft = raw_ew - rot_x
        
        bp_nsouth_m = feet_to_meters(bp_nsouth_ft)
        bp_ewest_m = feet_to_meters(bp_ewest_ft)
        
        base_point_info = "N: {:.3f} m ({:.6f} ft), E: {:.3f} m ({:.6f} ft), Angle: {:.2f}°".format(
            bp_nsouth_m, bp_nsouth_ft,
            bp_ewest_m, bp_ewest_ft,
            math.degrees(angle)
        )
        break

# --- STEP 4: Processing Loop ---
stats = {
    "success": 0,
    "skipped_group": 0,
    "error": 0,
    "total": len(elements)
}
skipped_ids = []

t = DB.Transaction(doc, "Update Coordinates")
t.Start()

t.SetFailureHandlingOptions(
    t.GetFailureHandlingOptions().SetFailuresPreprocessor(WarningSwallower())
)

# เปิดอนุญาตให้เขียนค่าลงใน Group (VariesAcrossGroups)
varies_n, varies_e = False, False
iterator = doc.ParameterBindings.ForwardIterator()
while iterator.MoveNext():
    definition = iterator.Key
    if definition.Name == "N_Coordinate" and isinstance(definition, DB.InternalDefinition):
        try:
            if not definition.VariesAcrossGroups: definition.SetAllowVaryBetweenGroups(doc, True)
            varies_n = definition.VariesAcrossGroups
        except:
            varies_n = getattr(definition, 'VariesAcrossGroups', False)
    elif definition.Name == "E_Coordinate" and isinstance(definition, DB.InternalDefinition):
        try:
            if not definition.VariesAcrossGroups: definition.SetAllowVaryBetweenGroups(doc, True)
            varies_e = definition.VariesAcrossGroups
        except:
            varies_e = getattr(definition, 'VariesAcrossGroups', False)
            
varies_across_groups = varies_n and varies_e

with forms.ProgressBar(title="Calculating... {value}/{max_value}", cancellable=True) as pb:
    count = 0
    for el in elements:
        if pb.cancelled:
            break
        count += 1
        pb.update_progress(count, stats["total"])

        # ข้าม Element ที่อยู่ใน Group *เฉพาะกรณีที่ไม่สามารถเปิด Vary by Group ได้*
        if el.GroupId != DB.ElementId.InvalidElementId:
            if not varies_across_groups:
                stats["skipped_group"] += 1
                skipped_ids.append(el.Id.ToString())
                continue

        # --- หาตำแหน่ง X, Y (ฟุต) ---
        x_ft, y_ft = None, None
        try:
            loc = el.Location
            if loc is None:
                bbox = el.get_BoundingBox(None)
                if bbox:
                    x_ft = (bbox.Min.X + bbox.Max.X) * 0.5
                    y_ft = (bbox.Min.Y + bbox.Max.Y) * 0.5
            elif isinstance(loc, DB.LocationPoint):
                x_ft = loc.Point.X
                y_ft = loc.Point.Y
            elif isinstance(loc, DB.LocationCurve):
                mid = loc.Curve.Evaluate(0.5, True)
                x_ft = mid.X
                y_ft = mid.Y
            else:
                bbox = el.get_BoundingBox(None)
                if bbox:
                    x_ft = (bbox.Min.X + bbox.Max.X) * 0.5
                    y_ft = (bbox.Min.Y + bbox.Max.Y) * 0.5

            if x_ft is None and hasattr(el, 'GetTransform'):
                trf = el.GetTransform()
                if trf:
                    x_ft = trf.Origin.X
                    y_ft = trf.Origin.Y
        except:
            stats["error"] += 1
            continue

        if x_ft is None:
            stats["error"] += 1
            continue

        # --- คำนวณค่าพิกัดเป็นเมตร ---
        try:
            x_m = feet_to_meters(x_ft)
            y_m = feet_to_meters(y_ft)
            north_m, east_m = find_cord(x_m, y_m, angle, bp_ewest_m, bp_nsouth_m)
            
            north_m = round(north_m, 3)
            east_m = round(east_m, 3)

            params_set = False

            # --- วนลูปอัปเดตพารามิเตอร์ N/E_Coordinate ---
            for p_name, val_m in [("N_Coordinate", north_m), ("E_Coordinate", east_m)]:
                param = el.LookupParameter(p_name)
                if param and not param.IsReadOnly:

                    is_length = False
                    if param.StorageType == DB.StorageType.Double:
                        try:
                            if HOST_APP.is_newer_than(2021):
                                spec = param.Definition.GetSpecTypeId()
                                if spec and spec == DB.SpecTypeId.Length:
                                    is_length = True
                            else:
                                if param.Definition.ParameterType == DB.ParameterType.Length:
                                    is_length = True
                        except:
                            is_length = False

                    # SET ค่าตาม StorageType
                    if param.StorageType == DB.StorageType.Double:
                        if is_length:
                            param.Set(val_m / 0.3048) # แปลงกลับเป็นฟุตให้ระบบ
                        else:
                            param.Set(val_m)
                        params_set = True

                    elif param.StorageType == DB.StorageType.String:
                        # หากเป็น Text จะแสดงให้ดูทั้งคู่ (ทะลุ Group ได้ด้วย)
                        feet_val = val_m / 0.3048
                        param.Set("{:.3f}".format(val_m))
                        params_set = True

            if params_set:
                stats["success"] += 1
            else:
                stats["error"] += 1

        except:
            stats["error"] += 1

t.Commit()

# ================================================================
# 4. REPORT UI & EXPORT
# ================================================================

output.print_md("# 📊 Coordinate Update Report")
output.print_md("---\n**Project Base Point Info:** `{}`".format(base_point_info))
output.print_md("**Total Elements Checked:** {}".format(stats["total"]))

table_data = [
    ["✅ Success", str(stats["success"]), "Updated successfully"],
    ["⚠️ Skipped", str(stats["skipped_group"]), "Inside Model Group (Vary by Group Off)"],
    ["❌ Error", str(stats["error"]), "Issue"]
]

output.print_table(table_data=table_data, columns=["Status", "Count", "Desc"], formats=["", "", ""])

if skipped_ids:
    output.print_md("---\n### ⚠️ Skipped Elements")
    output.print_md("`IDs: {}`".format(", ".join(skipped_ids[:50]) + ("..." if len(skipped_ids)>50 else "")))

output.print_md("---")

# --- Save CSV Report to Export Path ---
if export_path and os.path.exists(export_path):
    try:
        csv_file = os.path.join(export_path, "Coordinate_Update_Report.csv")
        with codecs.open(csv_file, 'w', encoding='utf-8-sig') as f:
            f.write('Project Base Point Info:,"{}"\n\n'.format(base_point_info))
            f.write("Status,Count,Desc\n")
            for row in table_data:
                f.write('{},{},"{}"\n'.format(row[0], row[1], row[2]))
                
        output.print_md("### 📁 Report Exported")
        output.print_md("Report saved to: `{}`".format(csv_file))
    except Exception as e:
        output.print_md("### ❌ Export Error")
        output.print_md("Failed to save report: {}".format(e))

if stats["success"] > 0:
    success_rate = (float(stats["success"]) / float(stats["total"])) * 100.0
    output.print_md("## 🎉 Success Rate: {:.1f}%".format(success_rate))

if stats["error"] == 0 and stats["skipped_group"] == 0:
    output.print_md("## 🎉 All Clear! 100% Success.")