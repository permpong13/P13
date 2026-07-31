# -*- coding: utf-8 -*-
"""Unified sheet, view, revision, and placeholder management for Revit 2026."""
from __future__ import print_function

__title__ = "Sheet\nManager"
__author__ = "P13"

import io
import os
import clr

clr.AddReference("System")
clr.AddReference("System.Drawing")
clr.AddReference("System.Windows.Forms")

from System import IntPtr
from System.Drawing import (
    Color,
    ContentAlignment,
    Font,
    FontStyle,
    Pen,
    Point,
    Size,
    SolidBrush,
)
from System.Drawing.Drawing2D import SmoothingMode
from System.Collections.Generic import List
from System.Windows.Forms import (
    AnchorStyles,
    Application,
    BorderStyle,
    Button,
    Clipboard,
    ComboBox,
    ComboBoxStyle,
    Cursor,
    Cursors,
    DataGridView,
    DataGridViewAutoSizeColumnsMode,
    DataGridViewColumnHeadersHeightSizeMode,
    DataGridViewHeaderBorderStyle,
    DataGridViewSelectionMode,
    DialogResult,
    DockStyle,
    FlatStyle,
    FlowDirection,
    FlowLayoutPanel,
    Form,
    FormBorderStyle,
    FormStartPosition,
    FormWindowState,
    Label,
    MouseButtons,
    OpenFileDialog,
    Padding,
    Panel,
    SaveFileDialog,
    TabAppearance,
    TabControl,
    TabPage,
    TabSizeMode,
    TextBox,
)

from pyrevit import DB, forms, revit, script


doc = revit.doc
uidoc = revit.uidoc
logger = script.get_logger()
config = script.get_config()

LAST_TITLEBLOCK_KEY = "last_sheet_manager_titleblock"
LAST_EXCEL_DIRECTORY_KEY = "last_sheet_manager_excel_directory"
PROFILES_KEY = "sheet_manager_profiles"

# P13 light palette. Keep the visual layer independent from Revit model logic
# so the theme can evolve without changing any document operation.
UI_BG = Color.FromArgb(245, 246, 248)
UI_HEADER = Color.FromArgb(255, 255, 255)
UI_SURFACE = Color.FromArgb(255, 255, 255)
UI_SURFACE_ALT = Color.FromArgb(247, 249, 252)
UI_SURFACE_HOVER = Color.FromArgb(230, 242, 252)
UI_BORDER = Color.FromArgb(215, 220, 226)
UI_TEXT = Color.FromArgb(31, 41, 55)
UI_MUTED = Color.FromArgb(100, 116, 139)
UI_CYAN = Color.FromArgb(32, 164, 243)
UI_CYAN_DARK = Color.FromArgb(0, 112, 170)
UI_ORANGE = Color.FromArgb(255, 159, 28)
UI_GRID_SELECTED = Color.FromArgb(208, 235, 250)

try:
    text_type = unicode
except NameError:
    text_type = str


def element_id_value(element_id):
    """Return the integer value of an ElementId across Revit API versions."""
    if hasattr(element_id, "Value"):
        return element_id.Value
    return element_id.IntegerValue


def parameter_text(parameter):
    """Return a display-safe parameter value."""
    if not parameter or not parameter.HasValue:
        return ""
    try:
        return parameter.AsString() or parameter.AsValueString() or ""
    except Exception:
        return ""


def titleblock_display_name(titleblock_type):
    """Return a stable Family : Type label for a title block type."""
    family_param = titleblock_type.get_Parameter(
        DB.BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM
    )
    type_param = titleblock_type.get_Parameter(
        DB.BuiltInParameter.SYMBOL_NAME_PARAM
    )
    family_name = parameter_text(family_param) or "Unknown Family"
    type_name = parameter_text(type_param) or getattr(
        titleblock_type, "Name", "Unknown Type"
    )
    return "{} : {}".format(family_name, type_name)


def parse_clipboard_rows():
    """Parse sheet number and name pairs copied from Excel or a text editor."""
    if not Clipboard.ContainsText():
        forms.alert(
            "Clipboard does not contain text. Copy two columns from Excel: "
            "Sheet Number and Sheet Name.",
            title="Sheet Manager",
        )
        return []

    parsed_rows = []
    for raw_line in Clipboard.GetText().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "\t" in line:
            parts = line.split("\t")
        elif "," in line:
            parts = line.split(",", 1)
        else:
            parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        number = parts[0].strip().strip('"')
        name = parts[1].strip().strip('"')
        if number and name:
            parsed_rows.append((number, name))

    if not parsed_rows:
        forms.alert(
            "No valid rows were found. Copy two columns from Excel: "
            "Sheet Number and Sheet Name.",
            title="Sheet Manager",
        )
    return parsed_rows


def choose_titleblock():
    """Choose a title block and remember the selection for the next run."""
    titleblocks = list(
        DB.FilteredElementCollector(doc)
        .OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
        .WhereElementIsElementType()
    )
    if not titleblocks:
        forms.alert(
            "No title block types are loaded in this project.",
            title="Sheet Manager",
        )
        return None

    choices = {}
    for titleblock in titleblocks:
        choices[titleblock_display_name(titleblock)] = titleblock

    labels = sorted(choices.keys())
    previous = config.get_option(LAST_TITLEBLOCK_KEY, "")
    selected = forms.SelectFromList.show(
        labels,
        title="Select Title Block",
        default=[previous] if previous in choices else None,
        multiselect=False,
    )
    if not selected:
        return None

    config.set_option(LAST_TITLEBLOCK_KEY, selected)
    script.save_config()
    return choices[selected]


def csv_field(value):
    """Return an RFC 4180-compatible CSV field."""
    text = "" if value is None else text_type(value)
    if '"' in text:
        text = text.replace('"', '""')
    if "," in text or '"' in text or "\n" in text or "\r" in text:
        return '"{}"'.format(text)
    return text


def parse_csv_line(line):
    """Parse one CSV row while preserving commas inside quoted fields."""
    fields = []
    current = []
    in_quotes = False
    index = 0
    while index < len(line):
        character = line[index]
        if character == '"':
            if in_quotes and index + 1 < len(line) and line[index + 1] == '"':
                current.append('"')
                index += 1
            else:
                in_quotes = not in_quotes
        elif character == "," and not in_quotes:
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
        index += 1
    fields.append("".join(current))
    return fields


class SheetManagerForm(Form):
    """Main clean-room sheet management window."""

    def __init__(self):
        self.Text = "P13 Sheet Manager"
        self.StartPosition = FormStartPosition.CenterScreen
        self.Size = Size(1220, 820)
        self.MinimumSize = Size(900, 600)
        self.Font = Font("Segoe UI", 9)
        self.BackColor = UI_BG
        self.FormBorderStyle = getattr(FormBorderStyle, "None")

        self.Paint += self.draw_form_border
        self.Resize += self.form_resize

        self.records = {
            "Sheets": [],
            "Views": [],
            "Revisions": [],
            "Placeholders": [],
        }
        self.grids = {}
        self.segment_buttons = []
        self.segmented_panel = None
        self._dragging = False
        self._drag_mouse_origin = Point(0, 0)
        self._drag_window_origin = Point(0, 0)
        self.window_buttons = []

        self._build_ui()
        self.refresh_data()

    def WndProc(self, m):
        if m.Msg == 0x84:  # WM_NCHITTEST
            pos = self.PointToClient(Cursor.Position)
            border = 8
            if self.WindowState == FormWindowState.Normal:
                if pos.X < border and pos.Y < border:
                    m.Result = IntPtr(13)
                    return
                if pos.X >= self.Width - border and pos.Y < border:
                    m.Result = IntPtr(14)
                    return
                if pos.X < border and pos.Y >= self.Height - border:
                    m.Result = IntPtr(16)
                    return
                if pos.X >= self.Width - border and pos.Y >= self.Height - border:
                    m.Result = IntPtr(17)
                    return
                if pos.X < border:
                    m.Result = IntPtr(10)
                    return
                if pos.X >= self.Width - border:
                    m.Result = IntPtr(11)
                    return
                if pos.Y < border:
                    m.Result = IntPtr(12)
                    return
                if pos.Y >= self.Height - border:
                    m.Result = IntPtr(15)
                    return
            if pos.Y < 52:
                # Child controls (tabs and Windows buttons) receive their own
                # mouse messages. Empty header space acts as a native title bar.
                m.Result = IntPtr(2)
                return
        Form.WndProc(self, m)

    def draw_form_border(self, sender, paint_args):
        g = paint_args.Graphics
        pen = Pen(UI_BORDER, 1)
        g.DrawRectangle(pen, 0, 0, sender.Width - 1, sender.Height - 1)
        pen.Dispose()

    def form_resize(self, sender, args):
        if hasattr(self, "segmented_panel") and self.segmented_panel is not None:
            self.segmented_panel.Location = Point((self.ClientSize.Width - 360) // 2, 12)
        if getattr(self, "window_buttons", None):
            button_right = self.ClientSize.Width - 8
            for button in reversed(self.window_buttons):
                button.Location = Point(button_right - button.Width, 12)
                button_right -= button.Width

    def _begin_window_drag(self, sender, args):
        if args.Button != MouseButtons.Left:
            return
        if self.WindowState == FormWindowState.Maximized:
            self.WindowState = FormWindowState.Normal
        self._dragging = True
        self._drag_mouse_origin = Cursor.Position
        self._drag_window_origin = self.Location
        sender.Capture = True

    def _move_window_drag(self, sender, args):
        if not self._dragging:
            return
        current = Cursor.Position
        delta_x = current.X - self._drag_mouse_origin.X
        delta_y = current.Y - self._drag_mouse_origin.Y
        self.Location = Point(
            self._drag_window_origin.X + delta_x,
            self._drag_window_origin.Y + delta_y,
        )

    def _end_window_drag(self, sender, args):
        self._dragging = False
        sender.Capture = False

    def _make_traffic_light(self, color, click_handler):
        lbl = Label()
        lbl.Size = Size(12, 12)
        lbl.Cursor = Cursors.Hand
        def on_paint(sender, paint_args):
            g = paint_args.Graphics
            g.SmoothingMode = SmoothingMode.AntiAlias
            brush = SolidBrush(color)
            g.FillEllipse(brush, 0, 0, 11, 11)
            brush.Dispose()
        lbl.Paint += on_paint
        lbl.Click += click_handler
        return lbl

    def update_tabs(self, index):
        self.tabs.SelectedIndex = index
        for i, btn in enumerate(self.segment_buttons):
            if i == index:
                btn.BackColor = UI_SURFACE
                btn.ForeColor = UI_CYAN
                btn.Font = Font("Segoe UI Semibold", 9)
            else:
                btn.BackColor = UI_SURFACE_ALT
                btn.ForeColor = UI_MUTED
                btn.Font = Font("Segoe UI", 9)
        self.filter_records()

    def _build_ui(self):
        # Header panel
        header = Panel(Dock=DockStyle.Top, Height=52, BackColor=UI_HEADER)
        def draw_header_bottom_border(sender, paint_args):
            g = paint_args.Graphics
            pen = Pen(UI_BORDER, 1)
            g.DrawLine(pen, 0, sender.Height - 1, sender.Width, sender.Height - 1)
            pen.Dispose()
        header.Paint += draw_header_bottom_border

        # Windows-style title bar with a draggable title area.
        title = Label(
            Text="P13 Sheet Manager",
            Font=Font("Segoe UI Semibold", 10.5),
            ForeColor=UI_TEXT,
            AutoSize=True,
            Location=Point(24, 7),
        )
        header.Controls.Add(title)

        subtitle = Label(
            Text="Sheet / View / Revision Workspace",
            Font=Font("Segoe UI", 7.5),
            ForeColor=UI_MUTED,
            AutoSize=True,
            Location=Point(25, 29),
        )
        header.Controls.Add(subtitle)

        header.MouseDown += self._begin_window_drag
        header.MouseMove += self._move_window_drag
        header.MouseUp += self._end_window_drag
        title.MouseDown += self._begin_window_drag
        title.MouseMove += self._move_window_drag
        title.MouseUp += self._end_window_drag
        subtitle.MouseDown += self._begin_window_drag
        subtitle.MouseMove += self._move_window_drag
        subtitle.MouseUp += self._end_window_drag

        def create_window_button(text, click_handler, width, close_button=False):
            button = Button(
                Text=text,
                Size=Size(width, 28),
                Anchor=AnchorStyles.Top | AnchorStyles.Right,
                FlatStyle=FlatStyle.Flat,
                BackColor=UI_HEADER,
                ForeColor=UI_TEXT,
                Cursor=Cursors.Hand,
                Font=Font("Segoe UI Semibold", 11),
            )
            button.FlatAppearance.BorderSize = 0
            button.FlatAppearance.MouseOverBackColor = (
                Color.FromArgb(254, 226, 226)
                if close_button
                else UI_SURFACE_HOVER
            )
            button.FlatAppearance.MouseDownBackColor = (
                Color.FromArgb(252, 200, 200)
                if close_button
                else UI_CYAN_DARK
            )
            button.Click += click_handler
            return button

        def min_form(s, a):
            self.WindowState = FormWindowState.Minimized

        def toggle_max(s, a):
            self.WindowState = (
                FormWindowState.Normal
                if self.WindowState == FormWindowState.Maximized
                else FormWindowState.Maximized
            )

        def close_form(s, a):
            self.Close()

        header.DoubleClick += toggle_max
        title.DoubleClick += toggle_max
        subtitle.DoubleClick += toggle_max

        button_right = self.ClientSize.Width - 8
        btn_close = create_window_button("×", close_form, 42, True)
        btn_close.Location = Point(button_right - btn_close.Width, 12)
        button_right -= btn_close.Width
        btn_max = create_window_button("□", toggle_max, 42)
        btn_max.Location = Point(button_right - btn_max.Width, 12)
        button_right -= btn_max.Width
        btn_min = create_window_button("—", min_form, 42)
        btn_min.Location = Point(button_right - btn_min.Width, 12)
        self.CancelButton = btn_close
        self.window_buttons = [btn_min, btn_max, btn_close]
        header.Controls.Add(btn_min)
        header.Controls.Add(btn_max)
        header.Controls.Add(btn_close)

        # Segmented Control Panel (center of header)
        self.segmented_panel = Panel(
            Size=Size(360, 28),
            Location=Point((self.ClientSize.Width - 360) // 2, 12),
            BackColor=UI_SURFACE_ALT
        )
        tab_names = ["Sheets", "Views", "Revisions", "Placeholders"]
        self.segment_buttons = []
        for i, t_name in enumerate(tab_names):
            btn = Button(
                Text=t_name,
                Location=Point(2 + i * 89, 2),
                Size=Size(87, 24),
                FlatStyle=FlatStyle.Flat,
                Cursor=Cursors.Hand,
            )
            btn.FlatAppearance.BorderSize = 0
            btn.FlatAppearance.MouseOverBackColor = UI_SURFACE_HOVER
            btn.FlatAppearance.MouseDownBackColor = UI_CYAN_DARK
            def make_segment_click_handler(idx):
                return lambda sender, args: self.update_tabs(idx)
            btn.Click += make_segment_click_handler(i)
            self.segment_buttons.append(btn)
            self.segmented_panel.Controls.Add(btn)
        header.Controls.Add(self.segmented_panel)
        self.Controls.Add(header)

        # Workflow toolbar: common operations stay visible and related commands
        # share one row. Each row scrolls horizontally on compact screens.
        toolbar = Panel(Dock=DockStyle.Top, Height=121, BackColor=UI_HEADER)
        def draw_toolbar_bottom_border(sender, paint_args):
            g = paint_args.Graphics
            pen = Pen(UI_BORDER, 1)
            g.DrawLine(pen, 0, sender.Height - 1, sender.Width, sender.Height - 1)
            pen.Dispose()
        toolbar.Paint += draw_toolbar_bottom_border

        def create_workflow_row():
            return FlowLayoutPanel(
                Dock=DockStyle.Top,
                Height=40,
                FlowDirection=FlowDirection.LeftToRight,
                WrapContents=False,
                AutoScroll=True,
                BackColor=UI_HEADER,
                Padding=Padding(12, 4, 8, 2),
            )

        def create_group_label(text):
            return Label(
                Text=text,
                Size=Size(108, 28),
                TextAlign=ContentAlignment.MiddleLeft,
                ForeColor=UI_MUTED,
                Font=Font("Segoe UI Semibold", 8),
                Margin=Padding(0, 0, 6, 0),
            )

        find_row = create_workflow_row()
        edit_row = create_workflow_row()
        data_row = create_workflow_row()

        find_row.Controls.Add(create_group_label("FIND & CREATE"))
        search_wrapper = Panel(
            Size=Size(250, 28),
            BackColor=UI_SURFACE,
            BorderStyle=BorderStyle.FixedSingle,
            Margin=Padding(0, 0, 8, 0),
        )
        self.search_box = TextBox(
            BorderStyle=getattr(BorderStyle, "None"),
            Location=Point(6, 6),
            Width=236,
            Font=Font("Segoe UI", 9.5),
            BackColor=UI_SURFACE,
            ForeColor=UI_TEXT,
        )
        self.search_box.TextChanged += self.filter_records
        search_wrapper.Controls.Add(self.search_box)
        find_row.Controls.Add(search_wrapper)

        def create_btn(text, handler, width, is_primary=False):
            btn = Button(
                Text=text,
                Size=Size(width, 28),
                FlatStyle=FlatStyle.Flat,
                Cursor=Cursors.Hand,
                Margin=Padding(0, 0, 8, 0),
            )
            if is_primary:
                btn.BackColor = UI_CYAN_DARK
                btn.ForeColor = Color.White
                btn.Font = Font("Segoe UI Semibold", 9)
                btn.FlatAppearance.BorderSize = 0
            else:
                btn.BackColor = UI_SURFACE
                btn.ForeColor = UI_TEXT
                btn.Font = Font("Segoe UI", 9)
                btn.FlatAppearance.BorderSize = 1
                btn.FlatAppearance.BorderColor = UI_BORDER
            btn.FlatAppearance.MouseOverBackColor = UI_CYAN if is_primary else UI_SURFACE_HOVER
            btn.FlatAppearance.MouseDownBackColor = UI_CYAN_DARK
            btn.Click += handler
            return btn

        find_buttons = [
            ("New Sheets from Clipboard", self.create_regular_sheets, 185, True),
            ("New Placeholders", self.create_placeholder_sheets, 135, False),
            ("Refresh", self.refresh_data, 80, False),
        ]
        for text, handler, width, is_primary in find_buttons:
            find_row.Controls.Add(
                create_btn(text, handler, width, is_primary)
            )

        edit_row.Controls.Add(create_group_label("EDIT & BATCH"))
        self.action_combo = ComboBox(
            Size=Size(225, 28),
            FlatStyle=FlatStyle.Flat,
            DropDownStyle=ComboBoxStyle.DropDownList,
            Font=Font("Segoe UI", 9),
            BackColor=UI_SURFACE,
            ForeColor=UI_TEXT,
            Margin=Padding(0, 0, 8, 0),
        )
        for action_name in (
            "Batch Rename",
            "Duplicate Sheets",
            "Convert Placeholders",
            "Assign Revisions",
            "Place Selected Views",
        ):
            self.action_combo.Items.Add(action_name)
        self.action_combo.SelectedIndex = 0
        edit_row.Controls.Add(self.action_combo)

        edit_buttons = [
            ("Run Action", self.run_selected_action, 95, True),
            ("Rename Selected", self.rename_selected_sheet, 125, False),
            ("Edit Parameters", self.edit_selected_parameters, 115, False),
            ("Apply Grid", self.apply_grid_changes, 95, True),
        ]
        for text, handler, width, is_primary in edit_buttons:
            edit_row.Controls.Add(
                create_btn(text, handler, width, is_primary)
            )

        data_row.Controls.Add(create_group_label("DATA & PROFILES"))
        data_buttons = [
            ("Import CSV", self.import_csv, 95, False),
            ("Export CSV", self.export_csv, 95, False),
            ("Save V/S Set", self.save_view_sheet_set, 105, False),
            ("Load V/S Set", self.load_view_sheet_set, 105, False),
            ("Save Profile", self.save_profile, 100, False),
            ("Load Profile", self.load_profile, 100, False),
        ]
        for text, handler, width, is_primary in data_buttons:
            data_row.Controls.Add(
                create_btn(text, handler, width, is_primary)
            )

        # Docking order is reversed for Top-docked controls.
        toolbar.Controls.Add(data_row)
        toolbar.Controls.Add(edit_row)
        toolbar.Controls.Add(find_row)
        self.Controls.Add(toolbar)

        # TabControl
        self.tabs = TabControl(
            Dock=DockStyle.Fill,
            Appearance=TabAppearance.Buttons,
            ItemSize=Size(0, 1),
            SizeMode=TabSizeMode.Fixed,
            BackColor=UI_BG,
            ForeColor=UI_TEXT,
        )
        for tab_name in ("Sheets", "Views", "Revisions", "Placeholders"):
            tab = TabPage(Text=tab_name, BackColor=UI_BG)
            grid = DataGridView(
                Dock=DockStyle.Fill,
                ReadOnly=False,
                AllowUserToAddRows=False,
                AllowUserToDeleteRows=False,
                AllowUserToResizeColumns=True,
                AllowUserToResizeRows=False,
                MultiSelect=True,
                SelectionMode=DataGridViewSelectionMode.FullRowSelect,
                AutoSizeColumnsMode=DataGridViewAutoSizeColumnsMode.Fill,
                BackgroundColor=UI_SURFACE,
                BorderStyle=getattr(BorderStyle, "None"),
                GridColor=UI_BORDER,
                RowHeadersVisible=False,
                ColumnHeadersVisible=True,
                EnableHeadersVisualStyles=False,
                ColumnHeadersBorderStyle=DataGridViewHeaderBorderStyle.Single,
                ColumnHeadersHeight=30,
                ColumnHeadersHeightSizeMode=(
                    DataGridViewColumnHeadersHeightSizeMode.DisableResizing
                ),
            )
            grid.AlternatingRowsDefaultCellStyle.BackColor = UI_SURFACE_ALT
            grid.RowsDefaultCellStyle.BackColor = UI_SURFACE
            grid.RowsDefaultCellStyle.ForeColor = UI_TEXT
            grid.RowsDefaultCellStyle.SelectionBackColor = UI_GRID_SELECTED
            grid.RowsDefaultCellStyle.SelectionForeColor = UI_TEXT
            grid.RowsDefaultCellStyle.Font = Font("Segoe UI", 9)
            grid.ColumnHeadersDefaultCellStyle.BackColor = UI_HEADER
            grid.ColumnHeadersDefaultCellStyle.ForeColor = UI_TEXT
            grid.ColumnHeadersDefaultCellStyle.Font = Font("Segoe UI Semibold", 9)
            grid.ColumnHeadersDefaultCellStyle.SelectionBackColor = UI_HEADER
            grid.RowTemplate.Height = 28

            grid.CellDoubleClick += self.open_selected_item
            grid.CellEndEdit += self.grid_cell_edited
            tab.Controls.Add(grid)
            self.tabs.TabPages.Add(tab)
            self.grids[tab_name] = grid

        self.Controls.Add(self.tabs)

        # Status Bar
        self.status = Label(
            Dock=DockStyle.Bottom,
            Height=28,
            Text="Ready",
            Padding=Padding(12, 6, 0, 0),
            BackColor=UI_HEADER,
            ForeColor=UI_MUTED,
            Font=Font("Segoe UI", 8.5)
        )
        def draw_status_top_border(sender, paint_args):
            g = paint_args.Graphics
            pen = Pen(UI_BORDER, 1)
            g.DrawLine(pen, 0, 0, sender.Width, 0)
            pen.Dispose()
        self.status.Paint += draw_status_top_border
        self.Controls.Add(self.status)

        # Keep the title bar above the toolbar in the custom borderless layout.
        self.Controls.SetChildIndex(header, 0)

        self.update_tabs(0)

    def _sheet_record(self, sheet):
        revision = parameter_text(
            sheet.get_Parameter(DB.BuiltInParameter.SHEET_CURRENT_REVISION)
        )
        return {
            "element": sheet,
            "values": [
                "Ready",
                sheet.SheetNumber or "",
                sheet.Name or "",
                revision,
                str(element_id_value(sheet.Id)),
            ],
        }

    def _collect_view_records(self, sheets):
        placed_on = {}
        for sheet in sheets:
            if sheet.IsPlaceholder:
                continue
            for viewport_id in sheet.GetAllViewports():
                viewport = doc.GetElement(viewport_id)
                if viewport:
                    placed_on.setdefault(element_id_value(viewport.ViewId), []).append(
                        sheet.SheetNumber
                    )

        for schedule_instance in DB.FilteredElementCollector(doc).OfClass(
            DB.ScheduleSheetInstance
        ):
            if schedule_instance.IsTitleblockRevisionSchedule:
                continue
            owner_sheet = doc.GetElement(schedule_instance.OwnerViewId)
            if owner_sheet:
                placed_on.setdefault(
                    element_id_value(schedule_instance.ScheduleId), []
                ).append(owner_sheet.SheetNumber)

        records = []
        for view in DB.FilteredElementCollector(doc).OfClass(DB.View):
            if view.IsTemplate or isinstance(view, DB.ViewSheet):
                continue
            view_id = element_id_value(view.Id)
            sheet_numbers = sorted(set(placed_on.get(view_id, [])))
            records.append(
                {
                    "element": view,
                    "values": [
                        view.Name or "",
                        str(view.ViewType),
                        ", ".join(sheet_numbers) if sheet_numbers else "Not Placed",
                        str(getattr(view, "Scale", "")),
                        str(view_id),
                    ],
                }
            )
        return records

    def _collect_revision_records(self):
        records = []
        revision_settings = DB.RevisionSettings.GetRevisionSettings(doc)
        is_per_sheet = (
            revision_settings.RevisionNumbering
            == DB.RevisionNumbering.PerSheet
        )
        for revision_id in DB.Revision.GetAllRevisionIds(doc):
            try:
                revision = doc.GetElement(revision_id)
                # A revision has no single global number when numbering is per
                # sheet. Its displayed number must be resolved from a sheet.
                revision_number = (
                    "Per Sheet" if is_per_sheet else revision.RevisionNumber
                )
                records.append(
                    {
                        "element": revision,
                        "values": [
                            "Ready",
                            str(revision.SequenceNumber),
                            revision_number or "",
                            revision.RevisionDate or "",
                            revision.Description or "",
                            "Yes" if revision.Issued else "No",
                            str(element_id_value(revision.Id)),
                        ],
                    }
                )
            except Exception as error:
                logger.warning(
                    "Could not read revision {}: {}".format(
                        element_id_value(revision_id), error
                    )
                )
        return records

    def refresh_data(self, sender=None, args=None):
        try:
            self.UseWaitCursor = True
            sheets = list(
                DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet).ToElements()
            )
            self.records["Sheets"] = [
                self._sheet_record(sheet) for sheet in sheets if not sheet.IsPlaceholder
            ]
            self.records["Placeholders"] = [
                self._sheet_record(sheet) for sheet in sheets if sheet.IsPlaceholder
            ]
            self.records["Views"] = self._collect_view_records(sheets)
            self.records["Revisions"] = self._collect_revision_records()
            self.filter_records()
        except Exception as error:
            logger.exception("Sheet Manager refresh failed")
            forms.alert(
                "Could not refresh Sheet Manager data.\n\n{}".format(error),
                title="Sheet Manager",
            )
        finally:
            self.UseWaitCursor = False

    def _active_tab_name(self):
        selected_tab = self.tabs.SelectedTab
        if selected_tab is not None:
            return selected_tab.Text
        if self.tabs.TabPages.Count:
            selected_index = self.tabs.SelectedIndex
            if selected_index < 0:
                selected_index = 0
            return self.tabs.TabPages[selected_index].Text
        return "Sheets"

    def _headers_for_tab(self, tab_name):
        if tab_name in ("Sheets", "Placeholders"):
            return ["Status", "Sheet Number", "Sheet Name", "Revision", "Element ID"]
        if tab_name == "Views":
            return ["View Name", "View Type", "Placed On", "Scale", "Element ID"]
        return [
            "Status",
            "Sequence",
            "Revision Number",
            "Date",
            "Description",
            "Issued",
            "Element ID",
        ]

    def _configure_grid_columns(self, tab_name, grid):
        """Give business-critical fields most of the available table width."""
        column_layouts = {
            "Sheets": (
                (48, 7.0),    # Status
                (100, 23.0),  # Sheet Number
                (160, 50.0),  # Sheet Name
                (56, 9.0),    # Revision
                (72, 11.0),   # Element ID
            ),
            "Placeholders": (
                (48, 7.0),
                (100, 23.0),
                (160, 50.0),
                (56, 9.0),
                (72, 11.0),
            ),
            "Views": (
                (140, 38.0),  # View Name
                (90, 17.0),   # View Type
                (110, 25.0),  # Placed On
                (48, 8.0),    # Scale
                (72, 12.0),   # Element ID
            ),
            "Revisions": (
                (48, 7.0),    # Status
                (54, 8.0),    # Sequence
                (80, 12.0),   # Revision Number
                (76, 11.0),   # Date
                (140, 40.0),  # Description
                (48, 8.0),    # Issued
                (72, 14.0),   # Element ID
            ),
        }
        layout = column_layouts.get(tab_name, ())
        for index, values in enumerate(layout):
            if index >= grid.Columns.Count:
                break
            minimum_width, fill_weight = values
            column = grid.Columns[index]
            column.MinimumWidth = minimum_width
            column.FillWeight = fill_weight

    def filter_records(self, sender=None, args=None):
        tab_name = self._active_tab_name()
        grid = self.grids[tab_name]
        search = self.search_box.Text.strip().lower()
        grid.SuspendLayout()
        try:
            grid.Rows.Clear()
            headers = self._headers_for_tab(tab_name)
            rebuild_columns = grid.Columns.Count != len(headers)
            if not rebuild_columns:
                for index, header in enumerate(headers):
                    if grid.Columns[index].HeaderText != header:
                        rebuild_columns = True
                        break
            if rebuild_columns:
                grid.Columns.Clear()
                for header in headers:
                    grid.Columns.Add(header, header)
                self._configure_grid_columns(tab_name, grid)
            for column in grid.Columns:
                column.ReadOnly = True
            if tab_name in ("Sheets", "Placeholders"):
                grid.Columns[1].ReadOnly = False
                grid.Columns[2].ReadOnly = False
            elif tab_name == "Revisions":
                grid.Columns[3].ReadOnly = False
                grid.Columns[4].ReadOnly = False
                grid.Columns[5].ReadOnly = False
            visible_count = 0
            for record in self.records[tab_name]:
                searchable = " | ".join(record["values"]).lower()
                if search and search not in searchable:
                    continue
                row_index = grid.Rows.Add(*record["values"])
                grid.Rows[row_index].Tag = record["element"]
                visible_count += 1
            self.status.Text = "{}: {} item(s)".format(tab_name, visible_count)
        finally:
            grid.ResumeLayout()

    def _selected_elements(self):
        grid = self.grids[self._active_tab_name()]
        return [row.Tag for row in grid.SelectedRows if row.Tag]

    def grid_cell_edited(self, sender, args):
        tab_name = self._active_tab_name()
        editable_columns = {
            "Sheets": (1, 2),
            "Placeholders": (1, 2),
            "Revisions": (3, 4, 5),
        }
        if args.RowIndex >= 0 and args.ColumnIndex in editable_columns.get(tab_name, ()):
            sender.Rows[args.RowIndex].Cells[0].Value = "Modified"
            sender.Rows[args.RowIndex].Cells[0].Style.ForeColor = Color.DarkOrange
            self.status.Text = "Unsaved grid changes. Click Apply Grid."

    def apply_grid_changes(self, sender, args):
        tab_name = self._active_tab_name()
        if tab_name == "Revisions":
            self.apply_revision_grid_changes()
            return
        if tab_name not in ("Sheets", "Placeholders"):
            forms.alert(
                "Direct grid editing is available on Sheets and Placeholders.",
                title="Sheet Manager",
            )
            return
        edits = []
        for row in self.grids[tab_name].Rows:
            status = text_type(row.Cells[0].Value or "")
            if status != "Modified":
                continue
            edits.append(
                (
                    row.Tag,
                    text_type(row.Cells[1].Value or "").strip(),
                    text_type(row.Cells[2].Value or "").strip(),
                )
            )
        if not edits:
            forms.alert("No grid changes were found.", title="Sheet Manager")
            return
        if self._apply_sheet_edits(edits, "P13 Apply Sheet Grid Changes"):
            self.refresh_data()
            forms.alert(
                "Applied changes to {} sheet(s).".format(len(edits)),
                title="Sheet Manager",
            )

    def apply_revision_grid_changes(self):
        edits = []
        for row in self.grids["Revisions"].Rows:
            if text_type(row.Cells[0].Value or "") != "Modified":
                continue
            issued_text = text_type(row.Cells[5].Value or "").strip().lower()
            if issued_text not in ("yes", "no", "true", "false", "1", "0"):
                forms.alert(
                    "Issued must be Yes or No.", title="Sheet Manager"
                )
                return
            edits.append(
                (
                    row.Tag,
                    text_type(row.Cells[3].Value or "").strip(),
                    text_type(row.Cells[4].Value or "").strip(),
                    issued_text in ("yes", "true", "1"),
                )
            )
        if not edits:
            forms.alert("No revision grid changes were found.", title="Sheet Manager")
            return
        transaction = DB.Transaction(doc, "P13 Apply Revision Grid Changes")
        transaction.Start()
        try:
            for revision, revision_date, description, issued in edits:
                if revision.Issued:
                    revision.Issued = False
                revision.RevisionDate = revision_date
                revision.Description = description
                revision.Issued = issued
            transaction.Commit()
        except Exception as error:
            transaction.RollBack()
            forms.alert(
                "Could not apply revision changes. Issued revisions may have "
                "read-only fields.\n\n{}".format(error),
                title="Sheet Manager",
            )
            return
        self.refresh_data()
        forms.alert(
            "Updated {} revision(s).".format(len(edits)), title="Sheet Manager"
        )

    def _apply_sheet_edits(self, edits, transaction_name):
        prohibited = set('{}[]|;<>?`~')
        proposed_numbers = {}
        for sheet in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet):
            proposed_numbers[element_id_value(sheet.Id)] = sheet.SheetNumber or ""

        for sheet, number, name in edits:
            if not number or not name:
                forms.alert(
                    "Sheet number and sheet name cannot be empty.",
                    title="Sheet Manager",
                )
                return False
            if any(character in prohibited for character in number):
                forms.alert(
                    "Sheet number '{}' contains a prohibited character.".format(number),
                    title="Sheet Manager",
                )
                return False
            proposed_numbers[element_id_value(sheet.Id)] = number

        used = {}
        for sheet_id, number in proposed_numbers.items():
            key = number.lower()
            if key in used and used[key] != sheet_id:
                forms.alert(
                    "Duplicate sheet number detected: '{}'".format(number),
                    title="Sheet Manager",
                )
                return False
            used[key] = sheet_id

        transaction = DB.Transaction(doc, transaction_name)
        transaction.Start()
        try:
            changed_numbers = []
            for sheet, number, name in edits:
                if sheet.SheetNumber != number:
                    temporary = "P13_TMP_{}".format(element_id_value(sheet.Id))
                    sheet.SheetNumber = temporary
                    changed_numbers.append((sheet, number))
                sheet.Name = name
            for sheet, number in changed_numbers:
                sheet.SheetNumber = number
            transaction.Commit()
            return True
        except Exception as error:
            transaction.RollBack()
            logger.exception("Sheet edit transaction failed")
            forms.alert(
                "Could not apply sheet changes.\n\n{}".format(error),
                title="Sheet Manager",
            )
            return False

    def run_selected_action(self, sender, args):
        action = text_type(self.action_combo.SelectedItem or "")
        handlers = {
            "Batch Rename": self.batch_rename,
            "Duplicate Sheets": self.duplicate_sheets,
            "Convert Placeholders": self.convert_placeholders,
            "Assign Revisions": self.assign_revisions,
            "Place Selected Views": self.place_selected_views,
        }
        handler = handlers.get(action)
        if handler:
            handler()

    def batch_rename(self):
        if self._active_tab_name() not in ("Sheets", "Placeholders"):
            forms.alert(
                "Select sheets or placeholders before batch renaming.",
                title="Sheet Manager",
            )
            return
        selected = self._selected_elements()
        if not selected:
            forms.alert("Select one or more sheets.", title="Sheet Manager")
            return
        number_pattern = forms.ask_for_string(
            default="{number}",
            prompt=(
                "Sheet number pattern. Use {number} and {name}. "
                "Sequential numbering is intentionally not used."
            ),
            title="Batch Rename Sheets",
        )
        if number_pattern is None:
            return
        name_pattern = forms.ask_for_string(
            default="{name}",
            prompt="Sheet name pattern. Use {number} and {name}.",
            title="Batch Rename Sheets",
        )
        if name_pattern is None:
            return
        edits = []
        for sheet in selected:
            new_number = number_pattern.replace(
                "{number}", sheet.SheetNumber
            ).replace("{name}", sheet.Name)
            new_name = name_pattern.replace(
                "{number}", sheet.SheetNumber
            ).replace("{name}", sheet.Name)
            edits.append((sheet, new_number.strip(), new_name.strip()))
        if self._apply_sheet_edits(edits, "P13 Batch Rename Sheets"):
            self.refresh_data()
            forms.alert(
                "Renamed {} sheet(s).".format(len(edits)), title="Sheet Manager"
            )

    def duplicate_sheets(self):
        """Duplicate selected sheets using Revit's native SheetDuplicateOption API."""
        if self._active_tab_name() != "Sheets":
            forms.alert(
                "Select regular sheets on the Sheets tab before duplicating.",
                title="Duplicate Sheets",
            )
            return

        selected = [
            sheet
            for sheet in self._selected_elements()
            if isinstance(sheet, DB.ViewSheet) and not sheet.IsPlaceholder
        ]
        if not selected:
            forms.alert("Select one or more regular sheets.", title="Duplicate Sheets")
            return

        option_map = {
            "Empty sheet": DB.SheetDuplicateOption.DuplicateEmptySheet,
            "Sheet with detailing": DB.SheetDuplicateOption.DuplicateSheetWithDetailing,
            "Sheet with views only": DB.SheetDuplicateOption.DuplicateSheetWithViewsOnly,
            "Sheet with views and detailing": DB.SheetDuplicateOption.DuplicateSheetWithViewsAndDetailing,
            "Sheet with dependent views": DB.SheetDuplicateOption.DuplicateSheetWithViewsAsDependent,
        }
        option_label = forms.SelectFromList.show(
            sorted(option_map.keys()),
            title="Duplicate Sheet Contents",
            multiselect=False,
        )
        if not option_label:
            return
        duplicate_option = option_map[option_label]

        number_pattern = forms.ask_for_string(
            default="{number}-COPY",
            prompt=(
                "New sheet number pattern. Use {number} and {name}. "
                "Category/group patterns are allowed; continuous numbering is not used."
            ),
            title="Duplicate Sheets",
        )
        if number_pattern is None or not number_pattern.strip():
            return
        name_pattern = forms.ask_for_string(
            default="{name} (Copy)",
            prompt="New sheet name pattern. Use {number} and {name}.",
            title="Duplicate Sheets",
        )
        if name_pattern is None or not name_pattern.strip():
            return

        planned = []
        prohibited = set('{}[]|;<>?`~')
        for source in selected:
            new_number = number_pattern.replace(
                "{number}", source.SheetNumber or ""
            ).replace("{name}", source.Name or "").strip()
            new_name = name_pattern.replace(
                "{number}", source.SheetNumber or ""
            ).replace("{name}", source.Name or "").strip()
            if not new_number or not new_name:
                forms.alert(
                    "The duplicate number and name patterns must produce values.",
                    title="Duplicate Sheets",
                )
                return
            if any(character in prohibited for character in new_number):
                forms.alert(
                    "Generated sheet number '{}' contains a prohibited character.".format(
                        new_number
                    ),
                    title="Duplicate Sheets",
                )
                return
            planned.append((source, new_number, new_name))

        existing_numbers = set(
            (sheet.SheetNumber or "").strip().lower()
            for sheet in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)
            if sheet.SheetNumber
        )
        planned_numbers = [number.lower() for _, number, _ in planned]
        if len(planned_numbers) != len(set(planned_numbers)):
            forms.alert(
                "The generated sheet numbers are duplicated. Change the pattern and try again.",
                title="Duplicate Sheets",
            )
            return
        conflicts = sorted(set(planned_numbers).intersection(existing_numbers))
        if conflicts:
            forms.alert(
                "These generated sheet numbers already exist:\n\n{}".format(
                    "\n".join(conflicts)
                ),
                title="Duplicate Sheets",
            )
            return

        candidates = []
        unavailable = []
        for source, new_number, new_name in planned:
            try:
                if source.CanBeDuplicated(duplicate_option):
                    candidates.append((source, new_number, new_name))
                else:
                    unavailable.append(source.SheetNumber)
            except Exception as error:
                logger.warning(
                    "Could not check whether sheet {} can be duplicated: {}".format(
                        source.SheetNumber, error
                    )
                )
                unavailable.append(source.SheetNumber)
        if not candidates:
            forms.alert(
                "None of the selected sheets can be duplicated with this option.",
                title="Duplicate Sheets",
            )
            return

        created = []
        skipped = list(unavailable)
        transaction = DB.Transaction(doc, "P13 Duplicate Sheets")
        transaction.Start()
        try:
            self.UseWaitCursor = True
            for source, new_number, new_name in candidates:
                subtransaction = DB.SubTransaction(doc)
                subtransaction.Start()
                try:
                    new_id = source.Duplicate(duplicate_option)
                    new_sheet = doc.GetElement(new_id)
                    # Use a temporary number so every final number can be assigned
                    # safely after all native duplication operations complete.
                    new_sheet.SheetNumber = "P13_TMP_DUP_{}".format(
                        element_id_value(new_id)
                    )
                    created.append((new_sheet, new_number, new_name))
                    subtransaction.Commit()
                except Exception as error:
                    subtransaction.RollBack()
                    skipped.append(source.SheetNumber)
                    logger.warning(
                        "Could not duplicate sheet {}: {}".format(
                            source.SheetNumber, error
                        )
                    )

            for new_sheet, new_number, new_name in created:
                new_sheet.SheetNumber = new_number
                new_sheet.Name = new_name
            transaction.Commit()
        except Exception as error:
            transaction.RollBack()
            logger.exception("Sheet duplication transaction failed")
            forms.alert(
                "Could not duplicate the selected sheets. No partial changes were kept.\n\n{}".format(
                    error
                ),
                title="Duplicate Sheets",
            )
            return
        finally:
            self.UseWaitCursor = False

        self.refresh_data()
        message = "Duplicated {} sheet(s) using '{}'.".format(
            len(created), option_label
        )
        if skipped:
            message += "\n\nSkipped:\n{}".format("\n".join(skipped))
        forms.alert(message, title="Duplicate Sheets")

    def convert_placeholders(self):
        if self._active_tab_name() != "Placeholders":
            forms.alert(
                "Select placeholder sheets on the Placeholders tab.",
                title="Sheet Manager",
            )
            return
        placeholders = self._selected_elements()
        if not placeholders:
            forms.alert("Select one or more placeholders.", title="Sheet Manager")
            return
        titleblock = choose_titleblock()
        if not titleblock:
            return
        converted = 0
        transaction = DB.Transaction(doc, "P13 Convert Placeholder Sheets")
        transaction.Start()
        try:
            for placeholder in placeholders:
                if placeholder.IsPlaceholder:
                    placeholder.ConvertToRealSheet(titleblock.Id)
                    converted += 1
            transaction.Commit()
        except Exception as error:
            transaction.RollBack()
            forms.alert(
                "Could not convert placeholder sheets.\n\n{}".format(error),
                title="Sheet Manager",
            )
            return
        self.refresh_data()
        forms.alert(
            "Converted {} placeholder sheet(s).".format(converted),
            title="Sheet Manager",
        )

    def assign_revisions(self):
        if self._active_tab_name() != "Sheets":
            forms.alert(
                "Select regular sheets on the Sheets tab.", title="Sheet Manager"
            )
            return
        sheets = self._selected_elements()
        if not sheets:
            forms.alert("Select one or more sheets.", title="Sheet Manager")
            return
        revision_map = {}
        for revision_id in DB.Revision.GetAllRevisionIds(doc):
            revision = doc.GetElement(revision_id)
            label = "Seq {} | {} | {}".format(
                revision.SequenceNumber,
                revision.RevisionDate or "No Date",
                revision.Description or "No Description",
            )
            revision_map[label] = revision.Id
        chosen = forms.SelectFromList.show(
            sorted(revision_map.keys()),
            title="Select Revisions",
            multiselect=True,
        )
        if not chosen:
            return
        mode = forms.SelectFromList.show(
            ["Add", "Remove", "Replace"],
            title="Revision Assignment Mode",
            multiselect=False,
        )
        if not mode:
            return
        revision_ids_by_value = dict(
            (element_id_value(revision_id), revision_id)
            for revision_id in revision_map.values()
        )
        chosen_ids = set(element_id_value(revision_map[label]) for label in chosen)
        transaction = DB.Transaction(doc, "P13 Assign Sheet Revisions")
        transaction.Start()
        try:
            for sheet in sheets:
                current = set()
                for revision_id in sheet.GetAdditionalRevisionIds():
                    revision_value = element_id_value(revision_id)
                    current.add(revision_value)
                    revision_ids_by_value[revision_value] = revision_id
                if mode == "Add":
                    result = current.union(chosen_ids)
                elif mode == "Remove":
                    result = current.difference(chosen_ids)
                else:
                    result = set(chosen_ids)
                sheet.SetAdditionalRevisionIds(
                    List[DB.ElementId]([
                        revision_ids_by_value[value] for value in result
                    ])
                )
            transaction.Commit()
        except Exception as error:
            transaction.RollBack()
            forms.alert(
                "Could not update sheet revisions.\n\n{}".format(error),
                title="Sheet Manager",
            )
            return
        self.refresh_data()
        forms.alert(
            "Updated revisions on {} sheet(s).".format(len(sheets)),
            title="Sheet Manager",
        )

    def place_selected_views(self):
        if self._active_tab_name() != "Views":
            forms.alert(
                "Select views on the Views tab.", title="Sheet Manager"
            )
            return
        views = self._selected_elements()
        if not views:
            forms.alert("Select one or more views.", title="Sheet Manager")
            return
        sheet_map = {}
        for sheet in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet):
            if not sheet.IsPlaceholder:
                sheet_map["{} | {}".format(sheet.SheetNumber, sheet.Name)] = sheet
        selected_sheet_label = forms.SelectFromList.show(
            sorted(sheet_map.keys()),
            title="Select Target Sheet",
            multiselect=False,
        )
        if not selected_sheet_label:
            return
        sheet = sheet_map[selected_sheet_label]
        outline = sheet.Outline
        center_x = (outline.Min.U + outline.Max.U) / 2.0
        center_y = (outline.Min.V + outline.Max.V) / 2.0
        placed = 0
        skipped = []
        transaction = DB.Transaction(doc, "P13 Place Views on Sheet")
        transaction.Start()
        try:
            for index, view in enumerate(views):
                point = DB.XYZ(
                    center_x + (index % 3 - 1) * 0.25,
                    center_y - (index // 3) * 0.20,
                    0.0,
                )
                subtransaction = DB.SubTransaction(doc)
                subtransaction.Start()
                try:
                    if isinstance(view, DB.ViewSchedule):
                        DB.ScheduleSheetInstance.Create(doc, sheet.Id, view.Id, point)
                    elif DB.Viewport.CanAddViewToSheet(doc, sheet.Id, view.Id):
                        DB.Viewport.Create(doc, sheet.Id, view.Id, point)
                    else:
                        skipped.append(view.Name)
                        subtransaction.RollBack()
                        continue
                    subtransaction.Commit()
                    placed += 1
                except Exception:
                    subtransaction.RollBack()
                    skipped.append(view.Name)
            transaction.Commit()
        except Exception as error:
            transaction.RollBack()
            forms.alert(
                "Could not place views.\n\n{}".format(error),
                title="Sheet Manager",
            )
            return
        self.refresh_data()
        message = "Placed {} view(s) on sheet {}.".format(
            placed, sheet.SheetNumber
        )
        if skipped:
            message += "\n\nSkipped:\n{}".format("\n".join(skipped))
        forms.alert(message, title="Sheet Manager")

    def save_view_sheet_set(self, sender, args):
        if self._active_tab_name() not in ("Sheets", "Views"):
            forms.alert(
                "View/Sheet Sets can be created from the Sheets or Views tab.",
                title="Sheet Manager",
            )
            return
        elements = self._selected_elements()
        printable_views = [
            element
            for element in elements
            if isinstance(element, DB.View) and element.CanBePrinted
        ]
        if not printable_views:
            forms.alert(
                "Select one or more printable sheets or views.",
                title="Sheet Manager",
            )
            return
        set_name = forms.ask_for_string(
            prompt="Enter a name for the View/Sheet Set:",
            title="Save View/Sheet Set",
        )
        if not set_name or not set_name.strip():
            return
        set_name = set_name.strip()
        existing_names = set(
            item.Name
            for item in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheetSet)
        )
        if set_name in existing_names:
            forms.alert(
                "A View/Sheet Set named '{}' already exists.".format(set_name),
                title="Sheet Manager",
            )
            return
        view_set = DB.ViewSet()
        for view in printable_views:
            view_set.Insert(view)
        transaction = DB.Transaction(doc, "P13 Save View Sheet Set")
        transaction.Start()
        try:
            view_sheet_setting = doc.PrintManager.ViewSheetSetting
            view_sheet_setting.CurrentViewSheetSet.Views = view_set
            view_sheet_setting.SaveAs(set_name)
            transaction.Commit()
        except Exception as error:
            transaction.RollBack()
            forms.alert(
                "Could not save the View/Sheet Set.\n\n{}".format(error),
                title="Sheet Manager",
            )
            return
        forms.alert(
            "Saved View/Sheet Set '{}'.".format(set_name),
            title="Sheet Manager",
        )

    def load_view_sheet_set(self, sender, args):
        sets = list(DB.FilteredElementCollector(doc).OfClass(DB.ViewSheetSet))
        if not sets:
            forms.alert("No saved View/Sheet Sets were found.", title="Sheet Manager")
            return
        set_map = dict((item.Name, item) for item in sets)
        selected_name = forms.SelectFromList.show(
            sorted(set_map.keys()),
            title="Load View/Sheet Set",
            multiselect=False,
        )
        if not selected_name:
            return
        set_views = list(set_map[selected_name].Views)
        desired_ids = set(element_id_value(view.Id) for view in set_views)
        has_sheets = any(isinstance(view, DB.ViewSheet) for view in set_views)
        self.update_tabs(0 if has_sheets else 1)
        self.search_box.Text = ""
        self.filter_records()
        grid = self.grids[self._active_tab_name()]
        selected_count = 0
        for row in grid.Rows:
            row.Selected = element_id_value(row.Tag.Id) in desired_ids
            if row.Selected:
                selected_count += 1
        self.status.Text = "Loaded set '{}': {} selected item(s)".format(
            selected_name, selected_count
        )

    def save_profile(self, sender, args):
        profile_name = forms.ask_for_string(
            prompt="Enter a profile name:", title="Save Sheet Manager Profile"
        )
        if not profile_name or not profile_name.strip():
            return
        profile_name = profile_name.strip()
        profiles = dict(config.get_option(PROFILES_KEY, {}) or {})
        profiles[profile_name] = {
            "tab": self._active_tab_name(),
            "search": self.search_box.Text,
            "selected_ids": [
                element_id_value(element.Id)
                for element in self._selected_elements()
            ],
            "action": text_type(self.action_combo.SelectedItem or "Batch Rename"),
        }
        config.set_option(PROFILES_KEY, profiles)
        script.save_config()
        forms.alert(
            "Saved profile '{}'.".format(profile_name), title="Sheet Manager"
        )

    def load_profile(self, sender, args):
        profiles = dict(config.get_option(PROFILES_KEY, {}) or {})
        if not profiles:
            forms.alert("No Sheet Manager profiles were found.", title="Sheet Manager")
            return
        profile_name = forms.SelectFromList.show(
            sorted(profiles.keys()),
            title="Load Sheet Manager Profile",
            multiselect=False,
        )
        if not profile_name:
            return
        profile = profiles[profile_name]
        tab_names = ["Sheets", "Views", "Revisions", "Placeholders"]
        tab_name = profile.get("tab", "Sheets")
        self.update_tabs(tab_names.index(tab_name) if tab_name in tab_names else 0)
        self.search_box.Text = profile.get("search", "")
        action = profile.get("action", "Batch Rename")
        if action in [text_type(item) for item in self.action_combo.Items]:
            self.action_combo.SelectedItem = action
        self.filter_records()
        selected_ids = set(profile.get("selected_ids", []))
        grid = self.grids[self._active_tab_name()]
        for row in grid.Rows:
            row.Selected = element_id_value(row.Tag.Id) in selected_ids
        self.status.Text = "Loaded profile '{}'".format(profile_name)

    def _configure_file_dialog(self, dialog):
        previous_directory = config.get_option(LAST_EXCEL_DIRECTORY_KEY, "")
        if previous_directory and os.path.isdir(previous_directory):
            dialog.InitialDirectory = previous_directory

    def _remember_file_directory(self, path):
        directory = os.path.dirname(path)
        if directory:
            config.set_option(LAST_EXCEL_DIRECTORY_KEY, directory)
            script.save_config()

    def export_csv(self, sender, args):
        tab_name = self._active_tab_name()
        grid = self.grids[tab_name]
        dialog = SaveFileDialog()
        dialog.Title = "Export Excel-Compatible CSV"
        dialog.Filter = "CSV files (*.csv)|*.csv"
        dialog.FileName = "P13_{}.csv".format(tab_name)
        self._configure_file_dialog(dialog)
        if dialog.ShowDialog() != DialogResult.OK:
            return
        try:
            headers = [text_type(column.HeaderText) for column in grid.Columns]
            include_placeholder_flag = tab_name in ("Sheets", "Placeholders")
            if include_placeholder_flag:
                headers.append("Placeholder")
            lines = [u",".join(csv_field(value) for value in headers)]
            for row in grid.Rows:
                values = [
                    text_type(cell.Value or "") for cell in row.Cells
                ]
                if include_placeholder_flag:
                    values.append("Yes" if tab_name == "Placeholders" else "No")
                lines.append(u",".join(csv_field(value) for value in values))
            with io.open(dialog.FileName, "w", encoding="utf-8-sig") as output_file:
                output_file.write(u"\r\n".join(lines))
            self._remember_file_directory(dialog.FileName)
            forms.alert(
                "Exported {} row(s) for Excel.".format(grid.Rows.Count),
                title="Sheet Manager",
            )
        except Exception as error:
            forms.alert(
                "Could not export CSV.\n\n{}".format(error),
                title="Sheet Manager",
            )

    def import_csv(self, sender, args):
        dialog = OpenFileDialog()
        dialog.Title = "Import Excel-Compatible CSV"
        dialog.Filter = "CSV files (*.csv)|*.csv"
        self._configure_file_dialog(dialog)
        if dialog.ShowDialog() != DialogResult.OK:
            return
        try:
            with io.open(dialog.FileName, "r", encoding="utf-8-sig") as input_file:
                lines = [line.rstrip("\r\n") for line in input_file if line.strip()]
            if not lines:
                raise ValueError("The CSV file is empty.")
            headers = [value.strip() for value in parse_csv_line(lines[0])]
            header_index = dict((name.strip(), index) for index, name in enumerate(headers))
            if "Sheet Number" not in header_index or "Sheet Name" not in header_index:
                raise ValueError(
                    "CSV must contain Sheet Number and Sheet Name columns."
                )
            imported_rows = []
            for line in lines[1:]:
                values = parse_csv_line(line)
                while len(values) < len(headers):
                    values.append("")
                imported_rows.append(dict(zip(headers, values)))
            self._import_sheet_rows(imported_rows)
            self._remember_file_directory(dialog.FileName)
        except Exception as error:
            logger.exception("CSV import failed")
            forms.alert(
                "Could not import CSV.\n\n{}".format(error),
                title="Sheet Manager",
            )

    def _import_sheet_rows(self, imported_rows):
        existing_sheets = list(
            DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)
        )
        by_id = dict((element_id_value(sheet.Id), sheet) for sheet in existing_sheets)
        by_number = dict(
            (sheet.SheetNumber.lower(), sheet)
            for sheet in existing_sheets
            if sheet.SheetNumber
        )
        edits = []
        creates = []
        for row in imported_rows:
            number = row.get("Sheet Number", "").strip()
            name = row.get("Sheet Name", "").strip()
            if not number or not name:
                continue
            element = None
            raw_id = row.get("Element ID", "").strip()
            if raw_id:
                try:
                    element = by_id.get(int(raw_id))
                except Exception:
                    element = None
            if element is None:
                element = by_number.get(number.lower())
            if element is not None:
                edits.append((element, number, name))
            else:
                placeholder_text = row.get("Placeholder", "").strip().lower()
                is_placeholder = placeholder_text in ("yes", "true", "1")
                creates.append((number, name, is_placeholder))

        desired_numbers = dict(
            (element_id_value(sheet.Id), sheet.SheetNumber.lower())
            for sheet in existing_sheets
        )
        for sheet, number, name in edits:
            desired_numbers[element_id_value(sheet.Id)] = number.lower()
        combined = list(desired_numbers.values()) + [
            number.lower() for number, name, placeholder in creates
        ]
        if len(combined) != len(set(combined)):
            forms.alert(
                "The imported data contains duplicate sheet numbers.",
                title="Sheet Manager",
            )
            return

        titleblock = None
        if any(not placeholder for number, name, placeholder in creates):
            titleblock = choose_titleblock()
            if not titleblock:
                return

        transaction = DB.Transaction(doc, "P13 Import Sheet CSV")
        transaction.Start()
        try:
            changed_numbers = []
            for sheet, number, name in edits:
                if sheet.SheetNumber != number:
                    sheet.SheetNumber = "P13_TMP_{}".format(
                        element_id_value(sheet.Id)
                    )
                    changed_numbers.append((sheet, number))
                sheet.Name = name
            for number, name, is_placeholder in creates:
                if is_placeholder:
                    sheet = DB.ViewSheet.CreatePlaceholder(doc)
                else:
                    sheet = DB.ViewSheet.Create(doc, titleblock.Id)
                sheet.SheetNumber = number
                sheet.Name = name
            for sheet, number in changed_numbers:
                sheet.SheetNumber = number
            transaction.Commit()
        except Exception:
            transaction.RollBack()
            raise
        self.refresh_data()
        forms.alert(
            "Imported {} update(s) and created {} sheet(s).".format(
                len(edits), len(creates)
            ),
            title="Sheet Manager",
        )

    def create_regular_sheets(self, sender, args):
        rows = parse_clipboard_rows()
        if not rows:
            return
        titleblock = choose_titleblock()
        if not titleblock:
            return
        self._create_sheets(rows, titleblock.Id, False)

    def create_placeholder_sheets(self, sender, args):
        rows = parse_clipboard_rows()
        if not rows:
            return
        self._create_sheets(rows, None, True)

    def _create_sheets(self, rows, titleblock_id, placeholders):
        existing_numbers = set(
            sheet.SheetNumber.lower()
            for sheet in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)
            if sheet.SheetNumber
        )
        created = 0
        skipped = []
        transaction_name = (
            "P13 Create Placeholder Sheets" if placeholders else "P13 Create Sheets"
        )
        transaction = DB.Transaction(doc, transaction_name)
        transaction.Start()
        try:
            for number, name in rows:
                if number.lower() in existing_numbers:
                    skipped.append(number)
                    continue
                if placeholders:
                    sheet = DB.ViewSheet.CreatePlaceholder(doc)
                else:
                    sheet = DB.ViewSheet.Create(doc, titleblock_id)
                sheet.SheetNumber = number
                sheet.Name = name
                existing_numbers.add(number.lower())
                created += 1
            transaction.Commit()
        except Exception:
            transaction.RollBack()
            logger.exception("Sheet creation failed")
            forms.alert(
                "Could not create the sheets. Review the pyRevit log for details.",
                title="Sheet Manager",
            )
            return

        self.refresh_data()
        message = "Created {} sheet(s).".format(created)
        if skipped:
            message += "\n\nSkipped duplicate numbers:\n{}".format(
                ", ".join(skipped)
            )
        forms.alert(message, title="Sheet Manager")

    def rename_selected_sheet(self, sender, args):
        if self._active_tab_name() not in ("Sheets", "Placeholders"):
            forms.alert(
                "Select one item on the Sheets or Placeholders tab.",
                title="Sheet Manager",
            )
            return
        selected = self._selected_elements()
        if len(selected) != 1:
            forms.alert(
                "Select exactly one sheet to rename.", title="Sheet Manager"
            )
            return
        sheet = selected[0]
        new_number = forms.ask_for_string(
            default=sheet.SheetNumber,
            prompt="Enter the new sheet number:",
            title="Rename Sheet",
        )
        if new_number is None:
            return
        new_name = forms.ask_for_string(
            default=sheet.Name,
            prompt="Enter the new sheet name:",
            title="Rename Sheet",
        )
        if new_name is None:
            return
        new_number = new_number.strip()
        new_name = new_name.strip()
        if not new_number or not new_name:
            forms.alert(
                "Sheet number and sheet name cannot be empty.",
                title="Sheet Manager",
            )
            return
        for existing in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet):
            if existing.Id != sheet.Id and existing.SheetNumber.lower() == new_number.lower():
                forms.alert(
                    "Sheet number '{}' already exists.".format(new_number),
                    title="Sheet Manager",
                )
                return
        with revit.Transaction("P13 Rename Sheet"):
            sheet.SheetNumber = new_number
            sheet.Name = new_name
        self.refresh_data()

    def edit_selected_parameters(self, sender, args):
        if self._active_tab_name() not in ("Sheets", "Placeholders"):
            forms.alert(
                "Parameter editing is available on Sheets and Placeholders.",
                title="Sheet Manager",
            )
            return
        selected = self._selected_elements()
        if not selected:
            forms.alert("Select one or more sheets.", title="Sheet Manager")
            return

        common_names = None
        for element in selected:
            writable_names = set(
                parameter.Definition.Name
                for parameter in element.Parameters
                if parameter.Definition
                and parameter.Definition.Name
                and not parameter.IsReadOnly
                and parameter.StorageType == DB.StorageType.String
            )
            common_names = (
                writable_names
                if common_names is None
                else common_names.intersection(writable_names)
            )
        if not common_names:
            forms.alert(
                "The selected sheets have no common writable text parameters.",
                title="Sheet Manager",
            )
            return

        parameter_name = forms.SelectFromList.show(
            sorted(common_names),
            title="Select Sheet Parameter",
            multiselect=False,
        )
        if not parameter_name:
            return
        new_value = forms.ask_for_string(
            prompt="Enter the new value for '{}':".format(parameter_name),
            title="Edit Sheet Parameters",
        )
        if new_value is None:
            return

        updated = 0
        with revit.Transaction("P13 Edit Sheet Parameters"):
            for element in selected:
                parameter = element.LookupParameter(parameter_name)
                if parameter and not parameter.IsReadOnly:
                    parameter.Set(new_value)
                    updated += 1
        self.refresh_data()
        forms.alert(
            "Updated {} sheet(s).".format(updated), title="Sheet Manager"
        )

    def open_selected_item(self, sender, args):
        if args.RowIndex < 0:
            return
        element = sender.Rows[args.RowIndex].Tag
        if isinstance(element, DB.View):
            try:
                uidoc.ActiveView = element
                self.Close()
            except Exception as error:
                forms.alert(
                    "Could not open the selected view.\n\n{}".format(error),
                    title="Sheet Manager",
                )


if __name__ == "__main__":
    SheetManagerForm().ShowDialog()
