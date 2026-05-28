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
    Form, FormStartPosition, Label, MessageBox, Panel, TextBox,
    DataGridView, DataGridViewAutoSizeColumnMode, DataGridViewColumn,
    DataGridViewDataErrorContexts,
    DataGridViewComboBoxColumn, DataGridViewSelectionMode, DataGridViewTextBoxColumn
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
PARAM_DIAMETERS = ["Rough Diameter", "Diameter", "Opening_Diameter", "Opening Diameter", "Cut_Diameter"]
PARAM_DEPTHS = ["Thickness", "Opening_Thickness", "Opening Depth", "Wall_Thickness"]
PARAM_SYSTEMS = ["MEP_System"]
PARAM_SIZES = ["MEP_Size"]
PARAM_ELEVATIONS = ["MEP_Elevation"]
PARAM_ROUGH_WIDTHS = ["Rough Width", "Width", "Opening_Width", "Opening Width", "Cut_Width"]
PARAM_ROUGH_HEIGHTS = ["Rough Height", "Height", "Opening_Height", "Opening Height", "Cut_Height"]
PARAM_SILL_HEIGHTS = ["Sill Height", "Default Sill Height", "Sill Height (default)"]

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

def is_valid_solid(solid, min_volume=1e-9):
    """Return True only for Revit solids that can safely be used in geometry calls."""
    if solid is None:
        return False
    try:
        if not solid.IsValidObject:
            return False
    except:
        pass
    try:
        if solid.Volume <= min_volume:
            return False
    except:
        return False
    try:
        if not solid.Faces or solid.Faces.Size == 0:
            return False
    except:
        return False
    return True

def append_valid_solid(solids, solid, transform=None):
    """Append a solid after optional transform, skipping null or invalid geometry."""
    if not is_valid_solid(solid):
        return
    try:
        safe_solid = DB.SolidUtils.CreateTransformed(solid, transform) if transform else solid
    except:
        return
    if is_valid_solid(safe_solid):
        solids.append(safe_solid)

def intersect_solid_with_curve(solid, curve):
    """Safely intersect a solid and curve without letting Revit abort on null solids."""
    if not is_valid_solid(solid) or curve is None:
        return None
    try:
        return solid.IntersectWithCurve(curve, DB.SolidCurveIntersectionOptions())
    except:
        return None

def boolean_intersection_solid(solid_a, solid_b):
    """Safely return the Boolean intersection solid, or None when geometry is unusable."""
    if not is_valid_solid(solid_a) or not is_valid_solid(solid_b):
        return None
    try:
        result = DB.BooleanOperationsUtils.ExecuteBooleanOperation(
            solid_a, solid_b, DB.BooleanOperationsType.Intersect
        )
    except:
        return None
    return result if is_valid_solid(result, min_volume=0.0001) else None

def get_element_solids(elem, transform=None):
    """Extract and merge all valid geometry solids of any element, transformed if in a link."""
    solids = []
    options = DB.Options()
    options.DetailLevel = DB.ViewDetailLevel.Fine
    try:
        geom = elem.get_Geometry(options)
    except:
        return solids
    if geom is None:
        return solids

    for obj in geom:
        if isinstance(obj, DB.Solid):
            append_valid_solid(solids, obj, transform)
        elif isinstance(obj, DB.GeometryInstance):
            try:
                inst_geom = obj.GetInstanceGeometry()
            except:
                inst_geom = None
            if inst_geom is None:
                continue
            for sub_obj in inst_geom:
                if isinstance(sub_obj, DB.Solid):
                    append_valid_solid(solids, sub_obj, transform)
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

def find_parameter(elem, possible_names):
    """Return the first parameter matching any name in the provided list."""
    if not elem:
        return None
    for name in possible_names:
        try:
            p = elem.LookupParameter(name)
            if p:
                return p
        except:
            pass
    return None

def set_parameter_value(param, value):
    """Set a parameter using the right storage type."""
    if not param or param.IsReadOnly:
        return False
    try:
        if param.StorageType == DB.StorageType.Double:
            param.Set(float(value))
        elif param.StorageType == DB.StorageType.Integer:
            param.Set(int(value))
        elif param.StorageType == DB.StorageType.String:
            param.Set(str(value))
        else:
            return False
        return True
    except:
        return False

def get_element_type(elem):
    """Get the Revit element type for an instance when available."""
    try:
        type_id = elem.GetTypeId()
        if type_id and type_id != DB.ElementId.InvalidElementId:
            return doc.GetElement(type_id)
    except:
        pass
    return None

def find_and_set_instance_or_type_parameter(elem, possible_names, value):
    """Set an instance parameter first, then the element type parameter as fallback."""
    if find_and_set_parameter(elem, possible_names, value):
        return True
    elem_type = get_element_type(elem)
    if elem_type:
        return find_and_set_parameter(elem_type, possible_names, value)
    return False

def safe_element_name(elem, fallback=""):
    """Read an element name without relying on IronPython dynamic .Name access."""
    if not elem:
        return fallback
    try:
        name = DB.Element.Name.GetValue(elem)
        if name:
            return name
    except:
        pass
    for bip_name in ["SYMBOL_NAME_PARAM", "ALL_MODEL_TYPE_NAME"]:
        try:
            p = elem.get_Parameter(getattr(DB.BuiltInParameter, bip_name))
            if p and p.AsString():
                return p.AsString()
        except:
            pass
    try:
        name = elem.Name
        if name:
            return name
    except:
        pass
    return fallback

def safe_family_name(symbol_or_family, fallback=""):
    """Read a family name from a Family or FamilySymbol safely."""
    if not symbol_or_family:
        return fallback
    try:
        p = symbol_or_family.get_Parameter(DB.BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
        if p and p.AsString():
            return p.AsString()
    except:
        pass
    try:
        family = symbol_or_family.Family
        name = safe_element_name(family, fallback)
        if name:
            return name
    except:
        pass
    return safe_element_name(symbol_or_family, fallback)

def safe_symbol_name(symbol, fallback=""):
    """Read a family symbol type name safely."""
    return safe_element_name(symbol, fallback)

def safe_symbol_display_name(symbol):
    """Build a stable Family : Type display name."""
    family_name = safe_family_name(symbol, "Unknown Family")
    type_name = safe_symbol_name(symbol, "Unknown Type")
    return "{} : {}".format(family_name, type_name)

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
    name = safe_symbol_display_name(symbol).lower()
    return "ROUND" if any(token in name for token in ["round", "circular", "pipe"]) else "RECT"

def get_first_parameter(elem, possible_names):
    """Find the first parameter from a name fallback list."""
    for name in possible_names:
        p = elem.LookupParameter(name)
        if p:
            return p
    elem_type = get_element_type(elem)
    if elem_type:
        for name in possible_names:
            p = elem_type.LookupParameter(name)
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

def get_sized_type_name(shape, width, height):
    """Build a stable family type name for size-driven window opening families."""
    if shape == "ROUND":
        return "P13 D{:.0f}mm".format(to_mm(max(width, height)))
    return "P13 {:.0f}x{:.0f}mm".format(to_mm(width), to_mm(height))

def set_symbol_opening_size(symbol, shape, width, height):
    """Write type parameters used by the local Window-Round and Window-Square opening families."""
    if shape == "ROUND":
        diameter = max(width, height)
        wrote = find_and_set_parameter(symbol, PARAM_DIAMETERS, diameter)
        if not wrote:
            find_and_set_parameter(symbol, PARAM_ROUGH_WIDTHS, diameter)
            find_and_set_parameter(symbol, PARAM_ROUGH_HEIGHTS, diameter)
        return True

    wrote_w = find_and_set_parameter(symbol, ["Width", "Opening_Width", "Opening Width", "Cut_Width"], width)
    wrote_h = find_and_set_parameter(symbol, ["Height", "Opening_Height", "Opening Height", "Cut_Height"], height)
    if not wrote_w:
        wrote_w = find_and_set_parameter(symbol, PARAM_ROUGH_WIDTHS, width)
    if not wrote_h:
        wrote_h = find_and_set_parameter(symbol, PARAM_ROUGH_HEIGHTS, height)
    return wrote_w or wrote_h

def get_or_create_sized_symbol(base_symbol, shape, width, height):
    """Create or reuse a unique family type for the required opening size."""
    if not base_symbol:
        return None
    type_name = get_sized_type_name(shape, width, height)
    family = base_symbol.Family
    for symbol_id in family.GetFamilySymbolIds():
        symbol = doc.GetElement(symbol_id)
        if symbol and safe_symbol_name(symbol) == type_name:
            set_symbol_opening_size(symbol, shape, width, height)
            if not symbol.IsActive:
                symbol.Activate()
            return symbol

    try:
        symbol = base_symbol.Duplicate(type_name)
    except:
        symbol = base_symbol
    set_symbol_opening_size(symbol, shape, width, height)
    if not symbol.IsActive:
        symbol.Activate()
    return symbol

def calculate_sill_height(midpoint, level, opening_height):
    """Calculate window sill height so the family opening center matches the detected midpoint."""
    if not midpoint or not level:
        return None
    return midpoint.Z - level.Elevation - (opening_height / 2.0)

def get_window_insertion_point(center_point, level):
    """
    Return the insertion point for a wall-hosted Window family.
    Window elevation is controlled by Sill Height, so the insertion point stays on the level plane
    while X/Y remains at the detected MEP center on the wall.
    """
    if not center_point:
        return None
    z_value = level.Elevation if level else center_point.Z
    return DB.XYZ(center_point.X, center_point.Y, z_value)

def set_builtin_double_parameter(elem, bip_name, value):
    """Set a double built-in parameter when it exists and is writable."""
    try:
        bip = getattr(DB.BuiltInParameter, bip_name)
        p = elem.get_Parameter(bip)
        if p and not p.IsReadOnly and p.StorageType == DB.StorageType.Double:
            p.Set(float(value))
            return True
    except:
        pass
    return False

def set_opening_sill_height(opening, level, midpoint, opening_height):
    """Write Sill Height / Default Sill Height for the local window opening families."""
    sill_height = calculate_sill_height(midpoint, level, opening_height)
    if sill_height is None:
        return False

    # Window sill is normally an instance parameter in projects. Use it first so
    # same-size openings at different elevations do not fight over one type value.
    if set_builtin_double_parameter(opening, "INSTANCE_SILL_HEIGHT_PARAM", sill_height):
        return True
    if set_builtin_double_parameter(opening, "INSTANCE_HEAD_HEIGHT_PARAM", sill_height + opening_height):
        return True
    if find_and_set_parameter(opening, PARAM_SILL_HEIGHTS, sill_height):
        return True
    return False

def set_opening_size(opening, shape, width, height, depth, level=None, midpoint=None):
    """Write opening dimensions using the local Window-Round and Window-Square family parameters."""
    wrote_size = False
    if shape == "ROUND":
        diameter = max(width, height)
        wrote_size = find_and_set_instance_or_type_parameter(opening, PARAM_DIAMETERS, diameter)
        wrote_size = find_and_set_instance_or_type_parameter(opening, PARAM_ROUGH_WIDTHS, diameter) or wrote_size
        find_and_set_instance_or_type_parameter(opening, PARAM_ROUGH_HEIGHTS, diameter)
    else:
        wrote_size = find_and_set_instance_or_type_parameter(opening, ["Width", "Opening_Width", "Opening Width", "Cut_Width"], width)
        wrote_size = find_and_set_instance_or_type_parameter(opening, ["Height", "Opening_Height", "Opening Height", "Cut_Height"], height) or wrote_size
        if not wrote_size:
            find_and_set_instance_or_type_parameter(opening, PARAM_ROUGH_WIDTHS, width)
            find_and_set_instance_or_type_parameter(opening, PARAM_ROUGH_HEIGHTS, height)
    wrote_depth = find_and_set_instance_or_type_parameter(opening, PARAM_DEPTHS, depth)
    wrote_sill = set_opening_sill_height(opening, level, midpoint, height) if level and midpoint else False
    return wrote_size or wrote_depth or wrote_sill

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

def align_opening_bbox_center(opening, target_center, wall_dir):
    """
    Move a wall-hosted window along the wall until its actual bounding-box center
    matches the detected MEP center. Some window families use a non-center insertion point.
    """
    if not opening or not target_center or not wall_dir:
        return False
    try:
        doc.Regenerate()
        bbox = opening.get_BoundingBox(None)
        if not bbox:
            return False
        current_center = bbox_center(bbox)
        offset = target_center - current_center
        along_wall = offset.DotProduct(wall_dir)
        move_vector = wall_dir * along_wall
        if move_vector.GetLength() <= 0.001:
            return False
        DB.ElementTransformUtils.MoveElement(doc, opening.Id, move_vector)
        return True
    except:
        return False

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
            if symbol_family_names and safe_family_name(inst.Symbol) not in symbol_family_names:
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
                    names.append(safe_element_name(conn.MEPSystem, "N/A"))
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
        if safe_family_name(fam) == name:
            return fam
    try:
        # Use simple overload (returns bool) and retrieve family object by name from collector
        loaded = doc.LoadFamily(rfa_path)
        if loaded:
            families = DB.FilteredElementCollector(doc).OfClass(DB.Family)
            for fam in families:
                if safe_family_name(fam) == name:
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
                display_name = safe_symbol_display_name(s)
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

def get_category_offset_mm(cat_name, settings):
    """Return clearance in millimeters for a category name."""
    if "Pipe" in cat_name:
        return float(settings.get("offset_pipe", 50.0))
    if "Duct" in cat_name or "MechanicalEquipment" in cat_name:
        return float(settings.get("offset_duct", 50.0))
    if "CableTray" in cat_name:
        return float(settings.get("offset_tray", 50.0))
    if "Conduit" in cat_name:
        return float(settings.get("offset_conduit", 50.0))
    return 50.0

def rounded_mm(value):
    """Round a Revit dimension converted to millimeters for grouping."""
    try:
        return int(round(float(value)))
    except:
        return 0

def get_mep_nominal_size_info(mep_el, mep_dim=None):
    """Return nominal MEP size data used for exact-size family mapping rows."""
    if not mep_el or not mep_el.Category:
        return None
    if mep_dim is None:
        mep_dim = get_mep_dimensions(mep_el)

    cat_name = mep_el.Category.BuiltInCategory.ToString()
    shape = mep_dim.get("shape", "RECT")
    width_mm = rounded_mm(to_mm(mep_dim.get("width", 0.0)))
    height_mm = rounded_mm(to_mm(mep_dim.get("height", 0.0)))
    diameter_mm = rounded_mm(to_mm(mep_dim.get("diameter", 0.0)))

    if shape == "ROUND" and diameter_mm > 0:
        size_mm = diameter_mm
        label = "D{}".format(diameter_mm)
    elif width_mm > 0 and height_mm > 0:
        shape = "RECT"
        size_mm = max(width_mm, height_mm)
        label = "{}x{}".format(width_mm, height_mm)
    else:
        bbox = mep_el.get_BoundingBox(None)
        if not bbox:
            return None
        dims = bbox.Max - bbox.Min
        width_mm = rounded_mm(to_mm(max(abs(dims.X), abs(dims.Y))))
        height_mm = rounded_mm(to_mm(abs(dims.Z)))
        if width_mm <= 0 or height_mm <= 0:
            return None
        shape = "RECT"
        diameter_mm = 0
        size_mm = max(width_mm, height_mm)
        label = "{}x{}".format(width_mm, height_mm)

    return {
        "category": cat_name,
        "mep_shape": shape,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "diameter_mm": diameter_mm,
        "max_size_mm": float(size_mm),
        "mep_size_label": label
    }

def get_recommended_family_name(shape, family_options):
    """Pick a sensible default opening family for a scanned MEP size."""
    preferred_tokens = ["round", "circular"] if shape == "ROUND" else ["square", "rect", "rectangle"]
    for family_name in family_options:
        lower_name = family_name.lower()
        if any(token in lower_name for token in preferred_tokens):
            return family_name
    fallback = "Window-Round Opening" if shape == "ROUND" else "Window-Square Opening"
    return fallback if fallback in family_options else (family_options[0] if family_options else fallback)

def build_scanned_size_rules(mep_items, settings, family_options):
    """Group equal MEP sizes into exact-match rules for fast family mapping."""
    groups = {}
    for mep_el, mep_t, mep_doc in mep_items:
        size_info = get_mep_nominal_size_info(mep_el)
        if not size_info:
            continue
        cat_name = size_info["category"]
        offset_mm = get_category_offset_mm(cat_name, settings)
        shape = size_info["mep_shape"]
        if shape == "ROUND":
            opening_dia = size_info["diameter_mm"] + (2.0 * offset_mm)
            recommended_label = "D{:.0f}".format(opening_dia)
            opening_shape = "ROUND"
            key = (cat_name, shape, size_info["diameter_mm"], 0, 0)
        else:
            opening_w = size_info["width_mm"] + (2.0 * offset_mm)
            opening_h = size_info["height_mm"] + (2.0 * offset_mm)
            recommended_label = "{:.0f}x{:.0f}".format(opening_w, opening_h)
            opening_shape = "RECT"
            key = (cat_name, shape, 0, size_info["width_mm"], size_info["height_mm"])

        if key not in groups:
            groups[key] = {
                "match_mode": "EXACT",
                "max_size_mm": size_info["max_size_mm"],
                "mep_shape": shape,
                "width_mm": float(size_info["width_mm"]),
                "height_mm": float(size_info["height_mm"]),
                "diameter_mm": float(size_info["diameter_mm"]),
                "mep_size_label": size_info["mep_size_label"],
                "recommended_opening_label": recommended_label,
                "count": 0,
                "shape": opening_shape,
                "family_name": get_recommended_family_name(opening_shape, family_options)
            }
        groups[key]["count"] += 1

    rules_by_category = {}
    for key, rule in groups.items():
        category = key[0]
        rules_by_category.setdefault(category, []).append(rule)
    for category, category_rules in rules_by_category.items():
        category_rules.sort(key=lambda rule: (
            rule.get("max_size_mm", 99999.0),
            rule.get("width_mm", 0.0),
            rule.get("height_mm", 0.0)
        ))
    return rules_by_category

def merge_scanned_rules(existing_rules, scanned_rules):
    """Replace old scanned exact rules while preserving manual threshold rules."""
    merged = {}
    all_categories = set(existing_rules.keys()) | set(scanned_rules.keys())
    for category in all_categories:
        manual_rules = []
        for rule in existing_rules.get(category, []):
            if rule.get("match_mode", "THRESHOLD") != "EXACT":
                manual_rules.append(rule)
        merged[category] = scanned_rules.get(category, []) + manual_rules
        merged[category].sort(key=lambda rule: (
            0 if rule.get("match_mode") == "EXACT" else 1,
            rule.get("max_size_mm", 99999.0),
            rule.get("width_mm", 0.0),
            rule.get("height_mm", 0.0)
        ))
    return merged

def rule_matches_exact_size(rule, mep_dim):
    """Check whether a scanned exact-size rule matches the current MEP element."""
    if rule.get("match_mode", "THRESHOLD") != "EXACT":
        return False
    size_info = {
        "mep_shape": mep_dim.get("shape", "RECT"),
        "width_mm": rounded_mm(to_mm(mep_dim.get("width", 0.0))),
        "height_mm": rounded_mm(to_mm(mep_dim.get("height", 0.0))),
        "diameter_mm": rounded_mm(to_mm(mep_dim.get("diameter", 0.0)))
    }
    if size_info["mep_shape"] == "ROUND":
        return (
            rule.get("mep_shape") == "ROUND" and
            rounded_mm(rule.get("diameter_mm", 0.0)) == size_info["diameter_mm"]
        )
    return (
        rule.get("mep_shape") == "RECT" and
        rounded_mm(rule.get("width_mm", 0.0)) == size_info["width_mm"] and
        rounded_mm(rule.get("height_mm", 0.0)) == size_info["height_mm"]
    )

def get_symbol_from_rule(rule, family_map, ui_round, ui_rect):
    """Resolve a rule family name to a project family symbol."""
    shape = rule.get("shape", "RECT")
    fam_name = rule.get("family_name")
    if fam_name:
        for display_name, symbol in family_map.items():
            if display_name.split(" : ")[0] == fam_name:
                return symbol, shape
    return (ui_round if shape == "ROUND" else ui_rect), shape

def resolve_opening_family(mep_el, mep_dim, rules, family_map, ui_round, ui_rect):
    """Looks up mapping rules based on element category and dimension."""
    if not mep_el.Category:
        return ui_rect, "RECT"

    cat_name = mep_el.Category.BuiltInCategory.ToString()
    rules_list = rules.get(cat_name, [])

    for rule in rules_list:
        if rule_matches_exact_size(rule, mep_dim):
            return get_symbol_from_rule(rule, family_map, ui_round, ui_rect)

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
        if rule.get("match_mode", "THRESHOLD") == "EXACT":
            continue
        if size_mm <= rule.get("max_size_mm", 99999.0):
            return get_symbol_from_rule(rule, family_map, ui_round, ui_rect)

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

def point_inside_box(point, bbox, tolerance=0.5):
    """Check whether a point is inside a bounding box with tolerance."""
    if not point or not bbox:
        return False
    return (
        bbox.Min.X - tolerance <= point.X <= bbox.Max.X + tolerance and
        bbox.Min.Y - tolerance <= point.Y <= bbox.Max.Y + tolerance and
        bbox.Min.Z - tolerance <= point.Z <= bbox.Max.Z + tolerance
    )

def get_box_intersection(boxA, boxB):
    """Return the overlapping bounding box, or None if there is no overlap."""
    if not boxes_overlap(boxA, boxB, tolerance=0.0):
        return None
    bbox = DB.BoundingBoxXYZ()
    bbox.Min = DB.XYZ(
        max(boxA.Min.X, boxB.Min.X),
        max(boxA.Min.Y, boxB.Min.Y),
        max(boxA.Min.Z, boxB.Min.Z)
    )
    bbox.Max = DB.XYZ(
        min(boxA.Max.X, boxB.Max.X),
        min(boxA.Max.Y, boxB.Max.Y),
        min(boxA.Max.Z, boxB.Max.Z)
    )
    return bbox

def get_curve_endpoints(curve):
    """Return safe start and end points for a Revit curve."""
    try:
        return curve.GetEndPoint(0), curve.GetEndPoint(1)
    except:
        return None, None

def estimate_curve_wall_plane_hit(mep_curve, wall_el, wall_t, wall_dir, wall_bbox, tolerance=1.0):
    """
    Fallback hit test: intersect the MEP centerline chord with the wall center plane.
    This catches common cases where Revit solid intersection misses due to linked geometry,
    view detail, or small tolerance differences.
    """
    start, end = get_curve_endpoints(mep_curve)
    if not start or not end:
        return None
    segment = end - start
    length = segment.GetLength()
    if length <= 0.0001:
        return None

    mep_dir = segment.Normalize()
    wall_normal = DB.XYZ(wall_dir.Y, -wall_dir.X, 0.0)
    if wall_normal.GetLength() <= 0.0001:
        return None
    wall_normal = wall_normal.Normalize()

    wall_curve = None
    try:
        if isinstance(wall_el.Location, DB.LocationCurve):
            wall_curve = wall_el.Location.Curve
            if wall_t:
                wall_curve = wall_curve.CreateTransformed(wall_t)
    except:
        wall_curve = None
    if not wall_curve:
        return None

    wall_origin = wall_curve.Evaluate(0.5, True)
    denom = mep_dir.DotProduct(wall_normal)
    if abs(denom) < 0.01:
        return None

    distance = (wall_origin - start).DotProduct(wall_normal) / denom
    if distance < -tolerance or distance > length + tolerance:
        return None

    hit_point = start + mep_dir * distance
    if not point_inside_box(hit_point, wall_bbox, tolerance):
        return None
    return hit_point

def bbox_center(bbox):
    """Return the center of a bounding box."""
    return bbox.Min + (bbox.Max - bbox.Min) * 0.5

def estimate_wall_thickness(wall_el, wall_bbox):
    """Return a reasonable wall thickness fallback in internal units."""
    if hasattr(wall_el, 'Width') and wall_el.Width > 0:
        return wall_el.Width
    if wall_bbox:
        dims = wall_bbox.Max - wall_bbox.Min
        candidates = [abs(dims.X), abs(dims.Y)]
        candidates = [v for v in candidates if v > 0.001]
        if candidates:
            return min(candidates)
    return to_feet(200.0)

def add_diag(diag, key):
    """Increment a diagnostic counter."""
    diag[key] = diag.get(key, 0) + 1

def print_diagnostics(diag):
    """Print a concise diagnostic summary when no openings are placed."""
    if not diag:
        return
    output.print_md("### Placement Diagnostics")
    rows = []
    labels = {
        "walls_no_bbox": "Walls skipped: no bounding box",
        "walls_no_solids": "Walls skipped: no usable solid geometry",
        "mep_no_bbox": "MEP skipped: no bounding box",
        "bbox_candidates": "MEP-wall bounding-box candidates",
        "shape_filtered": "Candidates skipped by selected opening shape",
        "no_symbol": "Candidates skipped: opening family type not found",
        "no_precise_hit": "Candidates skipped: no centerline/solid/bbox hit",
        "no_projection": "Candidates skipped: projection size failed",
        "duplicates": "Candidates skipped: opening already tracked",
        "no_level": "Candidates skipped: no host level found",
        "placement_failed": "Candidates skipped: family placement failed"
    }
    for key in sorted(labels.keys()):
        if diag.get(key, 0):
            rows.append([labels[key], diag[key]])
    if rows:
        output.print_table(table_data=rows, title="Why no openings were placed", columns=["Reason", "Count"])

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
            loaded_symbols.append(safe_symbol_display_name(s))
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
        self.Size = Size(1380, 840)
        self.StartPosition = FormStartPosition.CenterScreen
        self.Font = Font("Segoe UI", 9)
        self.BackColor = Color.FromArgb(242, 244, 247)
        self.settings = dict(settings)
        self.rules = load_rules()
        self.action = "cancel"
        self.inputs = {}
        self.profile_round = None
        self.profile_rect = None
        self.enable_numbering = None
        self.numbering_controls = []
        self.rule_grid = None
        self.bulk_shape = None
        self.bulk_family = None
        self._bulk_updating = False
        self.tracked_rule_categories = [
            "OST_PipeCurves", "OST_DuctCurves", "OST_CableTray", "OST_Conduit",
            "OST_PipeFitting", "OST_PipeAccessory", "OST_DuctFitting", "OST_DuctAccessory",
            "OST_MechanicalEquipment"
        ]
        self.rule_family_options = self._get_rule_family_options()
        self._build_ui()
        self._load_rule_rows()
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

    def _style_grid(self, grid):
        grid.AllowUserToAddRows = False
        grid.AllowUserToDeleteRows = False
        grid.MultiSelect = True
        grid.RowHeadersVisible = False
        grid.SelectionMode = DataGridViewSelectionMode.FullRowSelect
        grid.BackgroundColor = Color.White
        grid.BorderStyle = getattr(BorderStyle, "None")
        grid.EnableHeadersVisualStyles = False
        grid.GridColor = Color.FromArgb(235, 235, 235)
        grid.ColumnHeadersDefaultCellStyle.BackColor = Color.FromArgb(240, 240, 240)
        grid.ColumnHeadersDefaultCellStyle.ForeColor = Color.FromArgb(60, 60, 60)
        grid.ColumnHeadersDefaultCellStyle.Font = Font("Segoe UI", 9, FontStyle.Bold)
        grid.ColumnHeadersHeight = 32
        grid.DefaultCellStyle.SelectionBackColor = Color.FromArgb(41, 128, 185)
        grid.DefaultCellStyle.SelectionForeColor = Color.White
        grid.AlternatingRowsDefaultCellStyle.BackColor = Color.FromArgb(250, 250, 250)

    def _get_rule_family_options(self):
        options = set()
        for rfa in get_local_rfa_files():
            options.add(rfa.replace(".rfa", ""))
        try:
            symbols = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol)
            for symbol in symbols:
                if symbol.Category and symbol.Category.BuiltInCategory in [DB.BuiltInCategory.OST_Windows, DB.BuiltInCategory.OST_GenericModel]:
                    family_name = safe_family_name(symbol)
                    if family_name:
                        options.add(family_name)
        except:
            pass
        if not options:
            options.add("Window-Round Opening")
            options.add("Window-Square Opening")
        return sorted(list(options))

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
        header.Size = Size(1328, 64)
        header.BackColor = Color.FromArgb(47, 54, 64)
        self.Controls.Add(header)
        title = self._create_label("WALL OPENING", Point(18, 12), Size(360, 24), header, True)
        title.ForeColor = Color.White
        subtitle = self._create_label("Create and update custom wall openings from MEP-wall intersections.", Point(18, 36), Size(680, 18), header, False)
        subtitle.ForeColor = Color.FromArgb(220, 225, 230)

        run_panel = self._create_panel("Run setup", Point(12, 88), Size(300, 630))
        self._create_hint("Choose what to process, then run. Update mode resizes and recenters existing tracked openings.", Point(16, 42), Size(286, 48), run_panel)
        mode = self._add_combo(run_panel, "mode", "Action", ["Create Mode", "Update Mode"], 16, 104, 266)
        mode.SelectedIndexChanged += self._mode_changed
        self._add_combo(run_panel, "scope", "Where to search", ["Active View", "Selected MEP Elements", "Entire Model"], 16, 164, 266)

        self._create_label("Opening types", Point(16, 224), Size(260, 20), run_panel, True)
        profile_value = str(self.settings.get("profiles", "Both Round & Rectangular"))
        self.profile_round = self._add_checkbox(run_panel, "Round openings", 16, 252, "Round" in profile_value or "Both" in profile_value, 260)
        self.profile_rect = self._add_checkbox(run_panel, "Rectangular openings", 16, 284, "Rectangular" in profile_value or "Both" in profile_value, 260)
        self._add_combo(run_panel, "source", "Opening family source", ["Script Folder RFAs", "Already Loaded Families in Project"], 16, 330, 266)
        self._create_hint("Use Scan MEP Sizes to build exact mapping rows from Pipe, Conduit, Duct, and Tray sizes.", Point(16, 390), Size(266, 52), run_panel)

        self._create_label("Opening marks", Point(16, 452), Size(260, 20), run_panel, True)
        self.enable_numbering = self._add_checkbox(run_panel, "Number openings by category", 16, 480, str(self.settings.get("enable_numbering", "No")) == "Yes", 270)
        self.enable_numbering.CheckedChanged += self._numbering_changed
        self.numbering_controls.append(self._add_textbox(run_panel, "number_param", "Write mark to parameter", 16, 514, 266))
        self.numbering_controls.append(self._add_textbox(run_panel, "prefix_pipe", "Pipe prefix", 16, 560, 136))
        self.numbering_controls.append(self._add_textbox(run_panel, "prefix_duct", "Duct prefix", 158, 560, 124))

        settings_panel = self._create_panel("Opening settings", Point(324, 88), Size(300, 630))
        self._create_label("Clearance around MEP", Point(16, 42), Size(260, 20), settings_panel, True)
        self._create_hint("Clearance is added on both sides of the detected MEP size before writing opening dimensions.", Point(16, 68), Size(266, 46), settings_panel)
        self._add_textbox(settings_panel, "offset_pipe", "Pipe (mm)", 16, 122, 126)
        self._add_textbox(settings_panel, "offset_duct", "Duct (mm)", 156, 122, 126)
        self._add_textbox(settings_panel, "offset_tray", "Cable Tray (mm)", 16, 184, 126)
        self._add_textbox(settings_panel, "offset_conduit", "Conduit (mm)", 156, 184, 126)

        self._create_label("Family parameter mapping", Point(16, 260), Size(260, 20), settings_panel, True)
        self._create_hint("Change these only if the opening families use different parameter names.", Point(16, 286), Size(266, 36), settings_panel)
        self._add_textbox(settings_panel, "param_width", "Width", 16, 336, 126)
        self._add_textbox(settings_panel, "param_height", "Height", 156, 336, 126)
        self._add_textbox(settings_panel, "param_depth", "Wall thickness", 16, 398, 126)
        self._add_textbox(settings_panel, "param_system", "MEP system", 156, 398, 126)

        self._create_label("Metadata parameters", Point(16, 474), Size(260, 20), settings_panel, True)
        self._add_textbox(settings_panel, "param_size", "MEP size", 16, 506, 126)
        self._add_textbox(settings_panel, "param_elevation", "Elevation", 156, 506, 126)
        self.numbering_controls.append(self._add_textbox(settings_panel, "prefix_tray", "Cable tray prefix", 16, 560, 126))
        self.numbering_controls.append(self._add_textbox(settings_panel, "prefix_conduit", "Conduit prefix", 156, 560, 126))

        rules_panel = self._create_panel("MEP size rules and family mapping", Point(636, 88), Size(704, 630))
        self._create_hint("Scan groups equal MEP sizes into one exact row. Select multiple rows, then apply Shape or Family once.", Point(16, 42), Size(672, 34), rules_panel)
        self._create_rules_grid(rules_panel)

        self.btn_scan_sizes = self._create_button("Scan MEP Sizes", Point(16, 520), Size(132, 30), self._scan_mep_sizes_clicked, Color.FromArgb(39, 174, 96))
        self.btn_add_rule = self._create_button("Add Rule", Point(160, 520), Size(90, 30), self._add_rule_clicked, Color.FromArgb(41, 128, 185))
        self.btn_delete_rule = self._create_button("Delete Rule", Point(262, 520), Size(96, 30), self._delete_rule_clicked, Color.FromArgb(192, 57, 43))
        rules_panel.Controls.Add(self.btn_scan_sizes)
        rules_panel.Controls.Add(self.btn_add_rule)
        rules_panel.Controls.Add(self.btn_delete_rule)

        self._create_label("Batch edit selected rows", Point(16, 562), Size(180, 18), rules_panel, True)
        self.bulk_shape = ComboBox()
        self.bulk_shape.Location = Point(200, 558)
        self.bulk_shape.Size = Size(86, 25)
        self.bulk_shape.DropDownStyle = ComboBoxStyle.DropDownList
        self.bulk_shape.Items.Add("ROUND")
        self.bulk_shape.Items.Add("RECT")
        self.bulk_shape.SelectedIndex = 0
        rules_panel.Controls.Add(self.bulk_shape)

        self.bulk_family = ComboBox()
        self.bulk_family.Location = Point(296, 558)
        self.bulk_family.Size = Size(246, 25)
        self.bulk_family.DropDownStyle = ComboBoxStyle.DropDownList
        for family_name in self.rule_family_options:
            self.bulk_family.Items.Add(family_name)
        if self.bulk_family.Items.Count:
            self.bulk_family.SelectedIndex = 0
        rules_panel.Controls.Add(self.bulk_family)

        self.btn_apply_selected = self._create_button("Apply", Point(554, 556), Size(80, 30), self._apply_selected_clicked, Color.FromArgb(52, 73, 94))
        rules_panel.Controls.Add(self.btn_apply_selected)

        self.btn_run = self._create_button("Create Openings", Point(12, 744), Size(220, 36), self._run_clicked, Color.FromArgb(39, 174, 96))
        self.btn_cancel = self._create_button("Cancel", Point(1200, 744), Size(140, 36), self._cancel_clicked, Color.FromArgb(127, 140, 141))
        self.Controls.Add(self.btn_run)
        self.Controls.Add(self.btn_cancel)

    def _create_rules_grid(self, parent):
        self.rule_grid = DataGridView()
        self.rule_grid.Location = Point(12, 84)
        self.rule_grid.Size = Size(parent.Size.Width - 24, 424)
        self._style_grid(self.rule_grid)
        self.rule_grid.CurrentCellDirtyStateChanged += self._rule_grid_dirty_state_changed
        self.rule_grid.CellValueChanged += self._rule_grid_cell_value_changed
        self.rule_grid.DataError += self._rule_grid_data_error
        parent.Controls.Add(self.rule_grid)

        category_col = DataGridViewComboBoxColumn()
        category_col.HeaderText = "MEP Category"
        category_col.Name = "Category"
        category_col.Width = 128
        for category in self.tracked_rule_categories:
            category_col.Items.Add(category)

        mep_size_col = DataGridViewTextBoxColumn()
        mep_size_col.HeaderText = "MEP Size"
        mep_size_col.Name = "MEPSize"
        mep_size_col.Width = 88
        mep_size_col.ReadOnly = True

        recommended_col = DataGridViewTextBoxColumn()
        recommended_col.HeaderText = "Opening"
        recommended_col.Name = "RecommendedOpening"
        recommended_col.Width = 96
        recommended_col.ReadOnly = True

        count_col = DataGridViewTextBoxColumn()
        count_col.HeaderText = "Qty"
        count_col.Name = "Count"
        count_col.Width = 44
        count_col.ReadOnly = True

        mode_col = DataGridViewTextBoxColumn()
        mode_col.HeaderText = "Match"
        mode_col.Name = "MatchMode"
        mode_col.Width = 70
        mode_col.ReadOnly = True

        max_col = DataGridViewTextBoxColumn()
        max_col.HeaderText = "Max Size (mm)"
        max_col.Name = "MaxSize"
        max_col.Width = 86

        shape_col = DataGridViewComboBoxColumn()
        shape_col.HeaderText = "Shape"
        shape_col.Name = "Shape"
        shape_col.Width = 74
        shape_col.Items.Add("ROUND")
        shape_col.Items.Add("RECT")

        family_col = DataGridViewComboBoxColumn()
        family_col.HeaderText = "Opening Family"
        family_col.Name = "FamilyName"
        family_col.AutoSizeMode = DataGridViewAutoSizeColumnMode.Fill
        for family_name in self.rule_family_options:
            family_col.Items.Add(family_name)

        self.rule_grid.Columns.Add(category_col)
        self.rule_grid.Columns.Add(mep_size_col)
        self.rule_grid.Columns.Add(recommended_col)
        self.rule_grid.Columns.Add(count_col)
        self.rule_grid.Columns.Add(mode_col)
        self.rule_grid.Columns.Add(max_col)
        self.rule_grid.Columns.Add(shape_col)
        self.rule_grid.Columns.Add(family_col)

        for hidden_name in ["MEPShape", "MEPWidth", "MEPHeight", "MEPDiameter"]:
            hidden_col = DataGridViewTextBoxColumn()
            hidden_col.Name = hidden_name
            hidden_col.Visible = False
            self.rule_grid.Columns.Add(hidden_col)

    def _load_rule_rows(self):
        if not self.rule_grid:
            return
        self.rule_grid.Rows.Clear()
        for category in self.tracked_rule_categories:
            for rule in self.rules.get(category, []):
                family_name = rule.get("family_name", "")
                self._ensure_family_option(family_name)
                max_size = rule.get("max_size_mm", 99999.0)
                max_text = "99999" if max_size >= 99999.0 else "{:.0f}".format(max_size)
                match_mode = rule.get("match_mode", "THRESHOLD")
                mep_size = rule.get("mep_size_label", "Any <= max") if match_mode == "EXACT" else "Any <= max"
                recommended = rule.get("recommended_opening_label", "")
                count_text = str(rule.get("count", "")) if match_mode == "EXACT" else ""
                row_index = self.rule_grid.Rows.Add(
                    category,
                    mep_size,
                    recommended,
                    count_text,
                    match_mode,
                    max_text,
                    rule.get("shape", "RECT"),
                    family_name,
                    rule.get("mep_shape", ""),
                    str(rule.get("width_mm", "")),
                    str(rule.get("height_mm", "")),
                    str(rule.get("diameter_mm", ""))
                )
                if match_mode == "EXACT":
                    self.rule_grid.Rows[row_index].DefaultCellStyle.BackColor = Color.FromArgb(245, 251, 247)

    def _ensure_family_option(self, family_name):
        if not family_name or family_name in self.rule_family_options:
            return
        self.rule_family_options.append(family_name)
        self.rule_family_options = sorted(list(set(self.rule_family_options)))
        if self.rule_grid:
            try:
                family_col = self.rule_grid.Columns["FamilyName"]
                if family_col and not family_col.Items.Contains(family_name):
                    family_col.Items.Add(family_name)
            except:
                pass
        if self.bulk_family:
            try:
                if not self.bulk_family.Items.Contains(family_name):
                    self.bulk_family.Items.Add(family_name)
            except:
                pass

    def _add_rule_clicked(self, sender, args):
        if not self.rule_grid:
            return
        family_name = "Window-Square Opening"
        if family_name not in self.rule_family_options and self.rule_family_options:
            family_name = self.rule_family_options[0]
        self.rule_grid.Rows.Add("OST_PipeCurves", "Any <= max", "", "", "THRESHOLD", "99999", "RECT", family_name, "", "", "", "")

    def _delete_rule_clicked(self, sender, args):
        if not self.rule_grid or self.rule_grid.SelectedRows.Count == 0:
            return
        rows_to_remove = []
        for row in self.rule_grid.SelectedRows:
            if not row.IsNewRow:
                rows_to_remove.append(row)
        for row in rows_to_remove:
            self.rule_grid.Rows.Remove(row)

    def _rule_grid_dirty_state_changed(self, sender, args):
        try:
            if self.rule_grid.IsCurrentCellDirty:
                self.rule_grid.CommitEdit(DataGridViewDataErrorContexts.Commit)
        except:
            pass

    def _rule_grid_cell_value_changed(self, sender, args):
        if self._bulk_updating or args.RowIndex < 0 or args.ColumnIndex < 0:
            return
        column_name = self.rule_grid.Columns[args.ColumnIndex].Name
        if column_name not in ["Shape", "FamilyName"]:
            return
        try:
            value = self.rule_grid.Rows[args.RowIndex].Cells[column_name].Value
            if not value or self.rule_grid.SelectedRows.Count <= 1:
                return
            self._bulk_updating = True
            for row in self.rule_grid.SelectedRows:
                if not row.IsNewRow:
                    row.Cells[column_name].Value = value
        finally:
            self._bulk_updating = False

    def _rule_grid_data_error(self, sender, args):
        args.ThrowException = False

    def _get_current_scan_settings(self):
        scan_settings = dict(self.settings)
        for key in ["offset_pipe", "offset_duct", "offset_tray", "offset_conduit"]:
            control = self.inputs.get(key)
            value = control.Text if control else scan_settings.get(key, 50.0)
            try:
                parsed = float(value)
                if parsed < 0:
                    raise ValueError()
                scan_settings[key] = parsed
            except:
                MessageBox.Show("Clearance values must be zero or positive numbers before scanning.", "Invalid Clearance")
                return None
        return scan_settings

    def _get_current_scope_key(self):
        scope_control = self.inputs.get("scope")
        scope_text = str(scope_control.SelectedItem) if scope_control and scope_control.SelectedItem else str(self.settings.get("scope", "Active View"))
        return "SELECTION" if "Selected" in scope_text else ("VIEW" if "View" in scope_text else "MODEL")

    def _scan_mep_sizes_clicked(self, sender, args):
        scan_settings = self._get_current_scan_settings()
        if scan_settings is None:
            return
        current_rules = self._collect_rules()
        if current_rules is None:
            return
        try:
            mep_items, wall_items = collect_elements(self._get_current_scope_key())
            scanned_rules = build_scanned_size_rules(mep_items, scan_settings, self.rule_family_options)
        except Exception as ex:
            MessageBox.Show("Failed to scan MEP sizes: {}".format(ex), "Scan Failed")
            return
        scanned_count = sum(len(category_rules) for category_rules in scanned_rules.values())
        if scanned_count == 0:
            MessageBox.Show("No measurable MEP sizes were found in the selected search scope.", "Scan MEP Sizes")
            return
        self.rules = merge_scanned_rules(current_rules, scanned_rules)
        self._load_rule_rows()
        MessageBox.Show(
            "Scanned {} MEP elements and created {} grouped size rows.".format(len(mep_items), scanned_count),
            "Scan MEP Sizes"
        )

    def _apply_selected_clicked(self, sender, args):
        if not self.rule_grid or self.rule_grid.SelectedRows.Count == 0:
            MessageBox.Show("Select one or more rows to update.", "Batch Edit")
            return
        shape_value = self.bulk_shape.SelectedItem if self.bulk_shape else None
        family_value = self.bulk_family.SelectedItem if self.bulk_family else None
        self._bulk_updating = True
        try:
            for row in self.rule_grid.SelectedRows:
                if row.IsNewRow:
                    continue
                if shape_value:
                    row.Cells["Shape"].Value = str(shape_value)
                if family_value:
                    row.Cells["FamilyName"].Value = str(family_value)
        finally:
            self._bulk_updating = False

    def _collect_rules(self):
        if not self.rule_grid:
            return self.rules
        self.rule_grid.EndEdit()
        new_rules = {}
        for category in self.tracked_rule_categories:
            new_rules[category] = []

        for row in self.rule_grid.Rows:
            if row.IsNewRow:
                continue
            category = row.Cells["Category"].Value
            max_size = row.Cells["MaxSize"].Value
            shape = row.Cells["Shape"].Value
            family_name = row.Cells["FamilyName"].Value
            match_mode = row.Cells["MatchMode"].Value
            category = "" if category is None else str(category)
            max_size = "" if max_size is None else str(max_size)
            shape = "" if shape is None else str(shape)
            family_name = "" if family_name is None else str(family_name)
            match_mode = "THRESHOLD" if match_mode is None else str(match_mode)

            if not category or category not in self.tracked_rule_categories:
                MessageBox.Show("Every size rule must have a valid MEP category.", "Invalid Size Rule")
                return None
            try:
                max_value = float(max_size)
                if max_value <= 0:
                    raise ValueError()
            except:
                MessageBox.Show("Max Size must be a positive number. Use 99999 for unlimited.", "Invalid Size Rule")
                return None
            if shape not in ["ROUND", "RECT"]:
                MessageBox.Show("Opening Shape must be ROUND or RECT.", "Invalid Size Rule")
                return None
            if not family_name:
                MessageBox.Show("Every size rule must have an opening family.", "Invalid Size Rule")
                return None

            rule_data = {
                "max_size_mm": max_value,
                "shape": shape,
                "family_name": family_name
            }
            if match_mode == "EXACT":
                rule_data["match_mode"] = "EXACT"
                rule_data["mep_size_label"] = str(row.Cells["MEPSize"].Value or "")
                rule_data["recommended_opening_label"] = str(row.Cells["RecommendedOpening"].Value or "")
                try:
                    rule_data["count"] = int(str(row.Cells["Count"].Value or "0"))
                except:
                    rule_data["count"] = 0
                rule_data["mep_shape"] = str(row.Cells["MEPShape"].Value or "")
                try:
                    rule_data["width_mm"] = float(str(row.Cells["MEPWidth"].Value or "0"))
                    rule_data["height_mm"] = float(str(row.Cells["MEPHeight"].Value or "0"))
                    rule_data["diameter_mm"] = float(str(row.Cells["MEPDiameter"].Value or "0"))
                except:
                    MessageBox.Show("Scanned exact-size rule data is invalid. Scan MEP Sizes again.", "Invalid Size Rule")
                    return None

            new_rules.setdefault(category, []).append(rule_data)

        for category, category_rules in new_rules.items():
            category_rules.sort(key=lambda rule: (
                0 if rule.get("match_mode") == "EXACT" else 1,
                rule.get("max_size_mm", 99999.0),
                rule.get("width_mm", 0.0),
                rule.get("height_mm", 0.0)
            ))
        return new_rules

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
        new_rules = self._collect_rules()
        if new_rules is None:
            return None
        self.rules = new_rules
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
        save_rules(self.rules)
        self.action = "run"
        self.DialogResult = DialogResult.OK
        self.Close()

    def _rules_clicked(self, sender, args):
        collected = self._collect_settings()
        if collected is not None:
            self.settings = collected
            save_rules(self.rules)
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

    # Configure inputs using settings table
    settings = configure_settings_table()
    rules = load_rules()

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
            diag = {}

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
                opening_family_names.add(safe_family_name(round_symbol))
            if rect_symbol:
                opening_family_names.add(safe_family_name(rect_symbol))
            existing_signatures = collect_tracked_opening_signatures(opening_family_names)

            # Bounding box filter optimization for large models
            for wall_el, wall_t, wall_doc in wall_items:
                wall_bbox = wall_el.get_BoundingBox(None)
                if not wall_bbox:
                    add_diag(diag, "walls_no_bbox")
                    continue

                # Get wall solids and direction
                wall_solids = get_wall_solids(wall_el, wall_t)
                wall_dir = get_wall_direction(wall_el, wall_t)

                # Transform wall bbox if in link
                wall_bbox = transform_bounding_box(wall_bbox, wall_t)
                if not wall_solids:
                    add_diag(diag, "walls_no_solids")

                # Filter candidates by Bounding Box pre-filter
                candidates = []
                for mep_el, mep_t, mep_doc in mep_items:
                    # Prevent self-intersections
                    if mep_el.Id == wall_el.Id and mep_doc == wall_doc:
                        continue

                    mep_bbox = mep_el.get_BoundingBox(None)
                    if not mep_bbox:
                        add_diag(diag, "mep_no_bbox")
                        continue

                    mep_bbox = transform_bounding_box(mep_bbox, mep_t)

                    # Check overlap
                    if boxes_overlap(wall_bbox, mep_bbox, tolerance=1.0):
                        candidates.append((mep_el, mep_t, mep_bbox))
                        add_diag(diag, "bbox_candidates")

                # Perform precise geometric checks on candidates
                for mep_el, mep_t, mep_bbox in candidates:
                    mep_cat = mep_el.Category.BuiltInCategory
                    mep_dim = get_mep_dimensions(mep_el)

                    # Resolve symbol using mapping rules JSON
                    symbol, shape = resolve_opening_family(mep_el, mep_dim, rules, family_map, round_symbol, rect_symbol)

                    # Filter based on shape selection
                    if shape == 'ROUND' and not place_round:
                        add_diag(diag, "shape_filtered")
                        continue
                    if shape == 'RECT' and not place_rect:
                        add_diag(diag, "shape_filtered")
                        continue
                    if not symbol:
                        add_diag(diag, "no_symbol")
                        continue

                    offset_ft = offsets.get(mep_cat, to_feet(50.0))
                    midpoint = None
                    opening_w = 0.0
                    opening_h = 0.0
                    wall_thickness = estimate_wall_thickness(wall_el, wall_bbox)

                    # Curve-based elements (Pipes, Ducts, Trays, Conduits)
                    mep_curve = get_transformed_curve(mep_el, mep_t)
                    if mep_curve:
                        mep_dir = mep_curve.ComputeDerivatives(0.5, True).BasisX.Normalize()

                        intersect_segment = None
                        for solid in wall_solids:
                            res = intersect_solid_with_curve(solid, mep_curve)
                            if res and res.SegmentCount > 0:
                                intersect_segment = res.GetCurveSegment(0)
                                break

                        if intersect_segment:
                            midpoint = intersect_segment.Evaluate(0.5, True)
                            wall_thickness = estimate_wall_thickness(wall_el, wall_bbox)
                        else:
                            midpoint = estimate_curve_wall_plane_hit(mep_curve, wall_el, wall_t, wall_dir, wall_bbox, tolerance=1.0)
                        if not midpoint:
                            add_diag(diag, "no_precise_hit")
                            continue
                        coord_key = (round(midpoint.X, 2), round(midpoint.Y, 2), round(midpoint.Z, 2))
                        if coord_key in placed_keys:
                            add_diag(diag, "duplicates")
                            continue
                        if (mep_el.UniqueId, wall_el.UniqueId, coord_key) in existing_signatures:
                            add_diag(diag, "duplicates")
                            continue

                        projected_dims = calculate_projection_size(mep_dim, mep_dir, wall_dir, offset_ft)
                        if not projected_dims:
                            add_diag(diag, "no_projection")
                            continue
                        opening_w, opening_h = projected_dims

                    # Solid-based elements (Fittings, Accessories, Mechanical Equipment)
                    else:
                        mep_solids = get_element_solids(mep_el, mep_t)

                        intersect_solid = None
                        for s_mep in mep_solids:
                            for s_wall in wall_solids:
                                res_solid = boolean_intersection_solid(s_mep, s_wall)
                                if res_solid:
                                    intersect_solid = res_solid
                                    break
                            if intersect_solid:
                                break

                        if intersect_solid:
                            # Centroid of overlapping region
                            bbox_intersect = intersect_solid.GetBoundingBox()
                            midpoint = bbox_center(bbox_intersect)
                        else:
                            bbox_intersect = get_box_intersection(mep_bbox, wall_bbox)
                            if bbox_intersect:
                                midpoint = bbox_center(bbox_intersect)

                        if not midpoint:
                            add_diag(diag, "no_precise_hit")
                            continue

                        coord_key = (round(midpoint.X, 2), round(midpoint.Y, 2), round(midpoint.Z, 2))
                        if coord_key in placed_keys:
                            add_diag(diag, "duplicates")
                            continue
                        if (mep_el.UniqueId, wall_el.UniqueId, coord_key) in existing_signatures:
                            add_diag(diag, "duplicates")
                            continue

                        # Get overlapping vertices and project them
                        pts = []
                        if intersect_solid:
                            for face in intersect_solid.Faces:
                                for loop in face.EdgeLoops:
                                    for edge in loop:
                                        pts.append(edge.Evaluate(0.0))
                                        pts.append(edge.Evaluate(1.0))
                        else:
                            pts = [
                                DB.XYZ(bbox_intersect.Min.X, bbox_intersect.Min.Y, bbox_intersect.Min.Z),
                                DB.XYZ(bbox_intersect.Min.X, bbox_intersect.Min.Y, bbox_intersect.Max.Z),
                                DB.XYZ(bbox_intersect.Min.X, bbox_intersect.Max.Y, bbox_intersect.Min.Z),
                                DB.XYZ(bbox_intersect.Min.X, bbox_intersect.Max.Y, bbox_intersect.Max.Z),
                                DB.XYZ(bbox_intersect.Max.X, bbox_intersect.Min.Y, bbox_intersect.Min.Z),
                                DB.XYZ(bbox_intersect.Max.X, bbox_intersect.Min.Y, bbox_intersect.Max.Z),
                                DB.XYZ(bbox_intersect.Max.X, bbox_intersect.Max.Y, bbox_intersect.Min.Z),
                                DB.XYZ(bbox_intersect.Max.X, bbox_intersect.Max.Y, bbox_intersect.Max.Z)
                            ]

                        x_coords = [p.DotProduct(wall_dir) for p in pts]
                        y_coords = [p.DotProduct(DB.XYZ.BasisZ) for p in pts]

                        opening_w = (max(x_coords) - min(x_coords)) + 2.0 * offset_ft
                        opening_h = (max(y_coords) - min(y_coords)) + 2.0 * offset_ft
                        wall_thickness = estimate_wall_thickness(wall_el, wall_bbox)

                    # Place instance
                    lvl = None
                    if wall_el.Document == doc:
                        lvl_id = wall_el.LevelId
                        if lvl_id != DB.ElementId.InvalidElementId:
                            lvl = doc.GetElement(lvl_id)
                    if not lvl:
                        lvl = get_closest_level(doc, midpoint.Z)
                    if not lvl:
                        add_diag(diag, "no_level")
                        continue

                    symbol = get_or_create_sized_symbol(symbol, shape, opening_w, opening_h)
                    if not symbol:
                        add_diag(diag, "no_symbol")
                        continue

                    insertion_point = get_window_insertion_point(midpoint, lvl)

                    inst = None
                    if wall_el.Document == doc:
                        try:
                            inst = doc.Create.NewFamilyInstance(
                                insertion_point, symbol, wall_el, lvl, DB.Structure.StructuralType.NonStructural
                            )
                        except:
                            pass
                    if not inst:
                        try:
                            inst = doc.Create.NewFamilyInstance(
                                insertion_point, symbol, lvl, DB.Structure.StructuralType.NonStructural
                            )
                            # Align angle with wall
                            wall_angle = math.atan2(wall_dir.Y, wall_dir.X)
                            rot_axis = DB.Line.CreateBound(insertion_point, insertion_point + DB.XYZ.BasisZ)
                            DB.ElementTransformUtils.RotateElement(doc, inst.Id, rot_axis, wall_angle)
                        except:
                            add_diag(diag, "placement_failed")
                            continue
                    if not inst:
                        add_diag(diag, "placement_failed")
                        continue

                    # Set size parameters
                    set_opening_size(inst, shape, opening_w, opening_h, wall_thickness, lvl, midpoint)
                    align_opening_bbox_center(inst, midpoint, wall_dir)

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
            if placed_count == 0:
                print_diagnostics(diag)

            if placed_details:
                table_data = []
                for idx, (inst, cat, mid) in enumerate(placed_details):
                    mep_cat_name = str(cat).replace("OST_", "")

                    shape = get_shape_from_symbol(inst.Symbol)

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
                symbols_names.add(safe_family_name(round_symbol))
            if rect_symbol:
                symbols_names.add(safe_family_name(rect_symbol))
            if not symbols_names:
                for display_name in family_map.keys():
                    symbols_names.add(display_name.split(" : ")[0])

            instances = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Windows).WhereElementIsNotElementType().ToElements()
            generic_instances = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_GenericModel).WhereElementIsNotElementType().ToElements()
            all_instances = list(instances) + list(generic_instances)

            tracked_openings = []
            for inst in all_instances:
                f_name = safe_family_name(inst.Symbol)
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
                        wall_candidates.append((wall_el, wall_t, wall_bbox))

                # Perform precise collision
                intersect_found = False
                matched_wall = None
                matched_wall_dir = None
                new_midpoint = None
                new_w, new_h, new_d = 0.0, 0.0, 0.0

                mep_cat = mep_el.Category.BuiltInCategory
                mep_dim = get_mep_dimensions(mep_el)
                target_symbol, target_shape = resolve_opening_family(mep_el, mep_dim, rules, family_map, round_symbol, rect_symbol)
                if not target_shape:
                    target_shape = get_shape_from_symbol(opening.Symbol)
                offset_ft = offsets.get(mep_cat, to_feet(50.0))

                matched_level = None
                for wall_el, wall_t, wall_bbox in wall_candidates:
                    wall_solids = get_wall_solids(wall_el, wall_t)
                    wall_dir = get_wall_direction(wall_el, wall_t)

                    # Curve check
                    mep_curve = get_transformed_curve(mep_el, mep_t)
                    if mep_curve:
                        mep_dir = mep_curve.ComputeDerivatives(0.5, True).BasisX.Normalize()
                        intersect_segment = None
                        for solid in wall_solids:
                            res = intersect_solid_with_curve(solid, mep_curve)
                            if res and res.SegmentCount > 0:
                                intersect_segment = res.GetCurveSegment(0)
                                break

                        if intersect_segment:
                            new_midpoint = intersect_segment.Evaluate(0.5, True)
                            projected_dims = calculate_projection_size(mep_dim, mep_dir, wall_dir, offset_ft)
                            if projected_dims:
                                new_w, new_h = projected_dims
                                new_d = estimate_wall_thickness(wall_el, wall_bbox)
                                intersect_found = True
                                matched_wall = wall_el
                                matched_wall_dir = wall_dir
                                matched_level = doc.GetElement(wall_el.LevelId) if wall_el.Document == doc and wall_el.LevelId != DB.ElementId.InvalidElementId else get_closest_level(doc, new_midpoint.Z)
                                break
                        else:
                            new_midpoint = estimate_curve_wall_plane_hit(mep_curve, wall_el, wall_t, wall_dir, wall_bbox, tolerance=1.0)
                            projected_dims = calculate_projection_size(mep_dim, mep_dir, wall_dir, offset_ft)
                            if new_midpoint and projected_dims:
                                new_w, new_h = projected_dims
                                new_d = estimate_wall_thickness(wall_el, wall_bbox)
                                intersect_found = True
                                matched_wall = wall_el
                                matched_wall_dir = wall_dir
                                matched_level = doc.GetElement(wall_el.LevelId) if wall_el.Document == doc and wall_el.LevelId != DB.ElementId.InvalidElementId else get_closest_level(doc, new_midpoint.Z)
                                break
                    # Solid check
                    else:
                        mep_solids = get_element_solids(mep_el, mep_t)
                        intersect_solid = None
                        for s_mep in mep_solids:
                            for s_wall in wall_solids:
                                res_solid = boolean_intersection_solid(s_mep, s_wall)
                                if res_solid:
                                    intersect_solid = res_solid
                                    break
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
                            new_d = estimate_wall_thickness(wall_el, wall_bbox)
                            intersect_found = True
                            matched_wall = wall_el
                            matched_wall_dir = wall_dir
                            matched_level = doc.GetElement(wall_el.LevelId) if wall_el.Document == doc and wall_el.LevelId != DB.ElementId.InvalidElementId else get_closest_level(doc, new_midpoint.Z)
                            break
                        else:
                            bbox_intersect = get_box_intersection(mep_bbox, wall_bbox)
                            if bbox_intersect:
                                new_midpoint = bbox_center(bbox_intersect)
                                pts = [
                                    DB.XYZ(bbox_intersect.Min.X, bbox_intersect.Min.Y, bbox_intersect.Min.Z),
                                    DB.XYZ(bbox_intersect.Min.X, bbox_intersect.Min.Y, bbox_intersect.Max.Z),
                                    DB.XYZ(bbox_intersect.Min.X, bbox_intersect.Max.Y, bbox_intersect.Min.Z),
                                    DB.XYZ(bbox_intersect.Min.X, bbox_intersect.Max.Y, bbox_intersect.Max.Z),
                                    DB.XYZ(bbox_intersect.Max.X, bbox_intersect.Min.Y, bbox_intersect.Min.Z),
                                    DB.XYZ(bbox_intersect.Max.X, bbox_intersect.Min.Y, bbox_intersect.Max.Z),
                                    DB.XYZ(bbox_intersect.Max.X, bbox_intersect.Max.Y, bbox_intersect.Min.Z),
                                    DB.XYZ(bbox_intersect.Max.X, bbox_intersect.Max.Y, bbox_intersect.Max.Z)
                                ]
                                x_coords = [p.DotProduct(wall_dir) for p in pts]
                                y_coords = [p.DotProduct(DB.XYZ.BasisZ) for p in pts]
                                new_w = (max(x_coords) - min(x_coords)) + 2.0 * offset_ft
                                new_h = (max(y_coords) - min(y_coords)) + 2.0 * offset_ft
                                new_d = estimate_wall_thickness(wall_el, wall_bbox)
                                intersect_found = True
                                matched_wall = wall_el
                                matched_wall_dir = wall_dir
                                matched_level = doc.GetElement(wall_el.LevelId) if wall_el.Document == doc and wall_el.LevelId != DB.ElementId.InvalidElementId else get_closest_level(doc, new_midpoint.Z)
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
                        target_location = get_window_insertion_point(new_midpoint, matched_level)
                        has_moved = target_location is not None and not opening.Location.Point.IsAlmostEqualTo(target_location, 0.01)
                except:
                    has_moved = False

                target_symbol = get_or_create_sized_symbol(target_symbol, target_shape, new_w, new_h)
                needs_symbol_update = target_symbol is not None and opening.Symbol.Id != target_symbol.Id
                needs_param_update = needs_opening_size_update(opening, target_shape, new_w, new_h, new_d)
                needs_center_align = False
                if matched_wall_dir:
                    try:
                        bbox = opening.get_BoundingBox(None)
                        if bbox:
                            needs_center_align = abs((new_midpoint - bbox_center(bbox)).DotProduct(matched_wall_dir)) > 0.01
                    except:
                        needs_center_align = False

                if has_moved or needs_param_update or needs_symbol_update or needs_center_align:
                    symbol_changed = False
                    if needs_symbol_update:
                        try:
                            symbol_changed = change_opening_symbol(opening, target_symbol)
                        except:
                            symbol_changed = False
                    if has_moved:
                        try:
                            move_opening_to_point(opening, target_location)
                        except:
                            has_moved = False
                    set_opening_size(opening, target_shape, new_w, new_h, new_d, matched_level, new_midpoint)
                    align_opening_bbox_center(opening, new_midpoint, matched_wall_dir)

                    # Update metadata
                    find_and_set_parameter(opening, PARAM_SYSTEMS, get_mep_system_name(mep_el))
                    find_and_set_parameter(opening, PARAM_SIZES, get_mep_size_string(mep_el, mep_dim))

                    elevation_string = "{:.0f} mm".format(to_mm(new_midpoint.Z))
                    find_and_set_parameter(opening, PARAM_ELEVATIONS, elevation_string)

                    updated_count += 1
                    print("Updated Opening ID: {} - Moved: {}, Resized: {}, Type Changed: {}, Center Aligned: {}".format(opening.Id, has_moved, needs_param_update, symbol_changed, needs_center_align))
                    updated_details.append((opening, mep_cat, new_midpoint, has_moved or needs_center_align, needs_param_update or symbol_changed))

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

                    shape = get_shape_from_symbol(inst.Symbol)

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
                        safe_family_name(o.Symbol),
                        safe_symbol_name(o.Symbol)
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
