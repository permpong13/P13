# -*- coding: utf-8 -*-
"""
Bloom / Extend MEP Curve (V5 - Multi-Select)
Support: Pipe, Duct, Fittings, Accessories, Equipment
Features: 
- Select MULTIPLE connectors to bloom at once
- Auto-detects pipe/duct type for each connector
- 90 & 45 Degree Elbows support
"""
import Autodesk.Revit.DB as DB
import Autodesk.Revit.UI as UI
from pyrevit import revit, forms, script
import math

# --- Configuration ---
my_config = script.get_config("BloomSettings")
DEFAULT_LENGTH = 500.0 
last_length = my_config.get_option("extension_length", DEFAULT_LENGTH)

doc = revit.doc
uidoc = revit.uidoc

# --- Helper Functions ---
def px_to_internal(mm_val):
    try:
        return DB.UnitUtils.ConvertToInternalUnits(float(mm_val), DB.UnitTypeId.Millimeters)
    except:
        return float(mm_val) / 304.8

def get_connector_manager(elem):
    if isinstance(elem, (DB.Plumbing.Pipe, DB.Mechanical.Duct)):
        return elem.ConnectorManager
    elif isinstance(elem, DB.FamilyInstance) and elem.MEPModel:
        return elem.MEPModel.ConnectorManager
    elif isinstance(elem, DB.MEPCurve): 
        return elem.ConnectorManager
    return None

def get_connector_info(connector):
    shape_info = {'shape': 'ROUND', 'size': 0.0, 'width': 0.0, 'height': 0.0, 'desc': ''}
    
    size_str = ""
    if connector.Shape == DB.ConnectorProfileType.Round:
        shape_info['shape'] = 'ROUND'
        shape_info['size'] = connector.Radius * 2.0
        try:
            mm_size = DB.UnitUtils.ConvertFromInternalUnits(shape_info['size'], DB.UnitTypeId.Millimeters)
            size_str = "Ø{:.0f}mm".format(mm_size)
        except:
            size_str = "Ø{:.2f}".format(shape_info['size'])
            
    elif connector.Shape == DB.ConnectorProfileType.Rectangular:
        shape_info['shape'] = 'RECT'
        shape_info['width'] = connector.Width
        shape_info['height'] = connector.Height
        size_str = "{:.0f}x{:.0f}".format(connector.Width*304.8, connector.Height*304.8)
    
    vec = connector.CoordinateSystem.BasisZ
    dir_str = "Unknown"
    if vec.IsAlmostEqualTo(DB.XYZ.BasisZ): dir_str = "Up (+Z)"
    elif vec.IsAlmostEqualTo(-DB.XYZ.BasisZ): dir_str = "Down (-Z)"
    elif abs(vec.X) > abs(vec.Y): dir_str = "X-Axis"
    else: dir_str = "Y-Axis"

    shape_info['desc'] = "{} [{}]".format(size_str, dir_str)
    return shape_info

def get_fallback_system(doc, domain):
    target_class = DB.MEPSystemClassification.SupplyHydronic
    if domain == DB.Domain.DomainPiping:
        target_class = DB.MEPSystemClassification.SupplyHydronic
    elif domain == DB.Domain.DomainHvac:
        target_class = DB.MEPSystemClassification.SupplyAir
        
    collector = DB.FilteredElementCollector(doc).OfClass(DB.MEPSystemType)
    for sys_type in collector:
        if sys_type.SystemClassification == target_class:
            return sys_type.Id
            
    if domain == DB.Domain.DomainPiping:
        first_pipe = DB.FilteredElementCollector(doc).OfClass(DB.Plumbing.PipingSystemType).FirstElement()
        if first_pipe: return first_pipe.Id
    elif domain == DB.Domain.DomainHvac:
        first_duct = DB.FilteredElementCollector(doc).OfClass(DB.Mechanical.MechanicalSystemType).FirstElement()
        if first_duct: return first_duct.Id
        
    return DB.ElementId.InvalidElementId

# --- Main Logic ---

# 1. Selection
selection = revit.get_selection()
if len(selection) != 1:
    forms.alert("กรุณาเลือกวัตถุ 1 ชิ้น", exitscript=True)

element = selection[0]
conn_manager = get_connector_manager(element)

if not conn_manager:
    forms.alert("วัตถุที่เลือกไม่มี Connector", exitscript=True)

# 2. Find Open Connectors
all_connectors = conn_manager.Connectors
open_connectors = [c for c in all_connectors if not c.IsConnected and c.ConnectorType != DB.ConnectorType.Logical]

target_connectors = [] # List to store selected connectors

if len(open_connectors) == 0:
    forms.alert("ไม่มีปลายเปิดให้ต่อท่อ", exitscript=True)

elif len(open_connectors) == 1:
    target_connectors = [open_connectors[0]]

else:
    # Multiple connectors -> Multiselect UI
    conn_options = {}
    for i, c in enumerate(open_connectors):
        info = get_connector_info(c)
        key_str = "Connector #{}: {}".format(i+1, info['desc'])
        conn_options[key_str] = c
    
    # *** Changed to multiselect=True ***
    selected_keys = forms.SelectFromList.show(
        sorted(conn_options.keys()),
        title='เลือกจุดเชื่อมต่อ (เลือกได้หลายช่อง):',
        multiselect=True,
        button_name='Select'
    )
    
    if not selected_keys:
        script.exit()
    
    target_connectors = [conn_options[k] for k in selected_keys]

# 3. UI - Direction (Ask once for all)
sorted_options = [
    '⬆️ Up 90 (+Z)', '↗️ Up 45', 
    '⬇️ Down 90 (-Z)', '↘️ Down 45',
    '⬅️ Left 90', '↖️ Left 45',
    '➡️ Right 90', '↗️ Right 45',
    '↔️ Straight'
]
dir_map = {
    '⬆️ Up 90 (+Z)': 'UP_90', '↗️ Up 45': 'UP_45',
    '⬇️ Down 90 (-Z)': 'DOWN_90', '↘️ Down 45': 'DOWN_45',
    '⬅️ Left 90': 'LEFT_90', '↖️ Left 45': 'LEFT_45',
    '➡️ Right 90': 'RIGHT_90', '↗️ Right 45': 'RIGHT_45',
    '↔️ Straight': 'STRAIGHT'
}

selected_direction_ui = forms.CommandSwitchWindow.show(
    sorted_options,
    message='เลือกทิศทาง Bloom (สำหรับทุกจุดที่เลือก):'
)

if not selected_direction_ui:
    script.exit()

direction_key = dir_map[selected_direction_ui]

# Ask Length
new_length_mm = forms.ask_for_string(
    default=str(last_length),
    prompt='ระบุความยาว (mm):',
    title='Extension Length'
)

if not new_length_mm:
    script.exit()

try:
    length_val = float(new_length_mm)
    my_config.set_option("extension_length", length_val)
    script.save_config()
except ValueError:
    script.exit()

extension_len = px_to_internal(length_val)

# 4. Processing Loop
t = DB.Transaction(doc, "Bloom MEP Multi")
t.Start()

try:
    # Prepare global vectors
    view = doc.ActiveView
    view_right = view.RightDirection
    
    for target_connector in target_connectors:
        # Get Info per connector
        domain = target_connector.Domain
        conn_info = get_connector_info(target_connector)
        origin = target_connector.Origin
        basis_z = target_connector.CoordinateSystem.BasisZ 

        # Calculate Vector for THIS connector
        final_vec = None
        ortho_vec = None

        if 'UP' in direction_key: ortho_vec = DB.XYZ.BasisZ
        elif 'DOWN' in direction_key: ortho_vec = -DB.XYZ.BasisZ
        elif 'RIGHT' in direction_key: ortho_vec = view_right
        elif 'LEFT' in direction_key: ortho_vec = -view_right
        elif 'STRAIGHT' in direction_key: final_vec = basis_z # Straight uses local Z

        if not final_vec and ortho_vec:
            if '90' in direction_key: final_vec = ortho_vec
            elif '45' in direction_key: final_vec = (basis_z + ortho_vec).Normalize()
            
        if not final_vec: continue # Skip if vector invalid

        new_end_point = origin + (final_vec * extension_len)
        level_id = element.LevelId
        
        # System determination
        system_type_id = DB.ElementId.InvalidElementId
        if target_connector.MEPSystem:
            system_type_id = target_connector.MEPSystem.GetTypeId()
        
        if system_type_id == DB.ElementId.InvalidElementId:
            system_type_id = get_fallback_system(doc, domain)

        new_me_curve = None
        
        # Create Element
        if domain == DB.Domain.DomainPiping:
            pipe_type_id = element.GetTypeId()
            if not isinstance(element, DB.Plumbing.Pipe):
                # Always find standard pipe type for non-pipe elements
                collector = DB.FilteredElementCollector(doc).OfClass(DB.Plumbing.PipeType).FirstElement()
                if collector: pipe_type_id = collector.Id
            
            # Create Pipe
            new_me_curve = DB.Plumbing.Pipe.Create(
                doc, system_type_id, pipe_type_id, level_id, origin, new_end_point
            )
            new_me_curve.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).Set(conn_info['size'])
            
        elif domain == DB.Domain.DomainHvac:
            duct_type_id = element.GetTypeId()
            if not isinstance(element, DB.Mechanical.Duct):
                 collector = DB.FilteredElementCollector(doc).OfClass(DB.Mechanical.DuctType).FirstElement()
                 if collector: duct_type_id = collector.Id

            # Create Duct
            new_me_curve = DB.Mechanical.Duct.Create(
                doc, system_type_id, duct_type_id, level_id, origin, new_end_point
            )
            if conn_info['shape'] == 'RECT':
                 new_me_curve.get_Parameter(DB.BuiltInParameter.RBS_CURVE_WIDTH_PARAM).Set(conn_info['width'])
                 new_me_curve.get_Parameter(DB.BuiltInParameter.RBS_CURVE_HEIGHT_PARAM).Set(conn_info['height'])
            else:
                 new_me_curve.get_Parameter(DB.BuiltInParameter.RBS_CURVE_DIAMETER_PARAM).Set(conn_info['size'])
        
        # Connect
        if new_me_curve:
            new_conns = new_me_curve.ConnectorManager.Connectors
            conn_to_connect = None
            for c in new_conns:
                if c.Origin.IsAlmostEqualTo(origin):
                    conn_to_connect = c
                    break
                    
            if conn_to_connect:
                if direction_key == 'STRAIGHT':
                    target_connector.ConnectTo(conn_to_connect)
                else:
                    doc.Create.NewElbowFitting(target_connector, conn_to_connect)

    t.Commit()

except Exception as e:
    t.RollBack()
    forms.alert("เกิดข้อผิดพลาด: {}".format(e))