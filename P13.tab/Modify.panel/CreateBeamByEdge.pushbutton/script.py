# -*- coding: utf-8 -*-
import clr
import sys
import os
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import ObjectType

from pyrevit import forms

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app = __revit__.Application

def get_symbol_name(symbol):
    if not symbol: return "Unknown"
    try:
        fam_name = symbol.FamilyName
        name_param = symbol.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        type_name = name_param.AsString() if name_param else Element.Name.__get__(symbol)
        return "{} - {}".format(fam_name, type_name)
    except: return "Unknown Symbol"

def get_adaptive_template():
    base_path = app.FamilyTemplatePath
    candidates = [r"\Metric Generic Model Adaptive.rft", r"\Generic Model Adaptive.rft", r"\English\Metric Generic Model Adaptive.rft"]
    if base_path and os.path.exists(base_path):
        for c in candidates:
            path = base_path + c
            if os.path.exists(path): return path
    return forms.pick_file(file_ext='rft', title="เลือกไฟล์ Generic Model Adaptive.rft")

def auto_generate_adaptive_family(fam_name):
    """สร้าง Adaptive Family พร้อมเส้นโครง"""
    template_path = get_adaptive_template()
    if not template_path: return None

    try:
        fam_doc = app.NewFamilyDocument(template_path)
        t = Transaction(fam_doc, "Create Skeleton")
        t.Start()

        pt1 = fam_doc.FamilyCreate.NewReferencePoint(XYZ(0, 0, 0))
        pt2 = fam_doc.FamilyCreate.NewReferencePoint(XYZ(10, 0, 0))
        AdaptiveComponentFamilyUtils.MakeAdaptivePoint(fam_doc, pt1.Id, AdaptivePointType.PlacementPoint)
        AdaptiveComponentFamilyUtils.MakeAdaptivePoint(fam_doc, pt2.Id, AdaptivePointType.PlacementPoint)

        ref_array = ReferencePointArray()
        ref_array.Append(pt1)
        ref_array.Append(pt2)
        fam_doc.FamilyCreate.NewCurveByPoints(ref_array)

        fam_mgr = fam_doc.FamilyManager
        group_id = GroupTypeId.Data
        spec_id = SpecTypeId.String.Text 
        fam_mgr.AddParameter("Profile 1", group_id, spec_id, True)
        fam_mgr.AddParameter("Profile 2", group_id, spec_id, True)

        t.Commit()

        class FamilyLoadOpt(IFamilyLoadOptions):
            def OnFamilyFound(self, use, ov): return True
            def OnSharedFamilyFound(self, sh, use, src, ov): return True

        loaded_fam = fam_doc.LoadFamily(doc, FamilyLoadOpt())
        fam_doc.Close(False)
        
        if loaded_fam:
            t_rename = Transaction(doc, "Rename Family")
            t_rename.Start()
            loaded_fam.Name = fam_name
            t_rename.Commit()
            for s_id in loaded_fam.GetFamilySymbolIds():
                return doc.GetElement(s_id)
    except Exception as e:
        print("Error: {}".format(e))
    return None

def main():
    target_fam_name = "P13_Adaptive_Beam"
    symbol = None

    for s in FilteredElementCollector(doc).OfClass(FamilySymbol).ToElements():
        if s.Family.Name == target_fam_name:
            symbol = s
            break

    if not symbol:
        symbol = auto_generate_adaptive_family(target_fam_name)
    
    if not symbol: return

    profiles = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_ProfileFamilies).WhereElementIsElementType().ToElements()
    profile_dict = {get_symbol_name(p): p for p in profiles}
    p_names = sorted(profile_dict.keys())
    
    sel_p1 = forms.SelectFromList.show(p_names, title="เลือก Profile 1")
    sel_p2 = forms.SelectFromList.show(p_names, title="เลือก Profile 2")
    if not sel_p1 or not sel_p2: return

    try:
        # รับค่าการเลือก Edges ทั้งหมด
        raw_references = uidoc.Selection.PickObjects(ObjectType.Edge, "เลือกเส้นริมขอบ")
    except: return

    # >>> เพิ่มระบบกรองเส้นซ้ำ (Duplicate Filter) <<<
    seen_edges = set()
    unique_references = []
    for r in raw_references:
        ref_id = r.ConvertToStableRepresentation(doc)
        if ref_id not in seen_edges:
            seen_edges.add(ref_id)
            unique_references.append(r)

    t_main = Transaction(doc, "Place Beams")
    t_main.Start()
    if not symbol.IsActive: symbol.Activate()

    count = 0
    for ref in unique_references:
        curve = doc.GetElement(ref).GetGeometryObjectFromReference(ref).AsCurve()
        try:
            inst = AdaptiveComponentInstanceUtils.CreateAdaptiveComponentInstance(doc, symbol)
            pt_ids = AdaptiveComponentInstanceUtils.GetInstancePlacementPointElementRefIds(inst)
            
            doc.GetElement(pt_ids[0]).Position = curve.GetEndPoint(0)
            doc.GetElement(pt_ids[1]).Position = curve.GetEndPoint(1)
            
            p1 = inst.LookupParameter("Profile 1")
            p2 = inst.LookupParameter("Profile 2")
            if p1: p1.Set(sel_p1)
            if p2: p2.Set(sel_p2)
            count += 1
        except: pass

    t_main.Commit()
    forms.alert("สร้างสำเร็จ {} ชิ้น\n\nคำยืนยัน: วัตถุถูกวางแล้วแต่อาจมองไม่เห็น\nกรุณา Edit Family '{}' เพื่อปั้น Solid เชื่อมระหว่างจุดครับ".format(count, target_fam_name))

if __name__ == '__main__':
    main()