# -*- coding: utf-8 -*-
"""View Template Manager - DiRootsOne Style"""
__title__ = "View Template (DiRootsOne UI)"
__author__ = "Permpong & Gemini"

import clr

clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
from pyrevit import forms

doc = __revit__.ActiveUIDocument.Document

# --------------------------------------------------------
# ⚙️ CORE ENGINE (Data Analysis)
# --------------------------------------------------------

def get_template_data():
    """Analyze all Templates and fetch usage count"""
    all_tpls = [v for v in FilteredElementCollector(doc).OfClass(View) if v.IsTemplate]
    used_list, unused_list = [], []

    if not all_tpls:
        return [], []

    with forms.ProgressBar(title="Loading View Templates...", cancellable=True) as pb:
        for i, tpl in enumerate(all_tpls):
            if pb.cancelled: break
            pb.update_progress(i + 1, len(all_tpls))

            rule = ParameterFilterRuleFactory.CreateEqualsRule(ElementId(BuiltInParameter.VIEW_TEMPLATE), tpl.Id)
            count = FilteredElementCollector(doc).OfClass(View).WherePasses(ElementParameterFilter(rule)).GetElementCount()

            data = {'el': tpl, 'name': tpl.Name, 'count': count, 'id': tpl.Id}
            if count > 0:
                used_list.append(data)
            else:
                unused_list.append(data)
    
    return used_list, unused_list

# --------------------------------------------------------
# 🛠️ TOOLS (Batch Processing Functions)
# --------------------------------------------------------

def bulk_rename(selected_tpls):
    """Batch Rename selected templates"""
    prefix = forms.ask_for_string(default="", prompt="1. Enter Prefix (Leave blank if none):", title="Rename: Prefix")
    if prefix is None: prefix = ""
    
    find_str = forms.ask_for_string(default="", prompt="2. Enter text to find (Leave blank if none):", title="Rename: Find")
    if find_str is None: find_str = ""
    
    replace_str = ""
    if find_str:
        replace_str = forms.ask_for_string(default="", prompt="3. Enter replacement text:", title="Rename: Replace")
        if replace_str is None: replace_str = ""

    if not prefix and not find_str:
        return

    t = Transaction(doc, "Batch Rename Templates")
    t.Start()
    success_count, error_count = 0, 0
    
    for tpl in selected_tpls:
        old_name = tpl['name']
        new_name = old_name
        
        if find_str: new_name = new_name.replace(find_str, replace_str)
        if prefix: new_name = prefix + new_name
        
        if new_name != old_name:
            try: 
                tpl['el'].Name = new_name
                success_count += 1
            except: 
                error_count += 1
                pass
                
    t.Commit()
    
    if error_count > 0:
        forms.alert("Renamed {} items.\nFailed {} items (Skipped due to duplicate names).".format(success_count, error_count))
    else:
        forms.alert("Successfully renamed {} items.".format(success_count))

def duplicate_templates(selected_tpls):
    """Batch Duplicate selected templates"""
    suffix = forms.ask_for_string(default="_Copy", prompt="Enter Suffix for duplicated templates:", title="Batch Duplicate")
    if suffix is None: return
    
    t = Transaction(doc, "Batch Duplicate Templates")
    t.Start()
    for tpl in selected_tpls:
        try:
            new_tpl_id = tpl['el'].Duplicate(ViewDuplicateOption.Duplicate)
            doc.GetElement(new_tpl_id).Name = tpl['name'] + suffix
        except: pass
    t.Commit()
    forms.alert("Successfully duplicated {} items.".format(len(selected_tpls)))

# --------------------------------------------------------
# 🎨 UI & DASHBOARD (Unified View)
# --------------------------------------------------------

class TemplateOption(forms.TemplateListItem):
    """Custom UI Wrapper: Formats the list to look like a DataGrid"""
    @property
    def name(self):
        # สร้างการแสดงผลแบบตาราง (Grid Layout) ในบรรทัดเดียว
        status_icon = "🟢 [ ACTIVE ]" if self.item['count'] > 0 else "🔴 [ UNUSED ]"
        view_count = "Views: {:02d}".format(self.item['count'])
        return "{}  |  {}  ➡️  {}".format(status_icon, view_count, self.item['name'])

def run_manager():
    while True:
        used, unused = get_template_data()
        all_data = used + unused
        
        if not all_data:
            forms.alert("No View Templates found in this project.", exitscript=True)

        # ห่อข้อมูลเพื่อแสดงผล
        list_items = [TemplateOption(tpl) for tpl in all_data]
        
        # สร้างข้อความ Dashboard เพื่อนำไปโชว์ในหน้าต่างหลักเลย
        dashboard_msg = "📊 DASHBOARD: Total {}  |  ✅ Active: {}  |  ⚠️ Unused: {}\n\nSelect templates below and click 'Next Action':".format(
            len(all_data), len(used), len(unused)
        )
        
        # 1. หน้าต่างหลัก (Main Hub) - แสดงทุกอย่าง
        selected_items = forms.SelectFromList.show(
            list_items,
            title="DiRootsOne Style DataGrid",
            message=dashboard_msg,
            button_name="Next Action ⚙️",
            multiselect=True
        )
        
        if not selected_items:
            break # ปิดหน้าต่าง (จบการทำงาน)
            
        # 2. แถบเครื่องมือจัดการ (Action Toolbar)
        ops = {
            "📄 Duplicate Selected Templates": "DUPLICATE",
            "✏️ Rename Selected Templates": "RENAME",
            "❌ Delete Selected Templates (Unused Only)": "DELETE",
            "🔙 Cancel (Back to List)": "BACK"
        }
        
        choice = forms.CommandSwitchWindow.show(
            ops.keys(), 
            message="Apply action to {} selected templates:".format(len(selected_items)),
            title="Action Menu"
        )
        
        if not choice or ops[choice] == "BACK":
            continue
        
        if ops[choice] == "DUPLICATE":
            duplicate_templates(selected_items)
            
        elif ops[choice] == "RENAME":
            bulk_rename(selected_items)
            
        elif ops[choice] == "DELETE":
            to_delete = [tpl for tpl in selected_items if tpl['count'] == 0]
            ignored = len(selected_items) - len(to_delete)
            
            if not to_delete:
                forms.alert("None of the selected templates are UNUSED.\nActive templates cannot be deleted from here.")
            else:
                msg = "Confirm deletion of {} UNUSED templates?".format(len(to_delete))
                if ignored > 0:
                    msg += "\n\n(Safety Guard: {} ACTIVE templates were automatically skipped)".format(ignored)
                
                if forms.alert(msg, yes=True, no=True):
                    with Transaction(doc, "Batch Delete Unused Templates") as t:
                        t.Start()
                        for tpl in to_delete: doc.Delete(tpl['el'].Id)
                        t.Commit()
                    forms.alert("Deleted {} items successfully.".format(len(to_delete)))

if __name__ == "__main__":
    run_manager()