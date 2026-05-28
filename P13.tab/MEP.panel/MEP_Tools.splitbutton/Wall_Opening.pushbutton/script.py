# -*- coding: utf-8 -*-
"""
Advanced Wall Opening Automation (P13)
Automates and synchronizes custom Wall Opening families at geometric intersections
between MEP elements (pipes, ducts, cable trays, conduits, fittings, accessories, equipment) and walls.
Supports host and linked models, non-orthogonal projections, mapping tables,
and Category Grouping sequence numbering.

Target environment: Revit 2026 API, .NET 8 framework.
All UI forms, logs, and script messages are in English.
"""

import math
import os
import json
import clr
from System import Guid, String
clr.AddReference('System')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
import Autodesk.Revit.DB as DB
import Autodesk.Revit.UI as UI
from Autodesk.Revit.DB.ExtensibleStorage import Schema, SchemaBuilder, Entity, AccessLevel
from pyrevit import revit, forms, script
from System.Windows.Forms import (
    BorderStyle, Button, CheckBox, ComboBox, ComboBoxStyle, DialogResult, FlatStyle,
    Form, FormStartPosition, Label, MessageBox, Panel, TextBox
)
from System.Drawing import Color, Font, FontStyle, Point, Size

# --- Revit Document Handles ---
doc = revit.doc
uidoc = revit.uidoc

# --- Configuration & Logging ---
logger = script.get_logger()
output = script.get_output()

# All tracked MEP categories
MEP_CATEGORIES = [
    DB.BuiltInCategory.OST_PipeCurves,
    DB.BuiltInCategory.OST_DuctCurves,
    DB.BuiltInCategory.OST_CableTray,
    DB.BuiltInCategory.OST_Conduit,
    DB.BuiltInCategory.OST_PipeFitting,
    DB.BuiltInCategory.OST_PipeAccessory,
    DB.BuiltInCategory.OST_DuctFitting,
    DB.BuiltInCategory.OST_DuctAccessory,
    DB.BuiltInCategory.OST_MechanicalEquipment
]
WALL_CATEGORIES = [DB.BuiltInCategory.OST_Walls]

# Parameters used to expose opening tracking to schedules when the family supports it.
# Comments and Mark are read only as legacy fallbacks because they are also used for numbering.
LINK_PARAM_NAMES = ["MEP_Link_ID"]
LEGACY_LINK_PARAM_NAMES = ["MEP_Link_ID", "Comments", "Mark"]

# Extensible Storage keeps Graitec-style synchronization stable without consuming taggable parameters.
TRACKING_SCHEMA_GUID = Guid("b7f7f1e0-1f4c-4ad3-b38e-5589f74d4101")
TRACKING_SCHEMA_NAME = "P13WallOpeningTracking"
TRACKING_FIELD_MEP_UID = "MepUniqueId"
TRACKING_FIELD_WALL_UID = "WallUniqueId"
TRACKING_FIELD_WALL_DOC = "WallDocumentTitle"

# Global fallback parameter names
PARAM_WIDTHS = ["Width", "Opening_Width", "Opening Width", "Cut_Width"]
PARAM_HEIGHTS = ["Height", "Opening_Height", "Opening Height", "Cut_Height"]
PARAM_DIAMETERS = ["Diameter", "Opening_Diameter", "Opening Diameter", "Cut_Diameter"]
PARAM_DEPTHS = ["Thickness", "Opening_Thickness", "Opening Depth", "Wall_Thickness"]
PARAM_SYSTEMS = ["MEP_System"]
PARAM_SIZES = ["MEP_Size"]
PARAM_ELEVATIONS = ["MEP_Elevation"]

# --- Helper Functions ---

def to_feet(mm_value):
    """Convert millimeters to Revit internal units (feet)."""
    return DB.UnitUtils.ConvertToInternalUnits(float(mm_value), DB.UnitTypeId.Millimeters)

def to_mm(feet_value):
    """Convert Revit internal units (feet) to millimeters."""
    return DB.UnitUtils.ConvertFromInternalUnits(float(feet_value), DB.UnitTypeId.Millimeters)

def get_closest_level(doc, z_elevation):
    """Find the Level in the host document closest to the given Z elevation."""
    levels = DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements()
    if not levels:
        return None
    sorted_levels = sorted(levels, key=lambda lvl: abs(lvl.Elevation - z_elevation))
    return sorted_levels[0]

def get_parameter_by_bips(elem, bip_names):
    """Retrieve parameter from element using a list of BuiltInParameter names as strings, safely avoiding AttributeErrors."""
    for name in bip_names:
        try:
            bip = getattr(DB.BuiltInParameter, name)
            p = elem.get_Parameter(bip)
            if p:
                return p
        except AttributeError:
            pass
    return None

def get_mep_dimensions(elem):
    """
    Extract geometric dimensions of an MEP element.
    Returns dict: {'shape': 'ROUND'|'RECT', 'width': w, 'height': h, 'diameter': d}
    All returned values are in Revit internal units (feet).
    """
    shape = 'ROUND'
    width = 0.0
    height = 0.0
    diameter = 0.0

    # Check standard parameters safely
    p_dia = get_parameter_by_bips(elem, [
        "RBS_PIPE_DIAMETER_PARAM",
        "RBS_CURVE_DIAMETER_PARAM",
        "RBS_CONDUIT_DIAMETER_PARAM",
        "RBS_CONDUIT_OUTSIDE_DIAMETER_PARAM"
    ])

    p_width = get_parameter_by_bips(elem, [
        "RBS_CURVE_WIDTH_PARAM",
        "RBS_CABLETRAY_WIDTH_PARAM"
    ])

    p_height = get_parameter_by_bips(elem, [
        "RBS_CURVE_HEIGHT_PARAM",
        "RBS_CABLETRAY_HEIGHT_PARAM"
    ])

    if p_width and p_height:
        shape = 'RECT'
        width = p_width.AsDouble()
        height = p_height.AsDouble()
    elif p_dia:
        shape = 'ROUND'
        diameter = p_dia.AsDouble()
    else:
        # Fallback: inspect connectors
        try:
            conn_manager = elem.ConnectorManager
            if conn_manager:
                for conn in conn_manager.Connectors:
                    if conn.Shape == DB.ConnectorProfileType.Round:
                        shape = 'ROUND'
                        diameter = conn.Radius * 2.0
                        break
                    elif conn.Shape == DB.ConnectorProfileType.Rectangular:
                        shape = 'RECT'
                        width = conn.Width
                        height = conn.Height
                        break
        except:
            pass

    # Fallback to direct attribute lookup if possible
    if shape == 'ROUND' and diameter == 0.0:
        if hasattr(elem, 'Diameter'):
            diameter = elem.Diameter
        elif hasattr(elem, 'Width'):
            shape = 'RECT'
            width = elem.Width
            height = elem.Height

    return {'shape': shape, 'width': width, 'height': height, 'diameter': diameter}

def get_transformed_curve(elem, transform=None):
    """Retrieve the location curve of the MEP element, transformed if in a link."""
    loc = elem.Location
    if isinstance(loc, DB.LocationCurve):
        curve = loc.Curve
        if transform:
            return curve.CreateTransformed(transform)
        return curve
    return None

def get_element_solids(elem, transform=None):
    """Extract and merge all valid geometry solids of any element, transformed if in a link."""
    solids = []
    options = DB.Options()
    options.DetailLevel = DB.ViewDetailLevel.Fine
    geom = elem.get_Geometry(options)
    if geom is None:
        return solids

    for obj in geom:
        if isinstance(obj, DB.Solid) and obj.Volume > 0.0:
            if transform:
                solids.append(DB.SolidUtils.CreateTransformed(obj, transform))
            else:
                solids.append(obj)
        elif isinstance(obj, DB.GeometryInstance):
            inst_geom = obj.GetInstanceGeometry()
            for sub_obj in inst_geom:
                if isinstance(sub_obj, DB.Solid) and sub_obj.Volume > 0.0:
                    if transform:
                        solids.append(DB.SolidUtils.CreateTransformed(sub_obj, transform))
                    else:
                        solids.append(sub_obj)
    return solids

def get_wall_solids(wall, transform=None):
    """Extract solids from a wall, applying transform if in a link."""
    return get_element_solids(wall, transform)

def get_wall_direction(wall, transform=None):
    """Get the wall centerline direction vector, transformed if in a link."""
    loc = wall.Location
    direction = DB.XYZ.BasisX
    if isinstance(loc, DB.LocationCurve):
        curve = loc.Curve
        direction = curve.ComputeDerivatives(0.5, True).BasisX.Normalize()

    if transform:
        return transform.OfVector(direction).Normalize()
    return direction

def calculate_projection_size(mep_dim, mep_dir, wall_dir, offset_ft):
    """
    Calculate the required opening width and height on the wall plane
    for sloped/skewed MEP element runs using vector math.
    """
    # Wall normal (horizontal plane)
    N_wall = DB.XYZ(wall_dir.Y, -wall_dir.X, 0.0).Normalize()

    # Check if MEP curve is parallel to the wall
    dot_product = abs(mep_dir.DotProduct(N_wall))
    if dot_product < 0.05:  # ~87 degrees to 90 degrees (parallel)
        return None

    # Local coordinate system axes of the MEP cross-section
    if abs(mep_dir.Z) > 0.999:  # Vertical MEP element
        U_mep = DB.XYZ.BasisX
        W_mep = DB.XYZ.BasisY
    else:  # Horizontal or sloped MEP element
        U_mep = DB.XYZ.BasisZ.CrossProduct(mep_dir).Normalize()
        W_mep = mep_dir.CrossProduct(U_mep).Normalize()

    # 1. Gather perimeter coordinates relative to element centerline
    perimeter_pts = []
    if mep_dim['shape'] == 'ROUND':
        R = mep_dim['diameter'] / 2.0
        for i in range(12):  # 12 samples around circle
            theta = i * 2.0 * math.pi / 12.0
            pt = U_mep * R * math.cos(theta) + W_mep * R * math.sin(theta)
            perimeter_pts.append(pt)
    else:
        w2 = mep_dim['width'] / 2.0
        h2 = mep_dim['height'] / 2.0
        perimeter_pts = [
            U_mep * w2 + W_mep * h2,
            U_mep * w2 - W_mep * h2,
            -U_mep * w2 + W_mep * h2,
            -U_mep * w2 - W_mep * h2
        ]

    # 2. Project points onto wall plane along the MEP direction
    proj_pts = []
    for P in perimeter_pts:
        t = P.DotProduct(N_wall) / mep_dir.DotProduct(N_wall)
        proj_pts.append(P - mep_dir * t)

    # 3. Project wall-plane points onto wall coordinate axes (horizontal wall-line and vertical Z)
    x_coords = [P.DotProduct(wall_dir) for P in proj_pts]
    y_coords = [P.DotProduct(DB.XYZ.BasisZ) for P in proj_pts]

    # Calculate bounding envelope sizes and add clearances
    opening_width = (max(x_coords) - min(x_coords)) + 2.0 * offset_ft
    opening_height = (max(y_coords) - min(y_coords)) + 2.0 * offset_ft

    return opening_width, opening_height

def find_and_set_parameter(elem, possible_names, value):
    """
    Search for a parameter by name from a list of possible names.
    Sets the value if found and writable.
    Returns True if successfully written, False otherwise.
    """
    for name in possible_names:
        p = elem.LookupParameter(name)
        if p and not p.IsReadOnly:
            try:
                if p.StorageType == DB.StorageType.Double:
                    p.Set(float(value))
                elif p.StorageType == DB.StorageType.Integer:
                    p.Set(int(value))
                elif p.StorageType == DB.StorageType.String:
                    p.Set(str(value))
                return True
            except:
                pass
    return False

def is_probable_revit_unique_id(value):
    """Return True when a string looks like a Revit UniqueId, not a Mark or sequence number."""
    if not value:
        return False
    value = str(value).strip()
    return len(value) > 20 and "-" in value

def get_tracking_schema(create_if_missing=False):
    """Get or create the Extensible Storage schema used for opening synchronization."""
    schema = Schema.Lookup(TRACKING_SCHEMA_GUID)
    if schema or not create_if_missing:
        return schema

    builder = SchemaBuilder(TRACKING_SCHEMA_GUID)
    builder.SetSchemaName(TRACKING_SCHEMA_NAME)
    builder.SetVendorId("P013")
    builder.SetReadAccessLevel(AccessLevel.Public)
    builder.SetWriteAccessLevel(AccessLevel.Public)
    builder.AddSimpleField(TRACKING_FIELD_MEP_UID, String)
    builder.AddSimpleField(TRACKING_FIELD_WALL_UID, String)
    builder.AddSimpleField(TRACKING_FIELD_WALL_DOC, String)
    return builder.Finish()

def get_entity_string(entity, schema, field_name):
    """Read a string field from Extensible Storage with IronPython generic fallback."""
    if not entity or not entity.IsValid():
        return None
    field = schema.GetField(field_name)
    if not field:
        return None
    try:
        return entity.Get[String](field)
    except:
        try:
            return entity.Get[String](field_name)
        except:
            return None

def set_entity_string(entity, field_name, value):
    """Write a string field to Extensible Storage with IronPython generic fallback."""
    try:
        entity.Set[String](field_name, str(value or ""))
        return True
    except:
        try:
            entity.Set(field_name, str(value or ""))
            return True
        except:
            return False

def get_opening_tracking(elem):
    """Retrieve tracking information from storage, then fall back to legacy parameters."""
    tracking = {"mep_uid": None, "wall_uid": None, "wall_doc": None, "source": "None"}
    schema = get_tracking_schema(False)
    if schema:
        try:
            entity = elem.GetEntity(schema)
            if entity and entity.IsValid():
                tracking["mep_uid"] = get_entity_string(entity, schema, TRACKING_FIELD_MEP_UID)
                tracking["wall_uid"] = get_entity_string(entity, schema, TRACKING_FIELD_WALL_UID)
                tracking["wall_doc"] = get_entity_string(entity, schema, TRACKING_FIELD_WALL_DOC)
                if tracking["mep_uid"]:
                    tracking["source"] = "Storage"
                    return tracking
        except:
            pass

    for name in LEGACY_LINK_PARAM_NAMES:
        p = elem.LookupParameter(name)
        if p and p.AsString() and is_probable_revit_unique_id(p.AsString()):
            tracking["mep_uid"] = p.AsString()
            tracking["source"] = "Legacy Parameter"
            return tracking
    return tracking

def get_link_id(elem):
    """Retrieve the stored MEP UniqueId from the opening instance."""
    return get_opening_tracking(elem).get("mep_uid")

def set_opening_tracking(elem, mep_uid, wall_uid=None, wall_doc_title=None):
    """Store source MEP and wall identity for future synchronization."""
    schema = get_tracking_schema(True)
    entity = Entity(schema)
    set_entity_string(entity, TRACKING_FIELD_MEP_UID, mep_uid)
    set_entity_string(entity, TRACKING_FIELD_WALL_UID, wall_uid)
    set_entity_string(entity, TRACKING_FIELD_WALL_DOC, wall_doc_title)
    try:
        elem.SetEntity(entity)
    except Exception as e:
        logger.warning("Could not write opening tracking storage: {}".format(e))

    # Keep a taggable/shared parameter populated when the family has it.
    for name in LINK_PARAM_NAMES:
        p = elem.LookupParameter(name)
        if p and not p.IsReadOnly:
            try:
                p.Set(str(mep_uid))
                return
            except:
                pass

def set_link_id(elem, value):
    """Compatibility wrapper for older code paths."""
    set_opening_tracking(elem, value)

def transform_bounding_box(bbox, transform=None):
    """Transform every bounding-box corner so rotated links produce valid extents."""
    if not bbox or not transform:
        return bbox
    points = [
        DB.XYZ(bbox.Min.X, bbox.Min.Y, bbox.Min.Z),
        DB.XYZ(bbox.Min.X, bbox.Min.Y, bbox.Max.Z),
        DB.XYZ(bbox.Min.X, bbox.Max.Y, bbox.Min.Z),
        DB.XYZ(bbox.Min.X, bbox.Max.Y, bbox.Max.Z),
        DB.XYZ(bbox.Max.X, bbox.Min.Y, bbox.Min.Z),
        DB.XYZ(bbox.Max.X, bbox.Min.Y, bbox.Max.Z),
        DB.XYZ(bbox.Max.X, bbox.Max.Y, bbox.Min.Z),
        DB.XYZ(bbox.Max.X, bbox.Max.Y, bbox.Max.Z)
    ]
    transformed = [transform.OfPoint(pt) for pt in points]
    new_bbox = DB.BoundingBoxXYZ()
    new_bbox.Min = DB.XYZ(
        min(pt.X for pt in transformed),
        min(pt.Y for pt in transformed),
        min(pt.Z for pt in transformed)
    )
    new_bbox.Max = DB.XYZ(
        max(pt.X for pt in transformed),
        max(pt.Y for pt in transformed),
        max(pt.Z for pt in transformed)
    )
    return new_bbox

def get_shape_from_symbol(symbol):
    """Infer opening shape from the selected family type name."""
    if not symbol:
        return "RECT"
    name = "{} {}".format(symbol.Family.Name, symbol.Name).lower()
    return "ROUND" if any(token in name for token in ["round", "circular", "pipe"]) else "RECT"

def get_first_parameter(elem, possible_names):
    """Find the first parameter from a name fallback list."""
    for name in possible_names:
        p = elem.LookupParameter(name)
        if p:
            return p
    return None

def parameter_double_changed(param, target_value, tolerance=0.001):
    """Check whether a double parameter differs from a target internal-unit value."""
    if not param or param.StorageType != DB.StorageType.Double:
        return False
    return abs(param.AsDouble() - target_value) > tolerance

def needs_opening_size_update(opening, shape, width, height, depth):
    """Detect dimension changes for both diameter-based and width-height opening families."""
    if shape == "ROUND":
        diameter = max(width, height)
        p_dia = get_first_parameter(opening, PARAM_DIAMETERS)
        if parameter_double_changed(p_dia, diameter):
            return True
        if not p_dia:
            p_w = get_first_parameter(opening, PARAM_WIDTHS)
            p_h = get_first_parameter(opening, PARAM_HEIGHTS)
            if parameter_double_changed(p_w, diameter) or parameter_double_changed(p_h, diameter):
                return True
    else:
        p_w = get_first_parameter(opening, PARAM_WIDTHS)
        p_h = get_first_parameter(opening, PARAM_HEIGHTS)
        if parameter_double_changed(p_w, width) or parameter_double_changed(p_h, height):
            return True
    p_depth = get_first_parameter(opening, PARAM_DEPTHS)
    return parameter_double_changed(p_depth, depth)

def set_opening_size(opening, shape, width, height, depth):
    """Write opening dimensions using round and rectangular family parameter conventions."""
    wrote_size = False
    if shape == "ROUND":
        diameter = max(width, height)
        wrote_size = find_and_set_parameter(opening, PARAM_DIAMETERS, diameter)
        wrote_size = find_and_set_parameter(opening, PARAM_WIDTHS, diameter) or wrote_size
        find_and_set_parameter(opening, PARAM_HEIGHTS, diameter)
    else:
        wrote_size = find_and_set_parameter(opening, PARAM_WIDTHS, width)
        wrote_size = find_and_set_parameter(opening, PARAM_HEIGHTS, height) or wrote_size
    wrote_depth = find_and_set_parameter(opening, PARAM_DEPTHS, depth)
    return wrote_size or wrote_depth

def move_opening_to_point(opening, target_point):
    """Move an opening instance to the target point using Revit's transform API."""
    loc = opening.Location
    if not hasattr(loc, "Point"):
        return False
    current_point = loc.Point
    if current_point.IsAlmostEqualTo(target_point, 0.01):
        return False
    DB.ElementTransformUtils.MoveElement(doc, opening.Id, target_point - current_point)
    return True

def change_opening_symbol(opening, target_symbol):
    """Swap the opening family type when rules now require another opening profile."""
    if not target_symbol or opening.Symbol.Id == target_symbol.Id:
        return False
    if not target_symbol.IsActive:
        target_symbol.Activate()
    opening.Symbol = target_symbol
    return True

def collect_tracked_opening_signatures(symbol_family_names):
    """Build a set of existing MEP-wall-location opening signatures to prevent duplicate placement."""
    signatures = set()
    instances = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Windows).WhereElementIsNotElementType().ToElements()
    generic_instances = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_GenericModel).WhereElementIsNotElementType().ToElements()
    for inst in list(instances) + list(generic_instances):
        try:
            if symbol_family_names and inst.Symbol.Family.Name not in symbol_family_names:
                continue
            tracking = get_opening_tracking(inst)
            if tracking.get("mep_uid") and tracking.get("wall_uid") and hasattr(inst.Location, "Point"):
                pt = inst.Location.Point
                coord_key = (round(pt.X, 2), round(pt.Y, 2), round(pt.Z, 2))
                signatures.add((tracking["mep_uid"], tracking["wall_uid"], coord_key))
        except:
            continue
    return signatures

def get_mep_system_name(mep_el):
    """Retrieve MEP System name from the element or connectors."""
    p_system = get_parameter_by_bips(mep_el, ["RBS_SYSTEM_NAME_PARAM"])
    if p_system and p_system.AsString():
        return p_system.AsString()
    try:
        if hasattr(mep_el, 'ConnectorManager') and mep_el.ConnectorManager:
            names = []
            for conn in mep_el.ConnectorManager.Connectors:
                if conn.MEPSystem:
                    names.append(conn.MEPSystem.Name)
            if names:
                return ", ".join(list(set(names)))
    except:
        pass
    return "N/A"

def get_mep_size_string(mep_el, mep_dim):
    """Format a human-readable size descriptor."""
    if mep_dim['shape'] == 'ROUND':
        dia_mm = to_mm(mep_dim['diameter'])
        return "Dia {:.0f}mm".format(dia_mm)
    else:
        w_mm = to_mm(mep_dim['width'])
        h_mm = to_mm(mep_dim['height'])
        if w_mm > 0 and h_mm > 0:
            return "{:.0f}x{:.0f}mm".format(w_mm, h_mm)

        # BBox fallback for fittings/equipment
        bbox = mep_el.get_BoundingBox(None)
        if bbox:
            dims = bbox.Max - bbox.Min
            return "BBox {:.0f}x{:.0f}x{:.0f}mm".format(to_mm(dims.X), to_mm(dims.Y), to_mm(dims.Z))
    return "N/A"

def get_local_rfa_files():
    """Scan the script folder for available .rfa files."""
    script_dir = os.path.dirname(__file__)
    rfa_files = []
    try:
        for f in os.listdir(script_dir):
            if f.lower().endswith(".rfa"):
                rfa_files.append(f)
    except Exception as e:
        logger.warning("Could not search local RFA files: {}".format(e))
    return rfa_files

def load_local_family(doc, rfa_path, name):
    """Load a family into the document if not already loaded."""
    families = DB.FilteredElementCollector(doc).OfClass(DB.Family)
    for fam in families:
        if fam.Name == name:
            return fam
    try:
        # Use simple overload (returns bool) and retrieve family object by name from collector
        loaded = doc.LoadFamily(rfa_path)
        if loaded:
            families = DB.FilteredElementCollector(doc).OfClass(DB.Family)
            for fam in families:
                if fam.Name == name:
                    return fam
    except Exception as e:
        logger.warning("Failed to load local family {}: {}".format(name, e))
    return None

def get_first_symbol(family):
    """Get the first active symbol of a loaded family."""
    if not family:
        return None
    for symbol_id in family.GetFamilySymbolIds():
        symbol = family.Document.GetElement(symbol_id)
        if symbol:
            return symbol
    return None

def build_family_map(doc):
    """Build a mapping of loaded window/generic opening symbols."""
    family_map = {}
    symbols = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol)
    for s in symbols:
        try:
            if not s or not s.Category:
                continue
            if s.Category.BuiltInCategory in [DB.BuiltInCategory.OST_Windows, DB.BuiltInCategory.OST_GenericModel]:
                f_name = s.Family.Name
                t_name = s.Name
                display_name = "{} : {}".format(f_name, t_name)
                family_map[display_name] = s
        except:
            continue
    return family_map

def collect_elements(scope):
    """
    Collect MEP elements and walls in host and links based on selected scope.
    Returns: (mep_items, wall_items) as lists of (element, transform, document)
    """
    mep_items = []
    wall_items = []

    # Track link instances
    link_instances = DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance).ToElements()
    link_docs = {}
    for link in link_instances:
        l_doc = link.GetLinkDocument()
        if l_doc:
            link_docs[l_doc.Title] = (l_doc, link.GetTotalTransform())

    if scope == 'SELECTION':
        selection_ids = uidoc.Selection.GetElementIds()
        for eid in selection_ids:
            el = doc.GetElement(eid)
            if not el:
                continue
            if isinstance(el, DB.RevitLinkInstance):
                l_doc = el.GetLinkDocument()
                if l_doc:
                    transform = el.GetTotalTransform()
                    for sub_el in DB.FilteredElementCollector(l_doc).WhereElementIsNotElementType().ToElements():
                        if not sub_el or not sub_el.Category:
                            continue
                        cat_id = sub_el.Category.BuiltInCategory
                        if cat_id in MEP_CATEGORIES:
                            mep_items.append((sub_el, transform, l_doc))
                        elif cat_id in WALL_CATEGORIES:
                            wall_items.append((sub_el, transform, l_doc))
            else:
                if el.Category:
                    cat_id = el.Category.BuiltInCategory
                    if cat_id in MEP_CATEGORIES:
                        mep_items.append((el, None, doc))
                    elif cat_id in WALL_CATEGORIES:
                        wall_items.append((el, None, doc))
    else:
        # Collect host elements
        if scope == 'VIEW':
            collector = DB.FilteredElementCollector(doc, doc.ActiveView.Id)
        else: # 'MODEL'
            collector = DB.FilteredElementCollector(doc)

        host_elems = collector.WhereElementIsNotElementType().ToElements()
        for el in host_elems:
            if not el or not el.Category:
                continue
            cat_id = el.Category.BuiltInCategory
            if cat_id in MEP_CATEGORIES:
                mep_items.append((el, None, doc))
            elif cat_id in WALL_CATEGORIES:
                wall_items.append((el, None, doc))

        # Collect from links
        for l_title, (l_doc, transform) in link_docs.items():
            link_collector = DB.FilteredElementCollector(l_doc)
            link_elems = link_collector.WhereElementIsNotElementType().ToElements()
            for el in link_elems:
                if not el or not el.Category:
                    continue
                cat_id = el.Category.BuiltInCategory
                if cat_id in MEP_CATEGORIES:
                    mep_items.append((el, transform, l_doc))
                elif cat_id in WALL_CATEGORIES:
                    wall_items.append((el, transform, l_doc))

    return mep_items, wall_items

def load_rules():
    """Load opening_rules.json file. Generates standard rules if missing."""
    script_dir = os.path.dirname(__file__)
    path = os.path.join(script_dir, "opening_rules.json")
    if not os.path.exists(path):
        default_rules = {
            "OST_PipeCurves": [
                { "max_size_mm": 100.0, "shape": "ROUND", "family_name": "Window-Round Opening" },
                { "max_size_mm": 99999.0, "shape": "RECT", "family_name": "Window-Square Opening" }
            ],
            "OST_Conduit": [
                { "max_size_mm": 99999.0, "shape": "ROUND", "family_name": "Window-Round Opening" }
            ],
            "OST_DuctCurves": [
                { "max_size_mm": 150.0, "shape": "ROUND", "family_name": "Window-Round Opening" },
                { "max_size_mm": 99999.0, "shape": "RECT", "family_name": "Window-Square Opening" }
            ],
            "OST_CableTray": [
                { "max_size_mm": 99999.0, "shape": "RECT", "family_name": "Window-Square Opening" }
            ],
            "OST_PipeAccessory": [
                { "max_size_mm": 99999.0, "shape": "RECT", "family_name": "Window-Square Opening" }
            ],
            "OST_PipeFitting": [
                { "max_size_mm": 99999.0, "shape": "RECT", "family_name": "Window-Square Opening" }
            ],
            "OST_DuctAccessory": [
                { "max_size_mm": 99999.0, "shape": "RECT", "family_name": "Window-Square Opening" }
            ],
            "OST_DuctFitting": [
                { "max_size_mm": 99999.0, "shape": "RECT", "family_name": "Window-Square Opening" }
            ],
            "OST_MechanicalEquipment": [
                { "max_size_mm": 99999.0, "shape": "RECT", "family_name": "Window-Square Opening" }
            ]
        }
        try:
            with open(path, "w") as f:
                json.dump(default_rules, f, indent=2)
            return default_rules
        except:
            return {}

    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load opening_rules.json: {}".format(e))
        return {}

def save_rules(rules):
    """Save mapping rules dictionary back to opening_rules.json."""
    script_dir = os.path.dirname(__file__)
    path = os.path.join(script_dir, "opening_rules.json")
    try:
        with open(path, "w") as f:
            json.dump(rules, f, indent=2)
        return True
    except Exception as e:
        logger.warning("Failed to save opening_rules.json: {}".format(e))
        return False

def resolve_opening_family(mep_el, mep_dim, rules, family_map, ui_round, ui_rect):
    """Looks up mapping rules based on element category and dimension."""
    if not mep_el.Category:
        return ui_rect, "RECT"

    cat_name = mep_el.Category.BuiltInCategory.ToString()
    rules_list = rules.get(cat_name, [])

    # Calculate size in mm for rule checks
    size_mm = 0.0
    if mep_dim['shape'] == 'ROUND':
        size_mm = to_mm(mep_dim['diameter'])
    else:
        size_mm = to_mm(max(mep_dim['width'], mep_dim['height']))

    # Check diagonal boundary size if zero (fittings/equipment)
    if size_mm == 0.0:
        bbox = mep_el.get_BoundingBox(None)
        if bbox:
            dims = bbox.Max - bbox.Min
            size_mm = to_mm(max(dims.X, dims.Y, dims.Z))

    # Match against rules list
    for rule in rules_list:
        if size_mm <= rule.get("max_size_mm", 99999.0):
            shape = rule.get("shape", "RECT")
            fam_name = rule.get("family_name")
            if fam_name:
                for display_name, symbol in family_map.items():
                    if display_name.split(" : ")[0] == fam_name:
                        return symbol, shape
            return (ui_round if shape == "ROUND" else ui_rect), shape

    return (ui_round if mep_dim['shape'] == 'ROUND' else ui_rect), mep_dim['shape']

def boxes_overlap(boxA, boxB, tolerance=0.5):
    """Perform a 3D bounding box overlap check with custom tolerance in feet."""
    if boxA.Min.X - tolerance > boxB.Max.X: return False
    if boxA.Max.X + tolerance < boxB.Min.X: return False
    if boxA.Min.Y - tolerance > boxB.Max.Y: return False
    if boxA.Max.Y + tolerance < boxB.Min.Y: return False
    if boxA.Min.Z - tolerance > boxB.Max.Z: return False
    if boxA.Max.Z + tolerance < boxB.Min.Z: return False
    return True

# --- Interactive Rules Editor Table (WPF SelectFromList) ---

class RuleRow(object):
    """Represents a rule row displayed inside the pyRevit SelectFromList grid."""
    def __init__(self, category, max_size, shape, family_name, json_cat, json_idx, rule_index):
        self.category = category
        self.max_size = max_size
        self.shape = shape
        self.family_name = family_name
        self.json_cat = json_cat
        self.json_idx = json_idx
        self.rule_index = rule_index

    @property
    def Category(self):
        return self.category

    @property
    def MaxSize(self):
        return "{:.0f} mm".format(self.max_size) if self.max_size < 99999.0 else "Unlimited"

    @property
    def Shape(self):
        return self.shape

    @property
    def FamilyName(self):
        return self.family_name

    def __str__(self):
        return "{:<24} | {:<10} | {:<5} | {}".format(
            self.category,
            self.MaxSize,
            self.shape,
            self.family_name
        )

    def __repr__(self):
        return self.__str__()

def edit_rules_table():
    """WPF Rules Editor table workflow."""
    rules = load_rules()
    local_rfas = get_local_rfa_files()

    # Collect symbols loaded in project
    loaded_symbols = []
    symbols = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol)
    for s in symbols:
        if s.Category and s.Category.BuiltInCategory in [DB.BuiltInCategory.OST_Windows, DB.BuiltInCategory.OST_GenericModel]:
            loaded_symbols.append("{} : {}".format(s.Family.Name, s.Name))
    loaded_symbols = sorted(list(set(loaded_symbols)))

    tracked_cats = [
        "OST_PipeCurves", "OST_DuctCurves", "OST_CableTray", "OST_Conduit",
        "OST_PipeFitting", "OST_PipeAccessory", "OST_DuctFitting", "OST_DuctAccessory",
        "OST_MechanicalEquipment"
    ]

    while True:
        rule_rows = []
        rule_idx = 0
        for cat in tracked_cats:
            cat_rules = rules.get(cat, [])
            for idx, r in enumerate(cat_rules):
                rule_rows.append(RuleRow(cat, r.get("max_size_mm", 99999.0), r.get("shape", "RECT"), r.get("family_name", "N/A"), cat, idx, rule_idx))
                rule_idx += 1

        selected = forms.SelectFromList.show(
            rule_rows,
            title="Sizing Rules Mapping Table (Revit 2026 Compatible)",
            columns=["Category", "MaxSize", "Shape", "FamilyName"],
            button_name="Edit Selected Rule",
            multiselect=False
        )

        if not selected:
            menu_choice = forms.CommandSwitchWindow.show(
                ['Save & Close Editor', 'Discard Changes & Close', 'Add New Rule', 'Delete a Rule'],
                message="Rules Editor Actions:"
            )
            if not menu_choice or 'Close' in menu_choice:
                if menu_choice and 'Save' in menu_choice:
                    save_rules(rules)
                    print("Sizing rules saved successfully.")
                break
            elif 'Add New Rule' in menu_choice:
                add_new_rule_flow(rules, tracked_cats, local_rfas, loaded_symbols)
            elif 'Delete a Rule' in menu_choice:
                delete_rule_flow(rules, rule_rows)
            continue

        edit_rule_flow(rules, selected, local_rfas, loaded_symbols)

def edit_rule_flow(rules, selected_row, local_rfas, loaded_symbols):
    cat = selected_row.json_cat
    idx = selected_row.json_idx
    rule = rules[cat][idx]

    choice = forms.CommandSwitchWindow.show(
        ['Edit Max Size (mm)', 'Edit Shape (ROUND / RECT)', 'Edit Family Name', 'Delete This Rule'],
        message="Editing rule for category: {}".format(cat)
    )
    if not choice:
        return

    if 'Max Size' in choice:
        new_size_str = forms.ask_for_string(
            default=str(rule.get("max_size_mm", 99999.0)),
            prompt="Enter new max size threshold in mm (use 99999 for unlimited):",
            title="Edit Max Size"
        )
        if new_size_str:
            try:
                rule["max_size_mm"] = float(new_size_str)
            except ValueError:
                forms.alert("Size must be a valid number.")

    elif 'Shape' in choice:
        shape_choice = forms.CommandSwitchWindow.show(
            ['ROUND', 'RECT'],
            message="Select opening shape:"
        )
        if shape_choice:
            rule["shape"] = shape_choice

    elif 'Family Name' in choice:
        options = ["Use Local RFA: {}".format(f.split(".rfa")[0]) for f in local_rfas] + \
                  ["Use Loaded Family: {}".format(s.split(" : ")[0]) for s in loaded_symbols]
        options = sorted(list(set(options)))

        fam_choice = forms.SelectFromList.show(
            options,
            title="Select Opening Family:",
            multiselect=False
        )
        if fam_choice:
            fam_name = fam_choice.split(": ")[1]
            rule["family_name"] = fam_name

    elif 'Delete' in choice:
        rules[cat].pop(idx)
        if not rules[cat]:
            rules[cat] = []

def add_new_rule_flow(rules, tracked_cats, local_rfas, loaded_symbols):
    cat = forms.SelectFromList.show(
        tracked_cats,
        title="Select Category for New Rule:",
        multiselect=False
    )
    if not cat:
        return

    size_str = forms.ask_for_string(
        default="99999.0",
        prompt="Enter max size threshold in mm (use 99999 for unlimited):",
        title="New Rule Max Size"
    )
    if not size_str:
        return
    try:
        max_size = float(size_str)
    except ValueError:
        forms.alert("Size must be a valid number.")
        return

    shape = forms.CommandSwitchWindow.show(
        ['ROUND', 'RECT'],
        message="Select opening shape:"
    )
    if not shape:
        return

    options = ["Use Local RFA: {}".format(f.split(".rfa")[0]) for f in local_rfas] + \
              ["Use Loaded Family: {}".format(s.split(" : ")[0]) for s in loaded_symbols]
    options = sorted(list(set(options)))

    fam_choice = forms.SelectFromList.show(
        options,
        title="Select Opening Family for New Rule:",
        multiselect=False
    )
    if not fam_choice:
        return
    fam_name = fam_choice.split(": ")[1]

    new_rule = {
        "max_size_mm": max_size,
        "shape": shape,
        "family_name": fam_name
    }

    if cat not in rules:
        rules[cat] = []
    rules[cat].append(new_rule)
    rules[cat].sort(key=lambda r: r.get("max_size_mm", 99999.0))

def delete_rule_flow(rules, rule_rows):
    selected = forms.SelectFromList.show(
        rule_rows,
        title="Select Rule to Delete:",
        columns=["Category", "MaxSize", "Shape", "FamilyName"],
        multiselect=False
    )
    if selected:
        cat = selected.json_cat
        idx = selected.json_idx
        rules[cat].pop(idx)

# --- Main Script Execution ---

class SettingRow(object):
    """Represents a configuration setting displayed inside pyRevit SelectFromList grid."""
    def __init__(self, key, display_name, value, description, options=None, group="General"):
        self.key = key
        self.display_name = display_name
        self.value = value
        self.description = description
        self.options = options
        self.group = group

    @property
    def Group(self):
        return self.group

    @property
    def Setting(self):
        return self.display_name

    @property
    def Value(self):
        return str(self.value)

    @property
    def Description(self):
        return self.description

    def __str__(self):
        return "{:<22} | {:<28} | {}".format(
            self.group,
            self.display_name,
            self.value
        )

    def __repr__(self):
        return self.__str__()

class SettingsDashboardForm(Form):
    """Task-first Wall Opening dashboard with only the controls needed to run."""
    def __init__(self, settings):
        self.Text = "Wall Opening"
        self.Size = Size(1060, 690)
        self.StartPosition = FormStartPosition.CenterScreen
        self.Font = Font("Segoe UI", 9)
        self.BackColor = Color.FromArgb(242, 244, 247)
        self.settings = dict(settings)
        self.action = "cancel"
        self.inputs = {}
        self.profile_round = None
        self.profile_rect = None
        self.enable_numbering = None
        self.numbering_controls = []
        self._build_ui()
        self._sync_numbering_controls()
        self._sync_run_button()

    def _create_label(self, text, location, size, parent, bold=False):
        label = Label()
        label.Text = text
        label.Location = location
        label.Size = size
        label.Font = Font(self.Font.FontFamily, self.Font.Size, FontStyle.Bold if bold else FontStyle.Regular)
        label.ForeColor = Color.FromArgb(50, 50, 50)
        parent.Controls.Add(label)
        return label

    def _create_panel(self, title, location, size):
        panel = Panel()
        panel.Location = location
        panel.Size = size
        panel.BackColor = Color.White
        panel.BorderStyle = BorderStyle.FixedSingle
        self.Controls.Add(panel)
        self._create_label(title, Point(14, 12), Size(size.Width - 28, 22), panel, True)
        return panel

    def _create_button(self, text, location, size, handler, back_color):
        button = Button()
        button.Text = text
        button.Location = location
        button.Size = size
        button.BackColor = back_color
        button.ForeColor = Color.White
        button.FlatStyle = FlatStyle.Flat
        button.Click += handler
        return button

    def _create_hint(self, text, location, size, parent):
        label = self._create_label(text, location, size, parent, False)
        label.ForeColor = Color.FromArgb(85, 95, 105)
        return label

    def _add_combo(self, parent, key, label_text, options, x, y, width=260):
        self._create_label(label_text, Point(x, y), Size(width, 18), parent, False)
        combo = ComboBox()
        combo.Location = Point(x, y + 20)
        combo.Size = Size(width, 25)
        combo.DropDownStyle = ComboBoxStyle.DropDownList
        for option in options:
            combo.Items.Add(option)
        value = str(self.settings.get(key, ""))
        if value in list(options):
            combo.SelectedItem = value
        elif combo.Items.Count:
            combo.SelectedIndex = 0
        parent.Controls.Add(combo)
        self.inputs[key] = combo
        return combo

    def _add_checkbox(self, parent, text, x, y, checked=False, width=220):
        checkbox = CheckBox()
        checkbox.Text = text
        checkbox.Location = Point(x, y)
        checkbox.Size = Size(width, 24)
        checkbox.Checked = checked
        checkbox.BackColor = Color.White
        parent.Controls.Add(checkbox)
        return checkbox

    def _add_textbox(self, parent, key, label_text, x, y, width=170):
        self._create_label(label_text, Point(x, y), Size(width, 18), parent, False)
        textbox = TextBox()
        textbox.Location = Point(x, y + 20)
        textbox.Size = Size(width, 24)
        textbox.Text = str(self.settings.get(key, ""))
        parent.Controls.Add(textbox)
        self.inputs[key] = textbox
        return textbox

    def _build_ui(self):
        header = Panel()
        header.Location = Point(12, 12)
        header.Size = Size(1000, 64)
        header.BackColor = Color.FromArgb(47, 54, 64)
        self.Controls.Add(header)
        title = self._create_label("WALL OPENING", Point(18, 12), Size(360, 24), header, True)
        title.ForeColor = Color.White
        subtitle = self._create_label("Create and update custom wall openings from MEP-wall intersections.", Point(18, 36), Size(680, 18), header, False)
        subtitle.ForeColor = Color.FromArgb(220, 225, 230)

        workflow = self._create_panel("1. What should the tool do?", Point(12, 88), Size(322, 238))
        self._create_hint("Use Create for new openings. Use Update after MEP sizes or locations change.", Point(16, 42), Size(286, 36), workflow)
        mode = self._add_combo(workflow, "mode", "Action", ["Create Mode", "Update Mode"], 16, 88, 286)
        mode.SelectedIndexChanged += self._mode_changed
        self._add_combo(workflow, "scope", "Where to search", ["Active View", "Selected MEP Elements", "Entire Model"], 16, 146, 286)

        profiles = self._create_panel("2. Opening types", Point(350, 88), Size(314, 238))
        profile_value = str(self.settings.get("profiles", "Both Round & Rectangular"))
        self.profile_round = self._add_checkbox(profiles, "Round openings", 18, 54, "Round" in profile_value or "Both" in profile_value, 260)
        self.profile_rect = self._add_checkbox(profiles, "Rectangular openings", 18, 86, "Rectangular" in profile_value or "Both" in profile_value, 260)
        self._add_combo(profiles, "source", "Opening family source", ["Script Folder RFAs", "Already Loaded Families in Project"], 18, 128, 270)
        self._create_hint("Size rules decide when each family is used. Keep both checked for most projects.", Point(18, 188), Size(270, 34), profiles)

        clearances = self._create_panel("3. Clearance around MEP", Point(680, 88), Size(332, 238))
        self._create_hint("Values are added around the detected MEP size before writing opening dimensions.", Point(16, 42), Size(292, 36), clearances)
        self._add_textbox(clearances, "offset_pipe", "Pipe (mm)", 16, 88, 140)
        self._add_textbox(clearances, "offset_duct", "Duct (mm)", 176, 88, 136)
        self._add_textbox(clearances, "offset_tray", "Cable Tray (mm)", 16, 154, 140)
        self._add_textbox(clearances, "offset_conduit", "Conduit (mm)", 176, 154, 136)

        numbering = self._create_panel("4. Opening marks", Point(12, 346), Size(322, 232))
        self.enable_numbering = self._add_checkbox(numbering, "Number openings by category", 16, 50, str(self.settings.get("enable_numbering", "No")) == "Yes", 270)
        self.enable_numbering.CheckedChanged += self._numbering_changed
        self.numbering_controls.append(self._add_textbox(numbering, "number_param", "Write mark to parameter", 16, 86, 286))
        self.numbering_controls.append(self._add_textbox(numbering, "prefix_pipe", "Pipe prefix", 16, 144, 136))
        self.numbering_controls.append(self._add_textbox(numbering, "prefix_duct", "Duct prefix", 170, 144, 132))
        self.numbering_controls.append(self._add_textbox(numbering, "prefix_tray", "Cable tray prefix", 16, 188, 136))
        self.numbering_controls.append(self._add_textbox(numbering, "prefix_conduit", "Conduit prefix", 170, 188, 132))

        parameters = self._create_panel("5. Family parameter mapping", Point(350, 346), Size(314, 232))
        self._create_hint("Only change these when your opening family uses different parameter names.", Point(16, 42), Size(278, 34), parameters)
        self._add_textbox(parameters, "param_width", "Width", 16, 86, 132)
        self._add_textbox(parameters, "param_height", "Height", 166, 86, 128)
        self._add_textbox(parameters, "param_depth", "Wall thickness", 16, 144, 132)
        self._add_textbox(parameters, "param_system", "MEP system", 166, 144, 128)
        self._add_textbox(parameters, "param_size", "MEP size", 16, 188, 132)
        self._add_textbox(parameters, "param_elevation", "Elevation", 166, 188, 128)

        rules = self._create_panel("6. Family selection rules", Point(680, 346), Size(332, 232))
        self._create_hint("Rules map category and size to the opening family. Configure once, then just Create or Update.", Point(16, 48), Size(292, 46), rules)
        self.btn_rules = self._create_button("Edit Size Rules", Point(16, 106), Size(290, 36), self._rules_clicked, Color.FromArgb(41, 128, 185))
        rules.Controls.Add(self.btn_rules)
        self._create_hint("Default local RFAs: Window-Round Opening and Window-Square Opening.", Point(16, 158), Size(292, 42), rules)

        self.btn_run = self._create_button("Create Openings", Point(12, 604), Size(220, 36), self._run_clicked, Color.FromArgb(39, 174, 96))
        self.btn_cancel = self._create_button("Cancel", Point(872, 604), Size(140, 36), self._cancel_clicked, Color.FromArgb(127, 140, 141))
        self.Controls.Add(self.btn_run)
        self.Controls.Add(self.btn_cancel)

    def _mode_changed(self, sender, args):
        self._sync_run_button()

    def _numbering_changed(self, sender, args):
        self._sync_numbering_controls()

    def _sync_run_button(self):
        mode_control = self.inputs.get("mode")
        mode_value = str(mode_control.SelectedItem) if mode_control and mode_control.SelectedItem else str(self.settings.get("mode", "Create Mode"))
        self.btn_run.Text = "Update Openings" if mode_value == "Update Mode" else "Create Openings"

    def _sync_numbering_controls(self):
        if not self.enable_numbering:
            return
        enabled = self.enable_numbering.Checked
        for control in self.numbering_controls:
            control.Enabled = enabled

    def _collect_settings(self):
        new_settings = dict(self.settings)
        if not self.profile_round.Checked and not self.profile_rect.Checked:
            MessageBox.Show("Select at least one opening type: Round or Rectangular.", "Opening Type Required")
            return None
        if self.profile_round.Checked and self.profile_rect.Checked:
            new_settings["profiles"] = "Both Round & Rectangular"
        elif self.profile_round.Checked:
            new_settings["profiles"] = "Round Only"
        else:
            new_settings["profiles"] = "Rectangular Only"
        new_settings["enable_numbering"] = "Yes" if self.enable_numbering.Checked else "No"

        for key, control in self.inputs.items():
            if key in ["profiles", "enable_numbering"]:
                continue
            if isinstance(control, ComboBox):
                value = control.SelectedItem
            else:
                value = control.Text
            value = "" if value is None else str(value)
            if key.startswith("offset_"):
                try:
                    offset_value = float(value)
                    if offset_value < 0:
                        raise ValueError()
                    new_settings[key] = offset_value
                except:
                    MessageBox.Show("Clearance values must be zero or positive numbers.", "Invalid Clearance")
                    return None
            else:
                if key.startswith("param_") and not value.strip():
                    MessageBox.Show("Family parameter names cannot be empty.", "Invalid Parameter Mapping")
                    return None
                if key == "number_param" and self.enable_numbering.Checked and not value.strip():
                    MessageBox.Show("Numbering parameter cannot be empty when numbering is enabled.", "Invalid Numbering")
                    return None
                new_settings[key] = value
        return new_settings

    def _run_clicked(self, sender, args):
        collected = self._collect_settings()
        if collected is None:
            return
        self.settings = collected
        self.action = "run"
        self.DialogResult = DialogResult.OK
        self.Close()

    def _rules_clicked(self, sender, args):
        collected = self._collect_settings()
        if collected is not None:
            self.settings = collected
        self.action = "rules"
        self.DialogResult = DialogResult.OK
        self.Close()

    def _cancel_clicked(self, sender, args):
        self.action = "cancel"
        self.DialogResult = DialogResult.Cancel
        self.Close()

def make_setting_rows(s):
    """Generates settings rows for the WPF SelectFromList grid."""
    return [
        SettingRow("mode", "Operation Mode", s["mode"], "Create Mode (Place New Openings) or Update Mode (Sync Existing)", ["Create Mode", "Update Mode"], "1. Operation"),
        SettingRow("scope", "Processing Scope", s["scope"], "Selected MEP Elements / Active View / Entire Model", ["Selected MEP Elements", "Active View", "Entire Model"], "1. Operation"),
        SettingRow("profiles", "Opening Shapes to Place", s["profiles"], "Filter by shape: Both / Round Only / Rectangular Only", ["Both Round & Rectangular", "Round Only", "Rectangular Only"], "1. Operation"),
        SettingRow("source", "Family Source", s["source"], "Use Script Folder RFAs or Use Already Loaded Families", ["Script Folder RFAs", "Already Loaded Families in Project"], "1. Operation"),

        SettingRow("offset_pipe", "Clearance: Pipes (mm)", s["offset_pipe"], "Safety offset clearance for pipe openings", None, "2. Clearances (mm)"),
        SettingRow("offset_duct", "Clearance: Ducts (mm)", s["offset_duct"], "Safety offset clearance for duct openings", None, "2. Clearances (mm)"),
        SettingRow("offset_tray", "Clearance: Cable Trays (mm)", s["offset_tray"], "Safety offset clearance for cable trays", None, "2. Clearances (mm)"),
        SettingRow("offset_conduit", "Clearance: Conduits (mm)", s["offset_conduit"], "Safety offset clearance for conduit openings", None, "2. Clearances (mm)"),

        SettingRow("param_width", "Parameter: Width", s["param_width"], "Target parameter name for opening width", None, "3. Parameters"),
        SettingRow("param_height", "Parameter: Height", s["param_height"], "Target parameter name for opening height", None, "3. Parameters"),
        SettingRow("param_depth", "Parameter: Thickness", s["param_depth"], "Target parameter name for opening thickness", None, "3. Parameters"),
        SettingRow("param_system", "Parameter: MEP System", s["param_system"], "Target parameter name for system type metadata", None, "3. Parameters"),
        SettingRow("param_size", "Parameter: MEP Size", s["param_size"], "Target parameter name for MEP size metadata", None, "3. Parameters"),
        SettingRow("param_elevation", "Parameter: MEP Elevation", s["param_elevation"], "Target parameter name for opening elevation metadata", None, "3. Parameters"),

        SettingRow("enable_numbering", "Enable Numbering", s["enable_numbering"], "Enable category-grouped sequence numbering", ["Yes", "No"], "4. Numbering"),
        SettingRow("number_param", "Numbering Parameter", s["number_param"], "Target parameter name for numbering sequences", None, "4. Numbering"),
        SettingRow("prefix_pipe", "Prefix: Pipes", s["prefix_pipe"], "Prefix for Pipe openings (e.g. OP-P-)", None, "4. Numbering"),
        SettingRow("prefix_duct", "Prefix: Ducts", s["prefix_duct"], "Prefix for Duct openings (e.g. OP-D-)", None, "4. Numbering"),
        SettingRow("prefix_tray", "Prefix: Cable Trays", s["prefix_tray"], "Prefix for Cable Tray openings (e.g. OP-C-)", None, "4. Numbering"),
        SettingRow("prefix_conduit", "Prefix: Conduits", s["prefix_conduit"], "Prefix for Conduit openings (e.g. OP-T-)", None, "4. Numbering")
    ]

def configure_settings_table():
    """Renders the settings table and loops until execution or cancel."""
    s = {
        "mode": "Create Mode",
        "scope": "Active View",
        "profiles": "Both Round & Rectangular",
        "source": "Script Folder RFAs",
        "offset_pipe": 50.0,
        "offset_duct": 50.0,
        "offset_tray": 50.0,
        "offset_conduit": 50.0,
        "param_width": "Width",
        "param_height": "Height",
        "param_depth": "Thickness",
        "param_system": "MEP_System",
        "param_size": "MEP_Size",
        "param_elevation": "MEP_Elevation",
        "enable_numbering": "No",
        "number_param": "Comments",
        "prefix_pipe": "OP-P-",
        "prefix_duct": "OP-D-",
        "prefix_tray": "OP-C-",
        "prefix_conduit": "OP-T-"
    }

    script_dir = os.path.dirname(__file__)
    settings_path = os.path.join(script_dir, "settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r") as f:
                saved = json.load(f)
                for k, v in saved.items():
                    if k in s:
                        s[k] = v
        except:
            pass

    while True:
        form = SettingsDashboardForm(s)
        form.ShowDialog()
        s = dict(form.settings)

        if form.action == "run":
            try:
                with open(settings_path, "w") as f:
                    json.dump(s, f, indent=2)
            except:
                pass
            return s
        elif form.action == "rules":
            edit_rules_table()
            continue
        else:
            script.exit()

def main():
    global PARAM_WIDTHS, PARAM_HEIGHTS, PARAM_DIAMETERS, PARAM_DEPTHS, PARAM_SYSTEMS, PARAM_SIZES, PARAM_ELEVATIONS

    # Load mapping rules
    rules = load_rules()

    # Configure inputs using settings table
    settings = configure_settings_table()

    is_update_mode = settings["mode"] == "Update Mode"
    scope = "SELECTION" if "Selected" in settings["scope"] else ("VIEW" if "View" in settings["scope"] else "MODEL")

    place_round = "Round" in settings["profiles"] or "Both" in settings["profiles"]
    place_rect = "Rectangular" in settings["profiles"] or "Both" in settings["profiles"]

    source_local = "Script Folder" in settings["source"]

    offset_pipe = to_feet(settings["offset_pipe"])
    offset_duct = to_feet(settings["offset_duct"])
    offset_tray = to_feet(settings["offset_tray"])
    offset_conduit = to_feet(settings["offset_conduit"])

    param_width = settings["param_width"]
    param_height = settings["param_height"]
    param_depth = settings["param_depth"]
    param_system = settings["param_system"]
    param_size = settings["param_size"]
    param_elevation = settings["param_elevation"]

    enable_numbering = settings["enable_numbering"] == "Yes"
    number_param = settings["number_param"]
    prefix_pipe = settings["prefix_pipe"]
    prefix_duct = settings["prefix_duct"]
    prefix_tray = settings["prefix_tray"]
    prefix_conduit = settings["prefix_conduit"]

    # Prepend customized names to the globally searched fallbacks
    PARAM_WIDTHS = [param_width] + PARAM_WIDTHS
    PARAM_HEIGHTS = [param_height] + PARAM_HEIGHTS
    PARAM_DIAMETERS = PARAM_DIAMETERS + [param_width, param_height]
    PARAM_DEPTHS = [param_depth] + PARAM_DEPTHS
    PARAM_SYSTEMS = [param_system] + PARAM_SYSTEMS
    PARAM_SIZES = [param_size] + PARAM_SIZES
    PARAM_ELEVATIONS = [param_elevation] + PARAM_ELEVATIONS

    # Collect symbols loaded in project
    family_map = build_family_map(doc)
    sorted_names = sorted(family_map.keys())

    round_symbol_display = None
    rect_symbol_display = None

    if not source_local:
        if not family_map:
            forms.alert('No loaded opening families found. Please load families first.', exitscript=True)

        if place_round:
            default_round = None
            for name in sorted_names:
                lower = name.lower()
                if "opening" in lower and any(x in lower for x in ["round", "circular", "pipe", "conduit"]):
                    default_round = name
                    break
            round_symbol_display = forms.SelectFromList.show(
                sorted_names, title='Select Round Opening Family Type:',
                default=[default_round] if default_round else None, multiselect=False
            )
            if not round_symbol_display:
                script.exit()

        if place_rect:
            default_rect = None
            for name in sorted_names:
                lower = name.lower()
                if "opening" in lower and any(x in lower for x in ["rect", "square", "duct", "tray"]):
                    default_rect = name
                    break
            rect_symbol_display = forms.SelectFromList.show(
                sorted_names, title='Select Rectangular Opening Family Type:',
                default=[default_rect] if default_rect else None, multiselect=False
            )
            if not rect_symbol_display:
                script.exit()

    # --- Execute Transactions ---
    t = DB.Transaction(doc, "Automate Wall Openings")
    t.Start()

    try:
        # Load local RFA files dynamically if requested
        if source_local:
            script_dir = os.path.dirname(__file__)
            local_rfas = get_local_rfa_files()
            if not local_rfas:
                forms.alert("No local family .rfa files found in script folder.", exitscript=True)

            for rfa in local_rfas:
                rfa_path = os.path.join(script_dir, rfa)
                fam_name = rfa.split(".rfa")[0]
                fam_obj = load_local_family(doc, rfa_path, fam_name)
                if fam_obj:
                    for symbol_id in fam_obj.GetFamilySymbolIds():
                        symbol = doc.GetElement(symbol_id)
                        if symbol and not symbol.IsActive:
                            symbol.Activate()

            # Rebuild family map and fallback values
            family_map = build_family_map(doc)
            round_symbol = None
            rect_symbol = None
            for display_name, symbol in family_map.items():
                if "round" in display_name.lower():
                    round_symbol = symbol
                if "square" in display_name.lower() or "rect" in display_name.lower():
                    rect_symbol = symbol
        else:
            round_symbol = family_map[round_symbol_display] if place_round else None
            rect_symbol = family_map[rect_symbol_display] if place_rect else None

        if round_symbol and not round_symbol.IsActive:
            round_symbol.Activate()
        if rect_symbol and not rect_symbol.IsActive:
            rect_symbol.Activate()
        doc.Regenerate()

        # --- Mode A: CREATE MODE ---
        if not is_update_mode:
            mep_items, wall_items = collect_elements(scope)
            print("Found {} MEP elements and {} walls to inspect.".format(len(mep_items), len(wall_items)))

            placed_count = 0
            placed_details = []
            placed_keys = set()

            offsets = {
                DB.BuiltInCategory.OST_PipeCurves: offset_pipe,
                DB.BuiltInCategory.OST_DuctCurves: offset_duct,
                DB.BuiltInCategory.OST_CableTray: offset_tray,
                DB.BuiltInCategory.OST_Conduit: offset_conduit,
                DB.BuiltInCategory.OST_PipeFitting: offset_pipe,
                DB.BuiltInCategory.OST_PipeAccessory: offset_pipe,
                DB.BuiltInCategory.OST_DuctFitting: offset_duct,
                DB.BuiltInCategory.OST_DuctAccessory: offset_duct,
                DB.BuiltInCategory.OST_MechanicalEquipment: offset_duct
            }

            opening_family_names = set()
            if round_symbol:
                opening_family_names.add(round_symbol.Family.Name)
            if rect_symbol:
                opening_family_names.add(rect_symbol.Family.Name)
            existing_signatures = collect_tracked_opening_signatures(opening_family_names)

            # Bounding box filter optimization for large models
            for wall_el, wall_t, wall_doc in wall_items:
                wall_bbox = wall_el.get_BoundingBox(None)
                if not wall_bbox:
                    continue

                # Get wall solids and direction
                wall_solids = get_wall_solids(wall_el, wall_t)
                if not wall_solids:
                    continue
                wall_dir = get_wall_direction(wall_el, wall_t)

                # Transform wall bbox if in link
                wall_bbox = transform_bounding_box(wall_bbox, wall_t)

                # Filter candidates by Bounding Box pre-filter
                candidates = []
                for mep_el, mep_t, mep_doc in mep_items:
                    # Prevent self-intersections
                    if mep_el.Id == wall_el.Id and mep_doc == wall_doc:
                        continue

                    mep_bbox = mep_el.get_BoundingBox(None)
                    if not mep_bbox:
                        continue

                    mep_bbox = transform_bounding_box(mep_bbox, mep_t)

                    # Check overlap
                    if boxes_overlap(wall_bbox, mep_bbox, tolerance=1.0):
                        candidates.append((mep_el, mep_t))

                # Perform precise geometric checks on candidates
                for mep_el, mep_t in candidates:
                    mep_cat = mep_el.Category.BuiltInCategory
                    mep_dim = get_mep_dimensions(mep_el)

                    # Resolve symbol using mapping rules JSON
                    symbol, shape = resolve_opening_family(mep_el, mep_dim, rules, family_map, round_symbol, rect_symbol)

                    # Filter based on shape selection
                    if shape == 'ROUND' and not place_round:
                        continue
                    if shape == 'RECT' and not place_rect:
                        continue
                    if not symbol:
                        continue

                    offset_ft = offsets.get(mep_cat, to_feet(50.0))

                    # Curve-based elements (Pipes, Ducts, Trays, Conduits)
                    mep_curve = get_transformed_curve(mep_el, mep_t)
                    if mep_curve:
                        mep_dir = mep_curve.ComputeDerivatives(0.5, True).BasisX.Normalize()

                        intersect_segment = None
                        for solid in wall_solids:
                            res = solid.IntersectWithCurve(mep_curve, DB.SolidCurveIntersectionOptions())
                            if res and res.SegmentCount > 0:
                                intersect_segment = res.GetCurveSegment(0)
                                break

                        if not intersect_segment:
                            continue

                        midpoint = intersect_segment.Evaluate(0.5, True)
                        coord_key = (round(midpoint.X, 2), round(midpoint.Y, 2), round(midpoint.Z, 2))
                        if coord_key in placed_keys:
                            continue
                        if (mep_el.UniqueId, wall_el.UniqueId, coord_key) in existing_signatures:
                            continue

                        projected_dims = calculate_projection_size(mep_dim, mep_dir, wall_dir, offset_ft)
                        if not projected_dims:
                            continue
                        opening_w, opening_h = projected_dims
                        wall_thickness = wall_el.Width if hasattr(wall_el, 'Width') else intersect_segment.Length

                    # Solid-based elements (Fittings, Accessories, Mechanical Equipment)
                    else:
                        mep_solids = get_element_solids(mep_el, mep_t)
                        if not mep_solids:
                            continue

                        intersect_solid = None
                        for s_mep in mep_solids:
                            for s_wall in wall_solids:
                                try:
                                    res_solid = DB.BooleanOperationsUtils.ExecuteBooleanOperation(
                                        s_mep, s_wall, DB.BooleanOperationsType.Intersect
                                    )
                                    if res_solid and res_solid.Volume > 0.0001:
                                        intersect_solid = res_solid
                                        break
                                except:
                                    pass
                            if intersect_solid:
                                break

                        if not intersect_solid:
                            continue

                        # Centroid of overlapping region
                        bbox_intersect = intersect_solid.GetBoundingBox()
                        midpoint = bbox_intersect.Min + (bbox_intersect.Max - bbox_intersect.Min) * 0.5

                        coord_key = (round(midpoint.X, 2), round(midpoint.Y, 2), round(midpoint.Z, 2))
                        if coord_key in placed_keys:
                            continue
                        if (mep_el.UniqueId, wall_el.UniqueId, coord_key) in existing_signatures:
                            continue

                        # Get overlapping vertices and project them
                        pts = []
                        for face in intersect_solid.Faces:
                            for loop in face.EdgeLoops:
                                for edge in loop:
                                    pts.append(edge.Evaluate(0.0))
                                    pts.append(edge.Evaluate(1.0))

                        x_coords = [p.DotProduct(wall_dir) for p in pts]
                        y_coords = [p.DotProduct(DB.XYZ.BasisZ) for p in pts]

                        opening_w = (max(x_coords) - min(x_coords)) + 2.0 * offset_ft
                        opening_h = (max(y_coords) - min(y_coords)) + 2.0 * offset_ft
                        wall_thickness = wall_el.Width if hasattr(wall_el, 'Width') else (bbox_intersect.Max.Y - bbox_intersect.Min.Y)

                    # Place instance
                    lvl = None
                    if wall_el.Document == doc:
                        lvl_id = wall_el.LevelId
                        if lvl_id != DB.ElementId.InvalidElementId:
                            lvl = doc.GetElement(lvl_id)
                    if not lvl:
                        lvl = get_closest_level(doc, midpoint.Z)
                    if not lvl:
                        continue

                    inst = None
                    if wall_el.Document == doc:
                        try:
                            inst = doc.Create.NewFamilyInstance(
                                midpoint, symbol, wall_el, lvl, DB.Structure.StructuralType.NonStructural
                            )
                        except:
                            pass
                    if not inst:
                        try:
                            inst = doc.Create.NewFamilyInstance(
                                midpoint, symbol, lvl, DB.Structure.StructuralType.NonStructural
                            )
                            # Align angle with wall
                            wall_angle = math.atan2(wall_dir.Y, wall_dir.X)
                            rot_axis = DB.Line.CreateBound(midpoint, midpoint + DB.XYZ.BasisZ)
                            DB.ElementTransformUtils.RotateElement(doc, inst.Id, rot_axis, wall_angle)
                        except:
                            continue

                    # Set size parameters
                    set_opening_size(inst, shape, opening_w, opening_h, wall_thickness)

                    # Set metadata
                    find_and_set_parameter(inst, PARAM_SYSTEMS, get_mep_system_name(mep_el))
                    find_and_set_parameter(inst, PARAM_SIZES, get_mep_size_string(mep_el, mep_dim))

                    elevation_string = "{:.0f} mm".format(to_mm(midpoint.Z))
                    find_and_set_parameter(inst, PARAM_ELEVATIONS, elevation_string)

                    # Write tracking IDs for future size and position updates.
                    set_opening_tracking(inst, mep_el.UniqueId, wall_el.UniqueId, wall_el.Document.Title)

                    placed_count += 1
                    placed_keys.add(coord_key)
                    existing_signatures.add((mep_el.UniqueId, wall_el.UniqueId, coord_key))
                    placed_details.append((inst, mep_cat, midpoint))

            # Sequential numbering
            if enable_numbering and placed_details:
                grouped = {}
                for inst, cat, mid in placed_details:
                    if cat not in grouped: grouped[cat] = []
                    grouped[cat].append((inst, mid))

                prefixes = {
                    DB.BuiltInCategory.OST_PipeCurves: prefix_pipe,
                    DB.BuiltInCategory.OST_DuctCurves: prefix_duct,
                    DB.BuiltInCategory.OST_CableTray: prefix_tray,
                    DB.BuiltInCategory.OST_Conduit: prefix_conduit
                }

                for cat, items in grouped.items():
                    items.sort(key=lambda item: (round(item[1].Z, 3), round(item[1].Y, 3), round(item[1].X, 3)))
                    pfx = prefixes.get(cat, "OP-")
                    for idx, (inst, _) in enumerate(items):
                        seq_num = "{}{:03d}".format(pfx, idx + 1)
                        find_and_set_parameter(inst, [number_param], seq_num)

            t.Commit()
            print("Successfully placed {} openings.".format(placed_count))
            output.print_md("### Placement Summary")
            output.print_md("- **Total Placed**: {}".format(placed_count))

            if placed_details:
                table_data = []
                for idx, (inst, cat, mid) in enumerate(placed_details):
                    mep_cat_name = str(cat).replace("OST_", "")

                    shape = "ROUND" if "round" in inst.Symbol.Family.Name.lower() else "RECT"

                    p_w = inst.LookupParameter(param_width) or inst.LookupParameter("Width")
                    p_h = inst.LookupParameter(param_height) or inst.LookupParameter("Height")
                    size = "N/A"
                    if p_w:
                        if shape == "ROUND":
                            size = "Dia {:.0f}mm".format(to_mm(p_w.AsDouble()))
                        elif p_h:
                            size = "{:.0f}x{:.0f}mm".format(to_mm(p_w.AsDouble()), to_mm(p_h.AsDouble()))

                    p_d = inst.LookupParameter(param_depth) or inst.LookupParameter("Thickness")
                    thickness = "{:.0f}mm".format(to_mm(p_d.AsDouble())) if p_d else "N/A"

                    loc_str = "{:.1f}, {:.1f}, {:.1f}".format(to_mm(mid.X), to_mm(mid.Y), to_mm(mid.Z))

                    # Fetch mark
                    p_mark = inst.LookupParameter(number_param)
                    mark = p_mark.AsString() if p_mark and p_mark.AsString() else "N/A"

                    table_data.append([
                        idx + 1,
                        mark,
                        inst.Id.ToString(),
                        mep_cat_name,
                        shape,
                        size,
                        thickness,
                        loc_str
                    ])

                output.print_table(
                    table_data=table_data,
                    title="Placed Wall Openings Summary Table",
                    columns=["No.", "Mark", "Opening ID", "MEP Category", "Shape", "Size", "Wall Thickness", "Location (X, Y, Z)"]
                )

        # --- Mode B: SYNC & UPDATE MODE ---
        else:
            print("Syncing existing openings...")

            symbols_names = set()
            if round_symbol:
                symbols_names.add(round_symbol.Family.Name)
            if rect_symbol:
                symbols_names.add(rect_symbol.Family.Name)
            if not symbols_names:
                for display_name in family_map.keys():
                    symbols_names.add(display_name.split(" : ")[0])

            instances = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Windows).WhereElementIsNotElementType().ToElements()
            generic_instances = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_GenericModel).WhereElementIsNotElementType().ToElements()
            all_instances = list(instances) + list(generic_instances)

            tracked_openings = []
            for inst in all_instances:
                f_name = inst.Symbol.Family.Name
                if f_name in symbols_names:
                    tracking = get_opening_tracking(inst)
                    if tracking.get("mep_uid"):
                        tracked_openings.append((inst, tracking))

            # Get links
            link_instances = DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance).ToElements()

            # Map of MEP element lookups
            orphaned_openings = []
            updated_count = 0
            updated_details = []

            offsets = {
                DB.BuiltInCategory.OST_PipeCurves: offset_pipe,
                DB.BuiltInCategory.OST_DuctCurves: offset_duct,
                DB.BuiltInCategory.OST_CableTray: offset_tray,
                DB.BuiltInCategory.OST_Conduit: offset_conduit,
                DB.BuiltInCategory.OST_PipeFitting: offset_pipe,
                DB.BuiltInCategory.OST_PipeAccessory: offset_pipe,
                DB.BuiltInCategory.OST_DuctFitting: offset_duct,
                DB.BuiltInCategory.OST_DuctAccessory: offset_duct,
                DB.BuiltInCategory.OST_MechanicalEquipment: offset_duct
            }

            # CRITICAL PERFORMANCE CACHE: Collect all walls ONCE outside the loop to speed up updates in large-scale projects
            _, wall_items = collect_elements("MODEL")
            print("Cached {} walls for update verification checks.".format(len(wall_items)))

            for opening, tracking in tracked_openings:
                # 1. Retrieve the MEP element
                mep_uid = tracking.get("mep_uid")
                wall_uid = tracking.get("wall_uid")
                mep_el = None
                mep_t = None
                mep_doc_name = "Host"

                # Check host
                try:
                    mep_el = doc.GetElement(mep_uid)
                except:
                    pass

                # Check links
                if not mep_el:
                    for link in link_instances:
                        link_doc = link.GetLinkDocument()
                        if link_doc:
                            try:
                                mep_el = link_doc.GetElement(mep_uid)
                                if mep_el:
                                    mep_t = link.GetTotalTransform()
                                    mep_doc_name = link_doc.Title
                                    break
                            except:
                                pass

                if not mep_el:
                    # Linked MEP element was deleted
                    orphaned_openings.append(opening)
                    continue

                # 2. Check if still intersecting any wall
                mep_bbox = mep_el.get_BoundingBox(None)
                if not mep_bbox:
                    orphaned_openings.append(opening)
                    continue

                mep_bbox = transform_bounding_box(mep_bbox, mep_t)

                # Find intersecting walls
                wall_candidates = []
                for wall_el, wall_t, wall_doc in wall_items:
                    if wall_uid and wall_el.UniqueId != wall_uid:
                        continue
                    wall_bbox = wall_el.get_BoundingBox(None)
                    if not wall_bbox:
                        continue
                    wall_bbox = transform_bounding_box(wall_bbox, wall_t)

                    if boxes_overlap(mep_bbox, wall_bbox, tolerance=1.0):
                        wall_candidates.append((wall_el, wall_t))

                # Perform precise collision
                intersect_found = False
                matched_wall = None
                new_midpoint = None
                new_w, new_h, new_d = 0.0, 0.0, 0.0

                mep_cat = mep_el.Category.BuiltInCategory
                mep_dim = get_mep_dimensions(mep_el)
                target_symbol, target_shape = resolve_opening_family(mep_el, mep_dim, rules, family_map, round_symbol, rect_symbol)
                if not target_shape:
                    target_shape = get_shape_from_symbol(opening.Symbol)
                offset_ft = offsets.get(mep_cat, to_feet(50.0))

                for wall_el, wall_t in wall_candidates:
                    wall_solids = get_wall_solids(wall_el, wall_t)
                    if not wall_solids:
                        continue
                    wall_dir = get_wall_direction(wall_el, wall_t)

                    # Curve check
                    mep_curve = get_transformed_curve(mep_el, mep_t)
                    if mep_curve:
                        mep_dir = mep_curve.ComputeDerivatives(0.5, True).BasisX.Normalize()
                        intersect_segment = None
                        for solid in wall_solids:
                            res = solid.IntersectWithCurve(mep_curve, DB.SolidCurveIntersectionOptions())
                            if res and res.SegmentCount > 0:
                                intersect_segment = res.GetCurveSegment(0)
                                break

                        if intersect_segment:
                            new_midpoint = intersect_segment.Evaluate(0.5, True)
                            projected_dims = calculate_projection_size(mep_dim, mep_dir, wall_dir, offset_ft)
                            if projected_dims:
                                new_w, new_h = projected_dims
                                new_d = wall_el.Width if hasattr(wall_el, 'Width') else intersect_segment.Length
                                intersect_found = True
                                matched_wall = wall_el
                                break
                    # Solid check
                    else:
                        mep_solids = get_element_solids(mep_el, mep_t)
                        intersect_solid = None
                        for s_mep in mep_solids:
                            for s_wall in wall_solids:
                                try:
                                    res_solid = DB.BooleanOperationsUtils.ExecuteBooleanOperation(
                                        s_mep, s_wall, DB.BooleanOperationsType.Intersect
                                    )
                                    if res_solid and res_solid.Volume > 0.0001:
                                        intersect_solid = res_solid
                                        break
                                except:
                                    pass
                            if intersect_solid:
                                break

                        if intersect_solid:
                            bbox_intersect = intersect_solid.GetBoundingBox()
                            new_midpoint = bbox_intersect.Min + (bbox_intersect.Max - bbox_intersect.Min) * 0.5

                            pts = []
                            for face in intersect_solid.Faces:
                                for loop in face.EdgeLoops:
                                    for edge in loop:
                                        pts.append(edge.Evaluate(0.0))
                                        pts.append(edge.Evaluate(1.0))

                            x_coords = [p.DotProduct(wall_dir) for p in pts]
                            y_coords = [p.DotProduct(DB.XYZ.BasisZ) for p in pts]

                            new_w = (max(x_coords) - min(x_coords)) + 2.0 * offset_ft
                            new_h = (max(y_coords) - min(y_coords)) + 2.0 * offset_ft
                            new_d = wall_el.Width if hasattr(wall_el, 'Width') else (bbox_intersect.Max.Y - bbox_intersect.Min.Y)
                            intersect_found = True
                            matched_wall = wall_el
                            break

                if not intersect_found:
                    # MEP element moved away from wall
                    orphaned_openings.append(opening)
                    continue

                if matched_wall:
                    set_opening_tracking(opening, mep_uid, matched_wall.UniqueId, matched_wall.Document.Title)

                # 3. Update parameters and location if changed
                has_moved = False
                try:
                    if hasattr(opening.Location, "Point"):
                        has_moved = not opening.Location.Point.IsAlmostEqualTo(new_midpoint, 0.01)
                except:
                    has_moved = False

                needs_symbol_update = target_symbol is not None and opening.Symbol.Id != target_symbol.Id
                needs_param_update = needs_opening_size_update(opening, target_shape, new_w, new_h, new_d)

                if has_moved or needs_param_update or needs_symbol_update:
                    symbol_changed = False
                    if needs_symbol_update:
                        try:
                            symbol_changed = change_opening_symbol(opening, target_symbol)
                        except:
                            symbol_changed = False
                    if has_moved:
                        try:
                            move_opening_to_point(opening, new_midpoint)
                        except:
                            has_moved = False
                    set_opening_size(opening, target_shape, new_w, new_h, new_d)

                    # Update metadata
                    find_and_set_parameter(opening, PARAM_SYSTEMS, get_mep_system_name(mep_el))
                    find_and_set_parameter(opening, PARAM_SIZES, get_mep_size_string(mep_el, mep_dim))

                    elevation_string = "{:.0f} mm".format(to_mm(new_midpoint.Z))
                    find_and_set_parameter(opening, PARAM_ELEVATIONS, elevation_string)

                    updated_count += 1
                    print("Updated Opening ID: {} - Moved: {}, Resized: {}, Type Changed: {}".format(opening.Id, has_moved, needs_param_update, symbol_changed))
                    updated_details.append((opening, mep_cat, new_midpoint, has_moved, needs_param_update or symbol_changed))

            print("\nSync completed. Updated {} openings.".format(updated_count))

            # 4. Handle orphaned openings
            if orphaned_openings:
                print("Found {} orphaned openings (linked MEP element was deleted or moved).".format(len(orphaned_openings)))
                clean_choice = forms.CommandSwitchWindow.show(
                    ['Yes, Delete Them', 'No, Keep Them'],
                    message='Delete {} orphaned openings?'.format(len(orphaned_openings))
                )
                if clean_choice and 'Delete' in clean_choice:
                    for orphaned in orphaned_openings:
                        try:
                            doc.Delete(orphaned.Id)
                        except:
                            pass
                    print("Deleted orphaned openings.")
                    output.print_md("- **Orphaned Openings Deleted**: {}".format(len(orphaned_openings)))
                else:
                    output.print_md("- **Orphaned Openings Kept**: {}".format(len(orphaned_openings)))
                    # Flag them in Comments
                    for orphaned in orphaned_openings:
                        find_and_set_parameter(orphaned, ["Comments"], "ORPHANED")
            else:
                print("No orphaned openings found.")

            t.Commit()

            output.print_md("### Sync Summary")
            output.print_md("- **Total Tracked Openings Inspected**: {}".format(len(tracked_openings)))
            output.print_md("- **Total Openings Updated**: {}".format(updated_count))
            output.print_md("- **Total Orphaned Openings**: {}".format(len(orphaned_openings)))

            if updated_details:
                table_data = []
                for idx, (inst, cat, mid, moved, resized) in enumerate(updated_details):
                    mep_cat_name = str(cat).replace("OST_", "")

                    shape = "ROUND" if "round" in inst.Symbol.Family.Name.lower() else "RECT"

                    p_w = inst.LookupParameter(param_width) or inst.LookupParameter("Width")
                    p_h = inst.LookupParameter(param_height) or inst.LookupParameter("Height")
                    size = "N/A"
                    if p_w:
                        if shape == "ROUND":
                            size = "Dia {:.0f}mm".format(to_mm(p_w.AsDouble()))
                        elif p_h:
                            size = "{:.0f}x{:.0f}mm".format(to_mm(p_w.AsDouble()), to_mm(p_h.AsDouble()))

                    loc_str = "{:.1f}, {:.1f}, {:.1f}".format(to_mm(mid.X), to_mm(mid.Y), to_mm(mid.Z))

                    # Fetch mark
                    p_mark = inst.LookupParameter(number_param)
                    mark = p_mark.AsString() if p_mark and p_mark.AsString() else "N/A"

                    table_data.append([
                        idx + 1,
                        mark,
                        inst.Id.ToString(),
                        mep_cat_name,
                        "Yes" if moved else "No",
                        "Yes" if resized else "No",
                        size,
                        loc_str
                    ])

                output.print_table(
                    table_data=table_data,
                    title="Updated Wall Openings Table",
                    columns=["No.", "Mark", "Opening ID", "MEP Category", "Moved", "Resized", "New Size", "New Location (X, Y, Z)"]
                )

            if orphaned_openings:
                orphaned_data = []
                for idx, o in enumerate(orphaned_openings):
                    p_mark = o.LookupParameter(number_param)
                    mark = p_mark.AsString() if p_mark and p_mark.AsString() else "N/A"
                    orphaned_data.append([
                        idx + 1,
                        mark,
                        o.Id.ToString(),
                        o.Symbol.Family.Name,
                        o.Symbol.Name
                    ])
                output.print_table(
                    table_data=orphaned_data,
                    title="Orphaned Openings Table (Linked MEP elements deleted/moved)",
                    columns=["No.", "Mark", "Opening ID", "Family Name", "Type Name"]
                )

    except Exception as e:
        t.RollBack()
        forms.alert("Transaction aborted due to critical error: {}".format(e), title="Transaction Error")

if __name__ == "__main__":
    main()
