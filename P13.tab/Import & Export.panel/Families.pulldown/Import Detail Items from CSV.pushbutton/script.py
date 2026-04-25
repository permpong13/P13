# -*- coding: utf-8 -*-
__title__ = "Detail Items\nfrom CSV (2026)"
__author__ = "Tee_เพิ่มพงษ์"
__doc__ = "อ่านพิกัดจากไฟล์ CSV สร้าง Detail Items, โหลด Family อัตโนมัติ, ระบบเช็คซ้ำ, UI สไตล์ macOS (Revit 2026)"

import clr
import csv
import math
import os
import sys
import json
import tempfile

# เพิ่ม Reference ให้ถูกต้องสำหรับใช้งาน Process และ ProcessStartInfo
clr.AddReference('System')
from System.Diagnostics import Process, ProcessStartInfo

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from System.Windows.Forms import *
from System.Drawing import *
from System.Collections.Generic import List

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

# ===== CONFIGURATION =====
SHOW_DETAILED_LOGS = False
PROGRESS_UPDATE_INTERVAL = 10
CONFIG_FILE_PATH = os.path.join(tempfile.gettempdir(), "revit_csv_import_last_path.json")

# ===== UI STYLING HELPERS (macOS Style) =====
def apply_macos_window_style(form):
    """ปรับแต่ง Form ให้ดูคลีนคล้าย macOS"""
    form.BackColor = Color.FromArgb(246, 246, 246) # สีเทาอ่อนแบบ Mac
    form.Font = Font("Segoe UI", 9.5, FontStyle.Regular)
    form.ShowIcon = False # ซ่อนไอคอนมุมซ้ายบนให้ดูคลีน

def apply_macos_primary_button(btn):
    """ปุ่มหลัก (เช่น OK) ใช้สีฟ้า macOS Blue"""
    btn.FlatStyle = FlatStyle.Flat
    btn.FlatAppearance.BorderSize = 0
    btn.BackColor = Color.FromArgb(0, 122, 255) # macOS Blue
    btn.ForeColor = Color.White
    btn.Font = Font("Segoe UI", 9.5, FontStyle.Bold)
    btn.Cursor = Cursors.Hand

def apply_macos_secondary_button(btn):
    """ปุ่มรอง (เช่น Cancel, Browse) ใช้สไตล์มินิมอล"""
    btn.FlatStyle = FlatStyle.Flat
    btn.FlatAppearance.BorderColor = Color.FromArgb(200, 200, 200)
    btn.BackColor = Color.White
    btn.ForeColor = Color.Black
    btn.Font = Font("Segoe UI", 9.5, FontStyle.Regular)
    btn.Cursor = Cursors.Hand

# ===== PERSISTENCE HELPERS =====
def load_last_folder():
    """โหลด path ของ folder ล่าสุดที่เคยใช้งาน"""
    try:
        if os.path.exists(CONFIG_FILE_PATH):
            with open(CONFIG_FILE_PATH, 'r') as f:
                data = json.load(f)
                path = data.get("last_folder", "")
                if os.path.exists(path):
                    return path
    except:
        pass
    return ""

def save_last_folder(file_path):
    """บันทึก folder ของไฟล์ที่เลือกล่าสุด"""
    try:
        folder_path = os.path.dirname(file_path)
        data = {"last_folder": folder_path}
        with open(CONFIG_FILE_PATH, 'w') as f:
            json.dump(data, f)
    except:
        pass

# ===== GEOMETRY HELPERS (2026 Update) =====
def create_plane(normal, origin):
    """สร้าง Plane ให้รองรับทั้ง Revit เก่าและใหม่ (2026 ใช้ Plane.Create)"""
    try:
        return Plane.Create(normal, origin)
    except AttributeError:
        return Plane.CreateByNormalAndOrigin(normal, origin)

def get_project_base_point_coordinates():
    """ดึงค่าพิกัดจาก Project Base Point"""
    try:
        collector = FilteredElementCollector(doc).OfClass(BasePoint)
        for bp in collector:
            if not bp.IsShared:
                east_param = bp.get_Parameter(BuiltInParameter.BASEPOINT_EASTWEST_PARAM)
                north_param = bp.get_Parameter(BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM)
                angle_param = bp.get_Parameter(BuiltInParameter.BASEPOINT_ANGLETON_PARAM)
                
                if east_param and east_param.HasValue and north_param and north_param.HasValue:
                    base_east = east_param.AsDouble() * 0.3048
                    base_north = north_param.AsDouble() * 0.3048
                    angle_degrees = 0.0
                    if angle_param and angle_param.HasValue:
                        angle_degrees = angle_param.AsDouble() * (180.0 / math.pi)
                    return base_east, base_north, angle_degrees
        try:
            project_location = doc.ActiveProjectLocation
            if project_location:
                position = project_location.GetProjectPosition(XYZ.Zero)
                if position:
                    base_east = position.EastWest * 0.3048
                    base_north = position.NorthSouth * 0.3048
                    angle_degrees = position.Angle * (180.0 / math.pi)
                    return base_east, base_north, angle_degrees
        except:
            pass
    except Exception as e:
        print("❌ ไม่สามารถดึงค่าพิกัดจาก Project Base Point: {}".format(e))
    
    return 748053.651, 1449973.325, 263.53

def get_actual_project_base_point_position():
    """ดึงตำแหน่งจริงของ Project Base Point ในแบบจำลอง Revit"""
    try:
        collector = FilteredElementCollector(doc).OfClass(BasePoint)
        for bp in collector:
            if not bp.IsShared:
                position = bp.Position
                return position.X, position.Y
    except Exception as e:
        print("❌ ไม่สามารถดึงตำแหน่ง Project Base Point Offset: {}".format(e))
    return 0.0, 0.0

class BasePointInputForm(Form):
    def __init__(self, default_east, default_north, default_angle):
        self.east_value = default_east
        self.north_value = default_north
        self.angle_value = default_angle
        self.InitializeComponent()
    
    def InitializeComponent(self):
        self.Text = "Verify Base Point (2026)"
        self.Size = Size(450, 350)
        self.StartPosition = FormStartPosition.CenterScreen
        apply_macos_window_style(self)
        
        lbl_title = Label()
        lbl_title.Text = "Base Point from Project"
        lbl_title.Location = Point(20, 20)
        lbl_title.Size = Size(400, 25)
        lbl_title.Font = Font("Segoe UI", 11, FontStyle.Bold)
        self.Controls.Add(lbl_title)
        
        lbl_desc = Label()
        lbl_desc.Text = "Please verify and edit if necessary:"
        lbl_desc.Location = Point(20, 50)
        lbl_desc.Size = Size(400, 20)
        self.Controls.Add(lbl_desc)
        
        lbl_east = Label()
        lbl_east.Text = "East (E):"
        lbl_east.Location = Point(20, 80)
        lbl_east.Size = Size(120, 20)
        self.Controls.Add(lbl_east)
        
        self.txt_east = TextBox()
        self.txt_east.Text = "{:.6f}".format(self.east_value)
        self.txt_east.Location = Point(150, 77)
        self.txt_east.Size = Size(250, 25)
        self.txt_east.BorderStyle = BorderStyle.FixedSingle
        self.Controls.Add(self.txt_east)
        
        lbl_north = Label()
        lbl_north.Text = "North (N):"
        lbl_north.Location = Point(20, 115)
        lbl_north.Size = Size(120, 20)
        self.Controls.Add(lbl_north)
        
        self.txt_north = TextBox()
        self.txt_north.Text = "{:.6f}".format(self.north_value)
        self.txt_north.Location = Point(150, 112)
        self.txt_north.Size = Size(250, 25)
        self.txt_north.BorderStyle = BorderStyle.FixedSingle
        self.Controls.Add(self.txt_north)
        
        lbl_angle = Label()
        lbl_angle.Text = "True North Angle:"
        lbl_angle.Location = Point(20, 150)
        lbl_angle.Size = Size(120, 20)
        self.Controls.Add(lbl_angle)
        
        self.txt_angle = TextBox()
        self.txt_angle.Text = "{:.6f}".format(self.angle_value)
        self.txt_angle.Location = Point(150, 147)
        self.txt_angle.Size = Size(250, 25)
        self.txt_angle.BorderStyle = BorderStyle.FixedSingle
        self.Controls.Add(self.txt_angle)
        
        lbl_info = Label()
        lbl_info.Text = "💡 These values are pulled from the Project Base Point.\nYou can modify them if incorrect."
        lbl_info.Location = Point(20, 185)
        lbl_info.Size = Size(400, 40)
        lbl_info.ForeColor = Color.DimGray # สีเทาเข้มแบบ Mac จะดูแพงกว่าสีน้ำเงินสด
        self.Controls.Add(lbl_info)
        
        self.btn_ok = Button()
        self.btn_ok.Text = "OK"
        self.btn_ok.Location = Point(240, 240)
        self.btn_ok.Size = Size(90, 32)
        apply_macos_primary_button(self.btn_ok)
        self.btn_ok.Click += self.on_ok_click
        self.Controls.Add(self.btn_ok)
        
        self.btn_cancel = Button()
        self.btn_cancel.Text = "Cancel"
        self.btn_cancel.Location = Point(340, 240)
        self.btn_cancel.Size = Size(80, 32)
        apply_macos_secondary_button(self.btn_cancel)
        self.btn_cancel.Click += self.on_cancel_click
        self.Controls.Add(self.btn_cancel)
    
    def on_ok_click(self, sender, event):
        try:
            self.east_value = float(self.txt_east.Text)
            self.north_value = float(self.txt_north.Text)
            self.angle_value = float(self.txt_angle.Text)
            self.DialogResult = DialogResult.OK
            self.Close()
        except:
            MessageBox.Show("Please enter valid numbers.", "Error")
    
    def on_cancel_click(self, sender, event):
        self.DialogResult = DialogResult.Cancel
        self.Close()

class ProgressForm(Form):
    def __init__(self, total_items):
        self.Text = "Processing..."
        self.Size = Size(450, 150)
        self.StartPosition = FormStartPosition.CenterScreen
        self.ControlBox = False
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        apply_macos_window_style(self)
        
        self.lbl_status = Label()
        self.lbl_status.Text = "Preparing data..."
        self.lbl_status.Location = Point(20, 20)
        self.lbl_status.Size = Size(400, 20)
        self.Controls.Add(self.lbl_status)
        
        self.progress_bar = ProgressBar()
        self.progress_bar.Location = Point(20, 50)
        self.progress_bar.Size = Size(400, 25)
        self.progress_bar.Minimum = 0
        self.progress_bar.Maximum = total_items
        self.progress_bar.Value = 0
        self.Controls.Add(self.progress_bar)

    def update_progress(self, current, total, pile_no):
        self.progress_bar.Value = current
        self.lbl_status.Text = "Processing Pile: {} ({}/{})".format(pile_no, current, total)
        Application.DoEvents()

def correct_coordinates_for_base_point_offset(x_feet, y_feet, base_point_x, base_point_y):
    corrected_x = x_feet + base_point_x
    corrected_y = y_feet + base_point_y
    return corrected_x, corrected_y

def transform_coordinates_corrected(survey_e, survey_n, base_e, base_n, angle_radians, base_point_offset_x, base_point_offset_y):
    delta_e = survey_e - base_e
    delta_n = survey_n - base_n
    
    cos_angle = math.cos(angle_radians)
    sin_angle = math.sin(angle_radians)
    
    revit_x = delta_e * cos_angle - delta_n * sin_angle
    revit_y = delta_e * sin_angle + delta_n * cos_angle
    
    revit_x_feet = revit_x * 3.28084
    revit_y_feet = revit_y * 3.28084
    
    corrected_x, corrected_y = correct_coordinates_for_base_point_offset(
        revit_x_feet, revit_y_feet, 
        base_point_offset_x, base_point_offset_y
    )
    
    return corrected_x, corrected_y

class CsvSelectionForm(Form):
    def __init__(self, last_folder):
        self.selected_path = ""
        self.last_folder = last_folder
        self.InitializeComponent()
    
    def InitializeComponent(self):
        self.Text = "Select CSV File for Coordinates"
        self.Size = Size(500, 240)
        self.StartPosition = FormStartPosition.CenterScreen
        apply_macos_window_style(self)
        
        lbl_info = Label()
        lbl_info.Text = "Specify CSV file path or open sample file:"
        lbl_info.Location = Point(20, 20)
        lbl_info.Size = Size(400, 20)
        self.Controls.Add(lbl_info)
        
        self.txt_path = TextBox()
        self.txt_path.Location = Point(20, 50)
        self.txt_path.Size = Size(350, 25)
        self.txt_path.BorderStyle = BorderStyle.FixedSingle
        self.Controls.Add(self.txt_path)
        
        btn_browse = Button()
        btn_browse.Text = "Browse..."
        btn_browse.Location = Point(380, 48)
        btn_browse.Size = Size(80, 28)
        apply_macos_secondary_button(btn_browse)
        btn_browse.Click += self.on_browse_click
        self.Controls.Add(btn_browse)
        
        btn_sample = Button()
        btn_sample.Text = "📄 Open Sample File (DetailItems_Coordinate.csv)"
        btn_sample.Location = Point(20, 95)
        btn_sample.Size = Size(350, 32)
        apply_macos_secondary_button(btn_sample)
        btn_sample.Click += self.on_sample_click
        self.Controls.Add(btn_sample)
        
        btn_ok = Button()
        btn_ok.Text = "OK"
        btn_ok.Location = Point(280, 150)
        btn_ok.Size = Size(90, 32)
        apply_macos_primary_button(btn_ok)
        btn_ok.Click += self.on_ok_click
        self.Controls.Add(btn_ok)
        
        btn_cancel = Button()
        btn_cancel.Text = "Cancel"
        btn_cancel.Location = Point(380, 150)
        btn_cancel.Size = Size(80, 32)
        apply_macos_secondary_button(btn_cancel)
        btn_cancel.Click += self.on_cancel_click
        self.Controls.Add(btn_cancel)

    def on_browse_click(self, sender, event):
        dialog = OpenFileDialog()
        dialog.Title = "Select Pile Coordinate CSV File"
        dialog.Filter = "CSV files (*.csv)|*.csv|All files (*.*)|*.*"
        dialog.Multiselect = False
        
        if self.last_folder and os.path.exists(self.last_folder):
            dialog.InitialDirectory = self.last_folder
            
        if dialog.ShowDialog() == DialogResult.OK:
            self.txt_path.Text = dialog.FileName
            
    def on_sample_click(self, sender, event):
        try:
            try:
                script_dir = os.path.dirname(__file__)
            except NameError:
                script_dir = os.getcwd()
                
            sample_file = os.path.join(script_dir, "DetailItems_Coordinate.csv")
            
            if os.path.exists(sample_file):
                start_info = ProcessStartInfo(sample_file)
                start_info.UseShellExecute = True
                Process.Start(start_info)
            else:
                MessageBox.Show("Sample file not found at:\n" + sample_file, "File Not Found", MessageBoxButtons.OK, MessageBoxIcon.Warning)
        except Exception as e:
            MessageBox.Show("Cannot open sample file:\n" + str(e), "Error")

    def on_ok_click(self, sender, event):
        if os.path.exists(self.txt_path.Text) and self.txt_path.Text.lower().endswith('.csv'):
            self.selected_path = self.txt_path.Text
            self.DialogResult = DialogResult.OK
            self.Close()
        else:
            MessageBox.Show("Please select a valid CSV file.", "Error")
            
    def on_cancel_click(self, sender, event):
        self.DialogResult = DialogResult.Cancel
        self.Close()

def select_csv_file():
    last_folder = load_last_folder()
    form = CsvSelectionForm(last_folder)
    if form.ShowDialog() == DialogResult.OK:
        save_last_folder(form.selected_path)
        return form.selected_path
    else:
        print("❌ ไม่ได้เลือกไฟล์")
        return None

def safe_float(value):
    if value is None: return None
    try:
        return float(str(value).strip())
    except:
        return None

def read_csv_file(csv_path):
    pile_data = []
    try:
        with open(csv_path, 'rb') as f:
            raw_content = f.read()
            
        encodings = ['utf-8-sig', 'utf-8', 'tis-620', 'cp874', 'latin-1']
        decoded_content = None
        
        for encoding in encodings:
            try:
                decoded_content = raw_content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
                
        if decoded_content is None:
            decoded_content = raw_content.decode('latin-1')
        
        try:
            from StringIO import StringIO
        except ImportError:
            from io import StringIO
            
        f_io = StringIO(decoded_content)
        reader = csv.DictReader(f_io)
        
        for row in reader:
            pile_no = None
            e = None
            n = None
            
            for key in row.keys():
                if 'pile' in key.lower() or 'no' in key.lower() or 'number' in key.lower():
                    pile_no = str(row.get(key, "")).strip()
                    break
            
            if not pile_no and row.keys():
                first_key = list(row.keys())[0]
                pile_no = str(row.get(first_key, "")).strip()
                        
            if not pile_no: 
                continue
                
            for key in row.keys():
                key_upper = key.upper()
                if key_upper == 'E' or 'east' in key.lower() or 'x' in key_upper:
                    e = safe_float(row.get(key))
                elif key_upper == 'N' or 'north' in key.lower() or 'y' in key_upper:
                    n = safe_float(row.get(key))
            
            if e is None or n is None:
                keys = list(row.keys())
                if len(keys) >= 3:
                    e = safe_float(row.get(keys[1]))
                    n = safe_float(row.get(keys[2]))
                        
            if e is None or n is None:
                continue
                
            pile_data.append({"PileNo": pile_no, "E": e, "N": n})
                
    except Exception as e:
        print("❌ เกิดข้อผิดพลาดในการอ่านไฟล์ CSV: {}".format(e))
        return []
    
    return pile_data

def ensure_center_mark_family_loaded(doc):
    """ตรวจสอบและโหลด Family 'Center_Mark' อัตโนมัติ หากยังไม่มีใน Project"""
    try:
        family_collector = FilteredElementCollector(doc).OfClass(Family)
        for family in family_collector:
            if family.Name == "Center_Mark":
                return True
        
        try:
            script_dir = os.path.dirname(__file__)
        except NameError:
            script_dir = os.getcwd()
            
        family_path = os.path.join(script_dir, "Center_Mark.rfa")
        
        if os.path.exists(family_path):
            print("🔄 ตรวจพบไฟล์ Center_Mark.rfa กำลังโหลดเข้าสู่โครงการ...")
            t = Transaction(doc, "Load Center_Mark Family")
            t.Start()
            
            ref_family = clr.Reference[Family]()
            loaded = doc.LoadFamily(family_path, ref_family)
            
            t.Commit()
            
            if loaded:
                print("✅ โหลด Family 'Center_Mark' สำเร็จ!")
                return True
            else:
                print("⚠️ ไม่สามารถโหลด Family 'Center_Mark' ได้ (อาจจะเกิดจากเวอร์ชัน)")
                return False
        else:
            print("ℹ️ ไม่พบไฟล์ Center_Mark.rfa ในโฟลเดอร์เดียวกับสคริปต์ ข้ามการโหลดอัตโนมัติ")
            
    except Exception as e:
        print("❌ เกิดข้อผิดพลาดในการโหลด Family: {}".format(e))
        if 't' in locals() and t.HasStarted() and not t.HasEnded():
            t.RollBack()
            
    return False

def get_element_name(elem, default_name="Unknown"):
    """ดึงชื่อ Element อย่างปลอดภัยเพื่อป้องกันข้อผิดพลาดจาก API"""
    try:
        if hasattr(elem, "Name") and elem.Name:
            return str(elem.Name)
        
        param = elem.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if param and param.HasValue:
            return str(param.AsString())
    except:
        pass
    return default_name

def get_all_detail_family_symbols(doc):
    all_symbols_info = []
    
    class SymbolInfo:
        def __init__(self, symbol, family_name, symbol_name, category_name):
            self.symbol = symbol
            self.family_name = family_name
            self.symbol_name = symbol_name
            self.category_name = category_name

    try:
        collector = FilteredElementCollector(doc).OfClass(FamilySymbol)
        for symbol in collector:
            try:
                if symbol.Category is None:
                    continue
                
                category_name = symbol.Category.Name if hasattr(symbol.Category, "Name") else ""
                
                valid_categories = ['detail', 'annotation', 'symbol', 'mark', 'generic']
                if any(keyword in category_name.lower() for keyword in valid_categories):
                    family_name = get_element_name(symbol.Family) if hasattr(symbol, "Family") and symbol.Family else "Unknown"
                    symbol_name = get_element_name(symbol, family_name)
                    
                    symbol_info = SymbolInfo(symbol, family_name, symbol_name, category_name)
                    all_symbols_info.append(symbol_info)
            except Exception:
                continue
        
        family_collector = FilteredElementCollector(doc).OfClass(Family)
        for family in family_collector:
            try:
                if family.FamilyCategory is None:
                    continue
                
                category_name = family.FamilyCategory.Name if hasattr(family.FamilyCategory, "Name") else ""
                
                valid_categories = ['detail', 'annotation', 'symbol', 'mark', 'generic']
                if any(keyword in category_name.lower() for keyword in valid_categories):
                    symbol_ids = family.GetFamilySymbolIds()
                    for symbol_id in symbol_ids:
                        symbol = doc.GetElement(symbol_id)
                        if symbol is not None:
                            symbol_exists = False
                            for existing_symbol in all_symbols_info:
                                if existing_symbol.symbol.Id == symbol.Id:
                                    symbol_exists = True
                                    break
                            
                            if not symbol_exists:
                                family_name = get_element_name(family)
                                symbol_name = get_element_name(symbol, family_name)
                                
                                symbol_info = SymbolInfo(symbol, family_name, symbol_name, category_name)
                                all_symbols_info.append(symbol_info)
            except Exception:
                continue
    except Exception as e:
        print("❌ ข้อผิดพลาดในการค้นหา Families: {}".format(e))
    
    return all_symbols_info

class ComboBoxItemWrapper(object):
    """ใช้ครอบข้อมูลเพื่อให้ ComboBox แสดงเฉพาะข้อความ"""
    def __init__(self, display_text, data_object):
        self.display_text = display_text
        self.data_object = data_object
        
    def ToString(self):
        return self.display_text

class FamilySelectionForm(Form):
    def __init__(self, families_data):
        self.families_data = families_data
        self.selected_family_symbol = None
        self.InitializeComponent()
    
    def InitializeComponent(self):
        self.Text = "Select Family and Type for Detail Items"
        self.Size = Size(500, 420)
        self.StartPosition = FormStartPosition.CenterScreen
        apply_macos_window_style(self)
        
        self.lbl_family = Label()
        self.lbl_family.Text = "Select Family:"
        self.lbl_family.Location = Point(20, 20)
        self.lbl_family.Size = Size(100, 20)
        self.Controls.Add(self.lbl_family)
        
        self.cb_family = ComboBox()
        self.cb_family.Location = Point(120, 18)
        self.cb_family.Size = Size(350, 20)
        self.cb_family.DropDownStyle = ComboBoxStyle.DropDownList
        self.cb_family.SelectedIndexChanged += self.on_family_selected
        self.Controls.Add(self.cb_family)
        
        self.lbl_type = Label()
        self.lbl_type.Text = "Select Type:"
        self.lbl_type.Location = Point(20, 60)
        self.lbl_type.Size = Size(100, 20)
        self.Controls.Add(self.lbl_type)
        
        self.cb_type = ComboBox()
        self.cb_type.Location = Point(120, 58)
        self.cb_type.Size = Size(350, 20)
        self.cb_type.DropDownStyle = ComboBoxStyle.DropDownList
        self.cb_type.SelectedIndexChanged += self.on_type_selected
        self.Controls.Add(self.cb_type)
        
        self.lbl_info = Label()
        self.lbl_info.Text = "Family Info:"
        self.lbl_info.Location = Point(20, 100)
        self.lbl_info.Size = Size(450, 80)
        self.lbl_info.BorderStyle = BorderStyle.None
        self.lbl_info.BackColor = Color.White
        self.lbl_info.Padding = Padding(10)
        self.Controls.Add(self.lbl_info)
        
        self.btn_ok = Button()
        self.btn_ok.Text = "OK"
        self.btn_ok.Location = Point(290, 320)
        self.btn_ok.Size = Size(90, 32)
        apply_macos_primary_button(self.btn_ok)
        self.btn_ok.Click += self.on_ok_click
        self.Controls.Add(self.btn_ok)
        
        self.btn_cancel = Button()
        self.btn_cancel.Text = "Cancel"
        self.btn_cancel.Location = Point(390, 320)
        self.btn_cancel.Size = Size(80, 32)
        apply_macos_secondary_button(self.btn_cancel)
        self.btn_cancel.Click += self.on_cancel_click
        self.Controls.Add(self.btn_cancel)
        
        self.load_families()
    
    def load_families(self):
        family_names = []
        for symbol_info in self.families_data:
            family_name = symbol_info.family_name
            if family_name not in family_names:
                family_names.append(family_name)
        
        family_names.sort()
        
        for name in family_names:
            self.cb_family.Items.Add(name)
        
        if self.cb_family.Items.Count > 0:
            center_mark_index = -1
            for i in range(self.cb_family.Items.Count):
                if self.cb_family.Items[i] == "Center_Mark":
                    center_mark_index = i
                    break
                    
            if center_mark_index >= 0:
                self.cb_family.SelectedIndex = center_mark_index
            else:
                self.cb_family.SelectedIndex = 0
    
    def on_family_selected(self, sender, event):
        if self.cb_family.SelectedIndex < 0:
            return
        
        selected_family = self.cb_family.SelectedItem.ToString()
        self.cb_type.Items.Clear()
        
        for symbol_info in self.families_data:
            if symbol_info.family_name == selected_family:
                display_name = "{} - {}".format(symbol_info.symbol_name, symbol_info.category_name)
                wrapper = ComboBoxItemWrapper(display_name, symbol_info)
                self.cb_type.Items.Add(wrapper)
        
        if self.cb_type.Items.Count > 0:
            self.cb_type.SelectedIndex = 0
            
        self.update_info()
    
    def on_type_selected(self, sender, event):
        self.update_info()
    
    def update_info(self):
        if (self.cb_family.SelectedIndex >= 0 and self.cb_type.SelectedIndex >= 0):
            family_name = self.cb_family.SelectedItem.ToString()
            selected_wrapper = self.cb_type.SelectedItem
            symbol_info = selected_wrapper.data_object
            
            info_text = "Family: {}\nType: {}\nCategory: {}\nSymbol Name: {}".format(
                family_name,
                symbol_info.symbol_name,
                symbol_info.category_name,
                symbol_info.symbol_name
            )
            self.lbl_info.Text = info_text
    
    def on_ok_click(self, sender, event):
        if (self.cb_family.SelectedIndex < 0 or self.cb_type.SelectedIndex < 0):
            MessageBox.Show("Please select Family and Type.", "Error")
            return
        
        selected_wrapper = self.cb_type.SelectedItem
        symbol_info = selected_wrapper.data_object
        self.selected_family_symbol = symbol_info.symbol
        self.DialogResult = DialogResult.OK
        self.Close()
    
    def on_cancel_click(self, sender, event):
        self.DialogResult = DialogResult.Cancel
        self.Close()

def let_user_select_family_symbol():
    all_symbols_info = get_all_detail_family_symbols(doc)
    
    if not all_symbols_info:
        print("❌ ไม่พบ Detail Item Families ในโครงการ")
        return None
    
    form = FamilySelectionForm(all_symbols_info)
    result = form.ShowDialog()
    
    if result == DialogResult.OK and form.selected_family_symbol:
        return form.selected_family_symbol
    else:
        print("❌ ผู้ใช้ยกเลิกการเลือก")
        return None

def set_parameter_value(element, param_name, value):
    try:
        param_names_to_try = [
            param_name,
            param_name.replace(" ", ""),
            param_name.upper(),
            param_name.lower()
        ]
        
        for name in param_names_to_try:
            param = element.LookupParameter(name)
            if param and not param.IsReadOnly:
                if param.StorageType == StorageType.String:
                    param.Set(str(value))
                    return True
                elif param.StorageType == StorageType.Double:
                    try:
                        float_value = float(value)
                        param.Set(float_value)
                        return True
                    except:
                        pass
                elif param.StorageType == StorageType.Integer:
                    try:
                        int_value = int(float(value))
                        param.Set(int_value)
                        return True
                    except:
                        pass
        return False
    except Exception as e:
        return False

def show_task_dialog(title, message):
    try:
        MessageBox.Show(message, title)
    except:
        print("{}: {}".format(title, message))

def create_custom_detail_item(view, location, pile_no, e, n):
    try:
        radius = 0.5
        center = location
        normal = XYZ.BasisZ
        
        plane = create_plane(normal, center)
        
        arcs = []
        for i in range(4):
            start_angle = i * math.pi / 2
            end_angle = (i + 1) * math.pi / 2
            try:
                arc = Arc.Create(center, radius, start_angle, end_angle, XYZ.BasisX, XYZ.BasisY)
            except:
                arc = Arc.Create(plane, radius, start_angle, end_angle)
            arcs.append(arc)
        
        curves = []
        for arc in arcs:
            detail_curve = doc.Create.NewDetailCurve(view, arc)
            if detail_curve:
                curves.append(detail_curve)
                set_parameter_value(detail_curve, "Comments", "Pile: {}".format(pile_no))
        
        return curves[0] if curves else None
        
    except Exception as ex:
        print("Error creating custom item: {}".format(ex))
        try:
            start_point = location
            end_point = XYZ(location.X + 1.0, location.Y, location.Z)
            line = Line.CreateBound(start_point, end_point)
            detail_line = doc.Create.NewDetailCurve(view, line)
            set_parameter_value(detail_line, "Comments", "Pile: {}".format(pile_no))
            return detail_line
        except Exception:
            return None

def get_existing_piles_in_view(active_view):
    """รวบรวมเบอร์เสาเข็มที่มีอยู่แล้วใน View ปัจจุบัน เพื่อป้องกันการสร้างซ้ำ"""
    existing_piles = set()
    
    components = FilteredElementCollector(doc, active_view.Id).OfCategory(BuiltInCategory.OST_DetailComponents).WhereElementIsNotElementType()
    for elem in components:
        mark_param = elem.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if mark_param and mark_param.HasValue:
            existing_piles.add(mark_param.AsString().strip())
        else:
            comments_param = elem.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            if comments_param and comments_param.HasValue:
                existing_piles.add(comments_param.AsString().strip())
                
    lines = FilteredElementCollector(doc, active_view.Id).OfCategory(BuiltInCategory.OST_Lines).WhereElementIsNotElementType()
    for elem in lines:
        comments_param = elem.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if comments_param and comments_param.HasValue:
            val = comments_param.AsString().strip()
            if val.startswith("Pile: "):
                existing_piles.add(val.replace("Pile: ", "").strip())
                
    return existing_piles

def main():
    csv_path = select_csv_file()
    if not csv_path:
        return

    print("🚀 เริ่มสร้าง Detail Items จาก CSV (Revit 2026)")

    print("\n🔍 กำลังดึงค่าพิกัดจาก Project Base Point...")
    BASE_E, BASE_N, ANGLE_DEGREES = get_project_base_point_coordinates()
    
    form = BasePointInputForm(BASE_E, BASE_N, ANGLE_DEGREES)
    result = form.ShowDialog()
    
    if result == DialogResult.OK:
        BASE_E = form.east_value
        BASE_N = form.north_value
        ANGLE_DEGREES = form.angle_value
        ANGLE_RADIANS = math.radians(ANGLE_DEGREES)
        
        print("📍 ใช้ค่า Base Point: E={:.3f} m, N={:.3f} m".format(BASE_E, BASE_N))
        print("📐 มุม True North: {:.2f}°".format(ANGLE_DEGREES))
    else:
        print("❌ ผู้ใช้ยกเลิก")
        return

    BASE_POINT_OFFSET_X, BASE_POINT_OFFSET_Y = get_actual_project_base_point_position()
    print("📍 Base Point Offset: X={:.3f} m, Y={:.3f} m".format(
        BASE_POINT_OFFSET_X * 0.3048, BASE_POINT_OFFSET_Y * 0.3048))

    active_view = doc.ActiveView

    if not isinstance(active_view, ViewPlan):
        show_task_dialog("Error", "❌ Please open a Plan View before running the script.")
        return

    pile_data = read_csv_file(csv_path)

    if not pile_data:
        show_task_dialog("Error", "❌ No data found in CSV or invalid file format.")
        return

    print("📖 อ่านข้อมูล {} ตำแหน่งจาก CSV".format(len(pile_data)))

    # โหลด Family Center_Mark อัตโนมัติ (ถ้ามีไฟล์ .rfa อยู่ในโฟลเดอร์เดียวกัน)
    ensure_center_mark_family_loaded(doc)

    fam_type = let_user_select_family_symbol()

    use_custom_elements = False
    if not fam_type:
        result = MessageBox.Show(
            "No Detail Item Families found in the project.\n\n" +
            "Do you want to create simple elements instead?",
            "Families Not Found",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Question
        )
        
        if result == DialogResult.Yes:
            use_custom_elements = True
        else:
            return

    existing_piles = get_existing_piles_in_view(active_view)

    t = Transaction(doc, "Create Detail Items from CSV")
    t.Start()
    
    created_count = 0
    skipped_count = 0
    failed_count = 0
    failed_items = []
    
    total_piles = len(pile_data)
    
    try:
        if fam_type and not fam_type.IsActive:
            fam_type.Activate()
            doc.Regenerate()

        view_elev = active_view.GenLevel.Elevation if active_view.GenLevel else 0.0

        if pile_data:
            test_pile = pile_data[0]
            test_x, test_y = transform_coordinates_corrected(
                test_pile["E"], test_pile["N"], 
                BASE_E, BASE_N, 
                ANGLE_RADIANS,
                BASE_POINT_OFFSET_X, 
                BASE_POINT_OFFSET_Y
            )
            print("🧪 ทดสอบจุดแรก: X={:.2f}, Y={:.2f} ฟุต".format(test_x, test_y))

        progress_form = ProgressForm(total_piles)
        progress_form.Show()

        for i, pile in enumerate(pile_data):
            pile_no = pile["PileNo"]
            e, n = pile["E"], pile["N"]
            
            progress_form.update_progress(i + 1, total_piles, pile_no)
            
            if pile_no in existing_piles:
                skipped_count += 1
                if (i + 1) % PROGRESS_UPDATE_INTERVAL == 0:
                    print("   ⏭️ ข้ามเสาเข็ม {} (มีอยู่แล้ว)".format(pile_no))
                continue
            
            try:
                x, y = transform_coordinates_corrected(
                    e, n, 
                    BASE_E, BASE_N, 
                    ANGLE_RADIANS,
                    BASE_POINT_OFFSET_X, 
                    BASE_POINT_OFFSET_Y
                )
                
                point = XYZ(x, y, view_elev)
                
                if use_custom_elements:
                    element = create_custom_detail_item(active_view, point, pile_no, e, n)
                else:
                    element = doc.Create.NewFamilyInstance(point, fam_type, active_view)
                    
                    if element:
                        set_parameter_value(element, "Mark", pile_no)
                        set_parameter_value(element, "Comments", pile_no)
                        set_parameter_value(element, "Survey_E", e)
                        set_parameter_value(element, "Survey_N", n)

                if element:
                    created_count += 1
                else:
                    failed_count += 1
                    failed_items.append(pile_no)
                
                if (i + 1) % PROGRESS_UPDATE_INTERVAL == 0:
                    print("   📊 ความคืบหน้า: {}/{}".format(i + 1, len(pile_data)))

            except Exception as ex:
                failed_count += 1
                failed_items.append(pile_no)
                print("❌ ล้มเหลว {}: {}".format(pile_no, str(ex)))

        progress_form.Close()
        t.Commit()
        
        print("\n✅ สร้างเสร็จสิ้น: {} ตำแหน่ง".format(created_count))
        if skipped_count > 0:
            print("⏭️ ข้าม (มีอยู่แล้ว): {} ตำแหน่ง".format(skipped_count))
        print("❌ ล้มเหลว: {} ตำแหน่ง".format(failed_count))
        
        if failed_items:
            print("📋 รายการที่ล้มเหลว: {}".format(", ".join(failed_items[:10])))
            if len(failed_items) > 10:
                print("   ... และอีก {} รายการ".format(len(failed_items) - 10))

    except Exception as ex:
        t.RollBack()
        if 'progress_form' in locals():
            progress_form.Close()
        print("❌ Transaction ล้มเหลว: {}".format(str(ex)))
        show_task_dialog("Error", "❌ An error occurred while creating Detail Items.")

if __name__ == "__main__":
    main()