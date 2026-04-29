# -*- coding: utf-8 -*-
import clr
import math
from pyrevit import revit, UI, DB, forms, script
from Autodesk.Revit.Exceptions import OperationCanceledException

try:
    clr.AddReference("PresentationCore")
    from System.Windows import Clipboard
    CLIPBOARD_READY = True
except ImportError:
    CLIPBOARD_READY = False

uidoc = revit.uidoc
doc = revit.doc
my_config = script.get_config()

# ---------------------------------------------------------
# ฟังก์ชันคำนวณหน่วยพื้นที่ไทย
# ---------------------------------------------------------
def convert_to_thai_units(area_sqm):
    rai = int(area_sqm // 1600)
    remainder = area_sqm % 1600
    ngan = int(remainder // 400)
    wa = (remainder % 400) / 4.0
    return rai, ngan, wa

# ---------------------------------------------------------
# Option 1: คลิกจุดยอดมุม + วาดเส้นไกด์ไลน์ชั่วคราว
# ---------------------------------------------------------
def mode_pick_points():
    points = []
    prev_pt = None
    
    # เปิด TransactionGroup เพื่อเก็บเส้นที่วาดไว้ แล้วลบทิ้งทีเดียวตอนจบ
    tg = DB.TransactionGroup(doc, "Temporary Guide Lines")
    tg.Start()
    
    try:
        while True:
            pt = uidoc.Selection.PickPoint("คลิกจุดที่ {} (กด ESC เพื่อคำนวณ)".format(len(points) + 1))
            points.append(pt)
            
            # วาดเส้นไกด์ไลน์ชั่วคราวให้ผู้ใช้เห็น
            if prev_pt and doc.ActiveView.ViewType != DB.ViewType.ThreeD:
                t = DB.Transaction(doc, "Draw Line")
                t.Start()
                try:
                    line = DB.Line.CreateBound(prev_pt, pt)
                    doc.Create.NewDetailCurve(doc.ActiveView, line)
                except:
                    pass
                t.Commit()
                uidoc.RefreshActiveView()
                
            prev_pt = pt
            
    except OperationCanceledException:
        pass
        
    # RollBack เพื่อลบเส้นไกด์ไลน์ทั้งหมดทิ้ง (คืนสภาพโมเดล)
    tg.RollBack()

    if len(points) < 3:
        return 0.0

    # คำนวณ Shoelace
    area_sqft = 0.0
    for i in range(len(points)):
        j = (i + 1) % len(points)
        area_sqft += points[i].X * points[j].Y
        area_sqft -= points[j].X * points[i].Y
    
    return abs(area_sqft) / 2.0

# ---------------------------------------------------------
# Option 2: หาพื้นที่จากการเลือกชิ้นงาน แล้วลบทิ้ง
# ---------------------------------------------------------
class AreaElementFilter(UI.Selection.ISelectionFilter):
    def AllowElement(self, elem):
        param = elem.get_Parameter(DB.BuiltInParameter.HOST_AREA_COMPUTED)
        if not param:
            param = elem.get_Parameter(DB.BuiltInParameter.ROOM_AREA)
        return param is not None
    def AllowReference(self, reference, position):
        return False

def mode_select_element():
    try:
        sel_filter = AreaElementFilter()
        ref = uidoc.Selection.PickObject(
            UI.Selection.ObjectType.Element, 
            sel_filter, 
            "คลิกเลือก Filled Region หรือชิ้นงานที่วาดไว้ (กด ESC เพื่อยกเลิก)"
        )
        elem = doc.GetElement(ref)
    except OperationCanceledException:
        return 0.0

    area_param = elem.get_Parameter(DB.BuiltInParameter.HOST_AREA_COMPUTED)
    if not area_param:
        area_param = elem.get_Parameter(DB.BuiltInParameter.ROOM_AREA)
        
    if not area_param:
        forms.alert("ไม่สามารถดึงค่าพื้นที่จากชิ้นงานนี้ได้ครับ", title="แจ้งเตือน")
        return 0.0
        
    area_sqft = area_param.AsDouble()
    
    # ลบ Element ทิ้งเพื่อรักษาความสะอาดของโมเดล
    t = DB.Transaction(doc, "Delete Temporary Area")
    t.Start()
    doc.Delete(elem.Id)
    t.Commit()
    
    return area_sqft

# ---------------------------------------------------------
# UI และระบบประมวลผลหลัก
# ---------------------------------------------------------
class SmartAreaUI(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        # โหลดการตั้งค่าเดิมที่เคยบันทึกไว้
        self.CostInput.Text = getattr(my_config, "saved_cost", "0")
        self.CheckAccumulate.IsChecked = getattr(my_config, "saved_accumulate", False)
        
    def save_settings(self):
        # บันทึกการตั้งค่าเพื่อใช้ในครั้งต่อไป
        my_config.saved_cost = self.CostInput.Text
        my_config.saved_accumulate = self.CheckAccumulate.IsChecked
        script.save_config()

    def process_area(self, mode_function):
        self.save_settings()
        self.Hide()
        
        is_accumulate = self.CheckAccumulate.IsChecked
        cost_per_sqm = float(self.CostInput.Text) if self.CostInput.Text.replace('.','',1).isdigit() else 0.0
        
        total_area_sqft = 0.0
        measurement_count = 0
        
        while True:
            area = mode_function()
            if area and area > 0:
                total_area_sqft += area
                measurement_count += 1
                
                if not is_accumulate:
                    break
                else:
                    # ถามผู้ใช้ว่าจะวัดห้องต่อไปไหม
                    res = forms.alert("บวกพื้นที่ไปแล้ว {} ครั้ง\nรวม {:.2f} ตร.ม.\n\nต้องการจิ้มพื้นที่ส่วนต่อไปเพื่อบวกเพิ่มหรือไม่?".format(
                        measurement_count, 
                        DB.UnitUtils.ConvertFromInternalUnits(total_area_sqft, DB.UnitTypeId.SquareMeters)), 
                        title="โหมดสะสมพื้นที่", options=["วัดต่อ", "พอแล้ว สรุปผล"])
                    if res != "วัดต่อ":
                        break
            else:
                break
                
        if total_area_sqft > 0:
            self.display_and_copy_results(total_area_sqft, cost_per_sqm, measurement_count)
            
        self.Close()

    def display_and_copy_results(self, area_sqft, cost_per_sqm, count):
        area_sqm = DB.UnitUtils.ConvertFromInternalUnits(area_sqft, DB.UnitTypeId.SquareMeters)
        rai, ngan, wa = convert_to_thai_units(area_sqm)
        total_cost = area_sqm * cost_per_sqm
        
        # จัดเตรียม Text สำหรับ Copy
        copy_text = "สรุปพื้นที่ชั่วคราว:\n"
        copy_text += "พื้นที่ (ตร.ม.): {:.2f}\n".format(area_sqm)
        if cost_per_sqm > 0:
            copy_text += "ราคาประเมิน: {:,.2f} บาท\n".format(total_cost)
        copy_text += "พื้นที่ (หน่วยไทย): {} ไร่ - {} งาน - {:.2f} ตารางวา".format(rai, ngan, wa)
        
        # แสดงผลลัพธ์ลง Output (เป็น History Log ในตัว)
        output = script.get_output()
        output.print_md("### 📐 สรุปผลลัพธ์พื้นที่")
        if count > 1:
            output.print_md("*รวมพื้นที่จากการวัด {} ครั้ง*", count)
        output.print_md("---")
        output.print_md("**• ตารางเมตร:** {:.2f} ตร.ม.".format(area_sqm))
        output.print_md("**• ตารางฟุต:** {:.2f} sq.ft.".format(area_sqft))
        output.print_md("**• หน่วยไทย:** {} ไร่ - {} งาน - {:.2f} ตารางวา".format(rai, ngan, wa))
        
        if cost_per_sqm > 0:
            output.print_md("**💰 ราคาประเมิน ({:,.2f} บ./ตร.ม.):** {:,.2f} บาท".format(cost_per_sqm, total_cost))
            
        output.print_md("---")
        
        # บันทึกประวัติ
        history = getattr(my_config, "history_log", [])
        history.insert(0, "{:.2f} ตร.ม. | {:,.2f} บาท".format(area_sqm, total_cost))
        my_config.history_log = history[:5] # เก็บแค่ 5 รายการล่าสุด
        script.save_config()
        
        output.print_md("**🕒 ประวัติการวัด 5 ครั้งล่าสุด:**")
        for idx, h in enumerate(my_config.history_log):
            output.print_md("{}. {}".format(idx+1, h))
        
        if CLIPBOARD_READY:
            Clipboard.SetText(copy_text)
            output.print_md("*✅ คัดลอกค่าทั้งหมดลง Clipboard สำเร็จ!*")

    def BtnPickPoints_Click(self, sender, args):
        self.process_area(mode_pick_points)

    def BtnSelectRegion_Click(self, sender, args):
        self.process_area(mode_select_element)

if __name__ == '__main__':
    ui = SmartAreaUI('ui.xaml')
    ui.ShowDialog()