# -*- coding: utf-8 -*-
"""
Pole Foundation Coordinates (Center & 4 Corners)
Location in Revit: P13 Tab -> Coordinate Panel -> Pole Found. Coord
Replaces: Coordinate Lighting Center.dyn & Coordinate Lighting Corner.dyn
Author: เพิ่มพงษ์ ทวีกุล (P13)
"""
__title__ = "Pole Found.\nCoord"
__author__ = "เพิ่มพงษ์ ทวีกุล (P13)"
__doc__ = """คำนวณและลงค่าพิกัดจริง (Shared Coordinates: Easting, Northing)
สำหรับจุด Center และ 4 มุมของฐานรากเสาไฟ และเสา CCTV
- CNT_E_Coordinate, CNT_N_Coordinate (Center)
- CNT_E_Coordinate 1..4, CNT_N_Coordinate 1..4 (Corners 1-4)
"""

import sys
import os
import math
import codecs
from Autodesk.Revit.DB import *
from pyrevit import revit, DB, forms, script, HOST_APP

# ================================================================
# 1. CONFIG & PARAMETERS
# ================================================================
doc = revit.doc
app = doc.Application
output = script.get_output()
config = script.get_config()

PARAM_CENTER_E = "CNT_E_Coordinate"
PARAM_CENTER_N = "CNT_N_Coordinate"
PARAM_CORNERS_E = ["CNT_E_Coordinate 1", "CNT_E_Coordinate 2", "CNT_E_Coordinate 3", "CNT_E_Coordinate 4"]
PARAM_CORNERS_N = ["CNT_N_Coordinate 1", "CNT_N_Coordinate 2", "CNT_N_Coordinate 3", "CNT_N_Coordinate 4"]
ALL_PARAMS = [PARAM_CENTER_E, PARAM_CENTER_N] + PARAM_CORNERS_E + PARAM_CORNERS_N

class WarningSwallower(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, failuresAccessor):
        fails = failuresAccessor.GetFailureMessages()
        for f in fails:
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                failuresAccessor.DeleteWarning(f)
        return DB.FailureProcessingResult.Continue

# ================================================================
# 2. COORDINATE & GEOMETRY LOGIC
# ================================================================
def to_shared_coordinates(doc, pt_internal):
    """แปลงพิกัดจุดจาก Internal Origin (Feet) เป็น Shared Coordinates (Feet)"""
    total_transform = doc.ActiveProjectLocation.GetTotalTransform()
    return total_transform.Inverse.OfPoint(pt_internal)

def extract_solids_from_geometry(geom_elem):
    """สกัด Solid ทั้งหมดออกจาก GeometryElement (รวม GeometryInstance)"""
    solids = []
    if geom_elem is None:
        return solids
    for g in geom_elem:
        if isinstance(g, DB.Solid) and g.Volume > 1e-5:
            solids.append(g)
        elif isinstance(g, DB.GeometryInstance):
            inst_geom = g.GetInstanceGeometry()
            if inst_geom:
                for ig in inst_geom:
                    if isinstance(ig, DB.Solid) and ig.Volume > 1e-5:
                        solids.append(ig)
    return solids

def get_foundation_geometry(elem, corner_order="clockwise"):
    """
    ดึงตำแหน่ง Center และ 4 มุมของฐานราก (Internal Coordinates, Feet)
    corner_order:
      - 'clockwise': 1=บนซ้าย (NW), 2=บนขวา (NE), 3=ล่างขวา (SE), 4=ล่างซ้าย (SW)
      - 'dynamo': เรียงตาม (X, Y) 1=ล่างซ้าย, 2=บนซ้าย, 3=ล่างขวา, 4=บนขวา
    """
    center_xyz = None
    rotation_rad = 0.0
    loc = elem.Location
    
    if isinstance(loc, DB.LocationPoint):
        center_xyz = loc.Point
        if hasattr(loc, "Rotation"):
            rotation_rad = loc.Rotation
    elif hasattr(elem, "GetTransform"):
        trf = elem.GetTransform()
        if trf:
            center_xyz = trf.Origin

    opt = DB.Options()
    opt.ComputeReferences = False
    opt.DetailLevel = DB.ViewDetailLevel.Fine
    geom_elem = elem.get_Geometry(opt)
    solids = extract_solids_from_geometry(geom_elem)

    if not solids:
        bbox = elem.get_BoundingBox(None)
        if bbox:
            if center_xyz is None:
                center_xyz = (bbox.Min + bbox.Max) * 0.5
            z_top = bbox.Max.Z
            tl = DB.XYZ(bbox.Min.X, bbox.Max.Y, z_top)
            tr = DB.XYZ(bbox.Max.X, bbox.Max.Y, z_top)
            br = DB.XYZ(bbox.Max.X, bbox.Min.Y, z_top)
            bl = DB.XYZ(bbox.Min.X, bbox.Min.Y, z_top)
            if corner_order == "clockwise":
                corners = [tl, tr, br, bl]
            else:
                corners = [bl, tl, br, tr]
            return center_xyz, rotation_rad, corners
        return center_xyz, rotation_rad, None

    main_solid = max(solids, key=lambda s: s.Volume)
    centroid = main_solid.ComputeCentroid()
    if center_xyz is None:
        center_xyz = centroid

    cx, cy = centroid.X, centroid.Y

    # หมุนจุดยอดทั้งหมดด้วย -rotation_rad รอบ Centroid เพื่อหาขอบเขต Unrotated
    cos_neg = math.cos(-rotation_rad)
    sin_neg = math.sin(-rotation_rad)

    unrot_pts = []
    max_z = -1e9

    for edge in main_solid.Edges:
        for t_val in (0.0, 1.0):
            p = edge.Evaluate(t_val)
            if p.Z > max_z:
                max_z = p.Z
            dx = p.X - cx
            dy = p.Y - cy
            ux = cx + (dx * cos_neg - dy * sin_neg)
            uy = cy + (dx * sin_neg + dy * cos_neg)
            unrot_pts.append((ux, uy, p.Z))

    if not unrot_pts:
        return center_xyz, rotation_rad, None

    min_ux = min(p[0] for p in unrot_pts)
    max_ux = max(p[0] for p in unrot_pts)
    min_uy = min(p[1] for p in unrot_pts)
    max_uy = max(p[1] for p in unrot_pts)

    # 4 มุมบนระนาบ Unrotated:
    # TL = (min_ux, max_uy), TR = (max_ux, max_uy), BR = (max_ux, min_uy), BL = (min_ux, min_uy)
    if corner_order == "clockwise":
        unrot_corners = [
            (min_ux, max_uy), # 1: บนซ้าย (Top-Left / NW)
            (max_ux, max_uy), # 2: บนขวา (Top-Right / NE)
            (max_ux, min_uy), # 3: ล่างขวา (Bottom-Right / SE)
            (min_ux, min_uy), # 4: ล่างซ้าย (Bottom-Left / SW)
        ]
    else: # Dynamo raw sort (X, then Y)
        unrot_corners = [
            (min_ux, min_uy), # 1: ล่างซ้าย
            (min_ux, max_uy), # 2: บนซ้าย
            (max_ux, min_uy), # 3: ล่างขวา
            (max_ux, max_uy), # 4: บนขวา
        ]

    # หมุนจุดมุมกลับด้วย +rotation_rad รอบ Centroid
    cos_pos = math.cos(rotation_rad)
    sin_pos = math.sin(rotation_rad)

    rot_corners = []
    for ux, uy in unrot_corners:
        dx = ux - cx
        dy = uy - cy
        rx = cx + (dx * cos_pos - dy * sin_pos)
        ry = cy + (dx * sin_pos + dy * cos_pos)
        rot_corners.append(DB.XYZ(rx, ry, max_z))

    return center_xyz, rotation_rad, rot_corners

def is_length_parameter(param):
    """ตรวจสอบว่า Parameter เป็นประเภท Length (ความยาว) หรือไม่"""
    try:
        spec = param.Definition.GetSpecTypeId()
        if spec == DB.SpecTypeId.Length:
            return True
        if spec and "length" in spec.TypeId.lower():
            return True
    except:
        pass
    try:
        if param.Definition.ParameterType == DB.ParameterType.Length:
            return True
    except:
        pass
    try:
        ut = param.GetUnitTypeId()
        if ut and any(k in ut.TypeId.lower() for k in ["millimeter", "meter", "foot", "length"]):
            return True
    except:
        pass
    return False

def set_parameter_smart(elem, param_name, coord_feet, precision=3, use_mm=False):
    """
    เขียนค่าพิกัดลง Parameter:
    - use_mm=False: หน่วยเมตร เช่น 736101.451 (ตรงตามป้าย Spot Coordinate ในแบบ)
    - use_mm=True:  หน่วยมิลลิเมตร เช่น 736101451.456 (ตามค่าใน Properties ของ Revit และ Dynamo)
    """
    param = elem.LookupParameter(param_name)
    if not param or param.IsReadOnly:
        return False

    scale = 304.8 if use_mm else 0.3048
    target_display_val = coord_feet * scale
    formatted_str = "{:.{}f}".format(target_display_val, precision)

    if param.StorageType == DB.StorageType.String:
        param.Set(formatted_str)
        return True

    elif param.StorageType == DB.StorageType.Double:
        if is_length_parameter(param):
            # ใน Revit Length Parameter เมื่อ Project ตั้งหน่วยเป็น mm
            # Revit จะนำค่าในฐานข้อมูล (Feet) ไปคูณ 304.8
            # เพื่อให้หน้าต่าง Properties แสดงค่า target_display_val พอดี:
            # จึงต้องส่ง target_display_val / 304.8 ฟุต เข้าไปในฐานข้อมูล!
            val_in_feet = target_display_val / 304.8
            param.Set(val_in_feet)
            return True
        else:
            param.Set(float(target_display_val))
            return True

    return False

# ================================================================
# 3. FAMILY DISCOVERY & SELECTION
# ================================================================
class FamilyCandidateItem(forms.TemplateListItem):
    def __init__(self, fam_name, info):
        super(FamilyCandidateItem, self).__init__(info)
        self.fam_name = fam_name
        self.info = info

    @property
    def name(self):
        v_cnt = len(self.info["view_instances"])
        a_cnt = len(self.info["all_instances"])
        param_tag = "✅ มี Param" if self.info["has_params"] else "⚠️ ไม่มี Param"
        cat_name = self.info["category"]
        return "{} | ใน View: {} ต้น (โมเดล: {} ต้น) [{}] [{}]".format(
            self.fam_name, v_cnt, a_cnt, cat_name, param_tag
        )

def discover_foundation_families(doc):
    """ค้นหา Family ฐานรากและเสาทั้งหมดในโมเดล พร้อมตรวจว่ามี Parameter หรือไม่"""
    categories = [
        DB.BuiltInCategory.OST_LightingFixtures,
        DB.BuiltInCategory.OST_SecurityDevices,
        DB.BuiltInCategory.OST_CommunicationDevices,
        DB.BuiltInCategory.OST_ElectricalFixtures,
        DB.BuiltInCategory.OST_ElectricalEquipment,
        DB.BuiltInCategory.OST_StructuralFoundation,
        DB.BuiltInCategory.OST_GenericModel
    ]

    active_view_id = doc.ActiveView.Id
    fam_dict = {}

    # 1. รวบรวม instance ทั้งโมเดล
    for bic in categories:
        try:
            col = DB.FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType().ToElements()
            for el in col:
                sym = getattr(el, "Symbol", None)
                fam = getattr(sym, "Family", None) if sym else None
                fam_name = getattr(fam, "Name", None) or getattr(el, "Name", "")
                if not fam_name:
                    continue

                fn_l = fam_name.lower()
                has_param = (el.LookupParameter(PARAM_CENTER_E) is not None or 
                             el.LookupParameter("CNT_E_Coordinate 1") is not None)
                
                is_candidate = (has_param or 
                                "foundation" in fn_l or 
                                "pole" in fn_l or 
                                "cctv" in fn_l or 
                                "camera" in fn_l or 
                                "lgf" in fn_l or 
                                "เสา" in fn_l or 
                                "ฐานราก" in fn_l)

                if is_candidate:
                    if fam_name not in fam_dict:
                        cat_str = el.Category.Name if el.Category else "Other"
                        fam_dict[fam_name] = {
                            "family": fam,
                            "fam_name": fam_name,
                            "category": cat_str,
                            "all_instances": [],
                            "view_instances": [],
                            "has_params": has_param
                        }
                    fam_dict[fam_name]["all_instances"].append(el)
        except:
            pass

    # 2. รวบรวม instance ใน Active View
    for bic in categories:
        try:
            col_v = DB.FilteredElementCollector(doc, active_view_id).OfCategory(bic).WhereElementIsNotElementType().ToElements()
            for el in col_v:
                sym = getattr(el, "Symbol", None)
                fam = getattr(sym, "Family", None) if sym else None
                fam_name = getattr(fam, "Name", None) or getattr(el, "Name", "")
                if fam_name in fam_dict:
                    fam_dict[fam_name]["view_instances"].append(el)
        except:
            pass

    return fam_dict

# ================================================================
# 4. MAIN WORKFLOW
# ================================================================
def main():
    sel_ids = revit.get_selection().element_ids
    selected_elements = [doc.GetElement(id) for id in sel_ids if doc.GetElement(id)] if sel_ids else []

    # สำรวจ Family ฐานรากในไฟล์
    fam_dict = discover_foundation_families(doc)
    fam_count = len(fam_dict)

    # 1. หน้าต่างเมนูหลัก (แสดงทุกครั้ง ไม่ข้าม!)
    scope_options = []
    if selected_elements:
        scope_options.append("🎯 ทำเฉพาะชิ้นงานที่เลือกไว้ในโมเดล (Selected: {} รายการ)".format(len(selected_elements)))
    
    scope_options.append("📋 เลือกจากรายชื่อ Family ฐานรากในโมเดล (พบ {} Family ในโปรเจกต์)".format(fam_count))
    scope_options.append("👆 คลิกเลือกชิ้นงานบนหน้าจอทีละต้น (Pick Elements on Screen)")
    
    total_view = sum(len(f["view_instances"]) for f in fam_dict.values())
    total_all = sum(len(f["all_instances"]) for f in fam_dict.values())
    scope_options.append("🌐 ทำทุกต้นที่มีพารามิเตอร์พิกัด ใน Active View (ทั้งหมด {} ต้น)".format(total_view))
    scope_options.append("🏢 ทำทุกต้นที่มีพารามิเตอร์พิกัด ในทั้งโมเดล (ทั้งหมด {} ต้น)".format(total_all))

    selected_scope = forms.SelectFromList.show(
        scope_options,
        title="เลือกวิธีการลงพิกัดฐานรากเสาไฟ / CCTV",
        button_name="ถัดไป ➡️"
    )
    if not selected_scope:
        sys.exit()

    target_elements = []

    # กรณี 1: ทำเฉพาะชิ้นงานที่เลือกไว้
    if "ทำเฉพาะชิ้นงานที่เลือกไว้" in selected_scope:
        target_elements = selected_elements

    # กรณี 2: คลิกเลือกบนหน้าจอทีละต้น
    elif "คลิกเลือกชิ้นงานบนหน้าจอ" in selected_scope:
        try:
            picked_refs = revit.get_selection().pick_element(
                allow_multiple=True, 
                message="คลิกเลือกเสาที่ต้องการลงพิกัด แล้วกดปุ่ม Finish บนแถบ Option ด้านบน"
            )
            if picked_refs:
                if isinstance(picked_refs, list):
                    target_elements = [doc.GetElement(r.ElementId) if hasattr(r, 'ElementId') else doc.GetElement(r) for r in picked_refs]
                else:
                    elem = doc.GetElement(picked_refs.ElementId) if hasattr(picked_refs, 'ElementId') else doc.GetElement(picked_refs)
                    target_elements = [elem]
        except Exception:
            sys.exit()

    # กรณี 3: เลือกจากรายชื่อ Family ฐานรากในไฟล์
    elif "เลือกจากรายชื่อ Family" in selected_scope:
        if not fam_dict:
            forms.alert("❌ ไม่พบ Family ฐานรากหรือเสาในไฟล์นี้", title="ไม่พบข้อมูล")
            sys.exit()

        # สร้าง Checklist ให้ผู้ใช้เลือกติ๊ก Family
        fam_items = []
        for fn in sorted(fam_dict.keys()):
            f_item = FamilyCandidateItem(fn, fam_dict[fn])
            # ถ้ามี parameter ครบ ให้ติ๊กถูกไว้ล่วงหน้า
            if fam_dict[fn]["has_params"]:
                f_item.state = True
            fam_items.append(f_item)

        chosen_fams = forms.SelectFromList.show(
            fam_items,
            multiselect=True,
            title="เลือก Family ฐานรากที่ต้องการอัปเดตพิกัด (ติ๊กถูกรายการที่ต้องการ)",
            button_name="ถัดไป ➡️"
        )
        if not chosen_fams:
            sys.exit()

        # เลือกขอบเขตว่าใน View หรือทั้งโปรเจกต์
        view_choice = forms.SelectFromList.show(
            [
                "👁️ เฉพาะชิ้นงานใน View ปัจจุบัน (Active View)",
                "🏢 ชิ้นงานทั้งหมดในโมเดล (Entire Project)"
            ],
            title="เลือกขอบเขตพื้นที่สำหรับ Family ที่เลือก",
            button_name="ถัดไป ➡️"
        )
        if not view_choice:
            sys.exit()

        is_view_only = "Active View" in view_choice
        for item in chosen_fams:
            fn = item.fam_name if hasattr(item, "fam_name") else str(item)
            if fn in fam_dict:
                insts = fam_dict[fn]["view_instances"] if is_view_only else fam_dict[fn]["all_instances"]
                target_elements.extend(insts)

    # กรณี 4: ทำทุกต้นใน View หรือทั้งโปรเจกต์
    else:
        is_view = "Active View" in selected_scope
        for f in fam_dict.values():
            if f["has_params"]:
                target_elements.extend(f["view_instances"] if is_view else f["all_instances"])

    if not target_elements:
        forms.alert("❌ ไม่พบ Element ที่ตรงตามเงื่อนไข", title="ไม่พบข้อมูล")
        sys.exit()

    # 4. หน้าต่างตั้งค่าหน่วยและลำดับมุม
    setting_options = [
        "📐 หน่วยมิลลิเมตร (mm) เช่น 736101451.456 [ตรงตามช่อง Properties ของ Revit และ Dynamo เดิม] | ลำดับมุมตามเข็มนาฬิกา (แนะนำ)",
        "📏 หน่วยเมตร (m) เช่น 736101.451 [ตรงตามป้าย Spot Coordinate บนแบบ] | ลำดับมุมตามเข็มนาฬิกา",
        "🔀 หน่วยมิลลิเมตร (mm) | ลำดับมุมตามไฟล์ Dynamo เดิม (1=ล่างซ้าย, 2=บนซ้าย, 3=ล่างขวา, 4=บนขวา)",
        "🔀 หน่วยเมตร (m) | ลำดับมุมตามไฟล์ Dynamo เดิม (1=ล่างซ้าย, 2=บนซ้าย, 3=ล่างขวา, 4=บนขวา)"
    ]

    selected_setting = forms.SelectFromList.show(
        setting_options,
        title="เลือกหน่วยพิกัดและลำดับมุมสำหรับบันทึกลง Parameter",
        button_name="🚀 เริ่มคำนวณและบันทึก"
    )
    if not selected_setting:
        sys.exit()

    use_mm = "มิลลิเมตร (mm)" in selected_setting
    corner_order = "dynamo" if "ตามไฟล์ Dynamo เดิม" in selected_setting else "clockwise"
    unit_label = "mm" if use_mm else "m"
    precision = 4 if use_mm else 3

    # ================================================================
    # 5. EXECUTION & TRANSACTION
    # ================================================================
    output.print_md("# 📍 Pole Foundation Coordinate Update")
    output.print_md("**Target Elements:** {} รายการ | **หน่วย:** `{}` | **ลำดับมุม:** `{}`".format(
        len(target_elements), unit_label, "ตามเข็มนาฬิกา (1=บนซ้าย, 2=บนขวา...)" if corner_order=="clockwise" else "ตาม Dynamo เดิม"
    ))
    output.print_md("---")

    # ปลดล็อก Varies Across Groups
    t_grp = DB.Transaction(doc, "Enable Varies Across Groups")
    t_grp.Start()
    try:
        iterator = doc.ParameterBindings.ForwardIterator()
        while iterator.MoveNext():
            definition = iterator.Key
            if definition.Name in ALL_PARAMS and isinstance(definition, DB.InternalDefinition):
                try:
                    if not definition.VariesAcrossGroups:
                        definition.SetAllowVaryBetweenGroups(doc, True)
                except: pass
        t_grp.Commit()
    except:
        t_grp.RollBack()

    # เริ่ม Transaction อัปเดตพิกัด
    t = DB.Transaction(doc, "Update Pole Foundation Coordinates")
    t.Start()
    t.SetFailureHandlingOptions(t.GetFailureHandlingOptions().SetFailuresPreprocessor(WarningSwallower()))

    stats = {"success": 0, "failed": 0, "missing_params": 0}
    report_rows = []

    with forms.ProgressBar(title="กำลังคำนวณพิกัดฐานราก... {value}/{max_value}", cancellable=True) as pb:
        for idx, elem in enumerate(target_elements, 1):
            if pb.cancelled:
                break
            pb.update_progress(idx, len(target_elements))

            fam_name = getattr(getattr(elem, "Symbol", None), "FamilyName", elem.Name)
            type_name = getattr(getattr(elem, "Symbol", None), "Name", "")

            # ตรวจสอบว่ามี Parameter ครบหรือไม่
            has_all_params = all(elem.LookupParameter(p) is not None for p in ALL_PARAMS)
            if not has_all_params:
                stats["missing_params"] += 1
                report_rows.append([str(elem.Id), fam_name, type_name, "⚠️ Parameter ไม่ครบ", "-", "-", "-", "-", "-", "-"])
                continue

            # คำนวณพิกัด
            try:
                center_xyz, rot_rad, corners_xyz = get_foundation_geometry(elem, corner_order=corner_order)
                if center_xyz is None or not corners_xyz or len(corners_xyz) < 4:
                    stats["failed"] += 1
                    report_rows.append([str(elem.Id), fam_name, type_name, "❌ ถอดรูปทรงไม่สำเร็จ", "-", "-", "-", "-", "-", "-"])
                    continue

                center_shared = to_shared_coordinates(doc, center_xyz)
                corners_shared = [to_shared_coordinates(doc, cp) for cp in corners_xyz]

                # บันทึกค่าลง Parameter
                set_parameter_smart(elem, PARAM_CENTER_E, center_shared.X, precision=precision, use_mm=use_mm)
                set_parameter_smart(elem, PARAM_CENTER_N, center_shared.Y, precision=precision, use_mm=use_mm)

                set_parameter_smart(elem, PARAM_CORNERS_E[0], corners_shared[0].X, precision=precision, use_mm=use_mm)
                set_parameter_smart(elem, PARAM_CORNERS_N[0], corners_shared[0].Y, precision=precision, use_mm=use_mm)
                set_parameter_smart(elem, PARAM_CORNERS_E[1], corners_shared[1].X, precision=precision, use_mm=use_mm)
                set_parameter_smart(elem, PARAM_CORNERS_N[1], corners_shared[1].Y, precision=precision, use_mm=use_mm)
                set_parameter_smart(elem, PARAM_CORNERS_E[2], corners_shared[2].X, precision=precision, use_mm=use_mm)
                set_parameter_smart(elem, PARAM_CORNERS_N[2], corners_shared[2].Y, precision=precision, use_mm=use_mm)
                set_parameter_smart(elem, PARAM_CORNERS_E[3], corners_shared[3].X, precision=precision, use_mm=use_mm)
                set_parameter_smart(elem, PARAM_CORNERS_N[3], corners_shared[3].Y, precision=precision, use_mm=use_mm)

                # ค่าแสดงผลสำหรับรายงาน
                scale = 304.8 if use_mm else 0.3048
                c_e = center_shared.X * scale
                c_n = center_shared.Y * scale
                c1_e = corners_shared[0].X * scale
                c1_n = corners_shared[0].Y * scale
                c2_e = corners_shared[1].X * scale
                c2_n = corners_shared[1].Y * scale
                c3_e = corners_shared[2].X * scale
                c3_n = corners_shared[2].Y * scale
                c4_e = corners_shared[3].X * scale
                c4_n = corners_shared[3].Y * scale

                stats["success"] += 1
                report_rows.append([
                    str(elem.Id), fam_name, type_name, "✅ สำเร็จ",
                    "{:.{}f}, {:.{}f}".format(c_e, precision, c_n, precision),
                    "{:.{}f}, {:.{}f}".format(c1_e, precision, c1_n, precision),
                    "{:.{}f}, {:.{}f}".format(c2_e, precision, c2_n, precision),
                    "{:.{}f}, {:.{}f}".format(c3_e, precision, c3_n, precision),
                    "{:.{}f}, {:.{}f}".format(c4_e, precision, c4_n, precision),
                ])

            except Exception as ex:
                stats["failed"] += 1
                report_rows.append([str(elem.Id), fam_name, type_name, "❌ Error: {}".format(ex), "-", "-", "-", "-", "-", "-"])

    t.Commit()

    # รายงานผล
    summary_table = [
        ["✅ สำเร็จ (Success)", str(stats["success"]), "อัปเดต Center และ 4 มุมครบถ้วนถูกต้อง"],
        ["⚠️ พารามิเตอร์ไม่ครบ (Missing Params)", str(stats["missing_params"]), "ไม่มี Parameter CNT_E/N_Coordinate ใน Family"],
        ["❌ ล้มเหลว (Failed)", str(stats["failed"]), "เกิดข้อผิดพลาด"]
    ]
    output.print_table(table_data=summary_table, columns=["สถานะ", "จำนวน", "คำอธิบาย"])

    output.print_md("### 📋 ตารางพิกัดที่บันทึก (หน่วย: {})".format(unit_label))
    detail_cols = ["Element ID", "Family", "Type", "Status", "Center (E, N)", "Corner 1", "Corner 2", "Corner 3", "Corner 4"]
    output.print_table(table_data=report_rows[:100], columns=detail_cols)

    # ส่งออก CSV
    export_dir = getattr(config, "export_path", "")
    if not export_dir or not os.path.exists(export_dir):
        export_dir = os.path.expanduser("~")

    csv_path = os.path.join(export_dir, "Pole_Foundation_Coordinates_Report.csv")
    try:
        with codecs.open(csv_path, "w", encoding="utf-8-sig") as f:
            f.write("Element ID,Family,Type,Status,Center E,Center N,Corner 1 E,Corner 1 N,Corner 2 E,Corner 2 N,Corner 3 E,Corner 3 N,Corner 4 E,Corner 4 N\n")
            for r in report_rows:
                f.write('{},"{}","{}",{},"{}"\n'.format(r[0], r[1], r[2], r[3], '","'.join(r[4:])))
        output.print_md("📁 **รายงาน CSV บันทึกไว้ที่:** `{}`".format(csv_path))
    except:
        pass

    if stats["success"] > 0:
        forms.alert("อัปเดตพิกัดเสร็จสิ้น {} ต้น!\n(หน่วย: {}, ลำดับมุม: {})".format(
            stats["success"], unit_label, "ตามเข็มนาฬิกา" if corner_order=="clockwise" else "ตาม Dynamo"
        ), title="สำเร็จ")

if __name__ == "__main__":
    main()
