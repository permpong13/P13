# -*- coding: utf-8 -*-
__title__ = "Model\nCheck"
__author__ = "Tee_เพิ่มพงษ์"
__doc__ = "ตรวจสอบสุขภาพโมเดล Revit สำหรับการ QA/QC และก่อนส่งงาน"

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('RevitServices')
clr.AddReference('System')

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from pyrevit import forms, revit, script
from System.Collections.Generic import List
from collections import defaultdict
import datetime
import sys

class ModelHealthChecker:
    def __init__(self, doc):
        self.doc = doc
        self.output = script.get_output()
        self.results = {
            'warnings': [],
            'duplicate_marks': [],
            'unused_elements': [],
            'performance_issues': []
        }
    
    def check_warnings(self):
        """ตรวจสอบและจัดหมวดหมู่ warnings"""
        try:
            # ดึงข้อมูล warnings
            warnings = self.doc.GetWarnings()
            warning_count = len(warnings)
            
            if warning_count == 0:
                return
            
            # จัดกลุ่ม warnings โดย description
            warning_groups = defaultdict(list)
            
            for warning in warnings:
                description = warning.GetDescriptionText()
                elements = []
                
                # ดึง elements ที่เกี่ยวข้อง
                failing_elements = warning.GetFailingElements()
                for elem_id in failing_elements:
                    elem = self.doc.GetElement(elem_id)
                    if elem:
                        elem_name = elem.Name if hasattr(elem, 'Name') and elem.Name else elem.GetType().Name
                        category_name = elem.Category.Name if elem.Category else "No Category"
                        
                        # รับประเภท element
                        elem_type = elem.GetType().Name
                        
                        elements.append({
                            'id': elem_id.IntegerValue,
                            'element_id': elem_id,  # เก็บ ElementId object สำหรับสร้างลิงก์
                            'name': elem_name,
                            'category': category_name,
                            'type': elem_type
                        })
                
                warning_groups[description].append({
                    'elements': elements,
                    'severity': 'High' if any(word in description.lower() for word in ['error', 'critical', 'fail']) else 'Medium'
                })
            
            # สรุปผล warnings
            for description, warnings_list in warning_groups.items():
                all_elements = []
                for warning_data in warnings_list:
                    all_elements.extend(warning_data['elements'])
                
                self.results['warnings'].append({
                    'description': description,
                    'count': len(warnings_list),
                    'total_elements': len(all_elements),
                    'elements': all_elements,
                    'severity': warnings_list[0]['severity']
                })
                
        except Exception as e:
            self.results['warnings'].append({
                'description': "Error checking warnings: {0}".format(str(e)),
                'count': 1,
                'total_elements': 0,
                'elements': [],
                'severity': 'High'
            })
    
    def check_duplicate_marks(self):
        """ตรวจสอบค่า Mark ที่ซ้ำกัน"""
        try:
            # เก็บค่า Mark จาก elements ที่มีพารามิเตอร์ Mark
            mark_data = defaultdict(list)
            
            # ใช้ filtered collector สำหรับ elements ที่มี Mark
            collector = FilteredElementCollector(self.doc).WhereElementIsNotElementType()
            
            elements_with_mark = 0
            for element in collector:
                try:
                    mark_param = element.LookupParameter("Mark")
                    if mark_param and not mark_param.IsReadOnly and mark_param.StorageType == StorageType.String:
                        mark_value = mark_param.AsString()
                        if mark_value and mark_value.strip():
                            elements_with_mark += 1
                            category_name = element.Category.Name if element.Category else "No Category"
                            mark_data[mark_value.strip()].append({
                                'id': element.Id.IntegerValue,
                                'element_id': element.Id,  # เก็บ ElementId object สำหรับสร้างลิงก์
                                'name': element.Name if hasattr(element, 'Name') and element.Name else "Unnamed",
                                'category': category_name,
                                'type': element.GetType().Name
                            })
                except:
                    continue
            
            # ตรวจสอบค่าที่ซ้ำ (มีมากกว่า 1 element)
            duplicate_count = 0
            for mark_value, elements in mark_data.items():
                if len(elements) > 1:
                    duplicate_count += 1
                    self.results['duplicate_marks'].append({
                        'mark': mark_value,
                        'elements': elements,
                        'count': len(elements)
                    })
            
            # เพิ่ม performance issue ถ้ามี duplicate จำนวนมาก
            if duplicate_count > 20:
                self.results['performance_issues'].append({
                    'issue': 'High number of duplicate marks',
                    'description': 'Found {0} duplicate mark values - this may cause identification issues'.format(duplicate_count),
                    'severity': 'Medium'
                })
                    
        except Exception as e:
            self.results['duplicate_marks'].append({
                'mark': "Error: {0}".format(str(e)),
                'elements': [],
                'count': 0
            })
    
    def check_unused_families(self):
        """ตรวจสอบ families ที่ไม่ได้ใช้"""
        try:
            used_family_ids = set()
            
            # ตรวจสอบจาก instances
            instance_collector = FilteredElementCollector(self.doc).WhereElementIsNotElementType()
            for instance in instance_collector:
                if hasattr(instance, 'Symbol'):
                    symbol = instance.Symbol
                    if symbol and hasattr(symbol, 'Family'):
                        family = symbol.Family
                        if family:
                            used_family_ids.add(family.Id.IntegerValue)
            
            # ตรวจสอบ families ทั้งหมด
            family_collector = FilteredElementCollector(self.doc).OfClass(Family)
            
            for family in family_collector:
                if family.Id.IntegerValue not in used_family_ids:
                    self.results['unused_elements'].append({
                        'type': 'Family',
                        'name': family.Name,
                        'category': family.FamilyCategory.Name if family.FamilyCategory else "No Category",
                        'id': family.Id.IntegerValue,
                        'element_id': family.Id  # เก็บ ElementId object สำหรับสร้างลิงก์
                    })
            
            # เพิ่ม performance issue ถ้ามี unused families จำนวนมาก
            unused_count = len([x for x in self.results['unused_elements'] if x['type'] == 'Family'])
            if unused_count > 50:
                self.results['performance_issues'].append({
                    'issue': 'Large number of unused families',
                    'description': 'Found {0} unused families - consider purging to reduce file size'.format(unused_count),
                    'severity': 'Low'
                })
                    
        except Exception as e:
            self.results['unused_elements'].append({
                'type': 'Family',
                'name': "Error: {0}".format(str(e)),
                'category': 'Error',
                'id': 0,
                'element_id': None
            })
    
    def check_unused_views(self):
        """ตรวจสอบ views ที่ไม่ได้ใช้ใน sheets"""
        try:
            used_view_ids = set()
            
            # ตรวจสอบ views ที่ใช้ใน sheets
            sheet_collector = FilteredElementCollector(self.doc).OfClass(ViewSheet)
            for sheet in sheet_collector:
                viewports = sheet.GetAllViewports()
                for vp_id in viewports:
                    viewport = self.doc.GetElement(vp_id)
                    if viewport:
                        used_view_ids.add(viewport.ViewId.IntegerValue)
            
            # ตรวจสอบ views ทั้งหมด (ไม่รวม templates และ system views)
            view_collector = FilteredElementCollector(self.doc).OfClass(View)
            for view in view_collector:
                if (view.IsTemplate or 
                    view.ViewType == ViewType.ProjectBrowser or
                    view.ViewType == ViewType.SystemBrowser or
                    view.ViewType == ViewType.Undefined):
                    continue
                
                if view.Id.IntegerValue not in used_view_ids:
                    self.results['unused_elements'].append({
                        'type': 'View',
                        'name': view.Name,
                        'category': str(view.ViewType),
                        'id': view.Id.IntegerValue,
                        'element_id': view.Id  # เก็บ ElementId object สำหรับสร้างลิงก์
                    })
            
            # เพิ่ม performance issue ถ้ามี unused views จำนวนมาก
            unused_views = len([x for x in self.results['unused_elements'] if x['type'] == 'View'])
            if unused_views > 30:
                self.results['performance_issues'].append({
                    'issue': 'Large number of unused views',
                    'description': 'Found {0} unused views - consider removing to improve performance'.format(unused_views),
                    'severity': 'Medium'
                })
                    
        except Exception as e:
            self.results['unused_elements'].append({
                'type': 'View',
                'name': "Error: {0}".format(str(e)),
                'category': 'Error',
                'id': 0,
                'element_id': None
            })
    
    def check_unused_worksets(self):
        """ตรวจสอบ worksets ที่ไม่มี elements"""
        try:
            # ตรวจสอบว่าเป็น workshared model หรือไม่
            if not self.doc.IsWorkshared:
                return
            
            used_workset_ids = set()
            
            # เก็บ worksets ที่มี elements
            element_collector = FilteredElementCollector(self.doc).WhereElementIsNotElementType()
            for element in element_collector:
                workset_id = element.WorksetId
                if workset_id != WorksetId.InvalidWorksetId:
                    used_workset_ids.add(workset_id.IntegerValue)
            
            # ตรวจสอบ worksets ทั้งหมด
            workset_table = self.doc.GetWorksetTable()
            worksets = WorksetTable.GetWorksets(workset_table)
            
            for workset in worksets:
                if (workset.Kind == WorksetKind.UserWorkset and 
                    workset.Id.IntegerValue not in used_workset_ids):
                    self.results['unused_elements'].append({
                        'type': 'Workset',
                        'name': workset.Name,
                        'category': str(workset.Kind),
                        'id': workset.Id.IntegerValue,
                        'element_id': ElementId(workset.Id.IntegerValue)  # เก็บ ElementId object สำหรับสร้างลิงก์
                    })
                    
        except Exception as e:
            self.results['unused_elements'].append({
                'type': 'Workset',
                'name': "Error: {0}".format(str(e)),
                'category': 'Error',
                'id': 0,
                'element_id': None
            })
    
    def check_performance_issues(self):
        """ตรวจสอบปัญหา performance"""
        try:
            # ตรวจสอบจำนวน warnings
            warnings = self.doc.GetWarnings()
            warning_count = len(warnings)
            if warning_count > 100:
                self.results['performance_issues'].append({
                    'issue': 'High number of warnings',
                    'description': 'Found {0} warnings - may impact model performance'.format(warning_count),
                    'severity': 'Medium'
                })
            
            # ตรวจสอบจำนวน groups
            group_collector = FilteredElementCollector(self.doc).OfClass(Group)
            group_count = group_collector.GetElementCount()
            if group_count > 50:
                self.results['performance_issues'].append({
                    'issue': 'Large number of groups',
                    'description': 'Found {0} groups - consider simplifying or using links'.format(group_count),
                    'severity': 'Low'
                })
            
            # ตรวจสอบจำนวน views
            view_collector = FilteredElementCollector(self.doc).OfClass(View)
            view_count = view_collector.GetElementCount()
            if view_count > 500:
                self.results['performance_issues'].append({
                    'issue': 'Large number of views',
                    'description': 'Found {0} views - consider purging unused views'.format(view_count),
                    'severity': 'Medium'
                })
            
            # ตรวจสอบ file size
            try:
                file_path = self.doc.PathName
                if file_path:
                    import os
                    if os.path.exists(file_path):
                        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
                        if file_size_mb > 300:
                            self.results['performance_issues'].append({
                                'issue': 'Large file size',
                                'description': 'File size: {0:.1f} MB - consider using worksets or purging'.format(file_size_mb),
                                'severity': 'High' if file_size_mb > 500 else 'Medium'
                            })
            except:
                pass
            
            # ตรวจสอบจำนวน elements
            all_elements = FilteredElementCollector(self.doc).WhereElementIsNotElementType()
            element_count = all_elements.GetElementCount()
            if element_count > 100000:
                self.results['performance_issues'].append({
                    'issue': 'High element count',
                    'description': 'Model contains {0} elements - consider optimizing'.format(element_count),
                    'severity': 'Medium'
                })
                
        except Exception as e:
            self.results['performance_issues'].append({
                'issue': 'Error checking performance',
                'description': str(e),
                'severity': 'High'
            })
    
    def run_all_checks(self, selected_checks):
        """รันการตรวจสอบทั้งหมดที่เลือก"""
        # ใช้วิธีที่ปลอดภัยในการล้าง output
        try:
            # พยายามล้าง output ถ้ามี method clear
            if hasattr(self.output, 'clear'):
                self.output.clear()
            else:
                # ถ้าไม่มี method clear ให้สร้าง output ใหม่
                self.output = script.get_output()
        except:
            # ถ้าเกิดข้อผิดพลาดให้สร้าง output ใหม่
            self.output = script.get_output()
        
        self.output.print_html("<div style='padding: 20px; background-color: #f8f9fa; border-radius: 10px;'>")
        
        if 'warnings' in selected_checks:
            self.output.print_html("<h3>🔍 กำลังตรวจสอบ Warnings...</h3>")
            self.check_warnings()
        
        if 'duplicate_marks' in selected_checks:
            self.output.print_html("<h3>🔍 กำลังตรวจสอบ Duplicate Marks...</h3>")
            self.check_duplicate_marks()
        
        if 'unused_families' in selected_checks:
            self.output.print_html("<h3>🔍 กำลังตรวจสอบ Unused Families...</h3>")
            self.check_unused_families()
        
        if 'unused_views' in selected_checks:
            self.output.print_html("<h3>🔍 กำลังตรวจสอบ Unused Views...</h3>")
            self.check_unused_views()
        
        if 'unused_worksets' in selected_checks:
            self.output.print_html("<h3>🔍 กำลังตรวจสอบ Unused Worksets...</h3>")
            self.check_unused_worksets()
        
        if 'performance' in selected_checks:
            self.output.print_html("<h3>🔍 กำลังตรวจสอบ Performance Issues...</h3>")
            self.check_performance_issues()
        
        self.output.print_html("</div>")
    
    def generate_report(self):
        """สร้างรายงานผลการตรวจสอบ"""
        # ใช้วิธีที่ปลอดภัยในการล้าง output
        try:
            # พยายามล้าง output ถ้ามี method clear
            if hasattr(self.output, 'clear'):
                self.output.clear()
            else:
                # ถ้าไม่มี method clear ให้สร้าง output ใหม่
                self.output = script.get_output()
        except:
            # ถ้าเกิดข้อผิดพลาดให้สร้าง output ใหม่
            self.output = script.get_output()
        
        # Header
        self.output.print_html("""
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; color: white; border-radius: 10px; margin-bottom: 20px;">
            <h1 style="margin: 0; font-size: 28px;">🩺 MODEL HEALTH CHECK REPORT</h1>
            <p style="margin: 5px 0; font-size: 16px;"><strong>Project:</strong> {0}</p>
            <p style="margin: 5px 0; font-size: 16px;"><strong>Date:</strong> {1}</p>
        </div>
        """.format(self.doc.Title, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        
        # Calculate Health Score
        total_issues = (
            len(self.results['warnings']) +
            len(self.results['duplicate_marks']) +
            len([x for x in self.results['unused_elements'] if x['type'] in ['Family', 'View', 'Workset']]) +
            len(self.results['performance_issues'])
        )
        
        health_score = max(0, 100 - total_issues * 3)
        if health_score >= 80:
            score_color = "#28a745"
            score_message = "Excellent"
        elif health_score >= 60:
            score_color = "#ffc107"
            score_message = "Good"
        elif health_score >= 40:
            score_color = "#fd7e14"
            score_message = "Fair"
        else:
            score_color = "#dc3545"
            score_message = "Needs Attention"
        
        # Health Score Card
        self.output.print_html("""
        <div style="background-color: white; padding: 25px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); margin-bottom: 20px; border-left: 5px solid {0};">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <h2 style="margin: 0; color: {0};">🏥 HEALTH SCORE: {1}/100</h2>
                    <p style="margin: 5px 0; font-size: 18px; color: {0};"><strong>{2}</strong></p>
                </div>
                <div style="text-align: right;">
                    <p style="margin: 5px 0;"><strong>Total Issues Found:</strong> {3}</p>
                </div>
            </div>
        </div>
        """.format(score_color, health_score, score_message, total_issues))
        
        # Results Sections
        self._display_section('⚠️ WARNINGS', self.results['warnings'], '#fff3cd', '#ffc107', self._format_warnings)
        self._display_section('🔢 DUPLICATE MARKS', self.results['duplicate_marks'], '#f8d7da', '#dc3545', self._format_duplicate_marks)
        self._display_section('🗑️ UNUSED ELEMENTS', self.results['unused_elements'], '#e2e3e5', '#6c757d', self._format_unused_elements)
        self._display_section('⚡ PERFORMANCE ISSUES', self.results['performance_issues'], '#d1ecf1', '#17a2b8', self._format_performance_issues)
        
        # Recommendations
        self._generate_recommendations()
    
    def _display_section(self, title, data, bg_color, border_color, formatter):
        """แสดงส่วนของรายงาน"""
        if data:
            self.output.print_html("""
            <div style="margin-bottom: 25px;">
                <h2 style="color: {0}; border-bottom: 2px solid {0}; padding-bottom: 10px;">{1}</h2>
            """.format(border_color, title))
            formatter(data, bg_color, border_color)
            self.output.print_html("</div>")
        else:
            self.output.print_html("""
            <div style="background-color: #d4edda; padding: 20px; border-radius: 5px; border-left: 4px solid #28a745; margin-bottom: 20px;">
                <h3 style="margin: 0; color: #155724;">✅ No {0} found</h3>
            </div>
            """.format(title.lower()))
    
    def _format_warnings(self, warnings, bg_color, border_color):
        for warning in warnings:
            self.output.print_html("""
            <div style="background-color: {0}; padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 4px solid {1};">
                <h4 style="margin: 0 0 10px 0;">{2}</h4>
                <p style="margin: 5px 0;"><strong>Count:</strong> {3} | <strong>Elements Affected:</strong> {4} | <strong>Severity:</strong> {5}</p>
            """.format(bg_color, border_color, warning['description'], warning['count'], warning['total_elements'], warning['severity']))
            
            # แสดง Element IDs ในรูปแบบตารางคลิกได้
            if warning['elements']:
                self.output.print_html("""
                <details>
                    <summary><strong>Show Element IDs ({0})</strong></summary>
                    <div style="margin: 10px 0;">
                """.format(len(warning['elements'])))
                
                # สร้างตารางข้อมูล
                table_data = []
                highlight_ids = []
                
                for element in warning['elements'][:50]:  # แสดงสูงสุด 50 elements
                    # สร้างลิงก์คลิกได้สำหรับ Element ID
                    element_id_link = self.output.linkify(element['element_id'])
                    
                    table_data.append([
                        element_id_link,
                        element['type'],
                        element['name'],
                        element['category']
                    ])
                    
                    highlight_ids.append(element['element_id'])
                
                # แสดงตาราง
                self.output.print_table(
                    table_data=table_data,
                    columns=["Element ID", "Type", "Name", "Category"],
                    title="Elements with this Warning"
                )
                
                if len(warning['elements']) > 50:
                    self.output.print_html("<p style='text-align: center; font-style: italic;'>... and {0} more elements</p>".format(len(warning['elements']) - 50))
                
                self.output.print_html("</div></details>")
            
            self.output.print_html("</div>")
    
    def _format_duplicate_marks(self, duplicates, bg_color, border_color):
        for dup in duplicates[:10]:  # Show only first 10
            self.output.print_html("""
            <div style="background-color: {0}; padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 4px solid {1};">
                <h4 style="margin: 0 0 10px 0;">Mark: {2}</h4>
                <p style="margin: 5px 0;"><strong>Duplicate Count:</strong> {3}</p>
                <details>
                    <summary><strong>Show Elements ({4})</strong></summary>
                    <div style="margin: 10px 0;">
            """.format(bg_color, border_color, dup['mark'], dup['count'], len(dup['elements'])))
            
            # สร้างตารางสำหรับ duplicate marks
            table_data = []
            for elem in dup['elements'][:20]:  # Show only first 20 elements
                element_id_link = self.output.linkify(elem['element_id'])
                
                table_data.append([
                    element_id_link,
                    elem['type'],
                    elem['name'],
                    elem['category']
                ])
            
            # แสดงตาราง
            self.output.print_table(
                table_data=table_data,
                columns=["Element ID", "Type", "Name", "Category"],
                title="Elements with Mark: {0}".format(dup['mark'])
            )
            
            if len(dup['elements']) > 20:
                self.output.print_html("<p style='text-align: center; font-style: italic;'>... and {0} more elements</p>".format(len(dup['elements']) - 20))
            
            self.output.print_html("</div></details></div>")
    
    def _format_unused_elements(self, unused_elements, bg_color, border_color):
        by_type = defaultdict(list)
        for element in unused_elements:
            by_type[element['type']].append(element)
        
        for elem_type, elements in by_type.items():
            self.output.print_html("""
            <div style="background-color: {0}; padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 4px solid {1};">
                <h4 style="margin: 0 0 10px 0;">{2} ({3})</h4>
                <details>
                    <summary><strong>Show Details</strong></summary>
                    <div style="margin: 10px 0;">
            """.format(bg_color, border_color, elem_type, len(elements)))
            
            # สร้างตารางสำหรับ unused elements
            table_data = []
            for element in elements[:30]:  # Show only first 30
                if element['element_id']:
                    element_id_link = self.output.linkify(element['element_id'])
                else:
                    element_id_link = "N/A"
                
                table_data.append([
                    element_id_link,
                    element['name'],
                    element['category']
                ])
            
            # แสดงตาราง
            self.output.print_table(
                table_data=table_data,
                columns=["Element ID", "Name", "Category"],
                title="Unused {0}".format(elem_type)
            )
            
            if len(elements) > 30:
                self.output.print_html("<p style='text-align: center; font-style: italic;'>... and {0} more {1}</p>".format(len(elements) - 30, elem_type.lower()))
            
            self.output.print_html("</div></details></div>")
    
    def _format_performance_issues(self, issues, bg_color, border_color):
        severity_order = {'High': 3, 'Medium': 2, 'Low': 1}
        sorted_issues = sorted(issues, key=lambda x: severity_order.get(x['severity'], 0), reverse=True)
        
        for issue in sorted_issues:
            severity_color = {
                'High': '#dc3545',
                'Medium': '#ffc107', 
                'Low': '#17a2b8'
            }.get(issue['severity'], '#6c757d')
            
            self.output.print_html("""
            <div style="background-color: {0}; padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 4px solid {1};">
                <h4 style="margin: 0 0 10px 0; color: {1};">{2} ({3})</h4>
                <p style="margin: 0;">{4}</p>
            </div>
            """.format(bg_color, severity_color, issue['issue'], issue['severity'], issue['description']))
    
    def _generate_recommendations(self):
        """สร้างคำแนะนำ"""
        recommendations = []
        
        if self.results['warnings']:
            recommendations.append("Resolve warnings to improve model quality and performance")
        
        if self.results['duplicate_marks']:
            recommendations.append("Fix duplicate marks for better element identification and scheduling")
        
        unused_families = [x for x in self.results['unused_elements'] if x['type'] == 'Family']
        if unused_families:
            recommendations.append("Purge unused families to reduce file size ({0} families found)".format(len(unused_families)))
        
        unused_views = [x for x in self.results['unused_elements'] if x['type'] == 'View']
        if unused_views:
            recommendations.append("Remove unused views to improve performance ({0} views found)".format(len(unused_views)))
        
        if self.results['performance_issues']:
            high_priority = [x for x in self.results['performance_issues'] if x['severity'] == 'High']
            if high_priority:
                recommendations.append("Address high priority performance issues immediately")
        
        if not recommendations:
            recommendations.append("Model is in excellent health! Maintain current practices")
        
        self.output.print_html("""
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 25px; border-radius: 10px; color: white;">
            <h2 style="margin: 0 0 15px 0;">💡 RECOMMENDATIONS</h2>
        """)
        
        for rec in recommendations:
            self.output.print_html("<p style='margin: 8px 0; font-size: 16px;'>• {0}</p>".format(rec))
        
        self.output.print_html("</div>")

def main():
    """ฟังก์ชันหลัก"""
    doc = revit.doc
    
    # เลือกประเภทการตรวจสอบ - ใช้ภาษาอังกฤษที่อ่านง่าย
    check_options = {
        'warnings': '⚠️ Warnings',
        'duplicate_marks': '🔢 Duplicate Marks', 
        'unused_families': '🏠 Unused Families',
        'unused_views': '📊 Unused Views',
        'unused_worksets': '👥 Unused Worksets',
        'performance': '⚡ Performance Issues'
    }
    
    # ใช้รูปแบบที่ง่ายและปลอดภัยสำหรับการเลือก
    selected_keys = forms.SelectFromList.show(
        sorted(check_options.keys()),
        title='Select Check Types',
        button_name='Start Check',
        multiselect=True,
        width=500
    )
    
    if not selected_keys:
        return
    
    # แปลง keys เป็นชื่อที่อ่านง่ายสำหรับการแสดงผล
    selected_checks = []
    selected_names = []
    
    for key in selected_keys:
        selected_checks.append(key)
        selected_names.append(check_options[key])
    
    # ยืนยันการตรวจสอบ
    confirmation_message = "Will check the following:\n" + "\n".join(["• " + name for name in selected_names])
    
    if not forms.alert(confirmation_message, ok=False, yes=True, no=True):
        return
    
    # รันการตรวจสอบ
    checker = ModelHealthChecker(doc)
    checker.run_all_checks(selected_checks)
    checker.generate_report()
    
    # แสดงสรุปผล
    forms.alert(
        "✅ Check completed!\n\nSee detailed report in Output Window",
        title="HealthCheck Complete"
    )

if __name__ == "__main__":
    main()