# -*- coding: utf-8 -*-
import clr
import sys
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.DB.Structure import StructuralType

from pyrevit import forms

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

def get_symbol_name(symbol):
    try: fam_name = symbol.FamilyName
    except: fam_name = "Unknown Family"
    try:
        sym_name_param = symbol.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        type_name = sym_name_param.AsString() if sym_name_param else "Unknown Type"
    except: type_name = "Unknown Type"
    return "{} - {}".format(fam_name, type_name)

def get_curveloop_from_profile(profile_symbol):
    try:
        # เปิดเข้าไปอ่านเส้นใน Family Profile
        fam_doc = doc.EditFamily(profile_symbol.Family)
        curve_elements = FilteredElementCollector(fam_doc).OfClass(CurveElement).ToElements()
        
        curves = []
        for c in curve_elements:
            if c.GeometryCurve and c.GeometryCurve.IsBound:
                # กรองไม่เอาเส้น Reference Line ที่ใช้สร้าง Family อ้างอิง
                if c.GetType().Name == "ReferenceLine":
                    continue
                curves.append(c.GeometryCurve)
                
        fam_doc.Close(False) # ปิด Family แบบไม่เซฟ
        
        if not curves: 
            print("Error: ไม่พบเส้นขอบ 2D ภายใน Profile '{}'".format(profile_symbol.Family.Name))
            return None
            
        # จัดเรียงเส้นขอบให้ต่อกันเป็นวงปิด
        sorted_curves = [curves.pop(0)]
        while curves:
            last_curve = sorted_curves[-1]
            end_pt = last_curve.GetEndPoint(1)
            found = False
            for i, c in enumerate(curves):
                # เพิ่ม Tolerance (0.001) เผื่อ Profile วาดเส้นไม่สนิทกัน 100%
                if c.GetEndPoint(0).DistanceTo(end_pt) < 0.001:
                    sorted_curves.append(c)
                    curves.pop(i)
                    found = True
                    break
                elif c.GetEndPoint(1).DistanceTo(end_pt) < 0.001:
                    sorted_curves.append(c.CreateReversed())
                    curves.pop(i)
                    found = True
                    break
            
            # ถ้าหาเส้นต่อไม่ได้แล้ว ให้หยุด (เผื่อเป็นหน้าตัดกลวง จะเอาแค่วงนอกสุด)
            if not found: 
                break
                
        loop = CurveLoop()
        for c in sorted_curves: 
            loop.Append(c)
        return loop
        
    except Exception as e:
        print("Profile Extraction Error: {}".format(e))
        return None

def transform_profile_to_curve(loop, curve, is_end=False):
    param = 1.0 if is_end else 0.0
    origin = curve.GetEndPoint(1) if is_end else curve.GetEndPoint(0)
    tangent = curve.ComputeDerivatives(param, True).BasisX.Normalize()
    
    transform = Transform.Identity
    transform.Origin = origin
    up = XYZ.BasisZ
    if tangent.IsAlmostEqualTo(XYZ.BasisZ) or tangent.IsAlmostEqualTo(-XYZ.BasisZ):
        up = XYZ.BasisY
        
    x_axis = up.CrossProduct(tangent).Normalize()
    y_axis = tangent.CrossProduct(x_axis).Normalize()
    transform.BasisX = x_axis
    transform.BasisY = y_axis
    transform.BasisZ = tangent
    return CurveLoop.CreateViaTransform(loop, transform)

def main():
    options_list = [
        "1. สร้างคานปกติ (เลือก Type ที่มีในโปรเจกต์)",
        "2. สร้างคานแบบ Swept Blend (เลือก Profile 1 & 2 สร้างอัตโนมัติ)"
    ]
    selected_option = forms.SelectFromList.show(options_list, title="เลือกรูปแบบการสร้างคาน")
    if not selected_option: sys.exit()

    # ---------------------------------------------------------
    # โหมด 1: คานปกติ
    # ---------------------------------------------------------
    if selected_option.startswith("1"):
        framing_types = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralFraming).WhereElementIsElementType().ToElements()
        framing_dict = {get_symbol_name(t): t for t in framing_types}
        selected_name = forms.SelectFromList.show(sorted(framing_dict.keys()), title="เลือก Type ของคาน")
        if not selected_name: sys.exit()
        
        beam_symbol = framing_dict[selected_name]
        level = doc.ActiveView.GenLevel or FilteredElementCollector(doc).OfClass(Level).FirstElement()
        
        try: references = uidoc.Selection.PickObjects(ObjectType.Edge, "คลิ๊กเลือกเส้นขอบ (กด Finish บน Option Bar)")
        except: sys.exit()

        t = Transaction(doc, "Create Standard Beams")
        t.Start()
        if not beam_symbol.IsActive: beam_symbol.Activate()
        
        count = 0
        for i, ref in enumerate(references):
            geom_obj = doc.GetElement(ref).GetGeometryObjectFromReference(ref)
            if isinstance(geom_obj, Edge):
                try:
                    doc.Create.NewFamilyInstance(geom_obj.AsCurve(), beam_symbol, level, StructuralType.Beam)
                    count += 1
                except Exception as e:
                    print("Failed on line {}: {}".format(i, e))
        t.Commit()
        forms.alert("สร้างคานสำเร็จ {} ชิ้น".format(count), title="สำเร็จ")

    # ---------------------------------------------------------
    # โหมด 2: Swept Blend 
    # ---------------------------------------------------------
    elif selected_option.startswith("2"):
        profiles = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_ProfileFamilies).WhereElementIsElementType().ToElements()
        profile_dict = {get_symbol_name(p): p for p in profiles}
        profile_names = sorted(profile_dict.keys())
        
        if not profile_names:
            forms.alert("ไม่พบ Profile ในโปรเจกต์ กรุณาโหลด Family Profile ก่อน", title="แจ้งเตือน")
            sys.exit()

        selected_p1_name = forms.SelectFromList.show(profile_names, title="เลือก Profile 1 (หัว)")
        if not selected_p1_name: sys.exit()
        p1_symbol = profile_dict[selected_p1_name]
        
        selected_p2_name = forms.SelectFromList.show(profile_names, title="เลือก Profile 2 (ท้าย)")
        if not selected_p2_name: sys.exit()
        p2_symbol = profile_dict[selected_p2_name]

        try: references = uidoc.Selection.PickObjects(ObjectType.Edge, "คลิ๊กเลือกเส้นขอบ (กด Finish เมื่อเสร็จ)")
        except: sys.exit()

        # >>> แก้ไข: ดึงเส้นจาก Profile ก่อนที่จะเปิด Transaction <<<
        loop1 = get_curveloop_from_profile(p1_symbol)
        loop2 = get_curveloop_from_profile(p2_symbol)
        
        if not loop1 or not loop2:
            forms.alert("ดึงเส้น Profile ไม่สำเร็จ\n(หากมีหน้าต่างข้อความดำๆ เด้งขึ้นมาด้านหลัง ให้ลองดู Error ตรงนั้นครับ)", title="Error")
            sys.exit()

        # เริ่ม Transaction หลังจากดึง Profile สำเร็จแล้วเท่านั้น
        t_main = Transaction(doc, "Create Swept Blend DirectShape")
        t_main.Start()
        
        cat_id = ElementId(BuiltInCategory.OST_StructuralFraming)
        count = 0
        
        for i, ref in enumerate(references):
            geom_obj = doc.GetElement(ref).GetGeometryObjectFromReference(ref)
            if isinstance(geom_obj, Edge):
                curve = geom_obj.AsCurve()
                try:
                    trans_loop1 = transform_profile_to_curve(loop1, curve, is_end=False)
                    trans_loop2 = transform_profile_to_curve(loop2, curve, is_end=True)
                    
                    solid_opts = SolidOptions(ElementId.InvalidElementId, ElementId.InvalidElementId)
                    solid = GeometryCreationUtilities.CreateLoftGeometry([trans_loop1, trans_loop2], solid_opts)
                    
                    ds = DirectShape.CreateElement(doc, cat_id)
                    ds.ApplicationId = "pyRevit_CustomTools"
                    ds.ApplicationDataId = "SweptBlendEdge"
                    ds.SetShape([solid])
                    
                    count += 1
                except Exception as e:
                    print("ข้ามการสร้างคานเส้นที่ {}: เนื่องจากความโค้งซับซ้อนเกินไป ({})".format(i+1, e))

        t_main.Commit()
        forms.alert("สร้างคาน Swept Blend สำเร็จ {} ชิ้น".format(count), title="สำเร็จ")

if __name__ == '__main__':
    main()