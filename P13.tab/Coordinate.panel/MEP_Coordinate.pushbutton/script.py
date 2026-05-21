# -*- coding: utf-8 -*-
"""MEP Coordinate — Dynamo runner + Model Verify (วิธีที่ 3)"""

import clr
import os
import System.Collections.Generic as SCG

clr.AddReference("DynamoRevitDS")
from Dynamo.Applications import DynamoRevit, DynamoRevitCommandData, JournalKeys

from pyrevit import revit, DB, script, forms

doc    = revit.doc
output = script.get_output()

output.print_md("# **MEP Coordinate — รัน Dynamo + ตรวจสอบผล**")

# =====================================================
# ขั้นตอน 1 : รัน Dynamo graph (silent / no UI)
# =====================================================
output.print_md("### ⏳ กำลังรัน Dynamo graph...")

dyn_path = os.path.join(os.path.dirname(__file__), "MEP_Coordinate.dyn")

if not os.path.exists(dyn_path):
    forms.alert("ไม่พบไฟล์ MEP_Coordinate.dyn\nตรวจสอบ path: {}".format(dyn_path), exitscript=True)

jd = SCG.Dictionary[str, str]()
jd[JournalKeys.ShowUiKey]         = "false"   # ไม่เปิด Dynamo UI
jd[JournalKeys.AutomationModeKey] = "true"    # รันอัตโนมัติ
jd[JournalKeys.DynPathKey]        = dyn_path
jd[JournalKeys.DynPathExecuteKey] = "true"
jd[JournalKeys.ForceManualRunKey] = "false"
jd[JournalKeys.ModelShutDownKey]  = "true"    # ปิด model หลังรัน

cmd_data             = DynamoRevitCommandData()
cmd_data.Application = __revit__
cmd_data.JournalData = jd

try:
    DynamoRevit().ExecuteCommand(cmd_data)
    output.print_md("✅ **Dynamo ExecuteCommand เสร็จสิ้น**")
except Exception as e:
    output.print_md("❌ **Dynamo ExecuteCommand ล้มเหลว:** `{}`".format(str(e)))
    forms.alert("Dynamo รันล้มเหลว:\n{}".format(str(e)))
    import sys; sys.exit()

output.print_md("---")

# =====================================================
# ขั้นตอน 2 : ตรวจสอบผลโดยตรงจาก Revit Model
# =====================================================
output.print_md("### 🔍 ตรวจสอบ N_Coordinate / E_Coordinate ในโมเดล")

# Categories ที่ Dynamo graph เขียนค่าให้
TARGET_CATS = {
    "Pipe Accessories" : DB.BuiltInCategory.OST_PipeAccessory,
    "Pipe Fittings"    : DB.BuiltInCategory.OST_PipeFitting,
}

grand_total   = 0
grand_ok      = 0
grand_missing = 0
grand_zero    = 0

for cat_name, cat_bic in TARGET_CATS.items():
    elements = (
        DB.FilteredElementCollector(doc)
          .OfCategory(cat_bic)
          .WhereElementIsNotElementType()
          .ToElements()
    )

    total     = len(elements)
    ok        = 0
    missing   = []
    zero_ids  = []

    for el in elements:
        p_n = el.LookupParameter("N_Coordinate")
        p_e = el.LookupParameter("E_Coordinate")

        if p_n and p_n.HasValue and p_e and p_e.HasValue:
            if p_n.AsDouble() != 0.0 or p_e.AsDouble() != 0.0:
                ok += 1
            else:
                zero_ids.append(el.Id.Value)
        else:
            missing.append(el.Id.Value)

    grand_total   += total
    grand_ok      += ok
    grand_missing += len(missing)
    grand_zero    += len(zero_ids)

    pct = int(ok * 100.0 / total) if total else 0
    output.print_md("#### {} ({} รายการ)".format(cat_name, total))
    output.print_md("✅ มีพิกัด: **{}** &nbsp;|&nbsp; ⚠️ ค่าเป็น 0: **{}** &nbsp;|&nbsp; ❌ ไม่มี Param: **{}** &nbsp;&nbsp;`{}%`".format(
        ok, len(zero_ids), len(missing), pct))

    if zero_ids:
        output.print_md("&nbsp;&nbsp;IDs ค่าเป็น 0: `{}`{}".format(
            ", ".join(str(i) for i in zero_ids[:10]),
            " …({}+ เพิ่มเติม)".format(len(zero_ids) - 10) if len(zero_ids) > 10 else ""
        ))
    if missing:
        output.print_md("&nbsp;&nbsp;IDs ไม่มี Param: `{}`{}".format(
            ", ".join(str(i) for i in missing[:10]),
            " …({}+ เพิ่มเติม)".format(len(missing) - 10) if len(missing) > 10 else ""
        ))

# =====================================================
# สรุปรวม
# =====================================================
output.print_md("---")
output.print_md("### 📊 สรุปรวมทุก Category")
output.print_md("| รายการ | จำนวน |")
output.print_md("|---|---|")
output.print_md("| ทั้งหมด | **{}** |".format(grand_total))
output.print_md("| ✅ มีพิกัดครบ | **{}** |".format(grand_ok))
output.print_md("| ⚠️ ค่าพิกัดเป็น 0 | **{}** |".format(grand_zero))
output.print_md("| ❌ ไม่มี Parameter | **{}** |".format(grand_missing))

if grand_missing > 0:
    output.print_md("\n🔴 **Shared Parameter ยังไม่ได้ถูกสร้าง — ตรวจสอบ Dynamo graph**")
elif grand_zero > 0:
    output.print_md("\n🟡 **Dynamo รันแล้ว แต่บางรายการได้ค่า 0 — อาจอยู่ที่ Origin หรือมี error ใน graph**")
elif grand_ok == grand_total and grand_total > 0:
    output.print_md("\n🟢 **Dynamo รันสำเร็จ — พิกัดครบทุกรายการ!**")
else:
    output.print_md("\n⚪ **ไม่พบ element ในโมเดล**")
