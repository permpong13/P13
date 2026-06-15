# -*- coding: utf-8 -*-
__title__ = 'Smart Copy\nViews'
__author__ = 'Permpong Taweekul (P13)'
__doc__ = 'Advanced tool to copy Legends & Drafting Views with Custom XAML UI'

import sys
import os
import clr
clr.AddReference('PresentationFramework')
from pyrevit import revit, DB, script, forms, HOST_APP
from System.Collections.Generic import List
from System.Windows.Media import Brushes

cfg = script.get_config()
out = script.get_output()

class CopyUseDestination(DB.IDuplicateTypeNamesHandler):
    def OnDuplicateTypeNamesFound(self, args):
        return DB.DuplicateTypeAction.UseDestinationTypes

def get_unique_name(existing_names, base_name):
    new_name = base_name
    counter = 1
    while new_name in existing_names:
        new_name = "{} ({})".format(base_name, counter)
        counter += 1
    return new_name

# --- สร้าง Class สำหรับควบคุมหน้าต่าง XAML ---
# Source view collection helpers.
def get_element_id_value(element_id):
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue

def get_view_display_name(view, used_names):
    view_name = revit.query.get_name(view)
    display_name = view_name
    if display_name in used_names:
        display_name = "{} <{}>".format(view_name, get_element_id_value(view.Id))
    used_names.add(display_name)
    return display_name

def get_copyable_source_views(doc):
    source_view_types = [DB.ViewType.Legend, DB.ViewType.DraftingView]
    views = []
    for view in DB.FilteredElementCollector(doc).OfClass(DB.View).WhereElementIsNotElementType():
        if view.IsTemplate:
            continue
        if view.ViewType in source_view_types:
            views.append(view)
    return sorted(views, key=lambda v: (str(v.ViewType), revit.query.get_name(v).lower(), get_element_id_value(v.Id)))

# XAML window controller.
class CustomUI(forms.WPFWindow):
    def __init__(self, xaml_file_name, open_docs, source_views):
        forms.WPFWindow.__init__(self, xaml_file_name)
        
        # จัดการข้อมูลให้อยู่ในรูปแบบ Dictionary เพื่อง่ายต่อการดึงค่ากลับ
        self.doc_dict = {d.Title: d for d in open_docs}
        
        # แยก Legend และ Drafting ออกจากกัน
        used_legend_names = set()
        used_drafting_names = set()
        self.legend_dict = {}
        self.drafting_dict = {}
        for view in source_views:
            if view.ViewType == DB.ViewType.Legend:
                self.legend_dict[get_view_display_name(view, used_legend_names)] = view
            elif view.ViewType == DB.ViewType.DraftingView:
                self.drafting_dict[get_view_display_name(view, used_drafting_names)] = view
        
        # ส่งรายชื่อเข้า ListBox ใน XAML เริ่มต้น
        self.DestDocsList.ItemsSource = sorted(self.doc_dict.keys())
        self.LegendViewsList.ItemsSource = sorted(self.legend_dict.keys())
        self.DraftingViewsList.ItemsSource = sorted(self.drafting_dict.keys())
        
        # โหลดการตั้งค่าโหมดเดิมที่เคยบันทึกไว้
        saved_mode_index = cfg.get_option('p13_view_copymode_index', 0)
        self.ModeCombo.SelectedIndex = int(saved_mode_index)
        
        # ผูก Event สำหรับระบบ Search
        self.DestSearch.TextChanged += self.SearchDest
        self.LegendSearch.TextChanged += self.SearchLegend
        self.DraftingSearch.TextChanged += self.SearchDrafting

        self.is_executed = False
        self.selected_dest_docs = []
        self.selected_src_views = []
        self.selected_mode_index = 0
        self.ShowDialog()

    # --- ฟังก์ชันค้นหา (Search Filters) ---
    def SearchDest(self, sender, args):
        query = self.DestSearch.Text.lower()
        if "search" in query: return # ข้ามหากเป็น Placeholder
        self.DestDocsList.ItemsSource = [k for k in sorted(self.doc_dict.keys()) if query in k.lower()]

    def SearchLegend(self, sender, args):
        query = self.LegendSearch.Text.lower()
        if "search" in query: return
        self.LegendViewsList.ItemsSource = [k for k in sorted(self.legend_dict.keys()) if query in k.lower()]

    def SearchDrafting(self, sender, args):
        query = self.DraftingSearch.Text.lower()
        if "search" in query: return
        self.DraftingViewsList.ItemsSource = [k for k in sorted(self.drafting_dict.keys()) if query in k.lower()]

    # --- ฟังก์ชันลบ/เพิ่ม Placeholder ---
    def RemovePlaceholder(self, sender, args):
        if "Search" in sender.Text:
            sender.Text = ""
            sender.Foreground = Brushes.White

    def AddPlaceholder(self, sender, args):
        # ใช้ strip() ของ Python ในการเช็คค่าว่าง เพื่อหลีกเลี่ยงบัค
        if not sender.Text.strip():
            if sender.Name == "DestSearch": sender.Text = "Search Destination..."
            elif sender.Name == "LegendSearch": sender.Text = "Search Legends..."
            elif sender.Name == "DraftingSearch": sender.Text = "Search Drafting Views..."
            sender.Foreground = Brushes.Gray

    # ฟังก์ชันเมื่อกดปุ่มใน XAML
    def ExecuteTransfer(self, sender, args):
        # ล้างค่าเก่าทิ้งก่อนเสมอ ป้องกันการกดปุ่มซ้ำแล้วส่งค่าผิดพลาด
        self.selected_dest_docs = []
        self.selected_src_views = []

        # ดึงค่าไฟล์ปลายทางที่ถูกเลือก
        for item in self.DestDocsList.SelectedItems:
            self.selected_dest_docs.append(self.doc_dict[item])
            
        # ดึงค่า View ต้นทางที่ถูกเลือก จากทั้ง 2 หน้าต่าง
        for item in self.LegendViewsList.SelectedItems:
            self.selected_src_views.append(self.legend_dict[item])
            
        for item in self.DraftingViewsList.SelectedItems:
            self.selected_src_views.append(self.drafting_dict[item])
            
        self.selected_mode_index = self.ModeCombo.SelectedIndex
        
        # ตรวจสอบว่าผู้ใช้เลือกข้อมูลครบหรือไม่
        if not self.selected_dest_docs:
            forms.alert('SYSTEM ERROR: No Destination Node selected.', title='P13 Warning')
            return
        if not self.selected_src_views:
            forms.alert('SYSTEM ERROR: No Source Data selected.', title='P13 Warning')
            return
            
        self.is_executed = True
        self.Close() # ปิดหน้าต่าง UI เพื่อรันโค้ดหลักต่อ

def main():
    src_doc = revit.doc

    # หาไฟล์ที่กำลังเปิดอยู่ทั้งหมด (ยกเว้นไฟล์ปัจจุบัน)
    open_docs = [d for d in revit.docs if not d.IsLinked and d.Title != src_doc.Title]
    if not open_docs:
        forms.alert("No other open documents found to transfer to.", title="P13 System")
        sys.exit(0)

    # หา Legends และ Drafting ทั้งหมดในไฟล์ปัจจุบัน
    source_views = get_copyable_source_views(src_doc)
    
    if not source_views:
        forms.alert("No Legends or Drafting Views found in this document.", title="P13 System")
        sys.exit(0)

    # หาตำแหน่งโฟลเดอร์ปัจจุบันที่สคริปต์นี้วางอยู่
    current_dir = os.path.dirname(__file__)
    xaml_path = os.path.join(current_dir, 'ui.xaml')

    # เรียกใช้โดยระบุ Path เต็ม
    ui = CustomUI(xaml_path, open_docs, source_views)
    
    # ถ้ายกเลิกหรือไม่กดปุ่ม Execute ให้จบการทำงาน
    if not ui.is_executed:
        sys.exit(0)
        
    # ดึงข้อมูลจาก UI มาประมวลผล
    dest_docs = ui.selected_dest_docs
    views = ui.selected_src_views
    mode_idx = ui.selected_mode_index
    
    # บันทึกโหมดที่เลือกลง Config
    cfg.p13_view_copymode_index = mode_idx
    script.save_config()
    
    # กำหนดโหมดตาม Index
    selected_mode = 'Keep Original'
    if mode_idx == 1: selected_mode = 'Convert to Drafting'
    elif mode_idx == 2: selected_mode = 'Convert to Legend'

    report_data = []

    # ป้องกัน ZeroDivisionError ด้วยการตรวจจับจำนวน Task ก่อน
    total_tasks = len(dest_docs) * len(views)
    if total_tasks == 0:
        forms.alert("SYSTEM ERROR: Total tasks calculated as 0. Transfer aborted.", title="P13 System")
        sys.exit(0)

    # โค้ดหลักในการคัดลอก (ทำงานเหมือนเดิม 100%)
    with forms.ProgressBar(title='[P13] NEURAL NETWORK TRANSFER IN PROGRESS... ({value} of {max_value})') as pb:
        current_task = 0
        
        for dest_doc in dest_docs:
            dest_all_views = revit.query.get_all_views(doc=dest_doc)
            existing_legend_names = [v.Name for v in dest_all_views if v.ViewType == DB.ViewType.Legend]
            existing_drafting_names = [v.Name for v in dest_all_views if v.ViewType == DB.ViewType.DraftingView]
            
            legends_in_dest = [v for v in dest_all_views if v.ViewType == DB.ViewType.Legend]
            file_link = dest_doc.Title

            with revit.Transaction('P13 Smart Copy Views', doc=dest_doc):
                cp_options = DB.CopyPasteOptions()
                cp_options.SetDuplicateTypeNamesHandler(CopyUseDestination())

                for src_view in views:
                    current_task += 1
                    pb.update_progress(current_task, total_tasks)
                    base_name = revit.query.get_name(src_view)
                    
                    target_is_legend = False
                    target_is_drafting = False
                    
                    if selected_mode == 'Keep Original':
                        if src_view.ViewType == DB.ViewType.Legend: target_is_legend = True
                        elif src_view.ViewType == DB.ViewType.DraftingView: target_is_drafting = True
                    elif selected_mode == 'Convert to Drafting':
                        target_is_drafting = True
                    elif selected_mode == 'Convert to Legend':
                        target_is_legend = True

                    # [LEGEND TARGET]
                    if target_is_legend:
                        unique_name = get_unique_name(existing_legend_names, base_name)
                        
                        if src_view.ViewType == DB.ViewType.Legend:
                            try:
                                view_ids = List[DB.ElementId]()
                                view_ids.Add(src_view.Id)
                                copied_ids = DB.ElementTransformUtils.CopyElements(src_doc, view_ids, dest_doc, DB.Transform.Identity, cp_options)
                                
                                new_view_id = None
                                for c_id in copied_ids:
                                    new_view = dest_doc.GetElement(c_id)
                                    if isinstance(new_view, DB.View):
                                        if new_view.Name != unique_name:
                                            new_view.Name = unique_name
                                        new_view_id = new_view.Id
                                        
                                clickable_name = out.linkify(new_view_id, title=unique_name) if new_view_id else unique_name
                                report_data.append([file_link, base_name, clickable_name, 'Legend -> Legend', '🟢 SUCCESS', '-'])
                                existing_legend_names.append(unique_name)
                            except Exception as e:
                                report_data.append([file_link, base_name, '-', 'Legend -> Legend', '🔴 FAILED', str(e)])
                                
                        elif src_view.ViewType == DB.ViewType.DraftingView:
                            if not legends_in_dest:
                                report_data.append([file_link, base_name, '-', 'Drafting -> Legend', '🔴 FAILED', 'No Base Legend in Dest. Node'])
                                continue
                                
                            try:
                                new_view_id = legends_in_dest[0].Duplicate(DB.ViewDuplicateOption.Duplicate)
                                new_view = dest_doc.GetElement(new_view_id)
                                new_view.Name = unique_name
                                new_view.Scale = src_view.Scale
                                
                                elements_to_delete = [el.Id for el in DB.FilteredElementCollector(dest_doc, new_view_id).WhereElementIsNotElementType() if el.Category and el.Id != new_view_id]
                                for el_id in elements_to_delete:
                                    try: dest_doc.Delete(el_id)
                                    except: pass
                                    
                                elements_to_copy = [el.Id for el in DB.FilteredElementCollector(src_doc, src_view.Id).WhereElementIsNotElementType() if el.Category and el.Id != src_view.Id]
                                if elements_to_copy:
                                    copied_elements = DB.ElementTransformUtils.CopyElements(src_view, List[DB.ElementId](elements_to_copy), new_view, None, cp_options)
                                    for d_id, s_id in zip(copied_elements, elements_to_copy):
                                        try: new_view.SetElementOverrides(d_id, src_view.GetElementOverrides(s_id))
                                        except: pass
                                        
                                clickable_name = out.linkify(new_view_id, title=unique_name)
                                report_data.append([file_link, base_name, clickable_name, 'Drafting -> Legend', '🟢 SUCCESS', '-'])
                                existing_legend_names.append(unique_name)
                            except Exception as e:
                                report_data.append([file_link, base_name, '-', 'Drafting -> Legend', '🔴 FAILED', str(e)])

                    # [DRAFTING TARGET]
                    elif target_is_drafting:
                        unique_name = get_unique_name(existing_drafting_names, base_name)
                        
                        drafting_types = [vt for vt in DB.FilteredElementCollector(dest_doc).OfClass(DB.ViewFamilyType) if vt.ViewFamily == DB.ViewFamily.Drafting]
                        if not drafting_types:
                            op_str = '{} -> Drafting'.format('Drafting' if src_view.ViewType == DB.ViewType.DraftingView else 'Legend')
                            report_data.append([file_link, base_name, '-', op_str, '🔴 FAILED', 'Drafting Type Not Found'])
                            continue
                            
                        drafting_view_type = drafting_types[0]
                        
                        try:
                            dest_view = DB.ViewDrafting.Create(dest_doc, drafting_view_type.Id)
                            dest_view.Name = unique_name
                            dest_view.Scale = src_view.Scale
                            
                            if src_view.ViewType == DB.ViewType.DraftingView:
                                elements_to_copy = [el.Id for el in DB.FilteredElementCollector(src_doc, src_view.Id).WhereElementIsNotElementType() if el.Category and el.Id != src_view.Id]
                                op_name = 'Drafting -> Drafting'
                            else:
                                elements_to_copy = [el.Id for el in DB.FilteredElementCollector(src_doc, src_view.Id).ToElements() if isinstance(el, DB.Element) and el.Category and el.Category.Name != 'Legend Components']
                                op_name = 'Legend -> Drafting'
                                
                            if elements_to_copy:
                                copied_elements = DB.ElementTransformUtils.CopyElements(src_view, List[DB.ElementId](elements_to_copy), dest_view, None, cp_options)
                                for d_id, s_id in zip(copied_elements, elements_to_copy):
                                    try: dest_view.SetElementOverrides(d_id, src_view.GetElementOverrides(s_id))
                                    except: pass
                                    
                            clickable_name = out.linkify(dest_view.Id, title=unique_name)
                            report_data.append([file_link, base_name, clickable_name, op_name, '🟢 SUCCESS', '-'])
                            existing_drafting_names.append(unique_name)
                        except Exception as e:
                            op_name = 'Drafting -> Drafting' if src_view.ViewType == DB.ViewType.DraftingView else 'Legend -> Drafting'
                            report_data.append([file_link, base_name, '-', op_name, '🔴 FAILED', str(e)])

    # --- Auto-Switch to Destination Document ---
    try:
        last_doc = dest_docs[-1]
        if last_doc.PathName:
            HOST_APP.uiapp.OpenAndActivateDocument(last_doc.PathName)
        elif hasattr(last_doc, 'IsModelInCloud') and last_doc.IsModelInCloud:
            cloud_path = last_doc.GetCloudModelPath()
            HOST_APP.uiapp.OpenAndActivateDocument(cloud_path, DB.OpenOptions(), False)
    except:
        pass

    # --- INJECT FUTURISTIC CSS ---
    out.print_html("""
    <style>
        body { background-color: #0b0f19 !important; color: #00ffcc !important; font-family: 'Consolas', monospace !important; }
        h1 { color: #00ffcc !important; text-shadow: 0 0 10px rgba(0,255,204,0.7); border-bottom: 2px solid #00ffcc; padding-bottom: 10px; }
        table { border-collapse: collapse; width: 100%; border: 1px solid #00ffcc; }
        th { background-color: #002b24 !important; color: #00ffcc !important; border: 1px solid #00ffcc !important; padding: 12px; }
        td { border: 1px solid rgba(0,255,204,0.2) !important; color: #e0f2f1 !important; padding: 10px; }
        tr:hover { background-color: rgba(0,255,204,0.1); }
        a { color: #ff007f !important; font-weight: bold; text-decoration: none !important; }
        a:hover { color: #ffffff !important; text-shadow: 0 0 10px #fff; }
        blockquote { border-left: 4px solid #ff007f !important; background-color: rgba(255,0,127,0.1); padding: 10px; }
    </style>
    """)

    out.set_title('P13 COMMAND CENTER')
    out.print_md('# ⚡ P13 COMMAND CENTER : DATA TRANSFER LOG')
    out.print_md('> **SYSTEM OVERRIDE:** Viewport routing complete. Click highlighted links to instantiate views.')
    
    if report_data:
        out.print_table(
            table_data=report_data,
            columns=['Target Node', 'Source Data', 'Instantiated View (Clickable)', 'Protocol', 'Status', 'Diagnostics']
        )
    else:
        out.print_md('> **WARNING: ZERO BYTES TRANSFERRED.**')

if __name__ == '__main__':
    main()
