# -*- coding: utf-8 -*-
__title__ = "Import Piles\n(3D from CSV)"
__author__ = "Tee_Fixed_V8"
__doc__ = "นำเข้า 3D Model Family (เสาเข็ม/ฐานราก) จาก CSV, ป้องกัน Detail Item 100%"

import clr
import csv
import math
import os
import sys

# เพิ่ม Reference ให้ถูกต้องสำหรับใช้งาน Process และ ProcessStartInfo
clr.AddReference('System')
from System.Diagnostics import Process, ProcessStartInfo

# Import Revit API
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI import *
from System.Windows.Forms import *
from System.Drawing import *

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

# ==========================================
# 0. UI STYLING HELPERS (macOS Style)
# ==========================================
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

# ==========================================
# 1. HELPER FUNCTIONS
# ==========================================

def get_revit_name(element, is_type=False):
    """อ่านชื่อให้ตรงกับ Revit Properties (แก้ไขเพื่อป้องกันปัญหา Unknown หรือ Object String)"""
    if element is None: return "Unknown"
    
    try:
        if hasattr(element, "Name") and element.Name:
            return str(element.Name)
            
        param_id = BuiltInParameter.SYMBOL_NAME_PARAM if is_type else BuiltInParameter.ALL_MODEL_FAMILY_NAME
        p = element.get_Parameter(param_id)
        if p and p.HasValue: 
            return str(p.AsString())
            
        if is_type:
             p = element.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
             if p and p.HasValue: 
                 return str(p.AsString())
    except: 
        pass
        
    return str(element)

def set_parameter_value(element, param_name, value):
    """เขียนค่า Parameter แบบพยายามเขียนให้ได้มากที่สุด"""
    if value is None: return False
    
    params = element.GetParameters(param_name)
    if not params:
        p = element.LookupParameter(param_name)
        if p: params = [p]
    
    for p in params:
        try:
            if p.StorageType == StorageType.String:
                p.Set(str(value))
                return True
            elif p.StorageType == StorageType.Double:
                p.Set(float(value))
                return True
            elif p.StorageType == StorageType.Integer:
                p.Set(int(float(value)))
                return True
        except: continue
    return False

def get_base_point_data(doc):
    be, bn, rot = 0.0, 0.0, 0.0
    try:
        pts = FilteredElementCollector(doc).OfClass(BasePoint).ToElements()
        for bp in pts:
            if not bp.IsShared:
                pe = bp.get_Parameter(BuiltInParameter.BASEPOINT_EASTWEST_PARAM)
                pn = bp.get_Parameter(BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM)
                pa = bp.get_Parameter(BuiltInParameter.BASEPOINT_ANGLETON_PARAM)
                if pe: be = pe.AsDouble() * 0.3048
                if pn: bn = pn.AsDouble() * 0.3048
                if pa: rot = pa.AsDouble()
    except: pass
    return be, bn, rot

def read_csv_data(filepath):
    """แก้ไขระบบอ่าน CSV ให้รองรับภาษาไทย และกันปัญหา Error เรื่อง Encoding"""
    data = []
    try:
        with open(filepath, 'rb') as f:
            raw_content = f.read()
            
        encodings = ['utf-8-sig', 'utf-8', 'tis-620', 'cp874', 'latin-1']
        decoded_content = None
        for enc in encodings:
            try:
                decoded_content = raw_content.decode(enc)
                break
            except: pass
            
        if decoded_content is None:
            decoded_content = raw_content.decode('latin-1')
            
        try:
            from StringIO import StringIO
        except ImportError:
            from io import StringIO
            
        f_io = StringIO(decoded_content)
        reader = csv.DictReader(f_io)
        
        for row in reader:
            el_no = None
            for k,v in row.items():
                if k is None: continue
                if any(x in str(k).lower() for x in ['mark', 'no', 'number', 'pile']):
                    el_no = str(v).strip()
                    break
            if not el_no: continue
            
            e_val, n_val, cutoff, t_val = None, None, None, None
            for k,v in row.items():
                if k is None or v is None: continue
                val = str(v).strip()
                if not val: continue
                kl = str(k).lower()
                try:
                    f_val = float(val.replace(',', ''))
                    if 'east' in kl or kl=='e': e_val = f_val
                    elif 'north' in kl or kl=='n': n_val = f_val
                    elif any(x in kl for x in ['cut', 'elev', 'top']): cutoff = f_val
                except: pass
                if any(x in kl for x in ['type', 'size', 'symbol']): t_val = val
            
            vals = list(row.values())
            if (e_val is None or n_val is None) and len(vals) >= 3:
                try: 
                    e_val = float(str(vals[1]).replace(',', ''))
                    n_val = float(str(vals[2]).replace(',', ''))
                except: pass
            
            if e_val is not None and n_val is not None:
                data.append({"No": el_no, "E": e_val, "N": n_val, "CutOff": cutoff, "Type": t_val})
    except Exception as e:
        MessageBox.Show("Error reading CSV: " + str(e), "Error")
        return []
    return data

# ==========================================
# 2. DATA & PARAMETER COLLECTOR (FIXED)
# ==========================================

class FamilyData:
    def __init__(self, family_name):
        self.name = family_name
        self.symbols = {} 
        self.parameters = [] 

def get_all_possible_parameters(doc, family_symbol):
    """ดึงรายชื่อ Parameter ทั้งหมด รวมถึง Instance Parameter"""
    param_set = set()
    
    common_params = [
        "Mark", "Comments", "Type Mark", "Pile Number", "Pile No", 
        "Element Number", "No", "Reference", "Tag", "Description"
    ]
    for p in common_params: param_set.add(p)
    
    for p in family_symbol.Parameters:
        param_set.add(p.Definition.Name)
        
    t = Transaction(doc, "Probe Params")
    t.Start()
    try:
        if not family_symbol.IsActive: family_symbol.Activate()
        inst = doc.Create.NewFamilyInstance(XYZ(0,0,0), family_symbol, StructuralType.NonStructural)
        
        for p in inst.Parameters:
            if p.StorageType != StorageType.ElementId:
                param_set.add(p.Definition.Name)
    except: pass
    finally: t.RollBack()
    
    return sorted(list(param_set))

def get_all_family_data(doc):
    fam_dict = {} 
    all_fams = FilteredElementCollector(doc).OfClass(Family)
    
    for fam in all_fams:
        try:
            if not fam.FamilyCategory: continue
            
            # บังคับดึงเฉพาะ 3D Model เท่านั้น ป้องกัน Detail Items เข้ามาปะปน
            if fam.FamilyCategory.CategoryType != CategoryType.Model: continue
            
            cat_name = fam.FamilyCategory.Name
            
            if not any(t in cat_name for t in ["Structural", "Column", "Foundation", "Generic", "Framing"]):
                continue
            
            fam_name = get_revit_name(fam, is_type=False)
            if fam_name not in fam_dict:
                fam_dict[fam_name] = FamilyData(fam_name)
            
            for sym_id in fam.GetFamilySymbolIds():
                sym = doc.GetElement(sym_id)
                if sym:
                    sym_name = get_revit_name(sym, is_type=True)
                    fam_dict[fam_name].symbols[sym_name] = sym
                    
        except: continue
        
    valid_fams = [f for f in fam_dict.values() if len(f.symbols) > 0]
    return sorted(valid_fams, key=lambda x: x.name)

# ==========================================
# 3. MAIN FORM
# ==========================================

class MainConfigForm(Form):
    def __init__(self, doc_levels, families_list):
        self.doc_levels = sorted(doc_levels, key=lambda l: l.Elevation)
        self.families_list = families_list
        
        self.csv_path = None
        self.selected_level = None
        self.selected_symbol = None
        self.target_param = "Mark"
        self.type_map = {}
        
        self.InitializeComponent()
    
    def InitializeComponent(self):
        self.Text = "Import 3D Piles from CSV"
        self.Size = Size(500, 460) 
        self.StartPosition = FormStartPosition.CenterScreen
        self.Font = Font("Segoe UI", 9)
        apply_macos_window_style(self)
        
        # 1. CSV
        self.gb_csv = GroupBox()
        self.gb_csv.Text = "1. CSV File"
        self.gb_csv.Location = Point(10, 10)
        self.gb_csv.Size = Size(460, 100) 
        self.Controls.Add(self.gb_csv)
        
        self.txt_csv = TextBox()
        self.txt_csv.Location = Point(10, 25)
        self.txt_csv.Size = Size(350, 25)
        self.txt_csv.ReadOnly = True
        self.txt_csv.BorderStyle = BorderStyle.FixedSingle
        self.gb_csv.Controls.Add(self.txt_csv)
        
        self.btn_browse = Button()
        self.btn_browse.Text = "Browse"
        self.btn_browse.Location = Point(370, 23)
        self.btn_browse.Size = Size(80, 27)
        apply_macos_secondary_button(self.btn_browse)
        self.btn_browse.Click += self.on_browse
        self.gb_csv.Controls.Add(self.btn_browse)

        # ปุ่มเปิดไฟล์ตัวอย่าง
        self.btn_sample = Button()
        self.btn_sample.Text = "📄 Open Sample File (Family_Coordinate.csv)"
        self.btn_sample.Location = Point(10, 60)
        self.btn_sample.Size = Size(350, 28)
        apply_macos_secondary_button(self.btn_sample)
        self.btn_sample.Click += self.on_sample_click
        self.gb_csv.Controls.Add(self.btn_sample)
        
        # 2. Config
        self.gb_set = GroupBox()
        self.gb_set.Text = "2. Configuration"
        self.gb_set.Location = Point(10, 120) 
        self.gb_set.Size = Size(460, 230)
        self.Controls.Add(self.gb_set)
        
        # Level
        self.lbl_lvl = Label()
        self.lbl_lvl.Text = "Level:"
        self.lbl_lvl.Location = Point(20, 30)
        self.lbl_lvl.AutoSize = True
        self.gb_set.Controls.Add(self.lbl_lvl)
        
        self.cb_lvl = ComboBox()
        self.cb_lvl.Location = Point(130, 27)
        self.cb_lvl.Size = Size(300, 25)
        self.cb_lvl.DropDownStyle = ComboBoxStyle.DropDownList
        for l in self.doc_levels: self.cb_lvl.Items.Add(l.Name)
        if self.cb_lvl.Items.Count > 0: self.cb_lvl.SelectedIndex = 0
        self.gb_set.Controls.Add(self.cb_lvl)
        
        # Family
        self.lbl_fam = Label()
        self.lbl_fam.Text = "Family:"
        self.lbl_fam.Location = Point(20, 70)
        self.lbl_fam.AutoSize = True
        self.gb_set.Controls.Add(self.lbl_fam)
        
        self.cb_fam = ComboBox()
        self.cb_fam.Location = Point(130, 67)
        self.cb_fam.Size = Size(300, 25)
        self.cb_fam.DropDownStyle = ComboBoxStyle.DropDownList
        self.cb_fam.SelectedIndexChanged += self.on_fam_changed
        for f in self.families_list: self.cb_fam.Items.Add(f.name)
        self.gb_set.Controls.Add(self.cb_fam)
        
        # Type
        self.lbl_type = Label()
        self.lbl_type.Text = "Default Type:"
        self.lbl_type.Location = Point(20, 110)
        self.lbl_type.AutoSize = True
        self.gb_set.Controls.Add(self.lbl_type)
        
        self.cb_type = ComboBox()
        self.cb_type.Location = Point(130, 107)
        self.cb_type.Size = Size(300, 25)
        self.cb_type.DropDownStyle = ComboBoxStyle.DropDownList
        self.gb_set.Controls.Add(self.cb_type)
        
        self.lbl_note = Label()
        self.lbl_note.Text = "(CSV Type will be used first, if available)"
        self.lbl_note.Location = Point(130, 135)
        self.lbl_note.Size = Size(300, 20)
        self.lbl_note.ForeColor = SystemColors.GrayText
        self.gb_set.Controls.Add(self.lbl_note)
        
        # Parameter
        self.lbl_param = Label()
        self.lbl_param.Text = "Write Name to:"
        self.lbl_param.Location = Point(20, 170)
        self.lbl_param.AutoSize = True
        self.gb_set.Controls.Add(self.lbl_param)
        
        self.cb_param = ComboBox()
        self.cb_param.Location = Point(130, 167)
        self.cb_param.Size = Size(300, 25)
        self.cb_param.DropDownStyle = ComboBoxStyle.DropDownList
        self.cb_param.Click += self.on_param_click 
        self.cb_param.Items.Add("Mark") 
        self.cb_param.SelectedIndex = 0
        self.gb_set.Controls.Add(self.cb_param)
        
        # Buttons
        self.btn_ok = Button()
        self.btn_ok.Text = "RUN"
        self.btn_ok.Location = Point(230, 365) 
        self.btn_ok.Size = Size(110, 35)
        apply_macos_primary_button(self.btn_ok)
        self.btn_ok.Click += self.on_ok
        self.Controls.Add(self.btn_ok)
        
        self.btn_cancel = Button()
        self.btn_cancel.Text = "Close"
        self.btn_cancel.Location = Point(350, 365) 
        self.btn_cancel.Size = Size(110, 35)
        apply_macos_secondary_button(self.btn_cancel)
        self.btn_cancel.Click += self.on_cancel
        self.Controls.Add(self.btn_cancel)
        
        if self.cb_fam.Items.Count > 0: self.cb_fam.SelectedIndex = 0

    def on_browse(self, sender, args):
        d = OpenFileDialog()
        d.Filter = "CSV Files (*.csv)|*.csv"
        if d.ShowDialog() == DialogResult.OK:
            self.txt_csv.Text = d.FileName
            
    def on_sample_click(self, sender, event):
        """ใช้ UseShellExecute เปิดไฟล์ตัวอย่างเพื่อแก้ปัญหาบน Windows 11/Revit 2026"""
        try:
            try:
                script_dir = os.path.dirname(__file__)
            except NameError:
                script_dir = os.getcwd()
                
            sample_file = os.path.join(script_dir, "Family_Coordinate.csv")
            
            if os.path.exists(sample_file):
                start_info = ProcessStartInfo(sample_file)
                start_info.UseShellExecute = True
                Process.Start(start_info)
            else:
                MessageBox.Show("Sample file not found at:\n" + sample_file, "File Not Found", MessageBoxButtons.OK, MessageBoxIcon.Warning)
        except Exception as e:
            MessageBox.Show("Cannot open sample file:\n" + str(e), "Error")
            
    def on_fam_changed(self, sender, args):
        self.cb_type.Items.Clear()
        idx = self.cb_fam.SelectedIndex
        if idx < 0: return
        
        fam_data = self.families_list[idx]
        for t_name in sorted(fam_data.symbols.keys()):
            self.cb_type.Items.Add(t_name)
        if self.cb_type.Items.Count > 0: self.cb_type.SelectedIndex = 0
        
        self.cb_param.Items.Clear()
        self.cb_param.Items.Add("Mark")
        self.cb_param.SelectedIndex = 0
        
    def on_param_click(self, sender, args):
        """โหลด Parameter เมื่อคลิก"""
        if self.cb_param.Items.Count > 1: return 
        
        fam_idx = self.cb_fam.SelectedIndex
        type_idx = self.cb_type.SelectedIndex
        if fam_idx < 0 or type_idx < 0: return
        
        fam_data = self.families_list[fam_idx]
        type_name = self.cb_type.SelectedItem
        sym = fam_data.symbols[type_name]
        
        all_params = get_all_possible_parameters(doc, sym)
        
        self.cb_param.Items.Clear()
        self.cb_param.Items.AddRange(tuple(all_params))
        
        if "Mark" in all_params:
            self.cb_param.SelectedItem = "Mark"
        elif self.cb_param.Items.Count > 0:
            self.cb_param.SelectedIndex = 0
        
    def on_ok(self, sender, args):
        if not self.txt_csv.Text:
            MessageBox.Show("Select CSV file.", "Warning"); return
        if self.cb_lvl.SelectedIndex < 0:
            MessageBox.Show("Select Level.", "Warning"); return
        if self.cb_fam.SelectedIndex < 0 or self.cb_type.SelectedIndex < 0:
            MessageBox.Show("Select Family/Type.", "Warning"); return
            
        self.csv_path = self.txt_csv.Text
        
        lvl_name = self.cb_lvl.SelectedItem
        for l in self.doc_levels:
            if l.Name == lvl_name:
                self.selected_level = l; break
                
        fam_idx = self.cb_fam.SelectedIndex
        fam_data = self.families_list[fam_idx]
        type_name = self.cb_type.SelectedItem
        self.selected_symbol = fam_data.symbols[type_name]
        
        self.type_map = {k.strip().lower(): v for k, v in fam_data.symbols.items()}
        self.target_param = self.cb_param.Text
        
        self.DialogResult = DialogResult.OK
        self.Close()
        
    def on_cancel(self, sender, args):
        self.DialogResult = DialogResult.Cancel
        self.Close()

# ==========================================
# 4. RUNNER
# ==========================================

def main():
    if not isinstance(doc.ActiveView, ViewPlan):
        MessageBox.Show("Please open a Plan View before running the script.", "Error"); return

    levels = [l for l in FilteredElementCollector(doc).OfClass(Level).ToElements()]
    families = get_all_family_data(doc)
    
    if not families:
        MessageBox.Show("No suitable 3D Model families found.", "Error"); return

    form = MainConfigForm(levels, families)
    if form.ShowDialog() != DialogResult.OK: return
    
    csv_path = form.csv_path
    base_level = form.selected_level
    default_sym = form.selected_symbol
    type_map = form.type_map
    target_param = form.target_param
    
    csv_data = read_csv_data(csv_path)
    if not csv_data: return

    be, bn, rad = get_base_point_data(doc)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    
    t = Transaction(doc, "Import 3D Piles from CSV")
    t.Start()
    
    count = 0
    if not default_sym.IsActive: default_sym.Activate()
    
    for item in csv_data:
        try:
            use_sym = default_sym
            if item["Type"]:
                t_key = item["Type"].strip().lower()
                if t_key in type_map:
                    use_sym = type_map[t_key]
                    if not use_sym.IsActive: use_sym.Activate()
            
            de = (item["E"] - be) * 3.28084
            dn = (item["N"] - bn) * 3.28084
            rx = de * cos_a - dn * sin_a
            ry = de * sin_a + dn * cos_a
            
            # การแก้ไขแกน Z ให้วางที่ระดับความสูงของ Level ที่เลือกไว้เสมอ
            z_val = base_level.Elevation
            loc = XYZ(rx, ry, z_val)
            
            st_type = StructuralType.Column
            if use_sym.Category and "Foundation" in use_sym.Category.Name:
                st_type = StructuralType.Footing
            
            inst = doc.Create.NewFamilyInstance(loc, use_sym, base_level, st_type)
            
            set_parameter_value(inst, target_param, item["No"])
            if item["Type"]: 
                set_parameter_value(inst, "Comments", "CSV Type: " + str(item["Type"]))
            
            # เมื่อมีการเซ็ต Cut-off จะทำการลบความสูงของ Level ออก เพื่อให้ได้ค่า Offset แท้จริง
            if item["CutOff"] is not None:
                offset_ft = (item["CutOff"] * 3.28084) - base_level.Elevation
                done_off = False
                for p_name in ["Base Offset", "Height Offset From Level", "Offset", "Bottom Offset"]:
                    if set_parameter_value(inst, p_name, offset_ft): 
                        done_off = True; break
                if not done_off:
                    try:
                        bp = inst.get_Parameter(BuiltInParameter.STRUCTURAL_BOTTOM_LEVEL_OFFSET_PARAM)
                        if bp: bp.Set(offset_ft)
                    except: pass
            
            count += 1
            
        except Exception as e:
            print("Err {}: {}".format(item["No"], e))
            
    t.Commit()
    MessageBox.Show("Successfully created {} 3D elements.".format(count), "Done")

if __name__ == "__main__":
    main()