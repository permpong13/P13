# -*- coding: utf-8 -*-
__title__ = "Update\nCoordinates"
__doc__ = """คำนวณพิกัด (เมตร) ลงในพารามิเตอร์ N/E_Coordinate
- รองรับ Revit 2024/2025/2026+
- พารามิเตอร์ Number → ตัวเลขเมตร
- พารามิเตอร์ Text → "736.241 m (2415489.433149 ft)"
- Project Base Point แสดงทั้งเมตรและฟุต
- ป้องกันการ Set ค่าฟุตผิดในพารามิเตอร์ Number"""
__author__ = "เพิ่มพงษ์"

from pyrevit import forms, script, DB, HOST_APP
import math
import sys
import os
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
# 2. CONFIG & SETUP
# ================================================================

config = script.get_config()
export_path = getattr(config, "export_path", "")

# ตรวจสอบและตั้งค่า Export Path หากยังไม่มี
if not export_path or not os.path.exists(export_path):
    selected_folder = forms.pick_folder(title="📁 กรุณาเลือกโฟลเดอร์สำหรับตั้งค่า Export Path")
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
    '🪧 Signage': DB.BuiltInCategory.OST_Signage, # หมวดหมู่ Signage
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
    title="เลือกหมวดหมู่ (แก้ไขการ Set ค่าผิดพลาด)",
    button_name="🚀 เริ่มคำนวณ"
)

if not selected:
    sys.exit()

# ตรวจสอบว่าค่าที่ return มาเป็น String หรือ Object
selected_keys = [opt.name if hasattr(opt, 'name') else str(opt) for opt in selected]

# บันทึกหมวดหมู่ที่เลือกลง Config
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
    forms.alert("❌ ไม่พบ Element ในหมวดหมู่ที่เลือก")
    sys.exit()

# --- STEP 2: Get Base Point Info (Project Base Point, ไม่แชร์) ---
angle = 0.0
bp_ewest_m = 0.0
bp_nsouth_m = 0.0
base_point_info = "Default"

base_points = DB.FilteredElementCollector(doc).OfClass(DB.BasePoint).ToElements()
for bp in base_points:
    if not bp.IsShared:   # Project Base Point
        # มุมหมุน
        angle_param = bp.get_Parameter(DB.BuiltInParameter.BASEPOINT_ANGLETON_PARAM)
        if angle_param:
            angle = angle_param.AsDouble()
        
        # ค่า Northing / Easting ที่ตั้งไว้ใน Base Point
        raw_ns = bp.get_Parameter(DB.BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM).AsDouble()
        raw_ew = bp.get_Parameter(DB.BuiltInParameter.BASEPOINT_EASTWEST_PARAM).AsDouble()
        
        # หมุนตำแหน่งของ Base Point กลับ
        rot_x, rot_y = rotate(bp.Position.X, bp.Position.Y, angle)
        
        # ค่า Offset ที่แท้จริง
        bp_nsouth_ft = raw_ns - rot_y
        bp_ewest_ft = raw_ew - rot_x
        
        # แปลงเป็นเมตร
        bp_nsouth_m = feet_to_meters(bp_nsouth_ft)
        bp_ewest_m = feet_to_meters(bp_ewest_ft)
        
        # แสดงผลทั้งเมตรและฟุต
        base_point_info = "N: {:.3f} m ({:.6f} ft), E: {:.3f} m ({:.6f} ft), Angle: {:.2f}°".format(
            bp_nsouth_m, bp_nsouth_ft,
            bp_ewest_m, bp_ewest_ft,
            math.degrees(angle)
        )
        break

# --- STEP 3: Processing Loop ---
stats = {
    "success": 0,
    "skipped_group": 0,
    "error": 0,
    "total": len(elements)
}
skipped_ids = []

with forms.ProgressBar(title="Calculating... {value}/{max_value}", cancellable=True) as pb:
    t = DB.Transaction(doc, "Update Coordinates")
    t.Start()
    
    t.SetFailureHandlingOptions(
        t.GetFailureHandlingOptions().SetFailuresPreprocessor(WarningSwallower())
    )

    count = 0
    for el in elements:
        if pb.cancelled:
            break
        count += 1
        pb.update_progress(count, stats["total"])

        # ข้าม Element ที่อยู่ใน Group
        if el.GroupId != DB.ElementId.InvalidElementId:
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

            # กรณี Family Instance ที่มี GetTransform
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
            
            # ปัดเศษเมตรเหลือ 3 ตำแหน่ง
            north_m = round(north_m, 3)
            east_m = round(east_m, 3)

            params_set = False

            # --- วนลูปอัปเดตพารามิเตอร์ N_Coordinate และ E_Coordinate ---
            for p_name, val_m in [("N_Coordinate", north_m), ("E_Coordinate", east_m)]:
                param = el.LookupParameter(p_name)
                if param and not param.IsReadOnly:

                    # ----- ตรวจสอบชนิดพารามิเตอร์อย่างแม่นยำ -----
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
                            # ถ้าเกิด Exception ให้ถือว่าไม่ใช่ Length (ป้องกันการ Set ฟุตผิด)
                            is_length = False

                    # ----- SET ค่าตาม StorageType -----
                    if param.StorageType == DB.StorageType.Double:
                        if is_length:
                            # Length → ต้องใส่ค่าฟุต
                            param.Set(val_m / 0.3048)
                        else:
                            # Number → ใส่ค่าเมตรตรง ๆ
                            param.Set(val_m)
                        params_set = True

                    elif param.StorageType == DB.StorageType.String:
                        # Text → แสดงทั้งเมตรและฟุต
                        feet_val = val_m / 0.3048
                        param.Set("{:.3f} m ({:.6f} ft)".format(val_m, feet_val))
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
    ["⚠️ Skipped", str(stats["skipped_group"]), "Inside Model Group"],
    ["❌ Error", str(stats["error"]), "Issue"]
]

output.print_table(table_data=table_data, columns=["Status", "Count", "Desc"], formats=["", "", ""])

if skipped_ids:
    output.print_md("---\n### ⚠️ Skipped Elements")
    output.print_md("`IDs: {}`".format(", ".join(skipped_ids[:50]) + ("..." if len(skipped_ids)>50 else "")))

output.print_md("---")

# --- Save CSV Report to Export Path (รองรับ IronPython 2.7) ---
if export_path and os.path.exists(export_path):
    try:
        csv_file = os.path.join(export_path, "Coordinate_Update_Report.csv")
        # ใช้ codecs แทนฟังก์ชัน open แบบเดิมเพื่อรองรับ Unicode/UTF-8 ใน IronPython
        with codecs.open(csv_file, 'w', encoding='utf-8-sig') as f:
            # เพิ่ม " " ครอบ base_point_info เพื่อป้องกันปัญหาจุลภาค (,) ในข้อความ
            f.write('Project Base Point Info:,"{}"\n\n'.format(base_point_info))
            f.write("Status,Count,Desc\n")
            for row in table_data:
                f.write('{},{},"{}"\n'.format(row[0], row[1], row[2]))
                
        output.print_md("### 📁 Report Exported")
        output.print_md("บันทึกไฟล์รายงานไว้ที่: `{}`".format(csv_file))
    except Exception as e:
        output.print_md("### ❌ Export Error")
        output.print_md("ไม่สามารถบันทึกไฟล์ได้: {}".format(e))

if stats["success"] > 0:
    success_rate = (float(stats["success"]) / float(stats["total"])) * 100.0
    output.print_md("## 🎉 Success Rate: {:.1f}%".format(success_rate))

if stats["error"] == 0 and stats["skipped_group"] == 0:
    output.print_md("## 🎉 All Clear! 100% Success.")