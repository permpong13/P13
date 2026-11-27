# -*- coding: utf-8 -*-
# pylint: disable=import-error,invalid-name,broad-except,too-many-lines
"""Import, Update & QA-Check 3D Piles/Foundations from CSV Survey Coordinates (Pro v2.0)."""
from __future__ import print_function, division

__title__ = "Import Piles\n(3D CSV)"
__author__ = "Permpong Taweekul (P13)"
__doc__ = "Import, update, and check As-Built deviation of 3D Piles/Foundations from CSV."

import os
import io
import re
import csv
import sys
import json
import math
import time
import traceback

import clr
clr.AddReference("System")
clr.AddReference("System.Data")
clr.AddReference("System.Xml")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

import System
from System.Data import DataTable
from System.Diagnostics import Process, ProcessStartInfo
from System.IO import MemoryStream
from System.Text import Encoding
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from Microsoft.Win32 import OpenFileDialog, SaveFileDialog

from Autodesk.Revit.DB import (
    BasePoint,
    BuiltInCategory,
    BuiltInParameter,
    Category,
    CategoryType,
    CheckoutStatus,
    ElementId,
    ElementTransformUtils,
    FailureProcessingResult,
    FailureSeverity,
    Family,
    FamilyInstance,
    FamilyPlacementType,
    FilteredElementCollector,
    FilteredWorksetCollector,
    IFailuresPreprocessor,
    Line,
    Level,
    LocationPoint,
    StorageType,
    Transaction,
    Transform,
    WorksetKind,
    WorksharingUtils,
    XYZ,
)
from Autodesk.Revit.DB.Structure import StructuralType

try:
    from Autodesk.Revit.DB import SpecTypeId
except Exception:
    SpecTypeId = None

from pyrevit import forms

try:
    from pyrevit import HOST_APP
except Exception:
    HOST_APP = None


# ------------------------------------------------------------------------------
# CONSTANTS & PYTHON 2/3 COMPATIBILITY
# ------------------------------------------------------------------------------
PY2 = sys.version_info[0] < 3
TEXT_TYPE = unicode if PY2 else str  # noqa: F821

METERS_PER_FOOT = 0.3048
MM_PER_FOOT = 304.8
FEET_PER_METER = 1.0 / METERS_PER_FOOT

UNIT_TO_FEET = {
    "Meters (m)": FEET_PER_METER,
    "Millimeters (mm)": 1.0 / MM_PER_FOOT,
    "Feet (ft)": 1.0,
}

UNIT_TO_MM = {
    "Meters (m)": 1000.0,
    "Millimeters (mm)": 1.0,
    "Feet (ft)": MM_PER_FOOT,
}

COORD_SURVEY = "Shared / Survey Coordinates (UTM / Civil)"
COORD_PROJECT = "Project Base Point (Local N/E)"
COORD_INTERNAL = "Revit Internal Origin"

DATUM_SURVEY = "Survey / Shared Elevation (MSL)"
DATUM_PROJECT = "Project Elevation (Relative to Base Point)"

MODE_UPSERT = "Smart Upsert (Update Existing + Create New)"
MODE_SKIP = "Create New Only (Skip Existing Numbers)"
MODE_CREATE_ALL = "Always Create New Instances"

NONE_COL = "<None>"
AUTO_LEN_PARAM = "<Auto-Detect Length / Depth>"
ACTIVE_WS_LABEL = "<Active Workset>"
NON_WS_LABEL = "<Non-Workshared Model>"

COMMON_LENGTH_PARAM_NAMES = (
    "Pile Length",
    "Pile_Length",
    "PileLength",
    "Length",
    "Depth",
    "Pile Depth",
    "Embedment Length",
    "Foundation Thickness",
    "Height",
    "L",
    u"\u0e04\u0e27\u0e32\u0e21\u0e22\u0e32\u0e27\u0e40\u0e2a\u0e32\u0e40\u0e02\u0e47\u0e21",
    u"\u0e04\u0e27\u0e32\u0e21\u0e22\u0e32\u0e27\u0e40\u0e02\u0e47\u0e21",
)

ALLOWED_3D_BIC_LIST = [
    BuiltInCategory.OST_StructuralFoundation,
    BuiltInCategory.OST_StructuralColumns,
    BuiltInCategory.OST_Columns,
    BuiltInCategory.OST_GenericModel,
]

ALLOWED_PLACEMENT_TYPES = set([
    FamilyPlacementType.OneLevelBased,
    FamilyPlacementType.TwoLevelsBased,
])


# ------------------------------------------------------------------------------
# GENERAL HELPERS & SETTINGS PERSISTENCE
# ------------------------------------------------------------------------------
def to_text(val):
    if val is None:
        return u""
    if isinstance(val, TEXT_TYPE):
        return val
    try:
        return val.decode("utf-8")
    except Exception:
        return TEXT_TYPE(val)


def get_id_val(eid):
    """Cross-version ElementId integer getter (Revit 2024+ .Value vs legacy .IntegerValue)."""
    if eid is None:
        return -1
    val = getattr(eid, "Value", None)
    if val is not None:
        return int(val)
    return int(eid.IntegerValue)


def get_settings_dir():
    appdata = to_text(os.environ.get("APPDATA") or os.path.expanduser("~"))
    folder = os.path.join(appdata, u"pyRevit", u"P13", u"ImportPiles3D")
    if not os.path.isdir(folder):
        try:
            os.makedirs(folder)
        except Exception:
            pass
    return folder


def get_settings_path():
    return os.path.join(get_settings_dir(), u"last_settings_v2.json")


def load_saved_settings():
    p = get_settings_path()
    if not os.path.isfile(p):
        return {}
    try:
        with io.open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_user_settings(payload):
    p = get_settings_path()
    try:
        raw = json.dumps(payload, indent=2, ensure_ascii=False)
        if PY2 and isinstance(raw, str):
            raw = raw.decode("utf-8")
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(raw)
    except Exception:
        pass


def parse_float_clean(raw_val):
    if raw_val is None:
        return None
    txt = to_text(raw_val).strip().replace(",", "")
    if not txt:
        return None
    txt = re.sub(r"^(?:el\.?|elev\.?)\s*", "", txt, flags=re.IGNORECASE)
    txt = re.sub(r"\s*(?:m|mm|ft|deg)$", "", txt, flags=re.IGNORECASE)
    try:
        return float(txt)
    except Exception:
        return None


def get_revit_name(element, is_type=False):
    if element is None:
        return u"Unknown"
    try:
        p_id = BuiltInParameter.SYMBOL_NAME_PARAM if is_type else BuiltInParameter.ALL_MODEL_FAMILY_NAME
        p = element.get_Parameter(p_id)
        if p and p.HasValue:
            s = to_text(p.AsString()).strip()
            if s:
                return s
        if is_type:
            p2 = element.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
            if p2 and p2.HasValue:
                s2 = to_text(p2.AsString()).strip()
                if s2:
                    return s2
        name_attr = getattr(element, "Name", None)
        if name_attr:
            return to_text(name_attr).strip()
    except Exception:
        pass
    return to_text(element)


# ------------------------------------------------------------------------------
# SILENT BATCH WARNING PREPROCESSOR (IFailuresPreprocessor)
# ------------------------------------------------------------------------------
class PileBatchFailuresPreprocessor(IFailuresPreprocessor):
    """Suppresses non-critical Revit pop-up warnings during large pile batch imports."""

    def __init__(self):
        self.suppressed_warnings = 0

    def PreprocessFailures(self, failuresAccessor):
        try:
            msgs = failuresAccessor.GetFailureMessages()
            for failure in msgs:
                if failure.GetSeverity() == FailureSeverity.Warning:
                    failuresAccessor.DeleteWarning(failure)
                    self.suppressed_warnings += 1
        except Exception:
            pass
        return FailureProcessingResult.Continue


# ------------------------------------------------------------------------------
# WORKSHARING & WORKSET HELPERS
# ------------------------------------------------------------------------------
def collect_user_worksets(doc):
    """Return list of (display_name, integer_workset_id) for workshared models."""
    if not doc.IsWorkshared:
        return []
    out = []
    try:
        for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset):
            ws_id_int = int(ws.Id.IntegerValue)
            out.append((to_text(ws.Name), ws_id_int))
    except Exception:
        pass
    return sorted(out, key=lambda x: x[0].lower())


def get_worksharing_lock_owner(doc, elem_id):
    """Return owner username string if checked out by ANOTHER user; else empty string."""
    if not doc.IsWorkshared or elem_id is None:
        return u""
    try:
        status = WorksharingUtils.GetCheckoutStatus(doc, elem_id)
        if status == CheckoutStatus.OwnedByOtherUser:
            info = WorksharingUtils.GetWorksharingTooltipInfo(doc, elem_id)
            owner = to_text(getattr(info, "Owner", "")).strip()
            return owner or u"Another User"
    except Exception:
        pass
    return u""


def assign_element_workset(inst, workset_int_id):
    if workset_int_id is None:
        return
    try:
        p_ws = inst.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
        if p_ws and not p_ws.IsReadOnly:
            p_ws.Set(int(workset_int_id))
    except Exception:
        pass


# ------------------------------------------------------------------------------
# EXACT BIDIRECTIONAL REVIT COORDINATE TRANSFORMATION ENGINE
# ------------------------------------------------------------------------------
class CoordinateConverter(object):
    """Exact matrix converter between Survey/Project/Internal and Revit Internal Feet."""

    def __init__(self, doc):
        self.doc = doc
        self.survey_to_internal = self._resolve_survey_to_internal_transform(doc)
        self.internal_to_survey = self.survey_to_internal.Inverse
        self.pbp_origin_internal = self._get_pbp_internal_position(doc)
        self.summary_text = self._build_summary_text(doc)

    @staticmethod
    def _resolve_survey_to_internal_transform(doc):
        """Self-verifying transform from Shared/Survey space (ft) -> Internal space (ft)."""
        try:
            loc = doc.ActiveProjectLocation
            tf = loc.GetTotalTransform()
            probe_survey = XYZ(123.45, 678.90, 12.34)
            cand = tf.OfPoint(probe_survey)
            pos = loc.GetProjectPosition(cand)
            if abs(pos.EastWest - 123.45) < 1e-4 and abs(pos.NorthSouth - 678.90) < 1e-4:
                return tf
            return tf.Inverse
        except Exception:
            return Transform.Identity

    @staticmethod
    def _get_pbp_internal_position(doc):
        try:
            pbp = BasePoint.GetProjectBasePoint(doc)
            if pbp is not None:
                return pbp.Position
        except Exception:
            pass
        try:
            for bp in FilteredElementCollector(doc).OfClass(BasePoint).ToElements():
                if not bp.IsShared:
                    bbox = bp.get_BoundingBox(None)
                    if bbox:
                        return (bbox.Min + bbox.Max) * 0.5
        except Exception:
            pass
        return XYZ.Zero

    def _build_summary_text(self, doc):
        try:
            pos = doc.ActiveProjectLocation.GetProjectPosition(self.pbp_origin_internal)
            ew_m = pos.EastWest * METERS_PER_FOOT
            ns_m = pos.NorthSouth * METERS_PER_FOOT
            el_m = pos.Elevation * METERS_PER_FOOT
            ang_deg = math.degrees(pos.Angle)
            return u"Base Point Shared -> E: {:,.3f} m  |  N: {:,.3f} m  |  Elev: {:+.3f} m  |  True North: {:.3f} deg".format(
                ew_m, ns_m, el_m, ang_deg
            )
        except Exception:
            return u"Active Project Location ready."

    def to_internal_xy(self, east_val, north_val, unit_factor, coord_mode):
        e_ft = float(east_val) * unit_factor
        n_ft = float(north_val) * unit_factor

        if coord_mode == COORD_SURVEY:
            pt_int = self.survey_to_internal.OfPoint(XYZ(e_ft, n_ft, 0.0))
            return pt_int.X, pt_int.Y
        if coord_mode == COORD_PROJECT:
            return self.pbp_origin_internal.X + e_ft, self.pbp_origin_internal.Y + n_ft
        return e_ft, n_ft

    def from_internal_to_input_xy(self, internal_pt, unit_factor, coord_mode):
        """Convert existing Revit internal XYZ back to E, N in the selected user unit & coord mode."""
        inv_factor = 1.0 / float(unit_factor) if unit_factor else METERS_PER_FOOT
        if coord_mode == COORD_SURVEY:
            pt_surv = self.internal_to_survey.OfPoint(internal_pt)
            return pt_surv.X * inv_factor, pt_surv.Y * inv_factor
        if coord_mode == COORD_PROJECT:
            dx = internal_pt.X - self.pbp_origin_internal.X
            dy = internal_pt.Y - self.pbp_origin_internal.Y
            return dx * inv_factor, dy * inv_factor
        return internal_pt.X * inv_factor, internal_pt.Y * inv_factor

    def to_internal_z(self, elev_val, unit_factor, datum_mode):
        z_ft = float(elev_val) * unit_factor
        if datum_mode == DATUM_SURVEY:
            pt_int = self.survey_to_internal.OfPoint(XYZ(0.0, 0.0, z_ft))
            return pt_int.Z
        return self.pbp_origin_internal.Z + z_ft


# ------------------------------------------------------------------------------
# 3D MODEL FAMILY & SMART PARAMETER UNIT DISCOVERY
# ------------------------------------------------------------------------------
class FamilyPack(object):
    def __init__(self, fam_name, cat_name, cat_id_val):
        self.name = fam_name
        self.category_name = cat_name
        self.category_id_val = cat_id_val
        self.symbols = {}

    @property
    def display_label(self):
        return u"[{}] {}".format(self.category_name, self.name)


def collect_3d_point_families(doc):
    """Collect strictly point-based 3D Model families; 100% blocks 2D Detail Items & Beams."""
    allowed_cat_ids = set()
    for bic in ALLOWED_3D_BIC_LIST:
        try:
            cat = Category.GetCategory(doc, bic)
            if cat is not None:
                allowed_cat_ids.add(get_id_val(cat.Id))
        except Exception:
            pass

    detail_cat_id = -999
    try:
        d_cat = Category.GetCategory(doc, BuiltInCategory.OST_DetailComponents)
        if d_cat is not None:
            detail_cat_id = get_id_val(d_cat.Id)
    except Exception:
        pass

    packs = {}
    for fam in FilteredElementCollector(doc).OfClass(Family).ToElements():
        try:
            if fam.IsInPlace:
                continue
            f_cat = fam.FamilyCategory
            if f_cat is None or f_cat.CategoryType != CategoryType.Model:
                continue

            cid = get_id_val(f_cat.Id)
            if cid == detail_cat_id or cid not in allowed_cat_ids:
                continue

            if fam.FamilyPlacementType not in ALLOWED_PLACEMENT_TYPES:
                continue

            fam_name = get_revit_name(fam, is_type=False)
            key = u"{}|{}".format(cid, fam_name)
            if key not in packs:
                packs[key] = FamilyPack(fam_name, to_text(f_cat.Name), cid)

            for sym_id in fam.GetFamilySymbolIds():
                sym = doc.GetElement(sym_id)
                if sym is not None:
                    t_name = get_revit_name(sym, is_type=True)
                    packs[key].symbols[t_name] = sym
        except Exception:
            continue

    valid = [p for p in packs.values() if p.symbols]
    return sorted(valid, key=lambda x: (x.category_name.lower(), x.name.lower()))


def is_parameter_length_spec(param):
    """Detect whether a Double parameter stores Revit internal Length (feet) vs raw Number."""
    if param is None or param.StorageType != StorageType.Double:
        return False
    defn = param.Definition
    if defn is None:
        return False

    # Revit 2022+ ForgeTypeId check
    try:
        dt = defn.GetDataType()
        if dt is not None:
            if SpecTypeId is not None and dt == SpecTypeId.Length:
                return True
            type_id_str = to_text(getattr(dt, "TypeId", "")).lower()
            if ":length" in type_id_str or "aec:distance" in type_id_str or "stationing" in type_id_str:
                return True
            if ":number" in type_id_str or ":angle" in type_id_str or ":slope" in type_id_str:
                return False
    except Exception:
        pass

    # Legacy Revit fallback
    try:
        pt_str = to_text(defn.ParameterType).lower()
        if "length" in pt_str:
            return True
    except Exception:
        pass
    return False


def discover_family_parameters(doc, fam_pack):
    """Return (all_writable_names, numeric_or_length_names) without dummy transactions."""
    all_names = set(["Mark", "Comments"])
    numeric_names = set()

    # 1. Inspect project/shared ParameterBindings bound to this category
    try:
        it = doc.ParameterBindings.ForwardIterator()
        it.Reset()
        while it.MoveNext():
            defn = it.Key
            binding = it.Current
            if binding.__class__.__name__ == "TypeBinding":
                continue
            cats = getattr(binding, "Categories", None)
            if cats:
                for c in cats:
                    if c and get_id_val(c.Id) == fam_pack.category_id_val:
                        if defn and defn.Name:
                            p_nm = to_text(defn.Name)
                            all_names.add(p_nm)
                            try:
                                dt = defn.GetDataType()
                                tid = to_text(getattr(dt, "TypeId", "")).lower()
                                if "length" in tid or "number" in tid or "distance" in tid:
                                    numeric_names.add(p_nm)
                            except Exception:
                                numeric_names.add(p_nm)
                        break
    except Exception:
        pass

    # 2. Inspect an existing placed instance of this family if available in the model
    try:
        sym_ids = set(get_id_val(s.Id) for s in fam_pack.symbols.values())
        bic_target = None
        for bic in ALLOWED_3D_BIC_LIST:
            cat = Category.GetCategory(doc, bic)
            if cat and get_id_val(cat.Id) == fam_pack.category_id_val:
                bic_target = bic
                break

        if bic_target is not None:
            col = FilteredElementCollector(doc).OfCategory(bic_target).WhereElementIsNotElementType()
            for inst in col:
                if get_id_val(inst.GetTypeId()) in sym_ids:
                    for p in inst.Parameters:
                        if p.IsReadOnly or not p.Definition or not p.Definition.Name:
                            continue
                        nm = to_text(p.Definition.Name)
                        if p.StorageType in (StorageType.String, StorageType.Double, StorageType.Integer):
                            all_names.add(nm)
                        if p.StorageType == StorageType.Double:
                            numeric_names.add(nm)
                    break
    except Exception:
        pass

    for common_len in COMMON_LENGTH_PARAM_NAMES[:8]:
        numeric_names.add(common_len)

    sorted_all = sorted(list(all_names), key=lambda s: (0 if s == "Mark" else 1, s.lower()))
    sorted_num = sorted(list(numeric_names), key=lambda s: s.lower())
    return sorted_all, sorted_num


# ------------------------------------------------------------------------------
# ROBUST MULTI-ENCODING CSV READER (PYTHON 2 & PYTHON 3 SAFE)
# ------------------------------------------------------------------------------
def decode_csv_bytes(raw_bytes):
    for enc in ("utf-8-sig", "utf-8", "cp874", "tis-620", "latin-1"):
        try:
            return raw_bytes.decode(enc)
        except Exception:
            continue
    return raw_bytes.decode("latin-1", errors="ignore")


def read_raw_csv_table(filepath, delimiter_choice="Auto"):
    """Return (headers_list, list_of_row_dicts) safely across IronPython 2.7 & CPython 3."""
    with io.open(filepath, "rb") as f:
        raw_bytes = f.read()

    text = decode_csv_bytes(raw_bytes)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return [], []

    if delimiter_choice == "Comma (,)":
        delim = ","
    elif delimiter_choice == "Semicolon (;)":
        delim = ";"
    elif delimiter_choice == "Tab (\\t)":
        delim = "\t"
    else:
        sample_head = lines[0]
        counts = [
            (",", sample_head.count(",")),
            (";", sample_head.count(";")),
            ("\t", sample_head.count("\t")),
        ]
        counts.sort(key=lambda item: item, reverse=True)
        delim = counts[0][0] if counts[0] > 0 else ","

    if PY2:
        encoded_lines = [ln.encode("utf-8") for ln in lines]
        reader = csv.reader(encoded_lines, delimiter=str(delim))
        raw_rows = [[cell.decode("utf-8") for cell in r] for r in reader]
    else:
        reader = csv.reader(lines, delimiter=delim)
        raw_rows = list(reader)

    if not raw_rows:
        return [], []

    headers = []
    seen = {}
    for idx, h in enumerate(raw_rows[0]):
        clean_h = to_text(h).strip() or u"Col_{}".format(idx + 1)
        if clean_h in seen:
            seen[clean_h] += 1
            clean_h = u"{}_{}".format(clean_h, seen[clean_h])
        else:
            seen[clean_h] = 1
        headers.append(clean_h)

    rows_out = []
    for r_idx, vals in enumerate(raw_rows[1:], start=2):
        if not any(to_text(c).strip() for c in vals):
            continue
        row_dict = {"__line__": r_idx}
        for c_idx, h_name in enumerate(headers):
            row_dict[h_name] = to_text(vals[c_idx]).strip() if c_idx < len(vals) else u""
        rows_out.append(row_dict)

    return headers, rows_out


def auto_pick_column(headers, priority_keywords, exact_matches=None):
    exact_set = set(x.lower() for x in (exact_matches or []))
    for h in headers:
        hl = h.strip().lower()
        if hl in exact_set:
            return h
    for kw in priority_keywords:
        kw_l = kw.lower()
        for h in headers:
            if kw_l in h.strip().lower():
                return h
    return NONE_COL


def ensure_and_open_sample_csv(script_dir):
    sample_path = os.path.join(script_dir, "Family_Coordinate.csv")
    if not os.path.isfile(sample_path):
        sample_content = (
            u"Pile_No,Easting,Northing,CutOff_Elev,Pile_Length,Tip_Elev,Type,Rotation_Deg\n"
            u"P-01,665120.500,1521340.250,-1.250,21.00,-22.250,I-0.26x0.26,0\n"
            u"P-02,665124.500,1521340.250,-1.250,21.00,-22.250,I-0.26x0.26,0\n"
            u"P-03,665120.500,1521345.250,-1.400,22.00,-23.400,I-0.30x0.30,90\n"
        )
        with io.open(sample_path, "w", encoding="utf-8-sig") as f:
            f.write(sample_content)

    psi = ProcessStartInfo(sample_path)
    psi.UseShellExecute = True
    Process.Start(psi)


def write_qa_deviation_csv(filepath, records, tol_mm):
    """Export UTF-8-BOM CSV report of As-Built Pile Deviation & Import Status for Excel."""
    headers = [
        "CSV_Line",
        "Pile_No",
        "Action",
        "Resolved_Type",
        "Design_Old_E",
        "Design_Old_N",
        "Survey_New_E",
        "Survey_New_N",
        "dE_mm",
        "dN_mm",
        "Radial_Offset_mm",
        "Allowable_Tol_mm",
        "QA_Status",
        "CutOff_Input",
        "Length_m",
    ]
    with io.open(filepath, "w", encoding="utf-8-sig") as f:
        f.write(u",".join(headers) + u"\n")
        for rec in records:
            old_e_txt = "{:.4f}".format(rec["old_e"]) if rec["old_e"] is not None else ""
            old_n_txt = "{:.4f}".format(rec["old_n"]) if rec["old_n"] is not None else ""
            de_txt = "{:+.1f}".format(rec["de_mm"]) if rec["de_mm"] is not None else ""
            dn_txt = "{:+.1f}".format(rec["dn_mm"]) if rec["dn_mm"] is not None else ""
            dist_txt = "{:.1f}".format(rec["offset_mm"]) if rec["offset_mm"] is not None else ""
            cut_txt = "{:+.3f}".format(rec["cutoff"]) if rec["cutoff"] is not None else ""
            len_txt = "{:.3f}".format(rec["length_ft"] * METERS_PER_FOOT) if rec["length_ft"] is not None else ""

            cells = [
                to_text(rec["line"]),
                u'"{}"'.format(to_text(rec["no"]).replace('"', '""')),
                u'"{}"'.format(to_text(rec["action_label"])),
                u'"{}"'.format(to_text(rec["resolved_type_name"]).replace('"', '""')),
                old_e_txt,
                old_n_txt,
                "{:.4f}".format(rec["e"]),
                "{:.4f}".format(rec["n"]),
                de_txt,
                dn_txt,
                dist_txt,
                "{:.1f}".format(tol_mm),
                u'"{}"'.format(to_text(rec["qa_status"])),
                cut_txt,
                len_txt,
            ]
            f.write(u",".join(cells) + u"\n")


# ------------------------------------------------------------------------------
# UNIT-AWARE PARAMETER & PILE GEOMETRY WRITERS
# ------------------------------------------------------------------------------
def set_param_unit_aware(element, param_name, raw_value, value_unit="raw"):
    """
    Write parameter safely with automatic unit awareness:
    - value_unit='feet': raw_value is in internal feet (convert to meters/number if target is plain Number/String).
    - value_unit='meters': raw_value is in meters (convert to feet ONLY if target Double param is Length spec!).
    - value_unit='mm': raw_value is in millimeters (convert to feet if target Double param is Length spec).
    - value_unit='raw': write directly as String/Double/Int.
    """
    if not param_name or raw_value is None:
        return False

    candidates = list(element.GetParameters(param_name))
    if not candidates:
        p_single = element.LookupParameter(param_name)
        if p_single:
            candidates = [p_single]

    for p in candidates:
        if p.IsReadOnly:
            continue
        try:
            st = p.StorageType
            if st == StorageType.String:
                if value_unit == "feet":
                    p.Set("{:.3f}".format(float(raw_value) * METERS_PER_FOOT))
                elif value_unit == "meters":
                    p.Set("{:.4f}".format(float(raw_value)))
                elif value_unit == "mm":
                    p.Set("{:.1f}".format(float(raw_value)))
                else:
                    p.Set(to_text(raw_value))
                return True

            if st == StorageType.Double:
                f_val = float(raw_value)
                is_len = is_parameter_length_spec(p)
                if value_unit == "feet":
                    p.Set(f_val if is_len else (f_val * METERS_PER_FOOT))
                elif value_unit == "meters":
                    p.Set((f_val * FEET_PER_METER) if is_len else f_val)
                elif value_unit == "mm":
                    p.Set((f_val / MM_PER_FOOT) if is_len else f_val)
                else:
                    p.Set(f_val)
                return True

            if st == StorageType.Integer:
                p.Set(int(round(float(raw_value))))
                return True
        except Exception:
            continue
    return False


def apply_level_and_cutoff_offset(inst, base_level, offset_ft):
    """Apply host level and vertical Cut-Off offset across Foundations, Columns & Generic Models."""
    for lvl_bip in (
        BuiltInParameter.FAMILY_LEVEL_PARAM,
        BuiltInParameter.FAMILY_BASE_LEVEL_PARAM,
        BuiltInParameter.SCHEDULE_LEVEL_PARAM,
    ):
        try:
            lp = inst.get_Parameter(lvl_bip)
            if lp and not lp.IsReadOnly and get_id_val(lp.AsElementId()) != get_id_val(base_level.Id):
                lp.Set(base_level.Id)
        except Exception:
            pass

    if offset_ft is None:
        return

    # For Two-Level Structural Columns (where Top is Cut-Off and Base is Tip), check if Top Level == Base Level
    top_lvl_param = inst.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM)
    base_lvl_param = inst.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM)
    if top_lvl_param and base_lvl_param and not top_lvl_param.IsReadOnly:
        try:
            top_lvl_param.Set(base_level.Id)
            top_off_p = inst.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM)
            if top_off_p and not top_off_p.IsReadOnly:
                top_off_p.Set(float(offset_ft))
                return
        except Exception:
            pass

    for off_bip in (
        BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM,
        BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM,
        BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM,
        BuiltInParameter.STRUCTURAL_BOTTOM_LEVEL_OFFSET_PARAM,
        BuiltInParameter.INSTANCE_ELEVATION_PARAM,
    ):
        try:
            op = inst.get_Parameter(off_bip)
            if op and not op.IsReadOnly and op.StorageType == StorageType.Double:
                op.Set(float(offset_ft))
                return
        except Exception:
            continue

    for p_name in ("Height Offset From Level", "Base Offset", "Offset", "Bottom Offset"):
        if set_param_unit_aware(inst, p_name, offset_ft, value_unit="feet"):
            return


def apply_pile_length_3d(inst, base_level, cutoff_offset_ft, length_ft, preferred_len_param):
    """Apply individual 3D pile length via instance parameter or Two-Level column bottom offset."""
    if length_ft is None or length_ft <= 1e-6:
        return False

    # 1. User-specified length parameter
    if preferred_len_param and preferred_len_param != AUTO_LEN_PARAM:
        if set_param_unit_aware(inst, preferred_len_param, length_ft, value_unit="feet"):
            return True

    # 2. Auto-detect common Pile Length / Depth instance parameters
    for cand_name in COMMON_LENGTH_PARAM_NAMES:
        if set_param_unit_aware(inst, cand_name, length_ft, value_unit="feet"):
            return True

    # 3. Fallback for Two-Level Structural Columns (Top = Cut-Off, Base Offset = Cut-Off - Length)
    try:
        top_lvl_p = inst.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM)
        base_off_p = inst.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM)
        top_off_p = inst.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM)
        if top_lvl_p and base_off_p and top_off_p and not base_off_p.IsReadOnly:
            top_lvl_p.Set(base_level.Id)
            top_off = float(cutoff_offset_ft) if cutoff_offset_ft is not None else 0.0
            top_off_p.Set(top_off)
            base_off_p.Set(top_off - float(length_ft))
            return True
    except Exception:
        pass

    return False


def index_existing_elements_by_key(doc, fam_pack, target_param_name):
    """Build {normalized_pile_no: FamilyInstance} map for Smart Upsert & Deviation QA."""
    lookup = {}
    if not target_param_name:
        return lookup

    bic_target = None
    for bic in ALLOWED_3D_BIC_LIST:
        cat = Category.GetCategory(doc, bic)
        if cat and get_id_val(cat.Id) == fam_pack.category_id_val:
            bic_target = bic
            break

    if bic_target is None:
        return lookup

    for inst in FilteredElementCollector(doc).OfCategory(bic_target).WhereElementIsNotElementType():
        if not isinstance(inst, FamilyInstance):
            continue
        p = inst.LookupParameter(target_param_name)
        if p is None and target_param_name == "Mark":
            p = inst.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if p is None:
            continue

        val_str = to_text(p.AsString() if p.StorageType == StorageType.String else p.AsValueString()).strip()
        if val_str:
            lookup[val_str.lower()] = inst
    return lookup


# ------------------------------------------------------------------------------
# REVIT-NATIVE WPF UI (P13 PRO v2.0 DESIGN)
# ------------------------------------------------------------------------------
IMPORT_PILES_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="P13 - Import 3D Piles &amp; As-Built QA from CSV (Pro v2.0)"
        Width="980" Height="780" MinWidth="860" MinHeight="680"
        WindowStartupLocation="CenterScreen"
        Background="#F3F4F6" FontFamily="Segoe UI" FontSize="12"
        UseLayoutRounding="True" SnapsToDevicePixels="True">
    <Grid>
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- Dark Revit-Style Header -->
        <Border Grid.Row="0" Background="#1F252D" Padding="18,12">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <StackPanel>
                    <TextBlock Text="Import 3D Piles, Foundations &amp; As-Built Deviation QA (Pro v2.0)" FontSize="15.5" FontWeight="SemiBold" Foreground="#FFFFFF"/>
                    <TextBlock Name="lbl_coord_summary" Text="Loading project coordinate system..." FontSize="11.5" Foreground="#9CA3AF" Margin="0,3,0,0"/>
                </StackPanel>
                <Border Grid.Column="1" Background="#0F766E" CornerRadius="4" Padding="10,4" VerticalAlignment="Center">
                    <TextBlock Text="3D MODEL + AS-BUILT QA" FontSize="10.5" FontWeight="Bold" Foreground="#FFFFFF"/>
                </Border>
            </Grid>
        </Border>

        <!-- Top Configuration Cards -->
        <Grid Grid.Row="1" Margin="14,10,14,8">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="1.08*"/>
                <ColumnDefinition Width="12"/>
                <ColumnDefinition Width="1.12*"/>
            </Grid.ColumnDefinitions>

            <!-- Left Card: CSV Source, Coordinate System & 8-Column Mapping -->
            <Border Grid.Column="0" Background="#FFFFFF" BorderBrush="#D1D5DB" BorderThickness="1" CornerRadius="6" Padding="12">
                <StackPanel>
                    <TextBlock Text="1. Survey CSV Source &amp; Column Mapping" FontWeight="SemiBold" Foreground="#111827" Margin="0,0,0,8"/>

                    <Grid Margin="0,0,0,6">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="76"/>
                            <ColumnDefinition Width="92"/>
                        </Grid.ColumnDefinitions>
                        <TextBox Name="txt_csv_path" IsReadOnly="True" Height="25" VerticalContentAlignment="Center" Padding="6,0" Background="#F9FAFB" BorderBrush="#D1D5DB"/>
                        <Button Name="btn_browse" Grid.Column="1" Content="Browse..." Height="25" Margin="6,0,0,0" Background="#2563EB" Foreground="#FFFFFF" BorderThickness="0" FontWeight="SemiBold"/>
                        <Button Name="btn_sample" Grid.Column="2" Content="Sample CSV" Height="25" Margin="6,0,0,0" Background="#F3F4F6" BorderBrush="#D1D5DB"/>
                    </Grid>

                    <Grid Margin="0,2,0,4">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="95"/>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="68"/>
                            <ColumnDefinition Width="112"/>
                        </Grid.ColumnDefinitions>
                        <TextBlock Text="Coord System:" VerticalAlignment="Center" Foreground="#374151"/>
                        <ComboBox Name="cb_coord_sys" Grid.Column="1" Height="24"/>
                        <TextBlock Grid.Column="2" Text="CSV Units:" VerticalAlignment="Center" Margin="8,0,0,0" Foreground="#374151"/>
                        <ComboBox Name="cb_units" Grid.Column="3" Height="24"/>
                    </Grid>

                    <Grid Margin="0,2,0,8">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="95"/>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="68"/>
                            <ColumnDefinition Width="112"/>
                        </Grid.ColumnDefinitions>
                        <TextBlock Text="Elev Datum:" VerticalAlignment="Center" Foreground="#374151"/>
                        <ComboBox Name="cb_elev_datum" Grid.Column="1" Height="24"/>
                        <TextBlock Grid.Column="2" Text="Delimiter:" VerticalAlignment="Center" Margin="8,0,0,0" Foreground="#374151"/>
                        <ComboBox Name="cb_delimiter" Grid.Column="3" Height="24"/>
                    </Grid>

                    <Border BorderBrush="#E5E7EB" BorderThickness="0,1,0,0" Padding="0,8,0,0">
                        <Grid>
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="84"/>
                                <ColumnDefinition Width="*"/>
                                <ColumnDefinition Width="10"/>
                                <ColumnDefinition Width="84"/>
                                <ColumnDefinition Width="*"/>
                            </Grid.ColumnDefinitions>
                            <Grid.RowDefinitions>
                                <RowDefinition Height="27"/>
                                <RowDefinition Height="27"/>
                                <RowDefinition Height="27"/>
                                <RowDefinition Height="27"/>
                            </Grid.RowDefinitions>

                            <TextBlock Grid.Row="0" Grid.Column="0" Text="Pile No *:" VerticalAlignment="Center" FontWeight="SemiBold"/>
                            <ComboBox Name="cb_col_no" Grid.Row="0" Grid.Column="1" Height="23"/>
                            <TextBlock Grid.Row="0" Grid.Column="3" Text="Type Col:" VerticalAlignment="Center"/>
                            <ComboBox Name="cb_col_type" Grid.Row="0" Grid.Column="4" Height="23"/>

                            <TextBlock Grid.Row="1" Grid.Column="0" Text="Easting (E) *:" VerticalAlignment="Center" FontWeight="SemiBold"/>
                            <ComboBox Name="cb_col_e" Grid.Row="1" Grid.Column="1" Height="23"/>
                            <TextBlock Grid.Row="1" Grid.Column="3" Text="Cut-Off Z:" VerticalAlignment="Center"/>
                            <ComboBox Name="cb_col_cutoff" Grid.Row="1" Grid.Column="4" Height="23"/>

                            <TextBlock Grid.Row="2" Grid.Column="0" Text="Northing (N)*:" VerticalAlignment="Center" FontWeight="SemiBold"/>
                            <ComboBox Name="cb_col_n" Grid.Row="2" Grid.Column="1" Height="23"/>
                            <TextBlock Grid.Row="2" Grid.Column="3" Text="Pile Length:" VerticalAlignment="Center"/>
                            <ComboBox Name="cb_col_len" Grid.Row="2" Grid.Column="4" Height="23"/>

                            <TextBlock Grid.Row="3" Grid.Column="0" Text="Rotation:" VerticalAlignment="Center"/>
                            <ComboBox Name="cb_col_rot" Grid.Row="3" Grid.Column="1" Height="23"/>
                            <TextBlock Grid.Row="3" Grid.Column="3" Text="Tip / Toe Z:" VerticalAlignment="Center"/>
                            <ComboBox Name="cb_col_tip" Grid.Row="3" Grid.Column="4" Height="23"/>
                        </Grid>
                    </Border>
                </StackPanel>
            </Border>

            <!-- Right Card: Revit 3D Family, Length, Workset, Upsert & Deviation QA -->
            <Border Grid.Column="2" Background="#FFFFFF" BorderBrush="#D1D5DB" BorderThickness="1" CornerRadius="6" Padding="12">
                <StackPanel>
                    <TextBlock Text="2. Revit 3D Placement, Workset &amp; As-Built QA Settings" FontWeight="SemiBold" Foreground="#111827" Margin="0,0,0,8"/>

                    <Grid Margin="0,0,0,5">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="108"/>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="74"/>
                            <ColumnDefinition Width="135"/>
                        </Grid.ColumnDefinitions>
                        <TextBlock Text="Host Level:" VerticalAlignment="Center" Foreground="#374151"/>
                        <ComboBox Name="cb_level" Grid.Column="1" Height="24"/>
                        <TextBlock Grid.Column="2" Text="Workset:" VerticalAlignment="Center" Margin="8,0,0,0" Foreground="#374151"/>
                        <ComboBox Name="cb_workset" Grid.Column="3" Height="24"/>
                    </Grid>

                    <Grid Margin="0,0,0,5">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="108"/>
                            <ColumnDefinition Width="*"/>
                        </Grid.ColumnDefinitions>
                        <TextBlock Text="3D Family:" VerticalAlignment="Center" Foreground="#374151"/>
                        <ComboBox Name="cb_family" Grid.Column="1" Height="24"/>
                    </Grid>

                    <Grid Margin="0,0,0,5">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="108"/>
                            <ColumnDefinition Width="*"/>
                        </Grid.ColumnDefinitions>
                        <TextBlock Text="Fallback Type:" VerticalAlignment="Center" Foreground="#374151"/>
                        <ComboBox Name="cb_default_type" Grid.Column="1" Height="24"/>
                    </Grid>

                    <Grid Margin="0,0,0,5">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="108"/>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="92"/>
                            <ColumnDefinition Width="*"/>
                        </Grid.ColumnDefinitions>
                        <TextBlock Text="Write No to:" VerticalAlignment="Center" Foreground="#374151"/>
                        <ComboBox Name="cb_target_param" Grid.Column="1" Height="24"/>
                        <TextBlock Grid.Column="2" Text="Length Param:" VerticalAlignment="Center" Margin="8,0,0,0" Foreground="#374151"/>
                        <ComboBox Name="cb_len_param" Grid.Column="3" Height="24"/>
                    </Grid>

                    <Grid Margin="0,0,0,6">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="108"/>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="92"/>
                            <ColumnDefinition Width="72"/>
                        </Grid.ColumnDefinitions>
                        <TextBlock Text="Duplicate Mode:" VerticalAlignment="Center" Foreground="#374151"/>
                        <ComboBox Name="cb_mode" Grid.Column="1" Height="24"/>
                        <TextBlock Grid.Column="2" Text="Max Tol (mm):" VerticalAlignment="Center" Margin="8,0,0,0" Foreground="#374151"/>
                        <TextBox Name="txt_tol_mm" Grid.Column="3" Text="75.0" Height="24" VerticalContentAlignment="Center" HorizontalContentAlignment="Right" Padding="4,0"/>
                    </Grid>

                    <Border BorderBrush="#E5E7EB" BorderThickness="0,1,0,0" Padding="0,6,0,0">
                        <StackPanel>
                            <CheckBox Name="chk_write_ne" IsChecked="True" Margin="0,2,0,3"
                                      Content="Write unit-aware N_Coordinate / E_Coordinate &amp; Deviation info"/>
                            <CheckBox Name="chk_export_qa" IsChecked="True" Margin="0,2,0,3"
                                      Content="Auto-export As-Built Deviation QA Report (.csv) when updating piles"/>
                            <CheckBox Name="chk_select_after" IsChecked="True" Margin="0,2,0,0"
                                      Content="Select placed / updated 3D elements in Revit after completion"/>
                        </StackPanel>
                    </Border>
                </StackPanel>
            </Border>
        </Grid>

        <!-- Center Live Preview & Deviation QA DataGrid -->
        <Border Grid.Row="2" Background="#FFFFFF" BorderBrush="#D1D5DB" BorderThickness="1" CornerRadius="6" Margin="14,0,14,10" Padding="10">
            <Grid>
                <Grid.RowDefinitions>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="*"/>
                </Grid.RowDefinitions>
                <Grid Grid.Row="0" Margin="0,0,0,6">
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="Auto"/>
                        <ColumnDefinition Width="*"/>
                        <ColumnDefinition Width="Auto"/>
                    </Grid.ColumnDefinitions>
                    <TextBlock Text="3. Live CSV Validation &amp; As-Built Deviation Preview (First 250 Rows)" FontWeight="SemiBold" Foreground="#111827" VerticalAlignment="Center"/>
                    <TextBlock Name="lbl_preview_stats" Grid.Column="1" Text="No CSV file loaded." Foreground="#2563EB" FontWeight="SemiBold" HorizontalAlignment="Right" VerticalAlignment="Center" Margin="12,0"/>
                    <Button Name="btn_export_qa" Grid.Column="2" Content="Export QA CSV..." Height="24" Padding="10,0" Background="#F3F4F6" BorderBrush="#D1D5DB"/>
                </Grid>

                <DataGrid Name="dg_preview" Grid.Row="1" AutoGenerateColumns="True" IsReadOnly="True"
                          CanUserAddRows="False" CanUserDeleteRows="False" GridLinesVisibility="Horizontal"
                          HorizontalGridLinesBrush="#E5E7EB" AlternatingRowBackground="#F9FAFB"
                          HeadersVisibility="Column" BorderBrush="#E5E7EB" BorderThickness="1"/>
            </Grid>
        </Border>

        <!-- Footer Bar -->
        <Border Grid.Row="3" Background="#E5E7EB" BorderBrush="#D1D5DB" BorderThickness="0,1,0,0" Padding="14,10">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <TextBlock Text="Worksharing-safe &amp; pop-up warning suppression active inside one undoable Transaction." VerticalAlignment="Center" Foreground="#4B5563" FontSize="11.5"/>
                <StackPanel Grid.Column="1" Orientation="Horizontal">
                    <Button Name="btn_run" Content="Import / Update 3D Piles" Width="190" Height="30"
                            Background="#006CBE" Foreground="#FFFFFF" BorderThickness="0" FontWeight="SemiBold" Margin="0,0,8,0" IsDefault="True"/>
                    <Button Name="btn_cancel" Content="Cancel" Width="90" Height="30"
                            Background="#FFFFFF" BorderBrush="#9CA3AF" IsCancel="True"/>
                </StackPanel>
            </Grid>
        </Border>
    </Grid>
</Window>
"""


class ImportPilesProController(object):
    def __init__(self, doc, levels, fam_packs, worksets, converter, script_dir):
        self.doc = doc
        self.levels = sorted(levels, key=lambda lv: lv.Elevation)
        self.fam_packs = fam_packs
        self.worksets = worksets  # [(ws_name, ws_int_id), ...]
        self.converter = converter
        self.script_dir = script_dir
        self.saved = load_saved_settings()

        self.csv_headers = []
        self.csv_raw_rows = []
        self.parsed_records = []
        self.confirmed = False
        self._suppress_events = True

        stream = MemoryStream(Encoding.UTF8.GetBytes(IMPORT_PILES_XAML))
        self.win = XamlReader.Load(stream)
        try:
            hwnd = HOST_APP.uiapp.MainWindowHandle if HOST_APP else System.IntPtr.Zero
            if hwnd != System.IntPtr.Zero:
                WindowInteropHelper(self.win).Owner = hwnd
        except Exception:
            pass

        self._bind_controls()
        self._populate_initial_values()
        self._suppress_events = False

        last_csv = to_text(self.saved.get("csv_path", ""))
        if last_csv and os.path.isfile(last_csv):
            self.load_csv_file(last_csv)

    def _bind_controls(self):
        w = self.win
        self.lbl_coord_summary = w.FindName("lbl_coord_summary")
        self.txt_csv_path = w.FindName("txt_csv_path")
        self.btn_browse = w.FindName("btn_browse")
        self.btn_sample = w.FindName("btn_sample")

        self.cb_coord_sys = w.FindName("cb_coord_sys")
        self.cb_units = w.FindName("cb_units")
        self.cb_elev_datum = w.FindName("cb_elev_datum")
        self.cb_delimiter = w.FindName("cb_delimiter")

        self.cb_col_no = w.FindName("cb_col_no")
        self.cb_col_e = w.FindName("cb_col_e")
        self.cb_col_n = w.FindName("cb_col_n")
        self.cb_col_cutoff = w.FindName("cb_col_cutoff")
        self.cb_col_len = w.FindName("cb_col_len")
        self.cb_col_tip = w.FindName("cb_col_tip")
        self.cb_col_type = w.FindName("cb_col_type")
        self.cb_col_rot = w.FindName("cb_col_rot")

        self.cb_level = w.FindName("cb_level")
        self.cb_workset = w.FindName("cb_workset")
        self.cb_family = w.FindName("cb_family")
        self.cb_default_type = w.FindName("cb_default_type")
        self.cb_target_param = w.FindName("cb_target_param")
        self.cb_len_param = w.FindName("cb_len_param")
        self.cb_mode = w.FindName("cb_mode")
        self.txt_tol_mm = w.FindName("txt_tol_mm")

        self.chk_write_ne = w.FindName("chk_write_ne")
        self.chk_export_qa = w.FindName("chk_export_qa")
        self.chk_select_after = w.FindName("chk_select_after")

        self.lbl_preview_stats = w.FindName("lbl_preview_stats")
        self.btn_export_qa = w.FindName("btn_export_qa")
        self.dg_preview = w.FindName("dg_preview")
        self.btn_run = w.FindName("btn_run")
        self.btn_cancel = w.FindName("btn_cancel")

        self.btn_browse.Click += self.on_browse
        self.btn_sample.Click += self.on_sample
        self.btn_export_qa.Click += self.on_export_qa_clicked
        self.btn_run.Click += self.on_run
        self.btn_cancel.Click += self.on_cancel

        self.cb_family.SelectionChanged += self.on_family_changed
        self.cb_delimiter.SelectionChanged += self.on_delimiter_changed
        self.txt_tol_mm.LostFocus += self.on_mapping_changed

        for cb in (
            self.cb_coord_sys, self.cb_units, self.cb_elev_datum,
            self.cb_col_no, self.cb_col_e, self.cb_col_n,
            self.cb_col_cutoff, self.cb_col_len, self.cb_col_tip,
            self.cb_col_type, self.cb_col_rot,
            self.cb_level, self.cb_default_type, self.cb_target_param, self.cb_mode,
        ):
            cb.SelectionChanged += self.on_mapping_changed

    def _populate_initial_values(self):
        self.lbl_coord_summary.Text = self.converter.summary_text

        for item in (COORD_SURVEY, COORD_PROJECT, COORD_INTERNAL):
            self.cb_coord_sys.Items.Add(item)
        self._select_combo_text(self.cb_coord_sys, self.saved.get("coord_sys"), COORD_SURVEY)

        for item in ("Meters (m)", "Millimeters (mm)", "Feet (ft)"):
            self.cb_units.Items.Add(item)
        self._select_combo_text(self.cb_units, self.saved.get("units"), "Meters (m)")

        for item in (DATUM_SURVEY, DATUM_PROJECT):
            self.cb_elev_datum.Items.Add(item)
        self._select_combo_text(self.cb_elev_datum, self.saved.get("elev_datum"), DATUM_SURVEY)

        for item in ("Auto", "Comma (,)", "Semicolon (;)", "Tab (\\t)"):
            self.cb_delimiter.Items.Add(item)
        self.cb_delimiter.SelectedIndex = 0

        for item in (MODE_UPSERT, MODE_SKIP, MODE_CREATE_ALL):
            self.cb_mode.Items.Add(item)
        self._select_combo_text(self.cb_mode, self.saved.get("mode"), MODE_UPSERT)

        if self.doc.IsWorkshared and self.worksets:
            self.cb_workset.Items.Add(ACTIVE_WS_LABEL)
            for ws_name, _ in self.worksets:
                self.cb_workset.Items.Add(ws_name)
            self._select_combo_text(self.cb_workset, self.saved.get("workset_name"), ACTIVE_WS_LABEL)
        else:
            self.cb_workset.Items.Add(NON_WS_LABEL)
            self.cb_workset.SelectedIndex = 0
            self.cb_workset.IsEnabled = False

        active_lvl_name = None
        try:
            gen_lvl = self.doc.ActiveView.GenLevel
            if gen_lvl:
                active_lvl_name = to_text(gen_lvl.Name)
        except Exception:
            pass

        for lv in self.levels:
            self.cb_level.Items.Add(to_text(lv.Name))
        self._select_combo_text(
            self.cb_level,
            self.saved.get("level_name") or active_lvl_name,
            to_text(self.levels[0].Name) if self.levels else None,
        )

        for fp in self.fam_packs:
            self.cb_family.Items.Add(fp.display_label)
        self._select_combo_text(
            self.cb_family,
            self.saved.get("family_label"),
            self.fam_packs[0].display_label if self.fam_packs else None,
        )
        self._refresh_family_dependents()

        self.txt_tol_mm.Text = to_text(self.saved.get("tol_mm", "75.0"))
        self.chk_write_ne.IsChecked = bool(self.saved.get("write_ne", True))
        self.chk_export_qa.IsChecked = bool(self.saved.get("export_qa", True))
        self.chk_select_after.IsChecked = bool(self.saved.get("select_after", True))

    @staticmethod
    def _select_combo_text(combo, preferred_text, fallback_text=None):
        if preferred_text:
            for i in range(combo.Items.Count):
                if to_text(combo.Items[i]) == to_text(preferred_text):
                    combo.SelectedIndex = i
                    return
        if fallback_text:
            for i in range(combo.Items.Count):
                if to_text(combo.Items[i]) == to_text(fallback_text):
                    combo.SelectedIndex = i
                    return
        if combo.Items.Count > 0 and combo.SelectedIndex < 0:
            combo.SelectedIndex = 0

    def get_selected_family_pack(self):
        idx = self.cb_family.SelectedIndex
        if 0 <= idx < len(self.fam_packs):
            return self.fam_packs[idx]
        return None

    def get_selected_level(self):
        idx = self.cb_level.SelectedIndex
        if 0 <= idx < len(self.levels):
            return self.levels[idx]
        return None

    def get_selected_workset_id(self):
        if not self.doc.IsWorkshared or not self.worksets:
            return None
        chosen = to_text(self.cb_workset.SelectedItem)
        if not chosen or chosen in (ACTIVE_WS_LABEL, NON_WS_LABEL):
            return None
        for ws_name, ws_id in self.worksets:
            if ws_name == chosen:
                return ws_id
        return None

    def get_tolerance_mm(self):
        val = parse_float_clean(self.txt_tol_mm.Text)
        return val if (val is not None and val >= 0.0) else 75.0

    def _refresh_family_dependents(self):
        fp = self.get_selected_family_pack()
        self.cb_default_type.Items.Clear()
        self.cb_target_param.Items.Clear()
        self.cb_len_param.Items.Clear()
        if fp is None:
            return

        for t_name in sorted(fp.symbols.keys(), key=lambda s: s.lower()):
            self.cb_default_type.Items.Add(t_name)
        self._select_combo_text(self.cb_default_type, self.saved.get("default_type"))

        all_params, num_params = discover_family_parameters(self.doc, fp)
        for p_name in all_params:
            self.cb_target_param.Items.Add(p_name)
        self._select_combo_text(self.cb_target_param, self.saved.get("target_param"), "Mark")

        self.cb_len_param.Items.Add(AUTO_LEN_PARAM)
        for np_name in num_params:
            self.cb_len_param.Items.Add(np_name)
        self._select_combo_text(self.cb_len_param, self.saved.get("len_param"), AUTO_LEN_PARAM)

    def on_family_changed(self, _sender, _args):
        if self._suppress_events:
            return
        self._suppress_events = True
        self._refresh_family_dependents()
        self._suppress_events = False
        self.rebuild_preview()

    def on_delimiter_changed(self, _sender, _args):
        if self._suppress_events:
            return
        path = to_text(self.txt_csv_path.Text).strip()
        if path and os.path.isfile(path):
            self.load_csv_file(path)

    def on_mapping_changed(self, _sender, _args):
        if self._suppress_events:
            return
        self.rebuild_preview()

    def on_browse(self, _sender, _args):
        dlg = OpenFileDialog()
        dlg.Title = "Select Pile / Foundation Survey CSV"
        dlg.Filter = "CSV & Text Files (*.csv;*.txt)|*.csv;*.txt|All Files (*.*)|*.*"
        cur = to_text(self.txt_csv_path.Text).strip()
        if cur and os.path.isdir(os.path.dirname(cur)):
            dlg.InitialDirectory = os.path.dirname(cur)
        if dlg.ShowDialog() is True:
            self.load_csv_file(dlg.FileName)

    def on_sample(self, _sender, _args):
        try:
            ensure_and_open_sample_csv(self.script_dir)
        except Exception as ex:
            forms.alert("Cannot open sample CSV:\n{}".format(ex), title="Import Piles Pro", warn_icon=True)

    def on_export_qa_clicked(self, _sender, _args):
        if not self.parsed_records:
            forms.alert("Load a CSV file first to export the QA Deviation Report.", title="Import Piles Pro", warn_icon=True)
            return
        sfd = SaveFileDialog()
        sfd.Title = "Save Pile Deviation QA Report"
        sfd.Filter = "CSV Report (*.csv)|*.csv"
        sfd.FileName = "Pile_Deviation_QA_{}.csv".format(time.strftime("%Y%m%d_%H%M"))
        cur = to_text(self.txt_csv_path.Text).strip()
        if cur and os.path.isdir(os.path.dirname(cur)):
            sfd.InitialDirectory = os.path.dirname(cur)
        if sfd.ShowDialog() is True:
            try:
                write_qa_deviation_csv(sfd.FileName, self.parsed_records, self.get_tolerance_mm())
                forms.toast("Saved QA Report:\n{}".format(sfd.FileName), title="Pile Deviation QA")
            except Exception as ex:
                forms.alert("Failed to write QA CSV:\n{}".format(ex), title="Export Error", warn_icon=True)

    def load_csv_file(self, filepath):
        try:
            delim_choice = to_text(self.cb_delimiter.SelectedItem or "Auto")
            headers, rows = read_raw_csv_table(filepath, delimiter_choice=delim_choice)
        except Exception as ex:
            forms.alert("Failed to read CSV file:\n{}".format(ex), title="CSV Error", warn_icon=True)
            return

        self._suppress_events = True
        self.txt_csv_path.Text = filepath
        self.csv_headers = headers
        self.csv_raw_rows = rows

        req_combos = (self.cb_col_no, self.cb_col_e, self.cb_col_n)
        opt_combos = (self.cb_col_cutoff, self.cb_col_len, self.cb_col_tip, self.cb_col_type, self.cb_col_rot)

        for cb in req_combos:
            cb.Items.Clear()
            for h in headers:
                cb.Items.Add(h)

        for cb in opt_combos:
            cb.Items.Clear()
            cb.Items.Add(NONE_COL)
            for h in headers:
                cb.Items.Add(h)

        pick_no = auto_pick_column(headers, ["pile_no", "pile", "mark", "number", "no", "id", "name"], ["no", "mark", "pile_no"])
        pick_e = auto_pick_column(headers, ["east", "coord_e", "utm_e"], ["e", "x", "easting"])
        pick_n = auto_pick_column(headers, ["north", "coord_n", "utm_n"], ["n", "y", "northing"])
        pick_cut = auto_pick_column(headers, ["cut", "top_elev", "bof", "cutoff"], ["z", "cutoff", "cutoff_elev", "elev"])
        pick_len = auto_pick_column(headers, ["pile_len", "length", "depth", "embed"], ["length", "pile_length", "l"])
        pick_tip = auto_pick_column(headers, ["tip", "toe", "bottom_elev", "bot_elev"], ["tip", "toe", "tip_elev"])
        pick_typ = auto_pick_column(headers, ["type", "size", "section", "symbol"], ["type"])
        pick_rot = auto_pick_column(headers, ["rot", "angle", "deg", "bearing"], ["rotation", "angle"])

        fb_h0 = headers[0] if len(headers) > 0 else None
        fb_h1 = headers if len(headers) > 1 else fb_h0
        fb_h2 = headers if len(headers) > 2 else fb_h0

        self._select_combo_text(self.cb_col_no, pick_no if pick_no != NONE_COL else fb_h0)
        self._select_combo_text(self.cb_col_e, pick_e if pick_e != NONE_COL else fb_h1)
        self._select_combo_text(self.cb_col_n, pick_n if pick_n != NONE_COL else fb_h2)
        self._select_combo_text(self.cb_col_cutoff, pick_cut, NONE_COL)
        self._select_combo_text(self.cb_col_len, pick_len, NONE_COL)
        self._select_combo_text(self.cb_col_tip, pick_tip, NONE_COL)
        self._select_combo_text(self.cb_col_type, pick_typ, NONE_COL)
        self._select_combo_text(self.cb_col_rot, pick_rot, NONE_COL)

        self._suppress_events = False
        self.rebuild_preview()

    def rebuild_preview(self):
        self.parsed_records = []
        dt = DataTable()
        for col_title in (
            "Row", "Pile_No", "Easting", "Northing", "CutOff", "Length_m",
            "Resolved_Type", "Offset_mm", "QA_Status", "Action"
        ):
            dt.Columns.Add(col_title)

        if not self.csv_raw_rows:
            self.dg_preview.ItemsSource = dt.DefaultView
            self.lbl_preview_stats.Text = u"No CSV rows loaded."
            return

        fp = self.get_selected_family_pack()
        base_level = self.get_selected_level()
        base_elev_ft = base_level.Elevation if base_level else 0.0

        def_type_name = to_text(self.cb_default_type.SelectedItem or "")
        type_lookup = {k.strip().lower(): k for k in (fp.symbols.keys() if fp else [])}

        unit_label = to_text(self.cb_units.SelectedItem or "Meters (m)")
        unit_factor = UNIT_TO_FEET.get(unit_label, FEET_PER_METER)
        mm_per_unit = UNIT_TO_MM.get(unit_label, 1000.0)
        coord_mode = to_text(self.cb_coord_sys.SelectedItem or COORD_SURVEY)
        datum_mode = to_text(self.cb_elev_datum.SelectedItem or DATUM_SURVEY)

        target_param = to_text(self.cb_target_param.SelectedItem or "Mark")
        mode = to_text(self.cb_mode.SelectedItem or MODE_UPSERT)
        tol_mm = self.get_tolerance_mm()
        existing_map = index_existing_elements_by_key(self.doc, fp, target_param) if fp else {}

        col_no = to_text(self.cb_col_no.SelectedItem or "")
        col_e = to_text(self.cb_col_e.SelectedItem or "")
        col_n = to_text(self.cb_col_n.SelectedItem or "")
        col_cut = to_text(self.cb_col_cutoff.SelectedItem or NONE_COL)
        col_len = to_text(self.cb_col_len.SelectedItem or NONE_COL)
        col_tip = to_text(self.cb_col_tip.SelectedItem or NONE_COL)
        col_typ = to_text(self.cb_col_type.SelectedItem or NONE_COL)
        col_rot = to_text(self.cb_col_rot.SelectedItem or NONE_COL)

        invalid_cnt = 0
        create_cnt = 0
        update_cnt = 0
        skip_cnt = 0
        locked_cnt = 0
        over_tol_cnt = 0

        for idx, r in enumerate(self.csv_raw_rows, start=1):
            p_no = to_text(r.get(col_no, "")).strip()
            e_val = parse_float_clean(r.get(col_e))
            n_val = parse_float_clean(r.get(col_n))
            c_val = parse_float_clean(r.get(col_cut)) if col_cut != NONE_COL else None
            len_val = parse_float_clean(r.get(col_len)) if col_len != NONE_COL else None
            tip_val = parse_float_clean(r.get(col_tip)) if col_tip != NONE_COL else None
            rot_val = parse_float_clean(r.get(col_rot)) if col_rot != NONE_COL else 0.0
            if rot_val is None:
                rot_val = 0.0

            raw_t = to_text(r.get(col_typ, "")).strip() if col_typ != NONE_COL else u""
            matched_t_name = type_lookup.get(raw_t.lower(), def_type_name) if raw_t else def_type_name
            used_fallback = bool(raw_t and raw_t.lower() not in type_lookup)

            if not p_no or e_val is None or n_val is None:
                invalid_cnt += 1
                if idx <= 250:
                    dt.Rows.Add(
                        str(r.get("__line__", idx)), p_no or "<Missing>",
                        to_text(r.get(col_e, "")), to_text(r.get(col_n, "")),
                        "-", "-", "-", "-", "INVALID", "SKIP (Invalid)"
                    )
                continue

            # Resolve individual Pile Length (in internal feet)
            int_cutoff_z = self.converter.to_internal_z(c_val, unit_factor, datum_mode) if c_val is not None else None
            top_z_ft = int_cutoff_z if int_cutoff_z is not None else base_elev_ft

            length_ft = None
            if len_val is not None and len_val > 0.0:
                length_ft = float(len_val) * unit_factor
            elif tip_val is not None:
                int_tip_z = self.converter.to_internal_z(tip_val, unit_factor, datum_mode)
                length_ft = abs(top_z_ft - int_tip_z)

            existing_inst = existing_map.get(p_no.lower())
            lock_owner = u""
            old_e = None
            old_n = None
            de_mm = None
            dn_mm = None
            offset_mm = None
            qa_status = u"NEW"

            if existing_inst is not None:
                lock_owner = get_worksharing_lock_owner(self.doc, existing_inst.Id)
                loc_obj = existing_inst.Location
                if isinstance(loc_obj, LocationPoint):
                    old_e, old_n = self.converter.from_internal_to_input_xy(
                        loc_obj.Point, unit_factor, coord_mode
                    )
                    de_mm = (e_val - old_e) * mm_per_unit
                    dn_mm = (n_val - old_n) * mm_per_unit
                    offset_mm = math.hypot(de_mm, dn_mm)
                    if offset_mm > tol_mm:
                        qa_status = u"OVER TOL! (>{:.0f}mm)".format(tol_mm)
                        over_tol_cnt += 1
                    else:
                        qa_status = u"OK (<={:.0f}mm)".format(tol_mm)

            if existing_inst is not None and mode == MODE_UPSERT:
                if lock_owner:
                    action_lbl = u"LOCKED ({})".format(lock_owner)
                    locked_cnt += 1
                else:
                    action_lbl = u"UPDATE Existing"
                    update_cnt += 1
            elif existing_inst is not None and mode == MODE_SKIP:
                action_lbl = u"SKIP (Exists)"
                skip_cnt += 1
            else:
                action_lbl = u"CREATE New"
                create_cnt += 1

            self.parsed_records.append({
                "line": r.get("__line__", idx),
                "no": p_no,
                "e": e_val,
                "n": n_val,
                "cutoff": c_val,
                "int_cutoff_z": int_cutoff_z,
                "length_ft": length_ft,
                "csv_type_raw": raw_t,
                "resolved_type_name": matched_t_name,
                "rot_deg": rot_val,
                "existing_inst": existing_inst,
                "lock_owner": lock_owner,
                "old_e": old_e,
                "old_n": old_n,
                "de_mm": de_mm,
                "dn_mm": dn_mm,
                "offset_mm": offset_mm,
                "qa_status": qa_status,
                "action_label": action_lbl,
            })

            if idx <= 250:
                t_disp = u"{} (Fallback)".format(matched_t_name) if used_fallback else matched_t_name
                len_disp = "{:.2f}".format(length_ft * METERS_PER_FOOT) if length_ft is not None else "-"
                off_disp = "{:.1f}".format(offset_mm) if offset_mm is not None else "-"
                dt.Rows.Add(
                    str(r.get("__line__", idx)),
                    p_no,
                    "{:,.3f}".format(e_val),
                    "{:,.3f}".format(n_val),
                    "{:+.3f}".format(c_val) if c_val is not None else "-",
                    len_disp,
                    t_disp,
                    off_disp,
                    qa_status,
                    action_lbl,
                )

        self.dg_preview.ItemsSource = dt.DefaultView
        self.lbl_preview_stats.Text = (
            u"Create: {} | Update: {} | Over-Tol: {} | Locked: {} | Skip: {} | Invalid: {}".format(
                create_cnt, update_cnt, over_tol_cnt, locked_cnt, skip_cnt, invalid_cnt
            )
        )

    def on_run(self, _sender, _args):
        if not self.parsed_records:
            forms.alert("Please select a valid CSV file with at least 1 valid coordinate row.", title="Import Piles Pro", warn_icon=True)
            return
        if self.get_selected_level() is None or self.get_selected_family_pack() is None:
            forms.alert("Please select both a Host Level and a 3D Model Family.", title="Import Piles Pro", warn_icon=True)
            return

        save_user_settings({
            "csv_path": to_text(self.txt_csv_path.Text).strip(),
            "coord_sys": to_text(self.cb_coord_sys.SelectedItem),
            "units": to_text(self.cb_units.SelectedItem),
            "elev_datum": to_text(self.cb_elev_datum.SelectedItem),
            "level_name": to_text(self.cb_level.SelectedItem),
            "workset_name": to_text(self.cb_workset.SelectedItem),
            "family_label": to_text(self.cb_family.SelectedItem),
            "default_type": to_text(self.cb_default_type.SelectedItem),
            "target_param": to_text(self.cb_target_param.SelectedItem),
            "len_param": to_text(self.cb_len_param.SelectedItem),
            "mode": to_text(self.cb_mode.SelectedItem),
            "tol_mm": "{:.1f}".format(self.get_tolerance_mm()),
            "write_ne": bool(self.chk_write_ne.IsChecked),
            "export_qa": bool(self.chk_export_qa.IsChecked),
            "select_after": bool(self.chk_select_after.IsChecked),
        })

        self.confirmed = True
        self.win.Close()

    def on_cancel(self, _sender, _args):
        self.confirmed = False
        self.win.Close()


# ------------------------------------------------------------------------------
# BATCH TRANSACTION EXECUTION (WORKSHARING-SAFE + WARNING SUPPRESSED)
# ------------------------------------------------------------------------------
def execute_pile_import(uidoc, ctrl):
    doc = uidoc.Document
    fp = ctrl.get_selected_family_pack()
    base_level = ctrl.get_selected_level()
    target_ws_id = ctrl.get_selected_workset_id()
    def_type_name = to_text(ctrl.cb_default_type.SelectedItem)
    default_sym = fp.symbols.get(def_type_name)

    unit_label = to_text(ctrl.cb_units.SelectedItem)
    unit_factor = UNIT_TO_FEET.get(unit_label, FEET_PER_METER)
    coord_mode = to_text(ctrl.cb_coord_sys.SelectedItem)
    dup_mode = to_text(ctrl.cb_mode.SelectedItem)
    target_param = to_text(ctrl.cb_target_param.SelectedItem)
    preferred_len_param = to_text(ctrl.cb_len_param.SelectedItem)
    tol_mm = ctrl.get_tolerance_mm()

    write_ne = bool(ctrl.chk_write_ne.IsChecked)
    export_qa = bool(ctrl.chk_export_qa.IsChecked)
    select_after = bool(ctrl.chk_select_after.IsChecked)

    st_type = StructuralType.NonStructural
    cat_lower = fp.category_name.lower()
    if "foundation" in cat_lower:
        st_type = StructuralType.Footing
    elif "structural" in cat_lower and "column" in cat_lower:
        st_type = StructuralType.Column

    created_cnt = 0
    updated_cnt = 0
    skipped_cnt = 0
    locked_skips = []
    over_tol_cnt = 0
    errors = []
    touched_ids = []

    records = ctrl.parsed_records
    total = len(records)
    fail_proc = PileBatchFailuresPreprocessor()

    t = Transaction(doc, "P13 Import 3D Piles from CSV (Pro v2.0)")
    t.Start()

    try:
        fh_opts = t.GetFailureHandlingOptions()
        fh_opts.SetFailuresPreprocessor(fail_proc)
        t.SetFailureHandlingOptions(fh_opts)
    except Exception:
        pass

    try:
        if default_sym and not default_sym.IsActive:
            default_sym.Activate()

        with forms.ProgressBar(title="P13 Importing 3D Piles ({value} of {max_value})", cancellable=True) as pb:
            for idx, rec in enumerate(records, start=1):
                if pb.cancelled:
                    t.RollBack()
                    forms.toast("Operation cancelled. All changes rolled back cleanly.", title="Import Piles Pro")
                    return

                pb.update_progress(idx, total)

                try:
                    existing_inst = rec["existing_inst"]
                    if existing_inst is not None and dup_mode == MODE_SKIP:
                        skipped_cnt += 1
                        continue

                    if existing_inst is not None and dup_mode == MODE_UPSERT and rec["lock_owner"]:
                        locked_skips.append(u"{} (Owned by {})".format(rec["no"], rec["lock_owner"]))
                        continue

                    use_sym = fp.symbols.get(rec["resolved_type_name"], default_sym)
                    if use_sym is None:
                        raise RuntimeError("No valid Family Type resolved.")
                    if not use_sym.IsActive:
                        use_sym.Activate()

                    rx, ry = ctrl.converter.to_internal_xy(rec["e"], rec["n"], unit_factor, coord_mode)
                    target_pt = XYZ(rx, ry, base_level.Elevation)

                    offset_ft = None
                    if rec["int_cutoff_z"] is not None:
                        offset_ft = rec["int_cutoff_z"] - base_level.Elevation

                    if existing_inst is not None and dup_mode == MODE_UPSERT:
                        inst = existing_inst
                        if get_id_val(inst.GetTypeId()) != get_id_val(use_sym.Id):
                            inst.ChangeTypeId(use_sym.Id)

                        loc_obj = inst.Location
                        if isinstance(loc_obj, LocationPoint):
                            cur_pt = loc_obj.Point
                            delta = XYZ(target_pt.X - cur_pt.X, target_pt.Y - cur_pt.Y, 0.0)
                            if delta.GetLength() > 1e-6:
                                ElementTransformUtils.MoveElement(doc, inst.Id, delta)

                            if rec["rot_deg"] is not None:
                                target_rad = math.radians(float(rec["rot_deg"]))
                                rot_diff = target_rad - loc_obj.Rotation
                                if abs(rot_diff) > 1e-5:
                                    axis = Line.CreateBound(target_pt, target_pt + XYZ.BasisZ)
                                    ElementTransformUtils.RotateElement(doc, inst.Id, axis, rot_diff)

                        if rec["offset_mm"] is not None and rec["offset_mm"] > tol_mm:
                            over_tol_cnt += 1
                        updated_cnt += 1
                    else:
                        inst = doc.Create.NewFamilyInstance(target_pt, use_sym, base_level, st_type)
                        if abs(float(rec["rot_deg"])) > 1e-5:
                            axis = Line.CreateBound(target_pt, target_pt + XYZ.BasisZ)
                            ElementTransformUtils.RotateElement(doc, inst.Id, axis, math.radians(float(rec["rot_deg"])))
                        created_cnt += 1

                    assign_element_workset(inst, target_ws_id)
                    apply_level_and_cutoff_offset(inst, base_level, offset_ft)
                    apply_pile_length_3d(inst, base_level, offset_ft, rec["length_ft"], preferred_len_param)

                    set_param_unit_aware(inst, target_param, rec["no"], value_unit="raw")

                    # Compose clean diagnostic Comments
                    comment_parts = []
                    if rec["csv_type_raw"]:
                        comment_parts.append(u"Type: {}".format(rec["csv_type_raw"]))
                    if write_ne and rec["offset_mm"] is not None:
                        comment_parts.append(
                            u"dE={:+.1f}mm, dN={:+.1f}mm, Offset={:.1f}mm [{}]".format(
                                rec["de_mm"], rec["dn_mm"], rec["offset_mm"], rec["qa_status"]
                            )
                        )
                    if comment_parts:
                        set_param_unit_aware(inst, "Comments", u" | ".join(comment_parts), value_unit="raw")

                    if write_ne:
                        e_meters = rec["e"] * unit_factor * METERS_PER_FOOT
                        n_meters = rec["n"] * unit_factor * METERS_PER_FOOT
                        set_param_unit_aware(inst, "E_Coordinate", e_meters, value_unit="meters")
                        set_param_unit_aware(inst, "N_Coordinate", n_meters, value_unit="meters")
                        if rec["offset_mm"] is not None:
                            set_param_unit_aware(inst, "Pile_Deviation_mm", rec["offset_mm"], value_unit="mm")
                            set_param_unit_aware(inst, "dE_mm", rec["de_mm"], value_unit="mm")
                            set_param_unit_aware(inst, "dN_mm", rec["dn_mm"], value_unit="mm")

                    touched_ids.append(inst.Id)
                except Exception as row_ex:
                    errors.append(u"Row {} ({}): {}".format(rec["line"], rec["no"], to_text(row_ex)))

        t.Commit()
    except Exception as fatal_ex:
        if t.HasStarted():
            t.RollBack()
        forms.alert(
            u"Transaction aborted and rolled back:\n{}\n\n{}".format(fatal_ex, traceback.format_exc()),
            title="Import Piles Pro - Error",
            warn_icon=True,
        )
        return

    # Auto-export QA report next to CSV if enabled and existing piles were compared
    qa_report_path = u""
    if export_qa and updated_cnt > 0:
        try:
            src_csv = to_text(ctrl.txt_csv_path.Text).strip()
            base_dir = os.path.dirname(src_csv) if (src_csv and os.path.isdir(os.path.dirname(src_csv))) else get_settings_dir()
            src_stem = os.path.splitext(os.path.basename(src_csv))[0] if src_csv else "Piles"
            qa_report_path = os.path.join(base_dir, u"{}_Deviation_QA_Report.csv".format(src_stem))
            write_qa_deviation_csv(qa_report_path, records, tol_mm)
        except Exception:
            qa_report_path = u""

    if select_after and touched_ids:
        try:
            id_list = System.Collections.Generic.List[ElementId](touched_ids)
            uidoc.Selection.SetElementIds(id_list)
        except Exception:
            pass

    summary = (
        u"Import / Update Complete!\n\n"
        u"- Created new 3D elements : {}\n"
        u"- Updated existing elements : {}\n"
        u"- Over tolerance (>{:.0f} mm) : {}\n"
        u"- Skipped (Existing / Locked) : {} / {}\n"
        u"- Suppressed Revit warnings : {}\n"
        u"- Row errors : {}".format(
            created_cnt,
            updated_cnt,
            tol_mm,
            over_tol_cnt,
            skipped_cnt,
            len(locked_skips),
            fail_proc.suppressed_warnings,
            len(errors),
        )
    )
    if qa_report_path:
        summary += u"\n\nAs-Built QA CSV Report saved to:\n{}".format(qa_report_path)
    if locked_skips:
        summary += u"\n\nSkipped Worksharing-locked piles:\n" + u"\n".join(locked_skips[:8])
    if errors:
        summary += u"\n\nFirst errors:\n" + u"\n".join(errors[:8])

    forms.alert(summary, title="P13 Import 3D Piles (Pro v2.0)")


def main():
    uidoc = getattr(__revit__, "ActiveUIDocument", None)  # noqa: F821
    if uidoc is None or uidoc.Document is None:
        forms.alert("No active Revit project document found.", title="Import Piles Pro", warn_icon=True)
        return

    doc = uidoc.Document
    if doc.IsFamilyDocument:
        forms.alert("Please run this command inside a Revit Project (.rvt), not the Family Editor.", title="Import Piles Pro", warn_icon=True)
        return

    levels = list(FilteredElementCollector(doc).OfClass(Level).ToElements())
    if not levels:
        forms.alert("No Levels found in the active project.", title="Import Piles Pro", warn_icon=True)
        return

    fam_packs = collect_3d_point_families(doc)
    if not fam_packs:
        forms.alert(
            "No point-based 3D Model families (Structural Foundations, Structural Columns, Columns, or Generic Models) are loaded in this project.",
            title="Import Piles Pro",
            warn_icon=True,
        )
        return

    worksets = collect_user_worksets(doc)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    converter = CoordinateConverter(doc)

    ctrl = ImportPilesProController(doc, levels, fam_packs, worksets, converter, script_dir)
    ctrl.win.ShowDialog()
    if ctrl.confirmed:
        execute_pile_import(uidoc, ctrl)


if __name__ == "__main__":
    main()