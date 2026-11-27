# -*- coding: utf-8 -*-
# pylint: disable=import-error,invalid-name,broad-except,too-many-lines
"""Import 3D Piles & Foundations from CSV Survey Coordinates (Pro Edition)."""
from __future__ import print_function, division

__title__ = "Import Piles\n(3D CSV)"
__author__ = "Permpong Taweekul (P13)"
__doc__ = "Import or update 3D Model Families (Piles/Foundations/Columns) from CSV coordinates."

import os
import io
import re
import csv
import sys
import json
import math
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
from Microsoft.Win32 import OpenFileDialog

from Autodesk.Revit.DB import (
    BasePoint,
    BuiltInCategory,
    BuiltInParameter,
    Category,
    CategoryType,
    ElementId,
    ElementTransformUtils,
    Family,
    FamilyInstance,
    FamilyPlacementType,
    FilteredElementCollector,
    Line,
    Level,
    LocationPoint,
    ProjectLocation,
    StorageType,
    Transaction,
    Transform,
    XYZ,
)
from Autodesk.Revit.DB.Structure import StructuralType

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
FEET_PER_METER = 1.0 / METERS_PER_FOOT
UNIT_TO_FEET = {
    "Meters (m)": FEET_PER_METER,
    "Millimeters (mm)": 1.0 / 304.8,
    "Feet (ft)": 1.0,
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


def get_settings_path():
    appdata = to_text(os.environ.get("APPDATA") or os.path.expanduser("~"))
    folder = os.path.join(appdata, u"pyRevit", u"P13", u"ImportPiles3D")
    if not os.path.isdir(folder):
        try:
            os.makedirs(folder)
        except Exception:
            pass
    return os.path.join(folder, u"last_settings.json")


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
    # Strip trailing unit suffixes such as 'm' or 'EL.'
    txt = re.sub(r"^(?:el\.?|elev\.?)\s*", "", txt, flags=re.IGNORECASE)
    txt = re.sub(r"\s*(?:m|mm|ft)$", "", txt, flags=re.IGNORECASE)
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
# EXACT REVIT COORDINATE TRANSFORMATION ENGINE
# ------------------------------------------------------------------------------
class CoordinateConverter(object):
    """Exact matrix-based converter between Survey/Project/Internal and Revit Internal Feet."""

    def __init__(self, doc):
        self.doc = doc
        self.survey_to_internal = self._resolve_survey_to_internal_transform(doc)
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
        """Return the internal XYZ location (in feet) of the Project Base Point."""
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
            return u"Base Point Shared -> E: {:,.3f} m  |  N: {:,.3f} m  |  Elev: {:+.3f} m  |  Angle: {:.3f} deg".format(
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

    def to_internal_z(self, elev_val, unit_factor, datum_mode):
        z_ft = float(elev_val) * unit_factor
        if datum_mode == DATUM_SURVEY:
            pt_int = self.survey_to_internal.OfPoint(XYZ(0.0, 0.0, z_ft))
            return pt_int.Z
        return self.pbp_origin_internal.Z + z_ft


# ------------------------------------------------------------------------------
# 3D MODEL FAMILY & PARAMETER DISCOVERY (ZERO DUMMY TRANSACTIONS)
# ------------------------------------------------------------------------------
class FamilyPack(object):
    def __init__(self, fam_name, cat_name, cat_id_val):
        self.name = fam_name
        self.category_name = cat_name
        self.category_id_val = cat_id_val
        self.symbols = {}  # {type_name: FamilySymbol}

    @property
    def display_label(self):
        return u"[{}] {}".format(self.category_name, self.name)


def collect_3d_point_families(doc):
    """Collect strictly point-based 3D Model families; 100% excludes 2D Detail Items & Beams."""
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

            # Ensure family is point-placed on a level (blocks curve beams & face-hosted families)
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


def get_writable_instance_parameters(doc, fam_pack):
    """Discover writable text/number instance parameters without starting any transaction."""
    names = set(["Mark", "Comments"])

    # 1. Inspect project/shared ParameterBindings bound to this category
    try:
        it = doc.ParameterBindings.ForwardIterator()
        it.Reset()
        while it.MoveNext():
            defn = it.Key
            binding = it.Current
            # Skip TypeBinding; we want InstanceBinding
            if binding.__class__.__name__ == "TypeBinding":
                continue
            cats = getattr(binding, "Categories", None)
            if cats:
                for c in cats:
                    if c and get_id_val(c.Id) == fam_pack.category_id_val:
                        if defn and defn.Name:
                            names.add(to_text(defn.Name))
                        break
    except Exception:
        pass

    # 2. If at least one instance of this family already exists in the model, inspect its parameters
    try:
        sym_ids = set(get_id_val(s.Id) for s in fam_pack.symbols.values())
        bic_target = None
        for bic in ALLOWED_3D_BIC_LIST:
            cat = Category.GetCategory(doc, bic)
            if cat and get_id_val(cat.Id) == fam_pack.category_id_val:
                bic_target = bic
                break

        if bic_target is not None:
            col = (
                FilteredElementCollector(doc)
                .OfCategory(bic_target)
                .WhereElementIsNotElementType()
            )
            for inst in col:
                if get_id_val(inst.GetTypeId()) in sym_ids:
                    for p in inst.Parameters:
                        if not p.IsReadOnly and p.StorageType in (
                            StorageType.String,
                            StorageType.Double,
                            StorageType.Integer,
                        ):
                            if p.Definition and p.Definition.Name:
                                names.add(to_text(p.Definition.Name))
                    break
    except Exception:
        pass

    return sorted(list(names), key=lambda s: (0 if s == "Mark" else 1, s.lower()))


# ------------------------------------------------------------------------------
# ROBUST MULTI-ENCODING CSV READER & COLUMN AUTO-DETECTOR
# ------------------------------------------------------------------------------
def decode_csv_bytes(raw_bytes):
    for enc in ("utf-8-sig", "utf-8", "cp874", "tis-620", "latin-1"):
        try:
            return raw_bytes.decode(enc)
        except Exception:
            continue
    return raw_bytes.decode("latin-1", errors="ignore")


def read_raw_csv_table(filepath, delimiter_choice="Auto"):
    """Return (headers_list, list_of_row_dicts) supporting Thai UTF-8/CP874 and custom delimiters."""
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
        counts = [(",", sample_head.count(",")), (";", sample_head.count(";")), ("\t", sample_head.count("\t"))]
        counts.sort(key=lambda item: item, reverse=True)
        delim = counts[0][0] if counts[0] > 0 else ","

    headers = []
    rows_out = []

    if PY2:
        encoded_lines = [ln.encode("utf-8") for ln in lines]
        reader = csv.reader(encoded_lines, delimiter=str(delim))
        raw_rows = [[cell.decode("utf-8") for cell in r] for r in reader]
    else:
        reader = csv.reader(lines, delimiter=delim)
        raw_rows = list(reader)

    if not raw_rows:
        return [], []

    seen = {}
    for idx, h in enumerate(raw_rows[0]):
        clean_h = to_text(h).strip() or u"Col_{}".format(idx + 1)
        if clean_h in seen:
            seen[clean_h] += 1
            clean_h = u"{}_{}".format(clean_h, seen[clean_h])
        else:
            seen[clean_h] = 1
        headers.append(clean_h)

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
            u"Pile_No,Easting,Northing,CutOff_Elev,Type,Rotation_Deg\n"
            u"P-01,665120.500,1521340.250,-1.250,I-0.26x0.26,0\n"
            u"P-02,665124.500,1521340.250,-1.250,I-0.26x0.26,0\n"
            u"P-03,665120.500,1521345.250,-1.400,I-0.30x0.30,90\n"
        )
        with io.open(sample_path, "w", encoding="utf-8-sig") as f:
            f.write(sample_content)

    psi = ProcessStartInfo(sample_path)
    psi.UseShellExecute = True
    Process.Start(psi)


# ------------------------------------------------------------------------------
# ELEMENT PARAMETER & PLACEMENT ENGINE
# ------------------------------------------------------------------------------
def set_param_flexible(element, param_name, val, is_length_feet=False):
    """Write parameter safely across String, Double, or Integer storage."""
    if not param_name or val is None:
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
                p.Set(to_text(val))
                return True
            if st == StorageType.Double:
                f_val = float(val)
                p.Set(f_val)
                return True
            if st == StorageType.Integer:
                p.Set(int(round(float(val))))
                return True
        except Exception:
            continue
    return False


def apply_level_and_cutoff_offset(inst, base_level, offset_ft):
    """Ensure host level and vertical offset are accurately applied for Foundations & Columns."""
    # Ensure host level matches selected base_level when writable
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

    # BuiltInParameters for vertical offset across Structural Foundations, Columns, and Generic Models
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
        if set_param_flexible(inst, p_name, offset_ft, is_length_feet=True):
            return


def index_existing_elements_by_key(doc, fam_pack, target_param_name):
    """Build {normalized_pile_no: FamilyInstance} map for Smart Upsert / Skip Existing."""
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

        val_str = u""
        if p.StorageType == StorageType.String:
            val_str = to_text(p.AsString()).strip()
        else:
            val_str = to_text(p.AsValueString()).strip()

        if val_str:
            lookup[val_str.lower()] = inst
    return lookup


# ------------------------------------------------------------------------------
# REVIT-NATIVE WPF UI (P13 PRO DESIGN)
# ------------------------------------------------------------------------------
IMPORT_PILES_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="P13 - Import 3D Piles &amp; Foundations from CSV (Pro)"
        Width="880" Height="720" MinWidth="780" MinHeight="620"
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
                    <TextBlock Text="Import 3D Piles &amp; Foundations from CSV" FontSize="16" FontWeight="SemiBold" Foreground="#FFFFFF"/>
                    <TextBlock Name="lbl_coord_summary" Text="Loading project coordinate system..." FontSize="11.5" Foreground="#9CA3AF" Margin="0,3,0,0"/>
                </StackPanel>
                <Border Grid.Column="1" Background="#0F766E" CornerRadius="4" Padding="10,4" VerticalAlignment="Center">
                    <TextBlock Text="3D MODEL ONLY (NO 2D DETAIL ITEMS)" FontSize="10.5" FontWeight="Bold" Foreground="#FFFFFF"/>
                </Border>
            </Grid>
        </Border>

        <!-- Top Configuration Cards -->
        <Grid Grid.Row="1" Margin="14,12,14,8">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="1.05*"/>
                <ColumnDefinition Width="12"/>
                <ColumnDefinition Width="1.15*"/>
            </Grid.ColumnDefinitions>

            <!-- Left Card: CSV File, Coordinate System & Column Mapping -->
            <Border Grid.Column="0" Background="#FFFFFF" BorderBrush="#D1D5DB" BorderThickness="1" CornerRadius="6" Padding="12">
                <StackPanel>
                    <TextBlock Text="1. Survey CSV Source &amp; Column Mapping" FontWeight="SemiBold" Foreground="#111827" Margin="0,0,0,8"/>

                    <Grid Margin="0,0,0,6">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="76"/>
                            <ColumnDefinition Width="92"/>
                        </Grid.ColumnDefinitions>
                        <TextBox Name="txt_csv_path" IsReadOnly="True" Height="26" VerticalContentAlignment="Center" Padding="6,0" Background="#F9FAFB" BorderBrush="#D1D5DB"/>
                        <Button Name="btn_browse" Grid.Column="1" Content="Browse..." Height="26" Margin="6,0,0,0" Background="#2563EB" Foreground="#FFFFFF" BorderThickness="0" FontWeight="SemiBold"/>
                        <Button Name="btn_sample" Grid.Column="2" Content="Sample CSV" Height="26" Margin="6,0,0,0" Background="#F3F4F6" BorderBrush="#D1D5DB"/>
                    </Grid>

                    <Grid Margin="0,4,0,4">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="105"/>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="72"/>
                            <ColumnDefinition Width="115"/>
                        </Grid.ColumnDefinitions>
                        <TextBlock Text="Coord System:" VerticalAlignment="Center" Foreground="#374151"/>
                        <ComboBox Name="cb_coord_sys" Grid.Column="1" Height="25"/>
                        <TextBlock Grid.Column="2" Text="CSV Units:" VerticalAlignment="Center" Margin="8,0,0,0" Foreground="#374151"/>
                        <ComboBox Name="cb_units" Grid.Column="3" Height="25"/>
                    </Grid>

                    <Grid Margin="0,4,0,8">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="105"/>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="72"/>
                            <ColumnDefinition Width="115"/>
                        </Grid.ColumnDefinitions>
                        <TextBlock Text="Cut-Off Datum:" VerticalAlignment="Center" Foreground="#374151"/>
                        <ComboBox Name="cb_elev_datum" Grid.Column="1" Height="25"/>
                        <TextBlock Grid.Column="2" Text="Delimiter:" VerticalAlignment="Center" Margin="8,0,0,0" Foreground="#374151"/>
                        <ComboBox Name="cb_delimiter" Grid.Column="3" Height="25"/>
                    </Grid>

                    <Border BorderBrush="#E5E7EB" BorderThickness="0,1,0,0" Padding="0,8,0,0">
                        <Grid>
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="82"/>
                                <ColumnDefinition Width="*"/>
                                <ColumnDefinition Width="10"/>
                                <ColumnDefinition Width="82"/>
                                <ColumnDefinition Width="*"/>
                            </Grid.ColumnDefinitions>
                            <Grid.RowDefinitions>
                                <RowDefinition Height="28"/>
                                <RowDefinition Height="28"/>
                                <RowDefinition Height="28"/>
                            </Grid.RowDefinitions>

                            <TextBlock Grid.Row="0" Grid.Column="0" Text="Pile No *:" VerticalAlignment="Center" FontWeight="SemiBold"/>
                            <ComboBox Name="cb_col_no" Grid.Row="0" Grid.Column="1" Height="24"/>

                            <TextBlock Grid.Row="0" Grid.Column="3" Text="Type Col:" VerticalAlignment="Center"/>
                            <ComboBox Name="cb_col_type" Grid.Row="0" Grid.Column="4" Height="24"/>

                            <TextBlock Grid.Row="1" Grid.Column="0" Text="Easting (E) *:" VerticalAlignment="Center" FontWeight="SemiBold"/>
                            <ComboBox Name="cb_col_e" Grid.Row="1" Grid.Column="1" Height="24"/>

                            <TextBlock Grid.Row="1" Grid.Column="3" Text="Cut-Off Z:" VerticalAlignment="Center"/>
                            <ComboBox Name="cb_col_cutoff" Grid.Row="1" Grid.Column="4" Height="24"/>

                            <TextBlock Grid.Row="2" Grid.Column="0" Text="Northing (N)*:" VerticalAlignment="Center" FontWeight="SemiBold"/>
                            <ComboBox Name="cb_col_n" Grid.Row="2" Grid.Column="1" Height="24"/>

                            <TextBlock Grid.Row="2" Grid.Column="3" Text="Rotation:" VerticalAlignment="Center"/>
                            <ComboBox Name="cb_col_rot" Grid.Row="2" Grid.Column="4" Height="24"/>
                        </Grid>
                    </Border>
                </StackPanel>
            </Border>

            <!-- Right Card: Revit 3D Family, Level, Upsert Mode & Options -->
            <Border Grid.Column="2" Background="#FFFFFF" BorderBrush="#D1D5DB" BorderThickness="1" CornerRadius="6" Padding="12">
                <StackPanel>
                    <TextBlock Text="2. Revit 3D Placement &amp; Smart Upsert Settings" FontWeight="SemiBold" Foreground="#111827" Margin="0,0,0,8"/>

                    <Grid Margin="0,0,0,6">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="120"/>
                            <ColumnDefinition Width="*"/>
                        </Grid.ColumnDefinitions>
                        <TextBlock Text="Host Level:" VerticalAlignment="Center" Foreground="#374151"/>
                        <ComboBox Name="cb_level" Grid.Column="1" Height="25"/>
                    </Grid>

                    <Grid Margin="0,0,0,6">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="120"/>
                            <ColumnDefinition Width="*"/>
                        </Grid.ColumnDefinitions>
                        <TextBlock Text="3D Model Family:" VerticalAlignment="Center" Foreground="#374151"/>
                        <ComboBox Name="cb_family" Grid.Column="1" Height="25"/>
                    </Grid>

                    <Grid Margin="0,0,0,6">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="120"/>
                            <ColumnDefinition Width="*"/>
                        </Grid.ColumnDefinitions>
                        <TextBlock Text="Fallback Type:" VerticalAlignment="Center" Foreground="#374151"/>
                        <ComboBox Name="cb_default_type" Grid.Column="1" Height="25"/>
                    </Grid>

                    <Grid Margin="0,0,0,6">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="120"/>
                            <ColumnDefinition Width="*"/>
                        </Grid.ColumnDefinitions>
                        <TextBlock Text="Write Pile No to:" VerticalAlignment="Center" Foreground="#374151"/>
                        <ComboBox Name="cb_target_param" Grid.Column="1" Height="25"/>
                    </Grid>

                    <Grid Margin="0,0,0,8">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="120"/>
                            <ColumnDefinition Width="*"/>
                        </Grid.ColumnDefinitions>
                        <TextBlock Text="Duplicate Mode:" VerticalAlignment="Center" Foreground="#374151"/>
                        <ComboBox Name="cb_mode" Grid.Column="1" Height="25"/>
                    </Grid>

                    <Border BorderBrush="#E5E7EB" BorderThickness="0,1,0,0" Padding="0,8,0,0">
                        <StackPanel>
                            <CheckBox Name="chk_write_ne" IsChecked="True" Margin="0,2,0,4"
                                      Content="Write N_Coordinate / E_Coordinate parameters (if present on Family)"/>
                            <CheckBox Name="chk_select_after" IsChecked="True" Margin="0,2,0,0"
                                      Content="Select placed / updated 3D elements in Revit after completion"/>
                        </StackPanel>
                    </Border>
                </StackPanel>
            </Border>
        </Grid>

        <!-- Center Live Preview DataGrid -->
        <Border Grid.Row="2" Background="#FFFFFF" BorderBrush="#D1D5DB" BorderThickness="1" CornerRadius="6" Margin="14,0,14,10" Padding="10">
            <Grid>
                <Grid.RowDefinitions>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="*"/>
                </Grid.RowDefinitions>
                <Grid Grid.Row="0" Margin="0,0,0,6">
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="*"/>
                        <ColumnDefinition Width="Auto"/>
                    </Grid.ColumnDefinitions>
                    <TextBlock Text="3. Live CSV Validation &amp; Placement Preview (First 200 Rows)" FontWeight="SemiBold" Foreground="#111827"/>
                    <TextBlock Name="lbl_preview_stats" Grid.Column="1" Text="No CSV file loaded." Foreground="#2563EB" FontWeight="SemiBold"/>
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
                <TextBlock Text="All placements run inside a single undoable Revit Transaction." VerticalAlignment="Center" Foreground="#4B5563" FontSize="11.5"/>
                <StackPanel Grid.Column="1" Orientation="Horizontal">
                    <Button Name="btn_run" Content="Import / Update 3D Piles" Width="185" Height="30"
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
    def __init__(self, doc, levels, fam_packs, converter, script_dir):
        self.doc = doc
        self.levels = sorted(levels, key=lambda lv: lv.Elevation)
        self.fam_packs = fam_packs
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
        self.cb_col_type = w.FindName("cb_col_type")
        self.cb_col_rot = w.FindName("cb_col_rot")

        self.cb_level = w.FindName("cb_level")
        self.cb_family = w.FindName("cb_family")
        self.cb_default_type = w.FindName("cb_default_type")
        self.cb_target_param = w.FindName("cb_target_param")
        self.cb_mode = w.FindName("cb_mode")

        self.chk_write_ne = w.FindName("chk_write_ne")
        self.chk_select_after = w.FindName("chk_select_after")

        self.lbl_preview_stats = w.FindName("lbl_preview_stats")
        self.dg_preview = w.FindName("dg_preview")
        self.btn_run = w.FindName("btn_run")
        self.btn_cancel = w.FindName("btn_cancel")

        self.btn_browse.Click += self.on_browse
        self.btn_sample.Click += self.on_sample
        self.btn_run.Click += self.on_run
        self.btn_cancel.Click += self.on_cancel

        self.cb_family.SelectionChanged += self.on_family_changed
        self.cb_delimiter.SelectionChanged += self.on_delimiter_changed

        for cb in (
            self.cb_coord_sys, self.cb_units, self.cb_elev_datum,
            self.cb_col_no, self.cb_col_e, self.cb_col_n,
            self.cb_col_cutoff, self.cb_col_type, self.cb_col_rot,
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

        self.chk_write_ne.IsChecked = bool(self.saved.get("write_ne", True))
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

    def _refresh_family_dependents(self):
        fp = self.get_selected_family_pack()
        self.cb_default_type.Items.Clear()
        self.cb_target_param.Items.Clear()
        if fp is None:
            return

        for t_name in sorted(fp.symbols.keys(), key=lambda s: s.lower()):
            self.cb_default_type.Items.Add(t_name)
        self._select_combo_text(self.cb_default_type, self.saved.get("default_type"))

        params = get_writable_instance_parameters(self.doc, fp)
        for p_name in params:
            self.cb_target_param.Items.Add(p_name)
        self._select_combo_text(self.cb_target_param, self.saved.get("target_param"), "Mark")

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
        dlg.Title = "Select Pile / Foundation Coordinate CSV"
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
        opt_combos = (self.cb_col_cutoff, self.cb_col_type, self.cb_col_rot)

        for cb in req_combos:
            cb.Items.Clear()
            for h in headers:
                cb.Items.Add(h)

        for cb in opt_combos:
            cb.Items.Clear()
            cb.Items.Add(NONE_COL)
            for h in headers:
                cb.Items.Add(h)

        pick_no = auto_pick_column(headers, ["pile", "mark", "number", "no", "id", "name"], ["no", "mark", "pile_no"])
        pick_e = auto_pick_column(headers, ["east", "coord_e", "utm_e"], ["e", "x", "easting"])
        pick_n = auto_pick_column(headers, ["north", "coord_n", "utm_n"], ["n", "y", "northing"])
        pick_cut = auto_pick_column(headers, ["cut", "elev", "top", "bof", "level"], ["z", "cutoff", "cutoff_elev"])
        pick_typ = auto_pick_column(headers, ["type", "size", "section", "symbol"], ["type"])
        pick_rot = auto_pick_column(headers, ["rot", "angle", "deg", "bearing"], ["rotation", "angle"])

        self._select_combo_text(self.cb_col_no, pick_no if pick_no != NONE_COL else (headers[0] if len(headers) > 0 else None))
        self._select_combo_text(self.cb_col_e, pick_e if pick_e != NONE_COL else (headers if len(headers) > 1 else None))
        self._select_combo_text(self.cb_col_n, pick_n if pick_n != NONE_COL else (headers if len(headers) > 2 else None))
        self._select_combo_text(self.cb_col_cutoff, pick_cut, NONE_COL)
        self._select_combo_text(self.cb_col_type, pick_typ, NONE_COL)
        self._select_combo_text(self.cb_col_rot, pick_rot, NONE_COL)

        self._suppress_events = False
        self.rebuild_preview()

    def rebuild_preview(self):
        self.parsed_records = []
        dt = DataTable()
        for col_title in ("Row", "Pile_No", "Easting", "Northing", "CutOff", "Resolved_Type", "Rot_Deg", "Action"):
            dt.Columns.Add(col_title)

        if not self.csv_raw_rows:
            self.dg_preview.ItemsSource = dt.DefaultView
            self.lbl_preview_stats.Text = u"No CSV rows loaded."
            return

        fp = self.get_selected_family_pack()
        def_type_name = to_text(self.cb_default_type.SelectedItem or "")
        type_lookup = {k.strip().lower(): k for k in (fp.symbols.keys() if fp else [])}

        target_param = to_text(self.cb_target_param.SelectedItem or "Mark")
        mode = to_text(self.cb_mode.SelectedItem or MODE_UPSERT)
        existing_map = index_existing_elements_by_key(self.doc, fp, target_param) if fp else {}

        col_no = to_text(self.cb_col_no.SelectedItem or "")
        col_e = to_text(self.cb_col_e.SelectedItem or "")
        col_n = to_text(self.cb_col_n.SelectedItem or "")
        col_cut = to_text(self.cb_col_cutoff.SelectedItem or NONE_COL)
        col_typ = to_text(self.cb_col_type.SelectedItem or NONE_COL)
        col_rot = to_text(self.cb_col_rot.SelectedItem or NONE_COL)

        invalid_count = 0
        update_count = 0
        create_count = 0
        skip_count = 0

        for idx, r in enumerate(self.csv_raw_rows, start=1):
            p_no = to_text(r.get(col_no, "")).strip()
            e_val = parse_float_clean(r.get(col_e))
            n_val = parse_float_clean(r.get(col_n))
            c_val = parse_float_clean(r.get(col_cut)) if col_cut != NONE_COL else None
            rot_val = parse_float_clean(r.get(col_rot)) if col_rot != NONE_COL else 0.0
            if rot_val is None:
                rot_val = 0.0

            raw_t = to_text(r.get(col_typ, "")).strip() if col_typ != NONE_COL else u""
            matched_t_name = type_lookup.get(raw_t.lower(), def_type_name) if raw_t else def_type_name
            used_fallback = bool(raw_t and raw_t.lower() not in type_lookup)

            if not p_no or e_val is None or n_val is None:
                invalid_count += 1
                if idx <= 200:
                    dt.Rows.Add(
                        str(r.get("__line__", idx)),
                        p_no or "<Missing>",
                        to_text(r.get(col_e, "")),
                        to_text(r.get(col_n, "")),
                        "-",
                        "-",
                        "-",
                        "INVALID (Skip)",
                    )
                continue

            exists = p_no.lower() in existing_map
            if exists and mode == MODE_UPSERT:
                action_lbl = "UPDATE Existing"
                update_count += 1
            elif exists and mode == MODE_SKIP:
                action_lbl = "SKIP (Exists)"
                skip_count += 1
            else:
                action_lbl = "CREATE New"
                create_count += 1

            self.parsed_records.append({
                "line": r.get("__line__", idx),
                "no": p_no,
                "e": e_val,
                "n": n_val,
                "cutoff": c_val,
                "csv_type_raw": raw_t,
                "resolved_type_name": matched_t_name,
                "rot_deg": rot_val,
                "existing_inst": existing_map.get(p_no.lower()),
            })

            if idx <= 200:
                t_disp = u"{} (Fallback)".format(matched_t_name) if used_fallback else matched_t_name
                dt.Rows.Add(
                    str(r.get("__line__", idx)),
                    p_no,
                    "{:,.3f}".format(e_val),
                    "{:,.3f}".format(n_val),
                    "{:+.3f}".format(c_val) if c_val is not None else "-",
                    t_disp,
                    "{:.1f}".format(rot_val),
                    action_lbl,
                )

        self.dg_preview.ItemsSource = dt.DefaultView
        self.lbl_preview_stats.Text = (
            u"Valid: {}  (Create: {} | Update: {} | Skip: {})   Invalid: {}".format(
                len(self.parsed_records), create_count, update_count, skip_count, invalid_count
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
            "family_label": to_text(self.cb_family.SelectedItem),
            "default_type": to_text(self.cb_default_type.SelectedItem),
            "target_param": to_text(self.cb_target_param.SelectedItem),
            "mode": to_text(self.cb_mode.SelectedItem),
            "write_ne": bool(self.chk_write_ne.IsChecked),
            "select_after": bool(self.chk_select_after.IsChecked),
        })

        self.confirmed = True
        self.win.Close()

    def on_cancel(self, _sender, _args):
        self.confirmed = False
        self.win.Close()


# ------------------------------------------------------------------------------
# BATCH TRANSACTION EXECUTION
# ------------------------------------------------------------------------------
def execute_pile_import(uidoc, ctrl):
    doc = uidoc.Document
    fp = ctrl.get_selected_family_pack()
    base_level = ctrl.get_selected_level()
    def_type_name = to_text(ctrl.cb_default_type.SelectedItem)
    default_sym = fp.symbols.get(def_type_name)

    unit_label = to_text(ctrl.cb_units.SelectedItem)
    unit_factor = UNIT_TO_FEET.get(unit_label, FEET_PER_METER)
    coord_mode = to_text(ctrl.cb_coord_sys.SelectedItem)
    datum_mode = to_text(ctrl.cb_elev_datum.SelectedItem)
    dup_mode = to_text(ctrl.cb_mode.SelectedItem)
    target_param = to_text(ctrl.cb_target_param.SelectedItem)
    write_ne = bool(ctrl.chk_write_ne.IsChecked)
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
    errors = []
    touched_ids = []

    records = ctrl.parsed_records
    total = len(records)

    t = Transaction(doc, "P13 Import 3D Piles from CSV")
    t.Start()
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

                    use_sym = fp.symbols.get(rec["resolved_type_name"], default_sym)
                    if use_sym is None:
                        raise RuntimeError("No valid Family Type resolved.")
                    if not use_sym.IsActive:
                        use_sym.Activate()

                    rx, ry = ctrl.converter.to_internal_xy(rec["e"], rec["n"], unit_factor, coord_mode)
                    target_pt = XYZ(rx, ry, base_level.Elevation)

                    offset_ft = None
                    if rec["cutoff"] is not None:
                        int_cutoff_z = ctrl.converter.to_internal_z(rec["cutoff"], unit_factor, datum_mode)
                        offset_ft = int_cutoff_z - base_level.Elevation

                    if existing_inst is not None and dup_mode == MODE_UPSERT:
                        inst = existing_inst
                        # Update Family Type if changed
                        if get_id_val(inst.GetTypeId()) != get_id_val(use_sym.Id):
                            inst.ChangeTypeId(use_sym.Id)

                        # Move XY location accurately
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
                        updated_cnt += 1
                    else:
                        inst = doc.Create.NewFamilyInstance(target_pt, use_sym, base_level, st_type)
                        if abs(float(rec["rot_deg"])) > 1e-5:
                            axis = Line.CreateBound(target_pt, target_pt + XYZ.BasisZ)
                            ElementTransformUtils.RotateElement(doc, inst.Id, axis, math.radians(float(rec["rot_deg"])))
                        created_cnt += 1

                    apply_level_and_cutoff_offset(inst, base_level, offset_ft)
                    set_param_flexible(inst, target_param, rec["no"])

                    if rec["csv_type_raw"]:
                        set_param_flexible(inst, "Comments", u"CSV Type: {}".format(rec["csv_type_raw"]))

                    if write_ne:
                        set_param_flexible(inst, "E_Coordinate", "{:.4f}".format(rec["e"]))
                        set_param_flexible(inst, "N_Coordinate", "{:.4f}".format(rec["n"]))

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

    if select_after and touched_ids:
        try:
            id_list = System.Collections.Generic.List[ElementId](touched_ids)
            uidoc.Selection.SetElementIds(id_list)
        except Exception:
            pass

    summary = (
        u"Import / Update Complete!\n\n"
        u"• Created new 3D elements : {}\n"
        u"• Updated existing elements : {}\n"
        u"• Skipped existing elements : {}\n"
        u"• Row errors : {}".format(created_cnt, updated_cnt, skipped_cnt, len(errors))
    )
    if errors:
        summary += u"\n\nFirst errors:\n" + u"\n".join(errors[:10])

    forms.alert(summary, title="P13 Import 3D Piles (Pro)")


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

    script_dir = os.path.dirname(os.path.abspath(__file__))
    converter = CoordinateConverter(doc)

    ctrl = ImportPilesProController(doc, levels, fam_packs, converter, script_dir)
    ctrl.win.ShowDialog()
    if ctrl.confirmed:
        execute_pile_import(uidoc, ctrl)


if __name__ == "__main__":
    main()
