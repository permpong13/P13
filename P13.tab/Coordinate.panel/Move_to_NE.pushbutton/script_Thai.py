# -*- coding: utf-8 -*-
__doc__ = "ย้าย Family ที่เลือกไปยังพิกัด North/East ที่ต้องการ (หน่วย: เมตร)"
__title__ = "Move to\nN/E"
__author__ = "เพิ่มพงษ์"

import math
import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
clr.AddReference("System")

import System.Drawing
import System.Windows.Forms

from pyrevit import forms, DB
from Autodesk.Revit.UI import Selection
from Autodesk.Revit.UI.Selection import ObjectType

from System.Windows.Forms import (
    Form, Label, TextBox, Button, FormStartPosition, DialogResult,
    FormBorderStyle, TableLayoutPanel, Panel,
    DockStyle, AnchorStyles, RowStyle, ColumnStyle, SizeType,
    Padding, BorderStyle, FlatStyle, AutoSizeMode
)
from System.Drawing import Size, Point, Font, Color, FontStyle
import System

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

# ============================================================
# Constants for iOS Style
# ============================================================
IOS_BLUE = Color.FromArgb(0, 122, 255)
IOS_BG_GRAY = Color.FromArgb(242, 242, 247)
IOS_SEPARATOR = Color.FromArgb(200, 199, 204)
IOS_TEXT_GRAY = Color.FromArgb(142, 142, 147)
FONT_REGULAR = Font("Segoe UI", 12)
FONT_BOLD = Font("Segoe UI", 12, FontStyle.Bold)
FONT_TITLE = Font("Segoe UI", 14, System.Drawing.FontStyle.Bold)
FONT_BUTTON = Font("Segoe UI Semibold", 13)

# ============================================================
# ฟอร์มกรอกพิกัด N / E แบบ iOS Style (Redesigned with Layouts)
# ============================================================
class iOSStyleNEInputForm(Form):
    def __init__(self):
        self.north = None
        self.east = None
        self.InitializeComponent()

    def InitializeComponent(self):
        # --- Form Setup ---
        self.Text = "Move to N/E"
        self.AutoSize = True
        self.AutoSizeMode = AutoSizeMode.GrowAndShrink
        self.MinimumSize = Size(380, 0)
        self.StartPosition = FormStartPosition.CenterScreen
        self.BackColor = System.Drawing.Color.White
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.Padding = Padding(0)

        # --- Main Layout Container (TableLayoutPanel) ---
        self.mainLayout = TableLayoutPanel()
        self.mainLayout.Dock = DockStyle.Fill
        self.mainLayout.AutoSize = True
        self.mainLayout.ColumnCount = 1
        self.mainLayout.RowCount = 4
        
        self.mainLayout.RowStyles.Add(RowStyle(SizeType.Absolute, 50))
        self.mainLayout.RowStyles.Add(RowStyle(SizeType.AutoSize))
        self.mainLayout.RowStyles.Add(RowStyle(SizeType.AutoSize))
        self.mainLayout.RowStyles.Add(RowStyle(SizeType.AutoSize))
        self.Controls.Add(self.mainLayout)

        # ==================== 1. Header Section ====================
        self.header_panel = Panel()
        self.header_panel.Dock = DockStyle.Fill
        self.header_panel.BackColor = System.Drawing.Color.White

        self.lbl_title = Label()
        self.lbl_title.Text = "ระบุพิกัดเป้าหมาย"
        self.lbl_title.Dock = DockStyle.Fill
        self.lbl_title.Font = FONT_TITLE
        self.lbl_title.TextAlign = System.Drawing.ContentAlignment.MiddleCenter
        self.header_panel.Controls.Add(self.lbl_title)

        header_separator = Panel()
        header_separator.Height = 1
        header_separator.Dock = DockStyle.Bottom
        header_separator.BackColor = System.Drawing.Color.FromArgb(230, 230, 230)
        self.header_panel.Controls.Add(header_separator)

        self.mainLayout.Controls.Add(self.header_panel, 0, 0)

        # ==================== 2. Description Section ====================
        self.lbl_desc = Label()
        self.lbl_desc.Text = "กรุณากรอกพิกัด N/E ที่ต้องการในหน่วยเมตร"
        self.lbl_desc.Dock = DockStyle.Fill
        self.lbl_desc.Font = FONT_REGULAR
        self.lbl_desc.ForeColor = IOS_TEXT_GRAY
        self.lbl_desc.TextAlign = System.Drawing.ContentAlignment.MiddleLeft
        self.lbl_desc.Padding = Padding(20, 15, 20, 5)
        self.lbl_desc.AutoSize = True
        self.mainLayout.Controls.Add(self.lbl_desc, 0, 1)

        # ==================== 3. Input Group Section (iOS Style) ====================
        self.inputGroupContainer = Panel()
        self.inputGroupContainer.Dock = DockStyle.Fill
        self.inputGroupContainer.BackColor = IOS_BG_GRAY
        self.inputGroupContainer.Padding = Padding(0, 10, 0, 20)
        self.inputGroupContainer.AutoSize = True

        self.innerInputTable = TableLayoutPanel()
        self.innerInputTable.Dock = DockStyle.Top
        self.innerInputTable.AutoSize = True
        self.innerInputTable.BackColor = System.Drawing.Color.White
        self.innerInputTable.ColumnCount = 1
        self.innerInputTable.RowCount = 3
        
        self.innerInputTable.RowStyles.Add(RowStyle(SizeType.Absolute, 50))
        self.innerInputTable.RowStyles.Add(RowStyle(SizeType.Absolute, 1))
        self.innerInputTable.RowStyles.Add(RowStyle(SizeType.Absolute, 50))
        
        top_border = Panel()
        top_border.Height = 1
        top_border.Dock = DockStyle.Top
        top_border.BackColor = IOS_SEPARATOR
        self.inputGroupContainer.Controls.Add(top_border)

        bottom_border = Panel()
        bottom_border.Height = 1
        bottom_border.Dock = DockStyle.Bottom
        bottom_border.BackColor = IOS_SEPARATOR
        self.inputGroupContainer.Controls.Add(bottom_border)
        
        # --- Row 1: Northing Input ---
        self.tb_n = self._create_input_row(self.innerInputTable, 0, "Northing (N)")

        # --- Row 2: Separator ---
        sep_panel = Panel()
        sep_panel.Dock = DockStyle.Fill
        sep_panel.BackColor = System.Drawing.Color.White
        sep_line = Panel()
        sep_line.Height = 1
        sep_line.Margin = Padding(20, 0, 0, 0)
        sep_line.Dock = DockStyle.Bottom
        sep_line.BackColor = IOS_SEPARATOR
        sep_panel.Controls.Add(sep_line)
        self.innerInputTable.Controls.Add(sep_panel, 0, 1)

        # --- Row 3: Easting Input ---
        self.tb_e = self._create_input_row(self.innerInputTable, 2, "Easting (E)")

        self.inputGroupContainer.Controls.Add(self.innerInputTable)
        self.mainLayout.Controls.Add(self.inputGroupContainer, 0, 2)

        # ==================== 4. Buttons Section ====================
        self.buttonTable = TableLayoutPanel()
        self.buttonTable.Dock = DockStyle.Fill
        self.buttonTable.AutoSize = True
        self.buttonTable.ColumnCount = 1
        self.buttonTable.RowCount = 2
        self.buttonTable.Padding = Padding(20, 0, 20, 20)
        self.buttonTable.RowStyles.Add(RowStyle(SizeType.AutoSize))
        self.buttonTable.RowStyles.Add(RowStyle(SizeType.AutoSize))

        self.btn_ok = Button()
        self.btn_ok.Text = "ย้ายตำแหน่ง"
        self.btn_ok.Height = 50
        self.btn_ok.Dock = DockStyle.Top
        self.btn_ok.Font = FONT_BUTTON
        self.btn_ok.BackColor = IOS_BLUE
        self.btn_ok.ForeColor = System.Drawing.Color.White
        self.btn_ok.FlatStyle = FlatStyle.Flat
        self.btn_ok.FlatAppearance.BorderSize = 0
        self.btn_ok.Click += self.on_ok_click
        self.btn_ok.Margin = Padding(0, 0, 0, 12)
        self.btn_ok.TabIndex = 2
        self.buttonTable.Controls.Add(self.btn_ok, 0, 0)

        self.btn_cancel = Button()
        self.btn_cancel.Text = "ยกเลิก"
        self.btn_cancel.Height = 50
        self.btn_cancel.Dock = DockStyle.Top
        self.btn_cancel.Font = FONT_REGULAR
        self.btn_cancel.BackColor = System.Drawing.Color.White
        self.btn_cancel.ForeColor = IOS_BLUE
        self.btn_cancel.FlatStyle = FlatStyle.Flat
        self.btn_cancel.FlatAppearance.BorderSize = 0
        self.btn_cancel.Click += self.on_cancel_click
        self.btn_cancel.TabIndex = 3
        self.buttonTable.Controls.Add(self.btn_cancel, 0, 1)

        self.mainLayout.Controls.Add(self.buttonTable, 0, 3)

        # --- Final Form Settings ---
        self.AcceptButton = self.btn_ok
        self.CancelButton = self.btn_cancel
        self.Shown += self.on_form_shown
        
        self.tb_n.TabIndex = 0
        self.tb_e.TabIndex = 1
        self.btn_ok.TabIndex = 2
        self.btn_cancel.TabIndex = 3

    def _create_input_row(self, parent_table, row_idx, label_text):
        row_panel = Panel()
        row_panel.Dock = DockStyle.Fill
        row_panel.Padding = Padding(20, 0, 20, 0)
        
        row_layout = TableLayoutPanel()
        row_layout.Dock = DockStyle.Fill
        row_layout.RowCount = 1
        row_layout.ColumnCount = 3
        
        row_layout.ColumnStyles.Add(ColumnStyle(SizeType.AutoSize))
        row_layout.ColumnStyles.Add(ColumnStyle(SizeType.Percent, 100))
        row_layout.ColumnStyles.Add(ColumnStyle(SizeType.AutoSize))

        lbl = Label()
        lbl.Text = label_text
        lbl.Font = FONT_REGULAR
        lbl.Dock = DockStyle.Left
        lbl.TextAlign = System.Drawing.ContentAlignment.MiddleLeft
        lbl.AutoSize = True
        lbl.TabStop = False
        row_layout.Controls.Add(lbl, 0, 0)

        unit_lbl = Label()
        unit_lbl.Text = "ม."
        unit_lbl.Font = FONT_REGULAR
        unit_lbl.ForeColor = IOS_TEXT_GRAY
        unit_lbl.Dock = DockStyle.Right
        unit_lbl.TextAlign = System.Drawing.ContentAlignment.MiddleRight
        unit_lbl.AutoSize = True
        unit_lbl.Padding = Padding(5, 0, 0, 0)
        unit_lbl.TabStop = False
        row_layout.Controls.Add(unit_lbl, 2, 0)

        tb = TextBox()
        tb.Dock = DockStyle.Fill
        tb.Font = FONT_REGULAR
        tb.BorderStyle = BorderStyle.None
        tb.TextAlign = System.Windows.Forms.HorizontalAlignment.Right
        tb.Multiline = True
        tb.Height = 30
        tb.Margin = Padding(10, 10, 0, 5)
        tb.KeyDown += self.textbox_key_down # ยังคงใช้ KeyDown สำหรับ Enter
        # tb.KeyPress += self.validate_numeric_input # <-- เอาออก เพื่อให้ Ctrl+V ทำงาน
        tb.TextChanged += self.textbox_text_changed # <-- เพิ่ม TextChanged event สำหรับ Paste
        row_layout.Controls.Add(tb, 1, 0)

        row_panel.Controls.Add(row_layout)
        parent_table.Controls.Add(row_panel, 0, row_idx)
        
        return tb

    def on_form_shown(self, sender, args):
        self.tb_n.Focus()
        
        try:
            import System.Runtime.InteropServices
            gdi32 = System.Runtime.InteropServices.DllImport("gdi32.dll")

            self.btn_ok.Region = System.Drawing.Region.FromHrgn(
                gdi32.CreateRoundRectRgn(0, 0, self.btn_ok.Width, self.btn_ok.Height, 12, 12)
            )
            self.btn_cancel.Region = System.Drawing.Region.FromHrgn(
                gdi32.CreateRoundRectRgn(0, 0, self.btn_cancel.Width, self.btn_cancel.Height, 12, 12)
            )
        except Exception as e:
            pass

    def textbox_key_down(self, sender, args):
        # Allow Ctrl+V to pass through without blocking
        # If Ctrl is pressed, and V is pressed, don't handle it here.
        if args.Control and args.KeyCode == System.Windows.Forms.Keys.V:
            args.Handled = False
            return
            
        if args.KeyCode == System.Windows.Forms.Keys.Enter:
            args.SuppressKeyPress = True
            self.on_ok_click(None, None)

    # --- NEW: Handle TextChanged event for validation (including Paste) ---
    def textbox_text_changed(self, sender, args):
        self._validate_textbox_content(sender)

    def _validate_textbox_content(self, textbox):
        """Validates the entire content of the textbox."""
        original_text = textbox.Text
        if not original_text: # ถ้าว่าง ก็ไม่ต้องทำอะไร
            textbox.BackColor = System.Drawing.Color.White
            return

        # ลบ comma ออกก่อนตรวจสอบ
        cleaned_text = original_text.replace(",", "").strip()

        # Check for valid numeric format
        try:
            float(cleaned_text)
            # ถ้าเป็นตัวเลขถูกต้อง
            textbox.BackColor = System.Drawing.Color.White # กลับเป็นสีขาว
            textbox.ForeColor = System.Drawing.Color.Black
        except ValueError:
            # ถ้าไม่ใช่ตัวเลข
            textbox.BackColor = System.Drawing.Color.LightPink # เปลี่ยนพื้นหลังเป็นสีชมพูอ่อน
            textbox.ForeColor = System.Drawing.Color.Red
            # Optional: System.Media.SystemSounds.Beep.Play() # เสียงเตือน

    def on_ok_click(self, sender, args):
        # ตรวจสอบว่ากรอกข้อมูลครบหรือไม่
        if not self.tb_n.Text.strip() or not self.tb_e.Text.strip():
            forms.alert("กรุณากรอกค่าพิกัดให้ครบถ้วน", title="ข้อมูลไม่ครบถ้วน")
            return

        # ตรวจสอบความถูกต้องของข้อมูลอีกครั้งก่อนส่งค่า
        try:
            n_val = float(self.tb_n.Text.replace(",", "").strip())
            e_val = float(self.tb_e.Text.replace(",", "").strip())
        except ValueError:
            forms.alert("กรุณากรอกค่าพิกัดเป็นตัวเลขที่ถูกต้อง (เมตร)\nช่องที่มีปัญหาจะแสดงเป็นสีชมพู", title="ข้อมูลไม่ถูกต้อง")
            # ถ้ามีปัญหา ให้ไป Focus ที่ TextBox ที่มีปัญหา
            self._validate_textbox_content(self.tb_n)
            self._validate_textbox_content(self.tb_e)
            if self.tb_n.BackColor == System.Drawing.Color.LightPink:
                self.tb_n.Focus()
            elif self.tb_e.BackColor == System.Drawing.Color.LightPink:
                self.tb_e.Focus()
            return

        self.north = n_val
        self.east = e_val
        self.DialogResult = DialogResult.OK
        self.Close()

    def on_cancel_click(self, sender, args):
        self.DialogResult = DialogResult.Cancel
        self.Close()


# ============================================================
# ฟังก์ชันดึงข้อมูล Base Point - ใช้สูตรเดียวกับสคริปต์คำนวณพิกัด
# ============================================================
def get_base_point_info(doc):
    locations = DB.FilteredElementCollector(doc).OfClass(DB.BasePoint).ToElements()
    bp_nsouth = bp_ewest = angle = 0.0
    basepoint_found = False

    for loc in locations:
        try:
            if not loc.IsShared:
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
        except Exception as e:
            pass

    if not basepoint_found:
        return 0.0, 0.0, 0.0

    return angle, bp_ewest, bp_nsouth


def rotate(x, y, theta):
    return [
        math.cos(theta) * x + math.sin(theta) * y,
        -math.sin(theta) * x + math.cos(theta) * y
    ]


def reverse_transform(target_north_m, target_east_m, angle, bp_ewest, bp_nsouth):
    target_north_ft = target_north_m / 0.3048
    target_east_ft = target_east_m / 0.3048
    
    relative_north = target_north_ft - bp_nsouth
    relative_east = target_east_ft - bp_ewest
    
    inverse_angle = -angle
    revit_coords = rotate(relative_east, relative_north, inverse_angle)
    
    return revit_coords[0], revit_coords[1]


# ============================================================
# ฟังก์ชันช่วยหาตำแหน่ง Element (X,Y,Z)
# ============================================================
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
        if transform:
            origin = transform.Origin
            return origin.X, origin.Y, origin.Z
    else:
        bbox = element.get_BoundingBox(None)
        if bbox:
            center = (bbox.Min + bbox.Max) * 0.5
            return center.X, center.Y, center.Z
    
    return None, None, None

# ============================================================
# MAIN
# ============================================================
def main():
    if doc is None:
        forms.alert("ไม่พบไฟล์ Revit ที่เปิดอยู่", exitscript=True)

    sel_ids = list(uidoc.Selection.GetElementIds())

    if not sel_ids:
        try:
            ref = uidoc.Selection.PickObject(ObjectType.Element, "เลือก Family หรือ Element ที่ต้องการย้าย")
            if ref:
                sel_ids = [ref.ElementId]
        except:
            forms.alert("ไม่ได้เลือก Element ใด ๆ", exitscript=True)

    if not sel_ids:
        forms.alert("ไม่ได้เลือก Element ใด ๆ", exitscript=True)

    elements = [doc.GetElement(eid) for eid in sel_ids]
    elements = [e for e in elements if e is not None and e.Category is not None]

    if not elements:
        forms.alert("ไม่พบ Element ที่สามารถใช้งานได้", exitscript=True)

    angle, bp_ewest, bp_nsouth = get_base_point_info(doc)
    
    form = iOSStyleNEInputForm()
    result = form.ShowDialog()

    if result != DialogResult.OK:
        return

    target_n = form.north
    target_e = form.east

    first_elem = elements[0]
    cur_x, cur_y, cur_z = get_element_xy(first_elem)
    
    if cur_x is None:
        forms.alert("Element แรกไม่มี Location ที่สามารถย้ายได้", exitscript=True)

    new_x, new_y = reverse_transform(target_n, target_e, angle, bp_ewest, bp_nsouth)

    new_point = DB.XYZ(new_x, new_y, cur_z)
    cur_point = DB.XYZ(cur_x, cur_y, cur_z)
    
    move_vec = new_point - cur_point

    with DB.Transaction(doc, "Move Elements to N/E") as t:
        t.Start()
        try:
            moved_count = 0
            failed_elements = []

            for e in elements:
                try:
                    DB.ElementTransformUtils.MoveElement(doc, e.Id, move_vec)
                    moved_count += 1
                except Exception as elem_ex:
                    failed_elements.append((e.Name, str(elem_ex)))
            
            if failed_elements:
                error_msg = "มีบาง Element ไม่สามารถย้ายได้:\n"
                for name, reason in failed_elements:
                    error_msg += "  - {}: {}\n".format(name, reason)
                forms.alert(error_msg, title="Warning: ย้ายไม่สมบูรณ์")
            
            t.Commit()

        except Exception as ex:
            t.RollBack()
            forms.alert("เกิดข้อผิดพลาดในการย้าย Element: {}".format(ex), title="Error", exitscript=True)
            return

    if moved_count > 0:
        forms.alert(
            "✅ ย้าย Element จำนวน {} ตัวสำเร็จ\n\n📍 ไปยังพิกัด:\n• Northing: {:.3f} m\n• Easting: {:.3f} m".format(
                moved_count, target_n, target_e
            ),
            title="ดำเนินการเสร็จสิ้น"
        )
    elif not failed_elements:
        forms.alert("ไม่มี Element ใดถูกย้าย", title="แจ้งเตือน")


if __name__ == "__main__":
    main()