# -*- coding: utf-8 -*-
__title__ = "Cut Wall\nAngle"
__author__ = "Permpong Taweekul"

import os
import sys
from System.Collections.Generic import List
from pyrevit import revit, DB, UI, forms, script

doc = revit.doc
uidoc = revit.uidoc
app = doc.Application

# 1. Configuration
cfg = script.get_config()
VOID_FAMILY_NAME = cfg.get_option('void_family_name', 'Void_Cutter_LineBased')
STRUCTURAL_CONNECTIONS_CATEGORY = DB.BuiltInCategory.OST_StructConnections
STRUCTURAL_CONNECTIONS_SUFFIX = "_StructuralConnections_FullHeight"
WALL_CUT_COMMENTS = "Wall-Cut"
VOID_VERTICAL_REACH = 1000.0
SUBCAT_NAME = "Hidden Void Cutters"

class FamilyLoadOptions(DB.IFamilyLoadOptions):
    def OnFamilyFound(self, familyInUse, overwriteParameterValues): return True
    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues): return True

class SuppressWarnings(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, failuresAccessor):
        for failure in failuresAccessor.GetFailureMessages():
            if failure.GetSeverity() == DB.FailureSeverity.Warning:
                failuresAccessor.DeleteWarning(failure)
        return DB.FailureProcessingResult.Continue

# 2. Cleanup Function
def purge_unused_void_families():
    t_purge = DB.Transaction(doc, "Purge Unused Void Families")
    t_purge.Start()
    try:
        families = DB.FilteredElementCollector(doc).OfClass(DB.Family).ToElements()
        for fam in families:
            if fam.Name.startswith(VOID_FAMILY_NAME):
                used = False
                for sym_id in fam.GetFamilySymbolIds():
                    filter = DB.FamilyInstanceFilter(doc, sym_id)
                    if len(DB.FilteredElementCollector(doc).WherePasses(filter).ToElementIds()) > 0:
                        used = True; break
                if not used: doc.Delete(fam.Id)
        t_purge.Commit()
    except: t_purge.RollBack()

# 3. Dynamic Void Family Creation
def get_or_create_dynamic_void_family(dist_feet, width_feet):
    dist_mm = int(dist_feet * 304.8)
    w_mm = int(width_feet * 304.8)
    # A full-height suffix prevents reuse of prior fixed-height cutter families.
    dynamic_family_name = "{}{}_L{}_W{}".format(
        VOID_FAMILY_NAME, STRUCTURAL_CONNECTIONS_SUFFIX, dist_mm, w_mm)
    
    collector = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).ToElements()
    void_symbol = next((s for s in collector if s.FamilyName == dynamic_family_name), None)
    if void_symbol: return void_symbol

    script_dir = os.path.dirname(__file__)
    family_path = os.path.join(script_dir, dynamic_family_name + ".rfa")
    
    template_path = None
    for i in range(2023, 2028):
        p = r"C:\ProgramData\Autodesk\RVT {}\Family Templates".format(i)
        if os.path.exists(p):
            for root, dirs, files in os.walk(p):
                for f in files:
                    if "generic model line based.rft" in f.lower():
                        template_path = os.path.join(root, f); break
            if template_path: break

    if not template_path:
        forms.alert("A Generic Model line-based family template could not be found.",
                    title="Cut Wall Angle", warn_icon=True)
        return None

    fam_doc = app.NewFamilyDocument(template_path)
    t = DB.Transaction(fam_doc, "Create Geometry")
    t.Start()
    try:
        structural_connections = fam_doc.Settings.Categories.get_Item(STRUCTURAL_CONNECTIONS_CATEGORY)
        fam_doc.OwnerFamily.FamilyCategory = structural_connections
        fam_doc.OwnerFamily.get_Parameter(DB.BuiltInParameter.FAMILY_ALLOW_CUT_WITH_VOIDS).Set(1)
        subcat = None
        if structural_connections.CanAddSubcategory:
            subcat = (structural_connections.SubCategories.get_Item(SUBCAT_NAME)
                      if structural_connections.SubCategories.Contains(SUBCAT_NAME)
                      else fam_doc.Settings.Categories.NewSubcategory(structural_connections, SUBCAT_NAME))
        
        p0, p1 = DB.XYZ(0, 0, 0), DB.XYZ(dist_feet, 0, 0)
        p2, p3 = DB.XYZ(dist_feet, -width_feet, 0), DB.XYZ(0, -width_feet, 0)
        c_array = DB.CurveArray()
        for l in [DB.Line.CreateBound(p0,p1), DB.Line.CreateBound(p1,p2), DB.Line.CreateBound(p2,p3), DB.Line.CreateBound(p3,p0)]: c_array.Append(l)
        
        arr_array = DB.CurveArrArray(); arr_array.Append(c_array)
        sketch_plane = DB.SketchPlane.Create(fam_doc, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, DB.XYZ.Zero))
        ext = fam_doc.FamilyCreate.NewExtrusion(False, arr_array, sketch_plane, 10.0)
        # This span remains valid when the wall Top or Bottom is edited later.
        ext.get_Parameter(DB.BuiltInParameter.EXTRUSION_START_PARAM).Set(-VOID_VERTICAL_REACH)
        ext.get_Parameter(DB.BuiltInParameter.EXTRUSION_END_PARAM).Set(VOID_VERTICAL_REACH)
        if subcat:
            ext.Subcategory = subcat
        t.Commit()
    except Exception as err:
        t.RollBack()
        fam_doc.Close(False)
        forms.alert("Could not create a Structural Connections void family.\n\n{}".format(err),
                    title="Cut Wall Angle", warn_icon=True)
        return None

    fam_doc.SaveAs(family_path, DB.SaveAsOptions(OverwriteExistingFile=True))
    fam_doc.Close(False)
    with revit.Transaction("Load Family"): doc.LoadFamily(family_path, FamilyLoadOptions())
    try: os.remove(family_path)
    except: pass
    return next((s for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol) if s.FamilyName == dynamic_family_name), None)

# 4. Main Execution
def cut_wall_angle():
    try:
        ref = uidoc.Selection.PickObject(UI.Selection.ObjectType.Element, "1/4: Select a wall")
        wall = doc.GetElement(ref)
        raw_pt1 = uidoc.Selection.PickPoint("2/4: Select the cut start point")
        raw_pt2 = uidoc.Selection.PickPoint("3/4: Select the cut end point")
        raw_pt3 = uidoc.Selection.PickPoint("4/4: Select the side to remove")
    except: return

    pt1, pt2, pt3 = [DB.XYZ(p.X, p.Y, 0) for p in [raw_pt1, raw_pt2, raw_pt3]]
    wall_curve = wall.Location.Curve
    wall_dir = wall_curve.Direction if isinstance(wall_curve, DB.Line) else wall_curve.ComputeDerivatives(wall_curve.Project(pt1).Parameter, True).BasisX
    wall_normal = DB.XYZ(-wall_dir.Y, wall_dir.X, 0).Normalize()
    
    v_user = pt2 - pt1
    mag = max(abs(v_user.DotProduct(wall_dir)), abs(v_user.DotProduct(wall_normal)))
    dir_45 = (wall_dir * (1 if v_user.DotProduct(wall_dir) >= 0 else -1) * mag + wall_normal * (1 if v_user.DotProduct(wall_normal) >= 0 else -1) * mag).Normalize()
    
    # Add a margin so the void fully spans the wall thickness and cut line.
    wall_width = wall.Width
    safe_width = wall_width + 0.5 
    buffer = 1.0 
    
    start_pt = pt1 - dir_45 * buffer
    end_pt = pt1 + dir_45 * (abs(v_user.DotProduct(dir_45)) + buffer)
    
    v_line = end_pt - start_pt
    v_pt3 = pt3 - pt1
    cut_line = DB.Line.CreateBound(start_pt, end_pt) if (v_line.X * v_pt3.Y - v_line.Y * v_pt3.X) < 0 else DB.Line.CreateBound(end_pt, start_pt)

    level = doc.GetElement(wall.LevelId)
    void_symbol = get_or_create_dynamic_void_family(cut_line.Length, safe_width)
    if not void_symbol: return
    if not void_symbol.IsActive:
        with revit.Transaction("Activate"): void_symbol.Activate()

    with revit.Transaction("Cut Wall Angle"):
        param_pt1 = wall_curve.Project(pt1).Parameter
        nearest_end = 0 if param_pt1 < (wall_curve.GetEndParameter(0) + wall_curve.GetEndParameter(1))/2 else 1
        
        DB.WallUtils.DisallowWallJoinAtEnd(wall, nearest_end)
        
        void_inst = doc.Create.NewFamilyInstance(cut_line, void_symbol, level, DB.Structure.StructuralType.NonStructural)
        comments_param = void_inst.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if not comments_param or comments_param.IsReadOnly:
            raise Exception("The created Structural Connections instance does not have a writable Comments parameter.")
        comments_param.Set(WALL_CUT_COMMENTS)
        
        # Cut only the selected wall instance.
        DB.InstanceVoidCutUtils.AddInstanceVoidCut(doc, wall, void_inst)

    purge_unused_void_families()
    uidoc.RefreshActiveView()

if __name__ == "__main__":
    cut_wall_angle()
