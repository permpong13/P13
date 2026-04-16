# -*- coding: utf-8 -*-
__title__ = 'G-Element\nStatus'
__author__ = 'เพิ่มพงษ์ ทวีกุล'

import clr
import System
import os
import tempfile
from System.Collections.Generic import List

from pyrevit import script, forms

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

CAT_LIST = [
    "OST_AirTerminals", "OST_CableTrayFitting", "OST_CableTray", "OST_Ceilings",
    "OST_Columns", "OST_ConduitFitting", "OST_Conduits", "OST_CurtainWallPanels",
    "OST_CurtainWallMullions", "OST_Doors", "OST_DuctAccessory", "OST_DuctFitting",
    "OST_DuctInsulations", "OST_DuctLinings", "OST_DuctPlaceHolders", "OST_DuctCurves",
    "OST_ElectricalEquipment", "OST_ElectricalFixtures", "OST_FireAlarmDevices",
    "OST_FireProtection", "OST_FlexDuctCurves", "OST_FlexPipeCurves", "OST_Floors",
    "OST_FoodServiceEquipment", "OST_Furniture", "OST_GenericModel", "OST_LightingDevices",
    "OST_LightingFixtures", "OST_MechanicalControlDevices", "OST_MechanicalEquipment",
    "OST_MechanicalEquipmentSet", "OST_MedicalEquipment", "OST_PipeAccessory",
    "OST_PipeFitting", "OST_PipeInsulations", "OST_PipePlaceHolders", "OST_PipeCurves",
    "OST_Planting", "OST_PlumbingEquipment", "OST_PlumbingFixtures", "OST_Railings",
    "OST_Ramps", "OST_Roads", "OST_Roofs", "OST_SecurityDevices", "OST_Signage",
    "OST_Site", "OST_Sprinklers", "OST_Stairs", "OST_BeamSystem", "OST_StructuralColumns",
    "OST_StructuralConnections", "OST_StructuralFoundation", "OST_StructuralFraming",
    "OST_StructuralTruss", "OST_TelephoneDevices", "OST_Walls", "OST_Windows", "OST_Wires",
    "OST_Rebar", "OST_StructuralRebar"
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
    try: return DB.GroupTypeId.IdentityData
    except: return DB.BuiltInParameterGroup.PG_IDENTITY_DATA

def get_workset_name(doc, elem):
    if doc.IsWorkshared:
        ws_id = elem.WorksetId
        if ws_id != DB.WorksetId.InvalidWorksetId:
            ws = doc.GetWorksetTable().GetWorkset(ws_id)
            return ws.Name if ws else "Shared"
    return "Non-Shared"

# =====================================================
# ฟังก์ชันตรวจสอบและสร้าง Shared Parameter อัตโนมัติ
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
        cat_set = existing_binding.Categories
        needs_update = False
        for c in all_cat_names:
            try:
                b_cat = getattr(DB.BuiltInCategory, c)
                cat = doc.Settings.Categories.get_Item(b_cat)
                if cat and cat.AllowsBoundParameters and not cat_set.Contains(cat):
                    cat_set.Insert(cat)
                    needs_update = True
            except: pass
            
        if needs_update:
            t_rebind = DB.Transaction(doc, "Update {} Categories".format(param_name))
            t_rebind.Start()
            try:
                new_binding = app.Create.NewInstanceBinding(cat_set)
                doc.ParameterBindings.ReInsert(existing_def, new_binding)
                t_rebind.Commit()
                return "updated"
            except:
                t_rebind.RollBack()
                return "exists"
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
            opt = DB.ExternalDefinitionCreationOptions(param_name, DB.SpecTypeId.String.Text)
            target_def = group.Definitions.Create(opt)
        except AttributeError:
            opt = DB.ExternalDefinitionCreationOptions(param_name, DB.ParameterType.Text)
            target_def = group.Definitions.Create(opt)
            
    if original_sp and app.SharedParametersFilename != original_sp:
        try: app.SharedParametersFilename = original_sp
        except: pass
            
    if not target_def: return "def_not_found"
        
    cat_set = app.Create.NewCategorySet()
    for c in all_cat_names:
        try:
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
        try: doc.ParameterBindings.Insert(target_def, binding, get_identity_group_id())
        except AttributeError: doc.ParameterBindings.Insert(target_def, binding, DB.BuiltInParameterGroup.PG_IDENTITY_DATA)
        t_param.Commit()
        return "created"
    except:
        t_param.RollBack()
        return "bind_error"

# =====================================================
# Main UI Form
# =====================================================
class ElementStatusForm(Form):
    def __init__(self, doc, grouped_elements, setup_status, scope_text):
        self.doc = doc
        self.grouped_elements = grouped_elements
        self.final_data = []
        self.setup_status = setup_status
        self.scope_text = scope_text
        self.InitializeComponent()

    def InitializeComponent(self):
        self.Text = "G-Element Status Manager"
        self.Width, self.Height = 960, 880
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
        lbl_title = Label(Text="Update Element Status: " + self.scope_text, ForeColor=Color.White, 
                          Font=Font("Segoe UI", 13, FontStyle.Bold), AutoSize=True, Location=Point(15, 12))
        
        status_txt = "READY (Auto-Setup Completed)" if self.setup_status in ["created", "updated", "exists"] else "ERROR"
        status_clr = Color.LimeGreen if "READY" in status_txt else Color.OrangeRed
        self.lbl_status = Label(Text="Parameter Status: " + status_txt, ForeColor=status_clr,
                               Font=Font("Segoe UI", 10, FontStyle.Bold), AutoSize=True, Location=Point(17, 45))
        
        header_panel.Controls.Add(lbl_title)
        header_panel.Controls.Add(self.lbl_status)

        # Selection Buttons
        sel_panel = FlowLayoutPanel(Dock=DockStyle.Fill, Padding=Padding(10, 8, 0, 0))
        for t, f in [("Select All", self.select_all), ("Unselect All", self.unselect_all), 
                     ("Select Highlight", self.select_highlight), ("Unselect Highlight", self.unselect_highlight)]:
            b = Button(Text=t, Width=130, Height=32, BackColor=Color.WhiteSmoke)
            b.Click += f; sel_panel.Controls.Add(b)

        # Highlight Setup
        hi_panel = FlowLayoutPanel(Dock=DockStyle.Fill, Padding=Padding(10, 8, 0, 0))
        hi_panel.Controls.Add(Label(Text="Set Status for Highlight:", AutoSize=True, Margin=Padding(0, 7, 5, 0)))
        self.cmb_hi = ComboBox(Width=120, DataSource=[s[0] for s in STATUS_MAP], DropDownStyle=ComboBoxStyle.DropDownList)
        btn_apply = Button(Text="Apply to List", Width=120, Height=28, BackColor=Color.AliceBlue)
        btn_apply.Click += self.apply_highlight_status
        hi_panel.Controls.Add(self.cmb_hi); hi_panel.Controls.Add(btn_apply)
        
        # DataGridView
        self.dgv = DataGridView(Dock=DockStyle.Fill, RowHeadersVisible=False, AllowUserToAddRows=False,
                                SelectionMode=DataGridViewSelectionMode.FullRowSelect, BackgroundColor=Color.White)
        self.dgv.Columns.Add(DataGridViewCheckBoxColumn(Name="Selected", HeaderText="Update?", Width=70))
        self.dgv.Columns.Add(DataGridViewTextBoxColumn(Name="GroupKey", HeaderText="Category [Workset]", Width=340, ReadOnly=True))
        self.dgv.Columns.Add(DataGridViewTextBoxColumn(Name="Current", HeaderText="Current Status", Width=120, ReadOnly=True))
        self.dgv.Columns.Add(DataGridViewTextBoxColumn(Name="Count", HeaderText="Count", Width=70, ReadOnly=True))
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
        for key in sorted(self.grouped_elements.keys()):
            for status, el_list in self.split_by_status(self.grouped_elements[key]["elements"]).items():
                self.dgv.Rows.Add(False, key, status, len(el_list), "0")

    def split_by_status(self, elements):
        gs = {}
        for el in elements:
            val = "Not Found"
            if "READY" in self.lbl_status.Text:
                p = el.LookupParameter(PARAM_NAME)
                val = "Empty"
                if p and p.HasValue:
                    val = p.AsValueString() or str(p.AsDouble()) if p.StorageType == DB.StorageType.Double else str(p.AsInteger())
                    val = val.replace(".0","")
            if val not in gs: gs[val] = []
            gs[val].append(el)
        return gs

    def ok_click(self, s, e):
        self.final_data = []
        for r in self.dgv.Rows:
            if r.Cells["Selected"].Value:
                self.final_data.append({"GroupKey": r.Cells["GroupKey"].Value, "Old": r.Cells["Current"].Value, "New": r.Cells["NewStatus"].Value})
        if self.final_data: self.DialogResult = DialogResult.OK; self.Close()

def main():
    doc = __revit__.ActiveUIDocument.Document
    app = doc.Application
    
    # 1. จัดการ Parameter อัตโนมัติ 
    setup_status = setup_parameter(doc, app, PARAM_NAME, "Text", CAT_LIST)

    # 2. ถามผู้ใช้ว่าต้องการ Scope ไหน
    scope_options = ["1. เฉพาะหน้าต่างปัจจุบัน (Current View)", "2. ทั้งโครงการ (Entire Project)"]
    selected_scope = forms.CommandSwitchWindow.show(scope_options, message="เลือกระยะการค้นหาชิ้นส่วน (Scope):")
    
    if not selected_scope:
        return # ผู้ใช้กดยกเลิก
        
    is_current_view = "Current View" in selected_scope

    # 3. เตรียมรายชื่อ Category ทั้งหมดจาก CAT_LIST มาให้เลือก (แปลงเป็นชื่อที่อ่านง่าย)
    cat_options_dict = {}
    for ost_name in CAT_LIST:
        try:
            bic = getattr(DB.BuiltInCategory, ost_name)
            cat = doc.Settings.Categories.get_Item(bic)
            if cat:
                cat_options_dict[cat.Name] = ost_name
        except: pass
        
    cat_names = sorted(cat_options_dict.keys())
    
    if not cat_names:
        UI.TaskDialog.Show("G-Status", "ไม่พบข้อมูล Category ในระบบ")
        return
        
    # ดึงค่าที่เคยเลือกไว้
    config = script.get_config()
    prev_cats = getattr(config, "gstatus_selected_cats", [])
    
    class CatOption(forms.TemplateListItem):
        @property
        def name(self): return self.item
        
    options = []
    for c_name in cat_names:
        opt = CatOption(c_name)
        # ติ๊กเลือกล่วงหน้าจากความจำเดิม (ถ้ามี) หรือติ๊กทั้งหมดถ้าเพิ่งรันครั้งแรก
        if not prev_cats or c_name in prev_cats:
            opt.state = True
        options.append(opt)
        
    selected_cats = forms.SelectFromList.show(
        options,
        multiselect=True,
        title="เลือกหมวดหมู่ (Category) ที่ต้องการอัปเดต",
        button_name="ดำเนินการต่อ ➔"
    )
    
    if not selected_cats:
        return 
        
    # บันทึก config และเก็บชื่อ Category ที่เลือก
    sel_cat_names = [opt.name if hasattr(opt, 'name') else str(opt) for opt in selected_cats]
    config.gstatus_selected_cats = sel_cat_names
    script.save_config()
    
    # 4. ค้นหาชิ้นส่วนตาม Scope
    target_cats = get_target_categories()
    cats = List[DB.ElementId]([DB.ElementId(c) for c in target_cats])
    multi_cat_filter = DB.ElementMulticategoryFilter(cats)
    
    if is_current_view:
        elems = DB.FilteredElementCollector(doc, doc.ActiveView.Id).WherePasses(multi_cat_filter).WhereElementIsNotElementType().ToElements()
    else:
        elems = DB.FilteredElementCollector(doc).WherePasses(multi_cat_filter).WhereElementIsNotElementType().ToElements()
        
    # 5. กรองชิ้นส่วนให้เหลือเฉพาะ Category ที่เลือก
    filtered_elems = [e for e in elems if e.Category and e.Category.Name in sel_cat_names]
    
    if not filtered_elems:
        UI.TaskDialog.Show("G-Status", "ไม่มีชิ้นส่วนหลงเหลือหลังจากการกรอง Category (ไม่พบในโมเดล)")
        return
    
    # 6. จัดกลุ่มข้อมูล (Group By: Category + Workset)
    grouped = {}
    for el in filtered_elems:
        c_name = el.Category.Name if el.Category else "Unknown"
        ws = get_workset_name(doc, el)
        key = "{} [{}]".format(c_name, ws) # แสดงผลเป็น "หมวดหมู่ [Workset]"
        if key not in grouped: grouped[key] = {"elements": []}
        grouped[key]["elements"].append(el)

    # 7. เปิดหน้าต่าง UI หลัก
    scope_text = "Current View" if is_current_view else "Entire Project"
    form = ElementStatusForm(doc, grouped, setup_status, scope_text)
    
    if form.ShowDialog() == DialogResult.OK:
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
            for task in form.final_data:
                for el in grouped[task["GroupKey"]]["elements"]:
                    if el.GroupId != DB.ElementId.InvalidElementId:
                        if not varies_across_groups:
                            continue

                    p = el.LookupParameter(PARAM_NAME)
                    if p and not p.IsReadOnly:
                        cur = "Empty"
                        if p.HasValue:
                            cur = p.AsValueString() or str(p.AsDouble()) if p.StorageType == DB.StorageType.Double else str(p.AsInteger())
                            cur = cur.replace(".0","")
                        
                        if cur == task["Old"]:
                            new_val = task["New"]
                            try:
                                if p.StorageType == DB.StorageType.String: p.Set(str(new_val))
                                elif p.StorageType == DB.StorageType.Double: p.Set(float(new_val))
                                elif p.StorageType == DB.StorageType.Integer: p.Set(int(float(new_val)))
                                count += 1
                            except: pass
            tx.Commit()
            UI.TaskDialog.Show("G-Status", "อัปเดตสถานะเรียบร้อยแล้วจำนวน {} ชิ้นครับ".format(count))

if __name__ == "__main__":
    main()