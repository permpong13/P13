# -*- coding: utf-8 -*-
"""
pyRevit - Ultimate Family Rescue Mode
"""
__title__ = "Family Rescue\nMode"
__author__ = "เพิ่มพงษ์"

import os
import clr
import codecs
import System
from datetime import datetime

from pyrevit import forms, script

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    Transaction,
    FilteredElementCollector,
    Family,
    IFamilyLoadOptions,
    FamilySource,
    IFailuresPreprocessor,
    FailureProcessingResult,
    FailureSeverity
)

doc = __revit__.ActiveUIDocument.Document
output = script.get_output()
config = script.get_config()

# =====================================================
# 1. จัดการ Export Path (สำหรับ Live Log)
# =====================================================
export_path = getattr(config, "export_path", "")
if not export_path or not os.path.exists(export_path):
    selected_export = forms.pick_folder(title="📁 [Setup] เลือกโฟลเดอร์เพื่อบันทึกไฟล์ Report")
    if selected_export:
        config.export_path = selected_export
        export_path = selected_export
        script.save_config()

# =====================================================
# 2. เลือกโฟลเดอร์ต้นฉบับ .rfa (Smart Memory)
# =====================================================
last_folder = getattr(config, "last_family_folder", "")
target_folder = ""

if last_folder and os.path.exists(last_folder):
    opt_use_last = "🔄 ใช้โฟลเดอร์เดิม: {}".format(last_folder)
    opt_new = "📁 เลือกโฟลเดอร์ใหม่"
    res = forms.CommandSwitchWindow.show([opt_use_last, opt_new], message="แหล่งที่มาของไฟล์ .rfa ที่สมบูรณ์")
    if res == opt_use_last: target_folder = last_folder
    elif res == opt_new: target_folder = forms.pick_folder(title="เลือกโฟลเดอร์ต้นฉบับ")
else:
    target_folder = forms.pick_folder(title="เลือกโฟลเดอร์ต้นฉบับ")

if not target_folder: script.exit()
config.last_family_folder = target_folder
script.save_config()

# =====================================================
# 3. เตรียมไฟล์ Live Log Report ทันที
# =====================================================
csv_file = ""
if export_path and os.path.exists(export_path):
    time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = os.path.join(export_path, "Rescue_LiveLog_{}.csv".format(time_str))
    with codecs.open(csv_file, 'w', encoding='utf-8-sig') as f:
        f.write("Time,Family Name,Status,Details\n")
    output.print_md("🔴 **[LIVE LOG ACTIVE]** ระบบจะบันทึกสถานะเรียลไทม์ไว้ที่: `{}`".format(csv_file))

# =====================================================
# 4. คลาสตัวช่วยโหลดแฟมิลีแบบข้าม Error แบบเงียบสนิท (Silent Mode)
# =====================================================
class WarningSwallower(IFailuresPreprocessor):
    def PreprocessFailures(self, failuresAccessor):
        # 4.1 ตรวจสอบว่ามี Elements สำคัญกำลังจะถูกลบหรือไม่
        deleted_ids = failuresAccessor.GetDeletedElementIds()
        doc_internal = failuresAccessor.GetDocument()
        
        if deleted_ids and deleted_ids.Count > 0:
            for d_id in deleted_ids:
                elem = doc_internal.GetElement(d_id)
                if elem:
                    cls_name = elem.GetType().Name
                    # ถ้าระบบแอบจะลบ Family หรือ FamilyInstance ให้สั่งยกเลิก(Rollback)ทันที
                    if cls_name == "Family" or cls_name == "FamilyInstance":
                        return FailureProcessingResult.ProceedWithRollBack

        # 4.2 จัดการกับหน้าต่างแจ้งเตือนและ Error แบบครอบจักรวาล
        fails = failuresAccessor.GetFailureMessages()
        has_fatal_error = False
        
        for f in fails:
            severity = f.GetSeverity()
            if severity == FailureSeverity.Warning:
                # ถ้าเป็นแค่คำเตือน ให้ลบทิ้งและโหลดต่อ
                failuresAccessor.DeleteWarning(f)
            else:
                # ถ้าเป็น Error ระดับร้ายแรง (รวมถึง Document Corruption / Unusable)
                # ให้ตั้งสถานะว่าเจอ Error เพื่อสั่ง Rollback ทีเดียว
                has_fatal_error = True
                
        if has_fatal_error:
            # สั่งให้ Revit ยกเลิกคำสั่งแบบอัตโนมัติ โดยไม่เด้งหน้าต่างใดๆ
            return FailureProcessingResult.ProceedWithRollBack
            
        return FailureProcessingResult.Continue

class FamLoadOpts(IFamilyLoadOptions):
    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        overwriteParameterValues.Value = True
        return True
    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        source.Value = FamilySource.Family
        overwriteParameterValues.Value = True
        return True

# =====================================================
# 5. ค้นหาไฟล์ .rfa (เลือกล่าสุดเสมอกรณีชื่อซ้ำ)
# =====================================================
rfa_files = {}
for root, dirs, files in os.walk(target_folder):
    for f in files:
        if f.lower().endswith(".rfa"):
            fam_name = os.path.splitext(f)[0]
            full_path = os.path.join(root, f)
            mod_time = os.path.getmtime(full_path)
            if fam_name not in rfa_files or mod_time > rfa_files[fam_name]['time']:
                rfa_files[fam_name] = {'path': full_path, 'time': mod_time}

if not rfa_files: forms.alert("❌ ไม่พบไฟล์ .rfa", exitscript=True)

# =====================================================
# 6. จับคู่กับในโมเดล (Blind Match)
# =====================================================
existing_fams = FilteredElementCollector(doc).OfClass(Family).ToElements()

class FamilyItem(forms.TemplateListItem):
    @property
    def name(self): return "📦 " + self.fam_name

matched_items = []
for fam in existing_fams:
    f_name = fam.Name
    if f_name in rfa_files:
        item = FamilyItem(f_name)
        item.fam_name = f_name
        item.path = rfa_files[f_name]['path']
        item.state = True 
        matched_items.append(item)

if not matched_items: forms.alert("ไม่พบชื่อแฟมิลีในโปรเจกต์ที่ตรงกับโฟลเดอร์ต้นฉบับเลย", exitscript=True)

# =====================================================
# 7. UI ให้ผู้ใช้ยืนยัน
# =====================================================
selected_fams = forms.SelectFromList.show(
    matched_items,
    multiselect=True,
    title="เลือกแฟมิลีที่ต้องการเขียนทับเพื่อกู้ชีพ",
    button_name="🚑 เริ่มกู้ไฟล์ (โหลดทับ)"
)

if not selected_fams: script.exit()

# =====================================================
# 8. กระบวนการกู้ภัย (ทีละ Transaction + Live Log)
# =====================================================
opts = FamLoadOpts()
loaded_count = 0
failed_count = 0
total_reload = len(selected_fams)

output.print_md("# 🚑 เริ่มต้นกระบวนการกู้ภัย (Rescue Mode)")

with forms.ProgressBar(title="Recovery in progress...", cancellable=True) as pb:
    for i, fam_name in enumerate(selected_fams, 1):
        if pb.cancelled: break
            
        pb.title = "Reloading: {}/{} ({}%)".format(i, total_reload, int(i/total_reload*100))
        pb.update_progress(i, total_reload)
        output.print_md("\n### กำลังกู้คืน: **{}**".format(fam_name))
        
        # เริ่ม Transaction ย่อย
        t = Transaction(doc, "Rescue: " + fam_name)
        t.Start()
        
        # ⭐️ ยกระดับการป้องกัน UI เด้ง ⭐️
        fho = t.GetFailureHandlingOptions()
        fho.SetFailuresPreprocessor(WarningSwallower())
        fho.SetClearAfterRollback(True) # ล้างแจ้งเตือนหลังจาก Rollback ทันที เพื่อความชัวร์
        t.SetFailureHandlingOptions(fho)
        
        status = ""
        msg = ""
        try:
            fam_ref = clr.Reference[Family]()
            fam_path = rfa_files[fam_name]['path']
            ok = doc.LoadFamily(fam_path, opts, fam_ref)
            
            if ok:
                loaded_count += 1
                status = "Success"
                msg = "โหลดทับสำเร็จ"
                output.print_md("- ✅ โหลดทับสำเร็จ")
                t.Commit()
            else:
                failed_count += 1
                status = "Failed"
                msg = "Revit ยกเลิกการโหลด (ปกป้องไฟล์ไม่ให้ถูกลบ/เสียหาย)"
                output.print_md("- ❌ ล้มเหลว (ข้ามไฟล์นี้เพื่อป้องกันความเสียหายแบบเงียบๆ)")
                t.RollBack()
                
        except Exception as ex:
            failed_count += 1
            status = "Error"
            msg = str(ex).replace('\n', ' ').replace(',', ';') 
            output.print_md("- ❌ ติด Error ร้ายแรง: `{}`".format(msg))
            t.RollBack()
            
        # LIVE LOG UPDATE 
        if csv_file:
            try:
                with codecs.open(csv_file, 'a', encoding='utf-8-sig') as f:
                    now = datetime.now().strftime("%H:%M:%S")
                    f.write("{},{},{},\"{}\"\n".format(now, fam_name, status, msg))
            except: pass
            
        # บังคับเคลียร์ RAM
        System.GC.Collect()
        System.GC.WaitForPendingFinalizers()

# =====================================================
# 9. สรุปผล
# =====================================================
output.print_md("\n---")
output.print_md("# 📊 สรุปผลการกู้ชีพ")
output.print_md("- 🟢 กู้คืนสำเร็จ: **{}**".format(loaded_count))
output.print_md("- 🔴 ข้ามไฟล์ที่มีปัญหา (ป้องกันไว้ได้): **{}**".format(failed_count))
if csv_file:
    output.print_md("- 📁 ตรวจสอบประวัติแบบละเอียดได้ที่: `{}`".format(csv_file))