# -*- coding: utf-8 -*-
__doc__ = "นำเข้าและวาง Family ตามพิกัด N/E จากไฟล์ Excel (.xlsx)"
__title__ = "Family Coord\nfrom Excel"
__author__ = "เพิ่มพงษ์ (Excel Version)"

import sys
import os
import math

from pyrevit import forms, DB, HOST_APP
from Autodesk.Revit.UI import UIApplication

import clr
from System.IO import FileStream, FileMode, FileAccess

# ============================================================
# ฟังก์ชันตั้งค่าพารามิเตอร์อย่างปลอดภัย
# ============================================================
def safe_set_parameter(element, param_name, value):
    """ตั้งค่าพารามิเตอร์อย่างปลอดภัย"""
    try:
        # ลองใช้ BuiltInParameter ก่อน
        if param_name.lower() == "mark":
            param = element.get_Parameter(DB.BuiltInParameter.ALL_MODEL_MARK)
        else:
            param = element.LookupParameter(param_name)
            
        if param and not param.IsReadOnly:
            if param.StorageType == DB.StorageType.String:
                param.Set(str(value))
                return True
            elif param.StorageType == DB.StorageType.Integer:
                param.Set(int(value))
                return True
            elif param.StorageType == DB.StorageType.Double:
                param.Set(float(value))
                return True
        return False
    except Exception as e:
        print("Error setting parameter {0}: {1}".format(param_name, e))
        return False

# ============================================================
# เตรียม ExcelDataReader
# ============================================================
def setup_excel_reader():
    try:
        # กรณีติดตั้ง ExcelDataReader ผ่าน GAC / global
        clr.AddReference("ExcelDataReader")
        clr.AddReference("ExcelDataReader.DataSet")
    except:
        # กรณีวาง DLL ไว้ข้างๆ script.py
        script_dir = os.path.dirname(__file__)
        dll1 = os.path.join(script_dir, "ExcelDataReader.dll")
        dll2 = os.path.join(script_dir, "ExcelDataReader.DataSet.dll")
        try:
            clr.AddReferenceToFileAndPath(dll1)
            clr.AddReferenceToFileAndPath(dll2)
        except Exception as e:
            forms.alert(
                "ไม่สามารถโหลด ExcelDataReader.dll ได้\n"
                "โปรดวางไฟล์ ExcelDataReader.dll และ ExcelDataReader.DataSet.dll\n"
                "ไว้ในโฟลเดอร์เดียวกับ script.py\n\nรายละเอียด:\n{0}".format(e),
                exitscript=True
            )

    import ExcelDataReader
    return ExcelDataReader


# ============================================================
# ฟังก์ชันช่วยอ่านค่าตัวเลขอย่างปลอดภัย
# ============================================================
def safe_float(val):
    try:
        return float(str(val).replace(",", "").strip())
    except:
        return None


# ============================================================
# เลือกไฟล์ Excel
# ============================================================
def select_excel_file():
    path = forms.pick_file(file_ext="xlsx", title="เลือกไฟล์ Excel (.xlsx) ที่มีพิกัด N/E")
    return path


# ============================================================
# อ่านข้อมูลจาก Excel (แบบแถวต่อแถว)
# ============================================================
def read_excel_file(excel_path, ExcelDataReader):
    data = []
    has_cutoff = False

    try:
        # เปิดไฟล์ Excel
        stream = FileStream(excel_path, FileMode.Open, FileAccess.Read)
        
        # สร้าง reader
        reader = ExcelDataReader.ExcelReaderFactory.CreateOpenXmlReader(stream)
        
        # อ่านข้อมูลแบบแถวต่อแถว
        headers = []
        row_index = 0
        
        while reader.Read():
            if row_index == 0:
                # อ่าน header
                headers = []
                for i in range(reader.FieldCount):
                    if not reader.IsDBNull(i):
                        headers.append(reader.GetString(i) if reader.IsDBNull(i) == False else "")
                    else:
                        headers.append("Column_{0}".format(i))
            else:
                # อ่านข้อมูล
                row_data = {}
                for i in range(reader.FieldCount):
                    col_name = headers[i] if i < len(headers) else "Col_{0}".format(i)
                    if reader.IsDBNull(i):
                        row_data[col_name] = None
                    else:
                        try:
                            row_data[col_name] = reader.GetValue(i)
                        except:
                            row_data[col_name] = None
                
                # ประมวลผลข้อมูล
                element_no = None
                e_val = None
                n_val = None
                cut_val = None
                
                # ค้นหาคอลัมน์โดยใช้ชื่อ
                for col_name, value in row_data.items():
                    if value is None:
                        continue
                        
                    col_name_lower = str(col_name).lower()
                    val_str = str(value).strip()
                    
                    # ElementNo
                    if element_no is None and any(key in col_name_lower for key in ["no", "pile", "element", "หมายเลข", "mark"]):
                        element_no = val_str
                    
                    # E coordinate
                    if e_val is None and any(key in col_name_lower for key in ["e", "east", "easting", "x", "ตะวันออก"]):
                        e_val = safe_float(value)
                    
                    # N coordinate  
                    if n_val is None and any(key in col_name_lower for key in ["n", "north", "northing", "y", "เหนือ"]):
                        n_val = safe_float(value)
                    
                    # Cutoff
                    if cut_val is None and any(key in col_name_lower for key in ["cut", "cutoff", "top", "elev", "ระดับ", "cut off"]):
                        cut_val = safe_float(value)
                
                # ตรวจสอบว่ามีข้อมูลครบ
                if element_no and e_val is not None and n_val is not None:
                    if cut_val is not None:
                        has_cutoff = True
                    
                    data.append({
                        "ElementNo": element_no,
                        "E": e_val,
                        "N": n_val,
                        "PileCutOff": cut_val
                    })
            
            row_index += 1

        # ปิด reader
        reader.Close()
        stream.Close()

        if not data:
            forms.alert("ไม่พบข้อมูล E/N ที่อ่านได้จากไฟล์ Excel", exitscript=True)

        return data, has_cutoff

    except Exception as ex:
        # ปิด reader หากมีข้อผิดพลาด
        try:
            if 'reader' in locals():
                reader.Close()
        except:
            pass
        try:
            if 'stream' in locals():
                stream.Close()
        except:
            pass
            
        forms.alert("เกิดข้อผิดพลาดขณะอ่านไฟล์ Excel:\n{0}".format(ex), exitscript=True)
        return [], False


# ============================================================
# ฟังก์ชันอ่าน Project Base Point และมุม
# ============================================================
def get_project_base_point_coordinates(doc):
    """คืน (base_e_m, base_n_m, angle_deg)"""
    try:
        project_base_point = DB.BasePoint.GetProjectBasePoint(doc)
        if project_base_point:
            eparam = project_base_point.get_Parameter(DB.BuiltInParameter.BASEPOINT_EASTWEST_PARAM)
            nparam = project_base_point.get_Parameter(DB.BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM)
            aparam = project_base_point.get_Parameter(DB.BuiltInParameter.BASEPOINT_ANGLETON_PARAM)

            if eparam and nparam and eparam.HasValue and nparam.HasValue:
                base_e = eparam.AsDouble() * 0.3048
                base_n = nparam.AsDouble() * 0.3048
                angle_deg = 0.0
                if aparam and aparam.HasValue:
                    angle_deg = aparam.AsDouble() * (180.0 / math.pi)
                return base_e, base_n, angle_deg

        # fallback แบบ collector
        collector = DB.FilteredElementCollector(doc).OfClass(DB.BasePoint)
        for bp in collector:
            if not bp.IsShared:
                eparam = bp.get_Parameter(DB.BuiltInParameter.BASEPOINT_EASTWEST_PARAM)
                nparam = bp.get_Parameter(DB.BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM)
                aparam = bp.get_Parameter(DB.BuiltInParameter.BASEPOINT_ANGLETON_PARAM)
                if eparam and nparam and eparam.HasValue and nparam.HasValue:
                    base_e = eparam.AsDouble() * 0.3048
                    base_n = nparam.AsDouble() * 0.3048
                    angle_deg = 0.0
                    if aparam and aparam.HasValue:
                        angle_deg = aparam.AsDouble() * (180.0 / math.pi)
                    return base_e, base_n, angle_deg

    except Exception as e:
        print("อ่าน Project Base Point ไม่สำเร็จ:", e)

    return 0.0, 0.0, 0.0


def get_actual_project_base_point_position(doc):
    """คืน (x_ft, y_ft) ของ Base Point ในโมเดล (ฟุต)"""
    try:
        project_base_point = DB.BasePoint.GetProjectBasePoint(doc)
        if project_base_point:
            pos = project_base_point.Position
            return pos.X, pos.Y

        collector = DB.FilteredElementCollector(doc).OfClass(DB.BasePoint)
        for bp in collector:
            if not bp.IsShared:
                pos = bp.Position
                return pos.X, pos.Y
    except Exception as e:
        print("อ่านตำแหน่ง Base Point ไม่สำเร็จ:", e)

    return 0.0, 0.0


# ============================================================
# แปลงพิกัด Survey → Revit XY (ฟุต)
# ============================================================
def transform_survey_to_revit_xy_feet(
        survey_e_m,
        survey_n_m,
        base_e_m,
        base_n_m,
        angle_rad,
        base_point_offset_x_ft,
        base_point_offset_y_ft):

    delta_e = survey_e_m - base_e_m
    delta_n = survey_n_m - base_n_m

    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    revit_x_m = delta_e * cos_a - delta_n * sin_a
    revit_y_m = delta_e * sin_a + delta_n * cos_a

    revit_x_ft = revit_x_m * 3.28084
    revit_y_ft = revit_y_m * 3.28084

    corrected_x = revit_x_ft + base_point_offset_x_ft
    corrected_y = revit_y_ft + base_point_offset_y_ft

    return corrected_x, corrected_y


# ============================================================
# เลือก Level ฐาน
# ============================================================
def pick_base_level(doc):
    levels = list(DB.FilteredElementCollector(doc).OfClass(DB.Level))
    if not levels:
        forms.alert("ไม่พบ Level ในโปรเจกต์", exitscript=True)

    level_dict = {lvl.Name: lvl for lvl in levels}
    chosen_name = forms.SelectFromList.show(
        sorted(level_dict.keys()),
        title="เลือก Base Level",
        multiselect=False
    )
    if not chosen_name:
        sys.exit()
    return level_dict[chosen_name]


# ============================================================
# เลือก Family + Type ที่จะสร้าง (แก้ไขแล้ว)
# ============================================================
def pick_family_symbol(doc):
    # เลือก Category
    cat_options = {
        "ฐานรากโครงสร้าง (Structural Foundation)": DB.BuiltInCategory.OST_StructuralFoundation,
        "เสาโครงสร้าง (Structural Columns)": DB.BuiltInCategory.OST_StructuralColumns,
        "Generic Models": DB.BuiltInCategory.OST_GenericModel,
    }

    cat_name = forms.SelectFromList.show(
        sorted(cat_options.keys()),
        title="เลือก Category ที่ต้องการสร้าง Family",
        multiselect=False
    )
    if not cat_name:
        sys.exit()

    bic = cat_options[cat_name]

    # เก็บ FamilySymbol ตาม Category
    col = DB.FilteredElementCollector(doc)\
        .OfCategory(bic)\
        .WhereElementIsElementType()

    symbols = [e for e in col if isinstance(e, DB.FamilySymbol)]
    if not symbols:
        forms.alert("ไม่พบ Family Type ใน Category ที่เลือก", exitscript=True)

    # map แสดงเป็น "<FamilyName : TypeName>" - แก้ไขส่วนนี้
    symbol_dict = {}
    for s in symbols:
        try:
            # ใช้ Parameter เพื่อดึงชื่ออย่างปลอดภัย
            family_name = "Unknown Family"
            type_name = "Unknown Type"
            
            # ดึงชื่อ Family
            try:
                if hasattr(s, 'Family') and s.Family:
                    family_param = s.Family.get_Parameter(DB.BuiltInParameter.ALL_MODEL_FAMILY_NAME)
                    if family_param:
                        family_name = family_param.AsString()
                    else:
                        family_name = s.Family.Name
            except:
                pass
                
            # ดึงชื่อ Type
            try:
                type_param = s.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_NAME)
                if type_param:
                    type_name = type_param.AsString()
                else:
                    type_name = s.Name
            except:
                pass
                
            key = "{0} : {1}".format(family_name, type_name)
        except Exception as e:
            # หากเกิดข้อผิดพลาด ให้ใช้ ID เป็น key
            key = "ID: {0}".format(s.Id.IntegerValue)
            
        symbol_dict[key] = s

    chosen = forms.SelectFromList.show(
        sorted(symbol_dict.keys()),
        title="เลือก Family Type",
        multiselect=False
    )
    if not chosen:
        sys.exit()

    return symbol_dict[chosen], bic


# ============================================================
# MAIN
# ============================================================
def main():
    uidoc = __revit__.ActiveUIDocument
    doc = uidoc.Document

    if not doc:
        forms.alert("ไม่พบเอกสาร Revit ที่เปิดอยู่", exitscript=True)

    # ตั้งค่า Excel Reader
    ExcelDataReader = setup_excel_reader()

    # เลือกไฟล์ Excel
    excel_path = select_excel_file()
    if not excel_path:
        forms.alert("ไม่ได้เลือกไฟล์ Excel", exitscript=True)

    # อ่านข้อมูลจาก Excel
    data, has_cutoff_data = read_excel_file(excel_path, ExcelDataReader)
    print("พบข้อมูล {0} แถว (มี CutOff: {1})".format(len(data), has_cutoff_data))

    # อ่าน Base Point + Offset
    base_e_m, base_n_m, angle_deg = get_project_base_point_coordinates(doc)
    bp_x_ft, bp_y_ft = get_actual_project_base_point_position(doc)
    angle_rad = math.radians(angle_deg)

    print("Base E/N (m):", base_e_m, base_n_m)
    print("BasePoint Offset (ft):", bp_x_ft, bp_y_ft)
    print("Angle (deg):", angle_deg)

    # เลือก Base Level
    base_level = pick_base_level(doc)

    # เลือก Family Type
    family_symbol, bic = pick_family_symbol(doc)

    # ตรวจสอบว่า Level ยังอยู่ในเอกสาร
    if base_level.IsValidObject is False:
        forms.alert("Base Level ไม่ถูกต้องหรือถูกลบไปแล้ว", exitscript=True)

    # เปิดใช้ symbol ถ้าเป็น Inactive
    if not family_symbol.IsActive:
        try:
            with DB.Transaction(doc, "Activate Symbol") as t:
                t.Start()
                family_symbol.Activate()
                doc.Regenerate()
                t.Commit()
        except Exception as e:
            forms.alert("ไม่สามารถเปิดใช้ Family Symbol: {0}".format(e), exitscript=True)

    # ตั้ง StructuralType ตาม Category
    structural_type = DB.Structure.StructuralType.NonStructural
    if bic == DB.BuiltInCategory.OST_StructuralColumns:
        structural_type = DB.Structure.StructuralType.Column
    elif bic == DB.BuiltInCategory.OST_StructuralFoundation:
        structural_type = DB.Structure.StructuralType.Footing

    # สร้าง Family ตามข้อมูลจาก Excel
    created_count = 0
    error_count = 0

    with DB.Transaction(doc, "Create Families from Excel") as t:
        t.Start()
        
        try:
            for row in data:
                try:
                    element_no = row["ElementNo"]
                    e_m = row["E"]
                    n_m = row["N"]
                    cut_m = row["PileCutOff"]

                    # แปลงพิกัด
                    x_ft, y_ft = transform_survey_to_revit_xy_feet(
                        e_m, n_m,
                        base_e_m, base_n_m,
                        angle_rad,
                        bp_x_ft, bp_y_ft
                    )

                    # คำนวณ Z
                    base_elev_ft = base_level.Elevation
                    z_ft = base_elev_ft
                    if cut_m is not None:
                        z_ft = cut_m * 3.28084

                    location = DB.XYZ(x_ft, y_ft, z_ft)

                    # สร้าง Family Instance
                    inst = doc.Create.NewFamilyInstance(
                        location,
                        family_symbol,
                        base_level,
                        structural_type
                    )

                    # พยายามตั้งค่า Mark (แต่ไม่ต้องกังวลถ้าไม่สำเร็จ)
                    safe_set_parameter(inst, "Mark", element_no)

                    created_count += 1

                except Exception as ex:
                    print("Error row {0}: {1}".format(row.get("ElementNo", "?"), ex))
                    error_count += 1
                    
            t.Commit()
            
        except Exception as global_error:
            t.RollBack()
            forms.alert("เกิดข้อผิดพลาดร้ายแรง: {0}".format(global_error), exitscript=True)

    forms.alert(
        "สร้าง Family จาก Excel เสร็จสิ้น!\n\n"
        "สร้างได้: {0} ตัว\nผิดพลาด: {1}\n".format(created_count, error_count),
        title="Family Coord from Excel"
    )


if __name__ == "__main__":
    main()