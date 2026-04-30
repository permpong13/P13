# -*- coding: utf-8 -*-
import clr
import math
import os
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
# Thai Unit Conversion
# ---------------------------------------------------------
def convert_to_thai_units(area_sqm):
    rai = int(area_sqm // 1600)
    remainder = area_sqm % 1600
    ngan = int(remainder // 400)
    wa = (remainder % 400) / 4.0
    return rai, ngan, wa

# ---------------------------------------------------------
# Option 1: Pick Points (Shoelace Formula) + Orange Line
# ---------------------------------------------------------
def mode_pick_points():
    points = []
    prev_pt = None
    
    tg = DB.TransactionGroup(doc, "Temporary Guide Lines")
    tg.Start()
    
    try:
        while True:
            pt = uidoc.Selection.PickPoint("Click Point {} (Press ESC to calculate)".format(len(points) + 1))
            points.append(pt)
            
            if prev_pt and doc.ActiveView.ViewType != DB.ViewType.ThreeD:
                t = DB.Transaction(doc, "Draw Line")
                t.Start()
                try:
                    line = DB.Line.CreateBound(prev_pt, pt)
                    detail_curve = doc.Create.NewDetailCurve(doc.ActiveView, line)
                    
                    # ปรับแต่งเส้นไกด์ไลน์ให้เป็นสีส้มเข้มและหนาขึ้น
                    orange_color = DB.Color(255, 109, 0) # สีส้มเข้ม (Dark Orange)
                    ogs = DB.OverrideGraphicSettings()
                    ogs.SetProjectionLineColor(orange_color)
                    ogs.SetProjectionLineWeight(5) # ปรับความหนาของเส้น (1-16)
                    doc.ActiveView.SetElementOverrides(detail_curve.Id, ogs)
                    
                except:
                    pass
                t.Commit()
                uidoc.RefreshActiveView()
                
            prev_pt = pt
            
    except OperationCanceledException:
        pass
        
    tg.RollBack()

    if len(points) < 3:
        return 0.0

    area_sqft = 0.0
    for i in range(len(points)):
        j = (i + 1) % len(points)
        area_sqft += points[i].X * points[j].Y
        area_sqft -= points[j].X * points[i].Y
    
    return abs(area_sqft) / 2.0

# ---------------------------------------------------------
# Option 2: Select Pre-Drawn Element (Auto-Clean)
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
            "Select a Filled Region or pre-drawn area element (Press ESC to cancel)"
        )
        elem = doc.GetElement(ref)
    except OperationCanceledException:
        return 0.0

    area_param = elem.get_Parameter(DB.BuiltInParameter.HOST_AREA_COMPUTED)
    if not area_param:
        area_param = elem.get_Parameter(DB.BuiltInParameter.ROOM_AREA)
        
    if not area_param:
        forms.alert("Cannot retrieve area parameter from this element.", title="Warning")
        return 0.0
        
    area_sqft = area_param.AsDouble()
    
    t = DB.Transaction(doc, "Delete Temporary Area")
    t.Start()
    doc.Delete(elem.Id)
    t.Commit()
    
    return area_sqft

# ---------------------------------------------------------
# UI & Main Execution Logic
# ---------------------------------------------------------
class SmartAreaUI(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        
        self.CostInput.Text = getattr(my_config, "saved_cost", "0")
        self.CheckAccumulate.IsChecked = getattr(my_config, "saved_accumulate", False)
        
        self.BtnPickPoints.Click += self.BtnPickPoints_Click
        self.BtnSelectRegion.Click += self.BtnSelectRegion_Click
        
    def save_settings(self):
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
                    res = forms.alert("Accumulated: {} measurement(s)\nTotal Area: {:.2f} sq.m.\n\nDo you want to add another area?".format(
                        measurement_count, 
                        DB.UnitUtils.ConvertFromInternalUnits(total_area_sqft, DB.UnitTypeId.SquareMeters)), 
                        title="Accumulate Mode", options=["Continue", "Finish & Summarize"])
                    if res != "Continue":
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
        
        # Prepare text for Clipboard
        copy_text = "Temporary Area Summary:\n"
        copy_text += "Area (sq.m.): {:.2f}\n".format(area_sqm)
        if cost_per_sqm > 0:
            copy_text += "Estimated Cost: {:,.2f}\n".format(total_cost)
        copy_text += "หน่วยไทย: {} ไร่ - {} งาน - {:.2f} ตารางวา".format(rai, ngan, wa)
        
        # Print Output
        output = script.get_output()
        output.print_md("### 📐 Area Calculation Results")
        
        if count > 1:
            output.print_md("*Total area from {} measurements*".format(count)) 
            
        output.print_md("---")
        output.print_md("**• Square Meters:** {:.2f} sq.m.".format(area_sqm))
        output.print_md("**• Square Feet:** {:.2f} sq.ft.".format(area_sqft))
        
        if cost_per_sqm > 0:
            output.print_md("**💰 Estimated Cost (@ {:,.2f} /sq.m.):** {:,.2f}".format(cost_per_sqm, total_cost))
            
        # ใช้ HTML เพื่อขยายฟอนต์และเปลี่ยนสีให้แสดงผลภาษาไทยเด่นชัดที่สุด
        output.print_md('<br><span style="font-size: 22px; font-weight: bold; color: #FF6D00;">🇹🇭 หน่วยไทย: {} ไร่ - {} งาน - {:.2f} ตารางวา</span>'.format(rai, ngan, wa))
        
        output.print_md("---")
        
        # Save History
        history = getattr(my_config, "history_log", [])
        history.insert(0, "{:.2f} sq.m. | {:,.2f} Cost".format(area_sqm, total_cost))
        my_config.history_log = history[:5]
        script.save_config()
        
        output.print_md("**🕒 Recent Measurements (Last 5):**")
        for idx, h in enumerate(my_config.history_log):
            output.print_md("{}. {}".format(idx+1, h))
        
        if CLIPBOARD_READY:
            Clipboard.SetText(copy_text)
            output.print_md("*✅ Results automatically copied to clipboard!*")

    def BtnPickPoints_Click(self, sender, args):
        self.process_area(mode_pick_points)

    def BtnSelectRegion_Click(self, sender, args):
        self.process_area(mode_select_element)

if __name__ == '__main__':
    xaml_path = os.path.join(os.path.dirname(__file__), 'ui.xaml')
    if not os.path.exists(xaml_path):
        forms.alert("UI file not found!\n\nPlease ensure 'ui.xaml' is in the same directory as script.py.", title="Error")
    else:
        ui = SmartAreaUI('ui.xaml')
        ui.ShowDialog()