# -*- coding: utf-8 -*-
__title__ = 'Smart Copy\nViews'
__author__ = 'เพิ่มพงษ์ ทวีกุล (P13)'
__doc__ = 'Advanced tool to copy Legends & Drafting Views. / คัดลอกและแปลงวิวข้ามโปรเจกต์พร้อม Interactive Dashboard'

import sys
from pyrevit import revit, DB, script, forms, HOST_APP
from System.Collections.Generic import List

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

def main():
    src_doc = revit.doc

    dest_docs = forms.select_open_docs(title='1. เลือกไฟล์ปลายทาง (Destination)')
    if not dest_docs:
        sys.exit(0)

    # [แก้ไขที่ 1] เอา use_selection=True ออก เพื่อบังคับให้หน้าต่างแสดงรายชื่อ View ขึ้นมาเสมอ!
    views = forms.select_views(
        title='2. เลือก Legends หรือ Drafting Views',
        filterfunc=lambda x: x.ViewType in [DB.ViewType.Legend, DB.ViewType.DraftingView]
    )
    if not views:
        sys.exit(0)

    saved_mode = cfg.get_option('p13_view_copymode', 'Copy Exact')
    mode_text_1 = '🚀 คัดลอกตามต้นฉบับ (Legend -> Legend)'
    mode_text_2 = '✨ แปลง Legend ทั้งหมดเป็น Drafting View'
    
    selected_option = forms.CommandSwitchWindow.show(
        [mode_text_1, mode_text_2],
        message='3. เลือกรูปแบบการทำงาน (ระบบจะจดจำค่านี้ไว้ใช้ครั้งหน้า):'
    )
    
    if not selected_option:
        sys.exit(0)
        
    selected_mode = 'Copy Exact' if selected_option == mode_text_1 else 'Convert to Drafting'
    cfg.p13_view_copymode = selected_mode
    script.save_config()

    report_data = []

    with forms.ProgressBar(title='P13 Smart Copier กำลังทำงาน... ({value} of {max_value})') as pb:
        total_tasks = len(dest_docs) * len(views)
        current_task = 0
        
        for dest_doc in dest_docs:
            all_views = revit.query.get_all_views(doc=dest_doc)
            existing_legend_names = [v.Name for v in all_views if v.ViewType == DB.ViewType.Legend]
            existing_drafting_names = [v.Name for v in all_views if v.ViewType == DB.ViewType.DraftingView]

            file_link = dest_doc.Title

            with revit.Transaction('P13 Smart Copy Views', doc=dest_doc):
                cp_options = DB.CopyPasteOptions()
                cp_options.SetDuplicateTypeNamesHandler(CopyUseDestination())

                for src_view in views:
                    current_task += 1
                    pb.update_progress(current_task, total_tasks)
                    base_name = revit.query.get_name(src_view)
                    
                    if src_view.ViewType == DB.ViewType.DraftingView:
                        drafting_types = [vt for vt in DB.FilteredElementCollector(dest_doc).OfClass(DB.ViewFamilyType) if vt.ViewFamily == DB.ViewFamily.Drafting]
                        if not drafting_types: continue
                        
                        drafting_view_type = drafting_types[0]
                        unique_name = get_unique_name(existing_drafting_names, base_name)

                        try:
                            dest_view = DB.ViewDrafting.Create(dest_doc, drafting_view_type.Id)
                            dest_view.Name = unique_name
                            dest_view.Scale = src_view.Scale

                            elements_to_copy = [el.Id for el in DB.FilteredElementCollector(src_doc, src_view.Id).WhereElementIsNotElementType() if el.Category and el.Id != src_view.Id]

                            if elements_to_copy:
                                copied_elements = DB.ElementTransformUtils.CopyElements(src_view, List[DB.ElementId](elements_to_copy), dest_view, None, cp_options)
                                for d_id, s_id in zip(copied_elements, elements_to_copy):
                                    try: dest_view.SetElementOverrides(d_id, src_view.GetElementOverrides(s_id))
                                    except: pass
                            
                            clickable_name = out.linkify(dest_view.Id, title=unique_name)
                            report_data.append([file_link, base_name, clickable_name, 'Drafting -> Drafting', '✅ Success', '-'])
                        except Exception as e:
                            report_data.append([file_link, base_name, '-', 'Drafting -> Drafting', '❌ Failed', str(e)])

                    elif src_view.ViewType == DB.ViewType.Legend:
                        if selected_mode == 'Copy Exact':
                            unique_name = get_unique_name(existing_legend_names, base_name)
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
                                        # [แก้ไขที่ 2] ดึง ID เสมอ ไม่ว่าชื่อวิวจะซ้ำหรือไม่ก็ตาม เพื่อให้เป็นลิงก์ตลอด
                                        new_view_id = new_view.Id
                                        
                                clickable_name = out.linkify(new_view_id, title=unique_name) if new_view_id else unique_name
                                report_data.append([file_link, base_name, clickable_name, 'Legend -> Legend', '✅ Success', '-'])
                            except Exception as e:
                                report_data.append([file_link, base_name, '-', 'Legend -> Legend', '❌ Failed', str(e)])

                        elif selected_mode == 'Convert to Drafting':
                            drafting_types = [vt for vt in DB.FilteredElementCollector(dest_doc).OfClass(DB.ViewFamilyType) if vt.ViewFamily == DB.ViewFamily.Drafting]
                            if not drafting_types: continue
                            
                            drafting_view_type = drafting_types[0]
                            unique_name = get_unique_name(existing_drafting_names, base_name)
                            elements_to_copy = [el.Id for el in DB.FilteredElementCollector(src_doc, src_view.Id).ToElements() if isinstance(el, DB.Element) and el.Category and el.Category.Name != 'Legend Components']

                            try:
                                dest_view = DB.ViewDrafting.Create(dest_doc, drafting_view_type.Id)
                                dest_view.Name = unique_name
                                dest_view.Scale = src_view.Scale
                                copied_elements = DB.ElementTransformUtils.CopyElements(src_view, List[DB.ElementId](elements_to_copy), dest_view, None, cp_options)

                                for d_id, s_id in zip(copied_elements, elements_to_copy):
                                    try: dest_view.SetElementOverrides(d_id, src_view.GetElementOverrides(s_id))
                                    except: pass
                                
                                clickable_name = out.linkify(dest_view.Id, title=unique_name)
                                report_data.append([file_link, base_name, clickable_name, 'Legend -> Drafting', '✅ Success', '-'])
                            except Exception as e:
                                report_data.append([file_link, base_name, '-', 'Legend -> Drafting', '❌ Failed', str(e)])

    # --- สลับไฟล์อัตโนมัติ ไปยังไฟล์ปลายทางเพื่อพร้อมให้คุณคลิกลิงก์ ---
    try:
        last_doc = dest_docs[-1]
        if last_doc.PathName:
            HOST_APP.uiapp.OpenAndActivateDocument(last_doc.PathName)
        elif hasattr(last_doc, 'IsModelInCloud') and last_doc.IsModelInCloud:
            cloud_path = last_doc.GetCloudModelPath()
            HOST_APP.uiapp.OpenAndActivateDocument(cloud_path, DB.OpenOptions(), False)
    except:
        pass

    # --- แสดงผล Dashboard ---
    out.set_title('P13 View Transfer Dashboard')
    out.print_md('# 📊 P13 View Transfer Dashboard')
    out.print_md('**Tip:** ระบบสลับไปยังไฟล์เป้าหมายให้เรียบร้อยแล้ว คุณสามารถคลิกที่ **"ชื่อ View ที่ได้"** เพื่อไฮไลต์เปิดวิวได้ทันทีครับ')
    
    if report_data:
        out.print_table(
            table_data=report_data,
            columns=['ไฟล์ปลายทาง', 'ชื่อ View ต้นทาง', 'ชื่อ View ที่ได้ (คลิกเปิดได้)', 'รูปแบบการทำงาน', 'สถานะ', 'หมายเหตุ']
        )
    else:
        out.print_md('> **ไม่มีข้อมูลถูกคัดลอก**')

if __name__ == '__main__':
    main()