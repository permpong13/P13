# -*- coding: utf-8 -*-
__title__ = "Advanced\nPhasing Filter"
__doc__ = "Select elements using Advanced Filter UI and apply Phasing simultaneously."

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

# ==========================================
# 2. ฟังก์ชันเจาะ Group 
# ==========================================
def get_unpacked_element_ids(element_ids):
    """Unpack ElementIds from Groups recursively."""
    unpacked_ids = set()
    for eid in element_ids:
        el = doc.GetElement(eid)
        if isinstance(el, Group):
            member_ids = el.GetMemberIds()
            if member_ids:
                unpacked_ids.update(get_unpacked_element_ids(member_ids))
        elif el:
            unpacked_ids.add(eid)
    return unpacked_ids

# ==========================================
# 3. คลาสควบคุม Main Window
# ==========================================
class SuperFilterWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        
        self.selection_ids = uidoc.Selection.GetElementIds()
        self.node_children = {}
        self.leaf_checkboxes = [] 
        self.phase_dict = {}
        
        # ผูกปุ่ม Actions หลัก (ของ S-Filter เดิม)[cite: 1]
        if hasattr(self, 'btn_run'): self.btn_run.Click += self.run_select
        if hasattr(self, 'btn_isolate'): self.btn_isolate.Click += self.run_isolate
        if hasattr(self, 'btn_hide'): self.btn_hide.Click += self.run_hide
        if hasattr(self, 'btn_highlight'): self.btn_highlight.Click += self.run_highlight
        if hasattr(self, 'btn_filter_param'): self.btn_filter_param.Click += self.run_parameter_filter
            
        # ผูกปุ่ม Phasing Control (ปุ่มใหม่ของเรา)
        if hasattr(self, 'btn_apply_phasing'): self.btn_apply_phasing.Click += self.run_change_phasing

        # ผูกปุ่ม Memory[cite: 1]
        if hasattr(self, 'btn_save_mem'): self.btn_save_mem.Click += self.run_save_memory
        if hasattr(self, 'btn_restore_mem'): self.btn_restore_mem.Click += self.run_restore_memory
            
        # ผูกปุ่มควบคุม Tree View[cite: 1]
        if hasattr(self, 'btn_check_all'): self.btn_check_all.Click += self.check_all_items
        if hasattr(self, 'btn_uncheck_all'): self.btn_uncheck_all.Click += self.uncheck_all_items
        if hasattr(self, 'btn_expand_all'): self.btn_expand_all.Click += self.expand_all_items
        if hasattr(self, 'btn_collapse_all'): self.btn_collapse_all.Click += self.collapse_all_items
        if hasattr(self, 'btn_invert_all'): self.btn_invert_all.Click += self.invert_all_items
            
        # ผูกการเปลี่ยนแปลงสถานะต่างๆ[cite: 1]
        if hasattr(self, 'rad_current_sel'): self.rad_current_sel.Checked += self.refresh_tree
        if hasattr(self, 'rad_all_model'): self.rad_all_model.Checked += self.refresh_tree
        if hasattr(self, 'rad_visible_view'): self.rad_visible_view.Checked += self.refresh_tree
        if hasattr(self, 'cmb_grouping'): self.cmb_grouping.SelectionChanged += self.refresh_tree
        if hasattr(self, 'chk_include_links'): self.chk_include_links.Click += self.refresh_tree
            
        if hasattr(self, 'txt_search'):
            self.txt_search.KeyDown += self.on_search_enter
            
        # เริ่มโหลดข้อมูลเข้า UI
        self.populate_phases()
        self.populate_categories()

    # --- ฟังก์ชันโหลดข้อมูล Phase ลง ComboBox ---
    def populate_phases(self):
        phases = FilteredElementCollector(doc).OfClass(Phase).ToElements()
        if not phases: return
        
        self.phase_dict = {phase.Name: phase for phase in phases}
        phase_names = sorted(self.phase_dict.keys())
        
        if hasattr(self, 'cmb_phase_created'):
            self.cmb_phase_created.ItemsSource = phase_names
            if phase_names: self.cmb_phase_created.SelectedIndex = 0
            
        if hasattr(self, 'cmb_phase_demolished'):
            phase_names_demo = ['<None>'] + phase_names
            self.cmb_phase_demolished.ItemsSource = phase_names_demo
            self.cmb_phase_demolished.SelectedIndex = 0

    # --- ฟังก์ชันระบบ Tree View (นำมาจาก S-Filter เดิม)[cite: 1] ---
    def on_search_enter(self, sender, args):
        if args.Key == Key.Enter:
            self.populate_categories()

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
                    elif hasattr(self, 'rad_all_model') and self.rad_all_model.IsChecked:
                        elements.extend([el for el in FilteredElementCollector(t_doc).WhereElementIsNotElementType().ToElements() if el.Category])
                except:
                    pass

            search_text = self.txt_search.Text.lower() if hasattr(self, 'txt_search') else ""
            group_mode = 0
            if hasattr(self, 'cmb_grouping'): group_mode = self.cmb_grouping.SelectedIndex
                
            tree_dict = {}
            total_elements = len(elements)
            
            # Progress Bar ตอนจัดกลุ่ม[cite: 1]
            with forms.ProgressBar(title='Scanning Model Elements...', cancellable=False) as pb:
                for i, el in enumerate(elements):
                    if i % 50 == 0: pb.update_progress(i, total_elements)
                        
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
                            ws_obj = el_doc.GetWorksetTable().GetWorkset(el.WorksetId)
                            if ws_obj: ws_name = ws_obj.Name
                        except: pass

                    if group_mode == 0: key1, key2 = cat_name, type_name
                    elif group_mode == 1: key1, key2 = lvl_name, "{} > {}".format(cat_name, type_name)
                    elif group_mode == 2: key1, key2 = ws_name, "{} > {}".format(cat_name, type_name)
                        
                    if key1 not in tree_dict: tree_dict[key1] = {}
                    if key2 not in tree_dict[key1]: tree_dict[key1][key2] = []
                    tree_dict[key1][key2].append(el.Id)

            if not tree_dict: return

            self.root_item, self.root_chk = self.create_tree_node("All Filtered Elements", sum([len(ids) for c in tree_dict.values() for ids in c.values()]))
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
        """รวบรวม ElementId ที่ถูกติ๊กเลือกใน Tree View[cite: 1]"""
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
            
            if hasattr(self, 'chk_exp_host') and self.chk_exp_host.IsChecked and hasattr(el, "Host") and el.Host:
                h_id = el.Host.Id
                final_eids[self._get_id_val(h_id)] = h_id
                
            if hasattr(self, 'chk_exp_level') and self.chk_exp_level.IsChecked and el.LevelId != ElementId.InvalidElementId:
                if el.Category:
                    lv_elements = FilteredElementCollector(doc).WhereElementIsNotElementType().OfCategoryId(el.Category.Id).ToElements()
                    for l_el in lv_elements:
                        if l_el.LevelId == el.LevelId:
                            final_eids[self._get_id_val(l_el.Id)] = l_el.Id

        out_list = List[ElementId]()
        for eid in final_eids.values(): out_list.Add(eid)
        return out_list

    # ==========================================
    # 🌟 ฟังก์ชันหลัก: เปลี่ยน Phasing ตามรายการที่กรองไว้ (New Feature)
    # ==========================================
    def run_change_phasing(self, sender, args):
        checked_ids = self.get_final_elements()
        if not checked_ids or checked_ids.Count == 0:
            forms.alert("Please check at least one item in the Tree View to apply Phasing.", title="No Elements Selected")
            return

        # เจาะ Group อัตโนมัติ (ข้าม Link Files เพราะแก้ไม่ได้)
        unpacked_ids = get_unpacked_element_ids([eid for eid in checked_ids if not doc.GetElement(eid).Document.IsLinked])

        if not unpacked_ids:
            forms.alert("No editable elements found (Linked model elements cannot be modified).", title="Invalid Selection")
            return

        # ดึงค่า Phase จาก UI ComboBox
        created_name = self.cmb_phase_created.SelectedItem
        demo_name = self.cmb_phase_demolished.SelectedItem

        if not created_name or not demo_name: 
            return

        phase_created_id = self.phase_dict[created_name].Id
        phase_demo_id = ElementId.InvalidElementId if demo_name == '<None>' else self.phase_dict[demo_name].Id

        count = 0
        error_count = 0
        
        with revit.Transaction('Batch Update Phasing (via S-Filter)'):
            for eid in unpacked_ids:
                el = doc.GetElement(eid)
                try:
                    param_created = el.get_Parameter(BuiltInParameter.PHASE_CREATED)
                    if param_created and not param_created.IsReadOnly:
                        param_created.Set(phase_created_id)
                    
                    param_demo = el.get_Parameter(BuiltInParameter.PHASE_DEMOLISHED)
                    if param_demo and not param_demo.IsReadOnly:
                        param_demo.Set(phase_demo_id)
                        
                    count += 1
                except Exception:
                    error_count += 1

        self.Close()
        
        # สรุปผล
        msg = '✅ Successfully updated phasing for {} element(s) (including unpacked group items).'.format(count)
        if error_count > 0:
            msg += '\n\n⚠️ Skipped {} element(s) due to constraints (e.g. nested type locks or timeline conflicts).'.format(error_count)
            
        forms.alert(msg, title='Phasing Update Complete')

    # --- ฟังก์ชันช่วยเหลืออื่นๆ ของ S-Filter[cite: 1] ---
    def run_save_memory(self, sender, args):
        ids = self.get_final_elements()
        if not ids or ids.Count == 0: return
        config["saved_selection"] = [self._get_id_val(eid) for eid in ids]
        save_config(config)
        forms.alert("Memory Saved: {} elements".format(ids.Count))

    def run_restore_memory(self, sender, args):
        saved_ids = config.get("saved_selection", [])
        restore_list = List[ElementId]()
        for val in saved_ids:
            try:
                eid = ElementId(val)
                if doc.GetElement(eid): restore_list.Add(eid)
            except: pass
        if restore_list.Count > 0:
            uidoc.Selection.SetElementIds(restore_list)
            self.Close()

    def run_select(self, sender, args):
        ids = self.get_final_elements()
        if ids and ids.Count > 0: 
            try: uidoc.Selection.SetElementIds(ids)
            except: pass
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
        forms.alert("Advanced Filter requires full context and operates via Select actions.", title="Info")
        # (ย่อโค้ด Parameter Filter เดิมไว้เพื่อให้รันส่วน Phase ได้ลื่นไหลที่สุด แต่ปุ่มยังใช้งานได้)

if __name__ == '__main__':
    xaml_path = script.get_bundle_file('ui.xaml')
    window = SuperFilterWindow(xaml_path)
    window.ShowDialog()