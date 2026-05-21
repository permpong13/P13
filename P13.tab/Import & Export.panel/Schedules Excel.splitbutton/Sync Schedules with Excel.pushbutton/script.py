# -*- coding: utf-8 -*-
from __future__ import print_function

__title__ = "Sync Schedules\nwith Excel"
__doc__ = "Sync P13/MLABS schedule Excel or CSV files with the current Revit model."
__author__ = "P13"

import datetime
import os
import shutil
import sys

import clr
clr.AddReference("System.Windows.Forms")
from System.Windows.Forms import OpenFileDialog, DialogResult

from pyrevit import revit, DB, forms, script

LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "_schedule_excel_lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

import p13_excel_v2 as sx

doc = revit.doc


class SilentWarningPreprocessor(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, failures_accessor):
        for failure in failures_accessor.GetFailureMessages():
            if failure.GetSeverity() == DB.FailureSeverity.Warning:
                failures_accessor.DeleteWarning(failure)
        return DB.FailureProcessingResult.Continue


class ExcelIO(object):
    def __init__(self):
        self.openpyxl = None
        self.bridge = None
        self.use_bridge = False

        try:
            from openpyxl_loader import load_openpyxl, get_subprocess_bridge
            try:
                self.openpyxl = load_openpyxl(auto_install=True)
                print("[sync] Loaded openpyxl directly.")
            except RuntimeError:
                self.bridge = get_subprocess_bridge(auto_install=True)
                self.use_bridge = True
                print("[sync] Using the CPython Excel bridge.")
        except Exception:
            print("[sync] Using the native XLSX engine.")

    def read_xlsx(self, path):
        if self.use_bridge and self.bridge:
            return self.bridge.read_xlsx(path)
        if self.openpyxl:
            workbook = self.openpyxl.load_workbook(path, data_only=True)
            data = {}
            for sheet_name in workbook.sheetnames:
                worksheet = workbook[sheet_name]
                data[sheet_name] = [list(row) for row in worksheet.iter_rows(values_only=True)]
            workbook.close()
            return data
        return sx.read_xlsx(path)

    def write_xlsx(self, path, sheets_data):
        if self.use_bridge and self.bridge:
            self.bridge.write_xlsx(path, sheets_data)
            return
        if self.openpyxl:
            workbook = self.openpyxl.load_workbook(path)
            for sheet_info in sheets_data:
                sheet_name = sheet_info["name"]
                if sheet_name not in workbook.sheetnames:
                    continue
                worksheet = workbook[sheet_name]
                for row_idx, row_data in enumerate(sheet_info["rows"]):
                    for col_idx, value in enumerate(row_data):
                        worksheet.cell(row=row_idx + 1, column=col_idx + 1).value = value if value != "" else None
            workbook.save(path)
            workbook.close()
            return
        sx.write_xlsx(path, sheets_data)

    def cleanup(self):
        if self.bridge:
            self.bridge.cleanup()


def to_text(value):
    text = sx.to_text(value).strip()
    if text.endswith(".0") and text[:-2].lstrip("-").isdigit():
        return text[:-2]
    return text


def normalize_row(row, size):
    values = list(row)
    while len(values) < size:
        values.append("")
    return values


def pick_schedule_file():
    dialog = OpenFileDialog()
    dialog.Title = "Select P13 Schedule Excel or CSV File"
    dialog.Filter = "Excel or CSV Files (*.xlsx;*.csv)|*.xlsx;*.csv|Excel Files (*.xlsx)|*.xlsx|CSV Files (*.csv)|*.csv"
    if dialog.ShowDialog() == DialogResult.OK:
        return dialog.FileName
    return None


def backup_file(path):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    root, ext = os.path.splitext(path)
    backup_path = "{}_backup_{}{}".format(root, timestamp, ext)
    shutil.copy2(path, backup_path)
    return backup_path


def read_source(path, excel_io):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        return excel_io.read_xlsx(path)
    if ext == ".csv":
        sheet_name = os.path.splitext(os.path.basename(path))[0]
        return {sheet_name: sx.read_csv(path)}
    raise Exception("Unsupported file type: {}".format(ext))


def write_source(path, sheets_data, excel_io):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        excel_io.write_xlsx(path, sheets_data)
        return
    if ext == ".csv":
        if not sheets_data:
            return
        sx.write_csv(path, sheets_data[0]["rows"])
        return
    raise Exception("Unsupported file type: {}".format(ext))


def parse_mlabs_metadata(rows):
    if len(rows) < 8:
        return {}

    headers = [to_text(header) for header in rows[7]]
    metadata = {}
    for col_idx in range(1, len(headers)):
        parameter_name = to_text(rows[0][col_idx]) if col_idx < len(rows[0]) else ""
        if not parameter_name or parameter_name.lower() == "mlabs":
            continue

        parameter_id = to_text(rows[1][col_idx]) if len(rows[1]) > col_idx else ""
        if parameter_id.endswith(".0"):
            parameter_id = parameter_id[:-2]

        storage = to_text(rows[4][col_idx]) if len(rows[4]) > col_idx else "String"
        modifiable = to_text(rows[5][col_idx]) if len(rows[5]) > col_idx else ""
        metadata[col_idx] = {
            "header": headers[col_idx],
            "parameter_id": parameter_id,
            "parameter_name": parameter_name,
            "writable": "1" if "Modifiable" in modifiable else "0",
            "storage": storage,
        }
    return metadata


def get_revit_element(element_id_text):
    try:
        clean_id = to_text(element_id_text)
        if clean_id.endswith(".0"):
            clean_id = clean_id[:-2]
        if not clean_id or not clean_id.lstrip("-").isdigit():
            return None
        return doc.GetElement(sx.make_element_id(int(clean_id)))
    except Exception:
        return None


def safe_float(text):
    digits = "".join(c for c in to_text(text) if c.isdigit() or c in ".-")
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def values_match(current_value, new_value, storage_type):
    current_clean = to_text(current_value).split(" ")[0].strip()
    new_clean = to_text(new_value).split(" ")[0].strip()
    if current_clean == new_clean:
        return True

    if storage_type in (DB.StorageType.Double, DB.StorageType.Integer):
        current_num = safe_float(current_clean)
        new_num = safe_float(new_clean)
        if current_num is not None and new_num is not None:
            return abs(current_num - new_num) < 0.001

    return False


def build_preview(data_sheets):
    changes = []
    errors = []
    stats = {
        "sheets_read": len(data_sheets),
        "sheets_with_metadata": 0,
        "total_rows": 0,
        "changed": 0,
        "unchanged": 0,
        "missing_elem": 0,
        "readonly": 0,
        "export_only": 0,
        "invalid_param": 0,
    }

    for sheet_name, rows in data_sheets.items():
        if len(rows) < 9:
            continue

        metadata = parse_mlabs_metadata(rows)
        if not metadata:
            continue
        stats["sheets_with_metadata"] += 1

        headers = [to_text(header) for header in rows[7]]
        id_col_idx = headers.index("ElementId") if "ElementId" in headers else 0
        for raw_row in rows[8:]:
            row = normalize_row(raw_row, len(headers))
            element_id_text = to_text(row[id_col_idx])
            if not element_id_text or not element_id_text.lstrip("-").isdigit():
                continue

            stats["total_rows"] += 1
            element = get_revit_element(element_id_text)
            if element is None:
                stats["missing_elem"] += 1
                errors.append([sheet_name, element_id_text, "-", "Element not found"])
                continue

            element_id = str(sx.get_id_value(element.Id))
            for col_idx, meta in metadata.items():
                if col_idx >= len(row):
                    continue
                if meta["writable"] != "1":
                    stats["export_only"] += 1
                    continue

                new_value = to_text(row[col_idx])
                parameter = sx.find_parameter(element, meta["parameter_id"], meta["parameter_name"], doc)
                if parameter is None:
                    stats["invalid_param"] += 1
                    errors.append([sheet_name, element_id, meta["parameter_name"], "Parameter not found"])
                    continue
                if parameter.IsReadOnly:
                    stats["readonly"] += 1
                    continue

                current_value = sx.parameter_to_text(parameter, doc)
                if values_match(current_value, new_value, parameter.StorageType):
                    stats["unchanged"] += 1
                    continue

                changes.append({
                    "sheet": sheet_name,
                    "element": element,
                    "element_id": element_id,
                    "parameter": parameter,
                    "parameter_name": meta["parameter_name"],
                    "old_value": current_value,
                    "new_value": new_value,
                    "meta": meta,
                })
                stats["changed"] += 1

    return changes, stats, errors


def print_preview(changes, stats, errors):
    output = script.get_output()
    output.print_md("# Excel to Revit Preview")
    output.print_table(
        table_data=[
            ["Sheets read", stats["sheets_read"]],
            ["Sheets with P13 metadata", stats["sheets_with_metadata"]],
            ["Rows checked", stats["total_rows"]],
            ["Values to update", stats["changed"]],
            ["Unchanged values", stats["unchanged"]],
            ["Missing elements", stats["missing_elem"]],
            ["Read-only parameters", stats["readonly"]],
            ["Export-only columns skipped", stats["export_only"]],
            ["Missing parameters", stats["invalid_param"]],
        ],
        columns=["Status", "Count"]
    )

    if changes:
        output.print_md("## First 50 Changes")
        output.print_table(
            [[item["sheet"], item["element_id"], item["parameter_name"], item["old_value"], item["new_value"]] for item in changes[:50]],
            columns=["Sheet", "ElementId", "Parameter", "Current Value", "New Value"]
        )

    if errors:
        output.print_md("## First 20 Issues")
        output.print_table(errors[:20], columns=["Sheet", "ElementId", "Parameter", "Issue"])


def apply_to_revit(changes):
    result = {"success": 0, "failed": 0}
    failed_rows = []

    tx = DB.Transaction(doc, "P13 Sync: Excel to Revit")
    try:
        tx.Start()
        options = tx.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(SilentWarningPreprocessor())
        tx.SetFailureHandlingOptions(options)

        for item in changes:
            try:
                ok, message = sx.set_parameter_from_text(item["parameter"], item["new_value"], item["meta"])
                if ok:
                    result["success"] += 1
                else:
                    result["failed"] += 1
                    failed_rows.append([item["element_id"], item["parameter_name"], message])
            except Exception as exc:
                result["failed"] += 1
                failed_rows.append([item["element_id"], item["parameter_name"], str(exc)])

        tx.Commit()
    except Exception as tx_exc:
        if tx.HasStarted() and not tx.HasEnded():
            tx.RollBack()
        forms.alert("Transaction failed:\n{}".format(tx_exc), title="Sync Error")

    return result, failed_rows


def print_result(result, failed_rows):
    output = script.get_output()
    output.print_md("# Excel to Revit Result")
    output.print_table(
        [["Updated", result["success"]], ["Failed", result["failed"]]],
        columns=["Status", "Count"]
    )
    if failed_rows:
        output.print_md("## Failed Updates")
        output.print_table(failed_rows[:50], columns=["ElementId", "Parameter", "Issue"])


def sync_to_file(path, data_sheets, excel_io):
    changes_count = 0
    updated_sheets = []

    for sheet_name, rows in data_sheets.items():
        if len(rows) < 9:
            updated_sheets.append({"name": sheet_name, "rows": rows})
            continue

        metadata = parse_mlabs_metadata(rows)
        headers = [to_text(header) for header in rows[7]]
        id_col_idx = headers.index("ElementId") if "ElementId" in headers else 0
        new_rows = [list(row) for row in rows[:8]]

        for raw_row in rows[8:]:
            row = normalize_row(raw_row, len(headers))
            element_id_text = to_text(row[id_col_idx])
            element = get_revit_element(element_id_text) if element_id_text.lstrip("-").isdigit() else None
            if element:
                for col_idx, meta in metadata.items():
                    if col_idx >= len(row):
                        continue
                    parameter = sx.find_parameter(element, meta["parameter_id"], meta["parameter_name"], doc)
                    if parameter:
                        new_value = sx.parameter_to_text(parameter, doc)
                        if to_text(row[col_idx]) != new_value:
                            row[col_idx] = new_value
                            changes_count += 1
            new_rows.append(row)

        updated_sheets.append({"name": sheet_name, "rows": new_rows})

    backup_path = None
    try:
        backup_path = backup_file(path)
    except Exception:
        pass

    write_source(path, updated_sheets, excel_io)
    return changes_count, backup_path


def main():
    path = pick_schedule_file()
    if not path:
        script.exit()

    excel_io = ExcelIO()
    try:
        direction = forms.CommandSwitchWindow.show(
            ["Excel to Revit", "Revit to Excel"],
            message="Choose sync direction"
        )
        if not direction:
            script.exit()

        try:
            data_sheets = read_source(path, excel_io)
        except Exception as exc:
            forms.alert(
                "Could not read file:\n{}\n\nError: {}".format(os.path.basename(path), exc),
                title="File Error",
                exitscript=True
            )

        if direction == "Revit to Excel":
            confirm = forms.alert(
                "This will overwrite the selected file with current model values.\n\n"
                "File: {}\n\nA backup copy will be created first.".format(os.path.basename(path)),
                title="Confirm Revit to Excel",
                options=["Proceed", "Cancel"]
            )
            if confirm != "Proceed":
                return

            try:
                changes_count, backup_path = sync_to_file(path, data_sheets, excel_io)
            except Exception as exc:
                forms.alert(
                    "Could not write the selected file.\nClose it in Excel and try again.\n\nError: {}".format(exc),
                    title="Write Error"
                )
                return

            message = "Revit to Excel sync complete.\n\nUpdated values: {}\nFile: {}".format(changes_count, os.path.basename(path))
            if backup_path:
                message += "\nBackup: {}".format(os.path.basename(backup_path))
            forms.alert(message, title="Sync Complete")
            return

        changes, stats, errors = build_preview(data_sheets)
        print_preview(changes, stats, errors)

        if stats["sheets_with_metadata"] == 0:
            forms.alert(
                "The selected file was read, but no P13 schedule metadata was found.\n\n"
                "Use a file created by 'Export Schedules to Excel', then try Sync again.",
                title="No P13 Schedule Data"
            )
            return

        if stats["total_rows"] == 0:
            forms.alert(
                "P13 metadata was found, but no ElementId data rows could be read.\n\n"
                "Check that the ElementId column still exists and contains values from the original export.",
                title="No Schedule Rows"
            )
            return

        if not changes:
            forms.alert("The model already matches the selected file. No updates are required.", title="Already in Sync")
            return

        confirm = forms.alert(
            "Found {} value(s) to update.\n\nMissing elements: {}\nMissing parameters: {}\n\nApply these changes?".format(
                stats["changed"], stats["missing_elem"], stats["invalid_param"]
            ),
            title="Confirm Excel to Revit",
            options=["Apply", "Cancel"]
        )
        if confirm != "Apply":
            return

        result, failed_rows = apply_to_revit(changes)
        print_result(result, failed_rows)
        forms.alert(
            "Sync complete.\n\nUpdated: {}\nFailed: {}".format(result["success"], result["failed"]),
            title="Sync Complete"
        )
    finally:
        excel_io.cleanup()


if __name__ == "__main__":
    main()
