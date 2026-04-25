# -*- coding: utf-8 -*-
import os
import json
import codecs
from pyrevit import revit, DB, forms, script
from System.Collections.Generic import List

doc = revit.doc

# ==========================================
# 0. โค้ด XAML สำหรับสร้างหน้าต่าง UI อัตโนมัติ (เอา LetterSpacing ออกแล้ว)
# ==========================================
UI_XAML = """<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="NEXUS Filter Manager" Height="500" Width="400"
        Background="#0D1117" WindowStartupLocation="CenterScreen"
        ResizeMode="NoResize" WindowStyle="ToolWindow">
    
    <Window.Resources>
        <Style TargetType="Button">
            <Setter Property="Background" Value="#161B22"/>
            <Setter Property="Foreground" Value="#00E5FF"/>
            <Setter Property="FontFamily" Value="Segoe UI"/>
            <Setter Property="FontSize" Value="14"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="Padding" Value="10"/>
            <Setter Property="Margin" Value="20, 8"/>
            <Setter Property="BorderBrush" Value="#00E5FF"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border Background="{TemplateBinding Background}" 
                                BorderBrush="{TemplateBinding BorderBrush}" 
                                BorderThickness="{TemplateBinding BorderThickness}" 
                                CornerRadius="4">
                            <ContentPresenter HorizontalAlignment="Left" VerticalAlignment="Center" Margin="15,0,0,0"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
            <Style.Triggers>
                <Trigger Property="IsMouseOver" Value="True">
                    <Setter Property="Background" Value="#00E5FF"/>
                    <Setter Property="Foreground" Value="#0D1117"/>
                    <Setter Property="Effect">
                        <Setter.Value>
                            <DropShadowEffect Color="#00E5FF" BlurRadius="15" ShadowDepth="0"/>
                        </Setter.Value>
                    </Setter>
                </Trigger>
            </Style.Triggers>
        </Style>
    </Window.Resources>

    <Grid>
        <StackPanel Margin="10,25,10,10">
            <TextBlock Text="NEXUS" Foreground="#00E5FF" FontSize="28" FontWeight="Black" HorizontalAlignment="Center" FontFamily="Segoe UI">
                <TextBlock.Effect>
                    <DropShadowEffect Color="#00E5FF" BlurRadius="10" ShadowDepth="0"/>
                </TextBlock.Effect>
            </TextBlock>
            <TextBlock Text="ADVANCED FILTER MANAGER" Foreground="#8B949E" FontSize="12" FontWeight="Medium" HorizontalAlignment="Center" Margin="0,0,0,30"/>
            
            <Button Name="btn_export" Content="📊 EXPORT FILTER REPORT" />
            <Button Name="btn_purge" Content="🧹 SMART PURGE UNUSED" />
            <Button Name="btn_delete" Content="🗑️ MANUAL BATCH DELETE" />
            <Button Name="btn_transfer" Content="📥 TRANSFER FROM PROJECT" />
            
            <Rectangle Height="1" Fill="#30363D" Margin="20,20,20,20"/>
            
            <Button Name="btn_close" Content="✖ CLOSE TERMINAL" BorderBrush="#FF0055" Foreground="#FF0055">
                <Button.Style>
                    <Style TargetType="Button" BasedOn="{StaticResource {x:Type Button}}">
                        <Style.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter Property="Background" Value="#FF0055"/>
                                <Setter Property="Foreground" Value="#FFFFFF"/>
                                <Setter Property="Effect">
                                    <Setter.Value>
                                        <DropShadowEffect Color="#FF0055" BlurRadius="15" ShadowDepth="0"/>
                                    </Setter.Value>
                                </Setter>
                            </Trigger>
                        </Style.Triggers>
                    </Style>
                </Button.Style>
            </Button>
        </StackPanel>
    </Grid>
</Window>"""

# ==========================================
# 1. ระบบจดจำและดึง Path
# ==========================================
def get_export_path():
    config_path = os.path.join(os.getenv('APPDATA'), 'pyRevit_FilterManager_Config.json')
    export_dir = None
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                export_dir = config.get("export_path")
        except Exception:
            pass
            
    if not export_dir or not os.path.exists(export_dir):
        export_dir = forms.pick_folder(title="เลือก Folder สำหรับบันทึกไฟล์ Export Filters")
        if export_dir:
            with open(config_path, 'w') as f:
                json.dump({"export_path": export_dir}, f)
        else:
            return None
            
    return export_dir

# ==========================================
# 2. ฟังก์ชันวิเคราะห์ข้อมูล Filter
# ==========================================
def get_filter_categories(f_element, target_doc):
    try:
        cat_ids = f_element.GetCategoryIds()
        cats = []
        for c_id in cat_ids:
            cat = DB.Category.GetCategory(target_doc, c_id)
            if cat:
                cats.append(cat.Name)
        return " & ".join(cats) if cats else "No Category"
    except Exception:
        return "Unknown"

def analyze_filters():
    all_views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
    all_filters = DB.FilteredElementCollector(doc).OfClass(DB.ParameterFilterElement).ToElements()
    
    filter_data = {}
    for f in all_filters:
        filter_data[f.Id] = {
            "Element": f,
            "Name": f.Name,
            "Categories": get_filter_categories(f, doc),
            "UsedInViews": []
        }
        
    for view in all_views:
        if not view.AreGraphicsOverridesAllowed():
            continue
        try:
            view_filters = view.GetFilters()
            for f_id in view_filters:
                if f_id in filter_data:
                    filter_data[f_id]["UsedInViews"].append(view.Name)
        except Exception:
            pass
            
    return filter_data

# ==========================================
# 3. เมนูคำสั่งย่อยต่างๆ
# ==========================================
def cmd_export_report(filter_data):
    export_dir = get_export_path()
    if not export_dir: return
        
    csv_path = os.path.join(export_dir, "Revit_Filters_Usage_Report.csv")
    with codecs.open(csv_path, mode='w', encoding='utf-8-sig') as file:
        file.write("Filter Name,Target Categories,Usage Count,Used In Views\n")
        for f_id, data in filter_data.items():
            name = data["Name"].replace(",", " ")
            categories = data["Categories"].replace(",", " ")
            views = " | ".join(data["UsedInViews"]).replace(",", " ")
            count = str(len(data["UsedInViews"]))
            file.write(u"{},{},{},{}\n".format(name, categories, count, views))
            
    forms.alert("Export สำเร็จ!\nตำแหน่งไฟล์: {}".format(csv_path), title="System Success")

def cmd_smart_purge(filter_data):
    unused_filters = [data["Element"] for f_id, data in filter_data.items() if len(data["UsedInViews"]) == 0]
    
    if not unused_filters:
        forms.alert("โปรเจกต์สะอาด ไม่มี Filter ขยะ", title="System Status")
        return
        
    confirm = forms.alert("พบ {} Filter ที่ไม่ได้ใช้งาน\nยืนยันการลบทั้งหมดหรือไม่?".format(len(unused_filters)), yes=True, no=True, title="Purge Protocol")
    if confirm:
        with revit.Transaction("Purge Unused Filters"):
            for f in unused_filters:
                doc.Delete(f.Id)
        forms.alert("ล้างข้อมูลสำเร็จ {} รายการ".format(len(unused_filters)), title="Purge Success")

def cmd_batch_delete(filter_data):
    options = []
    for f_id, data in filter_data.items():
        usage_count = len(data["UsedInViews"])
        display_name = "{} [ใช้งาน: {} Views]".format(data["Name"], usage_count)
        options.append({"name": display_name, "element": data["Element"]})
        
    options = sorted(options, key=lambda x: x["name"])
    
    selected_items = forms.SelectFromList.show(
        [opt["name"] for opt in options],
        title="Manual Batch Delete",
        multiselect=True
    )
    
    if selected_items:
        elements_to_delete = [opt["element"] for opt in options if opt["name"] in selected_items]
        with revit.Transaction("Batch Delete Filters"):
            for element in elements_to_delete:
                try: doc.Delete(element.Id)
                except Exception: pass
        forms.alert("ลบ Filter ที่เลือกเรียบร้อยแล้ว", title="Delete Success")

def cmd_transfer_filters():
    open_docs = [d for d in __revit__.Application.Documents if not d.IsLinked and d.Title != doc.Title]
    if not open_docs:
        forms.alert("ไม่พบโปรเจกต์อื่นที่เปิดอยู่", title="Transfer Error")
        return

    doc_options = {d.Title: d for d in open_docs}
    selected_doc_title = forms.SelectFromList.show(list(doc_options.keys()), title="1. เลือกโปรเจกต์ต้นทาง", multiselect=False)
    if not selected_doc_title: return
    source_doc = doc_options[selected_doc_title]

    source_filters = DB.FilteredElementCollector(source_doc).OfClass(DB.ParameterFilterElement).ToElements()
    if not source_filters: return

    existing_filter_names = [f.Name for f in DB.FilteredElementCollector(doc).OfClass(DB.ParameterFilterElement).ToElements()]
    filter_options = []
    
    for f in source_filters:
        prefix = "⚠️ [มีอยู่แล้ว] " if f.Name in existing_filter_names else "✅ [ใหม่] "
        filter_options.append({"name": prefix + f.Name, "element": f})

    filter_options = sorted(filter_options, key=lambda x: x["name"])

    selected_filters = forms.SelectFromList.show([opt["name"] for opt in filter_options], title="2. เลือก Filter", multiselect=True)
    if not selected_filters: return

    elements_to_copy = [opt["element"].Id for opt in filter_options if opt["name"] in selected_filters]
    ids_list = List[DB.ElementId](elements_to_copy)
    copy_pasted_tools = DB.CopyPasteOptions()

    with revit.Transaction("Transfer Filters"):
        try:
            DB.ElementTransformUtils.CopyElements(source_doc, ids_list, doc, DB.Transform.Identity, copy_pasted_tools)
            forms.alert("ดาวน์โหลด Filter เข้าโปรเจกต์สำเร็จ!", title="Transfer Success")
        except Exception as e:
            forms.alert("Error:\n" + str(e), title="Transfer Error")

# ==========================================
# 4. คลาสควบคุม UI (XAML Binding)
# ==========================================
class FuturisticUI(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        self.action = None
        
        self.btn_export.Click += self.on_export
        self.btn_purge.Click += self.on_purge
        self.btn_delete.Click += self.on_delete
        self.btn_transfer.Click += self.on_transfer
        self.btn_close.Click += self.on_close

    def on_export(self, sender, args):
        self.action = "export"
        self.Close()

    def on_purge(self, sender, args):
        self.action = "purge"
        self.Close()

    def on_delete(self, sender, args):
        self.action = "delete"
        self.Close()

    def on_transfer(self, sender, args):
        self.action = "transfer"
        self.Close()

    def on_close(self, sender, args):
        self.action = None
        self.Close()

# ==========================================
# Main Execution
# ==========================================
def main():
    script_dir = os.path.dirname(__file__)
    xaml_path = os.path.join(script_dir, 'ui.xaml')
    
    # อัปเกรด: บังคับเขียนไฟล์ ui.xaml ใหม่ทุกครั้งทับของเดิม เพื่อแก้ปัญหาไฟล์เก่าค้าง
    try:
        with codecs.open(xaml_path, 'w', encoding='utf-8') as f:
            f.write(UI_XAML)
    except Exception as e:
        forms.alert("เกิดข้อผิดพลาดในการอัปเดตไฟล์ UI:\n" + str(e), title="Auto-Generate Error")
        return

    # เรียกหน้าต่าง UI ขึ้นมาแสดง
    window = FuturisticUI(xaml_path)
    window.ShowDialog()
    
    if window.action:
        if window.action == "export":
            cmd_export_report(analyze_filters())
        elif window.action == "purge":
            cmd_smart_purge(analyze_filters())
        elif window.action == "delete":
            cmd_batch_delete(analyze_filters())
        elif window.action == "transfer":
            cmd_transfer_filters()

if __name__ == '__main__':
    main()