# -*- coding: utf-8 -*-
"""Calculate Pipe Start and End Bottom-of-Pipe (B.O.P.) elevations and set parameters for tagging."""

__title__ = "Pipe BOP\nCalculator"
__author__ = "เพิ่มพงษ์ ทวีกุล (P13)"
__doc__ = "คำนวณระดับท้องท่อ (Bottom of Pipe - B.O.P.) ที่จุดเริ่มต้น (BOP_Start) และจุดสิ้นสุด (BOP_End) เพื่อบันทึกค่าลงใน Parameter สำหรับใช้งานคู่กับ Tag"

import os
import tempfile
import math
from System.Collections.Generic import List
from pyrevit import revit, DB, script, forms

doc = revit.doc
app = doc.Application
output = script.get_output()

output.print_md("## **Pipe BOP & Slope Calculator (คำนวณระดับท้องท่อเพื่อการ Tag)**")

# =====================================================
# ฟังก์ชันตรวจสอบและสร้าง Shared Parameter อัตโนมัติ (สไตล์เดียวกับ Windows Cal)
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
# ตรวจสอบและเตรียมพารามิเตอร์เริ่มต้น
# =====================================================
output.print_md("### **1. ตรวจสอบ Parameter ในโปรเจกต์**")
cat_pipes = ["OST_PipeCurves"]

status_start = setup_parameter(doc, app, "BOP_Start", "Length", cat_pipes)
status_end   = setup_parameter(doc, app, "BOP_End",   "Length", cat_pipes)

if status_start in ["created", "updated", "exists"] and status_end in ["created", "updated", "exists"]:
    output.print_md("✅ **พารามิเตอร์ 'BOP_Start' และ 'BOP_End' (ชนิด LENGTH) พร้อมใช้งาน**")
else:
    output.print_md("⚠️ **เกิดข้อผิดพลาดในการตรวจสอบ/สร้างพารามิเตอร์ (BOP_Start: {}, BOP_End: {})**".format(status_start, status_end))
    script.exit()

# =====================================================
# ดึงข้อมูลท่อ (Pipes)
# =====================================================
selection = revit.get_selection()
pipes = [el for el in selection if isinstance(el, DB.Plumbing.Pipe)]

is_selection_mode = True
if not pipes:
    is_selection_mode = False
    pipes = DB.FilteredElementCollector(doc, doc.ActiveView.Id) \
              .OfCategory(DB.BuiltInCategory.OST_PipeCurves) \
              .WhereElementIsNotElementType() \
              .ToElements()

if not pipes:
    output.print_md("❌ **ไม่พบท่อ (Pipe) ในกลุ่มที่เลือก หรือในมุมมองปัจจุบัน**")
    script.exit()

output.print_md("---")
if is_selection_mode:
    output.print_md("### **2. กำลังคำนวณระดับท้องท่อ (Selection Mode) จำนวน: {} รายการ**".format(len(pipes)))
else:
    output.print_md("### **2. กำลังคำนวณระดับท้องท่อในมุมมองปัจจุบัน (Active View Mode) จำนวน: {} รายการ**".format(len(pipes)))

# =====================================================
# ตรวจสอบ Worksets ในกรณี Worksharing
# =====================================================
if doc.IsWorkshared:
    try:
        ws_ids = set()
        for p in pipes:
            if hasattr(p, 'WorksetId') and p.WorksetId != DB.WorksetId.InvalidWorksetId:
                ws_ids.add(p.WorksetId)
        if ws_ids:
            ws_list = List[DB.WorksetId]()
            for w_id in ws_ids:
                ws_list.Add(w_id)
            DB.WorksharingUtils.CheckoutWorksets(doc, ws_list)
    except Exception as ex:
        output.print_md("⚠️ **แจ้งเตือน: ไม่สามารถ Checkout Worksets บางรายการได้สำเร็จ (อาจเนื่องจากมีผู้อื่นถือครองอยู่): {}**".format(ex))

# =====================================================
# ฟังก์ชันอนุญาตให้มีค่าแตกต่างกันในแต่ละ Group Instance
# =====================================================
def set_allow_vary_between_groups(doc, param_name):
    iterator = doc.ParameterBindings.ForwardIterator()
    while iterator.MoveNext():
        definition = iterator.Key
        if definition.Name == param_name and isinstance(definition, DB.InternalDefinition):
            try:
                if not definition.VariesAcrossGroups:
                    definition.SetAllowVaryBetweenGroups(doc, True)
            except:
                pass
            break

# =====================================================
# คำนวณและเขียนระดับท้องท่อ
# =====================================================
t = DB.Transaction(doc, "Calculate Pipe BOP Parameters")
t.Start()

set_allow_vary_between_groups(doc, "BOP_Start")
set_allow_vary_between_groups(doc, "BOP_End")

success_count = 0
read_only_count = 0
group_skipped_count = 0
error_count = 0

summary_data = []

with forms.ProgressBar(title='กำลังคำนวณระดับท้องท่อ... ({value} จาก {max_value})', cancellable=True) as pb:
    for index, pipe in enumerate(pipes):
        if pb.cancelled:
            break
        pb.update_progress(index + 1, len(pipes))
        
        # 1. ข้ามท่อที่อยู่ใน Group เพื่อเลี่ยง Group Element Modification Error
        if hasattr(pipe, 'GroupId') and pipe.GroupId != DB.ElementId.InvalidElementId:
            group_skipped_count += 1
            continue
            
        try:
            # 2. ดึงเส้นโครงสร้างทางเรขาคณิต (Curve)
            geom_curve = pipe.Location.Curve
            if not geom_curve:
                error_count += 1
                continue
                
            # 3. ดึงระดับความสูงกึ่งกลางท่อที่จุดปลาย (Centerline endpoints z0, z1 in feet)
            p0 = geom_curve.GetEndPoint(0)
            p1 = geom_curve.GetEndPoint(1)
            
            z0 = p0.Z
            z1 = p1.Z
            
            # 4. ดึงขนาดเส้นผ่านศูนย์กลางภายนอก (Outside Diameter)
            od_param = pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPE_OUTER_DIAMETER)
            if od_param and od_param.HasValue:
                od = od_param.AsDouble()
            else:
                # กรณีฉุกเฉินให้ดึง Nominal Diameter แทน
                dia_param = pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
                od = dia_param.AsDouble() if dia_param else 0.0
                
            # 5. คำนวณหาจุดสูงสุดและต่ำสุดของท้องท่อ (B.O.P. = Centerline - Outside Diameter/2)
            z_high = max(z0, z1)
            z_low = min(z0, z1)
            
            bop_high = z_high - (od / 2.0)
            bop_low = z_low - (od / 2.0)
            
            # 6. ดึงข้อมูลความลาดชัน (Slope)
            slope_param = pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPE_SLOPE)
            slope_val = slope_param.AsDouble() if slope_param else 0.0
            
            # 7. เขียนระดับลงในพารามิเตอร์ BOP_Start (ด้านสูง) และ BOP_End (ด้านต่ำ)
            p_start = pipe.LookupParameter("BOP_Start")
            p_end = pipe.LookupParameter("BOP_End")
            
            if p_start and p_end:
                if not p_start.IsReadOnly and not p_end.IsReadOnly:
                    p_start.Set(bop_high)
                    p_end.Set(bop_low)
                    success_count += 1
                    
                    # บันทึกข้อมูลเพื่อรายงานผล
                    size_name = pipe.LookupParameter("Size").AsString() or "N/A"
                    sys_abbr = pipe.LookupParameter("System Abbreviation").AsString() or "N/A"
                    
                    bop_high_m = bop_high * 0.3048
                    bop_low_m = bop_low * 0.3048
                    slope_percent = slope_val * 100.0
                    
                    # แปลง Slope เป็นอัตราส่วน (เช่น 1:100)
                    if slope_val > 0.0001:
                        slope_ratio = "1:{:.0f}".format(1.0 / slope_val)
                    else:
                        slope_ratio = "Flat"
                        
                    summary_data.append({
                        "id": pipe.Id.IntegerValue if hasattr(pipe.Id, "IntegerValue") else pipe.Id.Value,
                        "name": "{} {}".format(size_name, sys_abbr),
                        "slope": "{:.2f}% ({})".format(slope_percent, slope_ratio),
                        "b_start": "{:.3f} m".format(bop_high_m),
                        "bop_cal": "{:.3f} m".format(bop_low_m)
                    })
                else:
                    read_only_count += 1
            else:
                error_count += 1
                
        except Exception as ex:
            error_count += 1

t.Commit()

# =====================================================
# รายงานผลลัพธ์
# =====================================================
output.print_md("### **สรุปผลการทำงาน**")
output.print_md("- อัปเดตข้อมูลระดับท้องท่อสำเร็จ: **{}** รายการ".format(success_count))
if group_skipped_count > 0:
    output.print_md("- ข้ามท่อที่อยู่ใน Group (ระบบไม่อนุญาตให้แก้ไข): **{}** รายการ".format(group_skipped_count))
if read_only_count > 0:
    output.print_md("- ⚠️ พารามิเตอร์เป็น Read-Only: **{}** รายการ".format(read_only_count))
if error_count > 0:
    output.print_md("- ❌ เกิดข้อผิดพลาดทางเทคนิค: **{}** รายการ".format(error_count))

if success_count > 0:
    output.print_md("---")
    output.print_md("### **ตารางตัวอย่างข้อมูลที่อัปเดต (สูงสุด 10 รายการแรก)**")
    output.print_md("| Pipe ID | Size & System | Slope | BOP_Start (BOP High) | BOP_End (BOP Low) |")
    output.print_md("| --- | --- | --- | --- | --- |")
    for row in summary_data[:10]:
        output.print_md("| {} | {} | {} | {} | {} |".format(
            row["id"], row["name"], row["slope"], row["b_start"], row["bop_cal"]
        ))
    output.print_md("---")
    output.print_md("**คำแนะนำ:** คุณสามารถนำพารามิเตอร์ `BOP_Start` และ `BOP_End` ไปจัดวางเป็นป้าย Tag ท่อในหน้า Drawing ของท่านได้ทันที")
