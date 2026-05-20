# -*- coding: utf-8 -*-
from __future__ import print_function

__title__ = "Import Excel\nas Revit Table"
__doc__ = "Import XLSX or CSV data as a text-based table in a new Revit drafting view."
__author__ = "P13"

import os
import sys

import clr
clr.AddReference("System.Windows.Forms")
from System.Windows.Forms import OpenFileDialog, DialogResult

from pyrevit import revit, DB, forms, script

# --- Library Setup ---
LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "_schedule_excel_lib")
while LIB_DIR in sys.path: sys.path.remove(LIB_DIR)
sys.path.insert(0, LIB_DIR)

# บังคับล้าง Cache และเรียกใช้ไฟล์ไลบรารีชื่อใหม่ (v2)
if "p13_excel_v2" in sys.modules: del sys.modules["p13_excel_v2"]
import p13_excel_v2 as sx

doc = revit.doc

def pick_table_file():
    dialog = OpenFileDialog()
    dialog.Title = "Select Excel or CSV File"
    dialog.Filter = "Excel or CSV Files (*.xlsx;*.csv)|*.xlsx;*.csv|Excel Files (*.xlsx)|*.xlsx|CSV Files (*.csv)|*.csv"
    if dialog.ShowDialog() == DialogResult.OK:
        return dialog.FileName
    return None

def read_table_source(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return os.path.splitext(os.path.basename(path))[0], sx.read_csv(path)

    sheets = sx.read_xlsx(path)
    # กรองชีตขยะที่ขึ้นต้นด้วย __ ทิ้ง (แทนการเรียก META_SHEET_NAME ที่ถูกลบไปแล้ว)
    names = [name for name in sheets.keys() if not str(name).startswith("__")]
    
    if not names:
        return None, None
    if len(names) == 1:
        return names[0], sheets[names[0]]

    selected_sheet = forms.SelectFromList.show(names, title="Select Sheet to Import", button_name="Select")
    if not selected_sheet:
        return None, None
    return selected_sheet, sheets[selected_sheet]

def get_default_text_type():
    types = DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType).ToElements()
    for t in types:
        if "2.5mm" in t.Name or "3/32\"" in t.Name:
            return t
    return types[0] if types else None

def create_cell_text(view, text_type, point, width, text):
    if not text or not text.strip():
        return
    options = DB.TextNoteOptions(text_type.Id)
    options.HorizontalAlignment = DB.HorizontalTextAlignment.Center
    options.VerticalAlignment = DB.VerticalTextAlignment.Middle
    options.TypeId = text_type.Id
    DB.TextNote.Create(doc, view.Id, point, width, text, options)

def create_line(view, start_pt, end_pt):
    line = DB.Line.CreateBound(start_pt, end_pt)
    DB.DetailCurve.Create(doc, view, line)

def create_table_view(sheet_name, rows):
    if not rows:
        return None, 0, 0

    view_family_types = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType).ToElements()
    drafting_type = next((v for v in view_family_types if v.ViewFamily == DB.ViewFamily.Drafting), None)
    if not drafting_type:
        return None, 0, 0

    view_name = "Excel Table - {}".format(sheet_name)
    used_names = [v.Name for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewDrafting).ToElements()]
    base_name = view_name
    idx = 2
    while view_name in used_names:
        view_name = "{} ({})".format(base_name, idx)
        idx += 1

    text_type = get_default_text_type()
    if not text_type:
        return None, 0, 0

    with DB.Transaction(doc, "Create Excel Table View"):
        view = DB.ViewDrafting.Create(doc, drafting_type.Id)
        view.Name = view_name
        view.Scale = 100

        col_count = max(len(row) for row in rows)
        widths = [0.0] * col_count
        padding_x = 0.5
        row_height = 1.5

        # 🌟 ฟิลเตอร์ทำความสะอาด: ถ้าเป็นไฟล์จาก MLABS ให้ตัด 7 บรรทัดบน (ที่มีแต่โค้ด) ทิ้งไปเลย ให้เหลือแต่ตารางสวยๆ
        if len(rows) > 7 and sx.to_text(rows[0][0]).strip() == "MLabs":
            rows = rows[7:]

        for row in rows:
            for i, val in enumerate(row):
                text_len = len(sx.to_text(val)) * 0.4
                widths[i] = max(widths[i], text_len + (padding_x * 2))

        total_width = sum(widths)
        total_height = len(rows) * row_height

        y = -row_height / 2.0
        for row_idx, row in enumerate(rows):
            x = 0.0
            for col_idx, value in enumerate(row):
                point = DB.XYZ(x + padding_x, y - padding_y, 0)
                create_cell_text(view, text_type, point, widths[col_idx] - (padding_x * 2), sx.to_text(value))
                x += widths[col_idx]
            y -= row_height

        x = 0.0
        create_line(view, DB.XYZ(0, 0, 0), DB.XYZ(total_width, 0, 0))
        create_line(view, DB.XYZ(0, -total_height, 0), DB.XYZ(total_width, -total_height, 0))
        for width in widths:
            create_line(view, DB.XYZ(x, 0, 0), DB.XYZ(x, -total_height, 0))
            x += width
        create_line(view, DB.XYZ(total_width, 0, 0), DB.XYZ(total_width, -total_height, 0))
        for row_idx in range(1, len(rows)):
            y_line = -row_idx * row_height
            create_line(view, DB.XYZ(0, y_line, 0), DB.XYZ(total_width, y_line, 0))

    return view_name, len(rows), len(widths)

def main():
    path = pick_table_file()
    if not path:
        script.exit()

    try:
        sheet_name, rows = read_table_source(path)
    except Exception as exc:
        forms.alert("Could not read file:\n{}".format(exc), title="Import Table", exitscript=True)

    if not sheet_name or not rows:
        forms.alert("No valid data found to import.", title="Import Table")
        return

    view_name, row_count, col_count = create_table_view(sheet_name, rows)
    if view_name:
        forms.alert("Created Drafting View: '{}'\nRows: {}\nCols: {}".format(view_name, row_count, col_count), title="Import Table Complete")
    else:
        forms.alert("Failed to create drafting view.", title="Import Table Error")

if __name__ == "__main__":
    main()