# -*- coding: utf-8 -*-
__title__ = "Numbering\nCategory"
__author__ = "เพิ่มพงษ์ ทวีกุล"
__doc__ = "DiRoots 3-Pane UI + Live Pick + Smart Parameter Write + Mark Family Types from Highlighted Preview Rows (Auto-load Preview)"

import clr
import csv
import os
import json
import tempfile
import traceback

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
clr.AddReference('System')

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import ObjectType
from System import Array, String, Int64
from System.Windows.Forms import *
from System.Drawing import *
from System.Collections.Generic import List

# ---------- Helper สำหรับสร้าง ElementId อย่างปลอดภัย ----------
def safe_element_id(value):
    try:
        if isinstance(value, ElementId):
            return value
        if isinstance(value, str) and value.isdigit():
            return ElementId(Int64(long(value)))
        elif isinstance(value, (int, long)):
            return ElementId(Int64(value))
        else:
            return ElementId(Int64(long(value)))
    except:
        return ElementId.InvalidElementId

# ---------- Document access ----------
try:
    doc = None
    uidoc = None
    try:
        from pyrevit import revit
        doc = revit.doc
        uidoc = revit.uidoc
    except:
        pass
    if not doc:
        try:
            doc = __revit__.ActiveUIDocument.Document
            uidoc = __revit__.ActiveUIDocument
        except: pass
    if not doc: raise Exception("Cannot access Revit document")
except Exception as ex:
    MessageBox.Show("Run this inside Revit (pyRevit / RPS).\n" + str(ex), "Error")
    raise

# ---------------- Helpers & Config ----------------
CONFIG_FILE = os.path.join(tempfile.gettempdir(), "pyRevit_Numbering_Config_DiRoots3Pane.json")

def load_user_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f: return json.load(f)
        except: pass
    return {}

def save_user_config(data):
    try:
        with open(CONFIG_FILE, 'w') as f: json.dump(data, f)
    except: pass

def get_element_id_value(element_id):
    try:
        if hasattr(element_id, 'IntegerValue'): return element_id.IntegerValue
        elif hasattr(element_id, 'Value'): return element_id.Value
        elif isinstance(element_id, int): return element_id
        else: return int(element_id)
    except: return 0

def get_element_location(element):
    try:
        loc = element.Location
        if loc:
            if hasattr(loc, "Point"): return loc.Point
            elif hasattr(loc, "Curve"):
                try: return loc.Curve.GetEndPoint(0)
                except: pass
    except: pass
    try:
        bbox = element.get_BoundingBox(None)
        if bbox: return XYZ((bbox.Min.X + bbox.Max.X)/2.0, (bbox.Min.Y + bbox.Max.Y)/2.0, (bbox.Min.Z + bbox.Max.Z)/2.0)
    except: pass
    return XYZ(0,0,0)

def has_pile_in_family(element):
    try:
        if hasattr(element, "Symbol") and element.Symbol:
            fam = element.Symbol.Family
            if fam and hasattr(fam, "Name"): return "PILE" in fam.Name.upper()
    except: pass
    return False

def get_ui_category_name(el):
    if has_pile_in_family(el):
        return "เสาเข็ม"
    if el and el.Category:
        el_cat_id = el.Category.Id.IntegerValue
        for key, bic in BUILTIN_MAP.items():
            if el_cat_id == int(bic):
                return key
    return "Unknown"

def get_basic_parameters():
    params = set()
    try:
        coll = FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements()
        sample = list(coll)[:40]
        for el in sample:
            try:
                for p in el.Parameters:
                    if p and hasattr(p, "Definition") and not p.IsReadOnly:
                        if p.StorageType in (StorageType.String, StorageType.Integer, StorageType.Double):
                            params.add(p.Definition.Name)
            except: continue
    except: pass
    preferred = ["Mark", "Type Mark", "Comments", "Type Comments", "Description"]
    out = [pr for pr in preferred if pr in params]
    for p in sorted(params):
        if p not in out: out.append(p)
    if not out: out = ["Mark", "Type Mark", "Comments", "Description"]
    return out

def read_parameter(element, param_name):
    if not element or not param_name: return ""
    p = element.LookupParameter(param_name)
    if p: return p.AsString() or ""
    try:
        tid = element.GetTypeId()
        if tid and tid != ElementId.InvalidElementId:
            el_type = doc.GetElement(tid)
            p_type = el_type.LookupParameter(param_name)
            if p_type: return p_type.AsString() or ""
    except: pass
    return ""

def write_parameter(element, param_name, value):
    if not element or not param_name: return False
    p = element.LookupParameter(param_name)
    if p and not p.IsReadOnly:
        try:
            p.Set(value)
            return True
        except: pass
    try:
        tid = element.GetTypeId()
        if tid and tid != ElementId.InvalidElementId:
            el_type = doc.GetElement(tid)
            if el_type:
                p_type = el_type.LookupParameter(param_name)
                if p_type and not p_type.IsReadOnly:
                    try:
                        p_type.Set(value)
                        return True
                    except: pass
    except: pass
    return False

# ---------------- สร้าง BUILTIN_MAP แบบ Dynamic ----------------
CATEGORY_CANDIDATES = {
    "Structural Columns": "OST_StructuralColumns",
    "Structural Framing": "OST_StructuralFraming",
    "Structural Foundations": "OST_StructuralFoundation",
    "Walls": "OST_Walls",
    "Floors": "OST_Floors",
    "Doors": "OST_Doors",
    "Windows": "OST_Windows",
    "Generic Models": "OST_GenericModel",
    "Plumbing Fixtures": "OST_PlumbingFixtures",
    "Pipes": "OST_PipeCurves",
    "Mechanical Equipment": "OST_MechanicalEquipment",
    "Electrical Equipment": "OST_ElectricalEquipment",
    "เสาเข็ม": "OST_StructuralFoundation",
    "Roofs": "OST_Roofs",
    "Ceilings": "OST_Ceilings",
    "Railings": "OST_Railings",
    "Stairs": "OST_Stairs",
    "Ramps": "OST_Ramps",
    "Furniture": "OST_Furniture",
    "Casework": "OST_Casework",
    "Specialty Equipment": "OST_SpecialityEquipment",
    "Lighting Fixtures": "OST_LightingFixtures",
    "Electrical Circuits": "OST_ElectricalCircuit",
    "Cable Tray": "OST_CableTray",
    "Conduit": "OST_Conduit",
    "Ducts": "OST_DuctCurves",
    "Air Terminals": "OST_AirTerminals",
    "Sprinklers": "OST_Sprinklers",
    "Parking": "OST_Parking",
    "Site": "OST_Site",
    "Entourage": "OST_Entourage",
    "Planting": "OST_Planting",
}

BUILTIN_MAP = {}
for display_name, enum_name in CATEGORY_CANDIDATES.items():
    try:
        bic = getattr(BuiltInCategory, enum_name)
        BUILTIN_MAP[display_name] = bic
    except AttributeError:
        pass

if not BUILTIN_MAP:
    BUILTIN_MAP = {
        "Structural Columns": BuiltInCategory.OST_StructuralColumns,
        "Structural Framing": BuiltInCategory.OST_StructuralFraming,
        "Walls": BuiltInCategory.OST_Walls,
        "Doors": BuiltInCategory.OST_Doors,
    }

def collect_elements_for_category(display_name, active_view=None):
    elems = []
    try:
        if display_name == "เสาเข็ม":
            bic = BuiltInCategory.OST_StructuralFoundation
            col = FilteredElementCollector(doc, active_view.Id) if active_view else FilteredElementCollector(doc)
            col.OfCategory(bic).WhereElementIsNotElementType()
            elems = [e for e in list(col) if has_pile_in_family(e)]
        else:
            bic = BUILTIN_MAP.get(display_name, None)
            if bic:
                col = FilteredElementCollector(doc, active_view.Id) if active_view else FilteredElementCollector(doc)
                col.OfCategory(bic).WhereElementIsNotElementType()
                elems = list(col)
    except: elems = []
    return elems

def filter_elements_by_view_visibility(elements, active_view):
    if not active_view: return elements
    return [el for el in elements if not el.IsHidden(active_view)]

# ---------------- Toggle Switch Control ----------------
class ToggleSwitch(Control):
    def __init__(self):
        self.Width = 44
        self.Height = 22
        self.Checked = False
        self.Click += self._toggle
        self.Paint += self._on_paint
    def _toggle(self, s, a):
        self.Checked = not self.Checked
        self.Invalidate()
    def _on_paint(self, s, a):
        g = a.Graphics
        g.SmoothingMode = Drawing2D.SmoothingMode.AntiAlias
        if self.Checked: g.FillRectangle(Brushes.DodgerBlue, 0, 0, self.Width, self.Height)
        else: g.FillRectangle(Brushes.LightGray, 0, 0, self.Width, self.Height)
        circle_x = self.Width - 20 if self.Checked else 2
        g.FillEllipse(Brushes.White, circle_x, 2, self.Height - 4, self.Height - 4)

# ---------------- Main UI Form ----------------
class NumberingForm(Form):
    def __init__(self):
        self.Text = "ReOrdering Style - Element Numbering"
        self.Size = Size(1250, 800)
        self.StartPosition = FormStartPosition.CenterScreen
        self.Font = Font("Segoe UI", 9)
        self.BackColor = Color.FromArgb(245, 246, 248) 
        self.config = load_user_config()
        self.preview_elements = []
        self.active_view = doc.ActiveView if doc else None
        self.use_view_filter = self.config.get("UseViewFilter", False)
        self.subcat_selections = {}
        self.elements_cache = {}
        
        self.UI_ACTION = None
        self.live_pick_data = None

        self.FormClosing += self._save_settings_on_close
        self._build_ui()
        self._load_categories()
        self._load_parameters()

    def _create_label(self, text, pt, size, font, parent, bold=False, forecolor=Color.FromArgb(50, 50, 50)):
        lbl = Label()
        lbl.Text = text
        lbl.Location = pt
        lbl.Size = size
        lbl.Font = Font(font.FontFamily, font.Size, FontStyle.Bold if bold else FontStyle.Regular)
        lbl.ForeColor = forecolor
        parent.Controls.Add(lbl)
        return lbl

    def _style_datagrid(self, grid):
        grid.AllowUserToAddRows = False
        grid.RowHeadersVisible = False
        grid.SelectionMode = DataGridViewSelectionMode.FullRowSelect
        grid.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill
        grid.BackgroundColor = Color.White
        grid.BorderStyle = BorderStyle.None 
        grid.EnableHeadersVisualStyles = False
        grid.GridColor = Color.FromArgb(235, 235, 235)
        grid.ColumnHeadersBorderStyle = DataGridViewHeaderBorderStyle.Single
        grid.ColumnHeadersDefaultCellStyle.BackColor = Color.FromArgb(240, 240, 240)
        grid.ColumnHeadersDefaultCellStyle.ForeColor = Color.FromArgb(60, 60, 60)
        grid.ColumnHeadersDefaultCellStyle.Font = Font("Segoe UI", 9, FontStyle.Bold)
        grid.ColumnHeadersHeight = 35
        grid.DefaultCellStyle.SelectionBackColor = Color.FromArgb(41, 128, 185) 
        grid.DefaultCellStyle.SelectionForeColor = Color.White
        grid.AlternatingRowsDefaultCellStyle.BackColor = Color.FromArgb(250, 250, 250)

    def _build_ui(self):
        # LEFT PANE
        pnl_left = Panel(Location=Point(10, 10), Size=Size(380, 700), BackColor=Color.White, BorderStyle=BorderStyle.FixedSingle)
        self._create_label("CATEGORIES (หมวดหมู่หลัก)", Point(15, 10), Size(300, 20), self.Font, pnl_left, True)
        self.grid_cat = DataGridView(Location=Point(0, 35), Size=Size(380, 280))
        self._style_datagrid(self.grid_cat)
        
        c_use = DataGridViewCheckBoxColumn(HeaderText="✓", Name="Use", Width=35)
        c_name = DataGridViewTextBoxColumn(HeaderText="Category", Name="Category", ReadOnly=True, Width=120)
        c_pref = DataGridViewTextBoxColumn(HeaderText="Prefix", Name="Prefix", Width=70)
        c_suf = DataGridViewTextBoxColumn(HeaderText="Suffix", Name="Suffix", Width=70)
        c_cnt = DataGridViewTextBoxColumn(HeaderText="รวม", Name="Count", ReadOnly=True, Width=50)
        self.grid_cat.Columns.AddRange(Array[DataGridViewColumn]([c_use, c_name, c_pref, c_suf, c_cnt]))
        self.grid_cat.SelectionChanged += self._on_category_selected
        pnl_left.Controls.Add(self.grid_cat)

        self._create_label("FAMILY TYPES (หมวดย่อย)", Point(15, 325), Size(300, 20), self.Font, pnl_left, True)

        # ปุ่มเลือก Family Types แบบกลุ่ม
        btn_all = self._create_btn("☑ ทั้งหมด", Point(10, 350), Size(80, 25), self._select_all_subcats, Color.FromArgb(41, 128, 185))
        btn_none = self._create_btn("☐ ยกเลิก", Point(95, 350), Size(80, 25), self._deselect_all_subcats, Color.FromArgb(149, 165, 166))
        # ปุ่มใหม่: ทำเครื่องหมาย Family Type จากแถวที่ไฮไลต์ใน Preview (จะโหลด Preview อัตโนมัติถ้ายังไม่มี)
        btn_mark = self._create_btn("✓ ทำเครื่องหมายจากแถวที่ไฮไลต์", Point(180, 350), Size(195, 25), self._mark_family_types_from_highlighted_rows, Color.FromArgb(142, 68, 173))

        pnl_left.Controls.Add(btn_all)
        pnl_left.Controls.Add(btn_none)
        pnl_left.Controls.Add(btn_mark)

        self.grid_subcat = DataGridView(Location=Point(0, 380), Size=Size(380, 315))
        self._style_datagrid(self.grid_subcat)
        
        s_use = DataGridViewCheckBoxColumn(HeaderText="✓", Name="Use", Width=35)
        s_name = DataGridViewTextBoxColumn(HeaderText="ชื่อ (Family/Type)", Name="Name", ReadOnly=True)
        s_cnt = DataGridViewTextBoxColumn(HeaderText="จำนวน", Name="Count", ReadOnly=True, Width=50)
        self.grid_subcat.Columns.AddRange(Array[DataGridViewColumn]([s_use, s_name, s_cnt]))
        self.grid_subcat.CellValueChanged += self._on_subcat_checked
        self.grid_subcat.CurrentCellDirtyStateChanged += self._commit_subcat_edit
        pnl_left.Controls.Add(self.grid_subcat)
        self.Controls.Add(pnl_left)

        # CENTER PANE
        pnl_center = Panel(Location=Point(400, 10), Size=Size(560, 700), BackColor=Color.White, BorderStyle=BorderStyle.FixedSingle)
        self._create_label("ELEMENTS PREVIEW (รายการที่จะรันเลข)", Point(15, 10), Size(350, 20), self.Font, pnl_center, True)
        self.grid_preview = DataGridView(Location=Point(0, 35), Size=Size(560, 660))
        self._style_datagrid(self.grid_preview)
        self.grid_preview.MultiSelect = True
        
        c_id = DataGridViewTextBoxColumn(HeaderText="ID", Name="Id", Width=70, ReadOnly=True)
        c_name = DataGridViewTextBoxColumn(HeaderText="ชื่อองค์ประกอบ", Name="Name", ReadOnly=True)
        c_val = DataGridViewTextBoxColumn(HeaderText="ค่าหมายเลข", Name="Value")
        c_num = DataGridViewTextBoxColumn(HeaderText="สถานะ", Name="Numbered", Width=90, ReadOnly=True)
        self.grid_preview.Columns.AddRange(Array[DataGridViewColumn]([c_id, c_name, c_val, c_num]))
        pnl_center.Controls.Add(self.grid_preview)
        self.Controls.Add(pnl_center)

        # RIGHT PANE
        pnl_right = Panel(Location=Point(970, 10), Size=Size(250, 700), BackColor=Color.White, BorderStyle=BorderStyle.FixedSingle)
        self._create_label("SCOPE (ขอบเขต):", Point(15, 15), Size(150, 20), self.Font, pnl_right, True)
        self.toggle_switch = ToggleSwitch()
        self.toggle_switch.Location = Point(15, 40)
        self.toggle_switch.Checked = self.use_view_filter
        self.toggle_switch.Click += self._toggle_search_mode
        pnl_right.Controls.Add(self.toggle_switch)
        self.lbl_view_mode = self._create_label("Active View", Point(70, 42), Size(170, 20), self.Font, pnl_right)
        self._update_toggle_labels()

        self._create_label("TARGET PARAMETER:", Point(15, 90), Size(200, 20), self.Font, pnl_right, True)
        self.cmb_param = ComboBox(Location=Point(15, 115), Size=Size(220, 26), DropDownStyle=ComboBoxStyle.DropDownList, Font=self.Font)
        pnl_right.Controls.Add(self.cmb_param)
        self.chk_custom = CheckBox(Text="กำหนดเอง:", Location=Point(15, 150), Size=Size(100, 20), Font=self.Font)
        self.chk_custom.CheckedChanged += self._toggle_custom
        pnl_right.Controls.Add(self.chk_custom)
        self.txt_custom = TextBox(Text="ชื่อ Parameter...", Location=Point(115, 148), Size=Size(120, 24), ForeColor=Color.Gray, Enabled=False, Font=self.Font)
        self.txt_custom.Enter += lambda s,e: self._clear_placeholder()
        pnl_right.Controls.Add(self.txt_custom)

        self._create_label("NUMBERING FORMAT:", Point(15, 185), Size(200, 20), self.Font, pnl_right, True)
        self._create_label("Prefix:", Point(15, 215), Size(50, 20), self.Font, pnl_right)
        self.txt_prefix = TextBox(Text=self.config.get("GlobalPrefix", ""), Location=Point(70, 212), Size=Size(165, 24), Font=self.Font)
        pnl_right.Controls.Add(self.txt_prefix)
        self._create_label("Start:", Point(15, 245), Size(50, 20), self.Font, pnl_right)
        self.txt_start = TextBox(Text=self.config.get("StartNumber", "1"), Location=Point(70, 242), Size=Size(60, 24), Font=self.Font)
        pnl_right.Controls.Add(self.txt_start)
        self._create_label("Step:", Point(135, 245), Size(40, 20), self.Font, pnl_right)
        self.txt_step = TextBox(Text=self.config.get("StepValue", "1"), Location=Point(175, 242), Size=Size(60, 24), Font=self.Font)
        pnl_right.Controls.Add(self.txt_step)
        self._create_label("Suffix:", Point(15, 275), Size(50, 20), self.Font, pnl_right)
        self.txt_suffix = TextBox(Text=self.config.get("GlobalSuffix", ""), Location=Point(70, 272), Size=Size(165, 24), Font=self.Font)
        pnl_right.Controls.Add(self.txt_suffix)
        self._create_label("Digits:", Point(15, 305), Size(50, 20), self.Font, pnl_right)
        self.digit_radios = []
        for i, digits in enumerate(["1", "2", "3", "4"]):
            rb = RadioButton(Text=digits, Location=Point(70 + (i*40), 303), Size=Size(35, 20), Tag=int(digits), Font=self.Font)
            if str(digits) == str(self.config.get("Digits", "2")): rb.Checked = True
            self.digit_radios.append(rb)
            pnl_right.Controls.Add(rb)

        self._create_label("SORTING (จัดเรียงในกลุ่ม):", Point(15, 340), Size(220, 20), self.Font, pnl_right, True)
        opts = ["Left to Right (X)", "Right to Left (-X)", "Bottom to Top (Y)", "Top to Bottom (-Y)", "Z Up", "Z Down"]
        self.dir_radios = []
        y = 365
        for i, txt in enumerate(opts):
            r = RadioButton(Text=txt, Location=Point(15, y), Size=Size(200, 20), Font=self.Font)
            if i == int(self.config.get("Direction", 0)): r.Checked = True
            self.dir_radios.append(r)
            pnl_right.Controls.Add(r)
            y += 28
        self.Controls.Add(pnl_right)

        # BOTTOM PANE
        pnl_bot = Panel(Location=Point(10, 720), Size=Size(1210, 40), BackColor=Color.Transparent)
        self.btn_load = self._create_btn("↻ โหลดข้อมูล (Preview)", Point(0, 0), Size(160, 35), self._load_preview, Color.FromArgb(41, 128, 185))
        self.btn_hl = self._create_btn("👁 ไฮไลต์", Point(170, 0), Size(80, 35), self._highlight_zoom, Color.FromArgb(149, 165, 166))
        self.btn_exp = self._create_btn("⬇ Export", Point(260, 0), Size(80, 35), self._export_csv, Color.FromArgb(22, 160, 133))
        self.btn_imp = self._create_btn("⬆ Import", Point(350, 0), Size(80, 35), self._import_csv, Color.FromArgb(39, 174, 96))
        self.btn_live = self._create_btn("⚡ Live Pick (คลิกใน 3D/แปลน)", Point(440, 0), Size(220, 35), self._live_pick_init, Color.FromArgb(142, 68, 173))
        self.lbl_status = self._create_label("Status: Ready", Point(670, 8), Size(300, 20), self.Font, pnl_bot, False, Color.Teal)
        self.btn_run = self._create_btn("▶ รันหมายเลขตามตาราง (Apply)", Point(980, 0), Size(230, 35), self._run_all, Color.FromArgb(39, 174, 96)) 
        pnl_bot.Controls.Add(self.btn_load)
        pnl_bot.Controls.Add(self.btn_hl)
        pnl_bot.Controls.Add(self.btn_exp)
        pnl_bot.Controls.Add(self.btn_imp)
        pnl_bot.Controls.Add(self.btn_live)
        pnl_bot.Controls.Add(self.lbl_status)
        pnl_bot.Controls.Add(self.btn_run)
        self.Controls.Add(pnl_bot)

    def _create_btn(self, txt, pt, size, event, color):
        b = Button(Text=txt, Location=pt, Size=size, BackColor=color, ForeColor=Color.White, FlatStyle=FlatStyle.Flat, Font=Font("Segoe UI", 9, FontStyle.Bold))
        b.FlatAppearance.BorderSize = 0
        b.Cursor = Cursors.Hand
        b.Click += event
        return b

    def _clear_placeholder(self):
        if self.txt_custom.Text == "ชื่อ Parameter...":
            self.txt_custom.Text = ""
            self.txt_custom.ForeColor = Color.Black

    def _get_param_name(self):
        if self.chk_custom.Checked:
            return self.txt_custom.Text.strip()
        else:
            return self.cmb_param.Text.strip()

    def _toggle_search_mode(self, s, e):
        self.use_view_filter = not self.use_view_filter
        self.toggle_switch.Checked = self.use_view_filter
        self._update_toggle_labels()
        self.elements_cache.clear()
        self._load_categories()

    def _update_toggle_labels(self):
        self.lbl_view_mode.Text = "Active View" if self.use_view_filter else "Entire Project"
        self.lbl_view_mode.ForeColor = Color.DodgerBlue if self.use_view_filter else Color.Gray

    def _toggle_custom(self, s, e):
        self.cmb_param.Enabled = not self.chk_custom.Checked
        self.txt_custom.Enabled = self.chk_custom.Checked

    # ---------------- Data Load ----------------
    def _load_categories(self):
        self.grid_cat.Rows.Clear()
        saved_cats = self.config.get("Categories", {})
        for cat_name, bic in BUILTIN_MAP.items():
            elems = collect_elements_for_category(cat_name, self.active_view if self.use_view_filter else None)
            if len(elems) > 0:
                saved_pref = saved_cats.get(cat_name, {}).get("Prefix", "")
                saved_suf = saved_cats.get(cat_name, {}).get("Suffix", "")
                saved_use = saved_cats.get(cat_name, {}).get("Use", False)
                self.grid_cat.Rows.Add(saved_use, cat_name, saved_pref, saved_suf, str(len(elems)))
                self.elements_cache[cat_name] = elems

    def _load_parameters(self):
        self.cmb_param.Items.Clear()
        params = get_basic_parameters()
        for p in params: self.cmb_param.Items.Add(p)
        if params: self.cmb_param.SelectedIndex = 0

    def _commit_subcat_edit(self, s, e):
        if self.grid_subcat.IsCurrentCellDirty:
            self.grid_subcat.CommitEdit(DataGridViewDataErrorContexts.Commit)

    def _on_subcat_checked(self, s, e):
        if e.ColumnIndex == 0 and e.RowIndex >= 0 and self.grid_cat.CurrentRow:
            cat_name = self.grid_cat.CurrentRow.Cells["Category"].Value
            sub_name = self.grid_subcat.Rows[e.RowIndex].Cells["Name"].Value
            is_checked = self.grid_subcat.Rows[e.RowIndex].Cells["Use"].Value
            if cat_name not in self.subcat_selections: self.subcat_selections[cat_name] = {}
            self.subcat_selections[cat_name][sub_name] = is_checked

    def _on_category_selected(self, s, e):
        self.grid_subcat.Rows.Clear()
        if not self.grid_cat.CurrentRow: return
        cat_name = self.grid_cat.CurrentRow.Cells["Category"].Value
        if cat_name not in self.elements_cache:
            self.elements_cache[cat_name] = collect_elements_for_category(cat_name, self.active_view if self.use_view_filter else None)
        elements = self.elements_cache[cat_name]
        subcats = {}
        for el in elements:
            try:
                sub_name = (el.Symbol.Family.Name if el.Symbol.Family else "") + " - " + el.Name if hasattr(el, "Symbol") and el.Symbol else (el.Name if hasattr(el, "Name") else "Unknown")
            except: sub_name = "Unknown"
            subcats[sub_name] = subcats.get(sub_name, 0) + 1
        for sub_name, count in sorted(subcats.items()):
            is_checked = self.subcat_selections.get(cat_name, {}).get(sub_name, False)
            if cat_name not in self.subcat_selections: self.subcat_selections[cat_name] = {}
            self.subcat_selections[cat_name][sub_name] = is_checked
            self.grid_subcat.Rows.Add(is_checked, sub_name, str(count))

    # ---------------- ปุ่มเลือก Family Types แบบกลุ่ม ----------------
    def _select_all_subcats(self, s, e):
        if not self.grid_cat.CurrentRow: return
        cat_name = self.grid_cat.CurrentRow.Cells["Category"].Value
        self.grid_subcat.CellValueChanged -= self._on_subcat_checked
        for row in self.grid_subcat.Rows:
            row.Cells["Use"].Value = True
            sub_name = row.Cells["Name"].Value
            if cat_name not in self.subcat_selections: self.subcat_selections[cat_name] = {}
            self.subcat_selections[cat_name][sub_name] = True
        self.grid_subcat.CellValueChanged += self._on_subcat_checked
        self.lbl_status.Text = "Status: เลือก Family Types ทั้งหมดในหมวด '{}'".format(cat_name)

    def _deselect_all_subcats(self, s, e):
        if not self.grid_cat.CurrentRow: return
        cat_name = self.grid_cat.CurrentRow.Cells["Category"].Value
        self.grid_subcat.CellValueChanged -= self._on_subcat_checked
        for row in self.grid_subcat.Rows:
            row.Cells["Use"].Value = False
            sub_name = row.Cells["Name"].Value
            if cat_name not in self.subcat_selections: self.subcat_selections[cat_name] = {}
            self.subcat_selections[cat_name][sub_name] = False
        self.grid_subcat.CellValueChanged += self._on_subcat_checked
        self.lbl_status.Text = "Status: ยกเลิกการเลือก Family Types ทั้งหมดในหมวด '{}'".format(cat_name)

    # ---------------- ฟังก์ชันใหม่: ทำเครื่องหมาย Family Type จากแถวที่ไฮไลต์ (โหลด Preview อัตโนมัติถ้ายังไม่มี) ----------------
    def _mark_family_types_from_highlighted_rows(self, s, e):
        # ถ้ายังไม่มีข้อมูลใน Preview ให้โหลด Preview โดยอัตโนมัติ
        if self.grid_preview.Rows.Count == 0:
            self._load_preview(None, None)
            # ถ้าหลังจากโหลดแล้วยังไม่มีข้อมูลอีก แสดงว่าไม่มี element ใดถูกเลือกในหมวดหมู่ปัจจุบัน
            if self.grid_preview.Rows.Count == 0:
                MessageBox.Show("ไม่พบข้อมูลใน Preview กรุณาตรวจสอบการเลือกหมวดหมู่หลักและ Family Type ให้ถูกต้องก่อน", "แจ้งเตือน")
                return
        
        if self.grid_preview.SelectedRows.Count == 0:
            MessageBox.Show("โปรดเลือกแถวที่ต้องการในตาราง Preview ก่อน (ใช้ Ctrl หรือ Shift เพื่อเลือกหลายแถว)", "ไม่มีรายการที่เลือก")
            return
        if not self.grid_cat.CurrentRow:
            MessageBox.Show("กรุณาเลือกหมวดหมู่ก่อน", "แจ้งเตือน")
            return

        cat_name = self.grid_cat.CurrentRow.Cells["Category"].Value
        sub_names_in_selected = set()

        for row in self.grid_preview.SelectedRows:
            val = row.Cells["Id"].Value
            eid = safe_element_id(val)
            if eid == ElementId.InvalidElementId: continue
            el = doc.GetElement(eid)
            if el and get_ui_category_name(el) == cat_name:
                try:
                    sub_name = (el.Symbol.Family.Name if el.Symbol.Family else "") + " - " + el.Name if hasattr(el, "Symbol") and el.Symbol else (el.Name if hasattr(el, "Name") else "Unknown")
                except:
                    sub_name = "Unknown"
                sub_names_in_selected.add(sub_name)

        if not sub_names_in_selected:
            MessageBox.Show("ไม่มี Family Type ของหมวดหมู่นี้ในแถวที่เลือก", "แจ้งเตือน")
            return

        if cat_name not in self.subcat_selections:
            self.subcat_selections[cat_name] = {}
        for sub_name in sub_names_in_selected:
            self.subcat_selections[cat_name][sub_name] = True

        self._refresh_subcat_checks()
        self.lbl_status.Text = "Status: ทำเครื่องหมาย Family Type ตามแถวที่ไฮไลต์ ({0} รายการ)".format(len(sub_names_in_selected))

    def _refresh_subcat_checks(self):
        if not self.grid_cat.CurrentRow:
            return
        cat_name = self.grid_cat.CurrentRow.Cells["Category"].Value
        self.grid_subcat.CellValueChanged -= self._on_subcat_checked
        for row in self.grid_subcat.Rows:
            sub_name = row.Cells["Name"].Value
            row.Cells["Use"].Value = self.subcat_selections.get(cat_name, {}).get(sub_name, False)
        self.grid_subcat.CellValueChanged += self._on_subcat_checked

    # ---------------- Core Numbering ----------------
    def _load_preview(self, s, e):
        self.grid_cat.EndEdit()
        self.preview_elements = []
        for r in self.grid_cat.Rows:
            if r.Cells["Use"].Value:
                cat_name = r.Cells["Category"].Value
                pref = r.Cells["Prefix"].Value or ""
                suf = r.Cells["Suffix"].Value or ""
                elems = self.elements_cache.get(cat_name, collect_elements_for_category(cat_name, self.active_view if self.use_view_filter else None))
                if self.use_view_filter: elems = filter_elements_by_view_visibility(elems, self.active_view)
                for el in elems:
                    try:
                        sub_name = (el.Symbol.Family.Name if el.Symbol.Family else "") + " - " + el.Name if hasattr(el, "Symbol") and el.Symbol else (el.Name if hasattr(el, "Name") else "Unknown")
                    except: sub_name = "Unknown"
                    if self.subcat_selections.get(cat_name, {}).get(sub_name, False):
                        self.preview_elements.append((el, cat_name, pref, suf))
        self._sort_elements()
        self._populate_preview_grid()

    def _sort_elements(self):
        def get_sort_key(item):
            loc = get_element_location(item[0])
            if self.dir_radios[0].Checked: return (loc.X, loc.Y, loc.Z)
            if self.dir_radios[1].Checked: return (-loc.X, loc.Y, loc.Z)
            if self.dir_radios[2].Checked: return (loc.Y, loc.X, loc.Z)
            if self.dir_radios[3].Checked: return (-loc.Y, loc.X, loc.Z)
            if self.dir_radios[4].Checked: return (loc.Z, loc.X, loc.Y)
            if len(self.dir_radios)>5 and self.dir_radios[5].Checked: return (-loc.Z, loc.X, loc.Y)
            return (loc.X, loc.Y, loc.Z)
        self.preview_elements.sort(key=get_sort_key)

    def _populate_preview_grid(self):
        self.grid_preview.Rows.Clear()
        if not self.preview_elements:
            self.lbl_status.Text = "Status: ไม่พบข้อมูลที่เลือก"
            return
        start_num = int(self.txt_start.Text) if self.txt_start.Text.isdigit() else 1
        step_val = int(self.txt_step.Text) if self.txt_step.Text.isdigit() else 1
        digit_count = next((rb.Tag for rb in self.digit_radios if rb.Checked), 2)
        current_num = start_num
        param_name = self._get_param_name()
        g_pref = self.txt_prefix.Text
        g_suf = self.txt_suffix.Text
        for el, cat, pref, suf in self.preview_elements:
            final_val = "{}{}{}{}{}".format(g_pref, pref, str(current_num).zfill(digit_count), suf, g_suf)
            current_val = read_parameter(el, param_name)
            self.grid_preview.Rows.Add(get_element_id_value(el.Id), el.Name, final_val, "อัปเดตแล้ว" if current_val == final_val else "-")
            current_num += step_val
        self.lbl_status.Text = "Status: พร้อมรันข้อมูล {} รายการ".format(len(self.preview_elements))

    def _run_all(self, s, e):
        if self.grid_preview.Rows.Count == 0: return
        param_name = self._get_param_name()
        t = Transaction(doc, "Numbering Elements")
        t.Start()
        try:
            for r in self.grid_preview.Rows:
                val = r.Cells["Id"].Value
                eid = safe_element_id(val)
                if eid == ElementId.InvalidElementId: continue
                el = doc.GetElement(eid)
                if el:
                    success = write_parameter(el, param_name, r.Cells["Value"].Value)
                    if success:
                        r.Cells["Numbered"].Value = "อัปเดตแล้ว"
                    else:
                        r.Cells["Numbered"].Value = "ไม่พบ/เขียนไม่ได้"
            t.Commit()
            self.lbl_status.Text = "Status: สำเร็จเรียบร้อย!"
        except Exception as ex:
            t.RollBack()
            MessageBox.Show(str(ex), "Error")

    def _live_pick_init(self, s, e):
        param_name = self._get_param_name()
        if not param_name:
            self.lbl_status.Text = "Status: กรุณาเลือก Parameter ปลายทาง"
            return
        self.grid_cat.EndEdit()
        self.grid_subcat.EndEdit()
        self._save_settings_on_close(None, None)
        self.live_pick_data = {
            "param_name": param_name,
            "start_num": int(self.txt_start.Text) if self.txt_start.Text.isdigit() else 1,
            "step_val": int(self.txt_step.Text) if self.txt_step.Text.isdigit() else 1,
            "digit_count": next((rb.Tag for rb in self.digit_radios if rb.Checked), 2),
            "g_prefix": self.txt_prefix.Text,
            "g_suffix": self.txt_suffix.Text,
            "direction": next((i for i, rb in enumerate(self.dir_radios) if rb.Checked), 0)
        }
        self.UI_ACTION = "LIVE_PICK"
        self.Close() 

    def _highlight_zoom(self, s, e):
        if self.grid_preview.CurrentRow:
            try:
                val = self.grid_preview.CurrentRow.Cells["Id"].Value
                eid = safe_element_id(val)
                if eid != ElementId.InvalidElementId:
                    uidoc.Selection.SetElementIds(List[ElementId]([eid]))
                    uidoc.ShowElements(eid)
            except: pass

    def _export_csv(self, s, e):
        if self.grid_preview.Rows.Count == 0: return
        last_path = self.config.get("ExportPath", "")
        export_file = ""
        if not last_path or not os.path.exists(last_path):
            dialog = FolderBrowserDialog()
            dialog.Description = "เลือกโฟลเดอร์สำหรับจัดเก็บไฟล์ CSV"
            if dialog.ShowDialog() == DialogResult.OK:
                self.config["ExportPath"] = dialog.SelectedPath
                export_file = os.path.join(dialog.SelectedPath, "Revit_Numbering_Export.csv")
            else: return
        else:
            export_file = os.path.join(last_path, "Revit_Numbering_Export.csv")
        try:
            with open(export_file, 'w') as f:
                writer = csv.writer(f)
                writer.writerow(["Id", "Name", "Value"])
                for r in self.grid_preview.Rows:
                    writer.writerow([str(r.Cells["Id"].Value), unicode(r.Cells["Name"].Value).encode('utf-8'), unicode(r.Cells["Value"].Value).encode('utf-8')])
            self.lbl_status.Text = "Status: ส่งออกที่ " + export_file
        except Exception as ex: MessageBox.Show(str(ex), "Error")

    def _import_csv(self, s, e):
        dialog = OpenFileDialog()
        dialog.Filter = "CSV files (*.csv)|*.csv"
        if dialog.ShowDialog() == DialogResult.OK:
            try:
                imported_data = {}
                with open(dialog.FileName, 'r') as f:
                    reader = csv.reader(f)
                    next(reader)
                    for row in reader:
                        if len(row) >= 3: imported_data[row[0]] = row[2]
                match_count = 0
                for r in self.grid_preview.Rows:
                    eid_str = str(r.Cells["Id"].Value)
                    if eid_str in imported_data:
                        r.Cells["Value"].Value = imported_data[eid_str]
                        r.Cells["Numbered"].Value = "รอการเขียน"
                        match_count += 1
                self.lbl_status.Text = "Status: อัปเดตจาก CSV {} รายการ".format(match_count)
            except Exception as ex: MessageBox.Show(str(ex), "Error")

    def _save_settings_on_close(self, sender=None, e=None):
        cats = {}
        for r in self.grid_cat.Rows:
            cats[r.Cells["Category"].Value] = {
                "Use": bool(r.Cells["Use"].Value),
                "Prefix": r.Cells["Prefix"].Value or "",
                "Suffix": r.Cells["Suffix"].Value or ""
            }
        self.config["Categories"] = cats
        self.config["StartNumber"] = self.txt_start.Text
        self.config["StepValue"] = self.txt_step.Text
        self.config["UseViewFilter"] = self.use_view_filter
        self.config["GlobalPrefix"] = self.txt_prefix.Text
        self.config["GlobalSuffix"] = self.txt_suffix.Text
        for i, rb in enumerate(self.dir_radios):
            if rb.Checked: self.config["Direction"] = i
        for rb in self.digit_radios:
            if rb.Checked: self.config["Digits"] = rb.Tag
        save_user_config(self.config)

# ---------------- Live Pick Engine ----------------
def perform_live_pick(data, config):
    param_name = data["param_name"]
    current_num = data["start_num"]
    step_val = data["step_val"]
    digit_count = data["digit_count"]
    g_pref = data["g_prefix"]
    g_suf = data["g_suffix"]
    direction = data["direction"]
    cat_settings = config.get("Categories", {})
    strict_cat = None
    for c_name, c_data in cat_settings.items():
        if c_data.get("Use"):
            strict_cat = c_name
            break
    picked_ids = []
    def _sort_elements_list(elements, dir_val):
        def get_sort_key(el):
            loc = get_element_location(el)
            if dir_val == 0: return (loc.X, loc.Y, loc.Z)
            if dir_val == 1: return (-loc.X, loc.Y, loc.Z)
            if dir_val == 2: return (loc.Y, loc.X, loc.Z)
            if dir_val == 3: return (-loc.Y, loc.X, loc.Z)
            if dir_val == 4: return (loc.Z, loc.X, loc.Y)
            if dir_val == 5: return (-loc.Z, loc.X, loc.Y)
            return (loc.X, loc.Y, loc.Z)
        elements.sort(key=get_sort_key)
        return elements
    while True:
        try:
            if strict_cat:
                prompt = "คลิกเลือก {} (หากคลิกโดนฐานราก จะรันเลขเข็มทั้งหมดให้) *กด ESC เพื่อจบ".format(strict_cat)
            else:
                prompt = "โหมดอิสระ: คลิกเลือก Family ใดก็ได้ (กด ESC เพื่อสิ้นสุด)"
            ref = uidoc.Selection.PickObject(ObjectType.Element, prompt)
            if not ref: break
            el = doc.GetElement(ref)
            main_cat = get_ui_category_name(el)
            potential_elements = []
            if strict_cat and main_cat != strict_cat:
                if hasattr(el, "GetSubComponentIds"):
                    sub_ids = el.GetSubComponentIds()
                    if sub_ids:
                        for sid in sub_ids:
                            sub_el = doc.GetElement(sid)
                            if get_ui_category_name(sub_el) == strict_cat:
                                potential_elements.append(sub_el)
            if not potential_elements:
                if strict_cat and main_cat != strict_cat:
                    continue 
                potential_elements.append(el)
            elements_to_process = _sort_elements_list(potential_elements, direction)
            t = Transaction(doc, "Live Renumber & Highlight")
            t.Start()
            for target_el in elements_to_process:
                if target_el.Id in picked_ids:
                    continue 
                c_name = get_ui_category_name(target_el)
                pref = cat_settings.get(c_name, {}).get("Prefix", "")
                suf = cat_settings.get(c_name, {}).get("Suffix", "")
                val = "{}{}{}{}{}".format(g_pref, pref, str(current_num).zfill(digit_count), suf, g_suf)
                success = write_parameter(target_el, param_name, val)
                if success:
                    ogs = OverrideGraphicSettings()
                    ogs.SetHalftone(True)
                    doc.ActiveView.SetElementOverrides(target_el.Id, ogs)
                    picked_ids.append(target_el.Id)
                    current_num += step_val
            t.Commit()
        except Exception:
            break 
    if picked_ids:
        t = Transaction(doc, "Clear Highlights")
        t.Start()
        clear_ogs = OverrideGraphicSettings()
        for eid in picked_ids:
            doc.ActiveView.SetElementOverrides(eid, clear_ogs)
        t.Commit()
    config["StartNumber"] = str(current_num)
    save_user_config(config)

# ---------------- Program Loop ----------------
def main():
    try:
        while doc:
            form = NumberingForm()
            form.ShowDialog()
            if getattr(form, 'UI_ACTION', None) == "LIVE_PICK":
                perform_live_pick(form.live_pick_data, form.config)
            else:
                break 
    except Exception as ex:
        MessageBox.Show(traceback.format_exc(), "Error")

if __name__ == '__main__':
    main()