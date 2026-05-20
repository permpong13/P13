# -*- coding: utf-8 -*-
__title__ = "Filled Regions\n& List"
__author__ = "Tee_เพิ่มพงษ์"
__doc__ = "สร้าง Filled Regions และป้ายชื่อ"

from pyrevit import revit, DB, UI, HOST_APP, forms
from rpw.ui.forms import (FlexForm, Label, ComboBox, Separator, Button, TextBox)
from collections import OrderedDict
from pyrevit.framework import List
from Autodesk.Revit import Exceptions
import sys

def validate_positive_integer(value, field_name):
    """ตรวจสอบว่าค่าเป็นจำนวนเต็มบวก"""
    try:
        int_value = int(value)
        if int_value <= 0:
            raise ValueError("{} must be positive".format(field_name))
        return int_value
    except ValueError:
        forms.alert("Invalid {} value. Please enter a positive number.".format(field_name), exitscript=True)

def create_rectangle(base_point, width, height):
    """สร้างสี่เหลี่ยมจากจุดเริ่มต้น"""
    p1 = base_point
    p2 = DB.XYZ(base_point.X + width, base_point.Y, 0)
    p3 = DB.XYZ(base_point.X + width, base_point.Y + height, 0)
    p4 = DB.XYZ(base_point.X, base_point.Y + height, 0)
    
    # สร้างเส้นตรง
    lines = [
        DB.Line.CreateBound(p1, p2),
        DB.Line.CreateBound(p2, p3),
        DB.Line.CreateBound(p3, p4),
        DB.Line.CreateBound(p4, p1)
    ]
    
    return DB.CurveLoop.Create(List[DB.Curve](lines))

def convert_length_to_internal(d_units):
    """แปลงหน่วยความยาว"""
    try:
        units = revit.doc.GetUnits()
        if HOST_APP.is_newer_than(2021):
            internal_units = units.GetFormatOptions(DB.SpecTypeId.Length).GetUnitTypeId()
        else:
            internal_units = units.GetFormatOptions(DB.UnitType.UT_Length).DisplayUnits
        return DB.UnitUtils.ConvertToInternalUnits(d_units, internal_units)
    except Exception as e:
        forms.alert("Unit conversion error: {}".format(str(e)), exitscript=True)

def main():
    # ตรวจสอบ View
    view = revit.active_view
    if view.ViewType in [DB.ViewType.ThreeD, DB.ViewType.Schedule]:
        forms.alert("This tool cannot be used in 3D views or schedules", exitscript=True)
    
    # รวบรวม FilledRegionTypes
    coll_fill_reg = DB.FilteredElementCollector(revit.doc).OfClass(DB.FilledRegionType)
    fillreg_dict = {}
    
    for fr in coll_fill_reg:
        try:
            if fr.IsValidObject:
                name = fr.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
                fillreg_dict[fr] = name
        except:
            continue
    
    if not fillreg_dict:
        forms.alert("No filled region types found in project", exitscript=True)
    
    sorted_fillreg = OrderedDict(sorted(fillreg_dict.items(), key=lambda t:t[1]))
    
    # รวบรวม TextNoteTypes
    txt_types = DB.FilteredElementCollector(revit.doc).OfClass(DB.TextNoteType)
    text_style_dict = {}
    
    for txt_t in txt_types:
        try:
            if txt_t.IsValidObject:
                name = txt_t.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
                text_style_dict[name] = txt_t
        except:
            continue
    
    if not text_style_dict:
        forms.alert("No text styles found in project", exitscript=True)
    
    # สร้าง UI
    components = [
        Label("Pick Text Style"),
        ComboBox(name="textstyle_combobox", options=text_style_dict),
        Label("Box Width [mm]"),
        TextBox(name="box_width", Text="800"),
        Label("Box Height [mm]"),
        TextBox(name="box_height", Text="300"),
        Label("Vertical Spacing [mm]"),
        TextBox(name="box_offset", Text="100"),
        Button("Select")
    ]
    
    form = FlexForm("Create Filled Region Legend", components)
    ok = form.show()
    
    if not ok:
        sys.exit()
    
    # ตรวจสอบและกำหนดค่า
    text_style = form.values["textstyle_combobox"]
    box_width = validate_positive_integer(form.values["box_width"], "Box width")
    box_height = validate_positive_integer(form.values["box_height"], "Box height")
    box_offset = validate_positive_integer(form.values["box_offset"], "Vertical spacing")
    
    # คำนวณสเกลและหน่วย
    scale = float(view.Scale) / 100
    w = convert_length_to_internal(box_width) * scale
    h = convert_length_to_internal(box_height) * scale
    text_offset = convert_length_to_internal(10) * scale  # offset 10mm สำหรับข้อความ
    shift = convert_length_to_internal(box_offset + box_height) * scale
    
    # เลือกจุดเริ่มต้น
    with forms.WarningBar(title="Pick Starting Point"):
        try:
            start_point = revit.uidoc.Selection.PickPoint()
        except Exceptions.OperationCanceledException:
            forms.alert("Cancelled", ok=True, exitscript=True)
    
    # สร้าง Filled Regions และป้ายชื่อ
    current_point = start_point
    success_count = 0
    
    with revit.Transaction("Draw Filled Regions Legend"):
        for fr, name in sorted_fillreg.items():
            try:
                # สร้างสี่เหลี่ยม
                curve_loop = create_rectangle(current_point, w, h)
                
                # สร้าง Filled Region
                new_reg = DB.FilledRegion.Create(revit.doc, fr.Id, view.Id, [curve_loop])
                
                if new_reg is not None:
                    # สร้างป้ายชื่อ
                    text_position = DB.XYZ(
                        current_point.X + w + text_offset,
                        current_point.Y + (h / 2),
                        0
                    )
                    
                    text_note = DB.TextNote.Create(revit.doc, view.Id, text_position, name, text_style.Id)
                    success_count += 1
                
                # ย้ายจุดสำหรับอันถัดไป
                current_point = DB.XYZ(current_point.X, current_point.Y - shift, 0)
                
            except Exception as e:
                print("Failed to create {}: {}".format(name, str(e)))
                continue
    
    # แสดงผลสรุป
    if success_count > 0:
        forms.alert("Successfully created {} filled regions".format(success_count))
    else:
        forms.alert("No filled regions were created")

if __name__ == "__main__":
    main()