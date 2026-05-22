# -*- coding: utf-8 -*-
from pyrevit import revit, forms, script
import json
import os
import clr

clr.AddReference('PresentationFramework')
from System.Windows.Controls import TreeViewItem, StackPanel, CheckBox, TextBlock, Orientation
from System.Windows import Thickness, VerticalAlignment
from System.Windows.Input import Key, Mouse, Cursors 

from Autodesk.Revit.DB import *
from System.Collections.Generic import List

doc = revit.doc
uidoc = revit.uidoc

# ==========================================
# 1. ระบบความจำตั้งค่า (Export Path)
# ==========================================
CONFIG_FILE = os.path.join(os.path.expanduser("~"), "pyrevit_superfilter_config.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {"export_path": "", "saved_selection": []}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)

config = load_config()

if not config.get("export_path"):
    selected_folder = forms.pick_folder(title="ไม่พบ Export Path: กรุณาเลือกโฟลเดอร์สำหรับทำงาน")
    if selected_folder:
        config["export_path"] = selected_folder
        save_config(config)
        forms.alert("ตั้งค่า Export Path เรียบร้อย: {}".format(selected_folder))
    else:
        forms.alert("คุณยังไม่ได้เลือก Export Path ฟังก์ชันบางอย่างอาจทำงานไม่สมบูรณ์", exitscript=False)


# ==========================================
# 2. คลาสควบคุม S-Filter (Ultimate)
# ==========================================
class SuperFilterWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        
        self.selection_ids = uidoc.Selection.GetElementIds()
        self.node_children = {}
        self.leaf_checkboxes = [] 
        
        # ผูกปุ่ม Actions หลัก
        if hasattr(self, 'btn_run'): self.btn_run.Click += self.run_select
        if hasattr(self, 'btn_isolate'): self.btn_isolate.Click += self.run_isolate
        if hasattr(self, 'btn_hide'): self.btn_hide.Click += self.run_hide
        if hasattr(self, 'btn_highlight'): self.btn_highlight.Click += self.run_highlight
        if hasattr(self, 'btn_filter_param'): self.btn_filter_param.Click += self.run_parameter_filter
            
        # ผูกปุ่ม Memory
        if hasattr(self, 'btn_save_mem'): self.btn_save_mem.Click += self.run_save_memory
        if hasattr(self, 'btn_restore_mem'): self.btn_restore_mem.Click += self.run_restore_memory
            
        # ผูกปุ่มควบคุม Tree View
        if hasattr(self, 'btn_check_all'): self.btn_check_all.Click += self.check_all_items
        if hasattr(self, 'btn_uncheck_all'): self.btn_uncheck_all.Click += self.uncheck_all_items
        if hasattr(self, 'btn_expand_all'): self.btn_expand_all.Click += self.expand_all_items
        if hasattr(self, 'btn_collapse_all'): self.btn_collapse_all.Click += self.collapse_all_items
        if hasattr(self, 'btn_invert_all'): self.btn_invert_all.Click += self.invert_all_items
            
        # ผูกการเปลี่ยนแปลงสถานะต่างๆ
        if hasattr(self, 'rad_current_sel'): self.rad_current_sel.Checked += self.refresh_tree
        if hasattr(self, 'rad_all_model'): self.rad_all_model.Checked += self.refresh_tree
        if hasattr(self, 'rad_visible_view'): self.rad_visible_view.Checked += self.refresh_tree
        if hasattr(self, 'rad_belong_view'): self.rad_belong_view.Checked += self.refresh_tree
        if hasattr(self, 'cmb_grouping'): self.cmb_grouping.SelectionChanged += self.refresh_tree
        if hasattr(self, 'chk_include_links'): self.chk_include_links.Click += self.refresh_tree
            
        if hasattr(self, 'txt_search'):
            self.txt_search.KeyDown += self.on_search_enter
            
        self.populate_categories()

    def on_search_enter(self, sender, args):
        if args.Key == Key.Enter:
            self.populate_categories()
            self.txt_search.Focus()
            self.txt_search.CaretIndex = len(self.txt_search.Text)

    def on_node_check(self, sender, args):
        is_checked = sender.IsChecked
        def cascade(parent_chk, state):
            if parent_chk in self.node_children:
                for child in self.node_children[parent_chk]:
                    child.IsChecked = state
                    cascade(child, state)
        cascade(sender, is_checked)

    def check_all_items(self, sender, args):
        if hasattr(self, 'root_chk'):
            self.root_chk.IsChecked = True
            self.on_node_check(self.root_chk, None)

    def uncheck_all_items(self, sender, args):
        if hasattr(self, 'root_chk'):
            self.root_chk.IsChecked = False
            self.on_node_check(self.root_chk, None)
            
    def invert_all_items(self, sender, args):
        for chk, _ in self.leaf_checkboxes:
            chk.IsChecked = not chk.IsChecked
            
    def _expand_nodes(self, items, state):
        for item in items:
            item.IsExpanded = state
            self._expand_nodes(item.Items, state)

    def expand_all_items(self, sender, args):
        self._expand_nodes(self.ui_treeview.Items, True)

    def collapse_all_items(self, sender, args):
        self._expand_nodes(self.ui_treeview.Items, False)
        if hasattr(self, 'root_item'): self.root_item.IsExpanded = True

    def refresh_tree(self, sender, args):
        self.populate_categories()

    def create_tree_node(self, name, count):
        item = TreeViewItem()
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        sp.Margin = Thickness(0, 2, 0, 2)
        
        chk = CheckBox()
        chk.IsChecked = False 
        chk.VerticalAlignment = VerticalAlignment.Center
        chk.Margin = Thickness(0, 0, 5, 0)
        chk.Click += self.on_node_check 
        
        txt = TextBlock()
        txt.Text = "{}   [{}]".format(name, count)
        txt.VerticalAlignment = VerticalAlignment.Center
        
        sp.Children.Add(chk)
        sp.Children.Add(txt)
        item.Header = sp
        return item, chk

    def populate_categories(self):
        if not hasattr(self, 'ui_treeview'): return
        
        Mouse.OverrideCursor = Cursors.Wait
        self.ui_treeview.Items.Clear()
        self.node_children = {}
        self.leaf_checkboxes = []
        elements = []
        
        try:
            # 1. รวบรวมข้อมูลโมเดล
            target_docs = [doc]
            if hasattr(self, 'chk_include_links') and self.chk_include_links.IsChecked:
                links = FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()
                for link in links:
                    ldoc = link.GetLinkDocument()
                    if ldoc: target_docs.append(ldoc)

            for t_doc in target_docs:
                try:
                    if hasattr(self, 'rad_current_sel') and self.rad_current_sel.IsChecked:
                        if self.selection_ids and not t_doc.IsLinked: 
                            elements.extend([t_doc.GetElement(eid) for eid in self.selection_ids])
                    elif hasattr(self, 'rad_visible_view') and self.rad_visible_view.IsChecked:
                        if not t_doc.IsLinked:
                            elements.extend([el for el in FilteredElementCollector(t_doc, doc.ActiveView.Id).WhereElementIsNotElementType().ToElements() if el.Category])
                        else:
                            elements.extend([el for el in FilteredElementCollector(t_doc).WhereElementIsNotElementType().ToElements() if el.Category])
                    elif hasattr(self, 'rad_belong_view') and self.rad_belong_view.IsChecked:
                        if not t_doc.IsLinked:
                            elements.extend([el for el in FilteredElementCollector(t_doc, doc.ActiveView.Id).WhereElementIsNotElementType().ToElements() if el.Category and el.ViewSpecific])
                    elif hasattr(self, 'rad_all_model') and self.rad_all_model.IsChecked:
                        elements.extend([el for el in FilteredElementCollector(t_doc).WhereElementIsNotElementType().ToElements() if el.Category])
                except:
                    pass

            search_text = self.txt_search.Text.lower() if hasattr(self, 'txt_search') else ""
            group_mode = 0
            if hasattr(self, 'cmb_grouping'): group_mode = self.cmb_grouping.SelectedIndex
                
            tree_dict = {}
            total_elements = len(elements)
            
            if total_elements == 0:
                if hasattr(self, 'lbl_status_count'): self.lbl_status_count.Text = "0"
                return

            # ✨ ฟีเจอร์: Progress Bar (แถบโหลดข้อมูล) ทำงานร่วมกับการจัดกลุ่ม
            with forms.ProgressBar(title='S-Filter: กำลังจัดกลุ่มข้อมูลโปรดรอสักครู่...', cancellable=False) as pb:
                for i, el in enumerate(elements):
                    # อัปเดตแถบโหลดทุกๆ 50 ชิ้น ป้องกันโปรแกรมค้าง
                    if i % 50 == 0:
                        pb.update_progress(i, total_elements)
                        
                    cat_name = el.Category.Name if el.Category else "Uncategorized"
                    type_name = "{} : {}".format(el.Symbol.Family.Name, el.Name) if (isinstance(el, FamilyInstance) and el.Symbol) else getattr(el, 'Name', type(el).__name__)
                    if not type_name: type_name = "Unknown Type"
                    
                    if search_text and search_text not in cat_name.lower() and search_text not in type_name.lower():
                        continue
                        
                    lvl_name = "No Level"
                    if el.LevelId != ElementId.InvalidElementId:
                        el_doc = el.Document 
                        lvl_obj = el_doc.GetElement(el.LevelId) 
                        if lvl_obj: lvl_name = lvl_obj.Name
                        
                    ws_name = "No Workset"
                    if doc.IsWorkshared and hasattr(el, 'WorksetId'):
                        try:
                            el_doc = el.Document
                            wt = el_doc.GetWorksetTable()
                            ws_obj = wt.GetWorkset(el.WorksetId)
                            if ws_obj: ws_name = ws_obj.Name
                        except: pass

                    if group_mode == 0:
                        key1, key2 = cat_name, type_name
                    elif group_mode == 1:
                        key1, key2 = lvl_name, "{} > {}".format(cat_name, type_name)
                    elif group_mode == 2:
                        key1, key2 = ws_name, "{} > {}".format(cat_name, type_name)
                        
                    if key1 not in tree_dict: tree_dict[key1] = {}
                    if key2 not in tree_dict[key1]: tree_dict[key1][key2] = []
                    tree_dict[key1][key2].append(el.Id)

            # นำข้อมูลที่จัดกลุ่มเสร็จแล้วไปสร้างหน้าต่าง TreeView
            if hasattr(self, 'lbl_status_count'): self.lbl_status_count.Text = str(len(elements))
            if not tree_dict: return

            self.root_item, self.root_chk = self.create_tree_node("All Elements", sum([len(ids) for c in tree_dict.values() for ids in c.values()]))
            self.ui_treeview.Items.Add(self.root_item)
            self.node_children[self.root_chk] = []
            
            for key1 in sorted(tree_dict.keys()):
                k1_eids = [eid for t_list in tree_dict[key1].values() for eid in t_list]
                k1_item, k1_chk = self.create_tree_node(key1, len(k1_eids))
                self.node_children[self.root_chk].append(k1_chk)
                self.node_children[k1_chk] = []
                self.root_item.Items.Add(k1_item)
                
                for key2 in sorted(tree_dict[key1].keys()):
                    k2_eids = tree_dict[key1][key2]
                    k2_item, k2_chk = self.create_tree_node(key2, len(k2_eids))
                    self.node_children[k1_chk].append(k2_chk)
                    self.leaf_checkboxes.append((k2_chk, k2_eids)) 
                    k1_item.Items.Add(k2_item)
                    
            self.root_item.IsExpanded = True
            
        finally:
            Mouse.OverrideCursor = None 

    def _get_id_val(self, eid):
        if hasattr(eid, "Value"): return eid.Value
        if hasattr(eid, "IntegerValue"): return eid.IntegerValue
        return eid 

    def get_final_elements(self):
        final_eids = {} 
        for chk, eids in self.leaf_checkboxes:
            if chk.IsChecked:
                for eid in eids:
                    val = self._get_id_val(eid)
                    final_eids[val] = eid
                
        if not final_eids: return List[ElementId]()
        
        base_values = list(final_eids.keys()) 
        for val in base_values:
            eid = final_eids[val]
            el = doc.GetElement(eid)
            if not el: continue
            
            if self.chk_exp_host.IsChecked and hasattr(el, "Host") and el.Host:
                h_id = el.Host.Id
                final_eids[self._get_id_val(h_id)] = h_id
                
            if self.chk_exp_level.IsChecked and el.LevelId != ElementId.InvalidElementId:
                if el.Category:
                    lv_elements = FilteredElementCollector(doc).WhereElementIsNotElementType().OfCategoryId(el.Category.Id).ToElements()
                    for l_el in lv_elements:
                        if l_el.LevelId == el.LevelId:
                            final_eids[self._get_id_val(l_el.Id)] = l_el.Id
                            
            if self.chk_exp_workset.IsChecked and doc.IsWorkshared:
                if el.Category:
                    ws_id = el.WorksetId
                    ws_elements = FilteredElementCollector(doc).WhereElementIsNotElementType().OfCategoryId(el.Category.Id).ToElements()
                    for w_el in ws_elements:
                        if w_el.WorksetId == ws_id:
                            final_eids[self._get_id_val(w_el.Id)] = w_el.Id

        out_list = List[ElementId]()
        for eid in final_eids.values(): out_list.Add(eid)
        return out_list

    # --- ฟังก์ชัน Memory ---
    def run_save_memory(self, sender, args):
        ids = self.get_final_elements()
        if not ids or ids.Count == 0:
            forms.alert("กรุณาติ๊กเลือกวัตถุใน Tree View ก่อนกดบันทึกค่ะ")
            return
        config["saved_selection"] = [self._get_id_val(eid) for eid in ids]
        save_config(config)
        forms.alert("บันทึกวัตถุลงหน่วยความจำแล้วจำนวน {} ชิ้น!".format(ids.Count))

    def run_restore_memory(self, sender, args):
        saved_ids = config.get("saved_selection", [])
        if not saved_ids:
            forms.alert("ยังไม่มีการบันทึกข้อมูลในหน่วยความจำค่ะ")
            return
        restore_list = List[ElementId]()
        for val in saved_ids:
            try:
                eid = ElementId(val)
                if doc.GetElement(eid): restore_list.Add(eid)
            except: pass
        if restore_list.Count > 0:
            uidoc.Selection.SetElementIds(restore_list)
            self.Close()
        else:
            forms.alert("วัตถุที่เคยจำไว้ ไม่มีอยู่ในโมเดลนี้แล้วค่ะ")

    # --- ปุ่ม Action ต่างๆ ---
    def run_select(self, sender, args):
        ids = self.get_final_elements()
        if ids and ids.Count > 0: 
            try:
                uidoc.Selection.SetElementIds(ids)
            except:
                forms.alert("คำเตือน: โมเดลที่คุณเลือกมีส่วนที่มาจากไฟล์ Link โปรแกรมไม่สามารถ Select วัตถุข้ามไฟล์ได้ แนะนำให้ใช้ปุ่ม Highlight แทนค่ะ")
                return
        self.Close()

    def run_isolate(self, sender, args):
        ids = self.get_final_elements()
        if ids and ids.Count > 0:
            try:
                uidoc.Selection.SetElementIds(ids)
                t = Transaction(doc, "S-Filter Isolate")
                t.Start()
                doc.ActiveView.IsolateElementsTemporary(ids)
                t.Commit()
            except: pass 
        self.Close()

    def run_hide(self, sender, args):
        ids = self.get_final_elements()
        if ids and ids.Count > 0:
            try:
                t = Transaction(doc, "S-Filter Hide")
                t.Start()
                doc.ActiveView.HideElementsTemporary(ids)
                t.Commit()
            except: pass
        self.Close()
        
    def run_highlight(self, sender, args):
        ids = self.get_final_elements()
        if ids and ids.Count > 0:
            try:
                color = Color(255, 235, 59) 
                ogs = OverrideGraphicSettings()
                ogs.SetProjectionLineColor(color)
                ogs.SetProjectionLineWeight(8) 
                ogs.SetCutLineColor(color)
                ogs.SetSurfaceTransparency(30)
                
                t = Transaction(doc, "S-Filter Highlight")
                t.Start()
                for eid in ids:
                    doc.ActiveView.SetElementOverrides(eid, ogs)
                t.Commit()
            except: pass
        self.Close()

    def run_parameter_filter(self, sender, args):
        self.Hide() 
        
        ids = self.get_final_elements()
        if not ids or ids.Count == 0:
            forms.alert("กรุณาติ๊กเลือกวัตถุใน Tree View ก่อนค่ะ")
            self.ShowDialog()
            return
            
        elements = [doc.GetElement(eid) for eid in ids if doc.GetElement(eid)]
        if not elements:
            self.ShowDialog()
            return

        param_names = set()
        for el in elements:
            for p in el.Parameters:
                if p.Definition.Name: param_names.add(p.Definition.Name)
                
        chosen_param = forms.SelectFromList.show(sorted(list(param_names)), title="Step 1: เลือก Parameter", multiselect=False)
        if not chosen_param:
            self.ShowDialog()
            return
            
        operators = ["Equals (=)  เท่ากับ", "Contains (มีคำว่า)", "Greater Than (>) มากกว่า", "Less Than (<) น้อยกว่า"]
        op = forms.SelectFromList.show(operators, title="Step 2: เลือกเงื่อนไข", multiselect=False)
        if not op:
            self.ShowDialog()
            return
            
        val = forms.ask_for_string(prompt="Step 3: ใส่ค่าตัวเลขหรือข้อความที่ต้องการเปรียบเทียบ", title="Rule-Based Filter")
        if val is None:
            self.ShowDialog()
            return
            
        new_selection = List[ElementId]()
        total_elements = len(elements)
        
        # ✨ ฟีเจอร์: Progress Bar (แถบโหลดสำหรับตอนกรอง Parameter ขั้นสูง)
        with forms.ProgressBar(title="S-Filter: กำลังประมวลผลเงื่อนไข Parameter...", cancellable=False) as pb:
            for i, el in enumerate(elements):
                if i % 10 == 0:
                    pb.update_progress(i, total_elements)
                    
                p = el.LookupParameter(chosen_param)
                if not p or not p.HasValue: continue
                
                p_val = p.AsValueString() or p.AsString() or str(p.AsInteger()) or str(p.AsDouble())
                
                match = False
                try:
                    if "Equals" in op:
                        match = (str(val).lower() == str(p_val).lower())
                    elif "Contains" in op:
                        match = (str(val).lower() in str(p_val).lower())
                    elif "Greater" in op:
                        match = float(p_val) > float(val)
                    elif "Less" in op:
                        match = float(p_val) < float(val)
                except:
                    pass 
                    
                if match:
                    new_selection.Add(el.Id)
                
        if new_selection.Count > 0:
            try:
                uidoc.Selection.SetElementIds(new_selection)
                forms.alert("S-Filter: พบวัตถุที่ตรงตามเงื่อนไขจำนวน {} ชิ้น".format(new_selection.Count))
            except:
                forms.alert("พบวัตถุ {} ชิ้น แต่อาจมีวัตถุจากไฟล์ Link ผสมอยู่ จึงไม่สามารถ Select ได้โดยตรงค่ะ".format(new_selection.Count))
            self.Close()
        else:
            forms.alert("ไม่พบวัตถุที่ตรงตามเงื่อนไขเลยค่ะ")
            self.ShowDialog()

if __name__ == '__main__':
    xaml_path = script.get_bundle_file('ui.xaml')
    window = SuperFilterWindow(xaml_path)
    window.ShowDialog()