# -*- coding: utf-8 -*-
__title__ = "Import Excel\n(macOS Style)"
__author__ = "Tee_V14_Stable"
__doc__ = "แก้ไขลำดับการทำงาน UI, แก้ไขชื่อ Type, ปรับหน้าตาแบบ macOS และเพิ่มปุ่มเปิดไฟล์ Excel ตัวอย่าง"

import sys
import os
import math
import clr

# เพิ่ม Reference สำหรับใช้งาน Process เปิดไฟล์
clr.AddReference('System')
from System.Diagnostics import Process, ProcessStartInfo

# Import Revit API
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
clr.AddReference('System.IO')

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI import *
from System.Windows.Forms import *
from System.Drawing import *
from System.IO import FileStream, FileMode, FileAccess

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

# ============================================================
# 0. UI STYLING HELPERS (macOS Style)
# ============================================================
def apply_macos_window_style(form):
    """ปรับแต่ง Form ให้ดูคลีนคล้าย macOS"""
    form.BackColor = Color.FromArgb(246, 246, 246)
    form.ShowIcon = False

def apply_macos_primary_button(btn):
    """ปุ่มหลัก ใช้สีฟ้า macOS Blue"""
    btn.FlatStyle = FlatStyle.Flat
    btn.FlatAppearance.BorderSize = 0
    btn.BackColor = Color.FromArgb(0, 122, 255)
    btn.ForeColor = Color.White
    btn.Font = Font("Segoe UI", 9, FontStyle.Bold)
    btn.Cursor = Cursors.Hand

def apply_macos_secondary_button(btn):
    """ปุ่มรอง ใช้สไตล์มินิมอล"""
    btn.FlatStyle = FlatStyle.Flat
    btn.FlatAppearance.BorderColor = Color.FromArgb(200, 200, 200)
    btn.BackColor = Color.White
    btn.ForeColor = Color.Black
    btn.Font = Font("Segoe UI", 9, FontStyle.Regular)
    btn.Cursor = Cursors.Hand

# ============================================================
# 1. SETUP EXCEL READER
# ============================================================
def setup_excel_reader():
    try:
        clr.AddReference("ExcelDataReader")
        clr.AddReference("ExcelDataReader.DataSet")
    except:
        script_dir = os.path.dirname(__file__)
        dll1 = os.path.join(script_dir, "ExcelDataReader.dll")
        dll2 = os.path.join(script_dir, "ExcelDataReader.DataSet.dll")
        try:
            clr.AddReferenceToFileAndPath(dll1)
            clr.AddReferenceToFileAndPath(dll2)
        except Exception as e:
            MessageBox.Show("Please place 'ExcelDataReader.dll' in the same folder as the script.", "Error")
            return None
    import ExcelDataReader
    return ExcelDataReader

# ============================================================
# 2. HELPER FUNCTIONS
# ============================================================
def get_revit_name(element, is_type=False):
    """อ่านชื่อให้ตรงกับ Revit Properties (แก้ไขเพื่อป้องกันปัญหา Unknown หรือ Object String)"""
    if element is None: return "Unknown"
    
    try:
        # ลำดับที่ 1: ดึงจาก Property .Name โดยตรง (ได้ผลแม่นยำที่สุด)
        if hasattr(element, "Name") and element.Name:
            return str(element.Name)
            
        # ลำดับที่ 2: ดึงจาก Parameter
        param_id = BuiltInParameter.SYMBOL_NAME_PARAM if is_type else BuiltInParameter.ALL_MODEL_FAMILY_NAME
        p = element.get_Parameter(param_id)
        if p and p.HasValue: 
            return str(p.AsString())
            
        # ลำดับที่ 3: เฉพาะกรณี Type ให้ลองหาจาก ALL_MODEL_TYPE_NAME
        if is_type:
             p = element.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
             if p and p.HasValue: 
                 return str(p.AsString())
    except: 
        pass
        
    return str(element)

def clean_excel_value(val):
    if val is None: return None
    try:
        f = float(val)
        if f.is_integer(): return str(int(f))
        else: return str(f)
    except: return str(val).strip()

def safe_float(val):
    try: return float(str(val).replace(",", "").strip())
    except: return None

def set_parameter_value(element, param_name, value):
    if value is None: return False
    str_val = str(value)
    found_params = []
    
    if param_name == "Mark":
        p = element.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if p: found_params.append(p)
        
    if not found_params:
        ps = element.GetParameters(param_name)
        if ps: found_params.extend(ps)
        else:
            p = element.LookupParameter(param_name)
            if p: found_params.append(p)

    success = False
    for p in found_params:
        if not p.IsReadOnly:
            try:
                if p.StorageType == StorageType.String:
                    p.Set(str_val)
                    success = True
                elif p.StorageType == StorageType.Double:
                    p.Set(float(str_val))
                    success = True
                elif p.StorageType == StorageType.Integer:
                    p.Set(int(float(str_val)))
                    success = True
                if success: break
            except: continue
    return success

# ============================================================
# 3. DATA COLLECTOR
# ============================================================
class FamilyData:
    def __init__(self, family_name, category_name):
        self.name = family_name
        self.category = category_name
        self.symbols = {}

def get_grouped_family_data(doc):
    cat_dict = {} 
    fam_cache = {}
    all_fams = FilteredElementCollector(doc).OfClass(Family)
    for fam in all_fams:
        try:
            if not fam.FamilyCategory: continue
            if fam.FamilyCategory.CategoryType != CategoryType.Model: continue
            cat_name = fam.FamilyCategory.Name
            fam_name = get_revit_name(fam, is_type=False)
            if fam_name not in fam_cache:
                fam_obj = FamilyData(fam_name, cat_name)
                fam_cache[fam_name] = fam_obj
                if cat_name not in cat_dict: cat_dict[cat_name] = []
                cat_dict[cat_name].append(fam_obj)
            else: fam_obj = fam_cache[fam_name]
            
            for sym_id in fam.GetFamilySymbolIds():
                sym = doc.GetElement(sym_id)
                if sym:
                    sym_name = get_revit_name(sym, is_type=True)
                    fam_obj.symbols[sym_name] = sym
        except: continue
        
    final_dict = {}
    for cat, fam_list in cat_dict.items():
        valid_fams = [f for f in fam_list if len(f.symbols) > 0]
        if valid_fams: final_dict[cat] = sorted(valid_fams, key=lambda x: x.name)
    return final_dict

def get_all_possible_parameters(doc, family_symbol):
    param_set = set()
    std_params = ["Mark", "Comments", "Pile Number", "No", "Reference", "Description", "Type Mark"]
    for p in std_params: param_set.add(p)
    for p in family_symbol.Parameters: param_set.add(p.Definition.Name)
    
    t = Transaction(doc, "Probe Params")
    t.Start()
    try:
        if not family_symbol.IsActive: family_symbol.Activate()
        inst = doc.Create.NewFamilyInstance(XYZ(0,0,0), family_symbol, StructuralType.NonStructural)
        for p in inst.Parameters:
            if p.StorageType != StorageType.ElementId: param_set.add(p.Definition.Name)
    except: pass
    finally: t.RollBack()
    return sorted(list(param_set))

# ============================================================
# 4. EXCEL READER
# ============================================================
def read_excel_data(excel_path, ExcelDataReader):
    data = []
    try:
        stream = FileStream(excel_path, FileMode.Open, FileAccess.Read)
        reader = ExcelDataReader.ExcelReaderFactory.CreateOpenXmlReader(stream)
        headers = {}
        if reader.Read():
            for i in range(reader.FieldCount):
                if not reader.IsDBNull(i):
                    headers[reader.GetString(i).strip().lower()] = i
        
        idx_no, idx_e, idx_n, idx_cut, idx_type = -1, -1, -1, -1, -1
        for h, i in headers.items():
            if any(x in h for x in ["no", "pile", "element", "mark", "number"]) and not any(bad in h for bad in ["cut", "off", "elev", "level", "top"]): idx_no = i
            if h in ["e", "east", "x", "e(m)", "e (m)"]: idx_e = i
            elif "east" in h or ("e-" in h) or ("coord" in h and "e" in h): 
                if idx_e == -1: idx_e = i
            if h in ["n", "north", "y", "n(m)", "n (m)"]: idx_n = i
            elif "north" in h or ("n-" in h) or ("coord" in h and "n" in h): 
                if idx_n == -1: idx_n = i
            if any(x in h for x in ["cut", "top", "elev", "level"]): idx_cut = i
            if any(x in h for x in ["type", "size", "symbol"]): idx_type = i

        while reader.Read():
            el_no, e_val, n_val, cut_val, t_val = None, None, None, None, None
            if idx_no != -1 and not reader.IsDBNull(idx_no): el_no = clean_excel_value(reader.GetValue(idx_no))
            if idx_e != -1 and not reader.IsDBNull(idx_e): e_val = safe_float(reader.GetValue(idx_e))
            if idx_n != -1 and not reader.IsDBNull(idx_n): n_val = safe_float(reader.GetValue(idx_n))
            if idx_cut != -1 and not reader.IsDBNull(idx_cut): cut_val = safe_float(reader.GetValue(idx_cut))
            if idx_type != -1 and not reader.IsDBNull(idx_type): t_val = str(reader.GetValue(idx_type)).strip()

            if el_no and e_val is not None and n_val is not None:
                data.append({"No": el_no, "E": e_val, "N": n_val, "CutOff": cut_val, "Type": t_val})
        reader.Close(); stream.Close()
    except Exception as e:
        MessageBox.Show("Error reading Excel: " + str(e), "Error"); return []
    return data

# ============================================================
# 5. MAIN FORM UI
# ============================================================
class MainConfigForm(Form):
    def __init__(self, doc_levels, category_dict):
        self.doc_levels = sorted(doc_levels, key=lambda l: l.Elevation)
        self.category_dict = category_dict
        self.current_families = []
        
        self.excel_path = None
        self.selected_level = None
        self.selected_symbol = None
        self.target_param = "Mark"
        self.type_map = {}
        
        self.InitializeComponent()
    
    def InitializeComponent(self):
        self.Text = "Import Excel"
        self.Size = Size(500, 560) # เพิ่มความสูงหน้าต่าง
        self.StartPosition = FormStartPosition.CenterScreen
        self.Font = Font("Segoe UI", 9)
        apply_macos_window_style(self)
        
        # --- UI CREATION ---
        
        self.gb_src = GroupBox()
        self.gb_src.Text = "1. Excel Source"
        self.gb_src.Location = Point(10, 10)
        self.gb_src.Size = Size(460, 100) # เพิ่มความสูงเพื่อใส่ปุ่ม Sample
        self.Controls.Add(self.gb_src)
        
        self.txt_path = TextBox()
        self.txt_path.Location = Point(10, 25)
        self.txt_path.Size = Size(350, 25)
        self.txt_path.ReadOnly = True
        self.txt_path.BorderStyle = BorderStyle.FixedSingle
        self.gb_src.Controls.Add(self.txt_path)
        
        self.btn_browse = Button()
        self.btn_browse.Text = "Browse"
        self.btn_browse.Location = Point(370, 23)
        self.btn_browse.Size = Size(80, 27)
        apply_macos_secondary_button(self.btn_browse)
        self.btn_browse.Click += self.on_browse
        self.gb_src.Controls.Add(self.btn_browse)

        # ปุ่มเปิดไฟล์ตัวอย่าง
        self.btn_sample = Button()
        self.btn_sample.Text = "📄 Open Sample File (Family_Coordinate.xlsx)"
        self.btn_sample.Location = Point(10, 60)
        self.btn_sample.Size = Size(350, 28)
        apply_macos_secondary_button(self.btn_sample)
        self.btn_sample.Click += self.on_sample_click
        self.gb_src.Controls.Add(self.btn_sample)
        
        self.gb_set = GroupBox()
        self.gb_set.Text = "2. Model Settings"
        self.gb_set.Location = Point(10, 120) # เลื่อนลง
        self.gb_set.Size = Size(460, 320)
        self.Controls.Add(self.gb_set)
        
        self.lbl_lvl = Label()
        self.lbl_lvl.Text = "Level (Ref):"
        self.lbl_lvl.Location = Point(20, 30)
        self.gb_set.Controls.Add(self.lbl_lvl)
        
        self.cb_lvl = ComboBox()
        self.cb_lvl.Location = Point(130, 27)
        self.cb_lvl.Size = Size(300, 25)
        self.cb_lvl.DropDownStyle = ComboBoxStyle.DropDownList
        for l in self.doc_levels: self.cb_lvl.Items.Add(l.Name)
        if self.cb_lvl.Items.Count > 0: self.cb_lvl.SelectedIndex = 0
        self.gb_set.Controls.Add(self.cb_lvl)
        
        self.lbl_cat = Label()
        self.lbl_cat.Text = "Category:"
        self.lbl_cat.Location = Point(20, 70)
        self.lbl_cat.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.gb_set.Controls.Add(self.lbl_cat)
        
        self.cb_cat = ComboBox()
        self.cb_cat.Location = Point(130, 67)
        self.cb_cat.Size = Size(300, 25)
        self.cb_cat.DropDownStyle = ComboBoxStyle.DropDownList
        self.cb_cat.SelectedIndexChanged += self.on_cat_changed
        self.gb_set.Controls.Add(self.cb_cat)
        
        self.lbl_fam = Label()
        self.lbl_fam.Text = "Family:"
        self.lbl_fam.Location = Point(20, 110)
        self.gb_set.Controls.Add(self.lbl_fam)
        
        self.cb_fam = ComboBox()
        self.cb_fam.Location = Point(130, 107)
        self.cb_fam.Size = Size(300, 25)
        self.cb_fam.DropDownStyle = ComboBoxStyle.DropDownList
        self.cb_fam.SelectedIndexChanged += self.on_fam_changed
        self.gb_set.Controls.Add(self.cb_fam)
        
        self.lbl_type = Label()
        self.lbl_type.Text = "Default Type:"
        self.lbl_type.Location = Point(20, 150)
        self.gb_set.Controls.Add(self.lbl_type)
        
        self.cb_type = ComboBox()
        self.cb_type.Location = Point(130, 147)
        self.cb_type.Size = Size(300, 25)
        self.cb_type.DropDownStyle = ComboBoxStyle.DropDownList
        self.gb_set.Controls.Add(self.cb_type)
        
        self.lbl_note = Label()
        self.lbl_note.Text = "(Excel Type override)"
        self.lbl_note.Location = Point(130, 175)
        self.lbl_note.Size = Size(300, 20)
        self.lbl_note.ForeColor = SystemColors.GrayText
        self.gb_set.Controls.Add(self.lbl_note)
        
        self.lbl_param = Label()
        self.lbl_param.Text = "Write No. to:"
        self.lbl_param.Location = Point(20, 210)
        self.gb_set.Controls.Add(self.lbl_param)
        
        self.cb_param = ComboBox()
        self.cb_param.Location = Point(130, 207)
        self.cb_param.Size = Size(300, 25)
        self.cb_param.DropDownStyle = ComboBoxStyle.DropDownList
        self.cb_param.Items.Add("Mark")
        self.cb_param.SelectedIndex = 0
        self.cb_param.Click += self.on_param_click
        self.gb_set.Controls.Add(self.cb_param)
        
        self.lbl_info = Label()
        self.lbl_info.Text = "* Click on 'Write No. to' to load all Parameters"
        self.lbl_info.Location = Point(130, 250)
        self.lbl_info.Size = Size(300, 20)
        self.lbl_info.ForeColor = Color.FromArgb(0, 122, 255) # สีฟ้าอ่อน
        self.gb_set.Controls.Add(self.lbl_info)
        
        self.btn_ok = Button()
        self.btn_ok.Text = "RUN IMPORT"
        self.btn_ok.Location = Point(230, 460) # เลื่อนลง
        self.btn_ok.Size = Size(110, 35)
        apply_macos_primary_button(self.btn_ok)
        self.btn_ok.Click += self.on_ok
        self.Controls.Add(self.btn_ok)
        
        self.btn_cancel = Button()
        self.btn_cancel.Text = "Cancel"
        self.btn_cancel.Location = Point(350, 460) # เลื่อนลง
        self.btn_cancel.Size = Size(110, 35)
        apply_macos_secondary_button(self.btn_cancel)
        self.btn_cancel.Click += self.on_cancel
        self.Controls.Add(self.btn_cancel)
        
        # --- LOGIC INITIALIZATION ---
        
        cat_list = sorted(self.category_dict.keys())
        self.cb_cat.Items.AddRange(tuple(cat_list))
        
        found_idx = -1
        for i, cat in enumerate(cat_list):
            if "Foundation" in cat or "ฐานราก" in cat:
                found_idx = i; break
        
        if found_idx != -1:
            self.cb_cat.SelectedIndex = found_idx
        elif self.cb_cat.Items.Count > 0:
            self.cb_cat.SelectedIndex = 0

    def on_browse(self, sender, args):
        d = OpenFileDialog()
        d.Filter = "Excel Files (*.xlsx)|*.xlsx"
        if d.ShowDialog() == DialogResult.OK:
            self.txt_path.Text = d.FileName

    def on_sample_click(self, sender, event):
        """ระบบเปิดไฟล์ Family_Coordinate.xlsx แบบอัตโนมัติ (แก้ไข Error เปิดไฟล์)"""
        try:
            try:
                script_dir = os.path.dirname(__file__)
            except NameError:
                script_dir = os.getcwd()
                
            sample_file = os.path.join(script_dir, "Family_Coordinate.xlsx")
            
            if os.path.exists(sample_file):
                # ใช้ UseShellExecute เพื่อสั่งระบบปฏิบัติการให้เปิดโปรแกรม Excel ขึ้นมาอัตโนมัติ
                start_info = ProcessStartInfo(sample_file)
                start_info.UseShellExecute = True
                Process.Start(start_info)
            else:
                MessageBox.Show("Sample file not found at:\n" + sample_file, "File Not Found", MessageBoxButtons.OK, MessageBoxIcon.Warning)
        except Exception as e:
            MessageBox.Show("Cannot open sample file:\n" + str(e), "Error")

    def on_cat_changed(self, sender, args):
        if not hasattr(self, 'cb_fam') or not hasattr(self, 'cb_type'): return

        self.cb_fam.Items.Clear()
        self.cb_type.Items.Clear()
        self.cb_param.Items.Clear()
        self.cb_param.Items.Add("Mark")
        self.cb_param.SelectedIndex = 0
        
        cat_name = self.cb_cat.SelectedItem
        if cat_name in self.category_dict:
            self.current_families = self.category_dict[cat_name]
            for f in self.current_families:
                self.cb_fam.Items.Add(f.name)
        if self.cb_fam.Items.Count > 0: self.cb_fam.SelectedIndex = 0
            
    def on_fam_changed(self, sender, args):
        if not hasattr(self, 'cb_type'): return
        
        self.cb_type.Items.Clear()
        self.cb_param.Items.Clear()
        self.cb_param.Items.Add("Mark")
        self.cb_param.SelectedIndex = 0
        
        idx = self.cb_fam.SelectedIndex
        if idx < 0: return
        fam_data = self.current_families[idx]
        for t_name in sorted(fam_data.symbols.keys()):
            self.cb_type.Items.Add(t_name)
        if self.cb_type.Items.Count > 0: self.cb_type.SelectedIndex = 0
    
    def on_param_click(self, sender, args):
        if self.cb_param.Items.Count > 1: return 
        if self.cb_fam.SelectedIndex < 0 or self.cb_type.SelectedIndex < 0: return
        try:
            fam_idx = self.cb_fam.SelectedIndex
            fam_data = self.current_families[fam_idx]
            type_name = self.cb_type.SelectedItem
            sym = fam_data.symbols[type_name]
            all_params = get_all_possible_parameters(doc, sym)
            
            current_sel = self.cb_param.Text
            self.cb_param.Items.Clear()
            self.cb_param.Items.AddRange(tuple(all_params))
            
            if current_sel in all_params: self.cb_param.SelectedItem = current_sel
            elif "Mark" in all_params: self.cb_param.SelectedItem = "Mark"
            elif self.cb_param.Items.Count > 0: self.cb_param.SelectedIndex = 0
        except: pass

    def on_ok(self, sender, args):
        if not self.txt_path.Text: MessageBox.Show("Please select an Excel file.", "Warning"); return
        if self.cb_cat.SelectedIndex < 0: MessageBox.Show("Please select Category.", "Warning"); return
        if self.cb_fam.SelectedIndex < 0 or self.cb_type.SelectedIndex < 0: MessageBox.Show("Please select Family and Type.", "Warning"); return
            
        self.excel_path = self.txt_path.Text
        lvl_name = self.cb_lvl.SelectedItem
        for l in self.doc_levels:
            if l.Name == lvl_name: self.selected_level = l; break
        
        fam_idx = self.cb_fam.SelectedIndex
        fam_data = self.current_families[fam_idx]
        type_name = self.cb_type.SelectedItem 
        self.selected_symbol = fam_data.symbols[type_name]
        
        self.type_map = {k.strip().lower(): v for k, v in fam_data.symbols.items()}
        self.target_param = self.cb_param.Text
        
        self.DialogResult = DialogResult.OK
        self.Close()
        
    def on_cancel(self, sender, args):
        self.DialogResult = DialogResult.Cancel
        self.Close()

# ============================================================
# 6. EXECUTION
# ============================================================
def get_project_base_point_data(doc):
    try:
        collector = FilteredElementCollector(doc).OfClass(BasePoint)
        for bp in collector:
            if not bp.IsShared:
                ep = bp.get_Parameter(BuiltInParameter.BASEPOINT_EASTWEST_PARAM).AsDouble()
                np = bp.get_Parameter(BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM).AsDouble()
                ap = bp.get_Parameter(BuiltInParameter.BASEPOINT_ANGLETON_PARAM).AsDouble()
                pos = bp.Position
                return ep * 0.3048, np * 0.3048, ap, pos.X, pos.Y
    except: pass
    return 0.0, 0.0, 0.0, 0.0, 0.0

def transform_coords(survey_e, survey_n, base_e, base_n, angle_rad, bp_x, bp_y):
    delta_e = survey_e - base_e
    delta_n = survey_n - base_n
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    revit_x_m = delta_e * cos_a - delta_n * sin_a
    revit_y_m = delta_e * sin_a + delta_n * cos_a
    return (revit_x_m * 3.28084) + bp_x, (revit_y_m * 3.28084) + bp_y

def main():
    if not isinstance(doc.ActiveView, ViewPlan):
        MessageBox.Show("Please open a Plan View before running the script.", "Error"); return
    
    ExcelDataReader = setup_excel_reader()
    if not ExcelDataReader: return
    
    levels = [l for l in FilteredElementCollector(doc).OfClass(Level).ToElements()]
    category_dict = get_grouped_family_data(doc)
    
    if not category_dict:
        MessageBox.Show("No Loadable Model Family found in the project.", "Error"); return

    form = MainConfigForm(levels, category_dict)
    if form.ShowDialog() != DialogResult.OK: return
    
    excel_path = form.excel_path
    base_level = form.selected_level
    default_sym = form.selected_symbol
    type_map = form.type_map
    target_param = form.target_param

    excel_data = read_excel_data(excel_path, ExcelDataReader)
    if not excel_data: MessageBox.Show("No coordinate data found in Excel file.", "Info"); return
    
    be, bn, ang, bpx, bpy = get_project_base_point_data(doc)
    
    t = Transaction(doc, "Import Piles from Excel")
    t.Start()
    count = 0
    if not default_sym.IsActive: default_sym.Activate()
    
    for item in excel_data:
        try:
            use_sym = default_sym
            if item["Type"]:
                t_key = item["Type"].strip().lower()
                for k, v in type_map.items():
                    if t_key in k: use_sym = v; break
                if not use_sym.IsActive: use_sym.Activate()

            rx, ry = transform_coords(item["E"], item["N"], be, bn, ang, bpx, bpy)
            z_val = base_level.Elevation
            if item["CutOff"] is not None: z_val = item["CutOff"] * 3.28084
            loc = XYZ(rx, ry, z_val)
            st_type = StructuralType.NonStructural
            if use_sym.Category:
                cn = use_sym.Category.Name
                if "Column" in cn: st_type = StructuralType.Column
                elif "Foundation" in cn: st_type = StructuralType.Footing
            try: inst = doc.Create.NewFamilyInstance(loc, use_sym, base_level, st_type)
            except: continue
            
            set_parameter_value(inst, target_param, item["No"])
            if item["Type"]: set_parameter_value(inst, "Comments", "Excel Type: " + str(item["Type"]))
            
            if item["CutOff"] is not None:
                offset_ft = z_val - base_level.Elevation
                param_list = ["Base Offset", "Height Offset From Level", "Offset", "Bottom Offset"]
                done = False
                for p in param_list:
                    if set_parameter_value(inst, p, offset_ft): done = True; break
                if not done:
                    try:
                        bp = inst.get_Parameter(BuiltInParameter.STRUCTURAL_BOTTOM_LEVEL_OFFSET_PARAM)
                        if bp: bp.Set(offset_ft)
                    except: pass
            count += 1
        except Exception: pass
        
    t.Commit()
    MessageBox.Show("Successfully created {} elements.".format(count), "Done")

if __name__ == "__main__":
    main()