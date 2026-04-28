# -*- coding: utf-8 -*-
"""View Template Manager - Ultimate Pro (Single Window GUI)"""
__title__ = "View Template (Single Hub)"
__author__ = "Permpong & Gemini"

import clr
import System
import tempfile
import os
import codecs
from System.Collections.Generic import List

clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
from pyrevit import forms, script

doc = __revit__.ActiveUIDocument.Document
app = __revit__.Application
output = script.get_output()

# ========================================================
# 1. XAML: กราฟิกดีไซน์หน้าต่าง (Single Window UI)
# ========================================================
XAML_UI = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="View Template Manager Ultimate (Single Window Hub)" Height="750" Width="1000" WindowStartupLocation="CenterScreen">
    <Grid Margin="15">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <Border Background="#F5F6F7" CornerRadius="8" Padding="15" Margin="0,0,0,15" BorderBrush="#E0E0E0" BorderThickness="1">
            <TextBlock x:Name="tb_dashboard" Foreground="#333333" FontSize="14" FontWeight="SemiBold" TextWrapping="Wrap"/>
        </Border>

        <ListView x:Name="lv_templates" Grid.Row="1" SelectionMode="Extended" BorderBrush="#CCCCCC" BorderThickness="1">
            <ListView.View>
                <GridView>
                    <GridViewColumn Header="Type Category" Width="150" DisplayMemberBinding="{Binding type}"/>
                    <GridViewColumn Header="Status" Width="110" DisplayMemberBinding="{Binding status}"/>
                    <GridViewColumn Header="Views" Width="80" DisplayMemberBinding="{Binding count}"/>
                    <GridViewColumn Header="Template Name" Width="600" DisplayMemberBinding="{Binding name}"/>
                </GridView>
            </ListView.View>
        </ListView>

        <StackPanel Grid.Row="2" Margin="0,15,0,0">
            <TextBlock Text="🛠️ BATCH ACTIONS (Select templates in the grid above)" FontWeight="Bold" Foreground="#2C3E50" Margin="0,0,0,8"/>
            <WrapPanel Margin="0,0,0,15">
                <Button Content="📄 Duplicate" Width="120" Height="32" Margin="0,0,10,0" Click="btn_duplicate"/>
                <Button Content="✏️ Rename" Width="120" Height="32" Margin="0,0,10,0" Click="btn_rename"/>
                <Button Content="❌ Delete (Unused)" Width="140" Height="32" Margin="0,0,10,0" Click="btn_delete" Background="#FFEBEE" BorderBrush="#FFCDD2" Foreground="#C62828" FontWeight="Bold"/>
            </WrapPanel>
            
            <TextBlock Text="🚀 ADVANCED TOOLS" FontWeight="Bold" Foreground="#2C3E50" Margin="0,0,0,8"/>
            <WrapPanel>
                <Button Content="👁️ Show Linked Views" Width="150" Height="32" Margin="0,0,10,0" Click="btn_show"/>
                <Button Content="⚖️ Compare Settings" Width="130" Height="32" Margin="0,0,10,0" Click="btn_compare"/>
                <Button Content="🎯 Apply to Views" Width="130" Height="32" Margin="0,0,10,0" Click="btn_apply"/>
                <Button Content="🧹 Reset 'Include'" Width="130" Height="32" Margin="0,0,10,0" Click="btn_reset"/>
                <Button Content="📥 Import Templates" Width="140" Height="32" Margin="0,0,10,0" Click="btn_import"/>
            </WrapPanel>
        </StackPanel>
    </Grid>
</Window>
"""

# ========================================================
# 2. CORE ENGINE & TOOLS
# ========================================================
def get_template_data():
    all_tpls = [v for v in FilteredElementCollector(doc).OfClass(View) if v.IsTemplate]
    used_list, unused_list = [], []
    if not all_tpls: return [], []

    type_map = {
        "FloorPlan": "📐 PLAN", "CeilingPlan": "💡 CEILING", "Elevation": "⛰️ ELEVATION",
        "ThreeD": "🧊 3D", "Schedule": "📋 SCHEDULE", "DraftingView": "📝 DRAFTING",
        "Section": "✂️ SECTION", "Detail": "🔍 DETAIL", "AreaPlan": "📏 AREA"
    }

    for tpl in all_tpls:
        rule = ParameterFilterRuleFactory.CreateEqualsRule(ElementId(BuiltInParameter.VIEW_TEMPLATE), tpl.Id)
        linked_views = FilteredElementCollector(doc).OfClass(View).WherePasses(ElementParameterFilter(rule)).ToElements()
        count = len(linked_views)
        raw_type = str(tpl.ViewType).replace("ViewType.", "")
        
        data = {
            'el': tpl, 'name': tpl.Name, 'count': count, 'id': tpl.Id, 
            'type': type_map.get(raw_type, "📄 " + raw_type.upper()), 'linked': linked_views
        }
        if count > 0: used_list.append(data)
        else: unused_list.append(data)
    
    return used_list, unused_list

# Class สำหรับโยนข้อมูลเข้าตาราง (Data Binding)
class TemplateItem(object):
    def __init__(self, data): self.data = data
    @property
    def name(self): return self.data['name']
    @property
    def type(self): return self.data['type']
    @property
    def status(self): return "🟢 ACTIVE" if self.data['count'] > 0 else "🔴 UNUSED"
    @property
    def count(self): return str(self.data['count'])

# ========================================================
# 3. WINDOW CONTROLLER (ควบคุมปุ่มกดและหน้าต่าง)
# ========================================================
class ViewTemplateManagerUI(forms.WPFWindow):
    def __init__(self, xaml_file_path):
        forms.WPFWindow.__init__(self, xaml_file_path)
        self.refresh_data()

    def refresh_data(self):
        """ดึงข้อมูลใหม่และอัปเดตหน้าจอทันที"""
        used, unused = get_template_data()
        self.all_data = sorted(used + unused, key=lambda x: (x['type'], x['name']))
        
        # อัปเดตข้อความ Dashboard
        self.tb_dashboard.Text = (
            "📊 SYSTEM DASHBOARD\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            " 📦 Total Templates  : {} รายการ\n"
            " 🟢 Active (In Use)  : {} รายการ\n"
            " 🔴 Unused (Orphan)  : {} รายการ\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📌 กรุณาคลิกเลือก Template ในตารางด้านล่าง และกดปุ่มคำสั่งที่ต้องการได้เลย"
        ).format(len(self.all_data), len(used), len(unused))
        
        # อัปเดตตาราง
        self.lv_templates.ItemsSource = [TemplateItem(d) for d in self.all_data]

    def get_selected(self):
        """ดึงรายการที่ผู้ใช้ไฮไลท์เลือกอยู่"""
        return [item.data for item in self.lv_templates.SelectedItems]

    # --- ฟังก์ชันเมื่อกดปุ่ม (Event Handlers) ---
    def btn_duplicate(self, sender, e):
        sel = self.get_selected()
        if not sel: return forms.alert("กรุณาเลือก Template ที่ต้องการก่อนครับ")
        
        suffix = forms.ask_for_string(default="_Copy", prompt="Enter Suffix:", title="Batch Duplicate")
        if not suffix: return
        
        t = Transaction(doc, "Batch Duplicate Templates")
        t.Start()
        for tpl in sel:
            try:
                new_id = tpl['el'].Duplicate(ViewDuplicateOption.Duplicate)
                doc.GetElement(new_id).Name = tpl['name'] + suffix
            except: pass
        t.Commit()
        forms.alert("Duplicated {} items.".format(len(sel)))
        self.refresh_data() # อัปเดตตารางอัตโนมัติ

    def btn_rename(self, sender, e):
        sel = self.get_selected()
        if not sel: return forms.alert("กรุณาเลือก Template ที่ต้องการก่อนครับ")
        
        prefix = forms.ask_for_string(default="", prompt="1. Enter Prefix (ปล่อยว่างได้):", title="Batch Rename")
        if prefix is None: return
        find_str = forms.ask_for_string(default="", prompt="2. Enter text to find (ปล่อยว่างได้):", title="Batch Rename")
        if find_str is None: return
        replace_str = ""
        if find_str:
            replace_str = forms.ask_for_string(default="", prompt="3. Enter replacement text:", title="Batch Rename")
            if replace_str is None: return

        t = Transaction(doc, "Batch Rename Templates")
        t.Start()
        for tpl in sel:
            old_name, new_name = tpl['name'], tpl['name']
            if find_str: new_name = new_name.replace(find_str, replace_str)
            if prefix: new_name = prefix + new_name
            if new_name != old_name:
                try: tpl['el'].Name = new_name
                except: pass
        t.Commit()
        self.refresh_data()

    def btn_delete(self, sender, e):
        sel = self.get_selected()
        if not sel: return forms.alert("กรุณาเลือก Template ที่ต้องการก่อนครับ")
        
        to_delete = [tpl for tpl in sel if tpl['count'] == 0]
        if not to_delete: return forms.alert("ไม่สามารถลบได้! ไฟล์ที่คุณเลือกมีสถานะ ACTIVE ทั้งหมด")
            
        if forms.alert("ยืนยันการลบ {} UNUSED templates?\n\n(Safety Guard: ไฟล์ Active จะไม่ถูกลบ)", yes=True, no=True):
            with Transaction(doc, "Batch Delete Unused Templates") as t:
                t.Start()
                for tpl in to_delete: doc.Delete(tpl['el'].Id)
                t.Commit()
            self.refresh_data()

    def btn_show(self, sender, e):
        sel = self.get_selected()
        if len(sel) != 1: return forms.alert("กรุณาเลือกเพียง 1 Template เพื่อดูข้อมูลครับ")
        if not sel[0]['linked']: return forms.alert("Template นี้ไม่ได้ถูกใช้งานอยู่เลยครับ (UNUSED)")
        names = sorted([v.Name for v in sel[0]['linked']])
        forms.SelectFromList.show(names, title="Views using: " + sel[0]['name'], button_name="รับทราบ")

    def btn_compare(self, sender, e):
        sel = self.get_selected()
        if len(sel) != 2: return forms.alert("กรุณาเลือก 2 Templates เท่านั้นเพื่อทำการเปรียบเทียบครับ")
        
        tpl1, tpl2 = sel[0], sel[1]
        p1 = {p.Definition.Name: (p.AsValueString() or p.AsString() or "") for p in tpl1['el'].Parameters}
        p2 = {p.Definition.Name: (p.AsValueString() or p.AsString() or "") for p in tpl2['el'].Parameters}
        diff = []
        for k in sorted(set(p1.keys()).union(set(p2.keys()))):
            v1, v2 = p1.get(k, "N/A"), p2.get(k, "N/A")
            if v1 != v2: diff.append([k, v1, v2])
                
        if diff:
            output.print_md("## ⚖️ Compare Template Differences")
            output.print_table(diff, columns=["Parameter", "Value in A", "Value in B"])
            forms.alert("ประมวลผลเสร็จสิ้น!\nกรุณาตรวจสอบตารางความต่างที่หน้าต่าง Output ด้านหลัง")
        else:
            forms.alert("ทั้ง 2 Templates นี้มีการตั้งค่าเหมือนกันทุกประการครับ")

    def btn_apply(self, sender, e):
        sel = self.get_selected()
        if len(sel) != 1: return forms.alert("กรุณาเลือก 1 Template ที่ต้องการนำไปสวมให้ Views ครับ")
        
        target_type = sel[0]['el'].ViewType
        all_views = [v for v in FilteredElementCollector(doc).OfClass(View) if not v.IsTemplate and v.ViewType == target_type]
        if not all_views: return forms.alert("ไม่พบ View ชนิดเดียวกันที่รองรับ Template นี้ครับ")
            
        class ViewOption(forms.TemplateListItem):
            @property
            def name(self): return self.item.Name
            
        list_items = [ViewOption(v) for v in sorted(all_views, key=lambda x: x.Name)]
        selected_views = forms.SelectFromList.show(list_items, multiselect=True, title="Apply to Views")
        
        if selected_views:
            t = Transaction(doc, "Apply View Template")
            t.Start()
            for v in selected_views: v.ViewTemplateId = sel[0]['el'].Id
            t.Commit()
            self.refresh_data() # อัปเดต Dashboard เพราะยอดลิงก์เปลี่ยน

    def btn_reset(self, sender, e):
        sel = self.get_selected()
        if not sel: return forms.alert("กรุณาเลือก Template ก่อนครับ")
        t = Transaction(doc, "Reset Template Includes")
        t.Start()
        for tpl in sel:
            try: tpl['el'].SetNonControlledTemplateParameterIds(List[ElementId]())
            except: pass
        t.Commit()
        forms.alert("เช็คถูก 'Include' ครบทุกช่องเรียบร้อยครับ")

    def btn_import(self, sender, e):
        open_docs = [d for d in app.Documents if d.Title != doc.Title]
        if not open_docs: return forms.alert("กรุณาเปิดไฟล์ Revit โปรเจกต์อื่นค้างไว้ก่อนทำการ Import ครับ")
            
        class DocOption(forms.TemplateListItem):
            @property
            def name(self): return self.item.Title
            
        selected_doc = forms.SelectFromList.show([DocOption(d) for d in open_docs], title="Select Source Project")
        if not selected_doc: return
        
        other_tpls = [v for v in FilteredElementCollector(selected_doc).OfClass(View) if v.IsTemplate]
        if not other_tpls: return forms.alert("ไม่พบ Template ในไฟล์ที่เลือกครับ")
            
        selected_to_import = forms.SelectFromList.show(other_tpls, name_attr='Name', multiselect=True, title="Select Templates")
        if selected_to_import:
            t = Transaction(doc, "Import View Templates")
            t.Start()
            ids = List[ElementId]([v.Id for v in selected_to_import])
            options = CopyPasteOptions()
            try: ElementTransformUtils.CopyElements(selected_doc, ids, doc, Transform.Identity, options)
            except Exception as ex: forms.alert("Import failed: {}".format(str(ex)))
            t.Commit()
            self.refresh_data() # อัปเดตกระดานเพื่อโชว์ตัวที่ดึงมาใหม่

# ========================================================
# 4. EXECUTION (สร้างและเปิดหน้าต่าง)
# ========================================================
if __name__ == "__main__":
    # สร้างไฟล์ชั่วคราวเพื่ออ่านโค้ดหน้าต่าง XAML (ลบตัวเองทิ้งทันทีเมื่อใช้เสร็จ ป้องกันไฟล์ขยะ)
    fd, path = tempfile.mkstemp(suffix=".xaml")
    with codecs.open(path, 'w', 'utf-8') as f:
        f.write(XAML_UI)
    os.close(fd)
    
    try:
        # เปิดหน้าต่างโปรแกรม
        ui = ViewTemplateManagerUI(path)
        ui.ShowDialog()
    finally:
        # ทำลายไฟล์ขยะทิ้ง
        os.remove(path)