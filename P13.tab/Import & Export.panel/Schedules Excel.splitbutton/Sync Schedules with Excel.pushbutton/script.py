# -*- coding: utf-8 -*-
"""
P13 Sync Schedules with Excel  |  v3.1  |  Revit 2026 Compatible
=================================================================
ใช้ openpyxl_loader.py สำหรับโหลด openpyxl ผ่าน CPython อัตโนมัติ

วิธีติดตั้ง:
  1. วาง openpyxl_loader.py ไว้ใน _schedule_excel_lib/
  2. ติดตั้ง Python (CPython) จาก https://python.org
  3. script จะติดตั้ง openpyxl ให้อัตโนมัติครั้งแรก
"""
from __future__ import print_function

__title__  = "Sync Schedules\nwith Excel"
__doc__    = "Sync P13/MLABS schedule Excel files with the current Revit model."
__author__ = "P13"

import os
import sys
import shutil
import datetime
import traceback

import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System")
from System.Windows.Forms import OpenFileDialog, DialogResult
import System

from pyrevit import revit, DB, forms, script

doc = revit.doc

# ─────────────────────────────────────────────────────────────
# โหลด openpyxl ผ่าน loader (รองรับ CPython fallback)
# ─────────────────────────────────────────────────────────────
LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "_schedule_excel_lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

# โหลด loader และ openpyxl
_bridge = None  # ใช้ถ้า Approach A ล้มเหลว

try:
    from openpyxl_loader import load_openpyxl, get_subprocess_bridge
    try:
        openpyxl = load_openpyxl(auto_install=True)
        _USE_BRIDGE = False
        print("[script] โหลด openpyxl สำเร็จ (direct import)")
    except RuntimeError:
        # Approach A ล้มเหลว ใช้ subprocess bridge
        _bridge = get_subprocess_bridge(auto_install=True)
        _USE_BRIDGE = True
        print("[script] ใช้ Subprocess Bridge สำหรับ Excel")
except ImportError:
    forms.alert(
        "ไม่พบ openpyxl_loader.py\n\n"
        "กรุณาวาง openpyxl_loader.py ใน:\n{}".format(LIB_DIR),
        title="Missing Loader",
        exitscript=True,
    )


# ─────────────────────────────────────────────────────────────
# EXCEL READ / WRITE  (unified API รองรับทั้ง 2 mode)
# ─────────────────────────────────────────────────────────────
def read_xlsx(path):
    """อ่าน xlsx คืน dict{ sheet_name: [[values]] }"""
    if _USE_BRIDGE:
        return _bridge.read_xlsx(path)
    wb = openpyxl.load_workbook(path, data_only=True)
    result = {}
    for name in wb.sheetnames:
        ws = wb[name]
        result[name] = [list(row) for row in ws.iter_rows(values_only=True)]
    wb.close()
    return result


def write_xlsx(path, sheets_data):
    """เขียน xlsx โดย preserve formatting"""
    if _USE_BRIDGE:
        _bridge.write_xlsx(path, sheets_data)
        return
    wb = openpyxl.load_workbook(path)
    for sheet_info in sheets_data:
        name = sheet_info["name"]
        rows = sheet_info["rows"]
        if name not in wb.sheetnames:
            continue
        ws = wb[name]
        for r_idx, row_data in enumerate(rows):
            for c_idx, value in enumerate(row_data):
                ws.cell(row=r_idx + 1, column=c_idx + 1).value = (
                    value if value != "" else None
                )
    wb.save(path)
    wb.close()


# ─────────────────────────────────────────────────────────────
# HELPER UTILITIES
# ─────────────────────────────────────────────────────────────
def to_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].lstrip("-").isdigit():
        return text[:-2]
    return text


def get_element_id_value(eid):
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def make_element_id(int_val):
    try:
        return DB.ElementId(System.Int64(int_val))
    except Exception:
        return DB.ElementId(int(int_val))


def normalize_row(row, size):
    row = list(row)
    while len(row) < size:
        row.append("")
    return row


def safe_float(text):
    digits = "".join(c for c in text if c.isdigit() or c in ".-")
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def backup_excel(path):
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.splitext(path)[0] + "_backup_{}.xlsx".format(ts)
    shutil.copy2(path, dest)
    return dest


# ─────────────────────────────────────────────────────────────
# MLABS FORMAT PARSER
# ─────────────────────────────────────────────────────────────
def parse_mlabs_metadata(rows):
    if len(rows) < 8:
        return {}
    row0, row1, row4, row5, row7 = rows[0], rows[1], rows[4], rows[5], rows[7]
    headers = [to_text(h) for h in row7]
    meta = {}
    for col in range(1, len(headers)):
        pname = to_text(row0[col]) if col < len(row0) else ""
        if not pname or pname.lower() in ("", "mlabs"):
            continue
        pid     = to_text(row1[col]) if col < len(row1) else ""
        storage = to_text(row4[col]) if col < len(row4) else "String"
        mod     = to_text(row5[col]) if col < len(row5) else ""
        meta[col] = {
            "header"         : headers[col],
            "parameter_id"   : pid,
            "parameter_name" : pname,
            "writable"       : "1" if "Modifiable" in mod else "0",
            "storage"        : storage,
        }
    return meta


# ─────────────────────────────────────────────────────────────
# REVIT PARAMETER UTILITIES
# ─────────────────────────────────────────────────────────────
def get_revit_element(id_text):
    try:
        clean = to_text(id_text)
        if not clean or not clean.lstrip("-").isdigit():
            return None
        return doc.GetElement(make_element_id(int(clean)))
    except Exception:
        return None


def find_parameter(element, pid, pname):
    if element is None:
        return None
    if pid and len(pid) == 36:
        try:
            param = element.get_Parameter(System.Guid(pid))
            if param is not None:
                return param
        except Exception:
            pass
    if pid:
        try:
            bip = getattr(DB.BuiltInParameter, pid.upper(), None)
            if bip is not None:
                param = element.get_Parameter(bip)
                if param is not None:
                    return param
        except Exception:
            pass
    if pname:
        param = element.LookupParameter(pname)
        if param is not None:
            return param
    if pname:
        for p in element.Parameters:
            if p.Definition and p.Definition.Name == pname:
                return p
    return None


def parameter_to_text(param):
    if param is None or not param.HasValue:
        return ""
    storage = param.StorageType
    if storage == DB.StorageType.String:
        return param.AsString() or ""
    if storage == DB.StorageType.Integer:
        try:
            if param.Definition.GetDataType() == DB.SpecTypeId.Boolean.YesNo:
                return "Yes" if param.AsInteger() == 1 else "No"
        except Exception:
            pass
        return str(param.AsInteger())
    if storage == DB.StorageType.Double:
        try:
            unit_id   = param.GetUnitTypeId()
            converted = DB.UnitUtils.ConvertFromInternalUnits(param.AsDouble(), unit_id)
            return "{:.6f}".format(converted).rstrip("0").rstrip(".")
        except Exception:
            return "{:.6f}".format(param.AsDouble()).rstrip("0").rstrip(".")
    if storage == DB.StorageType.ElementId:
        eid = param.AsElementId()
        if eid == DB.ElementId.InvalidElementId:
            return ""
        linked = doc.GetElement(eid)
        if linked:
            try:
                return linked.Name
            except Exception:
                return str(get_element_id_value(eid))
        return str(get_element_id_value(eid))
    return param.AsValueString() or ""


def set_parameter_from_text(param, value_text, meta=None):
    if param is None:
        return False, "Parameter is None"
    if param.IsReadOnly:
        return False, "Parameter is read-only"
    storage    = param.StorageType
    value_text = (value_text or "").strip()
    try:
        if storage == DB.StorageType.String:
            param.Set(value_text)
            return True, "OK"
        if storage == DB.StorageType.Integer:
            lo = value_text.lower()
            if lo in ("yes", "true", "1"):
                param.Set(1)
            elif lo in ("no", "false", "0", ""):
                param.Set(0)
            else:
                num = safe_float(value_text)
                if num is None:
                    return False, "Cannot parse integer: '{}'".format(value_text)
                param.Set(int(num))
            return True, "OK"
        if storage == DB.StorageType.Double:
            num = safe_float(value_text)
            if num is None:
                return False, "Cannot parse number: '{}'".format(value_text)
            try:
                unit_id = param.GetUnitTypeId()
                param.Set(DB.UnitUtils.ConvertToInternalUnits(num, unit_id))
            except Exception:
                param.Set(num)
            return True, "OK"
        if storage == DB.StorageType.ElementId:
            if not value_text or value_text.lower() in ("none", "invalid", "-1", ""):
                param.Set(DB.ElementId.InvalidElementId)
            else:
                num = safe_float(value_text)
                if num is None:
                    return False, "Cannot parse ElementId: '{}'".format(value_text)
                param.Set(make_element_id(int(num)))
            return True, "OK"
        return False, "Unsupported StorageType: {}".format(storage)
    except Exception as exc:
        return False, str(exc)


def values_match(cur, new, storage_type):
    if cur.strip() == new.strip():
        return True
    if storage_type in (DB.StorageType.Double, DB.StorageType.Integer):
        a, b = safe_float(cur), safe_float(new)
        if a is not None and b is not None:
            return abs(a - b) < 0.001
    return False


# ─────────────────────────────────────────────────────────────
# FAILURE PREPROCESSOR
# ─────────────────────────────────────────────────────────────
class SilentWarningPreprocessor(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, accessor):
        for msg in accessor.GetFailureMessages():
            if msg.GetSeverity() == DB.FailureSeverity.Warning:
                accessor.DeleteWarning(msg)
        return DB.PreprocessorResult.Continue


# ─────────────────────────────────────────────────────────────
# FILE PICKER
# ─────────────────────────────────────────────────────────────
def pick_excel_file():
    dlg        = OpenFileDialog()
    dlg.Title  = "เลือกไฟล์ Excel (MLABS/P13 Format)"
    dlg.Filter = "Excel Files (*.xlsx)|*.xlsx"
    if dlg.ShowDialog() == DialogResult.OK:
        return dlg.FileName
    return None


# ─────────────────────────────────────────────────────────────
# EXCEL -> REVIT
# ─────────────────────────────────────────────────────────────
def build_preview(data_sheets):
    changes, errors = [], []
    stats = {
        "total_rows": 0, "changed": 0, "unchanged": 0,
        "missing_elem": 0, "readonly": 0,
        "export_only": 0, "invalid_param": 0,
    }
    for sheet_name, rows in data_sheets.items():
        if len(rows) < 9:
            continue
        meta = parse_mlabs_metadata(rows)
        if not meta:
            continue
        headers = [to_text(h) for h in rows[7]]
        id_col  = headers.index("ElementId") if "ElementId" in headers else 0
        for raw_row in rows[8:]:
            row     = normalize_row(raw_row, len(headers))
            id_text = to_text(row[id_col])
            if not id_text or not id_text.lstrip("-").isdigit():
                continue
            stats["total_rows"] += 1
            element = get_revit_element(id_text)
            if element is None:
                stats["missing_elem"] += 1
                errors.append([sheet_name, id_text, "-", "Element not found"])
                continue
            eid_str = str(get_element_id_value(element.Id))
            for col, m in meta.items():
                if col >= len(row):
                    continue
                if m["writable"] != "1":
                    stats["export_only"] += 1
                    continue
                new_val = to_text(row[col])
                param   = find_parameter(element, m["parameter_id"], m["parameter_name"])
                if param is None:
                    stats["invalid_param"] += 1
                    errors.append([sheet_name, eid_str, m["parameter_name"], "Parameter not found"])
                    continue
                if param.IsReadOnly:
                    stats["readonly"] += 1
                    continue
                cur_val = parameter_to_text(param)
                if values_match(cur_val, new_val, param.StorageType):
                    stats["unchanged"] += 1
                    continue
                changes.append({
                    "sheet"          : sheet_name,
                    "element"        : element,
                    "element_id"     : eid_str,
                    "parameter"      : param,
                    "parameter_name" : m["parameter_name"],
                    "old_value"      : cur_val,
                    "new_value"      : new_val,
                    "meta"           : m,
                })
                stats["changed"] += 1
    return changes, stats, errors


def print_preview(changes, stats, errors):
    out = script.get_output()
    out.print_md("# 📊 Excel → Revit  |  Preview")
    out.print_table(
        table_data=[
            ["🔍 แถวที่สแกน",              stats["total_rows"]],
            ["✅ ค่าที่จะอัปเดต",           stats["changed"]],
            ["⏭️  ตรงกันแล้ว (ข้าม)",       stats["unchanged"]],
            ["❓ ไม่พบ Element",             stats["missing_elem"]],
            ["🔒 Read-only (ข้าม)",         stats["readonly"]],
            ["⬆️  Export-only (ข้าม)",      stats["export_only"]],
            ["⚠️  ไม่พบ Parameter",          stats["invalid_param"]],
        ],
        columns=["สถานะ", "จำนวน"],
    )
    if changes:
        out.print_md("## 🔄 รายการที่จะเปลี่ยน (แสดง 50 จาก {})".format(len(changes)))
        out.print_table(
            [[c["sheet"], c["element_id"], c["parameter_name"], c["old_value"], c["new_value"]]
             for c in changes[:50]],
            columns=["Sheet", "ElementId", "Parameter", "ค่าปัจจุบัน", "ค่าใหม่"],
        )
    if errors:
        out.print_md("## ⚠️ ปัญหาที่พบ (แสดง 20 รายการ)")
        out.print_table(errors[:20], columns=["Sheet", "ElementId", "Parameter", "ปัญหา"])


def apply_to_revit(changes):
    result      = {"success": 0, "failed": 0}
    failed_rows = []
    tx = DB.Transaction(doc, "P13 Sync: Excel -> Revit")
    try:
        tx.Start()
        fail_opts = tx.GetFailureHandlingOptions()
        fail_opts.SetFailuresPreprocessor(SilentWarningPreprocessor())
        tx.SetFailureHandlingOptions(fail_opts)
        for item in changes:
            try:
                ok, msg = set_parameter_from_text(item["parameter"], item["new_value"], item["meta"])
                if ok:
                    result["success"] += 1
                else:
                    result["failed"] += 1
                    failed_rows.append([item["element_id"], item["parameter_name"], msg])
            except Exception as exc:
                result["failed"] += 1
                failed_rows.append([item["element_id"], item["parameter_name"], str(exc)])
        tx.Commit()
    except Exception as tx_exc:
        try:
            if tx.IsValidObject and tx.HasStarted() and not tx.HasEnded():
                tx.RollBack()
        except Exception:
            pass
        forms.alert("❌ Transaction ล้มเหลว:\n{}".format(tx_exc), title="Sync Error")
    return result, failed_rows


def print_result(result, failed_rows):
    out = script.get_output()
    out.print_md("# ✅ ผลลัพธ์ Excel → Revit")
    out.print_table(
        [["✅ สำเร็จ", result["success"]], ["❌ ล้มเหลว", result["failed"]]],
        columns=["สถานะ", "จำนวน"],
    )
    if failed_rows:
        out.print_md("## ❌ รายการที่ล้มเหลว")
        out.print_table(failed_rows[:50], columns=["ElementId", "Parameter", "สาเหตุ"])


# ─────────────────────────────────────────────────────────────
# REVIT -> EXCEL
# ─────────────────────────────────────────────────────────────
def sync_to_excel(path, data_sheets):
    changes_count  = 0
    updated_sheets = []
    for sheet_name, rows in data_sheets.items():
        if len(rows) < 9:
            updated_sheets.append({"name": sheet_name, "rows": rows})
            continue
        meta     = parse_mlabs_metadata(rows)
        headers  = [to_text(h) for h in rows[7]]
        id_col   = headers.index("ElementId") if "ElementId" in headers else 0
        new_rows = [list(r) for r in rows[:8]]
        for raw_row in rows[8:]:
            row     = normalize_row(raw_row, len(headers))
            id_text = to_text(row[id_col])
            element = get_revit_element(id_text) if id_text.lstrip("-").isdigit() else None
            if element:
                for col, m in meta.items():
                    if col >= len(row):
                        continue
                    param = find_parameter(element, m["parameter_id"], m["parameter_name"])
                    if param:
                        new_val = parameter_to_text(param)
                        if to_text(row[col]) != new_val:
                            row[col] = new_val
                            changes_count += 1
            new_rows.append(row)
        updated_sheets.append({"name": sheet_name, "rows": new_rows})

    try:
        backup_path = backup_excel(path)
    except Exception:
        backup_path = None

    try:
        write_xlsx(path, updated_sheets)
        msg = "✅ Revit → Excel sync สำเร็จ!\n\nอัปเดต {} ค่า\nไฟล์: {}".format(
            changes_count, os.path.basename(path)
        )
        if backup_path:
            msg += "\n\nBackup: {}".format(os.path.basename(backup_path))
        forms.alert(msg, title="Sync Complete")
    except Exception as exc:
        forms.alert(
            "❌ เขียนไฟล์ Excel ไม่ได้\nปิดไฟล์ใน Excel ก่อนแล้วลองใหม่\n\nError: {}".format(exc),
            title="Write Error",
        )


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def main():
    path = pick_excel_file()
    if not path:
        script.exit()

    direction = forms.CommandSwitchWindow.show(
        [
            "Excel  ->  Revit   (นำ Excel มาอัปเดตโมเดล)",
            "Revit  ->  Excel   (ส่งข้อมูลโมเดลกลับ Excel)",
        ],
        message="เลือกทิศทางการ Sync ข้อมูล",
    )
    if not direction:
        script.exit()

    try:
        data_sheets = read_xlsx(path)
    except Exception as exc:
        forms.alert(
            "❌ อ่านไฟล์ไม่ได้:\n{}\n\nError: {}".format(os.path.basename(path), exc),
            title="File Error",
            exitscript=True,
        )
        return

    # ══  REVIT -> EXCEL  ══════════════════════════════════
    if "Revit" in direction and direction.index("Revit") < direction.index("Excel"):
        confirm = forms.alert(
            "จะเขียนทับ Excel ด้วยข้อมูลล่าสุดจากโมเดล\n\n"
            "ไฟล์: {}\n\nระบบจะสำรอง backup อัตโนมัติ\nดำเนินการต่อ?".format(
                os.path.basename(path)
            ),
            title="ยืนยัน Revit → Excel",
            options=["ดำเนินการ", "ยกเลิก"],
        )
        if confirm != "ดำเนินการ":
            return
        sync_to_excel(path, data_sheets)
        # cleanup bridge ถ้าใช้
        if _USE_BRIDGE and _bridge:
            _bridge.cleanup()
        return

    # ══  EXCEL -> REVIT  ══════════════════════════════════
    changes, stats, errors = build_preview(data_sheets)
    print_preview(changes, stats, errors)

    if not changes:
        forms.alert("✅ โมเดลตรงกับ Excel แล้ว ไม่มีอะไรต้องอัปเดต", title="Already in Sync")
        return

    confirm = forms.alert(
        "พบ {} ค่าที่ต้องอัปเดต\n\n"
        "ไม่พบ Element: {}\nปัญหา Parameter: {}\n\n"
        "Apply การเปลี่ยนแปลงหรือไม่?".format(
            stats["changed"], stats["missing_elem"], stats["invalid_param"]
        ),
        title="ยืนยัน Excel → Revit",
        options=["Apply", "ยกเลิก"],
    )
    if confirm != "Apply":
        return

    result, failed_rows = apply_to_revit(changes)
    print_result(result, failed_rows)
    forms.alert(
        "✅ Sync เสร็จสิ้น!\n\nสำเร็จ: {}\nล้มเหลว: {}".format(
            result["success"], result["failed"]
        ),
        title="Sync Done",
    )

    if _USE_BRIDGE and _bridge:
        _bridge.cleanup()


if __name__ == "__main__":
    main()
