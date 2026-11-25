# -*- coding: utf-8 -*-
# pylint: disable=import-error,invalid-name,broad-except,too-many-lines,too-many-instance-attributes
"""Transfer View Filters, V/G graphic overrides, and filter rules via JSON presets."""

__title__ = "Filter\nTransfer"
__author__ = "Permpong Thawikul (P13)"
__doc__ = (
    "Copy, paste, and transfer View Filters across views, View Templates, and projects.\n\n"
    "- Preserves Enable, Visibility, Halftone, Transparency, Lines, and FG/BG Patterns\n"
    "- Stores Filter Rules & Categories in JSON; builds missing filters on target models\n"
    "- Interactive Paste Destination highlight cards with live target view summary\n"
    "- Multi-select rows with Shift+Click, Ctrl+Click, and Spacebar\n\n"
    "Shift+Click: Set preset storage folder"
)

import os
import io
import sys
import copy
import time
import json
import shutil
import datetime
import traceback
import subprocess

import clr
clr.AddReference("System")
clr.AddReference("System.Data")
clr.AddReference("System.Xml")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

import System
from System.Collections.Generic import List
from System.Data import DataTable
from System.Windows import Thickness
from System.Windows import Visibility
from System.Windows.Controls import CheckBox
from System.Windows.Controls import DataGridRow
from System.Windows.Controls import DataGridSelectionMode
from System.Windows.Controls import DataGridSelectionUnit
from System.Windows.Controls import SelectionMode
from System.Windows.Input import Key
from System.Windows.Input import Keyboard
from System.Windows.Input import ModifierKeys
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import Brushes
from System.Windows.Media import Color as MediaColor
from System.Windows.Media import SolidColorBrush
from System.Windows.Media import Visual
from System.Windows.Media import VisualTreeHelper

from pyrevit import revit
from pyrevit import DB
from pyrevit import forms
from pyrevit import script
from pyrevit import HOST_APP
from pyrevit import EXEC_PARAMS

try:
    from pyrevit import UI
except Exception:
    clr.AddReference("RevitAPIUI")
    import Autodesk.Revit.UI as UI

# ------------------------------------------------------------------------------
# CONSTANTS & CONFIG
# ------------------------------------------------------------------------------
SCHEMA_VERSION = "3.0"
CONFIG_SECTION = "p13_filter_state"
SOLID_FILL_MARKER = "<Solid fill>"
QUICK_CLIPBOARD_NAME = "_QuickCopy_Clipboard"
RECENT_THRESHOLD_SEC = 300

PY2 = sys.version_info[0] < 3
TEXT_TYPE = unicode if PY2 else str  # noqa: F821

my_config = script.get_config(CONFIG_SECTION)
legacy_config = script.get_config()
logger = script.get_logger()
output = script.get_output()


# ------------------------------------------------------------------------------
# UNICODE, UI & REVIT API COMPATIBILITY HELPERS (Revit 2019 - 2026+)
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


def show_alert(title, msg):
    try:
        UI.TaskDialog.Show(to_text(title), to_text(msg))
    except Exception:
        forms.alert(to_text(msg), title=to_text(title))


def ask_yes_no(title, msg):
    try:
        res = UI.TaskDialog.Show(
            to_text(title),
            to_text(msg),
            UI.TaskDialogCommonButtons.Yes | UI.TaskDialogCommonButtons.No
        )
        return res == UI.TaskDialogResult.Yes
    except Exception:
        return bool(forms.alert(to_text(msg), title=to_text(title), yes=True, no=True))


def set_revit_owner(wpf_win):
    try:
        hwnd = System.IntPtr.Zero
        try:
            hwnd = HOST_APP.uiapp.MainWindowHandle
        except Exception:
            pass
        if hwnd == System.IntPtr.Zero:
            hwnd = System.Diagnostics.Process.GetCurrentProcess().MainWindowHandle
        if hwnd != System.IntPtr.Zero:
            WindowInteropHelper(wpf_win).Owner = hwnd
    except Exception:
        pass


def get_target_active_view(doc, uidoc):
    v = doc.ActiveView
    if v and v.AreGraphicsOverridesAllowed():
        return v
    try:
        gv = uidoc.ActiveGraphicalView
        if gv and gv.AreGraphicsOverridesAllowed():
            return gv
    except Exception:
        pass
    return v


def get_id_val(eid):
    if eid is None or eid == DB.ElementId.InvalidElementId:
        return -1
    return int(eid.Value if hasattr(eid, "Value") else eid.IntegerValue)


def make_element_id(int_val):
    if int_val is None or int(int_val) == -1:
        return DB.ElementId.InvalidElementId
    try:
        return DB.ElementId(System.Int64(int(int_val)))
    except TypeError:
        return DB.ElementId(int(int_val))


def get_ordered_filters(view):
    if hasattr(view, "GetOrderedFilters"):
        return list(view.GetOrderedFilters())
    return list(view.GetFilters())


def get_rgb(color):
    if color and color.IsValid:
        return [int(color.Red), int(color.Green), int(color.Blue)]
    return None


def make_color(rgb_list):
    if rgb_list and isinstance(rgb_list, (list, tuple)) and len(rgb_list) == 3:
        try:
            return DB.Color(
                System.Byte(max(0, min(255, int(rgb_list[0])))),
                System.Byte(max(0, min(255, int(rgb_list[1])))),
                System.Byte(max(0, min(255, int(rgb_list[2]))))
            )
        except Exception:
            pass
    return DB.Color.InvalidColorValue


def make_hex_brush(r, g, b):
    br = SolidColorBrush(
        MediaColor.FromArgb(
            System.Byte(255),
            System.Byte(r),
            System.Byte(g),
            System.Byte(b)
        )
    )
    br.Freeze()
    return br


def make_wpf_brush(rgb_list, fallback_brush=None):
    if rgb_list and isinstance(rgb_list, (list, tuple)) and len(rgb_list) == 3:
        try:
            return make_hex_brush(
                max(0, min(255, int(rgb_list[0]))),
                max(0, min(255, int(rgb_list[1]))),
                max(0, min(255, int(rgb_list[2])))
            )
        except Exception:
            pass
    return fallback_brush if fallback_brush is not None else Brushes.Transparent


# Swatch & Status Brushes
BRUSH_BDR_ACTIVE = make_hex_brush(95, 95, 95)
BRUSH_BDR_EMPTY = make_hex_brush(210, 210, 210)
BRUSH_BG_HIDDEN = make_hex_brush(235, 235, 235)
BRUSH_BG_LIGHT = make_hex_brush(248, 248, 248)
BRUSH_FG_NORMAL = make_hex_brush(30, 30, 30)
BRUSH_FG_MUTED = make_hex_brush(136, 136, 136)
BRUSH_STATUS_OK = make_hex_brush(24, 118, 52)
BRUSH_STATUS_PULL = make_hex_brush(0, 102, 180)
BRUSH_STATUS_WARN = make_hex_brush(180, 95, 6)

# Interactive Destination & Mode Card Highlight Brushes
BRUSH_CARD_SEL_BG = make_hex_brush(230, 243, 255)
BRUSH_CARD_SEL_BDR = make_hex_brush(0, 120, 212)
BRUSH_CARD_WARN_BG = make_hex_brush(255, 247, 230)
BRUSH_CARD_WARN_BDR = make_hex_brush(217, 119, 6)
BRUSH_CARD_DANGER_BG = make_hex_brush(253, 242, 242)
BRUSH_CARD_DANGER_BDR = make_hex_brush(209, 52, 56)
BRUSH_CARD_IDLE_BG = make_hex_brush(249, 250, 251)
BRUSH_CARD_IDLE_BDR = make_hex_brush(212, 216, 220)

BRUSH_BTN_BLUE_BG = make_hex_brush(0, 120, 212)
BRUSH_BTN_AMBER_BG = make_hex_brush(217, 119, 6)
BRUSH_BTN_SUBTLE_BG = make_hex_brush(240, 246, 252)
BRUSH_BTN_SUBTLE_BDR = make_hex_brush(122, 178, 230)
BRUSH_WHITE = make_hex_brush(255, 255, 255)
BRUSH_DARK_BLUE = make_hex_brush(0, 78, 146)
BRUSH_AMBER_TEXT = make_hex_brush(168, 85, 4)


def get_document_path(doc):
    try:
        if doc.IsWorkshared and doc.IsModelInCloud:
            mp = doc.GetCloudModelPath()
            return to_text(DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(mp))
    except Exception:
        pass
    try:
        return to_text(doc.PathName) if doc.PathName else None
    except Exception:
        return None


# ------------------------------------------------------------------------------
# STORAGE & ATOMIC FILE MANAGEMENT (SHARED BY COPY & PASTE)
# ------------------------------------------------------------------------------
def _is_writable_preset_folder(path):
    if not path:
        return False
    try:
        clean = to_text(path).strip(u'\'" ')
        norm = os.path.abspath(os.path.normpath(clean))
        if not os.path.isdir(norm) or os.path.dirname(norm) == norm:
            return False
        probe = os.path.join(
            norm,
            u".p13_write_test_{}_{}.tmp".format(os.getpid(), int(time.time() * 1000))
        )
        with io.open(probe, "w", encoding="utf-8") as f:
            f.write(u"ok")
        try:
            os.remove(probe)
        except Exception:
            pass
        return True
    except Exception:
        return False


def _save_export_path(path):
    my_config.export_path = to_text(path)
    try:
        script.save_config()
    except Exception:
        pass


def _migrate_existing_presets(target_folder):
    try:
        doc_dir = to_text(
            System.Environment.GetFolderPath(System.Environment.SpecialFolder.MyDocuments)
        )
        if not doc_dir:
            doc_dir = to_text(os.path.expanduser("~"))
        old_dir = os.path.join(doc_dir, u"P13 Filter Presets")
        if os.path.isdir(old_dir) and os.path.abspath(old_dir).lower() != os.path.abspath(target_folder).lower():
            for fname in os.listdir(old_dir):
                fn_txt = to_text(fname)
                if fn_txt.lower().endswith(u".json"):
                    src = os.path.join(old_dir, fn_txt)
                    dst = os.path.join(target_folder, fn_txt)
                    if not os.path.exists(dst):
                        shutil.copy2(src, dst)
    except Exception:
        pass


def get_export_path(prompt_if_missing=True):
    for cfg_path in (getattr(my_config, "export_path", None), getattr(legacy_config, "export_path", None)):
        if cfg_path and _is_writable_preset_folder(cfg_path):
            return os.path.abspath(os.path.normpath(to_text(cfg_path).strip(u'\'" ')))

    candidates = []
    appdata = to_text(os.getenv("APPDATA"))
    if appdata:
        candidates.append(os.path.join(appdata, u"pyRevit", u"P13 Filter Presets"))
    try:
        docs = to_text(System.Environment.GetFolderPath(System.Environment.SpecialFolder.MyDocuments))
        if docs:
            candidates.append(os.path.join(docs, u"P13 Filter Presets"))
    except Exception:
        pass
    home = to_text(os.path.expanduser("~"))
    if home:
        candidates.append(os.path.join(home, u"P13 Filter Presets"))
    local_app = to_text(os.getenv("LOCALAPPDATA"))
    if local_app:
        candidates.append(os.path.join(local_app, u"pyRevit", u"P13 Filter Presets"))

    for cand in candidates:
        try:
            norm = os.path.abspath(os.path.normpath(cand))
            if not os.path.isdir(norm):
                os.makedirs(norm)
            if _is_writable_preset_folder(norm):
                _migrate_existing_presets(norm)
                _save_export_path(norm)
                return norm
        except Exception:
            continue

    if prompt_if_missing:
        picked = forms.pick_folder(title="Select Writable Folder for Filter Presets")
        if picked and _is_writable_preset_folder(picked):
            norm = os.path.abspath(os.path.normpath(to_text(picked)))
            _save_export_path(norm)
            return norm

    show_alert("Filter Transfer", "Could not find or create a writable folder for Filter Presets.")
    return None


def get_preset_file_path(export_path, preset_name):
    name = to_text(preset_name).strip()
    if name.lower().endswith(u".json"):
        name = name[:-5].strip()
    if not name or name in (u".", u"..") or any(ch in name for ch in u'<>:"/\\|?*'):
        return None
    return os.path.join(to_text(export_path), u"{}.json".format(name))


def write_json_atomic(file_path, payload):
    folder = os.path.dirname(file_path)
    tmp_path = os.path.join(
        folder,
        u".tmp_{}_{}.json".format(os.getpid(), int(time.time() * 1000))
    )
    text_data = json.dumps(payload, indent=2, ensure_ascii=False)
    if PY2 and isinstance(text_data, str):
        text_data = text_data.decode("utf-8")
    with io.open(tmp_path, "w", encoding="utf-8") as f:
        f.write(text_data)
    if os.path.exists(file_path):
        os.remove(file_path)
    os.rename(tmp_path, file_path)


def read_json_preset(file_path):
    with io.open(file_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    mtime = 0.0
    try:
        mtime = os.path.getmtime(file_path)
    except Exception:
        pass

    if isinstance(raw, list):
        return {
            "schema_version": "1.0",
            "preset_name": to_text(os.path.splitext(os.path.basename(file_path))[0]),
            "created_at": "Legacy v1.0",
            "source_document": raw[0].get("source_document_title", "Unknown") if raw else "Unknown",
            "source_document_path": raw[0].get("source_document_path") if raw else None,
            "source_view_name": "-",
            "filters": raw,
            "_file_path": file_path,
            "_mtime": mtime
        }
    raw["_file_path"] = file_path
    raw["_mtime"] = mtime
    return raw


# ------------------------------------------------------------------------------
# FILTER RULES SERIALIZATION & RECONSTRUCTION ENGINE (SCHEMA v3.0)
# ------------------------------------------------------------------------------
def _extract_evaluator_key(evaluator):
    if evaluator is None:
        return None
    tname = evaluator.GetType().Name
    mapping = {
        "FilterNumericEquals": "NumEq",
        "FilterNumericGreater": "NumGt",
        "FilterNumericGreaterOrEqual": "NumGe",
        "FilterNumericLess": "NumLt",
        "FilterNumericLessOrEqual": "NumLe",
        "FilterStringEquals": "StrEq",
        "FilterStringContains": "StrContains",
        "FilterStringBeginsWith": "StrBegins",
        "FilterStringEndsWith": "StrEnds",
        "FilterStringGreater": "StrGt",
        "FilterStringGreaterOrEqual": "StrGe",
        "FilterStringLess": "StrLt",
        "FilterStringLessOrEqual": "StrLe"
    }
    return mapping.get(tname, tname)


def _serialize_single_rule(doc, rule):
    inverted = False
    inner = rule
    if isinstance(rule, DB.FilterInverseRule):
        inverted = True
        inner = rule.GetInnerRule()

    param_eid = inner.GetRuleParameter()
    pid = get_id_val(param_eid)
    param_info = {"id": pid, "name": None, "shared_guid": None}
    if pid > 0:
        pelem = doc.GetElement(param_eid)
        if pelem:
            param_info["name"] = to_text(pelem.Name)
            if isinstance(pelem, DB.SharedParameterElement):
                try:
                    param_info["shared_guid"] = str(pelem.GuidValue)
                except Exception:
                    pass

    rtype = inner.GetType().Name
    if rtype == "HasValueFilterRule" or (hasattr(DB, "HasValueFilterRule") and isinstance(inner, DB.HasValueFilterRule)):
        return {"rule_kind": "HasValue", "inverted": inverted, "param": param_info}
    if rtype == "HasNoValueFilterRule" or (hasattr(DB, "HasNoValueFilterRule") and isinstance(inner, DB.HasNoValueFilterRule)):
        return {"rule_kind": "HasNoValue", "inverted": inverted, "param": param_info}

    eval_key = _extract_evaluator_key(inner.GetEvaluator()) if hasattr(inner, "GetEvaluator") else None

    if isinstance(inner, DB.FilterStringRule):
        val_str = to_text(inner.RuleString) if hasattr(inner, "RuleString") else u""
        return {
            "rule_kind": "String",
            "eval": eval_key,
            "val": val_str,
            "inverted": inverted,
            "param": param_info
        }
    if isinstance(inner, DB.FilterDoubleRule):
        return {
            "rule_kind": "Double",
            "eval": eval_key,
            "val": float(inner.RuleValue),
            "eps": float(inner.Epsilon),
            "inverted": inverted,
            "param": param_info
        }
    if isinstance(inner, DB.FilterIntegerRule):
        ival = int(inner.RuleValue)
        ws_name = None
        if pid == int(DB.BuiltInParameter.ELEM_PARTITION_PARAM):
            try:
                ws = doc.GetWorksetTable().GetWorkset(DB.WorksetId(ival))
                if ws:
                    ws_name = to_text(ws.Name)
            except Exception:
                pass
        return {
            "rule_kind": "Integer",
            "eval": eval_key,
            "val": ival,
            "workset_name": ws_name,
            "inverted": inverted,
            "param": param_info
        }
    if isinstance(inner, DB.FilterElementIdRule):
        rv = inner.RuleValue
        ref_elem = doc.GetElement(rv)
        return {
            "rule_kind": "ElementId",
            "eval": eval_key,
            "val": get_id_val(rv),
            "val_name": to_text(ref_elem.Name) if ref_elem else None,
            "inverted": inverted,
            "param": param_info
        }
    if hasattr(DB, "FilterGlobalParameterAssociationRule") and isinstance(inner, DB.FilterGlobalParameterAssociationRule):
        rv = inner.RuleValue
        gp = doc.GetElement(rv)
        return {
            "rule_kind": "GlobalParam",
            "eval": eval_key,
            "val": get_id_val(rv),
            "val_name": to_text(gp.Name) if gp else None,
            "inverted": inverted,
            "param": param_info
        }
    return None


def serialize_element_filter_tree(doc, elem_filter):
    if elem_filter is None:
        return None
    if isinstance(elem_filter, DB.LogicalAndFilter):
        children = []
        for sub in elem_filter.GetFilters():
            node = serialize_element_filter_tree(doc, sub)
            if node:
                children.append(node)
        return {"node": "And", "children": children}
    if isinstance(elem_filter, DB.LogicalOrFilter):
        children = []
        for sub in elem_filter.GetFilters():
            node = serialize_element_filter_tree(doc, sub)
            if node:
                children.append(node)
        return {"node": "Or", "children": children}
    if isinstance(elem_filter, DB.ElementParameterFilter):
        rules = []
        for r in elem_filter.GetRules():
            sr = _serialize_single_rule(doc, r)
            if sr:
                rules.append(sr)
        return {"node": "ParamFilter", "rules": rules}
    return None


def _resolve_rule_parameter_id(doc, param_info, resolver):
    if not param_info:
        return DB.ElementId.InvalidElementId
    pid = param_info.get("id", -1)
    if pid < -1:
        return make_element_id(pid)
    guid_str = param_info.get("shared_guid")
    if guid_str and guid_str in resolver.shared_params_by_guid:
        return resolver.shared_params_by_guid[guid_str]
    pname = param_info.get("name")
    if pname and pname.lower() in resolver.project_params_by_name:
        return resolver.project_params_by_name[pname.lower()]
    return DB.ElementId.InvalidElementId


def _call_string_rule_factory(fn_name, param_eid, val_str):
    fn = getattr(DB.ParameterFilterRuleFactory, fn_name, None)
    if fn is None:
        return None
    try:
        return fn(param_eid, val_str)
    except TypeError:
        return fn(param_eid, val_str, False)


def _rebuild_single_rule(doc, rdict, resolver):
    param_eid = _resolve_rule_parameter_id(doc, rdict.get("param"), resolver)
    if param_eid == DB.ElementId.InvalidElementId:
        return None

    rkind = rdict.get("rule_kind")
    ev = rdict.get("eval")
    inverted = bool(rdict.get("inverted", False))
    rule = None
    f_cls = DB.ParameterFilterRuleFactory

    if rkind == "HasValue" and hasattr(f_cls, "CreateHasValueParameterRule"):
        rule = f_cls.CreateHasValueParameterRule(param_eid)
    elif rkind == "HasNoValue" and hasattr(f_cls, "CreateHasNoValueParameterRule"):
        rule = f_cls.CreateHasNoValueParameterRule(param_eid)
    elif rkind == "String":
        val_s = to_text(rdict.get("val", u""))
        str_map = {
            "StrEq": ("CreateEqualsRule", False),
            "StrContains": ("CreateContainsRule", False),
            "StrBegins": ("CreateBeginsWithRule", False),
            "StrEnds": ("CreateEndsWithRule", False),
            "StrGt": ("CreateGreaterRule", False),
            "StrGe": ("CreateGreaterOrEqualRule", False),
            "StrLt": ("CreateLessRule", False),
            "StrLe": ("CreateLessOrEqualRule", False)
        }
        fn_name, _ = str_map.get(ev, ("CreateEqualsRule", False))
        rule = _call_string_rule_factory(fn_name, param_eid, val_s)
    elif rkind == "Double":
        val_d = float(rdict.get("val", 0.0))
        eps = float(rdict.get("eps", 1e-6))
        num_map = {
            "NumEq": "CreateEqualsRule",
            "NumGt": "CreateGreaterRule",
            "NumGe": "CreateGreaterOrEqualRule",
            "NumLt": "CreateLessRule",
            "NumLe": "CreateLessOrEqualRule"
        }
        fn = getattr(f_cls, num_map.get(ev, "CreateEqualsRule"), None)
        if fn:
            rule = fn(param_eid, val_d, eps)
    elif rkind == "Integer":
        ival = int(rdict.get("val", 0))
        ws_name = rdict.get("workset_name")
        if ws_name and ws_name.lower() in resolver.worksets_by_name:
            ival = resolver.worksets_by_name[ws_name.lower()]
        num_map = {
            "NumEq": "CreateEqualsRule",
            "NumGt": "CreateGreaterRule",
            "NumGe": "CreateGreaterOrEqualRule",
            "NumLt": "CreateLessRule",
            "NumLe": "CreateLessOrEqualRule"
        }
        fn = getattr(f_cls, num_map.get(ev, "CreateEqualsRule"), None)
        if fn:
            rule = fn(param_eid, ival)
    elif rkind == "ElementId":
        target_eid = make_element_id(rdict.get("val", -1))
        vname = rdict.get("val_name")
        if (target_eid == DB.ElementId.InvalidElementId or doc.GetElement(target_eid) is None) and vname:
            target_eid = resolver.elements_by_name.get(vname.lower(), target_eid)
        num_map = {
            "NumEq": "CreateEqualsRule",
            "NumGt": "CreateGreaterRule",
            "NumGe": "CreateGreaterOrEqualRule",
            "NumLt": "CreateLessRule",
            "NumLe": "CreateLessOrEqualRule"
        }
        fn = getattr(f_cls, num_map.get(ev, "CreateEqualsRule"), None)
        if fn:
            rule = fn(param_eid, target_eid)

    if rule is not None and inverted:
        rule = DB.FilterInverseRule(rule)
    return rule


def rebuild_element_filter_tree(doc, tree_dict, resolver):
    if not tree_dict:
        return None
    ntype = tree_dict.get("node")
    if ntype in ("And", "Or"):
        sub_list = List[DB.ElementFilter]()
        for ch in tree_dict.get("children", []):
            built = rebuild_element_filter_tree(doc, ch, resolver)
            if built is not None:
                sub_list.Add(built)
        if sub_list.Count == 0:
            return None
        return DB.LogicalAndFilter(sub_list) if ntype == "And" else DB.LogicalOrFilter(sub_list)
    if ntype == "ParamFilter":
        rule_list = List[DB.FilterRule]()
        for rdict in tree_dict.get("rules", []):
            r = _rebuild_single_rule(doc, rdict, resolver)
            if r is not None:
                rule_list.Add(r)
        if rule_list.Count == 0:
            return None
        return DB.ElementParameterFilter(rule_list)
    return None


# ------------------------------------------------------------------------------
# PATTERN, OVERRIDE & CROSS-PROJECT FILTER RESOLVER
# ------------------------------------------------------------------------------
def get_pattern_info(doc, pattern_id):
    if pattern_id is None or pattern_id == DB.ElementId.InvalidElementId:
        return {"id": -1, "name": None, "is_solid": False, "target": None}
    elem = doc.GetElement(pattern_id)
    if not elem:
        return {"id": get_id_val(pattern_id), "name": None, "is_solid": False, "target": None}
    is_solid, target_str = False, None
    if isinstance(elem, DB.FillPatternElement):
        fp = elem.GetFillPattern()
        if fp:
            is_solid = fp.IsSolidFill
            target_str = to_text(fp.Target)
    return {
        "id": get_id_val(pattern_id),
        "name": SOLID_FILL_MARKER if is_solid else to_text(elem.Name),
        "is_solid": is_solid,
        "target": target_str
    }


def get_line_pattern_info(doc, line_pattern_id):
    val = get_id_val(line_pattern_id)
    if line_pattern_id is None or line_pattern_id == DB.ElementId.InvalidElementId:
        return {"id": -1, "name": None, "is_solid": False}
    try:
        if val == get_id_val(DB.LinePatternElement.GetSolidPatternId()):
            return {"id": val, "name": "Solid", "is_solid": True}
    except Exception:
        pass
    elem = doc.GetElement(line_pattern_id)
    return {"id": val, "name": to_text(elem.Name) if elem else None, "is_solid": False}


class DocumentResourceResolver(object):
    """Unified resolver combining Cross-Project Auto-Pull with v3.0 Rule Builder."""

    def __init__(self, doc):
        self.doc = doc
        self.app = HOST_APP.app
        self.filters_by_name = {}
        self.filters_by_uid = {}
        self.drafting_patterns = {}
        self.solid_fill_id = DB.ElementId.InvalidElementId
        self.line_patterns = {}
        self.solid_line_id = DB.LinePatternElement.GetSolidPatternId()
        self.shared_params_by_guid = {}
        self.project_params_by_name = {}
        self.worksets_by_name = {}
        self.elements_by_name = {}
        self._scan_document()

    def _scan_document(self):
        filter_classes = [DB.ParameterFilterElement]
        if hasattr(DB, "SelectionFilterElement"):
            filter_classes.append(DB.SelectionFilterElement)
        for f_cls in filter_classes:
            for f_elem in DB.FilteredElementCollector(self.doc).OfClass(f_cls):
                self.filters_by_name[f_elem.Name] = f_elem
                self.filters_by_uid[f_elem.UniqueId] = f_elem

        for fp_elem in DB.FilteredElementCollector(self.doc).OfClass(DB.FillPatternElement):
            fp = fp_elem.GetFillPattern()
            if fp:
                if fp.IsSolidFill:
                    self.solid_fill_id = fp_elem.Id
                if fp.IsSolidFill or fp.Target == DB.FillPatternTarget.Drafting:
                    self.drafting_patterns[fp_elem.Name.lower()] = fp_elem.Id

        for lp_elem in DB.FilteredElementCollector(self.doc).OfClass(DB.LinePatternElement):
            self.line_patterns[lp_elem.Name.lower()] = lp_elem.Id

        for sp_elem in DB.FilteredElementCollector(self.doc).OfClass(DB.SharedParameterElement):
            try:
                self.shared_params_by_guid[str(sp_elem.GuidValue)] = sp_elem.Id
            except Exception:
                pass
            self.project_params_by_name[sp_elem.Name.lower()] = sp_elem.Id

        for pe_elem in DB.FilteredElementCollector(self.doc).OfClass(DB.ParameterElement):
            self.project_params_by_name[pe_elem.Name.lower()] = pe_elem.Id

        if self.doc.IsWorkshared:
            try:
                for ws in DB.FilteredWorksetCollector(self.doc).OfKind(DB.WorksetKind.UserWorkset):
                    self.worksets_by_name[ws.Name.lower()] = int(ws.Id.IntegerValue)
            except Exception:
                pass

    def find_open_source_document(self, filter_entry):
        source_path = filter_entry.get("source_document_path")
        source_title = filter_entry.get("source_document_title")
        fallback_docs = []

        for cand in self.app.Documents:
            if cand.IsLinked or cand.Equals(self.doc):
                continue
            fallback_docs.append(cand)
            try:
                if source_path and cand.PathName and cand.PathName.lower() == source_path.lower():
                    return cand
            except Exception:
                pass
            if source_title and cand.Title == source_title:
                return cand

        fname = filter_entry.get("name")
        filter_classes = [DB.ParameterFilterElement]
        if hasattr(DB, "SelectionFilterElement"):
            filter_classes.append(DB.SelectionFilterElement)
        for cand in fallback_docs:
            for f_cls in filter_classes:
                for fe in DB.FilteredElementCollector(cand).OfClass(f_cls):
                    if fe.Name == fname:
                        return cand
        return None

    def find_source_filter_in_doc(self, source_doc, filter_entry):
        uid = filter_entry.get("source_filter_unique_id")
        if uid:
            try:
                sf = source_doc.GetElement(uid)
                if sf and isinstance(sf, DB.FilterElement):
                    return sf
            except Exception:
                pass
        fname = filter_entry.get("name")
        filter_classes = [DB.ParameterFilterElement]
        if hasattr(DB, "SelectionFilterElement"):
            filter_classes.append(DB.SelectionFilterElement)
        for f_cls in filter_classes:
            for sf in DB.FilteredElementCollector(source_doc).OfClass(f_cls):
                if sf.Name == fname:
                    return sf
        return None

    def inspect_filter_availability(self, filter_entry):
        fname = filter_entry.get("name")
        if fname in self.filters_by_name:
            return u"In Model", BRUSH_STATUS_OK

        src_doc = self.find_open_source_document(filter_entry)
        if src_doc and self.find_source_filter_in_doc(src_doc, filter_entry):
            return u"Auto-Pull ({})".format(to_text(src_doc.Title)), BRUSH_STATUS_PULL

        if filter_entry.get("category_ids") and filter_entry.get("rule_tree"):
            return u"Create + Rules", BRUSH_STATUS_PULL
        if filter_entry.get("category_ids"):
            return u"Create (Categories)", BRUSH_STATUS_PULL

        return u"Need Source RVT", BRUSH_STATUS_WARN

    def resolve_or_create_filter(self, filter_entry):
        fname = filter_entry.get("name")
        if fname in self.filters_by_name:
            return self.filters_by_name[fname], u"Existing"

        src_doc = self.find_open_source_document(filter_entry)
        if src_doc:
            src_filter = self.find_source_filter_in_doc(src_doc, filter_entry)
            if src_filter:
                try:
                    src_ids = List[DB.ElementId]()
                    src_ids.Add(src_filter.Id)
                    copied_ids = DB.ElementTransformUtils.CopyElements(
                        src_doc,
                        src_ids,
                        self.doc,
                        DB.Transform.Identity,
                        DB.CopyPasteOptions()
                    )
                    if copied_ids and copied_ids.Count > 0:
                        nf = self.doc.GetElement(copied_ids[0])
                        self.filters_by_name[nf.Name] = nf
                        self.filters_by_uid[nf.UniqueId] = nf
                        return nf, u"Pulled from '{}'".format(to_text(src_doc.Title))
                except Exception as ex:
                    logger.debug("Cross-project CopyElements failed: {}".format(ex))

        cat_ids = filter_entry.get("category_ids", [])
        if cat_ids:
            try:
                clist = List[DB.ElementId]()
                for cid in cat_ids:
                    ceid = make_element_id(cid)
                    if DB.Category.GetCategory(self.doc, ceid) is not None:
                        clist.Add(ceid)
                if clist.Count > 0:
                    nf = DB.ParameterFilterElement.Create(self.doc, fname, clist)
                    rtree = filter_entry.get("rule_tree")
                    if rtree:
                        efilter = rebuild_element_filter_tree(self.doc, rtree, self)
                        if efilter is not None:
                            nf.SetElementFilter(efilter)
                    self.filters_by_name[nf.Name] = nf
                    self.filters_by_uid[nf.UniqueId] = nf
                    return nf, u"Created New Filter"
            except Exception as ex:
                logger.debug("Rule reconstruction failed: {}".format(ex))

        return None, u"Missing (Open source RVT or Import .RVT)"

    def resolve_drafting_fill_pattern_id(self, pat_info, legacy_id=-1, legacy_name=None):
        if isinstance(pat_info, dict):
            if pat_info.get("is_solid") or pat_info.get("name") == SOLID_FILL_MARKER:
                return self.solid_fill_id
            name = pat_info.get("name")
            if name and name.lower() in self.drafting_patterns:
                return self.drafting_patterns[name.lower()]

        if legacy_name:
            if legacy_name in (SOLID_FILL_MARKER, "<Solid fill>", "Solid fill"):
                return self.solid_fill_id
            if legacy_name.lower() in self.drafting_patterns:
                return self.drafting_patterns[legacy_name.lower()]

        if legacy_id not in (None, -1) and int(legacy_id) > 0:
            cand_id = make_element_id(legacy_id)
            cand = self.doc.GetElement(cand_id)
            if cand and isinstance(cand, DB.FillPatternElement):
                fp = cand.GetFillPattern()
                if fp and (fp.IsSolidFill or fp.Target == DB.FillPatternTarget.Drafting):
                    return cand_id
        return DB.ElementId.InvalidElementId

    def resolve_line_pattern_id(self, lp_info, legacy_id=-1, legacy_name=None):
        if isinstance(lp_info, dict):
            if lp_info.get("is_solid") or lp_info.get("name") == "Solid":
                return self.solid_line_id
            name = lp_info.get("name")
            if name and name.lower() in self.line_patterns:
                return self.line_patterns[name.lower()]

        if legacy_id == get_id_val(self.solid_line_id) or legacy_name == "Solid":
            return self.solid_line_id
        if legacy_name and legacy_name.lower() in self.line_patterns:
            return self.line_patterns[legacy_name.lower()]
        if legacy_id not in (None, -1) and int(legacy_id) > 0:
            cand_id = make_element_id(legacy_id)
            cand = self.doc.GetElement(cand_id)
            if cand and isinstance(cand, DB.LinePatternElement):
                return cand_id
        return DB.ElementId.InvalidElementId


def serialize_view_filter(doc, view, fid, order_index):
    f_elem = doc.GetElement(fid)
    ovr = view.GetFilterOverrides(fid)
    trans = ovr.SurfaceTransparency if hasattr(ovr, "SurfaceTransparency") else ovr.Transparency

    cat_ids, cat_names = [], []
    rule_tree = None
    if isinstance(f_elem, DB.ParameterFilterElement):
        try:
            for cid in f_elem.GetCategories():
                cat_ids.append(get_id_val(cid))
                cat = DB.Category.GetCategory(doc, cid)
                if cat:
                    cat_names.append(to_text(cat.Name))
        except Exception:
            pass
        try:
            rule_tree = serialize_element_filter_tree(doc, f_elem.GetElementFilter())
        except Exception:
            rule_tree = None

    sbg_id = ovr.SurfaceBackgroundPatternId if hasattr(ovr, "SurfaceBackgroundPatternId") else DB.ElementId.InvalidElementId
    cbg_id = ovr.CutBackgroundPatternId if hasattr(ovr, "CutBackgroundPatternId") else DB.ElementId.InvalidElementId

    pl_info = get_line_pattern_info(doc, ovr.ProjectionLinePatternId)
    cl_info = get_line_pattern_info(doc, ovr.CutLinePatternId)
    sfg_info = get_pattern_info(doc, ovr.SurfaceForegroundPatternId)
    sbg_info = get_pattern_info(doc, sbg_id)
    cfg_info = get_pattern_info(doc, ovr.CutForegroundPatternId)
    cbg_info = get_pattern_info(doc, cbg_id)

    return {
        "order_index": order_index,
        "name": to_text(f_elem.Name),
        "source_document_title": to_text(doc.Title),
        "source_document_path": get_document_path(doc),
        "source_filter_unique_id": f_elem.UniqueId,
        "source_filter_class": f_elem.GetType().FullName,
        "category_ids": cat_ids,
        "category_names": cat_names,
        "rule_tree": rule_tree,
        "is_visible": view.GetFilterVisibility(fid),
        "is_enabled": view.GetIsFilterEnabled(fid) if hasattr(view, "GetIsFilterEnabled") else True,
        "overrides": {
            "halftone": ovr.Halftone,
            "transparency": trans,
            "proj_line_color": get_rgb(ovr.ProjectionLineColor),
            "proj_line_weight": ovr.ProjectionLineWeight,
            "proj_line_pattern_info": pl_info,
            "proj_line_pattern": pl_info["id"],
            "proj_line_pattern_name": pl_info["name"],
            "surf_fg_visible": ovr.IsSurfaceForegroundPatternVisible if hasattr(ovr, "IsSurfaceForegroundPatternVisible") else True,
            "surf_fg_pattern_info": sfg_info,
            "surf_fg_pattern_id": sfg_info["id"],
            "surf_fg_pattern_name": sfg_info["name"],
            "surf_fg_pattern_color": get_rgb(ovr.SurfaceForegroundPatternColor),
            "surf_bg_visible": ovr.IsSurfaceBackgroundPatternVisible if hasattr(ovr, "IsSurfaceBackgroundPatternVisible") else True,
            "surf_bg_pattern_info": sbg_info,
            "surf_bg_pattern_id": sbg_info["id"],
            "surf_bg_pattern_name": sbg_info["name"],
            "surf_bg_pattern_color": get_rgb(ovr.SurfaceBackgroundPatternColor) if hasattr(ovr, "SurfaceBackgroundPatternColor") else None,
            "cut_line_color": get_rgb(ovr.CutLineColor),
            "cut_line_weight": ovr.CutLineWeight,
            "cut_line_pattern_info": cl_info,
            "cut_line_pattern": cl_info["id"],
            "cut_line_pattern_name": cl_info["name"],
            "cut_fg_visible": ovr.IsCutForegroundPatternVisible if hasattr(ovr, "IsCutForegroundPatternVisible") else True,
            "cut_fg_pattern_info": cfg_info,
            "cut_fg_pattern_id": cfg_info["id"],
            "cut_fg_pattern_name": cfg_info["name"],
            "cut_fg_pattern_color": get_rgb(ovr.CutForegroundPatternColor),
            "cut_bg_visible": ovr.IsCutBackgroundPatternVisible if hasattr(ovr, "IsCutBackgroundPatternVisible") else True,
            "cut_bg_pattern_info": cbg_info,
            "cut_bg_pattern_id": cbg_info["id"],
            "cut_bg_pattern_name": cbg_info["name"],
            "cut_bg_pattern_color": get_rgb(ovr.CutBackgroundPatternColor) if hasattr(ovr, "CutBackgroundPatternColor") else None
        }
    }


def build_override_graphic_settings(ovr, resolver):
    ogs = DB.OverrideGraphicSettings()
    if not ovr:
        return ogs

    ogs.SetHalftone(bool(ovr.get("halftone", False)))
    trans = int(ovr.get("transparency", 0) or 0)
    if 0 <= trans <= 100:
        if hasattr(ogs, "SetSurfaceTransparency"):
            ogs.SetSurfaceTransparency(trans)
        else:
            ogs.SetTransparency(trans)

    pcol = make_color(ovr.get("proj_line_color"))
    if pcol.IsValid:
        ogs.SetProjectionLineColor(pcol)
    pwt = ovr.get("proj_line_weight", -1)
    if pwt is not None and int(pwt) > 0:
        ogs.SetProjectionLineWeight(int(pwt))
    plp = resolver.resolve_line_pattern_id(
        ovr.get("proj_line_pattern_info"),
        ovr.get("proj_line_pattern", -1),
        ovr.get("proj_line_pattern_name")
    )
    if plp != DB.ElementId.InvalidElementId:
        ogs.SetProjectionLinePatternId(plp)

    ccol = make_color(ovr.get("cut_line_color"))
    if ccol.IsValid:
        ogs.SetCutLineColor(ccol)
    cwt = ovr.get("cut_line_weight", -1)
    if cwt is not None and int(cwt) > 0:
        ogs.SetCutLineWeight(int(cwt))
    clp = resolver.resolve_line_pattern_id(
        ovr.get("cut_line_pattern_info"),
        ovr.get("cut_line_pattern", -1),
        ovr.get("cut_line_pattern_name")
    )
    if clp != DB.ElementId.InvalidElementId:
        ogs.SetCutLinePatternId(clp)

    sfg_pat = resolver.resolve_drafting_fill_pattern_id(
        ovr.get("surf_fg_pattern_info"),
        ovr.get("surf_fg_pattern_id", -1),
        ovr.get("surf_fg_pattern_name")
    )
    if sfg_pat != DB.ElementId.InvalidElementId:
        ogs.SetSurfaceForegroundPatternId(sfg_pat)
    sfg_col = make_color(ovr.get("surf_fg_pattern_color"))
    if sfg_col.IsValid:
        ogs.SetSurfaceForegroundPatternColor(sfg_col)
    if hasattr(ogs, "SetSurfaceForegroundPatternVisible") and "surf_fg_visible" in ovr:
        ogs.SetSurfaceForegroundPatternVisible(bool(ovr["surf_fg_visible"]))

    if hasattr(ogs, "SetSurfaceBackgroundPatternId"):
        sbg_pat = resolver.resolve_drafting_fill_pattern_id(
            ovr.get("surf_bg_pattern_info"),
            ovr.get("surf_bg_pattern_id", -1),
            ovr.get("surf_bg_pattern_name")
        )
        if sbg_pat != DB.ElementId.InvalidElementId:
            ogs.SetSurfaceBackgroundPatternId(sbg_pat)
        sbg_col = make_color(ovr.get("surf_bg_pattern_color"))
        if sbg_col.IsValid:
            ogs.SetSurfaceBackgroundPatternColor(sbg_col)
        if hasattr(ogs, "SetSurfaceBackgroundPatternVisible") and "surf_bg_visible" in ovr:
            ogs.SetSurfaceBackgroundPatternVisible(bool(ovr["surf_bg_visible"]))

    cfg_pat = resolver.resolve_drafting_fill_pattern_id(
        ovr.get("cut_fg_pattern_info"),
        ovr.get("cut_fg_pattern_id", -1),
        ovr.get("cut_fg_pattern_name")
    )
    if cfg_pat != DB.ElementId.InvalidElementId:
        ogs.SetCutForegroundPatternId(cfg_pat)
    cfg_col = make_color(ovr.get("cut_fg_pattern_color"))
    if cfg_col.IsValid:
        ogs.SetCutForegroundPatternColor(cfg_col)
    if hasattr(ogs, "SetCutForegroundPatternVisible") and "cut_fg_visible" in ovr:
        ogs.SetCutForegroundPatternVisible(bool(ovr["cut_fg_visible"]))

    if hasattr(ogs, "SetCutBackgroundPatternId"):
        cbg_pat = resolver.resolve_drafting_fill_pattern_id(
            ovr.get("cut_bg_pattern_info"),
            ovr.get("cut_bg_pattern_id", -1),
            ovr.get("cut_bg_pattern_name")
        )
        if cbg_pat != DB.ElementId.InvalidElementId:
            ogs.SetCutBackgroundPatternId(cbg_pat)
        cbg_col = make_color(ovr.get("cut_bg_pattern_color"))
        if cbg_col.IsValid:
            ogs.SetCutBackgroundPatternColor(cbg_col)
        if hasattr(ogs, "SetCutBackgroundPatternVisible") and "cut_bg_visible" in ovr:
            ogs.SetCutBackgroundPatternVisible(bool(ovr["cut_bg_visible"]))

    return ogs


# ------------------------------------------------------------------------------
# DATATABLE BUILDER WITH NATIVE WPF BRUSHES
# ------------------------------------------------------------------------------
def create_filters_datatable():
    b_type = System.Windows.Media.Brush
    dt = DataTable("FiltersGrid")
    for col, dtype in [
        ("IsChecked", System.Boolean),
        ("OrderNum", System.Int32),
        ("FilterName", System.String),
        ("StatusText", System.String),
        ("StatusFg", b_type),
        ("IsEnabled", System.Boolean),
        ("IsVisible", System.Boolean),
        ("ProjLineBrush", b_type),
        ("ProjLineBorder", b_type),
        ("ProjLineText", System.String),
        ("ProjLineFg", b_type),
        ("SurfFgBrush", b_type),
        ("SurfFgBorder", b_type),
        ("SurfBgBrush", b_type),
        ("SurfBgBorder", b_type),
        ("SurfPatText", System.String),
        ("SurfPatFg", b_type),
        ("IsHalftone", System.Boolean),
        ("CutLineBrush", b_type),
        ("CutLineBorder", b_type),
        ("CutLineText", System.String),
        ("CutLineFg", b_type),
        ("CutFgBrush", b_type),
        ("CutFgBorder", b_type),
        ("CutBgBrush", b_type),
        ("CutBgBorder", b_type),
        ("CutPatText", System.String),
        ("CutPatFg", b_type),
        ("Transparency", System.Double),
        ("TransText", System.String),
        ("RawIndex", System.Int32)
    ]:
        dt.Columns.Add(col, dtype)
    return dt


def _fmt_line_brushes(rgb, wt, pat_name):
    parts = []
    if wt and int(wt) > 0:
        parts.append(u"W:{}".format(wt))
    if pat_name:
        parts.append(to_text(pat_name))
    if not rgb and not parts:
        return Brushes.Transparent, BRUSH_BDR_EMPTY, u"<No Override>", BRUSH_FG_MUTED
    sw = make_wpf_brush(rgb, BRUSH_BG_LIGHT)
    bdr = BRUSH_BDR_ACTIVE if rgb else BRUSH_BDR_EMPTY
    txt = u", ".join(parts) if parts else u"Color"
    return sw, bdr, txt, BRUSH_FG_NORMAL


def _fmt_pat_brushes(fg_rgb, fg_name, fg_vis, bg_rgb, bg_name, bg_vis):
    has_fg = bool(fg_rgb or fg_name or (fg_vis is False))
    has_bg = bool(bg_rgb or bg_name or (bg_vis is False))
    if not has_fg and not has_bg:
        return Brushes.Transparent, BRUSH_BDR_EMPTY, Brushes.Transparent, BRUSH_BDR_EMPTY, u"<No Override>", BRUSH_FG_MUTED

    fg_sw = make_wpf_brush(fg_rgb, BRUSH_BG_LIGHT) if fg_vis is not False else BRUSH_BG_HIDDEN
    bg_sw = make_wpf_brush(bg_rgb, BRUSH_BG_LIGHT) if bg_vis is not False else BRUSH_BG_HIDDEN
    fg_bdr = BRUSH_BDR_ACTIVE if fg_rgb else BRUSH_BDR_EMPTY
    bg_bdr = BRUSH_BDR_ACTIVE if bg_rgb else BRUSH_BDR_EMPTY

    labels = []
    if fg_vis is False:
        labels.append(u"FG:Off")
    elif fg_name:
        labels.append(to_text(fg_name))
    elif fg_rgb:
        labels.append(u"FG:Color")
    if bg_vis is False:
        labels.append(u"BG:Off")
    elif bg_name:
        labels.append(u"BG:" + to_text(bg_name))
    elif bg_rgb:
        labels.append(u"BG:Color")
    return fg_sw, fg_bdr, bg_sw, bg_bdr, u" | ".join(labels), BRUSH_FG_NORMAL


def populate_filters_datatable(dt, entries, resolver=None, checked_default=True):
    dt.Rows.Clear()
    for idx, entry in enumerate(entries):
        ovr = entry.get("overrides", {})
        row = dt.NewRow()
        row["IsChecked"] = bool(entry.get("_ui_checked", checked_default))
        row["OrderNum"] = idx + 1
        row["FilterName"] = to_text(entry.get("name", "Unnamed"))

        if resolver is not None:
            st_txt, st_fg = resolver.inspect_filter_availability(entry)
        else:
            st_txt, st_fg = u"Ready to Copy", BRUSH_STATUS_OK
        row["StatusText"] = st_txt
        row["StatusFg"] = st_fg

        row["IsEnabled"] = bool(entry.get("is_enabled", True))
        row["IsVisible"] = bool(entry.get("is_visible", True))

        pl_name = (ovr.get("proj_line_pattern_info") or {}).get("name") or ovr.get("proj_line_pattern_name")
        row["ProjLineBrush"], row["ProjLineBorder"], row["ProjLineText"], row["ProjLineFg"] = _fmt_line_brushes(
            ovr.get("proj_line_color"), ovr.get("proj_line_weight"), pl_name
        )

        sfg_n = (ovr.get("surf_fg_pattern_info") or {}).get("name") or ovr.get("surf_fg_pattern_name")
        sbg_n = (ovr.get("surf_bg_pattern_info") or {}).get("name") or ovr.get("surf_bg_pattern_name")
        row["SurfFgBrush"], row["SurfFgBorder"], row["SurfBgBrush"], row["SurfBgBorder"], row["SurfPatText"], row["SurfPatFg"] = _fmt_pat_brushes(
            ovr.get("surf_fg_pattern_color"), sfg_n, ovr.get("surf_fg_visible", True),
            ovr.get("surf_bg_pattern_color"), sbg_n, ovr.get("surf_bg_visible", True)
        )

        row["IsHalftone"] = bool(ovr.get("halftone", False))

        cl_name = (ovr.get("cut_line_pattern_info") or {}).get("name") or ovr.get("cut_line_pattern_name")
        row["CutLineBrush"], row["CutLineBorder"], row["CutLineText"], row["CutLineFg"] = _fmt_line_brushes(
            ovr.get("cut_line_color"), ovr.get("cut_line_weight"), cl_name
        )

        cfg_n = (ovr.get("cut_fg_pattern_info") or {}).get("name") or ovr.get("cut_fg_pattern_name")
        cbg_n = (ovr.get("cut_bg_pattern_info") or {}).get("name") or ovr.get("cut_bg_pattern_name")
        row["CutFgBrush"], row["CutFgBorder"], row["CutBgBrush"], row["CutBgBorder"], row["CutPatText"], row["CutPatFg"] = _fmt_pat_brushes(
            ovr.get("cut_fg_pattern_color"), cfg_n, ovr.get("cut_fg_visible", True),
            ovr.get("cut_bg_pattern_color"), cbg_n, ovr.get("cut_bg_visible", True)
        )

        trans = int(ovr.get("transparency", 0) or 0)
        row["Transparency"] = float(trans)
        row["TransText"] = u"{}%".format(trans) if trans > 0 else u"-"
        row["RawIndex"] = idx
        dt.Rows.Add(row)


# ------------------------------------------------------------------------------
# MULTI-SELECT DATAGRID CONTROLLER (WINDOWS SHIFT+CLICK, CTRL+CLICK, SPACEBAR)
# ------------------------------------------------------------------------------
class MultiSelectGridController(object):
    """Enables Windows-like Shift+Click, Ctrl+Click, Spacebar, and batch checkbox toggling."""

    def __init__(self, dg, dt, info_label=None, check_col="IsChecked"):
        self.dg = dg
        self.dt = dt
        self.info_label = info_label
        self.check_col = check_col
        self.last_check_idx = {}
        self._bind()

    def _bind(self):
        self.dg.SelectionMode = DataGridSelectionMode.Extended
        self.dg.SelectionUnit = DataGridSelectionUnit.FullRow
        self.dg.PreviewMouseLeftButtonDown += self._on_preview_mouse_down
        self.dg.PreviewKeyDown += self._on_preview_key_down
        self.dg.SelectionChanged += self._on_selection_changed

    def _find_visual_ancestors(self, dep_obj):
        cb = None
        row = None
        curr = dep_obj
        while curr is not None:
            if cb is None and isinstance(curr, CheckBox):
                cb = curr
            if row is None and isinstance(curr, DataGridRow):
                row = curr
                break
            if not isinstance(curr, Visual):
                break
            curr = VisualTreeHelper.GetParent(curr)
        return cb, row

    def _on_preview_mouse_down(self, sender, args):
        cb, row = self._find_visual_ancestors(args.OriginalSource)
        if cb is None or row is None:
            return

        col_name = to_text(cb.Tag) if cb.Tag else self.check_col
        if not self.dt.Columns.Contains(col_name):
            return

        drv = row.Item
        cur_idx = row.GetIndex()
        new_val = not bool(drv[col_name])
        mods = Keyboard.Modifiers

        if (mods & ModifierKeys.Shift) == ModifierKeys.Shift and col_name in self.last_check_idx:
            start_i = min(self.last_check_idx[col_name], cur_idx)
            end_i = max(self.last_check_idx[col_name], cur_idx)
            view_rows = self.dg.Items
            for i in range(start_i, min(end_i + 1, view_rows.Count)):
                view_rows[i][col_name] = new_val
            self.last_check_idx[col_name] = cur_idx
            args.Handled = True
            return

        if row.IsSelected and self.dg.SelectedItems.Count > 1:
            for sel_item in list(self.dg.SelectedItems):
                sel_item[col_name] = new_val
            self.last_check_idx[col_name] = cur_idx
            args.Handled = True
            return

        drv[col_name] = new_val
        self.last_check_idx[col_name] = cur_idx
        if (mods & ModifierKeys.Control) != ModifierKeys.Control:
            self.dg.SelectedIndex = cur_idx
        args.Handled = True

    def _on_preview_key_down(self, sender, args):
        if args.Key == Key.Space and self.dg.SelectedItems.Count > 0:
            first_item = self.dg.SelectedItems[0]
            new_val = not bool(first_item[self.check_col])
            for sel_item in list(self.dg.SelectedItems):
                sel_item[self.check_col] = new_val
            args.Handled = True

    def _on_selection_changed(self, sender, args):
        if self.info_label is not None:
            cnt = self.dg.SelectedItems.Count
            if cnt > 1:
                self.info_label.Text = u"{} rows selected (Spacebar or click checkbox to toggle all)".format(cnt)
            elif cnt == 1:
                self.info_label.Text = u"1 row selected (Shift+Click / Ctrl+Click for multi-select)"
            else:
                self.info_label.Text = u"Tip: Shift+Click or Ctrl+Click to select multiple filters"

    def set_selected_checked(self, state):
        if self.dg.SelectedItems.Count == 0:
            return 0
        cnt = 0
        for sel_item in list(self.dg.SelectedItems):
            sel_item[self.check_col] = bool(state)
            cnt += 1
        return cnt

    def get_selected_raw_indices(self):
        indices = []
        for sel_item in list(self.dg.SelectedItems):
            indices.append(int(sel_item["RawIndex"]))
        indices.sort()
        return indices


# ------------------------------------------------------------------------------
# REVIT-NATIVE WPF XAML DEFINITIONS (WITH HIGH-VISIBILITY DESTINATION CARDS)
# ------------------------------------------------------------------------------
VIEW_PICKER_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Select Paste Destination (Views / View Templates)"
        Width="620" Height="520" MinWidth="460" MinHeight="380"
        WindowStartupLocation="CenterOwner"
        Background="#F0F0F0" FontFamily="Segoe UI" FontSize="12"
        UseLayoutRounding="True" SnapsToDevicePixels="True">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <Grid Grid.Row="0" Margin="0,0,0,8">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <TextBlock Text="Search:" VerticalAlignment="Center" Margin="0,0,8,0" FontWeight="SemiBold"/>
            <TextBox Name="txt_search" Grid.Column="1" Height="25" VerticalContentAlignment="Center" Padding="5,0"/>
            <CheckBox Name="chk_templates_only" Grid.Column="2" Content="View Templates Only" VerticalAlignment="Center" Margin="10,0,0,0" FontWeight="SemiBold"/>
        </Grid>
        <DataGrid Name="dg_views" Grid.Row="1" AutoGenerateColumns="False" CanUserAddRows="False"
                  CanUserDeleteRows="False" CanUserResizeRows="False" HeadersVisibility="Column"
                  SelectionMode="Extended" SelectionUnit="FullRow"
                  GridLinesVisibility="All" HorizontalGridLinesBrush="#E2E2E2" VerticalGridLinesBrush="#E2E2E2"
                  Background="#FFFFFF" BorderBrush="#ABADB3" BorderThickness="1" RowHeight="25">
            <DataGrid.Columns>
                <DataGridTemplateColumn Header="Use" Width="48">
                    <DataGridTemplateColumn.CellTemplate>
                        <DataTemplate>
                            <CheckBox Tag="IsSelected" IsChecked="{Binding IsSelected, Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}"
                                      HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </DataTemplate>
                    </DataGridTemplateColumn.CellTemplate>
                </DataGridTemplateColumn>
                <DataGridTextColumn Header="Group / Type" Binding="{Binding ViewKind}" Width="150" IsReadOnly="True"/>
                <DataGridTextColumn Header="View / Template Name" Binding="{Binding ViewName}" Width="*" IsReadOnly="True"/>
            </DataGrid.Columns>
        </DataGrid>
        <Grid Grid.Row="2" Margin="0,8,0,8">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <StackPanel Orientation="Horizontal">
                <Button Name="btn_check_all" Content="Check All" Width="78" Height="24" Margin="0,0,6,0"/>
                <Button Name="btn_check_none" Content="Check None" Width="84" Height="24" Margin="0,0,6,0"/>
                <Button Name="btn_check_sel" Content="Check Selected" Width="100" Height="24"/>
            </StackPanel>
            <TextBlock Name="lbl_sel_views" Grid.Column="1" Text="Shift+Click / Spacebar supported"
                       Foreground="#555555" FontSize="11" HorizontalAlignment="Right" VerticalAlignment="Center"/>
        </Grid>
        <Border Grid.Row="3" BorderBrush="#D9D9D9" BorderThickness="0,1,0,0" Padding="0,10,0,0">
            <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
                <Button Name="btn_ok" Content="OK" Width="82" Height="25" Margin="0,0,8,0" IsDefault="True" FontWeight="SemiBold"/>
                <Button Name="btn_cancel" Content="Cancel" Width="82" Height="25" IsCancel="True"/>
            </StackPanel>
        </Border>
    </Grid>
</Window>
"""

_GRID_COLS_XAML = """
    <DataGridTemplateColumn Header="Use" Width="40">
        <DataGridTemplateColumn.CellTemplate>
            <DataTemplate>
                <CheckBox Tag="IsChecked" IsChecked="{Binding IsChecked, Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}"
                          HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </DataTemplate>
        </DataGridTemplateColumn.CellTemplate>
    </DataGridTemplateColumn>
    <DataGridTextColumn Header="#" Binding="{Binding OrderNum}" Width="32" IsReadOnly="True"/>
    <DataGridTextColumn Header="Name" Binding="{Binding FilterName}" Width="185" IsReadOnly="True"/>
    <DataGridTemplateColumn Header="Model Status" Width="135">
        <DataGridTemplateColumn.CellTemplate>
            <DataTemplate>
                <TextBlock Text="{Binding StatusText}" Foreground="{Binding StatusFg}"
                           Margin="5,0" VerticalAlignment="Center" TextTrimming="CharacterEllipsis"/>
            </DataTemplate>
        </DataGridTemplateColumn.CellTemplate>
    </DataGridTemplateColumn>
    <DataGridTemplateColumn Header="Enable Filter" Width="78">
        <DataGridTemplateColumn.CellTemplate>
            <DataTemplate>
                <CheckBox Tag="IsEnabled" IsChecked="{Binding IsEnabled, Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}"
                          HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </DataTemplate>
        </DataGridTemplateColumn.CellTemplate>
    </DataGridTemplateColumn>
    <DataGridTemplateColumn Header="Visibility" Width="62">
        <DataGridTemplateColumn.CellTemplate>
            <DataTemplate>
                <CheckBox Tag="IsVisible" IsChecked="{Binding IsVisible, Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}"
                          HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </DataTemplate>
        </DataGridTemplateColumn.CellTemplate>
    </DataGridTemplateColumn>
    <DataGridTemplateColumn Header="Projection: Lines" Width="130">
        <DataGridTemplateColumn.CellTemplate>
            <DataTemplate>
                <StackPanel Orientation="Horizontal" VerticalAlignment="Center" Margin="5,0">
                    <Border Width="13" Height="13" Background="{Binding ProjLineBrush}" BorderBrush="{Binding ProjLineBorder}" BorderThickness="1" Margin="0,0,6,0"/>
                    <TextBlock Text="{Binding ProjLineText}" Foreground="{Binding ProjLineFg}" VerticalAlignment="Center" TextTrimming="CharacterEllipsis"/>
                </StackPanel>
            </DataTemplate>
        </DataGridTemplateColumn.CellTemplate>
    </DataGridTemplateColumn>
    <DataGridTemplateColumn Header="Projection: Patterns" Width="155">
        <DataGridTemplateColumn.CellTemplate>
            <DataTemplate>
                <StackPanel Orientation="Horizontal" VerticalAlignment="Center" Margin="5,0">
                    <Border Width="12" Height="12" Background="{Binding SurfFgBrush}" BorderBrush="{Binding SurfFgBorder}" BorderThickness="1" Margin="0,0,2,0" ToolTip="Surface FG"/>
                    <Border Width="12" Height="12" Background="{Binding SurfBgBrush}" BorderBrush="{Binding SurfBgBorder}" BorderThickness="1" Margin="0,0,6,0" ToolTip="Surface BG"/>
                    <TextBlock Text="{Binding SurfPatText}" Foreground="{Binding SurfPatFg}" VerticalAlignment="Center" TextTrimming="CharacterEllipsis"/>
                </StackPanel>
            </DataTemplate>
        </DataGridTemplateColumn.CellTemplate>
    </DataGridTemplateColumn>
    <DataGridTemplateColumn Header="Halftone" Width="60">
        <DataGridTemplateColumn.CellTemplate>
            <DataTemplate>
                <CheckBox Tag="IsHalftone" IsChecked="{Binding IsHalftone, Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}"
                          HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </DataTemplate>
        </DataGridTemplateColumn.CellTemplate>
    </DataGridTemplateColumn>
    <DataGridTemplateColumn Header="Cut: Lines" Width="125">
        <DataGridTemplateColumn.CellTemplate>
            <DataTemplate>
                <StackPanel Orientation="Horizontal" VerticalAlignment="Center" Margin="5,0">
                    <Border Width="13" Height="13" Background="{Binding CutLineBrush}" BorderBrush="{Binding CutLineBorder}" BorderThickness="1" Margin="0,0,6,0"/>
                    <TextBlock Text="{Binding CutLineText}" Foreground="{Binding CutLineFg}" VerticalAlignment="Center" TextTrimming="CharacterEllipsis"/>
                </StackPanel>
            </DataTemplate>
        </DataGridTemplateColumn.CellTemplate>
    </DataGridTemplateColumn>
    <DataGridTemplateColumn Header="Cut: Patterns" Width="150">
        <DataGridTemplateColumn.CellTemplate>
            <DataTemplate>
                <StackPanel Orientation="Horizontal" VerticalAlignment="Center" Margin="5,0">
                    <Border Width="12" Height="12" Background="{Binding CutFgBrush}" BorderBrush="{Binding CutFgBorder}" BorderThickness="1" Margin="0,0,2,0" ToolTip="Cut FG"/>
                    <Border Width="12" Height="12" Background="{Binding CutBgBrush}" BorderBrush="{Binding CutBgBorder}" BorderThickness="1" Margin="0,0,6,0" ToolTip="Cut BG"/>
                    <TextBlock Text="{Binding CutPatText}" Foreground="{Binding CutPatFg}" VerticalAlignment="Center" TextTrimming="CharacterEllipsis"/>
                </StackPanel>
            </DataTemplate>
        </DataGridTemplateColumn.CellTemplate>
    </DataGridTemplateColumn>
    <DataGridTemplateColumn Header="Transp" Width="85">
        <DataGridTemplateColumn.CellTemplate>
            <DataTemplate>
                <StackPanel Orientation="Horizontal" VerticalAlignment="Center" Margin="5,0">
                    <ProgressBar Minimum="0" Maximum="100" Value="{Binding Transparency, Mode=OneWay}" Width="34" Height="9" Foreground="#0696D7" Margin="0,0,5,0"/>
                    <TextBlock Text="{Binding TransText}" Foreground="#333333" VerticalAlignment="Center"/>
                </StackPanel>
            </DataTemplate>
        </DataGridTemplateColumn.CellTemplate>
    </DataGridTemplateColumn>
"""

MAIN_WINDOW_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Visibility/Graphic Overrides - Filter Transfer (Pro)"
        Width="1240" Height="720" MinWidth="980" MinHeight="580"
        WindowStartupLocation="CenterScreen"
        Background="#F0F0F0" FontFamily="Segoe UI" FontSize="12"
        UseLayoutRounding="True" SnapsToDevicePixels="True">
    <Window.Resources>
        <Style x:Key="RevitBtn" TargetType="Button">
            <Setter Property="Height" Value="24"/>
            <Setter Property="MinWidth" Value="70"/>
            <Setter Property="Padding" Value="9,2"/>
            <Setter Property="Background" Value="#FBFBFB"/>
            <Setter Property="Foreground" Value="#1E1E1E"/>
            <Setter Property="BorderBrush" Value="#ABADB3"/>
            <Setter Property="BorderThickness" Value="1"/>
        </Style>
        <Style x:Key="RevitPrimaryBtn" TargetType="Button" BasedOn="{StaticResource RevitBtn}">
            <Setter Property="BorderBrush" Value="#0078D4"/>
            <Setter Property="BorderThickness" Value="1.5"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
        </Style>
        <!-- Flat High-Visibility Badge Button Style (renders dynamic Python Background/Foreground cleanly) -->
        <Style x:Key="TargetSelectBtn" TargetType="Button">
            <Setter Property="Height" Value="26"/>
            <Setter Property="MinWidth" Value="128"/>
            <Setter Property="Padding" Value="10,2"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="btnBdr"
                                Background="{TemplateBinding Background}"
                                BorderBrush="{TemplateBinding BorderBrush}"
                                BorderThickness="{TemplateBinding BorderThickness}"
                                CornerRadius="3"
                                Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="btnBdr" Property="Opacity" Value="0.88"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
        <Style x:Key="RevitDataGrid" TargetType="DataGrid">
            <Setter Property="AutoGenerateColumns" Value="False"/>
            <Setter Property="CanUserAddRows" Value="False"/>
            <Setter Property="CanUserDeleteRows" Value="False"/>
            <Setter Property="CanUserResizeRows" Value="False"/>
            <Setter Property="CanUserSortColumns" Value="False"/>
            <Setter Property="HeadersVisibility" Value="Column"/>
            <Setter Property="SelectionMode" Value="Extended"/>
            <Setter Property="SelectionUnit" Value="FullRow"/>
            <Setter Property="GridLinesVisibility" Value="All"/>
            <Setter Property="HorizontalGridLinesBrush" Value="#E2E2E2"/>
            <Setter Property="VerticalGridLinesBrush" Value="#E2E2E2"/>
            <Setter Property="Background" Value="#FFFFFF"/>
            <Setter Property="BorderBrush" Value="#ABADB3"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="RowHeight" Value="25"/>
        </Style>
        <Style TargetType="DataGridColumnHeader">
            <Setter Property="Background" Value="#F5F6F7"/>
            <Setter Property="Foreground" Value="#1E1E1E"/>
            <Setter Property="BorderBrush" Value="#D8D8D8"/>
            <Setter Property="BorderThickness" Value="0,0,1,1"/>
            <Setter Property="Padding" Value="6,5"/>
        </Style>
        <Style TargetType="DataGridRow">
            <Style.Triggers>
                <Trigger Property="IsSelected" Value="True">
                    <Setter Property="Background" Value="#CDE4FA"/>
                    <Setter Property="Foreground" Value="#111111"/>
                </Trigger>
            </Style.Triggers>
        </Style>
        <Style TargetType="DataGridCell">
            <Setter Property="BorderThickness" Value="0"/>
            <Style.Triggers>
                <Trigger Property="IsSelected" Value="True">
                    <Setter Property="Background" Value="#CDE4FA"/>
                    <Setter Property="Foreground" Value="#111111"/>
                </Trigger>
            </Style.Triggers>
        </Style>
    </Window.Resources>

    <Grid>
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- Header Bar -->
        <Border Grid.Row="0" Background="#FFFFFF" BorderBrush="#D9D9D9" BorderThickness="0,0,0,1" Padding="14,8">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
                    <Border Width="4" Height="16" Background="#0696D7" Margin="0,0,8,0"/>
                    <TextBlock Name="lbl_doc_context" Text="Document: - | Active View: -" FontWeight="SemiBold" VerticalAlignment="Center"/>
                </StackPanel>
                <StackPanel Grid.Column="1" Orientation="Horizontal">
                    <Button Name="btn_quick_copy_active" Content="Quick Copy Active View" Style="{StaticResource RevitPrimaryBtn}" Margin="0,0,8,0"
                            ToolTip="Instantly copy all filters from Active View to Quick Clipboard"/>
                    <Button Name="btn_open_folder" Content="Open Folder" Style="{StaticResource RevitBtn}" Margin="0,0,6,0"/>
                    <Button Name="btn_change_folder" Content="Folder..." Style="{StaticResource RevitBtn}"/>
                </StackPanel>
            </Grid>
        </Border>

        <!-- View Template Lock Warning Banner -->
        <Border Name="bdr_vt_warning" Grid.Row="1" Background="#FFF8E1" BorderBrush="#E2B93B" BorderThickness="0,0,0,1" Padding="14,6" Visibility="Collapsed">
            <CheckBox Name="chk_apply_to_vt" IsChecked="True" Foreground="#5C4300" FontWeight="SemiBold"
                      Content="Active View Filters are locked by a View Template. Redirect Paste/Apply directly to View Template."/>
        </Border>

        <!-- Unified Tabs -->
        <TabControl Name="main_tabs" Grid.Row="2" Margin="10,8,10,6" Background="#FFFFFF" BorderBrush="#ABADB3">

            <!-- TAB 1: PASTE / APPLY FILTER STATE -->
            <TabItem Header="  1. Paste / Apply State  ">
                <Grid Margin="10">
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="265"/>
                        <ColumnDefinition Width="10"/>
                        <ColumnDefinition Width="*"/>
                    </Grid.ColumnDefinitions>

                    <Grid Grid.Column="0">
                        <Grid.RowDefinitions>
                            <RowDefinition Height="Auto"/>
                            <RowDefinition Height="Auto"/>
                            <RowDefinition Height="*"/>
                            <RowDefinition Height="Auto"/>
                            <RowDefinition Height="Auto"/>
                            <RowDefinition Height="Auto"/>
                        </Grid.RowDefinitions>
                        <Grid Grid.Row="0" Margin="0,0,0,4">
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="*"/>
                                <ColumnDefinition Width="Auto"/>
                            </Grid.ColumnDefinitions>
                            <TextBlock Text="Saved Filter Presets:" VerticalAlignment="Center" FontWeight="SemiBold"/>
                            <Button Name="btn_browse_json" Grid.Column="1" Content="Browse .json..." Height="21" Padding="6,0"
                                    Background="#FBFBFB" BorderBrush="#ABADB3"/>
                        </Grid>
                        <TextBox Name="txt_preset_search" Grid.Row="1" Height="24" VerticalContentAlignment="Center" Padding="5,0" Margin="0,0,0,6"/>
                        <ListBox Name="lb_presets" Grid.Row="2" BorderBrush="#ABADB3" BorderThickness="1" DisplayMemberPath="DisplayLabel"/>
                        <Border Grid.Row="3" Background="#F7F8F9" BorderBrush="#E0E0E0" BorderThickness="1,0,1,1" Padding="8,6">
                            <TextBlock Name="lbl_preset_meta" Text="Select a preset to preview." Foreground="#555555" FontSize="11" TextWrapping="Wrap"/>
                        </Border>
                        <StackPanel Grid.Row="4" Orientation="Horizontal" Margin="0,6,0,0">
                            <Button Name="btn_refresh_presets" Content="Refresh" Style="{StaticResource RevitBtn}" Margin="0,0,6,0"/>
                            <Button Name="btn_report_preset" Content="Report" Style="{StaticResource RevitBtn}" Margin="0,0,6,0"/>
                            <Button Name="btn_delete_preset" Content="Delete" Style="{StaticResource RevitBtn}"/>
                        </StackPanel>
                        <Button Name="btn_import_rvt" Grid.Row="5" Content="Import Missing Filters from .RVT File..."
                                Style="{StaticResource RevitBtn}" Margin="0,6,0,0"
                                ToolTip="Pull missing filters from a closed .RVT file on disk and upgrade v1.0 presets"/>
                    </Grid>

                    <Grid Grid.Column="2">
                        <Grid.RowDefinitions>
                            <RowDefinition Height="Auto"/>
                            <RowDefinition Height="*"/>
                            <RowDefinition Height="Auto"/>
                            <RowDefinition Height="Auto"/>
                        </Grid.RowDefinitions>
                        <Grid Grid.Row="0" Margin="0,0,0,4">
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="Auto"/>
                                <ColumnDefinition Width="*"/>
                            </Grid.ColumnDefinitions>
                            <TextBlock Text="Filters to Paste (in priority order - top overrides first):" FontWeight="SemiBold"/>
                            <TextBlock Name="lbl_load_sel_info" Grid.Column="1" Text="Tip: Shift+Click or Ctrl+Click to select multiple filters"
                                       Foreground="#0066B4" FontSize="11" HorizontalAlignment="Right"/>
                        </Grid>

                        <DataGrid Name="dg_load_filters" Grid.Row="1" Style="{StaticResource RevitDataGrid}">
                            <DataGrid.Columns>""" + _GRID_COLS_XAML + """</DataGrid.Columns>
                        </DataGrid>

                        <Grid Grid.Row="2" Margin="0,6,0,8">
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="*"/>
                                <ColumnDefinition Width="Auto"/>
                            </Grid.ColumnDefinitions>
                            <StackPanel Orientation="Horizontal">
                                <Button Name="btn_load_all" Content="Check All" Style="{StaticResource RevitBtn}" Margin="0,0,5,0"/>
                                <Button Name="btn_load_none" Content="Check None" Style="{StaticResource RevitBtn}" Margin="0,0,5,0"/>
                                <Button Name="btn_load_chk_sel" Content="Check Selected" Style="{StaticResource RevitBtn}" Margin="0,0,5,0"/>
                                <Button Name="btn_load_unchk_sel" Content="Uncheck Selected" Style="{StaticResource RevitBtn}" Margin="0,0,14,0"/>
                                <Button Name="btn_load_up" Content="Move Up" Style="{StaticResource RevitBtn}" Margin="0,0,5,0"/>
                                <Button Name="btn_load_down" Content="Move Down" Style="{StaticResource RevitBtn}"/>
                            </StackPanel>
                            <Button Name="btn_save_checked_new" Grid.Column="1" Content="Save Checked As New..." Style="{StaticResource RevitBtn}"/>
                        </Grid>

                        <!-- EMPHASIZED PASTE DESTINATION & APPLY MODE PANEL -->
                        <Grid Grid.Row="3">
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="1.22*"/>
                                <ColumnDefinition Width="10"/>
                                <ColumnDefinition Width="1*"/>
                            </Grid.ColumnDefinitions>

                            <!-- LEFT BOX: HIGH-VISIBILITY PASTE DESTINATION -->
                            <Border Grid.Column="0" Background="#FFFFFF" BorderBrush="#6BAce4" BorderThickness="1.5" CornerRadius="4">
                                <Grid>
                                    <Grid.ColumnDefinitions>
                                        <ColumnDefinition Width="5"/>
                                        <ColumnDefinition Width="*"/>
                                    </Grid.ColumnDefinitions>
                                    <Border Grid.Column="0" Background="#0078D4" CornerRadius="3,0,0,3"/>

                                    <StackPanel Grid.Column="1" Margin="10,7,10,8">
                                        <StackPanel Orientation="Horizontal" Margin="0,0,0,6">
                                            <Border Background="#0078D4" CornerRadius="2" Padding="6,1" Margin="0,0,8,0">
                                                <TextBlock Text="STEP 1" Foreground="#FFFFFF" FontSize="10" FontWeight="Bold"/>
                                            </Border>
                                            <TextBlock Text="PASTE DESTINATION" Foreground="#004E92" FontSize="12.5" FontWeight="Bold" VerticalAlignment="Center"/>
                                        </StackPanel>

                                        <!-- Option Card 1: Active View -->
                                        <Border Name="bdr_dest_active" Background="#E6F3FF" BorderBrush="#0078D4" BorderThickness="2"
                                                CornerRadius="3" Padding="8,5" Margin="0,0,0,6" Cursor="Hand">
                                            <Grid>
                                                <Grid.ColumnDefinitions>
                                                    <ColumnDefinition Width="Auto"/>
                                                    <ColumnDefinition Width="*"/>
                                                </Grid.ColumnDefinitions>
                                                <RadioButton Name="rb_target_active" GroupName="PasteDestGrp" IsChecked="True"
                                                             Content="1. Paste to Active View" FontWeight="Bold" FontSize="12.5"
                                                             Foreground="#111111" VerticalAlignment="Center"/>
                                                <Border Grid.Column="1" Background="#FFFFFF" BorderBrush="#B8D8F8" BorderThickness="1"
                                                        CornerRadius="2" Padding="6,1" HorizontalAlignment="Right" VerticalAlignment="Center" Margin="8,0,0,0">
                                                    <TextBlock Name="lbl_active_target_name" Text="-" Foreground="#004E92" FontSize="11.5"
                                                               FontWeight="SemiBold" MaxWidth="230" TextTrimming="CharacterEllipsis"/>
                                                </Border>
                                            </Grid>
                                        </Border>

                                        <!-- Option Card 2: Selected Views / View Templates -->
                                        <Border Name="bdr_dest_multi" Background="#F9FAFB" BorderBrush="#D4D8DC" BorderThickness="1"
                                                CornerRadius="3" Padding="8,5" Cursor="Hand">
                                            <Grid>
                                                <Grid.ColumnDefinitions>
                                                    <ColumnDefinition Width="Auto"/>
                                                    <ColumnDefinition Width="*"/>
                                                    <ColumnDefinition Width="Auto"/>
                                                </Grid.ColumnDefinitions>
                                                <RadioButton Name="rb_target_multi" GroupName="PasteDestGrp"
                                                             Content="2. Selected Views / Templates" FontWeight="SemiBold" FontSize="12.5"
                                                             Foreground="#222222" VerticalAlignment="Center"/>
                                                <TextBlock Name="lbl_multi_target_info" Grid.Column="1" Text="No views selected"
                                                           Foreground="#777777" FontSize="11" VerticalAlignment="Center"
                                                           Margin="8,0,8,0" TextTrimming="CharacterEllipsis"/>
                                                <Button Name="btn_pick_views" Grid.Column="2" Content="Select Views... (0)"
                                                        Style="{StaticResource TargetSelectBtn}"
                                                        Background="#F0F6FC" Foreground="#004E92" BorderBrush="#7AB2E6" BorderThickness="1"/>
                                            </Grid>
                                        </Border>
                                    </StackPanel>
                                </Grid>
                            </Border>

                            <!-- RIGHT BOX: APPLY MODE -->
                            <Border Grid.Column="2" Background="#FFFFFF" BorderBrush="#C8CDD2" BorderThickness="1" CornerRadius="4" Padding="10,7,10,8">
                                <StackPanel>
                                    <StackPanel Orientation="Horizontal" Margin="0,0,0,6">
                                        <Border Background="#5A6570" CornerRadius="2" Padding="6,1" Margin="0,0,8,0">
                                            <TextBlock Text="STEP 2" Foreground="#FFFFFF" FontSize="10" FontWeight="Bold"/>
                                        </Border>
                                        <TextBlock Text="FILTER APPLY MODE" Foreground="#2C353D" FontSize="12.5" FontWeight="Bold" VerticalAlignment="Center"/>
                                    </StackPanel>

                                    <Border Name="bdr_mode_merge" Background="#E6F3FF" BorderBrush="#0078D4" BorderThickness="1.5"
                                            CornerRadius="3" Padding="8,6" Margin="0,0,0,6" Cursor="Hand">
                                        <RadioButton Name="rb_mode_merge" GroupName="PasteModeGrp" IsChecked="True"
                                                     Content="Merge / Update Selected (Auto-Pull Missing)"
                                                     FontWeight="SemiBold" Foreground="#111111" VerticalAlignment="Center"/>
                                    </Border>

                                    <Border Name="bdr_mode_replace" Background="#F9FAFB" BorderBrush="#D4D8DC" BorderThickness="1"
                                            CornerRadius="3" Padding="8,6" Cursor="Hand">
                                        <RadioButton Name="rb_mode_replace" GroupName="PasteModeGrp"
                                                     Content="Replace All Existing Filters in Target View(s)"
                                                     FontWeight="SemiBold" Foreground="#222222" VerticalAlignment="Center"/>
                                    </Border>
                                </StackPanel>
                            </Border>
                        </Grid>
                    </Grid>
                </Grid>
            </TabItem>

            <!-- TAB 2: COPY / SAVE FILTER STATE -->
            <TabItem Header="  2. Copy / Save State from Model  ">
                <Grid Margin="10">
                    <Grid.RowDefinitions>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="*"/>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="Auto"/>
                    </Grid.RowDefinitions>
                    <Grid Grid.Row="0" Margin="0,0,0,8">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="Auto"/>
                            <ColumnDefinition Width="360"/>
                            <ColumnDefinition Width="Auto"/>
                            <ColumnDefinition Width="*"/>
                        </Grid.ColumnDefinitions>
                        <TextBlock Text="Source View / View Template:" VerticalAlignment="Center" Margin="0,0,8,0" FontWeight="SemiBold"/>
                        <ComboBox Name="cmb_source_view" Grid.Column="1" Height="24" VerticalContentAlignment="Center" DisplayMemberPath="DisplayName"/>
                        <Button Name="btn_use_active_view" Grid.Column="2" Content="Use Active View" Style="{StaticResource RevitBtn}" Margin="8,0,0,0"/>
                        <TextBlock Name="lbl_save_sel_info" Grid.Column="3" Text="Tip: Shift+Click or Ctrl+Click to select multiple filters"
                                   Foreground="#0066B4" FontSize="11" HorizontalAlignment="Right" VerticalAlignment="Center"/>
                    </Grid>

                    <DataGrid Name="dg_save_filters" Grid.Row="1" Style="{StaticResource RevitDataGrid}">
                        <DataGrid.Columns>""" + _GRID_COLS_XAML + """</DataGrid.Columns>
                    </DataGrid>

                    <StackPanel Grid.Row="2" Orientation="Horizontal" Margin="0,6,0,8">
                        <Button Name="btn_save_all" Content="Check All" Style="{StaticResource RevitBtn}" Margin="0,0,5,0"/>
                        <Button Name="btn_save_none" Content="Check None" Style="{StaticResource RevitBtn}" Margin="0,0,5,0"/>
                        <Button Name="btn_save_chk_sel" Content="Check Selected" Style="{StaticResource RevitBtn}" Margin="0,0,5,0"/>
                        <Button Name="btn_save_unchk_sel" Content="Uncheck Selected" Style="{StaticResource RevitBtn}" Margin="0,0,14,0"/>
                        <Button Name="btn_save_up" Content="Move Up" Style="{StaticResource RevitBtn}" Margin="0,0,5,0"/>
                        <Button Name="btn_save_down" Content="Move Down" Style="{StaticResource RevitBtn}"/>
                    </StackPanel>

                    <GroupBox Grid.Row="3" Header="Copy / Save Checked Filters as Portable JSON Preset (v3.0 with Rules)" BorderBrush="#D0D0D0" Padding="10,8">
                        <Grid>
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="Auto"/>
                                <ColumnDefinition Width="*"/>
                                <ColumnDefinition Width="Auto"/>
                            </Grid.ColumnDefinitions>
                            <TextBlock Text="Preset Name:" VerticalAlignment="Center" Margin="0,0,8,0" FontWeight="SemiBold"/>
                            <TextBox Name="txt_save_name" Grid.Column="1" Height="24" VerticalContentAlignment="Center" Padding="5,0" Margin="0,0,10,0"/>
                            <Button Name="btn_save_preset" Grid.Column="2" Content="Copy / Save Preset" Style="{StaticResource RevitPrimaryBtn}" Width="145"/>
                        </Grid>
                    </GroupBox>
                </Grid>
            </TabItem>
        </TabControl>

        <!-- Revit Native Footer -->
        <Border Grid.Row="3" Background="#F0F0F0" BorderBrush="#D6D6D6" BorderThickness="0,1,0,0" Padding="12,8,12,10">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <TextBlock Name="lbl_status" Text="Ready." Foreground="#555555" VerticalAlignment="Center" TextTrimming="CharacterEllipsis" Margin="2,0,12,0"/>
                <StackPanel Grid.Column="1" Orientation="Horizontal">
                    <Button Name="btn_ok" Content="OK" Style="{StaticResource RevitPrimaryBtn}" Width="82" Margin="0,0,8,0"/>
                    <Button Name="btn_cancel" Content="Cancel" Style="{StaticResource RevitBtn}" Width="82" Margin="0,0,8,0" IsCancel="True"/>
                    <Button Name="btn_apply" Content="Paste -> Active View" Style="{StaticResource RevitPrimaryBtn}" MinWidth="135"/>
                </StackPanel>
            </Grid>
        </Border>
    </Grid>
</Window>
"""


# ------------------------------------------------------------------------------
# MULTI-VIEW / VIEW TEMPLATE PICKER DIALOG
# ------------------------------------------------------------------------------
class RevitViewPickerDialog(object):
    def __init__(self, parent_win, all_views, preselected_ids):
        self.win = XamlReader.Parse(VIEW_PICKER_XAML)
        if parent_win is not None:
            self.win.Owner = parent_win
        else:
            set_revit_owner(self.win)

        self.all_views = all_views
        self.selected_ids = set(preselected_ids)
        self.result_views = None

        self.txt_search = self.win.FindName("txt_search")
        self.chk_templates_only = self.win.FindName("chk_templates_only")
        self.dg_views = self.win.FindName("dg_views")
        self.lbl_sel_views = self.win.FindName("lbl_sel_views")

        self.dt = DataTable("ViewsPicker")
        self.dt.Columns.Add("IsSelected", System.Boolean)
        self.dt.Columns.Add("ViewKind", System.String)
        self.dt.Columns.Add("ViewName", System.String)
        self.dt.Columns.Add("RawIndex", System.Int32)

        self._populate()
        self.dg_views.ItemsSource = self.dt.DefaultView
        self.ms_ctrl = MultiSelectGridController(self.dg_views, self.dt, self.lbl_sel_views, check_col="IsSelected")

        self.txt_search.TextChanged += self._on_filter_changed
        self.chk_templates_only.Checked += self._on_filter_changed
        self.chk_templates_only.Unchecked += self._on_filter_changed
        self.win.FindName("btn_check_all").Click += self._on_check_all
        self.win.FindName("btn_check_none").Click += self._on_check_none
        self.win.FindName("btn_check_sel").Click += self._on_check_sel
        self.win.FindName("btn_ok").Click += self._on_ok
        self.win.FindName("btn_cancel").Click += self._on_cancel

    def show_dialog(self):
        self.win.ShowDialog()
        return self.result_views

    def _sync_selection(self):
        for row in self.dt.Rows:
            vid = get_id_val(self.all_views[int(row["RawIndex"])].Id)
            if bool(row["IsSelected"]):
                self.selected_ids.add(vid)
            elif vid in self.selected_ids:
                self.selected_ids.remove(vid)

    def _populate(self):
        self.dt.Rows.Clear()
        q = to_text(self.txt_search.Text).strip().lower()
        tpl_only = bool(self.chk_templates_only.IsChecked)
        for idx, v in enumerate(self.all_views):
            if tpl_only and not v.IsTemplate:
                continue
            if q and q not in to_text(v.Name).lower() and q not in to_text(v.ViewType).lower():
                continue
            row = self.dt.NewRow()
            row["IsSelected"] = get_id_val(v.Id) in self.selected_ids
            row["ViewKind"] = u"1. View Template" if v.IsTemplate else u"2. View ({})".format(to_text(v.ViewType))
            row["ViewName"] = to_text(v.Name)
            row["RawIndex"] = idx
            self.dt.Rows.Add(row)

    def _on_filter_changed(self, sender, args):
        self._sync_selection()
        self._populate()

    def _on_check_all(self, sender, args):
        for row in self.dt.Rows:
            row["IsSelected"] = True

    def _on_check_none(self, sender, args):
        for row in self.dt.Rows:
            row["IsSelected"] = False

    def _on_check_sel(self, sender, args):
        self.ms_ctrl.set_selected_checked(True)

    def _on_ok(self, sender, args):
        self._sync_selection()
        self.result_views = [v for v in self.all_views if get_id_val(v.Id) in self.selected_ids]
        self.win.Close()

    def _on_cancel(self, sender, args):
        self.result_views = None
        self.win.Close()


# ------------------------------------------------------------------------------
# UNIFIED COPY & PASTE WINDOW CONTROLLER
# ------------------------------------------------------------------------------
class UnifiedFilterPresetWindow(object):
    def __init__(self, doc, uidoc, export_path):
        self.win = XamlReader.Parse(MAIN_WINDOW_XAML)
        set_revit_owner(self.win)

        self.doc = doc
        self.uidoc = uidoc
        self.active_view = get_target_active_view(doc, uidoc)
        self.export_path = export_path
        self.resolver = DocumentResourceResolver(doc)

        for cname in [
            "lbl_doc_context", "btn_quick_copy_active", "btn_open_folder", "btn_change_folder",
            "bdr_vt_warning", "chk_apply_to_vt", "main_tabs",
            "btn_browse_json", "txt_preset_search", "lb_presets", "lbl_preset_meta",
            "btn_refresh_presets", "btn_report_preset", "btn_delete_preset", "btn_import_rvt",
            "lbl_load_sel_info", "dg_load_filters",
            "btn_load_all", "btn_load_none", "btn_load_chk_sel", "btn_load_unchk_sel",
            "btn_load_up", "btn_load_down", "btn_save_checked_new",
            "bdr_dest_active", "rb_target_active", "lbl_active_target_name",
            "bdr_dest_multi", "rb_target_multi", "lbl_multi_target_info", "btn_pick_views",
            "bdr_mode_merge", "rb_mode_merge",
            "bdr_mode_replace", "rb_mode_replace",
            "cmb_source_view", "btn_use_active_view", "lbl_save_sel_info", "dg_save_filters",
            "btn_save_all", "btn_save_none", "btn_save_chk_sel", "btn_save_unchk_sel",
            "btn_save_up", "btn_save_down",
            "txt_save_name", "btn_save_preset",
            "lbl_status", "btn_ok", "btn_cancel", "btn_apply"
        ]:
            setattr(self, cname, self.win.FindName(cname))

        self.lb_presets.SelectionMode = SelectionMode.Single
        self.all_presets = []
        self.external_presets = []
        self.current_load_filters = []
        self.current_save_filters = []
        self.picked_target_views = []
        self.controlling_vt = None

        excluded_types = set([
            DB.ViewType.ProjectBrowser,
            DB.ViewType.SystemBrowser,
            DB.ViewType.Internal,
            DB.ViewType.DrawingSheet
        ])
        self.all_views = [
            v for v in DB.FilteredElementCollector(self.doc).OfClass(DB.View).WhereElementIsNotElementType()
            if (v.IsTemplate or v.ViewType not in excluded_types) and v.AreGraphicsOverridesAllowed()
        ]
        self.all_views.sort(key=lambda x: (not x.IsTemplate, to_text(x.ViewType), to_text(x.Name)))

        self.dt_presets = DataTable("PresetsList")
        self.dt_presets.Columns.Add("DisplayLabel", System.String)
        self.dt_presets.Columns.Add("PresetIndex", System.Int32)

        self.dt_source_views = DataTable("SourceViews")
        self.dt_source_views.Columns.Add("DisplayName", System.String)
        self.dt_source_views.Columns.Add("ViewIndex", System.Int32)

        self.dt_load_grid = create_filters_datatable()
        self.dt_save_grid = create_filters_datatable()

        self.lb_presets.ItemsSource = self.dt_presets.DefaultView
        self.cmb_source_view.ItemsSource = self.dt_source_views.DefaultView
        self.dg_load_filters.ItemsSource = self.dt_load_grid.DefaultView
        self.dg_save_filters.ItemsSource = self.dt_save_grid.DefaultView

        self.load_ms = MultiSelectGridController(self.dg_load_filters, self.dt_load_grid, self.lbl_load_sel_info)
        self.save_ms = MultiSelectGridController(self.dg_save_filters, self.dt_save_grid, self.lbl_save_sel_info)

        self._init_context_header()
        self._populate_source_views_combo()
        recent_auto = self._reload_presets_list(auto_select_recent=True)
        self._bind_events()
        self._update_destination_visuals()

        if recent_auto:
            self._set_status(u"Auto-loaded recent state (<5 min): '{}'. Ready to Paste!".format(recent_auto))
            self.main_tabs.SelectedIndex = 0
        elif not self.all_presets:
            self._set_status(u"No presets saved yet. Switched to 'Copy / Save State' tab.")
            self.main_tabs.SelectedIndex = 1
        else:
            self._set_status(u"Preset Folder: {}".format(to_text(self.export_path)))

    def show_dialog(self):
        self.win.ShowDialog()

    def _set_status(self, msg):
        self.lbl_status.Text = to_text(msg)

    def _init_context_header(self):
        av_name = to_text(self.active_view.Name) if self.active_view else u"None"
        self.lbl_doc_context.Text = u"Document: {}   |   Active View: {}".format(
            to_text(self.doc.Title), av_name
        )

        if not self.active_view or not self.active_view.AreGraphicsOverridesAllowed():
            self.rb_target_active.IsEnabled = False
            self.rb_target_multi.IsChecked = True
            self.btn_quick_copy_active.IsEnabled = False
            self.lbl_active_target_name.Text = u"Not supported"
            return

        if not self.active_view.IsTemplate:
            try:
                vt_id = self.active_view.ViewTemplateId
                if vt_id and vt_id != DB.ElementId.InvalidElementId:
                    vt = self.doc.GetElement(vt_id)
                    if vt:
                        non_ctrl = set(get_id_val(pid) for pid in vt.GetNonControlledTemplateParameterIds())
                        vg_param = get_id_val(DB.ElementId(DB.BuiltInParameter.VIS_GRAPHICS_FILTERS))
                        if vg_param not in non_ctrl:
                            self.controlling_vt = vt
                            self.chk_apply_to_vt.Content = (
                                u"Active View Filters are controlled by View Template '{}'. "
                                u"Redirect Paste/Apply directly to View Template.".format(to_text(vt.Name))
                            )
                            self.bdr_vt_warning.Visibility = Visibility.Visible
            except Exception:
                pass

    def _update_destination_visuals(self):
        """Update visual highlight cards, target badges, and Apply button label dynamically."""
        is_active_dest = bool(self.rb_target_active.IsChecked)
        sel_cnt = len(self.picked_target_views)

        # Update Active View Badge text
        if self.active_view and self.active_view.AreGraphicsOverridesAllowed():
            if self.controlling_vt is not None and bool(self.chk_apply_to_vt.IsChecked):
                t_label = u"Template: {}".format(to_text(self.controlling_vt.Name))
            else:
                t_label = to_text(self.active_view.Name)
            self.lbl_active_target_name.Text = t_label
            self.lbl_active_target_name.ToolTip = t_label

        # Highlight Card 1 vs Card 2
        if is_active_dest:
            self.bdr_dest_active.Background = BRUSH_CARD_SEL_BG
            self.bdr_dest_active.BorderBrush = BRUSH_CARD_SEL_BDR
            self.bdr_dest_active.BorderThickness = Thickness(2)

            self.bdr_dest_multi.Background = BRUSH_CARD_IDLE_BG
            self.bdr_dest_multi.BorderBrush = BRUSH_CARD_IDLE_BDR
            self.bdr_dest_multi.BorderThickness = Thickness(1)

            self.btn_pick_views.Background = BRUSH_BTN_SUBTLE_BG
            self.btn_pick_views.Foreground = BRUSH_DARK_BLUE
            self.btn_pick_views.BorderBrush = BRUSH_BTN_SUBTLE_BDR
            self.btn_pick_views.BorderThickness = Thickness(1)
            self.btn_apply.Content = u"Paste -> Active View"
        else:
            self.bdr_dest_active.Background = BRUSH_CARD_IDLE_BG
            self.bdr_dest_active.BorderBrush = BRUSH_CARD_IDLE_BDR
            self.bdr_dest_active.BorderThickness = Thickness(1)

            if sel_cnt == 0:
                self.bdr_dest_multi.Background = BRUSH_CARD_WARN_BG
                self.bdr_dest_multi.BorderBrush = BRUSH_CARD_WARN_BDR
                self.bdr_dest_multi.BorderThickness = Thickness(2)

                self.btn_pick_views.Background = BRUSH_BTN_AMBER_BG
                self.btn_pick_views.Foreground = BRUSH_WHITE
                self.btn_pick_views.BorderBrush = BRUSH_CARD_WARN_BDR
                self.btn_pick_views.BorderThickness = Thickness(1)
                self.btn_apply.Content = u"Select Views & Paste..."
            else:
                self.bdr_dest_multi.Background = BRUSH_CARD_SEL_BG
                self.bdr_dest_multi.BorderBrush = BRUSH_CARD_SEL_BDR
                self.bdr_dest_multi.BorderThickness = Thickness(2)

                self.btn_pick_views.Background = BRUSH_BTN_BLUE_BG
                self.btn_pick_views.Foreground = BRUSH_WHITE
                self.btn_pick_views.BorderBrush = BRUSH_CARD_SEL_BDR
                self.btn_pick_views.BorderThickness = Thickness(1)
                self.btn_apply.Content = u"Paste -> {} View(s)".format(sel_cnt)

        # Update Multi-Target summary text & button label
        self.btn_pick_views.Content = u"Select Views... ({})".format(sel_cnt)
        if sel_cnt == 0:
            self.lbl_multi_target_info.Text = u"Click button ->" if not is_active_dest else u"No views selected"
            self.lbl_multi_target_info.Foreground = BRUSH_AMBER_TEXT if not is_active_dest else BRUSH_FG_MUTED
            self.lbl_multi_target_info.ToolTip = None
        else:
            preview_names = u", ".join(to_text(v.Name) for v in self.picked_target_views[:3])
            if sel_cnt > 3:
                preview_names += u" (+{} more)".format(sel_cnt - 3)
            self.lbl_multi_target_info.Text = preview_names
            self.lbl_multi_target_info.Foreground = BRUSH_DARK_BLUE
            self.lbl_multi_target_info.ToolTip = u"\n".join(to_text(v.Name) for v in self.picked_target_views)

        # Highlight Mode Cards (Merge vs Replace All)
        if bool(self.rb_mode_merge.IsChecked):
            self.bdr_mode_merge.Background = BRUSH_CARD_SEL_BG
            self.bdr_mode_merge.BorderBrush = BRUSH_CARD_SEL_BDR
            self.bdr_mode_merge.BorderThickness = Thickness(1.5)

            self.bdr_mode_replace.Background = BRUSH_CARD_IDLE_BG
            self.bdr_mode_replace.BorderBrush = BRUSH_CARD_IDLE_BDR
            self.bdr_mode_replace.BorderThickness = Thickness(1)
        else:
            self.bdr_mode_merge.Background = BRUSH_CARD_IDLE_BG
            self.bdr_mode_merge.BorderBrush = BRUSH_CARD_IDLE_BDR
            self.bdr_mode_merge.BorderThickness = Thickness(1)

            self.bdr_mode_replace.Background = BRUSH_CARD_DANGER_BG
            self.bdr_mode_replace.BorderBrush = BRUSH_CARD_DANGER_BDR
            self.bdr_mode_replace.BorderThickness = Thickness(1.5)

    def _populate_source_views_combo(self):
        self.dt_source_views.Rows.Clear()
        active_combo_idx = 0
        target_view = self.controlling_vt if self.controlling_vt else self.active_view
        target_id = get_id_val(target_view.Id) if target_view else -1

        for idx, v in enumerate(self.all_views):
            row = self.dt_source_views.NewRow()
            prefix = u"[Template] " if v.IsTemplate else u"[{}] ".format(to_text(v.ViewType))
            row["DisplayName"] = prefix + to_text(v.Name)
            row["ViewIndex"] = idx
            self.dt_source_views.Rows.Add(row)
            if get_id_val(v.Id) == target_id:
                active_combo_idx = idx

        if self.dt_source_views.Rows.Count > 0:
            self.cmb_source_view.SelectedIndex = active_combo_idx
            self._load_source_view_filters(self.all_views[active_combo_idx])

    def _load_source_view_filters(self, view):
        fids = get_ordered_filters(view)
        self.current_save_filters = [
            serialize_view_filter(self.doc, view, fid, idx)
            for idx, fid in enumerate(fids)
            if self.doc.GetElement(fid)
        ]
        populate_filters_datatable(self.dt_save_grid, self.current_save_filters, resolver=None, checked_default=True)
        safe_name = u"".join(c if c.isalnum() or c in u"_-" else u"_" for c in to_text(view.Name))
        self.txt_save_name.Text = u"{}_Filters".format(safe_name)

    def _reload_presets_list(self, select_name=None, auto_select_recent=False):
        self.all_presets = list(self.external_presets)
        if os.path.isdir(self.export_path):
            for fname in sorted(os.listdir(self.export_path)):
                fn_txt = to_text(fname)
                if fn_txt.lower().endswith(u".json") and not fn_txt.startswith(u"."):
                    fpath = os.path.join(self.export_path, fn_txt)
                    try:
                        data = read_json_preset(fpath)
                        self.all_presets.append(data)
                    except Exception as ex:
                        logger.warning("Skipped preset {}: {}".format(fn_txt, ex))

        recent_hit_name = None
        if auto_select_recent and self.all_presets:
            latest_p = max(self.all_presets, key=lambda item: item.get("_mtime", 0.0))
            if (time.time() - latest_p.get("_mtime", 0.0)) <= RECENT_THRESHOLD_SEC:
                recent_hit_name = to_text(latest_p.get("preset_name"))
                select_name = recent_hit_name

        self._filter_presets_listbox(select_name)
        return recent_hit_name

    def _filter_presets_listbox(self, select_name=None):
        self.dt_presets.Rows.Clear()
        q = to_text(self.txt_preset_search.Text).strip().lower()
        sel_row_idx = 0
        now_ts = time.time()

        for idx, p in enumerate(self.all_presets):
            pname = to_text(p.get("preset_name", "Unnamed"))
            if q and q not in pname.lower():
                continue
            row = self.dt_presets.NewRow()
            is_recent = (now_ts - p.get("_mtime", 0.0)) <= RECENT_THRESHOLD_SEC
            badge = u" [Recent]" if is_recent else u""
            row["DisplayLabel"] = u"{} ({}){}".format(pname, len(p.get("filters", [])), badge)
            row["PresetIndex"] = idx
            self.dt_presets.Rows.Add(row)
            if select_name and pname == to_text(select_name):
                sel_row_idx = self.dt_presets.Rows.Count - 1

        if self.dt_presets.Rows.Count > 0:
            self.lb_presets.SelectedIndex = sel_row_idx
            self._load_selected_preset()
        else:
            self.current_load_filters = []
            self.dt_load_grid.Rows.Clear()
            self.lbl_preset_meta.Text = u"No presets found. Use '2. Copy / Save State' tab to create one."

    def _load_selected_preset(self):
        sel = self.lb_presets.SelectedItem
        if sel is None:
            return
        p = self.all_presets[int(sel["PresetIndex"])]
        self.current_load_filters = copy.deepcopy(p.get("filters", []))
        populate_filters_datatable(self.dt_load_grid, self.current_load_filters, resolver=self.resolver, checked_default=True)
        ver = to_text(p.get("schema_version", "1.0"))
        self.lbl_preset_meta.Text = u"Source: {} | View: {} | Schema: v{} | Saved: {}".format(
            to_text(p.get("source_document", "-")),
            to_text(p.get("source_view_name", "-")),
            ver,
            to_text(p.get("created_at", "-"))
        )

    def _sync_grid_state(self, dt, entries):
        for row in dt.Rows:
            idx = int(row["RawIndex"])
            if 0 <= idx < len(entries):
                entries[idx]["_ui_checked"] = bool(row["IsChecked"])
                entries[idx]["is_enabled"] = bool(row["IsEnabled"])
                entries[idx]["is_visible"] = bool(row["IsVisible"])
                entries[idx].setdefault("overrides", {})["halftone"] = bool(row["IsHalftone"])

    def _move_selected_rows(self, dg, dt, entries, ms_ctrl, delta):
        sel_indices = ms_ctrl.get_selected_raw_indices()
        if not sel_indices:
            return
        self._sync_grid_state(dt, entries)

        if delta < 0:
            if sel_indices[0] == 0:
                return
            new_sel = []
            for idx in sel_indices:
                entries[idx - 1], entries[idx] = entries[idx], entries[idx - 1]
                new_sel.append(idx - 1)
        else:
            if sel_indices[-1] >= len(entries) - 1:
                return
            new_sel = []
            for idx in reversed(sel_indices):
                entries[idx + 1], entries[idx] = entries[idx], entries[idx + 1]
                new_sel.append(idx + 1)
            new_sel.reverse()

        res = self.resolver if dg == self.dg_load_filters else None
        populate_filters_datatable(dt, entries, resolver=res, checked_default=True)
        dg.SelectedItems.Clear()
        for nidx in new_sel:
            if 0 <= nidx < dg.Items.Count:
                dg.SelectedItems.Add(dg.Items[nidx])

    def _bind_events(self):
        self.btn_quick_copy_active.Click += self._on_quick_copy_active
        self.btn_open_folder.Click += self._on_open_folder
        self.btn_change_folder.Click += self._on_change_folder

        self.btn_browse_json.Click += self._on_browse_json
        self.txt_preset_search.TextChanged += lambda s, a: self._filter_presets_listbox()
        self.lb_presets.SelectionChanged += lambda s, a: self._load_selected_preset()
        self.btn_refresh_presets.Click += lambda s, a: self._refresh_all()
        self.btn_report_preset.Click += self._on_report_preset
        self.btn_delete_preset.Click += self._on_delete_preset
        self.btn_import_rvt.Click += self._on_import_from_rvt

        self.btn_load_all.Click += lambda s, a: self._set_all_rows(self.dt_load_grid, True)
        self.btn_load_none.Click += lambda s, a: self._set_all_rows(self.dt_load_grid, False)
        self.btn_load_chk_sel.Click += lambda s, a: self.load_ms.set_selected_checked(True)
        self.btn_load_unchk_sel.Click += lambda s, a: self.load_ms.set_selected_checked(False)
        self.btn_load_up.Click += lambda s, a: self._move_selected_rows(
            self.dg_load_filters, self.dt_load_grid, self.current_load_filters, self.load_ms, -1
        )
        self.btn_load_down.Click += lambda s, a: self._move_selected_rows(
            self.dg_load_filters, self.dt_load_grid, self.current_load_filters, self.load_ms, 1
        )
        self.btn_save_checked_new.Click += self._on_save_checked_load_as_new

        # Interactive Destination & Mode Card Clicks + Radio Events
        self.chk_apply_to_vt.Checked += lambda s, a: self._update_destination_visuals()
        self.chk_apply_to_vt.Unchecked += lambda s, a: self._update_destination_visuals()
        self.rb_target_active.Checked += lambda s, a: self._update_destination_visuals()
        self.rb_target_multi.Checked += lambda s, a: self._update_destination_visuals()
        self.rb_mode_merge.Checked += lambda s, a: self._update_destination_visuals()
        self.rb_mode_replace.Checked += lambda s, a: self._update_destination_visuals()

        self.bdr_dest_active.MouseLeftButtonDown += self._on_card_active_click
        self.bdr_dest_multi.MouseLeftButtonDown += self._on_card_multi_click
        self.bdr_mode_merge.MouseLeftButtonDown += self._on_card_merge_click
        self.bdr_mode_replace.MouseLeftButtonDown += self._on_card_replace_click
        self.btn_pick_views.Click += self._on_pick_views

        self.cmb_source_view.SelectionChanged += self._on_source_view_changed
        self.btn_use_active_view.Click += self._on_use_active_view
        self.btn_save_all.Click += lambda s, a: self._set_all_rows(self.dt_save_grid, True)
        self.btn_save_none.Click += lambda s, a: self._set_all_rows(self.dt_save_grid, False)
        self.btn_save_chk_sel.Click += lambda s, a: self.save_ms.set_selected_checked(True)
        self.btn_save_unchk_sel.Click += lambda s, a: self.save_ms.set_selected_checked(False)
        self.btn_save_up.Click += lambda s, a: self._move_selected_rows(
            self.dg_save_filters, self.dt_save_grid, self.current_save_filters, self.save_ms, -1
        )
        self.btn_save_down.Click += lambda s, a: self._move_selected_rows(
            self.dg_save_filters, self.dt_save_grid, self.current_save_filters, self.save_ms, 1
        )
        self.btn_save_preset.Click += self._on_save_preset

        self.btn_apply.Click += self._on_apply
        self.btn_ok.Click += self._on_ok
        self.btn_cancel.Click += lambda s, a: self.win.Close()

    def _on_card_active_click(self, sender, args):
        if self.rb_target_active.IsEnabled:
            self.rb_target_active.IsChecked = True

    def _on_card_multi_click(self, sender, args):
        self.rb_target_multi.IsChecked = True

    def _on_card_merge_click(self, sender, args):
        self.rb_mode_merge.IsChecked = True

    def _on_card_replace_click(self, sender, args):
        self.rb_mode_replace.IsChecked = True

    def _set_all_rows(self, dt, state):
        for r in dt.Rows:
            r["IsChecked"] = bool(state)

    def _refresh_all(self):
        self.resolver = DocumentResourceResolver(self.doc)
        self._reload_presets_list()
        self._set_status(u"Refreshed presets and model filter cache.")

    def _on_browse_json(self, sender, args):
        picked_file = forms.pick_file(file_ext="json", init_dir=self.export_path)
        if not picked_file:
            return
        try:
            data = read_json_preset(to_text(picked_file))
            pname = to_text(data.get("preset_name", "External_Preset"))
            self.external_presets = [ep for ep in self.external_presets if ep.get("_file_path") != data.get("_file_path")]
            self.external_presets.append(data)
            self._reload_presets_list(select_name=pname)
            self._set_status(u"Loaded external preset: {}".format(picked_file))
        except Exception as ex:
            show_alert("Load JSON Error", u"Failed to read JSON file:\n{}".format(ex))

    def _on_quick_copy_active(self, sender, args):
        src_v = self.controlling_vt if self.controlling_vt else self.active_view
        if not src_v:
            show_alert("Quick Copy", "No valid Active View found.")
            return
        fids = get_ordered_filters(src_v)
        if not fids:
            show_alert("Quick Copy", u"No View Filters found in '{}'.".format(to_text(src_v.Name)))
            return
        chosen = [
            serialize_view_filter(self.doc, src_v, fid, idx)
            for idx, fid in enumerate(fids)
            if self.doc.GetElement(fid)
        ]
        fpath = get_preset_file_path(self.export_path, QUICK_CLIPBOARD_NAME)
        payload = self._build_preset_payload(QUICK_CLIPBOARD_NAME, src_v, chosen)
        try:
            write_json_atomic(fpath, payload)
            self._reload_presets_list(select_name=QUICK_CLIPBOARD_NAME)
            self.main_tabs.SelectedIndex = 0
            self._set_status(
                u"Quick-Copied {} filter(s) from '{}' to Clipboard! Ready to Paste.".format(
                    len(chosen), to_text(src_v.Name)
                )
            )
        except Exception as ex:
            show_alert("Quick Copy Error", to_text(ex))

    def _on_open_folder(self, sender, args):
        if os.path.isdir(self.export_path):
            subprocess.Popen(["explorer", self.export_path])

    def _on_change_folder(self, sender, args):
        picked = forms.pick_folder(title="Select Writable Folder for Filter Presets")
        if picked and _is_writable_preset_folder(picked):
            self.export_path = os.path.abspath(os.path.normpath(to_text(picked)))
            _save_export_path(self.export_path)
            self._reload_presets_list()
            self._set_status(u"Updated folder: {}".format(self.export_path))

    def _on_source_view_changed(self, sender, args):
        sel = self.cmb_source_view.SelectedItem
        if sel is not None:
            self._load_source_view_filters(self.all_views[int(sel["ViewIndex"])])

    def _on_use_active_view(self, sender, args):
        target = self.controlling_vt if self.controlling_vt else self.active_view
        if not target:
            return
        tid = get_id_val(target.Id)
        for i, row in enumerate(self.dt_source_views.Rows):
            if get_id_val(self.all_views[int(row["ViewIndex"])].Id) == tid:
                self.cmb_source_view.SelectedIndex = i
                break

    def _on_pick_views(self, sender, args):
        self.rb_target_multi.IsChecked = True
        pre_ids = [get_id_val(v.Id) for v in self.picked_target_views]
        dlg = RevitViewPickerDialog(self.win, self.all_views, pre_ids)
        res = dlg.show_dialog()
        if res is not None:
            self.picked_target_views = res
        self._update_destination_visuals()

    def _on_delete_preset(self, sender, args):
        sel = self.lb_presets.SelectedItem
        if sel is None:
            return
        p = self.all_presets[int(sel["PresetIndex"])]
        pname = to_text(p.get("preset_name", "Preset"))
        if ask_yes_no("Confirm Delete", u"Delete preset '{}'?".format(pname)):
            try:
                if os.path.exists(p["_file_path"]):
                    os.remove(p["_file_path"])
                self.external_presets = [ep for ep in self.external_presets if ep.get("_file_path") != p.get("_file_path")]
                self._reload_presets_list()
                self._set_status(u"Deleted preset '{}'.".format(pname))
            except Exception as ex:
                show_alert("Delete Error", u"Could not delete file:\n{}".format(ex))

    def _on_report_preset(self, sender, args):
        sel = self.lb_presets.SelectedItem
        if sel is None:
            return
        p = self.all_presets[int(sel["PresetIndex"])]
        output.print_md(u"## Preset Summary: `{}`".format(to_text(p.get("preset_name"))))
        rows = []
        for idx, f in enumerate(p.get("filters", []), 1):
            ovr = f.get("overrides", {})
            rows.append([
                idx, to_text(f.get("name")), str(f.get("is_enabled", True)), str(f.get("is_visible", True)),
                ovr.get("transparency", 0), str(ovr.get("halftone", False)),
                str(ovr.get("proj_line_color") or "-"), str(ovr.get("surf_fg_pattern_color") or "-"),
                str(ovr.get("cut_fg_pattern_color") or "-")
            ])
        output.print_table(
            table_data=rows,
            columns=["#", "Filter", "Enabled", "Visible", "Trans%", "Halftone", "Proj RGB", "Surf FG", "Cut FG"]
        )
        self._set_status(u"Printed report to pyRevit Output.")

    def _on_import_from_rvt(self, sender, args):
        if not self.current_load_filters:
            show_alert("Import .RVT", "Select a preset first.")
            return
        self._sync_grid_state(self.dt_load_grid, self.current_load_filters)
        missing = [
            f for f in self.current_load_filters
            if f.get("_ui_checked", True) and f.get("name") not in self.resolver.filters_by_name
        ]
        if not missing:
            show_alert("Import .RVT", "All checked filters already exist in the current model!")
            return

        rvt_path = forms.pick_file(file_ext="rvt", title="Select Source Revit Project (.rvt) Containing Filters")
        if not rvt_path:
            return

        src_doc = None
        pulled = 0
        try:
            mp = DB.ModelPathUtils.ConvertUserVisiblePathToModelPath(to_text(rvt_path))
            open_opts = DB.OpenOptions()
            open_opts.DetachFromCentralOption = DB.DetachFromCentralOption.DetachAndPreserveWorksets
            src_doc = HOST_APP.app.OpenDocumentFile(mp, open_opts)

            with revit.Transaction("Import Missing Filters from RVT"):
                for f_entry in missing:
                    sf = self.resolver.find_source_filter_in_doc(src_doc, f_entry)
                    if sf:
                        ids = List[DB.ElementId]()
                        ids.Add(sf.Id)
                        copied = DB.ElementTransformUtils.CopyElements(
                            src_doc, ids, self.doc, DB.Transform.Identity, DB.CopyPasteOptions()
                        )
                        if copied and copied.Count > 0:
                            pulled += 1
                            if isinstance(sf, DB.ParameterFilterElement):
                                f_entry["category_ids"] = [get_id_val(cid) for cid in sf.GetCategories()]
                                f_entry["rule_tree"] = serialize_element_filter_tree(src_doc, sf.GetElementFilter())
        except Exception as ex:
            show_alert("Import .RVT Error", u"Could not pull filters from RVT:\n{}".format(ex))
        finally:
            if src_doc is not None:
                try:
                    src_doc.Close(False)
                except Exception:
                    pass

        self.resolver = DocumentResourceResolver(self.doc)
        populate_filters_datatable(self.dt_load_grid, self.current_load_filters, resolver=self.resolver, checked_default=True)

        sel = self.lb_presets.SelectedItem
        if pulled > 0 and sel is not None:
            p = self.all_presets[int(sel["PresetIndex"])]
            if p.get("_file_path") and os.path.exists(p["_file_path"]):
                try:
                    clean_list = []
                    for item in self.current_load_filters:
                        c = dict(item)
                        c.pop("_ui_checked", None)
                        clean_list.append(c)
                    p["schema_version"] = SCHEMA_VERSION
                    p["filters"] = clean_list
                    save_copy = dict(p)
                    save_copy.pop("_file_path", None)
                    save_copy.pop("_mtime", None)
                    write_json_atomic(p["_file_path"], save_copy)
                except Exception:
                    pass

        self._set_status(u"Imported {} filter(s) from '{}' and upgraded preset to v3.0.".format(pulled, os.path.basename(rvt_path)))

    def _build_preset_payload(self, pname, src_view, filters_list):
        return {
            "schema_version": SCHEMA_VERSION,
            "preset_name": to_text(pname),
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "created_by": to_text(self.doc.Application.Username),
            "revit_version": to_text(self.doc.Application.VersionNumber),
            "source_document": to_text(self.doc.Title),
            "source_document_path": get_document_path(self.doc),
            "source_view_name": to_text(src_view.Name) if src_view else "-",
            "source_is_template": bool(src_view.IsTemplate) if src_view else False,
            "filters": filters_list
        }

    def _on_save_checked_load_as_new(self, sender, args):
        if not self.current_load_filters:
            return
        self._sync_grid_state(self.dt_load_grid, self.current_load_filters)
        chosen = []
        for f in self.current_load_filters:
            if f.get("_ui_checked", True):
                cf = dict(f)
                cf.pop("_ui_checked", None)
                cf["order_index"] = len(chosen)
                chosen.append(cf)
        if not chosen:
            show_alert("Save Checked As New", "Please check at least one filter.")
            return
        new_name = forms.ask_for_string(
            default="Selected_Filters_Preset",
            prompt="Enter new preset name for {} checked filter(s):".format(len(chosen)),
            title="Save Checked Filters As New Preset"
        )
        if not new_name:
            return
        fpath = get_preset_file_path(self.export_path, new_name)
        if not fpath:
            show_alert("Invalid Name", "Avoid special characters: \\ / : * ? \" < > |")
            return
        if os.path.exists(fpath) and not ask_yes_no("Overwrite", u"Overwrite '{}'?".format(os.path.basename(fpath))):
            return
        pname = to_text(os.path.splitext(os.path.basename(fpath))[0])
        payload = self._build_preset_payload(pname, self.active_view, chosen)
        write_json_atomic(fpath, payload)
        self._reload_presets_list(select_name=pname)
        self._set_status(u"Saved {} checked filter(s) as '{}.json'.".format(len(chosen), pname))

    def _on_save_preset(self, sender, args):
        self._sync_grid_state(self.dt_save_grid, self.current_save_filters)
        chosen = []
        for f in self.current_save_filters:
            if f.get("_ui_checked", True):
                clean_f = dict(f)
                clean_f.pop("_ui_checked", None)
                clean_f["order_index"] = len(chosen)
                chosen.append(clean_f)

        if not chosen:
            show_alert("Copy / Save Preset", "Please check at least one filter to save.")
            return

        fpath = get_preset_file_path(self.export_path, self.txt_save_name.Text)
        if not fpath:
            show_alert("Invalid Name", "Avoid special characters: \\ / : * ? \" < > |")
            return

        if os.path.exists(fpath):
            if not ask_yes_no("Confirm Overwrite", u"Overwrite existing preset '{}'?".format(os.path.basename(fpath))):
                return

        sel_src = self.cmb_source_view.SelectedItem
        src_view = self.all_views[int(sel_src["ViewIndex"])] if sel_src is not None else self.active_view
        pname = to_text(os.path.splitext(os.path.basename(fpath))[0])
        payload = self._build_preset_payload(pname, src_view, chosen)
        try:
            write_json_atomic(fpath, payload)
            self._reload_presets_list(select_name=pname)
            self.main_tabs.SelectedIndex = 0
            self._set_status(u"Saved {} filter(s) with rules to '{}.json'.".format(len(chosen), pname))
        except Exception as ex:
            show_alert("Save Error", u"Failed to save preset:\n{}".format(ex))

    def _execute_paste(self):
        if not self.current_load_filters:
            show_alert("Paste Preset", "No preset filters loaded to paste.")
            return False

        self._sync_grid_state(self.dt_load_grid, self.current_load_filters)
        chosen = [f for f in self.current_load_filters if f.get("_ui_checked", True)]
        if not chosen:
            show_alert("Paste Preset", "Please check at least one filter in the 'Use' column.")
            return False

        if bool(self.rb_target_active.IsChecked):
            if self.controlling_vt is not None:
                if bool(self.chk_apply_to_vt.IsChecked):
                    targets = [self.controlling_vt]
                else:
                    show_alert("View Template Locked", "Enable redirect banner or pick target views.")
                    return False
            else:
                targets = [self.active_view]
        else:
            if not self.picked_target_views:
                self._on_pick_views(None, None)
            if not self.picked_target_views:
                return False
            targets = self.picked_target_views

        replace_all = bool(self.rb_mode_replace.IsChecked)
        self.resolver = DocumentResourceResolver(self.doc)

        applied_cnt = 0
        pulled_cnt = 0
        pull_errors = []

        tg = DB.TransactionGroup(self.doc, "Filter Transfer Paste")
        tg.Start()
        try:
            resolved_items = []
            with revit.Transaction("Resolve & Auto-Pull Missing Filters"):
                for f_entry in chosen:
                    f_elem, res_note = self.resolver.resolve_or_create_filter(f_entry)
                    if f_elem is None:
                        pull_errors.append(u"{}: {}".format(to_text(f_entry.get("name")), res_note))
                        continue
                    if res_note != u"Existing":
                        pulled_cnt += 1
                    ogs = build_override_graphic_settings(f_entry.get("overrides", {}), self.resolver)
                    resolved_items.append((f_entry, f_elem, ogs))

            chosen_names_set = set(to_text(item[0].get("name")) for item in resolved_items)

            for t_view in targets:
                with revit.Transaction(u"Paste Filters to {}".format(to_text(t_view.Name))):
                    for efid in list(t_view.GetFilters()):
                        ef_elem = self.doc.GetElement(efid)
                        if replace_all or (ef_elem and to_text(ef_elem.Name) in chosen_names_set):
                            try:
                                t_view.RemoveFilter(efid)
                            except Exception:
                                pass

                    existing_ids = set(get_id_val(fid) for fid in t_view.GetFilters())
                    for f_entry, f_elem, ogs in resolved_items:
                        try:
                            fid_int = get_id_val(f_elem.Id)
                            if fid_int not in existing_ids:
                                t_view.AddFilter(f_elem.Id)
                                existing_ids.add(fid_int)

                            t_view.SetFilterVisibility(f_elem.Id, bool(f_entry.get("is_visible", True)))
                            if hasattr(t_view, "SetIsFilterEnabled"):
                                t_view.SetIsFilterEnabled(f_elem.Id, bool(f_entry.get("is_enabled", True)))
                            t_view.SetFilterOverrides(f_elem.Id, ogs)
                            applied_cnt += 1
                        except Exception as vex:
                            pull_errors.append(u"{} ({}): {}".format(to_text(f_entry.get("name")), to_text(t_view.Name), vex))

            tg.Assimilate()
        except Exception as ex:
            if tg.GetStatus() == DB.TransactionStatus.Started:
                tg.RollBack()
            show_alert("Paste Error", u"Transaction failed:\n{}".format(ex))
            return False

        try:
            self.uidoc.RefreshActiveView()
        except Exception:
            pass

        self.resolver = DocumentResourceResolver(self.doc)
        populate_filters_datatable(self.dt_load_grid, self.current_load_filters, resolver=self.resolver, checked_default=True)
        self._on_source_view_changed(None, None)

        msg = u"Pasted {} filter override(s) across {} view(s).".format(applied_cnt, len(targets))
        if pulled_cnt > 0:
            msg += u" (Auto-pulled/created {} new filter(s))".format(pulled_cnt)
        self._set_status(msg)

        if pull_errors:
            show_alert(
                "Cross-Project Filter Paste Notice",
                u"Some filters could not be pasted:\n\n{}\n\n"
                u"Tip: Keep the source .RVT open in Revit, or click 'Import Missing Filters from .RVT File...'."
                .format(u"\n".join(pull_errors[:12]))
            )
        return len(pull_errors) == 0 or applied_cnt > 0

    def _on_apply(self, sender, args):
        self.main_tabs.SelectedIndex = 0
        self._execute_paste()

    def _on_ok(self, sender, args):
        if self.main_tabs.SelectedIndex == 0 and self.current_load_filters:
            if self._execute_paste():
                self.win.Close()
        elif self.main_tabs.SelectedIndex == 1:
            self._on_save_preset(sender, args)
        else:
            self.win.Close()


# ------------------------------------------------------------------------------
# DIRECT EXECUTION ENTRY POINT
# ------------------------------------------------------------------------------
def run_unified_filter_manager():
    try:
        if not revit.doc:
            show_alert("Filter Transfer", "No active Revit document found.")
            return

        is_shift = bool(getattr(EXEC_PARAMS, "config_mode", False)) or bool(globals().get("__shiftclick__", False))
        if is_shift:
            picked = forms.pick_folder(title="Select Preset Folder (Shift+Click Config)")
            if picked and _is_writable_preset_folder(picked):
                norm = os.path.abspath(os.path.normpath(to_text(picked)))
                _save_export_path(norm)
                forms.toast("Preset folder updated:\n{}".format(norm), title="Folder Updated")
            elif picked:
                show_alert("Filter Transfer", "The selected folder is not writable.")
            return

        export_path = get_export_path(prompt_if_missing=True)
        if not export_path:
            return

        dialog = UnifiedFilterPresetWindow(revit.doc, revit.uidoc, export_path)
        dialog.show_dialog()
    except Exception:
        show_alert("Filter Transfer - Script Error", traceback.format_exc())


run_unified_filter_manager()