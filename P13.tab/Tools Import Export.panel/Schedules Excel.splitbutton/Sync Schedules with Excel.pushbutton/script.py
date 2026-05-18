# -*- coding: utf-8 -*-
from __future__ import print_function

__title__ = "Sync Schedules\nwith Excel"
__doc__ = "Sync P13 schedule Excel files with the current Revit model in a controlled direction (MLABS Format)."
__author__ = "P13"

import os
import sys
import clr
clr.AddReference("System.Windows.Forms")
from System.Windows.Forms import OpenFileDialog, DialogResult

from pyrevit import revit, DB, forms, script

# --- Library Setup ---
LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "_schedule_excel_lib")

# 🌟 บังคับแทรกเข้าคิวแรกสุด (index 0) และล้าง Cache เหมือนปุ่มอื่นๆ
while LIB_DIR in sys.path:
    sys.path.remove(LIB_DIR)
sys.path.insert(0, LIB_DIR)

if "p13_excel_v2" in sys.modules:
    del sys.modules["p13_excel_v2"]

# ใช้ไฟล์ไลบรารีชื่อใหม่ล่าสุด
import p13_excel_v2 as sx

doc = revit.doc

def pick_schedule_file():
    dialog = OpenFileDialog()
    dialog.Title = "Select MLABS/P13 Schedule Excel File to Sync"
    dialog.Filter = "Excel Files (*.xlsx)|*.xlsx" # แนะนำให้ใช้ XLSX สำหรับ Sync
    if dialog.ShowDialog() == DialogResult.OK:
        return dialog.FileName
    return None

def normalize_row(row, size):
    values = list(row)
    while len(values) < size: values.append("")
    return values

def parse_mlabs_metadata(rows):
    if len(rows) < 8: return {}
    headers = [sx.to_text(h).strip() for h in rows[7]]
    meta = {}
    
    for col_idx in range(1, len(headers)):
        if col_idx >= len(rows[0]): break
        pname = sx.to_text(rows[0][col_idx]).strip()
        if not pname or pname == "" or pname == "MLabs": continue
        
        pid = sx.to_text(rows[1][col_idx]).strip() if len(rows[1]) > col_idx else ""
        if pid.endswith(".0"): pid = pid[:-2]
            
        mod = sx.to_text(rows[5][col_idx]).strip() if len(rows[5]) > col_idx else ""
        storage = sx.to_text(rows[4][col_idx]).strip() if len(rows[4]) > col_idx else "String"

        meta[col_idx] = {
            "header": headers[col_idx] if col_idx < len(headers) else pname,
            "parameter_id": pid, "parameter_name": pname,
            "writable": "1" if "Modifiable" in mod else "0", "storage": storage,
        }
    return meta

def get_element(element_id_text):
    try:
        clean_id = sx.to_text(element_id_text).strip()
        if clean_id.endswith(".0"): clean_id = clean_id[:-2]
        element_id = DB.ElementId(int(float(clean_id)))
        return doc.GetElement(element_id)
    except Exception: return None

# =======================================================
# 1. ทิศทาง: EXCEL -> REVIT (ดึงจาก Excel มาอัปเดตโมเดล)
# =======================================================
def build_excel_to_revit_preview(data_sheets):
    changes, errors = [], []
    stats = {"changed": 0, "unchanged": 0, "missing": 0, "readonly": 0, "invalid": 0, "export_only": 0, "total_rows": 0}

    for sheet_name, rows in data_sheets.items():
        if len(rows) < 9: continue 

        sheet_meta = parse_mlabs_metadata(rows)
        if not sheet_meta: continue
        
        headers = [sx.to_text(h).strip() for h in rows[7]]
        data_rows = rows[8:] 

        id_col_idx = 0
        if "ElementId" in headers: id_col_idx = headers.index("ElementId")

        for raw_row in data_rows:
            row = normalize_row(raw_row, len(headers))
            
            e_id_text = sx.to_text(row[id_col_idx]).strip()
            if e_id_text.endswith(".0"): e_id_text = e_id_text[:-2]
            if not e_id_text or not e_id_text.isdigit(): continue

            stats["total_rows"] += 1
            element = get_element(e_id_text)
            if element is None:
                stats["missing"] += 1
                continue

            for col_idx, meta in sheet_meta.items():
                if col_idx >= len(row): continue
                new_value = sx.to_text(row[col_idx]).strip()

                if meta.get("writable", "0") != "1":
                    stats["export_only"] += 1
                    continue

                parameter = sx.find_parameter(element, meta.get("parameter_id", ""), meta.get("parameter_name", ""), doc)
                if parameter is None:
                    stats["invalid"] += 1
                    errors.append([sheet_name, sx.get_id_value(element.Id), meta.get("parameter_name", ""), "Parameter not found"])
                    continue
                if parameter.IsReadOnly:
                    stats["readonly"] += 1
                    continue

                current_val = sx.parameter_to_text(parameter, doc)
                
                c_val_clean = current_val.split(" ")[0].strip()
                n_val_clean = new_value.split(" ")[0].strip()
                
                is_match = (c_val_clean == n_val_clean)
                if not is_match and parameter.StorageType in (DB.StorageType.Double, DB.StorageType.Integer):
                    try:
                        n1 = float(''.join(c for c in c_val_clean if c.isdigit() or c in '.-'))
                        n2 = float(''.join(c for c in n_val_clean if c.isdigit() or c in '.-'))
                        is_match = (abs(n1 - n2) < 0.001)
                    except: pass

                if is_match:
                    stats["unchanged"] += 1
                    continue

                changes.append({
                    "sheet": sheet_name, "element": element, "element_id": sx.get_id_value(element.Id),
                    "parameter": parameter, "parameter_name": meta.get("parameter_name", ""),
                    "old_value": current_val, "new_value": new_value, "meta": meta
                })
                stats["changed"] += 1
    return changes, stats, errors

def print_excel_to_revit_preview(changes, stats, errors):
    output = script.get_output()
    output.print_md("# Excel -> Revit Sync Preview")
    output.print_table(
        table_data=[
            ["Rows checked", stats["total_rows"]], ["Values to update", stats["changed"]],
            ["Unchanged values", stats["unchanged"]], ["Missing elements", stats["missing"]],
            ["Read-only parameters", stats["readonly"]], ["Export-only columns skipped", stats["export_only"]],
            ["Invalid values or missing parameters", stats["invalid"]]
        ],
        columns=["Status", "Count"]
    )
    if changes:
        preview_rows = [[item["sheet"], str(item["element_id"]), item["parameter_name"], item["old_value"], item["new_value"]] for item in changes[:50]]
        output.print_md("## First 50 Changes")
        output.print_table(preview_rows, columns=["Sheet", "ElementId", "Parameter", "Old", "New"])
    if errors:
        output.print_md("## First 20 Issues")
        output.print_table(errors[:20], columns=["Sheet", "ElementId", "Parameter", "Issue"])

def apply_excel_to_revit(changes):
    result = {"success": 0, "failed": 0}
    failed = []
    
    tx = DB.Transaction(doc, "P13 Sync Excel -> Revit")
    try:
        tx.Start()
        # ข้ามหน้าต่างแจ้งเตือน
        options = tx.GetFailureHandlingOptions()
        options.SetForcedModalHandling_Status(False)
        tx.SetFailureHandlingOptions(options)
        
        for item in changes:
            try:
                ok, message = sx.set_parameter_from_text(item["parameter"], item["new_value"], item["meta"])
                if ok: result["success"] += 1
                else:
                    result["failed"] += 1
                    failed.append([item["element_id"], item["parameter_name"], message])
            except Exception as exc:
                result["failed"] += 1
                failed.append([item["element_id"], item["parameter_name"], str(exc)])
        tx.Commit()
    except Exception as tx_exc:
        if tx.IsValidObject and tx.HasStarted() and not tx.HasEnded(): tx.RollBack()
        forms.alert("Transaction Failed: {}".format(tx_exc))
    return result, failed

# =======================================================
# 2. ทิศทาง: REVIT -> EXCEL (ดึงจากโมเดลไปอัปเดตไฟล์ Excel)
# =======================================================
def sync_revit_to_excel(path, data_sheets):
    changes_count = 0
    updated_sheets = []
    
    for sheet_name, rows in data_sheets.items():
        if len(rows) < 9: 
            updated_sheets.append({"name": sheet_name, "rows": rows})
            continue
        
        sheet_meta = parse_mlabs_metadata(rows)
        headers = [sx.to_text(h).strip() for h in rows[7]]
        id_col_idx = headers.index("ElementId") if "ElementId" in headers else 0

        # เก็บ 8 บรรทัดแรกไว้ (MLABS Headers + Data Headers)
        new_rows = rows[:8] 
        
        for raw_row in rows[8:]:
            row = normalize_row(raw_row, len(headers))
            e_id_text = sx.to_text(row[id_col_idx]).strip()
            if e_id_text.endswith(".0"): e_id_text = e_id_text[:-2]
            
            element = get_element(e_id_text) if e_id_text.isdigit() else None
            
            # ถ้าเจอ Element ตัวนี้ในโมเดล ให้ดึงค่าล่าสุดไปทับใน Excel
            if element:
                for col_idx, meta in sheet_meta.items():
                    if col_idx >= len(row): continue
                    
                    parameter = sx.find_parameter(element, meta.get("parameter_id", ""), meta.get("parameter_name", ""), doc)
                    if parameter:
                        new_val = sx.parameter_to_text(parameter, doc)
                        if row[col_idx] != new_val:
                            row[col_idx] = new_val
                            changes_count += 1
                            
            new_rows.append(row)
        updated_sheets.append({"name": sheet_name, "rows": new_rows})
        
    try:
        sx.write_xlsx(path, updated_sheets)
        forms.alert("Revit -> Excel Sync complete.\nUpdated {} value(s) in Excel.".format(changes_count), title="Sync Schedules")
    except Exception as exc:
        forms.alert("Failed to write Excel file (Please close the file if it is open).\nError: {}".format(exc), title="Sync Error")

# =======================================================
# MAIN
# =======================================================
def main():
    path = pick_schedule_file()
    if not path: script.exit()

    direction = forms.CommandSwitchWindow.show(
        ["Excel -> Revit", "Revit -> Excel"],
        message="Choose sync direction (เลือกทิศทางการ Sync ข้อมูล)"
    )
    if not direction: script.exit()

    try: 
        data_sheets = sx.read_xlsx(path)
    except Exception as exc: 
        forms.alert("Could not read sync file:\n{}".format(exc), title="Schedule Sync", exitscript=True)

    # กรณีเลือกทิศทางโยนข้อมูลจาก Revit ไปทับใน Excel
    if direction == "Revit -> Excel":
        sync_revit_to_excel(path, data_sheets)
        return

    # กรณีเลือกทิศทางดึงข้อมูลจาก Excel มาทับใน Revit
    changes, stats, errors = build_excel_to_revit_preview(data_sheets)
    print_excel_to_revit_preview(changes, stats, errors)

    if not changes:
        forms.alert("No writable Excel changes were found.", title="Schedule Sync")
        return

    answer = forms.alert(
        "Preview found {} value(s) to update in Revit.\n\nApply these Excel values to the current model?".format(len(changes)),
        title="Confirm Schedule Sync", options=["Apply", "Cancel"]
    )
    if answer != "Apply": return

    result, failed = apply_excel_to_revit(changes)
    
    output = script.get_output()
    output.print_md("## Sync Result")
    output.print_table(table_data=[["Updated", result["success"]], ["Failed", result["failed"]]], columns=["Status", "Count"])
    if failed: output.print_table(failed[:50], columns=["ElementId", "Parameter", "Issue"])
    forms.alert("Sync complete.\nUpdated: {}\nFailed: {}".format(result["success"], result["failed"]), title="Schedule Sync")

if __name__ == "__main__":
    main()