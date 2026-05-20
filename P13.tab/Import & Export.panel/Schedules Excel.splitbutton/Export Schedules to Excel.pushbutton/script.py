# -*- coding: utf-8 -*-
from __future__ import print_function

__title__ = "Export Schedules\nto Excel"
__doc__ = "Export selected Revit schedules to XLSX with MLABS format for round-trip import."
__author__ = "P13"

import datetime
import os
import sys

from pyrevit import revit, DB, forms, script

LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "_schedule_excel_lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

# 🌟 เรียกใช้ชื่อไลบรารีใหม่ เพื่อตัดปัญหา Cache ของโปรแกรม Revit ทิ้งไปเลย!
import p13_excel_v2 as sx

doc = revit.doc

class ConfigManager:
    def __init__(self):
        self.cfg = script.get_config("P13ScheduleExcel")

    def get_or_set_export_path(self):
        export_path = getattr(self.cfg, "export_path", "")
        if not export_path or not os.path.exists(export_path):
            export_path = forms.pick_folder(title="Select Export Path (เลือกโฟลเดอร์สำหรับ Export)")
            if not export_path: return None
            self.cfg.export_path = export_path
            script.save_config()
        return export_path

class ScheduleOption(forms.TemplateListItem):
    @property
    def name(self):
        try: itemized = self.item.Definition.IsItemized
        except Exception: itemized = False
        return "{}{}".format(self.item.Name, "" if itemized else " [Grouped - export only]")

class ScheduleDataBuilder:
    @staticmethod
    def collect_valid_schedules():
        schedules = DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule).ToElements()
        valid = []
        for schedule in schedules:
            try:
                if schedule.IsTemplate or schedule.Name.startswith("<"): continue
                valid.append(schedule)
            except Exception: pass
        return sorted(valid, key=lambda x: x.Name.lower())

    @staticmethod
    def build_sheet_data(schedule, used_sheet_names):
        rows, stats, itemized = sx.collect_schedule_rows(doc, schedule)
        sheet_name = sx.safe_sheet_name(schedule.Name, used_sheet_names)
        return {
            "name": sheet_name, "rows": rows, "itemized": itemized,
            "row_count": stats["row_count"], "mapped_rows": stats["mapped_rows"],
            "writable_count": stats["writable_count"], "original_schedule": schedule
        }

class ExportManager:
    def __init__(self, export_path):
        self.export_path = export_path

    @staticmethod
    def print_summary(exported_sheets):
        output = script.get_output()
        output.print_md("# P13 Schedule Export Summary (MLABS Format)")
        table_data = [[item["name"], item["row_count"], item["mapped_rows"], item["writable_count"], "Yes" if item["itemized"] else "No"] for item in exported_sheets]
        output.print_table(table_data=table_data, columns=["Schedule", "Rows", "Mapped Rows", "Writable Columns", "Itemized"])

    def unique_file_path(self, base_name, extension):
        path = os.path.join(self.export_path, base_name + extension)
        if not os.path.exists(path): return path
        index = 2
        while True:
            candidate = os.path.join(self.export_path, "{}_{}{}".format(base_name, index, extension))
            if not os.path.exists(candidate): return candidate
            index += 1

    def export_single_workbook(self, selected_schedules):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        workbook_path = os.path.join(self.export_path, "P13_Schedules_{}.xlsx".format(timestamp))
        sheets, exported_info, used_sheet_names = [], [], set()

        for schedule in selected_schedules:
            sheet_data = ScheduleDataBuilder.build_sheet_data(schedule, used_sheet_names)
            exported_info.append(sheet_data)
            sheets.append({"name": sheet_data["name"], "rows": sheet_data["rows"]})

        try:
            sx.write_xlsx(workbook_path, sheets)
            self.print_summary(exported_info)
            return workbook_path
        except Exception as exc:
            for sheet_data in exported_info:
                base_name = sx.safe_filename(sheet_data["original_schedule"].Name)
                sx.write_csv(self.unique_file_path(base_name, ".csv"), sheet_data["rows"])
            return self.export_path

    def export_separate_files(self, selected_schedules, csv_only=False):
        created_files, exported_info = [], []
        for schedule in selected_schedules:
            sheet_data = ScheduleDataBuilder.build_sheet_data(schedule, set())
            exported_info.append(sheet_data)
            base_name = sx.safe_filename(schedule.Name)

            if csv_only:
                path = self.unique_file_path(base_name, ".csv")
                sx.write_csv(path, sheet_data["rows"])
                created_files.append(path)
                continue

            path = self.unique_file_path(base_name, ".xlsx")
            try: sx.write_xlsx(path, [{"name": sheet_data["name"], "rows": sheet_data["rows"]}])
            except Exception:
                path = self.unique_file_path(base_name, ".csv")
                sx.write_csv(path, sheet_data["rows"])
            created_files.append(path)

        self.print_summary(exported_info)
        return created_files

def main():
    schedules = ScheduleDataBuilder.collect_valid_schedules()
    if not schedules: forms.alert("No valid schedules were found in the current model.", exitscript=True)

    selected = forms.SelectFromList.show([ScheduleOption(s) for s in schedules], title="Select Schedules to Export", button_name="Export", multiselect=True)
    if not selected: script.exit()

    mode = forms.CommandSwitchWindow.show(["Single XLSX Workbook", "Separate XLSX Files", "Separate CSV Files"], message="Choose export mode")
    if not mode: script.exit()

    export_path = ConfigManager().get_or_set_export_path()
    if not export_path: script.exit()

    exporter = ExportManager(export_path)
    if mode == "Single XLSX Workbook":
        result = exporter.export_single_workbook(selected)
        forms.alert("Export complete.\n\n{}".format(result), title="Export Schedules")
    else:
        is_csv = (mode == "Separate CSV Files")
        created = exporter.export_separate_files(selected, csv_only=is_csv)
        forms.alert("Exported {} file(s) to:\n{}".format(len(created), export_path), title="Export Schedules")
    try: os.startfile(export_path)
    except Exception: pass

if __name__ == "__main__":
    main()