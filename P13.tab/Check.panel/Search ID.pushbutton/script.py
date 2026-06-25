# -*- coding: utf-8 -*-
from __future__ import print_function

__title__ = "Search\nID"
__doc__ = "Find and select elements by their Element IDs or Unique IDs/GUIDs."
__author__ = "P13"

import os
import sys
import re
import clr
import System

clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from System.Windows import Clipboard
from Autodesk.Revit.DB import *
from System.Collections.Generic import List
from pyrevit import revit, DB, forms, script

doc = revit.doc
uidoc = revit.uidoc

def get_id_value(element_id):
    if hasattr(element_id, "Value"):
        return element_id.Value
    return element_id.IntegerValue

def create_element_id(val):
    try:
        # For Revit 2024+ (uses Int64 / long)
        return ElementId(System.Int64(val))
    except (TypeError, Exception):
        try:
            # For older versions (uses Int32 / int)
            return ElementId(System.Int32(val))
        except Exception:
            return ElementId(val)

class ElementRow(object):
    def __init__(self, id_str, status, status_color, category="-", family="-", type_name="-", level="-", workset="-", element=None):
        self.IsSelected = True
        self.Id = id_str
        self.Category = category
        self.FamilyName = family
        self.TypeName = type_name
        self.Level = level
        self.Workset = workset
        self.Status = status
        self.StatusColor = status_color
        self.Element = element

class FindByIDWindow(forms.WPFWindow):
    def __init__(self, xaml_file_path):
        forms.WPFWindow.__init__(self, xaml_file_path)
        self.results = []
        
        # Wire Event Handlers
        if hasattr(self, 'btn_search'): self.btn_search.Click += self.on_search
        if hasattr(self, 'btn_select'): self.btn_select.Click += self.on_select
        if hasattr(self, 'btn_isolate'): self.btn_isolate.Click += self.on_isolate
        if hasattr(self, 'btn_highlight'): self.btn_highlight.Click += self.on_highlight
        if hasattr(self, 'btn_reset_view'): self.btn_reset_view.Click += self.on_reset_view
        if hasattr(self, 'btn_copy'): self.btn_copy.Click += self.on_copy
        if hasattr(self, 'btn_clear'): self.btn_clear.Click += self.on_clear
        if hasattr(self, 'btn_check_all'): self.btn_check_all.Click += self.on_check_all
        if hasattr(self, 'btn_uncheck_all'): self.btn_uncheck_all.Click += self.on_uncheck_all
        if hasattr(self, 'btn_invert'): self.btn_invert.Click += self.on_invert
        
        # Setup grid double click
        if hasattr(self, 'grid_results'):
            self.grid_results.MouseDoubleClick += self.on_grid_double_click
            
        self.txt_ids.Focus()

    def resolve_element(self, id_str):
        # Determine if it is a number or GUID/UniqueID
        is_guid = False
        if "-" in id_str:
            is_guid = True

        el = None
        if is_guid:
            try:
                el = doc.GetElement(id_str)
            except Exception:
                return ElementRow(id_str, "รูปแบบรหัส GUID ไม่ถูกต้อง", "Red")
        else:
            try:
                val = int(id_str)
                eid = create_element_id(val)
                el = doc.GetElement(eid)
            except Exception as e:
                return ElementRow(id_str, "รหัสผิดพลาด: {}".format(e), "Red")

        if el is None:
            return ElementRow(id_str, "ไม่พบวัตถุนี้ในโมเดล", "Red")

        # Wrap metadata resolution in try-except for maximum robustness
        try:
            eid = el.Id
            id_display = str(get_id_value(eid))

            # If it is a Type
            is_type = False
            if isinstance(el, ElementType):
                is_type = True

            # Get Category
            category_name = "-"
            if el.Category:
                category_name = el.Category.Name
            elif hasattr(el, "StyleType"):
                category_name = str(el.StyleType)

            # Get Family and Type name
            family_name = "-"
            type_name = "-"
            
            if is_type:
                type_name = el.Name
                if hasattr(el, "FamilyName"):
                    family_name = el.FamilyName
                else:
                    family_name = el.GetType().Name
                status = "แฟมิลี่ไทป์ (Type)"
                status_color = "DarkOrange"
            else:
                # It's an instance
                try:
                    type_id = el.GetTypeId()
                    if type_id != ElementId.InvalidElementId:
                        el_type = doc.GetElement(type_id)
                        if el_type:
                            type_name = el_type.Name
                            if hasattr(el_type, "FamilyName"):
                                family_name = el_type.FamilyName
                            else:
                                family_name = el_type.GetType().Name
                    else:
                        type_name = el.Name
                        family_name = "-"
                except Exception:
                    type_name = el.Name
                    family_name = "-"
                
                status = "วัตถุโมเดล (Instance)"
                status_color = "Green"

            # Specific checks for views, sheets, levels
            if isinstance(el, View):
                status = "มุมมอง / แผ่นงาน (View)"
                status_color = "Teal"
                type_name = el.Name
                family_name = el.ViewType.ToString()
            elif isinstance(el, Level):
                status = "เส้นระดับชั้น (Level)"
                status_color = "Teal"
                type_name = el.Name
            elif isinstance(el, Workset):
                status = "เวิร์กเซต (Workset)"
                status_color = "Blue"
                type_name = el.Name

            # Get Level
            level_name = "-"
            try:
                level_id = el.LevelId if hasattr(el, "LevelId") else None
                if level_id and level_id != ElementId.InvalidElementId:
                    lvl = doc.GetElement(level_id)
                    if lvl:
                        level_name = lvl.Name
                else:
                    p_level = el.LookupParameter("Level") or el.LookupParameter("Reference Level") or el.LookupParameter("Base Constraint")
                    if p_level and p_level.HasValue:
                        level_name = p_level.AsValueString() or p_level.AsString() or "-"
            except Exception:
                pass

            # Get Workset
            workset_name = "-"
            try:
                if doc.IsWorkshared and hasattr(el, "WorksetId"):
                    workset_id = el.WorksetId
                    if workset_id and workset_id != WorksetId.InvalidWorksetId:
                        workset_table = doc.GetWorksetTable()
                        if workset_table:
                            ws = workset_table.GetWorkset(workset_id)
                            if ws:
                                workset_name = ws.Name
            except Exception:
                pass

            return ElementRow(id_display, status, status_color, category_name, family_name, type_name, level_name, workset_name, el)
            
        except Exception as e:
            # Fallback if property resolution fails - retains Revit element object for select/isolate actions
            return ElementRow(id_str, "ดึงข้อมูลล้มเหลว: {}".format(e), "Red", element=el)

    def on_search(self, sender, args):
        input_text = self.txt_ids.Text.strip()
        if not input_text:
            forms.alert("กรุณากรอกรหัส Element ID หรือ Unique ID ในช่องด้านซ้ายก่อนค่ะ", title="ข้อมูลว่างเปล่า")
            return
            
        # Regex to find either integer element IDs or UniqueIDs
        id_pattern = re.compile(r'\b\d+\b|\b[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}(?:-[a-fA-F0-9]{8})?\b')
        matches = id_pattern.findall(input_text)
        
        if not matches:
            forms.alert("ไม่พบรูปแบบรหัส ID หรือ GUID ที่สามารถนำไปใช้ค้นหาได้เลยค่ะ", title="ไม่พบรหัสวัตถุ")
            return
            
        # Remove duplicates preserving order
        seen = set()
        unique_matches = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                unique_matches.append(m)
                
        # Resolve elements
        self.results = []
        found_cnt = 0
        total_cnt = len(unique_matches)
        
        with forms.ProgressBar(title="กำลังดำเนินการค้นหาและตรวจสอบข้อมูลวัตถุ...", cancellable=False) as pb:
            for i, m in enumerate(unique_matches):
                pb.update_progress(i, total_cnt)
                row = self.resolve_element(m)
                if row.Element:
                    found_cnt += 1
                self.results.append(row)
                
        self.grid_results.ItemsSource = self.results
        self.grid_results.Items.Refresh()
        
        # Update stats label
        self.lbl_stats.Text = " (พบวัตถุจำนวน {} ชิ้น จากทั้งหมด {} รายการ)".format(found_cnt, total_cnt)

    def on_select(self, sender, args):
        checked_rows = [r for r in self.results if r.IsSelected]
        if not checked_rows:
            forms.alert("กรุณาทำเครื่องหมายติ๊กถูกหน้าแถวผลลัพธ์ในตารางก่อนสั่งงานค่ะ", title="ไม่มีการเลือกรายการ")
            return
            
        ids = List[ElementId]()
        not_found = []
        not_selectable = []
        
        for r in checked_rows:
            if r.Element is None:
                not_found.append(r.Id)
            else:
                el = r.Element
                if isinstance(el, ElementType) or isinstance(el, View) or isinstance(el, Workset):
                    not_selectable.append(el)
                else:
                    ids.Add(el.Id)
                    
        if ids.Count > 0:
            try:
                uidoc.Selection.SetElementIds(ids)
                uidoc.ShowElements(ids)
                
                # Report warnings if there are any not found or not selectable
                warn_msg = []
                if not_found:
                    warn_msg.append("ไม่พบวัตถุจริงในโมเดล ({} ID):\n- {}".format(len(not_found), "\n- ".join(not_found[:5])))
                    if len(not_found) > 5:
                        warn_msg.append("... และอีก {} รายการ".format(len(not_found) - 5))
                if not_selectable:
                    warn_msg.append("วัตถุประเภท Type/View/Workset ซึ่งแสดงในโมเดล 3D ไม่ได้ ({} รายการ):\n- {}".format(len(not_selectable), "\n- ".join([el.Name for el in not_selectable[:5]])))
                    if len(not_selectable) > 5:
                        warn_msg.append("... และอีก {} รายการ".format(len(not_selectable) - 5))
                        
                if warn_msg:
                    forms.alert(
                        "ทำการเลือกวัตถุประเภทโมเดลชิ้นงานจำนวน {} ชิ้นเรียบร้อยแล้วค่ะ\n\n"
                        "หมายเหตุเพิ่มเติม:\n{}".format(ids.Count, "\n\n".join(warn_msg)),
                        title="แจ้งเตือนการเลือกวัตถุ"
                    )
            except Exception as e:
                forms.alert("เกิดข้อผิดพลาดในการเลือกวัตถุ: {}".format(e))
        else:
            # Nothing could be selected
            err_msg = []
            if not_found:
                err_msg.append("ไม่พบข้อมูลวัตถุจริงในโมเดล หรือรหัสผิดพลาด ({} ID):\n- {}".format(len(not_found), "\n- ".join(not_found[:5])))
                if len(not_found) > 5:
                    err_msg.append("... และอีก {} รายการ".format(len(not_found) - 5))
            if not_selectable:
                err_msg.append("วัตถุประเภทนี้ไม่สามารถแสดงผลการเลือกบนจอเขียนแบบได้ (เป็น Type, View หรือ Workset):\n- {}".format("\n- ".join([el.Name for el in not_selectable[:5]])))
                if len(not_selectable) > 5:
                    err_msg.append("... และอีก {} รายการ".format(len(not_selectable) - 5))
                    
            forms.alert("\n\n".join(err_msg), title="ไม่สามารถดำเนินการเลือกได้")

    def on_isolate(self, sender, args):
        checked_rows = [r for r in self.results if r.IsSelected]
        if not checked_rows:
            forms.alert("กรุณาทำเครื่องหมายติ๊กถูกหน้าแถวผลลัพธ์ในตารางก่อนสั่งงานค่ะ", title="ไม่มีการเลือกรายการ")
            return
            
        active_view = uidoc.ActiveView
        ids = List[ElementId]()
        
        for r in checked_rows:
            if r.Element:
                el = r.Element
                if not isinstance(el, ElementType) and not isinstance(el, View) and not isinstance(el, Workset):
                    if el.CanBeHidden(active_view):
                        ids.Add(el.Id)
                    
        if ids.Count > 0:
            try:
                with revit.Transaction("Isolate Elements"):
                    active_view.IsolateElementsTemporary(ids)
            except Exception as e:
                forms.alert("เกิดข้อผิดพลาดในการซ่อน/แสดงวัตถุ: {}".format(e))
        else:
            forms.alert("ไม่พบวัตถุที่สามารถดำเนินการแยกแสดง (Isolate) ในมุมมองปัจจุบันได้เลยค่ะ (วัตถุอาจเป็น Type, View, Workset หรือไม่มีในมุมมองนี้)", title="ไม่สามารถแยกมุมมองได้")

    def on_highlight(self, sender, args):
        checked_rows = [r for r in self.results if r.IsSelected]
        if not checked_rows:
            forms.alert("กรุณาทำเครื่องหมายติ๊กถูกหน้าแถวผลลัพธ์ในตารางก่อนสั่งงานค่ะ", title="ไม่มีการเลือกรายการ")
            return
            
        active_view = uidoc.ActiveView
        ids = List[ElementId]()
        
        for r in checked_rows:
            if r.Element:
                el = r.Element
                if not isinstance(el, ElementType) and not isinstance(el, View) and not isinstance(el, Workset):
                    ids.Add(el.Id)
                    
        if ids.Count == 0:
            forms.alert("วัตถุที่เลือกทั้งหมดไม่สามารถระบายสีไฮไลท์ได้ค่ะ (ต้องเป็นโมเดลชิ้นงานปกติเท่านั้น)", title="ไม่สามารถไฮไลท์ได้")
            return

        # Find solid fill pattern
        collector = FilteredElementCollector(doc)
        patterns = collector.OfClass(FillPatternElement).ToElements()
        solid_pattern = None
        for p in patterns:
            pattern_type = p.GetFillPattern()
            if pattern_type.IsSolidFill:
                solid_pattern = p
                break
                
        if not solid_pattern:
            forms.alert("ไม่พบรูปแบบลวดลายทึบ (Solid Fill Pattern) ในโปรเจกต์นี้ จึงไม่สามารถลงสีไฮไลท์กราฟิกได้ค่ะ", title="ข้อผิดพลาด")
            return
            
        # Create solid vibrant green override
        override_settings = OverrideGraphicSettings()
        color = Color(34, 180, 34) # Forest Green
        
        try:
            override_settings.SetSurfaceForegroundPatternId(solid_pattern.Id)
            override_settings.SetSurfaceForegroundPatternColor(color)
            override_settings.SetCutForegroundPatternId(solid_pattern.Id)
            override_settings.SetCutForegroundPatternColor(color)
        except AttributeError:
            override_settings.SetProjectionFillPatternId(solid_pattern.Id)
            override_settings.SetProjectionFillPatternColor(color)
            override_settings.SetCutFillPatternId(solid_pattern.Id)
            override_settings.SetCutFillPatternColor(color)

        try:
            with revit.Transaction("Highlight Elements"):
                for eid in ids:
                    active_view.SetElementOverrides(eid, override_settings)
            uidoc.RefreshActiveView()
        except Exception as e:
            forms.alert("เกิดข้อผิดพลาดในการลงสีไฮไลท์กราฟิกวัตถุ: {}".format(e))

    def on_reset_view(self, sender, args):
        active_view = uidoc.ActiveView
        
        try:
            with revit.Transaction("Reset View Overrides"):
                # Reset temporary isolation
                if active_view.IsTemporaryHideIsolateActive():
                    active_view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)
                
                # Clear overrides for all checked elements in the results
                empty_overrides = OverrideGraphicSettings()
                for row in self.results:
                    if row.Element and row.Element.IsValidObject:
                        if not isinstance(row.Element, ElementType) and not isinstance(row.Element, View) and not isinstance(row.Element, Workset):
                            active_view.SetElementOverrides(row.Element.Id, empty_overrides)
            uidoc.RefreshActiveView()
        except Exception as e:
            forms.alert("เกิดข้อผิดพลาดในการรีเซ็ตมุมมอง: {}".format(e))

    def on_copy(self, sender, args):
        if not self.results:
            forms.alert("ไม่พบข้อมูลผลลัพธ์ที่จะคัดลอกค่ะ", title="ไม่มีข้อมูล")
            return
            
        lines = []
        # Header
        lines.append("Element ID\tCategory\tFamily Name\tType Name\tLevel\tWorkset\tStatus")
        for r in self.results:
            lines.append("{}\t{}\t{}\t{}\t{}\t{}\t{}".format(
                r.Id, r.Category, r.FamilyName, r.TypeName, r.Level, r.Workset, r.Status
            ))
            
        text = "\r\n".join(lines)
        try:
            Clipboard.SetText(text)
            forms.alert("คัดลอกข้อมูลตารางจำนวน {} แถวลงคลิปบอร์ดเสร็จเรียบร้อยแล้วค่ะ (สเปรดชีตสไตล์ Excel)".format(len(self.results)), title="คัดลอกสำเร็จ")
        except Exception as e:
            forms.alert("เกิดข้อผิดพลาดในการคัดลอกลงคลิปบอร์ด: {}".format(e))

    def on_clear(self, sender, args):
        self.txt_ids.Text = ""
        self.results = []
        self.grid_results.ItemsSource = None
        self.grid_results.Items.Refresh()
        self.lbl_stats.Text = " (ไม่มีรายการ)"

    def on_check_all(self, sender, args):
        for r in self.results:
            r.IsSelected = True
        self.grid_results.Items.Refresh()

    def on_uncheck_all(self, sender, args):
        for r in self.results:
            r.IsSelected = False
        self.grid_results.Items.Refresh()

    def on_invert(self, sender, args):
        for r in self.results:
            r.IsSelected = not r.IsSelected
        self.grid_results.Items.Refresh()

    def on_grid_double_click(self, sender, args):
        try:
            selected_row = self.grid_results.SelectedItem
            if selected_row and hasattr(selected_row, 'Element') and selected_row.Element:
                el = selected_row.Element
                if not isinstance(el, ElementType) and not isinstance(el, View) and not isinstance(el, Workset):
                    ids = List[ElementId]()
                    ids.Add(el.Id)
                    uidoc.Selection.SetElementIds(ids)
                    uidoc.ShowElements(ids)
        except Exception:
            pass

def main():
    if not doc:
        forms.alert("No open Revit document found.", exitscript=True)
    
    xaml_path = script.get_bundle_file('ui.xaml')
    window = FindByIDWindow(xaml_path)
    window.ShowDialog()

if __name__ == '__main__':
    main()
