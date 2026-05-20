# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import re
import sys
import csv
import tempfile
import zipfile
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET

from pyrevit import DB, coreutils, revit
import clr

# =======================================================
# 🌟 ระบบโหลด EPPlus.dll แบบหุ้มเกราะ (Dual-Engine)
# =======================================================
LIB_DIR = os.path.dirname(__file__)
BIN_DIR = os.path.join(LIB_DIR, "bin")
EPPLUS_PATH = os.path.join(BIN_DIR, "EPPlus.dll")

excel_lib = None
if os.path.exists(EPPLUS_PATH):
    try:
        clr.AddReferenceToFileAndPath(EPPLUS_PATH)
        import OfficeOpenXml
        try:
            OfficeOpenXml.ExcelPackage.LicenseContext = OfficeOpenXml.LicenseContext.NonCommercial
        except Exception: pass
        excel_lib = OfficeOpenXml
    except Exception as e:
        print("⚠️ Warning: EPPlus.dll load failed. Falling back to Native Engine.")
        excel_lib = None

def to_text(value):
    if value is None: return ""
    try: return unicode(value)
    except NameError: return str(value)
    except Exception: return str(value)

def get_id_value(element_id):
    if element_id is None: return None
    if hasattr(element_id, "Value"): return element_id.Value
    if hasattr(element_id, "IntegerValue"): return element_id.IntegerValue
    try: return int(element_id)
    except Exception: return None

def safe_filename(value):
    value = re.sub(r'[\\/:*?"<>|]+', "_", value or "Schedule")
    value = value.strip(" .")
    return value or "Schedule"

def safe_sheet_name(value, used_names=None):
    used_names = used_names or set()
    name = re.sub(r"[\[\]\:\*\?\/\\]+", "_", value or "Sheet")
    name = name.strip(" '")[:31] or "Sheet"
    base = name
    index = 2
    while name.lower() in used_names:
        suffix = "_{}".format(index)
        name = (base[:31 - len(suffix)] + suffix)[:31]
        index += 1
    used_names.add(name.lower())
    return name

def parameter_to_text(parameter, doc=None):
    if parameter is None or not parameter.HasValue: return ""
    try:
        if parameter.StorageType == DB.StorageType.String:
            return parameter.Annotations if hasattr(parameter, "Annotations") else parameter.AsString() or ""
        if parameter.StorageType == DB.StorageType.Integer:
            return str(parameter.AsInteger())
        if parameter.StorageType == DB.StorageType.Double:
            text = parameter.AsValueString()
            if text: return text
            return str(parameter.AsDouble())
        if parameter.StorageType == DB.StorageType.ElementId:
            if doc:
                try:
                    elem_id = parameter.AsElementId()
                    if elem_id and elem_id != DB.ElementId.InvalidElementId:
                        linked_elem = doc.GetElement(elem_id)
                        if linked_elem: return linked_elem.Name
                except Exception: pass
            return ""
    except Exception: pass
    return ""

def parameter_storage_name(parameter):
    if parameter is None: return ""
    try: return str(parameter.StorageType)
    except Exception: return ""

def parameter_source(element, parameter):
    if element is None or parameter is None: return ""
    try:
        for p in element.Parameters:
            if p.Id == parameter.Id: return "Instance"
    except Exception: pass
    try:
        type_id = element.GetTypeId()
        if type_id and type_id != DB.ElementId.InvalidElementId: return "Type"
    except Exception: pass
    return ""

def find_parameter(element, parameter_id, parameter_name, doc):
    parameter = None
    if element is None: return None
    
    clean_id = to_text(parameter_id).strip()
    if clean_id.endswith(".0"): clean_id = clean_id[:-2]

    if clean_id not in (None, "", "-1", "-1.0"):
        try:
            pid_int = int(float(clean_id))
            if pid_int < 0:
                try:
                    import System
                    builtin_param = System.Enum.ToObject(DB.BuiltInParameter, pid_int)
                    parameter = element.get_Parameter(builtin_param)
                except Exception: parameter = None
            if parameter is None:
                pid = DB.ElementId(pid_int)
                try: parameter = element.get_Parameter(pid)
                except Exception: parameter = None
        except Exception: parameter = None

    if parameter is None and parameter_name:
        clean_name = to_text(parameter_name).strip()
        try: parameter = element.LookupParameter(clean_name)
        except Exception: parameter = None

    if parameter is None:
        try:
            type_id = element.GetTypeId()
            if type_id and type_id != DB.ElementId.InvalidElementId:
                element_type = doc.GetElement(type_id)
                if element_type: parameter = find_parameter(element_type, parameter_id, parameter_name, doc)
        except Exception: parameter = None
    return parameter

# 🌟 [CRITICAL FIX]: ดักตรวจสอบค่า Boolean จากการสั่ง Set() จริง ป้องกัน Revit ปฏิเสธค่าเงียบ
def set_parameter_from_text(parameter, text_value, meta=None):
    if parameter is None: return False, "Parameter not found"
    if parameter.IsReadOnly: return False, "Read-only parameter"

    value = to_text(text_value).strip()
    try:
        if parameter.StorageType == DB.StorageType.String:
            if parameter.Set(value): return True, ""
            return False, "Revit rejected string update"
            
        if parameter.StorageType == DB.StorageType.Integer:
            if value == "": return False, "Blank integer value"
            clean_val = value.replace(",", "").split(".")[0]
            if parameter.Set(int(clean_val)): return True, ""
            return False, "Revit rejected integer update"
            
        if parameter.StorageType == DB.StorageType.Double:
            if value == "": return False, "Blank numeric value"
            try:
                if parameter.SetValueString(value): return True, ""
            except Exception: pass
            try:
                clean_num = value.replace(",", "")
                val_float = float(clean_num)
                is_length = False
                if meta and (meta.get("storage") == "Double" or "length" in str(meta.get("header")).lower()):
                    is_length = True
                    
                if is_length:
                    internal_unit_val = val_float / 304.8
                    if parameter.Set(internal_unit_val): return True, ""
                else:
                    if parameter.Set(val_float): return True, ""
                return False, "Revit rejected numeric value bounds or unit constraint"
            except Exception as e:
                return False, "Unit parsing failure: " + str(e)
                
        return False, "Unsupported storage type"
    except Exception as exc:
        return False, str(exc)

def is_field_editable_parameter(field):
    try:
        if field.IsCalculatedField: return False, "Calculated field"
    except Exception: pass
    try:
        if field.IsCombinedParameterField: return False, "Combined parameter field"
    except Exception: pass
    try:
        if field.ParameterId == DB.ElementId.InvalidElementId: return False, "No parameter id"
    except Exception: pass
    return True, ""

def collect_schedule_fields(doc, schedule):
    fields = []
    try: field_ids = list(schedule.Definition.GetFieldOrder())
    except Exception: field_ids = []

    for field_id in field_ids:
        try: field = schedule.Definition.GetField(field_id)
        except Exception: continue
        try:
            if field.IsHidden: continue
        except Exception: pass

        try: field_name = field.GetName(doc)
        except Exception: field_name = "Field"

        header = None
        try: header = field.ColumnHeading
        except Exception: pass
        if not header: header = field_name

        try: parameter_id = str(get_id_value(field.ParameterId))
        except Exception: parameter_id = ""
        can_edit, edit_note = is_field_editable_parameter(field)

        fields.append({
            "header": header, "field_name": field_name, "parameter_id": parameter_id,
            "field": field, "can_edit": can_edit, "edit_note": edit_note
        })
    return fields

def schedule_is_itemized(schedule):
    try: return bool(schedule.Definition.IsItemized)
    except Exception: return False

def _looks_like_header(row, headers):
    if not row or not headers: return False
    matches = sum(1 for i in range(min(len(row), len(headers))) if to_text(row[i]).strip().lower() == to_text(headers[i]).strip().lower())
    return matches >= max(1, min(len(row), len(headers)) // 2)

def collect_schedule_display_rows(schedule, field_count, headers):
    temp_dir = tempfile.gettempdir()
    fname = "p13_export_{}.txt".format(get_id_value(schedule.Id))
    temp_path = os.path.join(temp_dir, fname)
    if os.path.exists(temp_path):
        try: os.remove(temp_path)
        except Exception: pass
            
    vseop = DB.ViewScheduleExportOptions()
    try:
        vseop.ColumnHeaders = coreutils.get_enum_value(DB.ExportColumnHeaders, "OneRow")
        vseop.TextQualifier = DB.ExportTextQualifier.DoubleQuote
    except Exception: pass
    vseop.FieldDelimiter = "\t"
    vseop.Title = False
    vseop.HeadersFootersBlanks = False
    
    try: schedule.Export(temp_dir, fname, vseop)
    except Exception: return []

    if not os.path.exists(temp_path): return []
    try: revit.files.correct_text_encoding(temp_path)
    except Exception: pass
        
    rows = []
    try:
        with open(temp_path, 'r') as f:
            reader = csv.reader(f, delimiter='\t')
            for r in reader:
                if sys.version_info[0] < 3: rows.append([unicode(x, 'utf-8') for x in r])
                else: rows.append(r)
    except Exception: pass
    try: os.remove(temp_path)
    except Exception: pass
    
    if not rows: return []
    header_idx = -1
    for i, row in enumerate(rows):
        if _looks_like_header(row, headers):
            header_idx = i
            break
    if header_idx != -1: rows = rows[header_idx + 1:]
        
    final_rows = []
    for row in rows:
        if not row or all(not str(c).strip() for c in row): continue
        clean_row = []
        for cell in row:
            c = to_text(cell).strip()
            if c.startswith('"') and c.endswith('"'): c = c[1:-1]
            clean_row.append(c)
        if len(clean_row) > field_count: clean_row = clean_row[:field_count]
        while len(clean_row) < field_count: clean_row.append("")
        final_rows.append(clean_row)
    return final_rows

def analyze_field_for_import(doc, elements, field):
    if not field.get("can_edit", False):
        return {"writable": "0", "storage": "", "source": "", "notes": field.get("edit_note", "Export-only field")}
    for element in elements:
        if not element: continue
        parameter = find_parameter(element, field["parameter_id"], field["field_name"], doc)
        if parameter is None: continue
        storage = parameter_storage_name(parameter)
        source = parameter_source(element, parameter)
        if parameter.IsReadOnly:
            return {"writable": "0", "storage": storage, "source": source, "notes": "Read-only parameter"}
        try:
            if parameter.StorageType == DB.StorageType.ElementId:
                return {"writable": "0", "storage": storage, "source": source, "notes": "ElementId parameter"}
        except Exception: pass
        return {"writable": "1", "storage": storage, "source": source, "notes": ""}
    return {"writable": "0", "storage": "", "source": "", "notes": "Parameter not found"}

def collect_schedule_rows(doc, schedule):
    fields = collect_schedule_fields(doc, schedule)
    itemized = schedule_is_itemized(schedule)
    try: elements = list(DB.FilteredElementCollector(doc, schedule.Id).WhereElementIsNotElementType().ToElements())
    except Exception: elements = []

    visible_headers = [f["header"] for f in fields]
    display_rows = collect_schedule_display_rows(schedule, len(fields), visible_headers)

    element_data = []
    for element in elements:
        edata = {"element": element, "values": []}
        for field in fields:
            param = find_parameter(element, field["parameter_id"], field["field_name"], doc)
            edata["values"].append(parameter_to_text(param, doc).strip().lower())
        element_data.append(edata)
        
    matched_elements = []
    used_indices = set()
    for d_row in display_rows:
        best_idx, best_score = None, -1
        clean_d_row = [to_text(x).strip().lower() for x in d_row]
        for idx, edata in enumerate(element_data):
            if idx in used_indices: continue
            score = sum(1 for i in range(min(len(clean_d_row), len(edata["values"]))) if clean_d_row[i] and clean_d_row[i] == edata["values"][i])
            if score > best_score:
                best_score, best_idx = score, idx
        if best_idx is not None and best_score > 0:
            matched_elements.append(element_data[best_idx]["element"])
            used_indices.add(best_idx)
        else: matched_elements.append(None)

    mlabs_rows = []
    row_mlabs = ["MLabs"]
    row_param_id = ["ParameterId"]
    row_data_type = ["DataType"]
    row_unit = ["Unit"]
    row_storage = ["StorageType"]
    row_modif = ["Modifiable?"]
    row_unit_id = ["UnitId"]
    row_headers = ["ElementId"]
    writable_count = 0

    for idx, field in enumerate(fields):
        import_info = analyze_field_for_import(doc, matched_elements, field)
        
        row_mlabs.append(field["field_name"])
        row_headers.append(field["header"])
        row_param_id.append(field["parameter_id"])

        storage = import_info["storage"]
        if storage == "String": data_type = "Text"
        elif storage == "Double": data_type = "Length" 
        elif storage == "Integer": data_type = "Integer"
        else: data_type = "Text"

        row_data_type.append(data_type)
        row_unit.append("autodesk.spec:spec.string-2.0.0" if data_type == "Text" else "autodesk.spec.aec:length-2.0.1")
        row_storage.append(storage or "String")

        modif = "Read Only"
        if import_info["writable"] == "1":
            writable_count += 1
            modif = "Modifiable (Type)" if import_info["source"] == "Type" else "Modifiable (Instance)"

        row_modif.append(modif)
        row_unit_id.append("Default")

    row_headers.extend(["Comment", "{ID} - {Element name}"])
    mlabs_rows.extend([row_mlabs, row_param_id, row_data_type, row_unit, row_storage, row_modif, row_unit_id, row_headers])
    mapped_rows = 0

    if display_rows:
        for row_idx, display_row in enumerate(display_rows):
            element = matched_elements[row_idx] if row_idx < len(matched_elements) else None
            e_id = str(get_id_value(element.Id)) if element else ""
            try: e_name = element.Name if element else ""
            except: e_name = ""
            if e_id: mapped_rows += 1
            
            row = [e_id] + display_row + ["", "({}) - ({})".format(e_id, e_name) if e_id else ""]
            mlabs_rows.append(row)
    else:
        for element in elements:
            e_id = str(get_id_value(element.Id))
            try: e_name = element.Name
            except: e_name = ""
            if e_id: mapped_rows += 1
            
            row = [e_id]
            for field in fields:
                param = find_parameter(element, field["parameter_id"], field["field_name"], doc)
                row.append(parameter_to_text(param, doc))
            row.extend(["", "({}) - ({})".format(e_id, e_name)])
            mlabs_rows.append(row)

    stats = {"mapped_rows": mapped_rows, "writable_count": writable_count, "row_count": len(mlabs_rows) - 8}
    return mlabs_rows, stats, itemized

def write_csv(path, rows):
    with open(path, "wb") as csvfile:
        csvfile.write(u"\ufeff".encode("utf-8"))
        for row in rows:
            cells = []
            for value in row:
                text = to_text(value).replace('"', '""')
                if any(ch in text for ch in [",", '"', "\n", "\r"]): text = '"{}"'.format(text)
                cells.append(text)
            csvfile.write((",".join(cells) + "\r\n").encode("utf-8"))

def read_csv(path):
    with open(path, "rb") as csvfile: raw = csvfile.read()
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp874", "tis-620", "latin-1"):
        try: text = raw.decode(enc); break
        except Exception: pass
    if text is None: text = raw.decode("latin-1")
    try: from StringIO import StringIO
    except ImportError: from io import StringIO
    reader = csv.reader(StringIO(text))
    return [[cell for cell in row] for row in reader]

def _col_name(index):
    index += 1
    name = ""
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name

def _sheet_xml(rows, hidden_col_count=0):
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">', "<sheetData>"]
    for r_idx, row in enumerate(rows, start=1):
        parts.append('<row r="{}">'.format(r_idx))
        for c_idx, value in enumerate(row):
            ref = "{}{}".format(_col_name(c_idx), r_idx)
            parts.append('<c r="{}" t="inlineStr"><is><t>{}</t></is></c>'.format(ref, escape(to_text(value))))
        parts.append("</row>")
    parts.append("</sheetData></worksheet>")
    return "".join(parts)

def native_write_xlsx(path, sheets):
    used_names, safe_sheets = set(), []
    for sheet in sheets:
        safe_sheets.append({"name": safe_sheet_name(sheet["name"], used_names), "rows": sheet.get("rows", []), "hidden": bool(sheet.get("hidden", False))})

    content_types = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>', '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
    ]
    for idx in range(len(safe_sheets)): content_types.append('<Override PartName="/xl/worksheets/sheet{}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'.format(idx + 1))
    content_types.append("</Types>")

    workbook = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>']
    workbook_rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for idx, sheet in enumerate(safe_sheets):
        state = ' state="hidden"' if sheet["hidden"] else ""
        workbook.append('<sheet name="{}" sheetId="{}" r:id="rId{}"{}/>'.format(escape(sheet["name"]), idx + 1, idx + 1, state))
        workbook_rels.append('<Relationship Id="rId{}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{}.xml"/>'.format(idx + 1, idx + 1))
    workbook.append("</sheets></workbook>")
    workbook_rels.append("</Relationships>")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "".join(content_types))
        zf.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        zf.writestr("docProps/core.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"/>')
        zf.writestr("docProps/app.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"/>')
        zf.writestr("xl/workbook.xml", "".join(workbook))
        zf.writestr("xl/_rels/workbook.xml.rels", "".join(workbook_rels))
        for idx, sheet in enumerate(safe_sheets):
            zf.writestr("xl/worksheets/sheet{}.xml".format(idx + 1), _sheet_xml(sheet["rows"]))

def _strip_ns(tag): return tag.split("}", 1)[-1] if "}" in tag else tag
def _cell_index(cell):
    ref = cell.attrib.get("r", "")
    letters = re.sub(r"[^A-Z]", "", ref.upper())
    if not letters: return None
    index = 0
    for char in letters: index = index * 26 + (ord(char) - 64)
    return index - 1
def _cell_text(cell, shared_strings=None):
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        texts = []
        for node in cell.iter():
            if _strip_ns(node.tag) == "t" and node.text: texts.append(node.text)
        return "".join(texts)
    value = None
    for child in cell:
        if _strip_ns(child.tag) == "v":
            value = child.text
            break
    if cell_type == "s" and value is not None and shared_strings is not None:
        try: return shared_strings[int(value)]
        except Exception: return value or ""
    return value or ""

def native_read_xlsx(path):
    sheets = {}
    with zipfile.ZipFile(path, "r") as zf:
        shared_strings = []
        try:
            sst = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in sst:
                texts = []
                for node in si.iter():
                    if _strip_ns(node.tag) == "t" and node.text: texts.append(node.text)
                shared_strings.append("".join(texts))
        except Exception: pass

        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {}
        for rel in rels:
            rel_id = rel.attrib.get("Id")
            target = rel.attrib.get("Target")
            if rel_id and target:
                rel_targets[rel_id] = target.lstrip("/") if target.startswith("/") else "xl/" + target.lstrip("/")

        for sheet in workbook.iter():
            if _strip_ns(sheet.tag) != "sheet": continue
            name, rel_id = sheet.attrib.get("name"), sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rel_targets.get(rel_id)
            if not name or not target: continue
            root = ET.fromstring(zf.read(target))
            rows = []
            for row in root.iter():
                if _strip_ns(row.tag) != "row": continue
                values = []
                for cell in row:
                    if _strip_ns(cell.tag) == "c":
                        col_idx = _cell_index(cell)
                        if col_idx is None: values.append(_cell_text(cell, shared_strings))
                        else:
                            while len(values) <= col_idx: values.append("")
                            values[col_idx] = _cell_text(cell, shared_strings)
                rows.append(values)
            sheets[name] = rows
    return sheets

def write_xlsx(path, sheets):
    if excel_lib:
        try:
            import System
            from System.IO import FileInfo
            file_info = FileInfo(path)
            if file_info.Exists: file_info.Delete() 
            with excel_lib.ExcelPackage(file_info) as package:
                used_names = set()
                for sheet_data in sheets:
                    s_name = safe_sheet_name(sheet_data["name"], used_names)
                    worksheet = package.Workbook.Worksheets.Add(s_name)
                    for r_idx, row in enumerate(sheet_data["rows"], start=1):
                        for c_idx, val in enumerate(row, start=1):
                            worksheet.Cells[r_idx, c_idx].Value = to_text(val)
                package.Save()
            return
        except Exception as e:
            print("⚠️ EPPlus write failed, falling back to Native XML:", e)
    native_write_xlsx(path, sheets)

def read_xlsx(path):
    if excel_lib:
        try:
            from System.IO import FileInfo
            sheets = {}
            file_info = FileInfo(path)
            with excel_lib.ExcelPackage(file_info) as package:
                for worksheet in package.Workbook.Worksheets:
                    sheet_name = worksheet.Name
                    rows = []
                    if worksheet.Dimension is None: continue
                    max_r = worksheet.Dimension.End.Row
                    max_c = worksheet.Dimension.End.Column
                    for r in range(1, max_r + 1):
                        row_vals = []
                        for c in range(1, max_c + 1):
                            cell_val = worksheet.Cells[r, c].Value
                            row_vals.append(to_text(cell_val))
                        rows.append(row_vals)
                    sheets[sheet_name] = rows
            return sheets
        except Exception as e:
            print("⚠️ EPPlus read failed, falling back to Native XML:", e)
    return native_read_xlsx(path)