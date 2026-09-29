# -*- coding: utf-8 -*-
__title__ = 'G-Element\nStatus'
__author__ = 'เพิ่มพงษ์ ทวีกุล'

import clr
import System
import os
import tempfile
from System.Collections.Generic import List

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

import Autodesk.Revit.DB as DB
import Autodesk.Revit.UI as UI
from System.Windows.Forms import *
from System.Drawing import *

# --------------------------
# CONFIG
# --------------------------
PARAM_NAME = "g_Element Status"

STATUS_MAP = [
    ("0", "0 : ยังไม่ได้ส่ง SHOP DRAWING"),
    ("0.1", "0.1 : ส่ง SHOP DRAWING แล้ว"),
    ("0.5", "0.5 : SHOPDRAWING ตอบกลับ AN หรือ RR"),
    ("1", "1 : SHOPDRAWING ตอบกลับ AP"),
    ("2", "2 : ส่ง AS-BUILT")
]

# รายการ Categories ทั้งหมด (ตรวจสอบตรงตาม Revit API BuiltInCategory)
CAT_LIST = [
    "OST_CableTray", "OST_CableTrayFitting", "OST_CableTrayRun",
    "OST_Ceilings", "OST_Columns",
    "OST_CommunicationDevices", "OST_Conduit", "OST_ConduitFitting", "OST_ConduitRun",
    "OST_CurtainWallPanels", "OST_CurtainWallMullions", "OST_DataDevices", "OST_Doors",
    "OST_DuctAccessory", "OST_DuctCurves", "OST_DuctFitting", "OST_DuctInsulations",
    "OST_DuctLinings", "OST_DuctTerminal", "OST_ElectricalEquipment", "OST_ElectricalFixtures",
    "OST_FireAlarmDevices", "OST_FireProtection", "OST_FlexDuctCurves", "OST_FlexPipeCurves",
    "OST_Floors", "OST_FoodServiceEquipment", "OST_Furniture", "OST_GenericModel",
    "OST_LightingDevices", "OST_LightingFixtures", "OST_MechanicalControlDevices",
    "OST_MechanicalEquipment", "OST_MechanicalEquipmentSet", "OST_MedicalEquipment",
    "OST_NurseCallDevices", "OST_PipeAccessory", "OST_PipeCurves", "OST_PipeFitting",
    "OST_PipeInsulations", "OST_PlaceHolderDucts", "OST_PlaceHolderPipes", "OST_Planting",
    "OST_PlumbingEquipment", "OST_PlumbingFixtures", "OST_Railings", "OST_Ramps",
    "OST_Rebar", "OST_Roads", "OST_Roofs", "OST_SecurityDevices", "OST_Signage",
    "OST_Site", "OST_Sprinklers", "OST_Stairs", "OST_BeamSystem", "OST_StructuralColumns",
    "OST_StructConnections", "OST_StructuralFoundation", "OST_StructuralFraming",
    "OST_StructuralTruss", "OST_TelephoneDevices", "OST_Walls", "OST_Windows", "OST_Wire"
]

def get_target_categories():
    valid_cats = []
    for name in CAT_LIST:
        try:
            if hasattr(DB.BuiltInCategory, name):
                valid_cats.append(getattr(DB.BuiltInCategory, name))
        except: pass
    return valid_cats

def get_identity_group_id():
    try:
        return DB.GroupTypeId.IdentityData
    except:
        return DB.BuiltInParameterGroup.PG_IDENTITY_DATA

def get_workset_name(doc, elem):
    if doc.IsWorkshared:
        ws_id = elem.WorksetId
        if ws_id != DB.WorksetId.InvalidWorksetId:
            ws = doc.GetWorksetTable().GetWorkset(ws_id)
            return ws.Name if ws else "Shared"
    return "Non-Shared"

# =====================================================
# ฟังก์ชันตรวจสอบว่าชิ้นส่วนเป็น Line Base หรือไม่
# =====================================================
def is_linebase_element(el, doc, type_cache=None):
    """
    ตรวจสอบว่าชิ้นส่วนมีคำว่า 'linebase' หรือ 'line base' หรือไม่
    (ทั้งในชื่อ Element, Type, Family Name หรือพารามิเตอร์ที่เกี่ยวข้อง)
    มีระบบ type_cache เพื่อให้อ่านค่าได้เร็วขึ้นระดับเสี้ยววินาที
    """
    tid_val = None
    try:
        tid = el.GetTypeId()
        if tid and tid != DB.ElementId.InvalidElementId:
            tid_val = tid.Value if hasattr(tid, 'Value') else tid.IntegerValue
            if type_cache is not None and tid_val in type_cache:
                return type_cache[tid_val]
    except: pass

    names_to_check = []
    
    # 1. Instance Name
    try:
        if el.Name:
            names_to_check.append(el.Name)
    except: pass
    
    # 2. Type Name & Family Name จาก ElementType
    try:
        if tid and tid != DB.ElementId.InvalidElementId:
            elem_type = doc.GetElement(tid)
            if elem_type:
                if elem_type.Name:
                    names_to_check.append(elem_type.Name)
                fam_name = getattr(elem_type, "FamilyName", None)
                if fam_name:
                    names_to_check.append(fam_name)
    except: pass
    
    # 3. Family Name & Symbol Name กรณีเป็น FamilyInstance
    try:
        if hasattr(el, "Symbol") and el.Symbol:
            if el.Symbol.Name:
                names_to_check.append(el.Symbol.Name)
            if el.Symbol.Family and el.Symbol.Family.Name:
                names_to_check.append(el.Symbol.Family.Name)
    except: pass

    # 4. Built-in Parameters (Family Name, Type Name)
    for bip in [DB.BuiltInParameter.ELEM_FAMILY_PARAM, DB.BuiltInParameter.ELEM_TYPE_PARAM]:
        try:
            p = el.get_Parameter(bip)
            if p:
                val = p.AsString() or p.AsValueString()
                if val:
                    names_to_check.append(val)
        except: pass

    # 5. พารามิเตอร์ทั่วไปที่มักเก็บชื่อ Family
    for p_name in ["FAMILY NAME", "Family Name", "Type Name"]:
        try:
            p = el.LookupParameter(p_name)
            if p:
                val = p.AsString() or p.AsValueString()
                if val:
                    names_to_check.append(val)
        except: pass

    is_lb = False
    for name in names_to_check:
        if not name:
            continue
        clean = str(name).lower().replace(" ", "").replace("_", "").replace("-", "")
        if "linebase" in clean:
            is_lb = True
            break
            
    if type_cache is not None and tid_val is not None:
        type_cache[tid_val] = is_lb

    return is_lb

# =====================================================
# ฟังก์ชันช่วยค้นหาและอ่าน/ล้างค่า Parameter
# =====================================================
def get_element_parameter(el, param_name):
    if not el:
        return None
    p = el.LookupParameter(param_name)
    if p:
        return p
    try:
        for param in el.Parameters:
            if param.Definition and param.Definition.Name == param_name:
                return param
    except: pass
    return None

def get_param_value(p):
    if not p:
        return "Not Found"
    if not p.HasValue:
        return "Empty"
    
    st = p.StorageType
    if st == DB.StorageType.String:
        val = p.AsString()
        return val if val else "Empty"
    elif st == DB.StorageType.Double:
        val = p.AsValueString()
        if not val:
            val = str(p.AsDouble())
        return val.replace(".0", "")
    elif st == DB.StorageType.Integer:
        return str(p.AsInteger())
    elif st == DB.StorageType.ElementId:
        eid = p.AsElementId()
        # รองรับ Revit 2024-2026 (.Value) และเวอร์ชันเก่า (.IntegerValue)
        return str(eid.Value if hasattr(eid, 'Value') else eid.IntegerValue)
    return "Empty"

def clear_param_value(p):
    """ล้างค่าพารามิเตอร์ให้กลับเป็นค่าว่าง"""
    if not p or p.IsReadOnly:
        return False
    try:
        if hasattr(p, "ClearValue"):
            p.ClearValue()
            return True
    except: pass
    try:
        if p.StorageType == DB.StorageType.String:
            p.Set("")
            return True
        elif p.StorageType == DB.StorageType.Double:
            p.Set(0.0)
            return True
        elif p.StorageType == DB.StorageType.Integer:
            p.Set(0)
            return True
    except: pass
    return False

# =====================================================
# ฟังก์ชันตรวจสอบและสร้าง/อัปเดต Shared Parameter อัตโนมัติ
# =====================================================
def setup_parameter(doc, app, param_name, param_type, all_cat_names):
    existing_def = None
    existing_binding = None
    
    iterator = doc.ParameterBindings.ForwardIterator()
    while iterator.MoveNext():
        if iterator.Key.Name == param_name:
            existing_def = iterator.Key
            existing_binding = iterator.Current
            break
            
    if existing_def and existing_binding:
        # หากมี Parameter ในโมเดลอยู่แล้ว ให้ใช้งานต่อทันที
        # ห้ามเรียก ReInsert เด็ดขาด เพราะ Revit API จะล้างค่าของพารามิเตอร์ทั้งหมดในโปรเจกต์ทิ้ง
        return "exists"
            
    sp_file = app.OpenSharedParameterFile()
    original_sp = app.SharedParametersFilename
    
    if not sp_file:
        temp_dir = tempfile.gettempdir()
        temp_sp_path = os.path.join(temp_dir, "Auto_SharedParams_Revit.txt")
        if not os.path.exists(temp_sp_path):
            with open(temp_sp_path, "w") as f: f.write("") 
        try:
            app.SharedParametersFilename = temp_sp_path
            sp_file = app.OpenSharedParameterFile()
        except: pass
            
    if not sp_file: return "sp_error"
        
    target_def = None
    for group in sp_file.Groups:
        for definition in group.Definitions:
            if definition.Name == param_name:
                target_def = definition
                break
        if target_def: break
            
    if not target_def:
        group_name = "Identity Data"
        group = sp_file.Groups.get_Item(group_name)
        if not group: group = sp_file.Groups.Create(group_name)
        try:
            if param_type == "Text":
                opt = DB.ExternalDefinitionCreationOptions(param_name, DB.SpecTypeId.String.Text)
            else:
                opt = DB.ExternalDefinitionCreationOptions(param_name, DB.SpecTypeId.Length)
            target_def = group.Definitions.Create(opt)
        except AttributeError:
            if param_type == "Text":
                opt = DB.ExternalDefinitionCreationOptions(param_name, DB.ParameterType.Text)
            else:
                opt = DB.ExternalDefinitionCreationOptions(param_name, DB.ParameterType.Length)
            target_def = group.Definitions.Create(opt)
            
    if original_sp and app.SharedParametersFilename != original_sp:
        try: app.SharedParametersFilename = original_sp
        except: pass
            
    if not target_def: return "def_not_found"
        
    cat_set = app.Create.NewCategorySet()
    for c in all_cat_names:
        try:
            if hasattr(DB.BuiltInCategory, c):
                b_cat = getattr(DB.BuiltInCategory, c)
                cat = doc.Settings.Categories.get_Item(b_cat)
                if cat and cat.AllowsBoundParameters:
                    cat_set.Insert(cat)
        except: pass
            
    if cat_set.IsEmpty: return "no_categories"
        
    binding = app.Create.NewInstanceBinding(cat_set)
    t_param = DB.Transaction(doc, "Setup Parameter: {}".format(param_name))
    t_param.Start()
    try:
        inserted = False
        try:
            inserted = doc.ParameterBindings.Insert(target_def, binding, get_identity_group_id())
        except AttributeError:
            inserted = doc.ParameterBindings.Insert(target_def, binding, DB.BuiltInParameterGroup.PG_IDENTITY_DATA)
        
        if inserted:
            try:
                iterator = doc.ParameterBindings.ForwardIterator()
                while iterator.MoveNext():
                    if iterator.Key.Name == param_name and isinstance(iterator.Key, DB.InternalDefinition):
                        if not iterator.Key.VariesAcrossGroups:
                            iterator.Key.SetAllowVaryBetweenGroups(doc, True)
                        break
            except: pass
            t_param.Commit()
            return "created"
        else:
            t_param.RollBack()
            return "bind_error"
    except:
        t_param.RollBack()
        return "bind_error"


class ElementStatusForm(Form):
    def __init__(self, doc, grouped_elements, setup_status, linebase_count=0):
        self.doc = doc
        self.grouped_elements = grouped_elements
        self.final_data = []
        self.setup_status = setup_status
        self.linebase_count = linebase_count
        self.InitializeComponent()

    def InitializeComponent(self):
        self.Text = "G-Element Status Manager"
        self.Width, self.Height = 940, 880
        self.StartPosition = FormStartPosition.CenterScreen
        self.Font = Font("Segoe UI", 9)
        self.BackColor = Color.White

        container = TableLayoutPanel(Dock=DockStyle.Fill, RowCount=7, ColumnCount=1)
        container.RowStyles.Add(RowStyle(SizeType.Absolute, 85))
        container.RowStyles.Add(RowStyle(SizeType.Absolute, 50))
        container.RowStyles.Add(RowStyle(SizeType.Absolute, 50))
        container.RowStyles.Add(RowStyle(SizeType.Percent, 100))
        container.RowStyles.Add(RowStyle(SizeType.Absolute, 180))
        container.RowStyles.Add(RowStyle(SizeType.Absolute, 85))
        
        # 1. Header
        header_panel = Panel(Dock=DockStyle.Fill, BackColor=Color.FromArgb(0, 70, 140))
        lbl_title = Label(Text="Update Element Status", ForeColor=Color.White, 
                          Font=Font("Segoe UI", 14, FontStyle.Bold), AutoSize=True, Location=Point(15, 12))
        
        # แสดงสถานะ Parameter และจำนวนชิ้นส่วน Line Base ที่ถูกคัดกรองออก
        status_txt = "READY (Auto-Setup Completed)" if self.setup_status in ["created", "updated", "exists"] else "ERROR"
        status_clr = Color.LimeGreen if "READY" in status_txt else Color.OrangeRed
        
        detail_txt = "Parameter Status: " + status_txt
        if self.linebase_count > 0:
            detail_txt += "  |  Filtered Line Base: {} elements".format(self.linebase_count)

        self.lbl_status = Label(Text=detail_txt, ForeColor=status_clr,
                               Font=Font("Segoe UI", 10, FontStyle.Bold), AutoSize=True, Location=Point(17, 44))
        
        header_panel.Controls.Add(lbl_title)
        header_panel.Controls.Add(self.lbl_status)

        # Selection & DataGrid
        sel_panel = FlowLayoutPanel(Dock=DockStyle.Fill, Padding=Padding(10, 8, 0, 0))
        for t, f in [("Select All", self.select_all), ("Unselect All", self.unselect_all), 
                     ("Select Highlight", self.select_highlight), ("Unselect Highlight", self.unselect_highlight)]:
            b = Button(Text=t, Width=130, Height=32, BackColor=Color.WhiteSmoke)
            b.Click += f; sel_panel.Controls.Add(b)

        hi_panel = FlowLayoutPanel(Dock=DockStyle.Fill, Padding=Padding(10, 8, 0, 0))
        hi_panel.Controls.Add(Label(Text="Set Status for Highlight:", AutoSize=True, Margin=Padding(0, 7, 5, 0)))
        self.cmb_hi = ComboBox(Width=120, DataSource=[s[0] for s in STATUS_MAP], DropDownStyle=ComboBoxStyle.DropDownList)
        btn_apply = Button(Text="Apply to List", Width=120, Height=28, BackColor=Color.AliceBlue)
        btn_apply.Click += self.apply_highlight_status
        hi_panel.Controls.Add(self.cmb_hi); hi_panel.Controls.Add(btn_apply)
        
        self.dgv = DataGridView(Dock=DockStyle.Fill, RowHeadersVisible=False, AllowUserToAddRows=False,
                                SelectionMode=DataGridViewSelectionMode.FullRowSelect, BackgroundColor=Color.White)
        self.dgv.Columns.Add(DataGridViewCheckBoxColumn(Name="Selected", HeaderText="Update?", Width=70))
        self.dgv.Columns.Add(DataGridViewTextBoxColumn(Name="Workset", HeaderText="Workset", Width=280, ReadOnly=True))
        self.dgv.Columns.Add(DataGridViewTextBoxColumn(Name="Current", HeaderText="Current Status", Width=120, ReadOnly=True))
        self.dgv.Columns.Add(DataGridViewTextBoxColumn(Name="Count", HeaderText="Count", Width=80, ReadOnly=True))
        self.dgv.Columns.Add(DataGridViewComboBoxColumn(Name="NewStatus", HeaderText="New Status", Width=180, DataSource=[s[0] for s in STATUS_MAP]))
        self.populate_data()

        leg_box = GroupBox(Text="Status Definitions", Dock=DockStyle.Fill, Margin=Padding(10))
        lbl_leg = Label(Text="\n".join([s[1] for s in STATUS_MAP]), Dock=DockStyle.Fill, Padding=Padding(10), Font=Font("Segoe UI", 10))
        leg_box.Controls.Add(lbl_leg)

        btn_pnl = FlowLayoutPanel(Dock=DockStyle.Fill, FlowDirection=FlowDirection.RightToLeft, Padding=Padding(0, 10, 20, 0))
        self.btn_ok = Button(Text="UPDATE SELECTED", Size=Size(250, 55), 
                            BackColor=Color.FromArgb(0, 0, 128), ForeColor=Color.White, 
                            Font=Font("Segoe UI", 13, FontStyle.Bold),
                            FlatStyle=FlatStyle.Flat, Enabled=("READY" in status_txt))
        self.btn_ok.Click += self.ok_click
        btn_pnl.Controls.Add(self.btn_ok)

        container.Controls.Add(header_panel, 0, 0); container.Controls.Add(sel_panel, 0, 1)
        container.Controls.Add(hi_panel, 0, 2); container.Controls.Add(self.dgv, 0, 3)
        container.Controls.Add(leg_box, 0, 4); container.Controls.Add(btn_pnl, 0, 5)
        self.Controls.Add(container)

    def select_all(self, s, e):
        for r in self.dgv.Rows: r.Cells["Selected"].Value = True
    def unselect_all(self, s, e):
        for r in self.dgv.Rows: r.Cells["Selected"].Value = False
    def select_highlight(self, s, e):
        for r in self.dgv.SelectedRows: r.Cells["Selected"].Value = True
    def unselect_highlight(self, s, e):
        for r in self.dgv.SelectedRows: r.Cells["Selected"].Value = False
    def apply_highlight_status(self, s, e):
        val = self.cmb_hi.SelectedItem
        for r in self.dgv.SelectedRows:
            r.Cells["NewStatus"].Value = val; r.Cells["Selected"].Value = True

    def populate_data(self):
        for ws in sorted(self.grouped_elements.keys()):
            for status, el_list in self.split_by_status(self.grouped_elements[ws]["elements"]).items():
                self.dgv.Rows.Add(False, ws, status, len(el_list), "0")

    def split_by_status(self, elements):
        gs = {}
        for el in elements:
            val = "Not Found"
            if "READY" in self.lbl_status.Text:
                p = el.LookupParameter(PARAM_NAME)
                val = get_param_value(p)
            if val not in gs: gs[val] = []
            gs[val].append(el)
        return gs

    def ok_click(self, s, e):
        self.final_data = []
        for r in self.dgv.Rows:
            if r.Cells["Selected"].Value:
                self.final_data.append({"WS": r.Cells["Workset"].Value, "Old": r.Cells["Current"].Value, "New": r.Cells["NewStatus"].Value})
        if self.final_data: self.DialogResult = DialogResult.OK; self.Close()

def main():
    doc = __revit__.ActiveUIDocument.Document
    app = doc.Application
    
    # 1. จัดการ Parameter อัตโนมัติก่อนเปิดหน้าต่าง (Smart Setup)
    setup_status = setup_parameter(doc, app, PARAM_NAME, "Text", CAT_LIST)

    # 2. ค้นหาชิ้นส่วน
    target_cats = get_target_categories()
    cats = List[DB.ElementId]([DB.ElementId(c) for c in target_cats])
    raw_elems = DB.FilteredElementCollector(doc, doc.ActiveView.Id).WherePasses(DB.ElementMulticategoryFilter(cats)).WhereElementIsNotElementType().ToElements()
    
    # กรองเอาเฉพาะ Element จริงๆ ไม่นับ Revit Link, ไฟล์ Import และแยกชิ้นส่วนที่เป็น Line Base ออก
    # ใช้ type_cache เพื่อให้สแกนไวขึ้นอย่างมาก
    elems = []
    linebase_elems = []
    type_cache = {}
    for el in raw_elems:
        if isinstance(el, DB.RevitLinkInstance) or isinstance(el, DB.ImportInstance):
            continue
        
        # ปรับแก้การเช็ค Category ID ให้รองรับทั้ง Revit 2026 (.Value) และเวอร์ชันเก่า
        if el.Category:
            cat_id = el.Category.Id
            cat_val = cat_id.Value if hasattr(cat_id, 'Value') else cat_id.IntegerValue
            if cat_val == int(DB.BuiltInCategory.OST_RvtLinks):
                continue
                
        # ข้ามชิ้นส่วนที่เป็น linebase เพราะเอาไว้จัดกลุ่มเฉย ๆ ไม่ฝังค่า
        if is_linebase_element(el, doc, type_cache):
            linebase_elems.append(el)
            continue

        elems.append(el)

    if not elems: 
        UI.TaskDialog.Show("G-Status", "ไม่พบชิ้นส่วนใน View ปัจจุบัน (ไม่รวม Revit Link และ Line Base)")
        return
    
    grouped = {}
    for el in elems:
        ws = get_workset_name(doc, el)
        if ws not in grouped: grouped[ws] = {"elements": []}
        grouped[ws]["elements"].append(el)

    # 3. เปิดหน้าต่าง UI
    form = ElementStatusForm(doc, grouped, setup_status, len(linebase_elems))
    if form.ShowDialog() == DialogResult.OK:
        
        # เตรียม Map งานแยกตาม Workset { Workset: { OldStatus: NewStatus } }
        ws_map = {}
        for task in form.final_data:
            ws_name = task["WS"]
            if ws_name not in ws_map:
                ws_map[ws_name] = {}
            ws_map[ws_name][task["Old"]] = task["New"]

        # 4. ทำการ Check Out Worksets ทั้งหมดที่เกี่ยวข้องก่อนเริ่มเขียนค่า
        # เพื่อแก้ไขปัญหา "You are trying to checkout a large number of elements"
        # และทำให้ Revit บันทึกค่าได้เร็วกว่าเดิม 50-100 เท่า (ไม่ต้องยืมทีละชิ้นผ่าน Network)
        if doc.IsWorkshared:
            ws_to_checkout = set()
            for ws_name in ws_map.keys():
                if ws_name in grouped and grouped[ws_name]["elements"]:
                    first_el = grouped[ws_name]["elements"][0]
                    wid = first_el.WorksetId
                    if wid != DB.WorksetId.InvalidWorksetId:
                        ws_to_checkout.add(wid)

            for el in linebase_elems:
                wid = el.WorksetId
                if wid != DB.WorksetId.InvalidWorksetId:
                    ws_to_checkout.add(wid)

            if ws_to_checkout:
                try:
                    from System.Collections.Generic import HashSet
                    hs = HashSet[DB.WorksetId]()
                    for wid in ws_to_checkout:
                        hs.Add(wid)
                    DB.WorksharingUtils.CheckoutWorksets(doc, hs)
                except:
                    try:
                        ws_list = List[DB.WorksetId](list(ws_to_checkout))
                        DB.WorksharingUtils.CheckoutWorksets(doc, ws_list)
                    except: pass

        with DB.Transaction(doc, "Update G-Status") as tx:
            tx.Start()
            
            # เปิดอนุญาตให้เขียนค่าลงใน Group (VariesAcrossGroups)
            varies_across_groups = False
            iterator = doc.ParameterBindings.ForwardIterator()
            while iterator.MoveNext():
                definition = iterator.Key
                if definition.Name == PARAM_NAME and isinstance(definition, DB.InternalDefinition):
                    try:
                        if not definition.VariesAcrossGroups: definition.SetAllowVaryBetweenGroups(doc, True)
                        varies_across_groups = definition.VariesAcrossGroups
                    except:
                        varies_across_groups = getattr(definition, 'VariesAcrossGroups', False)
                    break

            count = 0
            for ws_name, status_dict in ws_map.items():
                if ws_name not in grouped:
                    continue
                for el in grouped[ws_name]["elements"]:
                    # ข้ามชิ้นส่วนใน Group หากไม่สามารถเปิด Vary by Group ได้
                    if el.GroupId != DB.ElementId.InvalidElementId:
                        if not varies_across_groups:
                            continue

                    p = el.LookupParameter(PARAM_NAME)
                    if p and not p.IsReadOnly:
                        cur = get_param_value(p)
                        if cur in status_dict:
                            new_val = status_dict[cur]
                            try:
                                if p.StorageType == DB.StorageType.String:
                                    p.Set(str(new_val))
                                elif p.StorageType == DB.StorageType.Double:
                                    p.Set(float(new_val))
                                elif p.StorageType == DB.StorageType.Integer:
                                    p.Set(int(float(new_val)))
                                count += 1
                            except: pass

            # ล้างค่าในชิ้นส่วน Line Base ที่อาจเคยถูกฝังค่าไว้ก่อนหน้านี้
            cleared_linebase_count = 0
            for el in linebase_elems:
                if el.GroupId != DB.ElementId.InvalidElementId and not varies_across_groups:
                    continue
                p = el.LookupParameter(PARAM_NAME)
                if p and not p.IsReadOnly and p.HasValue:
                    cur = get_param_value(p)
                    if cur not in ["Empty", "Not Found", ""]:
                        if clear_param_value(p):
                            cleared_linebase_count += 1

            tx.Commit()

            msg = "อัปเดตสถานะเรียบร้อยแล้วจำนวน {} ชิ้น".format(count)
            if cleared_linebase_count > 0:
                msg += "\n(ล้างค่าออกจากชิ้นส่วน Line Base ที่เคยมีค่า {} ชิ้น)".format(cleared_linebase_count)
            elif len(linebase_elems) > 0:
                msg += "\n(ข้ามชิ้นส่วน Line Base {} ชิ้น ไม่มีการฝังค่า)".format(len(linebase_elems))
            UI.TaskDialog.Show("G-Status", msg)

if __name__ == "__main__":
    main()