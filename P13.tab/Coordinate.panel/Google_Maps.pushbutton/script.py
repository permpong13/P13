# -*- coding: utf-8 -*-
# คำอธิบาย: แสดงตำแหน่งของจุดหรือวัตถุที่เลือกในโมเดลบน Google Maps
__doc__ = "Identify a point or element in Revit and open its location on Google Maps."
__title__ = "Google\nMaps"
__author__ = "เพิ่มพงษ์"

import math
import clr
import webbrowser

clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
clr.AddReference("System")

import System.Drawing
import System.Windows.Forms

from pyrevit import forms, DB, script
from Autodesk.Revit.UI.Selection import ObjectType

from System.Windows.Forms import (
    Form, Label, ComboBox, ComboBoxStyle, RadioButton, GroupBox, Button, CheckBox, TextBox,
    FormStartPosition, DialogResult, FormBorderStyle, TableLayoutPanel, Panel,
    DockStyle, AnchorStyles, RowStyle, ColumnStyle, SizeType,
    Padding, BorderStyle, FlatStyle, AutoSizeMode
)
from System.Drawing import Size, Point, Font, Color, FontStyle

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

# ============================================================
# ค่าคงที่สำหรับการออกแบบ iOS Style
# ============================================================
IOS_BLUE = Color.FromArgb(0, 122, 255)
IOS_BG_GRAY = Color.FromArgb(242, 242, 247)
IOS_SEPARATOR = Color.FromArgb(200, 199, 204)
IOS_TEXT_GRAY = Color.FromArgb(142, 142, 147)
FONT_REGULAR = Font("Segoe UI", 10)
FONT_BOLD = Font("Segoe UI", 10, FontStyle.Bold)
FONT_TITLE = Font("Segoe UI", 13, System.Drawing.FontStyle.Bold)
FONT_BUTTON = Font("Segoe UI Semibold", 11)

# ============================================================
# ฐานข้อมูลจังหวัดในไทยและการเลือก UTM Zone
# ============================================================
province_data = {
    "Zone 47N (EPSG:32647)": [
        "กรุงเทพมหานคร", "กระบี่", "กาญจนบุรี", "กำแพงเพชร", "ฉะเชิงเทรา", "ชลบุรี", "ชัยนาท", "ชุมพร", "เชียงราย", "เชียงใหม่", 
        "ตรัง", "ตาก", "นครนายก", "นครปฐม", "นครศรีธรรมราช", "นครสวรรค์", "นนทบุรี", "นราธิวาส", 
        "น่าน", "ปทุมธานี", "ประจวบคีรีขันธ์", "ปราจีนบุรี", "ปัตตานี", "พระนครศรีอยุธยา", "พะเยา", "พังงา", 
        "พัทลุง", "พิจิตร", "พิษณุโลก", "เพชรบุรี", "เพชรบูรณ์", "แพร่", "ภูเก็ต", "แม่ฮ่องสอน", 
        "ยะลา", "ระนอง", "ระยอง", "ราชบุรี", "ลพบุรี", "ลำปาง", "ลำพูน", "สงขลา", "สตูล", "สมุทรปราการ", 
        "สมุทรสงคราม", "สมุทรสาคร", "สระบุรี", "สิงห์บุรี", "สุโขทัย", "สุพรรณบุรี", "สุราษฎร์ธานี", 
        "อ่างทอง", "อุตรดิตถ์", "อุทัยธานี"
    ],
    "Zone 48N (EPSG:32648)": [
        "กาฬสินธุ์", "ขอนแก่น", "จันทบุรี", "ชัยภูมิ", "ตราด", "นครพนม", 
        "นครราชสีมา", "บึงกาฬ", "บุรีรัมย์", "มหาสารคาม", "มุกดาหาร", "ยโสธร", 
        "ร้อยเอ็ด", "เลย", "ศรีสะเกษ", "สกลนคร", "สระแก้ว", "สุรินทร์", "หนองคาย", 
        "หนองบัวลำภู", "อำนาจเจริญ", "อุดรธานี", "อุบลราชธานี"
    ]
}

province_to_zone = {}
for zone_name, list_prov in province_data.items():
    zone_num = 47 if "47" in zone_name else 48
    for p in list_prov:
        province_to_zone[p] = zone_num

provinces = sorted(province_to_zone.keys())

# ============================================================
# ส่วนการคำนวณแปลงพิกัด UTM เป็น WGS84 (Lat/Lon)
# ============================================================
K0 = 0.9996
E = 0.00669438
E2 = E * E
E3 = E2 * E
E_P2 = E / (1.0 - E)

SQRT_E = math.sqrt(1.0 - E)
_E = (1.0 - SQRT_E) / (1.0 + SQRT_E)
_E2 = _E * _E
_E3 = _E2 * _E
_E4 = _E3 * _E
_E5 = _E4 * _E

M1 = (1.0 - E / 4.0 - 3.0 * E2 / 64.0 - 5.0 * E3 / 256.0)
M2 = (3.0 * E / 8.0 + 3.0 * E2 / 32.0 + 45.0 * E3 / 1024.0)
M3 = (15.0 * E2 / 256.0 + 45.0 * E3 / 1024.0)
M4 = (35.0 * E3 / 3072.0)

P2 = (3.0 / 2.0 * _E - 27.0 / 32.0 * _E3 + 269.0 / 512.0 * _E5)
P3 = (21.0 / 16.0 * _E2 - 55.0 / 32.0 * _E4)
P4 = (151.0 / 96.0 * _E3 - 417.0 / 128.0 * _E5)
P5 = (1097.0 / 512.0 * _E4)

R = 6378137.0

def mod_angle(value):
    return (value + math.pi) % (2.0 * math.pi) - math.pi

def zone_number_to_central_longitude(zone_number):
    return (zone_number - 1) * 6 - 180 + 3

def utm_to_latlon(easting, northing, zone_number, northern=True):
    """แปลงค่าพิกัด UTM (E/N เมตร) ไปเป็น Lat/Lon (WGS84) ในแบบ Pure Python"""
    x = easting - 500000.0
    y = northing if northern else northing - 10000000.0

    m = y / K0
    mu = m / (R * M1)

    p_rad = (mu +
             P2 * math.sin(2.0 * mu) +
             P3 * math.sin(4.0 * mu) +
             P4 * math.sin(6.0 * mu) +
             P5 * math.sin(8.0 * mu))

    p_sin = math.sin(p_rad)
    p_sin2 = p_sin * p_sin
    p_cos = math.cos(p_rad)
    p_tan = p_sin / p_cos
    p_tan2 = p_tan * p_tan
    p_tan4 = p_tan2 * p_tan2

    ep_sin = 1.0 - E * p_sin2
    ep_sin_sqrt = math.sqrt(ep_sin)

    n = R / ep_sin_sqrt
    r = (1.0 - E) / ep_sin

    c = E_P2 * p_cos**2
    c2 = c * c

    d = x / (n * K0)
    d2 = d * d
    d3 = d2 * d
    d4 = d3 * d
    d5 = d4 * d
    d6 = d5 * d

    latitude = p_rad - (p_tan / r) * (
                 d2 / 2.0 -
                 d4 / 24.0 * (5.0 + 3.0 * p_tan2 + 10.0 * c - 4.0 * c2 - 9.0 * E_P2) +
                 d6 / 720.0 * (61.0 + 90.0 * p_tan2 + 298.0 * c + 45.0 * p_tan4 - 252.0 * E_P2 - 3.0 * c2))

    longitude = (d -
                 d3 / 6.0 * (1.0 + 2.0 * p_tan2 + c) +
                 d5 / 120.0 * (5.0 - 2.0 * c + 28.0 * p_tan2 - 3.0 * c2 + 8.0 * E_P2 + 24.0 * p_tan4)) / p_cos

    longitude = mod_angle(longitude + math.radians(zone_number_to_central_longitude(zone_number)))

    return math.degrees(latitude), math.degrees(longitude)

# ============================================================
# ส่วนประมวลผลตำแหน่งพิกัดของ Revit
# ============================================================
def get_base_point_info(doc):
    locations = DB.FilteredElementCollector(doc).OfClass(DB.BasePoint).ToElements()
    bp_nsouth = bp_ewest = angle = 0.0
    basepoint_found = False
    for loc in locations:
        try:
            if not loc.IsShared: # Project Base Point
                angle_param = loc.get_Parameter(DB.BuiltInParameter.BASEPOINT_ANGLETON_PARAM)
                if angle_param and angle_param.AsDouble() is not None:
                    angle = angle_param.AsDouble()
                    bp_nsouth_param = loc.get_Parameter(DB.BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM)
                    bp_ewest_param = loc.get_Parameter(DB.BuiltInParameter.BASEPOINT_EASTWEST_PARAM)
                    if bp_nsouth_param and bp_ewest_param:
                        bp_nsouth_val = bp_nsouth_param.AsDouble()
                        bp_ewest_val = bp_ewest_param.AsDouble()
                        rotated_pos = rotate(loc.Position.X, loc.Position.Y, angle)
                        bp_nsouth = bp_nsouth_val - rotated_pos[1]
                        bp_ewest = bp_ewest_val - rotated_pos[0]
                        basepoint_found = True
                        break
        except: pass
    if not basepoint_found: return 0.0, 0.0, 0.0
    return angle, bp_ewest, bp_nsouth

def rotate(x, y, theta):
    return [math.cos(theta) * x + math.sin(theta) * y, -math.sin(theta) * x + math.cos(theta) * y]

def forward_transform(revit_x, revit_y, angle=0.0, bp_ewest=0.0, bp_nsouth=0.0, doc=None):
    """แปลงพิกัด Revit Internal (ฟุต) เป็นพิกัดจริง N/E (เมตร) โดยใช้ API หรือการคำนวณแบบแมนนวล"""
    if doc is not None:
        try:
            pt = DB.XYZ(revit_x, revit_y, 0.0)
            transform = doc.ActiveProjectLocation.GetTotalTransform()
            shared_pt = transform.Inverse.OfPoint(pt)
            return shared_pt.Y * 0.3048, shared_pt.X * 0.3048
        except:
            pass
            
    relative_coords = rotate(revit_x, revit_y, angle)
    relative_east = relative_coords[0]
    relative_north = relative_coords[1]
    
    target_east_ft = relative_east + bp_ewest
    target_north_ft = relative_north + bp_nsouth
    
    return target_north_ft * 0.3048, target_east_ft * 0.3048

def get_element_xy(element):
    if isinstance(element, DB.FamilyInstance) and element.Location:
        if isinstance(element.Location, DB.LocationPoint):
            p = element.Location.Point
            return p.X, p.Y, p.Z
    loc = element.Location
    if isinstance(loc, DB.LocationPoint):
        p = loc.Point
        return p.X, p.Y, p.Z
    elif isinstance(loc, DB.LocationCurve):
        mid = loc.Curve.Evaluate(0.5, True)
        return mid.X, mid.Y, mid.Z
    elif hasattr(element, 'GetTransform'):
        transform = element.GetTransform()
        if transform: return transform.Origin.X, transform.Origin.Y, transform.Origin.Z
    else:
        bbox = element.get_BoundingBox(None)
        if bbox:
            center = (bbox.Min + bbox.Max) * 0.5
            return center.X, center.Y, center.Z
    return None, None, None

def detect_utm_zone(easting, northing):
    # Try Zone 47N
    try:
        lat47, lon47 = utm_to_latlon(easting, northing, 47, northern=True)
        in47 = (5.6 <= lat47 <= 20.5) and (97.3 <= lon47 <= 105.7)
    except:
        in47 = False

    # Try Zone 48N
    try:
        lat48, lon48 = utm_to_latlon(easting, northing, 48, northern=True)
        in48 = (5.6 <= lat48 <= 20.5) and (97.3 <= lon48 <= 105.7)
    except:
        in48 = False

    if in47 and not in48:
        return 47
    elif in48 and not in47:
        return 48
    
    # Fallback to SiteLocation
    try:
        site = doc.SiteLocation
        lat_deg = math.degrees(site.Latitude)
        lon_deg = math.degrees(site.Longitude)
        if 5.0 <= lat_deg <= 21.0 and 97.0 <= lon_deg <= 106.0:
            return int((lon_deg + 180) / 6) + 1
    except:
        pass
        
    return None

# ============================================================
# หน้าต่างอินเตอร์เฟซผู้ใช้แบบ iOS Style (WPF/Form)
# ============================================================
def get_model_bounds(doc):
    """คำนวณขอบเขตของโมเดลทั้งหมดที่มองเห็นใน Active View ในหน่วยฟุต เพื่อระบุขอบเขตครอบคลุมโมเดล"""
    try:
        view = doc.ActiveView
        # 1. ลองใช้ CropBox ก่อน หากเปิดใช้งาน Crop View อยู่ เพื่อขอบเขตที่สอดคล้องกับที่ผู้ใช้เห็น
        if view.CropBoxActive:
            crop_box = view.CropBox
            trans = crop_box.Transform
            c_min = crop_box.Min
            c_max = crop_box.Max
            pts = [
                trans.OfPoint(DB.XYZ(c_min.X, c_min.Y, 0.0)),
                trans.OfPoint(DB.XYZ(c_max.X, c_min.Y, 0.0)),
                trans.OfPoint(DB.XYZ(c_min.X, c_max.Y, 0.0)),
                trans.OfPoint(DB.XYZ(c_max.X, c_max.Y, 0.0))
            ]
            min_x = min(p.X for p in pts)
            max_x = max(p.X for p in pts)
            min_y = min(p.Y for p in pts)
            max_y = max(p.Y for p in pts)
            return min_x, min_y, max_x, max_y
    except:
        pass

    # 2. หากไม่ได้เปิด Crop View ให้หาขอบเขตจากโมเดลองค์ประกอบทั้งหมดใน View (ใช้โมเดลพิกัดภายใน)
    try:
        collector = DB.FilteredElementCollector(doc, doc.ActiveView.Id)
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        has_points = False
        
        ignored_categories = [
            int(DB.BuiltInCategory.OST_ProjectBasePoint),
            int(DB.BuiltInCategory.OST_SharedBasePoint),
            int(DB.BuiltInCategory.OST_Levels),
            int(DB.BuiltInCategory.OST_Grids),
            int(DB.BuiltInCategory.OST_Views),
            int(DB.BuiltInCategory.OST_Cameras),
            int(DB.BuiltInCategory.OST_SectionBox),
            int(DB.BuiltInCategory.OST_VolumeOfInterest) # Scope Boxes
        ]
        
        for elem in collector:
            if elem.Category is None:
                continue
            if elem.Category.Id.IntegerValue in ignored_categories:
                continue
            
            # ดึงเฉพาะประเภทที่เป็นโมเดล หรือพวก CAD/Link
            is_model = elem.Category.CategoryType == DB.CategoryType.Model
            is_link_or_import = isinstance(elem, (DB.RevitLinkInstance, DB.ImportSymbol))
            
            if not (is_model or is_link_or_import):
                continue
                
            # ดึง Bounding Box ในพิกัดโมเดลภายใน (ใช้ None แทน view เพื่อได้พิกัดโมเดลจริงตรงๆ)
            bbox = elem.get_BoundingBox(None)
            if bbox is not None:
                # ข้ามค่าพิกัดที่หลุดไปไกลเกินจริง (พิกัดขยะ)
                if bbox.Min.X > -1000000 and bbox.Max.X < 1000000 and bbox.Min.Y > -1000000 and bbox.Max.Y < 1000000:
                    min_x = min(min_x, bbox.Min.X)
                    min_y = min(min_y, bbox.Min.Y)
                    max_x = max(max_x, bbox.Max.X)
                    max_y = max(max_y, bbox.Max.Y)
                    has_points = True
                    
        if not has_points:
            return None
        return min_x, min_y, max_x, max_y
    except:
        return None

# ============================================================
# หน้าต่างอินเตอร์เฟซผู้ใช้แบบ iOS Style (WPF/Form)
# ============================================================
class GoogleMapsForm(Form):
    def __init__(self, last_mode, last_province, detected_zone, last_import, last_size, last_auto_size, model_auto_size):
        self.selected_mode = None
        self.selected_province = None
        self.utm_zone = None
        self.import_map = False
        self.map_size = 500.0
        self.auto_size = True
        
        self.last_mode = last_mode
        self.last_province = last_province
        self.detected_zone = detected_zone
        self.last_import = last_import
        self.last_size = last_size
        self.last_auto_size = last_auto_size
        self.model_auto_size = model_auto_size
        
        self.InitializeComponent()

    def InitializeComponent(self):
        # --- ตั้งค่าฟอร์ม ---
        self.Text = "Show on Google Maps"
        self.ClientSize = Size(500, 540) # ปรับขนาดความสูงเป็น 540 เพื่อความพอดีหลังจากเอาเมนูความละเอียดออก
        self.StartPosition = FormStartPosition.CenterScreen
        self.BackColor = Color.White
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False
        
        # mainLayout
        self.mainLayout = TableLayoutPanel()
        self.mainLayout.Dock = DockStyle.Fill
        self.mainLayout.ColumnCount = 1
        self.mainLayout.RowCount = 5
        self.mainLayout.Padding = Padding(15)
        
        self.mainLayout.RowStyles.Add(RowStyle(SizeType.Absolute, 50))  # 0: Title
        self.mainLayout.RowStyles.Add(RowStyle(SizeType.Absolute, 170)) # 1: Mode group
        self.mainLayout.RowStyles.Add(RowStyle(SizeType.Absolute, 130)) # 2: Location settings (Province & Zone)
        self.mainLayout.RowStyles.Add(RowStyle(SizeType.Absolute, 120)) # 3: Import settings
        self.mainLayout.RowStyles.Add(RowStyle(SizeType.Absolute, 60))  # 4: Buttons
        
        self.Controls.Add(self.mainLayout)
        
        # 1. Title
        self.lbl_title = Label()
        self.lbl_title.Text = "Show on Google Maps\nตรวจสอบพิกัดบนแผนที่"
        self.lbl_title.Font = FONT_TITLE
        self.lbl_title.ForeColor = IOS_BLUE
        self.lbl_title.TextAlign = System.Drawing.ContentAlignment.MiddleCenter
        self.lbl_title.Dock = DockStyle.Fill
        self.mainLayout.Controls.Add(self.lbl_title, 0, 0)
        
        # 2. Mode Group
        self.mode_group = GroupBox()
        self.mode_group.Text = "Coordinate Reference Point / แหล่งอ้างอิงพิกัด"
        self.mode_group.Font = FONT_BOLD
        self.mode_group.Dock = DockStyle.Fill
        self.mode_group.FlatStyle = FlatStyle.Flat
        
        self.rb_pick = RadioButton()
        self.rb_pick.Text = "Pick point on screen / คลิกเลือกจุดในแบบ"
        self.rb_pick.Location = Point(15, 25)
        self.rb_pick.Width = 440
        self.rb_pick.Font = FONT_REGULAR
        self.rb_pick.Checked = (self.last_mode == "PickPoint")
        
        self.rb_elem = RadioButton()
        self.rb_elem.Text = "Selected element / อ้างอิงจากโมเดลที่เลือก"
        self.rb_elem.Location = Point(15, 55)
        self.rb_elem.Width = 440
        self.rb_elem.Font = FONT_REGULAR
        self.rb_elem.Checked = (self.last_mode == "Element")
        
        self.rb_pbp = RadioButton()
        self.rb_pbp.Text = "Project Base Point (จุดเริ่มต้นของโครงการ)"
        self.rb_pbp.Location = Point(15, 85)
        self.rb_pbp.Width = 440
        self.rb_pbp.Font = FONT_REGULAR
        self.rb_pbp.Checked = (self.last_mode == "ProjectBasePoint")
        
        self.rb_sp = RadioButton()
        self.rb_sp.Text = "Survey Point (จุดอ้างอิงรังวัดจริง)"
        self.rb_sp.Location = Point(15, 115)
        self.rb_sp.Width = 440
        self.rb_sp.Font = FONT_REGULAR
        self.rb_sp.Checked = (self.last_mode == "SurveyPoint")
        
        self.mode_group.Controls.Add(self.rb_pick)
        self.mode_group.Controls.Add(self.rb_elem)
        self.mode_group.Controls.Add(self.rb_pbp)
        self.mode_group.Controls.Add(self.rb_sp)
        self.mainLayout.Controls.Add(self.mode_group, 0, 1)
        
        # 3. Location Settings Panel
        self.loc_panel = Panel()
        self.loc_panel.Dock = DockStyle.Fill
        
        # Province Label & ComboBox
        self.lbl_prov = Label()
        self.lbl_prov.Text = "Select Province / เลือกจังหวัด"
        self.lbl_prov.Font = FONT_BOLD
        self.lbl_prov.Location = Point(0, 5)
        self.lbl_prov.Width = 470
        self.lbl_prov.Height = 20
        self.loc_panel.Controls.Add(self.lbl_prov)
        
        self.cb_province = ComboBox()
        self.cb_province.Location = Point(0, 25)
        self.cb_province.Width = 470
        self.cb_province.Font = FONT_REGULAR
        self.cb_province.DropDownStyle = ComboBoxStyle.DropDownList
        for p in provinces:
            self.cb_province.Items.Add(p)
            
        # กำหนดจังหวัดเริ่มต้นอิงตาม UTM Zone ที่ตรวจพบอัตโนมัติ
        default_prov = self.last_province
        if self.detected_zone == 47:
            if default_prov not in province_to_zone or province_to_zone[default_prov] != 47:
                default_prov = "กรุงเทพมหานคร"
        elif self.detected_zone == 48:
            if default_prov not in province_to_zone or province_to_zone[default_prov] != 48:
                default_prov = "ขอนแก่น"

        if default_prov in province_to_zone:
            self.cb_province.SelectedItem = default_prov
        else:
            self.cb_province.SelectedIndex = 0
            
        self.loc_panel.Controls.Add(self.cb_province)
        
        # UTM Zone Label & ComboBox
        self.lbl_zone = Label()
        self.lbl_zone.Text = "UTM Zone / โซนพิกัด (สามารถเปลี่ยนเพื่อข้ามค่าได้)"
        self.lbl_zone.Font = FONT_BOLD
        self.lbl_zone.Location = Point(0, 60)
        self.lbl_zone.Width = 470
        self.lbl_zone.Height = 20
        self.loc_panel.Controls.Add(self.lbl_zone)
        
        self.cb_zone = ComboBox()
        self.cb_zone.Location = Point(0, 80)
        self.cb_zone.Width = 470
        self.cb_zone.Font = FONT_REGULAR
        self.cb_zone.DropDownStyle = ComboBoxStyle.DropDownList
        self.cb_zone.Items.Add("UTM Zone 47N (EPSG:32647)")
        self.cb_zone.Items.Add("UTM Zone 48N (EPSG:32648)")
        
        # เลือก UTM Zone เริ่มต้นอิงตามการตรวจพบอัตโนมัติ
        if self.detected_zone == 47:
            self.cb_zone.SelectedIndex = 0
        elif self.detected_zone == 48:
            self.cb_zone.SelectedIndex = 1
        else:
            zone = province_to_zone[self.cb_province.SelectedItem]
            self.cb_zone.SelectedIndex = 0 if zone == 47 else 1
            
        self.loc_panel.Controls.Add(self.cb_zone)
        
        # เชื่อมโยง Event Listener หลังกำหนดค่าเริ่มต้นแล้ว
        self.cb_province.SelectedIndexChanged += self.on_province_changed
        
        # ป้ายสถานะแจ้งการตรวจสอบอัตโนมัติ (Auto-Detection Status Label)
        self.lbl_auto_detect = Label()
        self.lbl_auto_detect.Location = Point(0, 107)
        self.lbl_auto_detect.Width = 470
        self.lbl_auto_detect.Height = 20
        self.lbl_auto_detect.Font = Font("Segoe UI", 9, FontStyle.Italic)
        if self.detected_zone is not None:
            self.lbl_auto_detect.Text = "ตรวจพบ UTM Zone {}N อัตโนมัติ / Auto-detected UTM Zone {}N".format(self.detected_zone, self.detected_zone)
            self.lbl_auto_detect.ForeColor = Color.FromArgb(46, 125, 50) # Forest Green
        else:
            self.lbl_auto_detect.Text = "ใช้ค่าเริ่มต้น/ประวัติการเลือก / Using default or history settings"
            self.lbl_auto_detect.ForeColor = IOS_TEXT_GRAY
        self.loc_panel.Controls.Add(self.lbl_auto_detect)
        
        self.mainLayout.Controls.Add(self.loc_panel, 0, 2)
        
        # 4. Import Settings Panel
        self.import_panel = Panel()
        self.import_panel.Dock = DockStyle.Fill
        
        self.cb_import = CheckBox()
        self.cb_import.Text = "Import satellite map / นำเข้าภาพดาวเทียม"
        self.cb_import.Font = FONT_BOLD
        self.cb_import.Location = Point(0, 5)
        self.cb_import.Width = 470
        self.cb_import.Height = 25
        self.cb_import.Checked = self.last_import
        self.cb_import.CheckedChanged += self.on_import_changed
        self.import_panel.Controls.Add(self.cb_import)
        
        self.cb_auto_size = CheckBox()
        self.cb_auto_size.Text = "Auto-detect from model bounds / ครอบคลุมพื้นที่โมเดลทั้งหมด"
        self.cb_auto_size.Font = FONT_REGULAR
        self.cb_auto_size.Location = Point(20, 32)
        self.cb_auto_size.Width = 450
        self.cb_auto_size.Height = 25
        self.cb_auto_size.Checked = self.last_auto_size if self.model_auto_size is not None else False
        self.cb_auto_size.Enabled = (self.model_auto_size is not None)
        self.cb_auto_size.CheckedChanged += self.on_auto_size_changed
        self.import_panel.Controls.Add(self.cb_auto_size)
        
        # เมนูสำหรับเลือกความละเอียดภาพดาวเทียม
        self.lbl_res = Label()
        self.lbl_res.Text = "Image Resolution / ความละเอียดรูปภาพ:"
        self.lbl_res.Font = FONT_REGULAR
        self.lbl_res.Location = Point(20, 60)
        self.lbl_res.Width = 200
        self.lbl_res.Height = 20
        self.import_panel.Controls.Add(self.lbl_res)
        
        self.lbl_size = Label()
        self.lbl_size.Text = "Map coverage size (meters) / ขนาดพื้นที่แผนที่ (เมตร):"
        self.lbl_size.Font = FONT_REGULAR
        self.lbl_size.Location = Point(20, 60)
        self.lbl_size.Width = 450
        self.lbl_size.Height = 20
        self.import_panel.Controls.Add(self.lbl_size)
        
        self.tb_size = TextBox()
        self.tb_size.Location = Point(20, 85)
        self.tb_size.Width = 120
        self.tb_size.Font = FONT_REGULAR
        self.tb_size.Text = str(self.last_size)
        self.tb_size.TextAlign = System.Windows.Forms.HorizontalAlignment.Right
        self.import_panel.Controls.Add(self.tb_size)
        
        self.mainLayout.Controls.Add(self.import_panel, 0, 3)
        self.on_import_changed(None, None) # Run once to set initial state of tb_size
        
        # 5. Action Buttons (Open Map / Cancel)
        self.btn_panel = TableLayoutPanel()
        self.btn_panel.Dock = DockStyle.Fill
        self.btn_panel.ColumnCount = 2
        self.btn_panel.RowCount = 1
        self.btn_panel.ColumnStyles.Add(ColumnStyle(SizeType.Percent, 50))
        self.btn_panel.ColumnStyles.Add(ColumnStyle(SizeType.Percent, 50))
        
        self.btn_ok = Button()
        self.btn_ok.Text = "Show Map / เปิดแผนที่"
        self.btn_ok.Dock = DockStyle.Fill
        self.btn_ok.Font = FONT_BUTTON
        self.btn_ok.BackColor = IOS_BLUE
        self.btn_ok.ForeColor = Color.White
        self.btn_ok.FlatStyle = FlatStyle.Flat
        self.btn_ok.FlatAppearance.BorderSize = 0
        self.btn_ok.Click += self.on_ok_click
        self.btn_panel.Controls.Add(self.btn_ok, 0, 0)
        
        self.btn_cancel = Button()
        self.btn_cancel.Text = "Cancel / ยกเลิก"
        self.btn_cancel.Dock = DockStyle.Fill
        self.btn_cancel.Font = FONT_REGULAR
        self.btn_cancel.BackColor = Color.White
        self.btn_cancel.ForeColor = IOS_BLUE
        self.btn_cancel.FlatStyle = FlatStyle.Flat
        self.btn_cancel.FlatAppearance.BorderSize = 0
        self.btn_cancel.Click += self.on_cancel_click
        self.btn_panel.Controls.Add(self.btn_cancel, 1, 0)
        
        self.mainLayout.Controls.Add(self.btn_panel, 0, 4)
        
        self.AcceptButton = self.btn_ok
        self.CancelButton = self.btn_cancel
        self.Shown += self.on_form_shown

    def on_form_shown(self, sender, args):
        try:
            import System.Runtime.InteropServices
            gdi32 = System.Runtime.InteropServices.DllImport("gdi32.dll")
            self.btn_ok.Region = System.Drawing.Region.FromHrgn(
                gdi32.CreateRoundRectRgn(0, 0, self.btn_ok.Width, self.btn_ok.Height, 8, 8)
            )
            self.btn_cancel.Region = System.Drawing.Region.FromHrgn(
                gdi32.CreateRoundRectRgn(0, 0, self.btn_cancel.Width, self.btn_cancel.Height, 8, 8)
            )
        except: pass

    def on_province_changed(self, sender, args):
        selected_prov = self.cb_province.SelectedItem
        zone = province_to_zone[selected_prov]
        if zone == 47:
            self.cb_zone.SelectedIndex = 0
        else:
            self.cb_zone.SelectedIndex = 1

    def on_import_changed(self, sender, args):
        is_checked = self.cb_import.Checked
        self.cb_auto_size.Enabled = is_checked and (self.model_auto_size is not None)
        self.on_auto_size_changed(None, None)

    def on_auto_size_changed(self, sender, args):
        is_import = self.cb_import.Checked
        is_auto = self.cb_auto_size.Checked and self.cb_auto_size.Enabled
        
        self.lbl_size.Enabled = is_import and not is_auto
        self.tb_size.Enabled = is_import and not is_auto
        
        if is_auto and self.model_auto_size is not None:
            self.tb_size.Text = "{:.1f}".format(self.model_auto_size)

    def on_ok_click(self, sender, args):
        if self.cb_import.Checked:
            try:
                size_val = float(self.tb_size.Text.replace(",", "").strip())
                if size_val <= 0: raise ValueError()
                self.map_size = size_val
            except:
                forms.alert("กรุณากรอกขนาดแผนที่ที่ถูกต้อง (ตัวเลขมากกว่า 0) / Please enter a valid map size.", title="Warning")
                return
        else:
            self.map_size = 500.0
            
        if self.rb_pick.Checked:
            self.selected_mode = "PickPoint"
        elif self.rb_elem.Checked:
            self.selected_mode = "Element"
        elif self.rb_pbp.Checked:
            self.selected_mode = "ProjectBasePoint"
        else:
            self.selected_mode = "SurveyPoint"
            
        self.selected_province = self.cb_province.SelectedItem
        self.utm_zone = 47 if self.cb_zone.SelectedIndex == 0 else 48
        self.import_map = self.cb_import.Checked
        self.auto_size = self.cb_auto_size.Checked if self.cb_auto_size.Enabled else False
        self.DialogResult = DialogResult.OK
        self.Close()

    def on_cancel_click(self, sender, args):
        self.DialogResult = DialogResult.Cancel
        self.Close()

# ============================================================
# เมธอดการทำงานหลักของโปรแกรม
# ============================================================
def main():
    if doc is None:
        forms.alert("No open Revit document found.", exitscript=True)

    # 1. ดึงข้อมูลพิกัดเริ่มต้นเพื่อตรวจสอบ UTM Zone อัตโนมัติ
    angle, bp_ewest, bp_nsouth = get_base_point_info(doc)
    init_x, init_y = 0.0, 0.0
    
    # เช็คว่าผู้ใช้เลือกโมเดลไว้อยู่ก่อนแล้วหรือไม่
    sel_ids = list(uidoc.Selection.GetElementIds())
    if sel_ids:
        elem = doc.GetElement(sel_ids[0])
        x_f, y_f, _ = get_element_xy(elem)
        if x_f is not None:
            init_x, init_y = x_f, y_f
    else:
        # หากไม่ได้เลือก ให้ใช้พิกัดของ Project Base Point เป็นพิกัดอ้างอิงเริ่มต้น
        base_points = DB.FilteredElementCollector(doc).OfClass(DB.BasePoint).ToElements()
        for bp in base_points:
            if not bp.IsShared: # Project Base Point
                init_x = bp.Position.X
                init_y = bp.Position.Y
                break

    # แปลงพิกัดเริ่มต้นเป็น UTM Metric (เมตร)
    init_northing, init_easting = forward_transform(init_x, init_y, angle, bp_ewest, bp_nsouth, doc=doc)
    
    # ตรวจสอบ UTM Zone อัตโนมัติจากพิกัด (เทียบ Zone 47N และ 48N ในพื้นที่ประเทศไทย)
    detected_zone = detect_utm_zone(init_easting, init_northing)

    # 2. คำนวณขอบเขตขนาดของโมเดลทั้งหมดในมุมมองปัจจุบัน
    model_bounds = get_model_bounds(doc)
    model_auto_size = None
    if model_bounds:
        min_x, min_y, max_x, max_y = model_bounds
        w_ft = max_x - min_x
        h_ft = max_y - min_y
        max_dim_ft = max(w_ft, h_ft)
        max_dim_m = max_dim_ft * 0.3048
        # เพิ่มระยะเผื่อขอบข้าง 25% เพื่อความสวยงามในการครอบคลุมโมเดล
        model_auto_size = max_dim_m * 1.25
        # จำกัดขนาดความกว้างให้อยู่ในช่วง 50 - 2000 เมตร
        model_auto_size = max(50.0, min(model_auto_size, 2000.0))
        # ปัดเศษเป็นทศนิยม 1 ตำแหน่ง
        model_auto_size = round(model_auto_size, 1)

    # โหลดประวัติการใช้งาน
    cfg = script.get_config("ShowOnGoogleMaps")
    last_mode = getattr(cfg, "last_mode", "PickPoint")
    last_province = getattr(cfg, "last_province", "ชลบุรี")
    last_import = getattr(cfg, "last_import", False)
    last_size = getattr(cfg, "last_size", 500)
    last_auto_size = getattr(cfg, "last_auto_size", True)

    # แสดงหน้าต่างพร้อมส่งค่า UTM Zone ที่ตรวจพบ และขอบเขตขนาดโมเดล
    form = GoogleMapsForm(last_mode, last_province, detected_zone, last_import, last_size, last_auto_size, model_auto_size)
    result = form.ShowDialog()

    if result != DialogResult.OK:
        return

    mode = form.selected_mode
    province = form.selected_province
    zone = form.utm_zone
    import_map = form.import_map
    map_size = form.map_size
    auto_size = form.auto_size
    
    # บันทึกประวัติการตั้งค่า
    cfg.last_mode = mode
    cfg.last_province = province
    cfg.last_import = import_map
    cfg.last_size = map_size
    cfg.last_auto_size = auto_size
    script.save_config()

    # ดึงค่ามุมเอียงและค่าพิกัดเริ่มต้นจาก Project Base Point
    angle, bp_ewest, bp_nsouth = get_base_point_info(doc)

    x_ft, y_ft = None, None

    if mode == "PickPoint":
        try:
            # ซ่อนหน้าต่างและแจ้งผู้ใช้งานคลิกจุดในโมเดล
            point = uidoc.Selection.PickPoint("คลิกเลือกจุดในโมเดลที่ต้องการแสดงบน Google Maps / Pick a point on screen")
            if point:
                x_ft = point.X
                y_ft = point.Y
        except Exception:
            return  # ผู้ใช้ยกเลิกการเลือก

    elif mode == "Element":
        sel_ids = list(uidoc.Selection.GetElementIds())
        element = None
        if sel_ids:
            element = doc.GetElement(sel_ids[0])
        else:
            try:
                ref = uidoc.Selection.PickObject(ObjectType.Element, "เลือกโมเดลที่ต้องการแสดงพิกัดบน Google Maps / Select an element")
                if ref:
                    element = doc.GetElement(ref.ElementId)
            except Exception:
                pass
        
        if element:
            x_ft, y_ft, _ = get_element_xy(element)
        else:
            forms.alert("ไม่ได้เลือกโมเดล / No element selected.", title="Warning")
            return

    elif mode == "ProjectBasePoint":
        base_points = DB.FilteredElementCollector(doc).OfClass(DB.BasePoint).ToElements()
        for bp in base_points:
            if not bp.IsShared: # Project Base Point
                x_ft = bp.Position.X
                y_ft = bp.Position.Y
                break

    elif mode == "SurveyPoint":
        base_points = DB.FilteredElementCollector(doc).OfClass(DB.BasePoint).ToElements()
        for bp in base_points:
            if bp.IsShared: # Survey Point
                x_ft = bp.Position.X
                y_ft = bp.Position.Y
                break

    if x_ft is None or y_ft is None:
        forms.alert("ไม่สามารถหาตำแหน่งพิกัดได้ / Could not determine coordinates.", title="Error")
        return

    # คำนวณเป็น UTM Northing, Easting ในหน่วยเมตรสำหรับจุดอ้างอิงหลัก
    northing, easting = forward_transform(x_ft, y_ft, angle, bp_ewest, bp_nsouth, doc=doc)
    
    # แปลง UTM เมตร เป็นค่าพิกัดแผนที่ (Latitude, Longitude)
    try:
        lat, lon = utm_to_latlon(easting, northing, zone, northern=True)
    except Exception as ex:
        forms.alert("เกิดข้อผิดพลาดในการคำนวณแปลงพิกัด: {}".format(ex), title="Error")
        return

    # สร้างลิงก์แผนที่ Google Maps
    google_maps_url = "https://www.google.com/maps/search/?api=1&query={:.7f},{:.7f}".format(lat, lon)
    
    # คัดลอกลิงก์ไปยัง Clipboard
    copied_status = ""
    try:
        System.Windows.Forms.Clipboard.SetText(google_maps_url)
        copied_status = "\n📋 คัดลอกลิงก์ Google Maps ลงใน Clipboard เรียบร้อยแล้ว!\n(Google Maps URL copied to clipboard!)"
    except Exception:
        pass

    # นำเข้าแผนที่ดาวเทียมเป็นพื้นหลังใน Revit (ถ้าเลือก)
    image_import_status = ""
    if import_map:
        import tempfile
        import os
        import System.Net
        
        # ตรวจสอบทิศทางการหันมุมของมุมมองปัจจุบัน (Project North หรือ True North)
        is_true_north = False
        if hasattr(doc.ActiveView, "Orientation"):
            try:
                is_true_north = (doc.ActiveView.Orientation == DB.ViewOrientationDirection.TrueNorth)
            except:
                pass
        
        # ตั้งค่ามุมหมุนรูปภาพเป็น 0.0 เสมอเพื่อให้ขนานตรงตามแนวทิศเหนือ (ไม่มีการหมุนภาพใน Revit) ตามที่ผู้ใช้ระบุ
        rot_angle = 0.0
        
        # กำหนดจุดศูนย์กลางของแผนที่ดาวเทียมทั้งหมด
        if auto_size and model_bounds is not None:
            min_x, min_y, max_x, max_y = model_bounds
            main_center_x = (min_x + max_x) / 2.0
            main_center_y = (min_y + max_y) / 2.0
        else:
            main_center_x = x_ft
            main_center_y = y_ft

        # อัตราส่วนภาพของ Yandex (650x450)
        aspect_ratio = 650.0 / 450.0
        total_h_m = map_size
        total_w_m = map_size * aspect_ratio
        
        import time
        unique_id = int(time.time())
        
        # ดึง Transform สำหรับการแปลงพิกัดจาก Revit API โดยตรง
        transform = doc.ActiveProjectLocation.GetTotalTransform()
        main_center_internal = DB.XYZ(main_center_x, main_center_y, 0.0)
        main_center_shared = transform.Inverse.OfPoint(main_center_internal)

        # เตรียมข้อมูลสำหรับดาวน์โหลดภาพเดียว (จุดศูนย์กลางใน Revit internal, จุดศูนย์กลางใน Shared, ความกว้าง, ความสูง, ดัชนี)
        tiles_data = [(
            main_center_internal.X, main_center_internal.Y,
            main_center_shared.X, main_center_shared.Y,
            total_w_m, total_h_m, 0
        )]

        success_count = 0
        temp_dir = tempfile.gettempdir()
        downloaded_files = []
        
        try:
            with DB.Transaction(doc, "Import Satellite Map Background") as t:
                t.Start()
                
                # 1. ปรับมุมมองปัจจุบันให้หันหาทิศ True North โดยอัตโนมัติเพื่อให้แผนที่ไม่ต้องหมุน
                try:
                    orient_param = doc.ActiveView.get_Parameter(DB.BuiltInParameter.VIEW_ORIENTATION)
                    if orient_param and not orient_param.IsReadOnly:
                        orient_param.Set(1) # 1 = True North
                except:
                    pass
                
                for tile_x_ft, tile_y_ft, tile_shared_x, tile_shared_y, tile_w_m, tile_h_m, tile_idx in tiles_data:
                    # คำนวณ Latitude, Longitude สำหรับตำแหน่งของแผ่นภาพนี้
                    try:
                        tile_northing = tile_shared_y * 0.3048
                        tile_easting = tile_shared_x * 0.3048
                        tile_lat, tile_lon = utm_to_latlon(tile_easting, tile_northing, zone, northern=True)
                    except Exception as ex:
                        continue
                    
                    # คำนวณ Span สำหรับภาพนี้
                    lat_degree_meters = 111320.0
                    lon_degree_meters = 111320.0 * math.cos(math.radians(tile_lat))
                    
                    spn_lat = tile_h_m / lat_degree_meters
                    spn_lon = tile_w_m / lon_degree_meters
                    
                    map_url = "https://static-maps.yandex.ru/1.x/?ll={:.7f},{:.7f}&spn={:.7f},{:.7f}&l=sat&size=650,450".format(
                        tile_lon, tile_lat, spn_lon, spn_lat
                    )
                    
                    temp_img_path = os.path.join(temp_dir, "revit_map_{}_{}.jpg".format(unique_id, tile_idx))
                    
                    try:
                        web_client = System.Net.WebClient()
                        web_client.Headers.Add("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
                        web_client.DownloadFile(map_url, temp_img_path)
                        
                        if os.path.exists(temp_img_path) and os.path.getsize(temp_img_path) > 0:
                            downloaded_files.append(temp_img_path)
                            
                            # สร้าง ImageType
                            try:
                                options = DB.ImageTypeOptions(temp_img_path, False, DB.ImageTypeSource.Import)
                                img_type = DB.ImageType.Create(doc, options)
                            except AttributeError:
                                img_type = DB.ImageType.Create(doc, temp_img_path)
                            
                            # วางรูปภาพใน Active 2D View
                            width_ft = tile_w_m / 0.3048
                            height_ft = tile_h_m / 0.3048
                            placement_pt = DB.XYZ(tile_x_ft, tile_y_ft, 0.0)
                            
                            try:
                                placement_opts = DB.ImagePlacementOptions(placement_pt, DB.BoxPlacement.Center)
                                img_instance = DB.ImageInstance.Create(doc, doc.ActiveView, img_type.Id, placement_opts)
                                # กำหนดขนาดที่ถูกต้อง
                                img_instance.Width = width_ft
                                img_instance.Height = height_ft
                            except (AttributeError, TypeError):
                                # Fallback สำหรับ Revit รุ่นเก่าที่วางภาพโดยใช้มุมซ้ายล่าง
                                bottom_left_pt = DB.XYZ(tile_x_ft - width_ft / 2.0, tile_y_ft - height_ft / 2.0, 0.0)
                                img_instance = DB.ImageInstance.Create(doc, doc.ActiveView, img_type.Id, bottom_left_pt)
                                # กำหนดขนาดที่ถูกต้อง
                                img_instance.Width = width_ft
                                img_instance.Height = height_ft
                            
                            # หมุนรูปภาพให้ตรงกับมุมมอง
                            if abs(rot_angle) > 0.0001:
                                axis = DB.Line.CreateBound(placement_pt, placement_pt + DB.XYZ(0, 0, 1))
                                DB.ElementTransformUtils.RotateElement(doc, img_instance.Id, axis, rot_angle)
                            
                            # ส่งรูปภาพดาวเทียมไปไว้ด้านหลังสุด (Send to Back) เพื่อให้เส้นโมเดลและ Grid ลอยทับขึ้นมามองเห็นชัดเจน
                            try:
                                import System.Collections.Generic
                                elem_ids = System.Collections.Generic.List[DB.ElementId]()
                                elem_ids.Add(img_instance.Id)
                                DB.DetailElementOrderUtils.SendToBack(doc, doc.ActiveView, elem_ids)
                            except:
                                pass
                                
                            success_count += 1
                    except:
                        pass
                
                t.Commit()
                
            if success_count > 0:
                image_import_status = "\n📥 นำเข้าภาพแผนที่ดาวเทียม (ขยายครอบคลุมโมเดล {} ม. ปรับหน้าต่างมองทิศ True North และส่งภาพไปข้างหลังสุด) สำเร็จแล้ว!\n(Satellite map imported successfully!)".format(map_size)
            else:
                image_import_status = "\n❌ ดาวน์โหลดภาพล้มเหลว (เกิดข้อผิดพลาดในการดึงข้อมูลภาพ)"
        except Exception as img_ex:
            image_import_status = "\n❌ ไม่สามารถนำเข้าภาพดาวเทียมได้: {}".format(img_ex)
        finally:
            # ลบไฟล์ภาพชั่วคราวบนดิสก์ออกทั้งหมดเพื่อประหยัดพื้นที่ดิสก์และรักษาความสะอาดของระบบ
            for file_path in downloaded_files:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except:
                    pass

    # เปิดเบราว์เซอร์
    try:
        webbrowser.open(google_maps_url)
    except Exception as ex:
        forms.alert("ไม่สามารถเปิดเบราว์เซอร์ได้: {}\n\nคุณสามารถนำลิงก์ด้านล่างนี้ไปเปิดเองได้:\n{}".format(ex, google_maps_url))
        return

    # คำนวณพิกัดหน่วยเมตร
    x_m = x_ft * 0.3048
    y_m = y_ft * 0.3048

    # แสดงรายงานสรุปผล
    msg = (
        "📍 แปลงพิกัดเสร็จสมบูรณ์ (Coordinate Conversion Successful)\n\n"
        "• จังหวัดสำหรับคำนวณ (Province): {}\n"
        "• UTM Zone อ้างอิง: {}N\n\n"
        "🏗️ ตำแหน่งพิกัดใน Revit (Internal Coordinates):\n"
        "• X: {:.3f} m ({:.3f} ft)\n"
        "• Y: {:.3f} m ({:.3f} ft)\n\n"
        "🌐 ค่าพิกัดจริง (UTM Metric):\n"
        "• Easting (E): {:.3f} m\n"
        "• Northing (N): {:.3f} m\n\n"
        "🗺️ ค่าพิกัดแผนที่ (Google Maps):\n"
        "• Latitude (Y): {:.7f}\n"
        "• Longitude (X): {:.7f}\n"
        "{}{}"
    ).format(province, zone, x_m, x_ft, y_m, y_ft, easting, northing, lat, lon, copied_status, image_import_status)

    forms.alert(msg, title="Open Google Maps")

if __name__ == "__main__":
    main()
