# -*- coding: utf-8 -*-
"""
One Parameter Manager - No Output Console
ไม่แสดง Output Window ของ pyRevit
แสดงผลผ่าน forms.alert() เท่านั้น
"""

__title__ = 'Parameter\nManager'
__author__ = 'เพิ่มพงษ์ ทวีกุล'

import json
import codecs
import os
import time

from pyrevit import revit, DB, forms, script

# ------------------------------------------------------------
# Revit document objects
# ------------------------------------------------------------
doc = revit.doc
app = doc.Application
uidoc = revit.uidoc
cfg = script.get_config()

# ------------------------------------------------------------
# 1. ForgeTypeId Helpers (Revit 2026 Compatibility)
# ------------------------------------------------------------
def get_safe_group_id(group_name):
    if hasattr(DB, "GroupTypeId"):
        clean = group_name.replace("PG_", "").upper()
        mapping = {
            "DATA": "Data", "IDENTITY_DATA": "IdentityData",
            "CONSTRAINTS": "Constraints", "GRAPHICS": "Graphics",
            "DIMENSIONS": "Dimensions", "ANALYSIS_RESULTS": "AnalysisResults"
        }
        attr_name = mapping.get(clean, "Data")
        return getattr(DB.GroupTypeId, attr_name, DB.GroupTypeId.Data)
    pg_str = "PG_" + group_name if not group_name.startswith("PG_") else group_name
    return getattr(DB.BuiltInParameterGroup, pg_str, DB.BuiltInParameterGroup.PG_DATA)

def get_safe_spec_id(type_str):
    if hasattr(DB, "SpecTypeId"):
        m = {"Text": DB.SpecTypeId.String.Text, "Integer": DB.SpecTypeId.Int,
             "Number": DB.SpecTypeId.Number, "Length": DB.SpecTypeId.Length,
             "Area": DB.SpecTypeId.Area, "Yes/No": DB.SpecTypeId.Boolean.YesNo}
        return m.get(type_str, DB.SpecTypeId.String.Text)
    return getattr(DB.ParameterType, type_str if type_str != "Text" else "String")

# ------------------------------------------------------------
# 2. Enhanced Parameter Manager
# ------------------------------------------------------------
class EnhancedParameterManager:
    def __init__(self, doc):
        self.doc = doc
        self._parameters_cache = None
        self._cache_time = None
        self._cache_duration = 30

    def get_all_parameters(self, force_refresh=False):
        current_time = time.time()
        if not force_refresh and self._parameters_cache and self._cache_time and \
           (current_time - self._cache_time) < self._cache_duration:
            return self._parameters_cache
        
        try:
            binding_map = self.doc.ParameterBindings
            it = binding_map.ForwardIterator()
            parameters = []
            all_elements = self._get_all_elements_for_usage_check()
            
            while it.MoveNext():
                defn = it.Key
                bind = it.Current
                
                name = defn.Name
                param_type = self._get_param_type(defn)
                categories = [c.Name for c in bind.Categories if hasattr(c, 'Name')]
                is_instance = isinstance(bind, DB.InstanceBinding)
                is_shared = isinstance(defn, DB.ExternalDefinition)
                guid = defn.GUID.ToString() if hasattr(defn, "GUID") else None
                is_used = self._is_parameter_used_accurate(name, categories, is_instance, all_elements)
                
                group = "DATA"
                try:
                    if hasattr(defn, "GetGroupTypeId"):
                        group = defn.GetGroupTypeId().TypeId
                    elif hasattr(defn, "ParameterGroup"):
                        group = str(defn.ParameterGroup)
                except:
                    pass
                group = group.replace("PG_", "").split('.')[-1]
                
                parameters.append({
                    'name': name,
                    'type': param_type,
                    'group': group,
                    'binding': 'Instance' if is_instance else 'Type',
                    'categories': categories,
                    'is_used': is_used,
                    'definition': defn,
                    'is_instance': is_instance,
                    'is_shared': is_shared,
                    'guid': guid,
                    'is_builtin': hasattr(defn, 'BuiltInParameter') and defn.BuiltInParameter != DB.BuiltInParameter.INVALID
                })
            
            self._parameters_cache = sorted(parameters, key=lambda x: x['name'])
            self._cache_time = time.time()
            return self._parameters_cache
        except Exception as e:
            print("Error: {}".format(str(e)))
            return []

    def _get_all_elements_for_usage_check(self):
        collector = DB.FilteredElementCollector(self.doc)
        elements = list(collector.WhereElementIsNotElementType().ToElements())
        types = list(collector.WhereElementIsElementType().ToElements())
        all_elems = (elements + types)[:2000]
        return all_elems

    def _get_param_type(self, definition):
        try:
            if hasattr(definition, 'ParameterType'):
                return str(definition.ParameterType).split('.')[-1]
            elif hasattr(definition, 'GetDataType'):
                return str(definition.GetDataType()).split('.')[-1]
            return "Unknown"
        except:
            return "Unknown"

    def _is_parameter_used_accurate(self, param_name, categories, is_instance, all_elements):
        if not all_elements:
            return False
        max_check = min(500, len(all_elements))
        for elem in all_elements[:max_check]:
            try:
                if not elem.IsValidObject:
                    continue
                if not is_instance and isinstance(elem, DB.ElementType):
                    p = elem.get_Parameter(param_name)
                elif is_instance and not isinstance(elem, DB.ElementType):
                    p = elem.LookupParameter(param_name)
                else:
                    continue
                if p and not p.IsReadOnly:
                    if p.StorageType == DB.StorageType.String:
                        if p.AsString() not in [None, ""]:
                            return True
                    elif p.StorageType == DB.StorageType.Double:
                        if abs(p.AsDouble()) > 1e-9:
                            return True
                    elif p.StorageType == DB.StorageType.Integer:
                        if p.AsInteger() != 0:
                            return True
                    elif p.StorageType == DB.StorageType.ElementId:
                        if p.AsElementId().IntegerValue != -1:
                            return True
            except:
                continue
        return False

    def delete_parameter_force(self, definition):
        try:
            if hasattr(definition, 'BuiltInParameter') and definition.BuiltInParameter != DB.BuiltInParameter.INVALID:
                return False, "Built-in parameter (cannot delete)"
            if self.doc.ParameterBindings.Remove(definition):
                self._parameters_cache = None
                return True, "Deleted successfully"
            else:
                return False, "Revit refused (may be in use or shared from external file)"
        except Exception as e:
            return False, str(e)

    def delete_multiple_parameters(self, definitions):
        success = []
        failed = []
        for defn in definitions:
            ok, msg = self.delete_parameter_force(defn)
            if ok:
                success.append(defn.Name)
            else:
                failed.append((defn.Name, msg))
        self._parameters_cache = None
        return success, failed

# ------------------------------------------------------------
# 3. Export / Import
# ------------------------------------------------------------
def export_parameters():
    mgr = EnhancedParameterManager(doc)
    params = mgr.get_all_parameters()
    if not params:
        forms.alert("❌ ไม่พบ Project Parameters", title="Export")
        return
    
    names = [p['name'] for p in params]
    selected = forms.SelectFromList.show(names, multiselect=True, title="เลือก Parameter เพื่อ Export", button_name="Export")
    if not selected:
        return
    
    out = []
    for name in selected:
        p = next(x for x in params if x['name'] == name)
        out.append({
            "Name": p['name'],
            "ParameterType": p['type'],
            "Group": p['group'],
            "IsShared": p['is_shared'],
            "GUID": p['guid'],
            "IsInstance": p['is_instance'],
            "Categories": p['categories']
        })
    
    path = forms.save_file(file_ext='json', default_name='ProjectParams.json', init_dir=getattr(cfg, 'last_dir', ''))
    if path:
        cfg.last_dir = os.path.dirname(path)
        script.save_config()
        with codecs.open(path, 'w', encoding='utf-8') as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        forms.alert("✅ Export สำเร็จ ({} parameters)".format(len(out)), title="Export")

def import_parameters():
    path = forms.pick_file(file_ext='json', init_dir=getattr(cfg, 'last_dir', ''), title="เลือกไฟล์ JSON")
    if not path:
        return
    cfg.last_dir = os.path.dirname(path)
    script.save_config()
    with codecs.open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    cat_map = {c.Name: c for c in doc.Settings.Categories if c.AllowsBoundParameters}
    success = 0
    fail = []
    with DB.Transaction(doc, "Import Project Parameters") as t:
        t.Start()
        for p in data:
            try:
                c_set = DB.CategorySet()
                for c_name in p.get('Categories', []):
                    if c_name in cat_map:
                        c_set.Insert(cat_map[c_name])
                if c_set.IsEmpty:
                    fail.append("{} (ไม่มีหมวดหมู่)".format(p['Name']))
                    continue
                
                temp_path = os.path.join(os.environ['TEMP'], "p13_bridge.txt")
                if not os.path.exists(temp_path):
                    open(temp_path, "w").close()
                old_path = app.SharedParametersFilename
                app.SharedParametersFilename = temp_path
                try:
                    df = app.OpenSharedParameterFile()
                    if not df:
                        raise Exception("Cannot open temp shared param file")
                    g = df.Groups.get_Item("Temp") or df.Groups.Create("Temp")
                    opt = DB.ExternalDefinitionCreationOptions(p['Name'], get_safe_spec_id(p['ParameterType']))
                    defn = g.Definitions.get_Item(p['Name']) or g.Definitions.Create(opt)
                    bind = DB.InstanceBinding(c_set) if p.get('IsInstance', True) else DB.TypeBinding(c_set)
                    doc.ParameterBindings.Insert(defn, bind, get_safe_group_id(p.get('Group', 'DATA')))
                    success += 1
                finally:
                    app.SharedParametersFilename = old_path
            except Exception as e:
                fail.append("{} ({})".format(p['Name'], str(e)))
        t.Commit()
    msg = "✅ Import สำเร็จ: {}\n❌ ล้มเหลว: {}".format(success, len(fail))
    if fail:
        msg += "\n\n" + "\n".join(fail[:10])
        if len(fail) > 10:
            msg += "\n... และอีก {} รายการ".format(len(fail)-10)
    forms.alert(msg, title="Import Result")

# ------------------------------------------------------------
# 4. Delete Functions
# ------------------------------------------------------------
def delete_selected_parameters():
    try:
        mgr = EnhancedParameterManager(doc)
        params = mgr.get_all_parameters()
        if not params:
            forms.alert("❌ No project parameters found")
            return
        
        display = []
        for p in params:
            status = "🔴" if p['is_used'] else "🟢"
            binding_icon = "👤" if p['is_instance'] else "📁"
            shared_tag = " [Shared]" if p['is_shared'] else ""
            builtin_tag = " [Built-in]" if p.get('is_builtin', False) else ""
            display.append("{}{} {}{}{}".format(status, binding_icon, p['name'], shared_tag, builtin_tag))
        
        selected = forms.SelectFromList.show(display, multiselect=True, title="Select parameters to delete (force attempt)",
                                              button_name='Delete Selected', width=600)
        if not selected:
            return
        
        selected_params = []
        for item in selected:
            idx = display.index(item)
            selected_params.append(params[idx])
        
        summary = "⚠️ Force delete {} parameter(s):\n\n".format(len(selected_params))
        for i, p in enumerate(selected_params[:20]):
            summary += "{}. {} [{}] {}\n".format(i+1, p['name'], p['binding'], "[Shared]" if p['is_shared'] else "")
        if len(selected_params) > 20:
            summary += "... and {} more\n".format(len(selected_params)-20)
        summary += "\nNote: Shared parameters may not delete via API. Built-in parameters cannot be deleted."
        
        confirm = forms.alert(summary, options=["Attempt Delete", "Cancel"], title="Confirm Force Delete")
        if confirm != "Attempt Delete":
            return
        
        with DB.Transaction(doc, "Delete Parameters") as t:
            t.Start()
            definitions = [p['definition'] for p in selected_params]
            success_list, failed_list = mgr.delete_multiple_parameters(definitions)
            t.Commit()
        
        if success_list:
            msg = "✅ Successfully deleted {} parameters.\n❌ Failed {}:\n".format(len(success_list), len(failed_list))
            for name, reason in failed_list[:15]:
                msg += "  • {} - {}\n".format(name, reason)
            if len(failed_list) > 15:
                msg += "  ... and {} more".format(len(failed_list)-15)
            forms.alert(msg, title="Delete Result")
        else:
            msg = "❌ No parameters were deleted.\n\nReasons:\n"
            for name, reason in failed_list[:15]:
                msg += "  • {} - {}\n".format(name, reason)
            forms.alert(msg, title="Delete Failed")
    except Exception as e:
        forms.alert("❌ Error: {}".format(str(e)))

def cleanup_unused_parameters():
    try:
        mgr = EnhancedParameterManager(doc)
        params = mgr.get_all_parameters()
        if not params:
            forms.alert("❌ No project parameters found")
            return
        
        unused = [p for p in params if not p['is_used']]
        if not unused:
            forms.alert("🎉 No unused parameters detected (based on current elements).")
            return
        
        display = []
        for p in unused:
            binding_icon = "👤" if p['is_instance'] else "📁"
            shared_tag = " [Shared]" if p['is_shared'] else ""
            display.append("{} {}{}".format(binding_icon, p['name'], shared_tag))
        
        selected = forms.SelectFromList.show(display, multiselect=True,
                                             title="Unused parameters ({} found)".format(len(unused)),
                                             button_name='Delete Selected', width=500)
        if not selected:
            return
        
        selected_params = []
        for item in selected:
            name_part = item.split(' ', 1)[1].split(' [')[0]
            p = next((x for x in unused if x['name'] == name_part), None)
            if p:
                selected_params.append(p)
        
        if not selected_params:
            return
        
        summary = "Confirm delete {} unused parameter(s):\n\n".format(len(selected_params))
        for i, p in enumerate(selected_params[:15]):
            summary += "{}. {}\n".format(i+1, p['name'])
        if len(selected_params) > 15:
            summary += "... and {} more".format(len(selected_params)-15)
        confirm = forms.alert(summary, options=["Delete", "Cancel"], title="Confirm")
        if confirm != "Delete":
            return
        
        with DB.Transaction(doc, "Delete Unused Parameters") as t:
            t.Start()
            definitions = [p['definition'] for p in selected_params]
            success_list, failed_list = mgr.delete_multiple_parameters(definitions)
            t.Commit()
        
        if success_list:
            msg = "✅ Deleted {} parameters.\n❌ Failed {}:\n".format(len(success_list), len(failed_list))
            for name, reason in failed_list[:15]:
                msg += "  • {} - {}\n".format(name, reason)
            forms.alert(msg, title="Result")
        else:
            forms.alert("❌ Could not delete any parameters.", title="Failed")
    except Exception as e:
        forms.alert("❌ Error: {}".format(str(e)))

# ------------------------------------------------------------
# 5. Report & View (No Output Console)
# ------------------------------------------------------------
def quick_parameter_report():
    """แสดงรายงานผ่าน forms.alert แทน output window"""
    try:
        mgr = EnhancedParameterManager(doc)
        params = mgr.get_all_parameters()
        if not params:
            forms.alert("❌ ไม่พบ Project Parameters", title="รายงาน")
            return
        
        total = len(params)
        used = sum(1 for p in params if p['is_used'])
        unused = total - used
        instance = sum(1 for p in params if p['is_instance'])
        shared = sum(1 for p in params if p['is_shared'])
        
        # สร้างข้อความสรุป
        msg = "📊 รายงาน Project Parameters\n"
        msg += "="*40 + "\n"
        msg += "ทั้งหมด: {} Parameters\n".format(total)
        msg += "ถูกใช้งาน: {}\n".format(used)
        msg += "ไม่ถูกใช้งาน: {}\n".format(unused)
        msg += "Instance: {} | Type: {}\n".format(instance, total-instance)
        msg += "Shared Parameters: {}\n".format(shared)
        msg += "="*40 + "\n"
        msg += "\n📋 รายชื่อ Parameters (แสดงเฉพาะชื่อ):\n"
        
        # แสดงชื่อ parameter (จำกัดจำนวน)
        for i, p in enumerate(sorted(params, key=lambda x: x['name'])[:30]):
            status = "✔️" if p['is_used'] else "❌"
            msg += "{}. {} {}\n".format(i+1, status, p['name'])
        if total > 30:
            msg += "... และอีก {} รายการ".format(total-30)
        
        # ถ้าต้องการ export รายละเอียดเพิ่มเติม ให้ถาม
        if forms.alert(msg + "\n\nต้องการ export รายงานเป็นไฟล์ข้อความหรือไม่?", 
                       options=["Export", "ปิด"], title="รายงาน Parameters") == "Export":
            path = forms.save_file(file_ext='txt', default_name='ParameterReport.txt', init_dir=getattr(cfg, 'last_dir', ''))
            if path:
                with codecs.open(path, 'w', encoding='utf-8') as f:
                    f.write(msg)
                    f.write("\n\nรายละเอียดเพิ่มเติม:\n")
                    for p in params:
                        f.write("{} | {} | {} | หมวดหมู่: {}\n".format(
                            p['name'], p['type'], p['binding'], ", ".join(p['categories'][:3])))
                forms.alert("✅ Export รายงานสำเร็จ", title="Export")
    except Exception as e:
        forms.alert("❌ เกิดข้อผิดพลาด: {}".format(str(e)))

def view_parameter_details():
    try:
        mgr = EnhancedParameterManager(doc)
        params = mgr.get_all_parameters()
        if not params:
            forms.alert("No parameters")
            return
        display = ["{} {} {}".format("🔴" if p['is_used'] else "🟢", "👤" if p['is_instance'] else "📁", p['name']) for p in params]
        selected = forms.SelectFromList.show(display, title="Select parameter", button_name="Details", multiselect=False)
        if not selected:
            return
        idx = display.index(selected)
        p = params[idx]
        detail = [
            "Name: {}".format(p['name']),
            "Type: {}".format(p['type']),
            "Group: {}".format(p['group']),
            "Binding: {}".format(p['binding']),
            "In use: {}".format("Yes" if p['is_used'] else "No"),
            "Shared: {}".format("Yes" if p['is_shared'] else "No"),
            "",
            "Categories ({}):".format(len(p['categories']))
        ]
        for cat in p['categories'][:10]:
            detail.append("  • {}".format(cat))
        if len(p['categories']) > 10:
            detail.append("  ... and {} more".format(len(p['categories'])-10))
        forms.alert("\n".join(detail), title="Parameter Details")
    except Exception as e:
        forms.alert("Error: {}".format(str(e)))

# ------------------------------------------------------------
# 6. Main Menu
# ------------------------------------------------------------
def main():
    try:
        mgr = EnhancedParameterManager(doc)
        params = mgr.get_all_parameters()
        total = len(params) if params else 0
        used = sum(1 for p in params if p['is_used']) if params else 0
        unused = total - used
        
        choice = forms.alert(
            "📊 One Parameter Manager (No Output Console)\n\n"
            "Total: {} parameters\n"
            "Used: {} | Unused: {}\n\n"
            "Select action:".format(total, used, unused),
            options=[
                "📤 Export JSON",
                "📥 Import JSON",
                "🗑️ Delete Selected (Force)",
                "🧹 Delete Unused (Auto-detected)",
                "📊 Generate Report",
                "🔍 View Details",
                "❌ Exit"
            ],
            title="Parameter Manager"
        )
        if choice == "📤 Export JSON":
            export_parameters()
        elif choice == "📥 Import JSON":
            import_parameters()
        elif choice == "🗑️ Delete Selected (Force)":
            delete_selected_parameters()
        elif choice == "🧹 Delete Unused (Auto-detected)":
            cleanup_unused_parameters()
        elif choice == "📊 Generate Report":
            quick_parameter_report()
        elif choice == "🔍 View Details":
            view_parameter_details()
    except Exception as e:
        forms.alert("Main error: {}".format(str(e)))

if __name__ == '__main__':
    main()