# -*- coding: utf-8 -*-
"""
Rotate Fitting Pro
หมุนข้อต่อด้วยหน้าต่างเลือกองศา (Naviate Style UI)
"""
import clr
import math
import os.path as op # เพิ่มตัวนี้เพื่อหาไฟล์ xaml
from Autodesk.Revit.DB import *
from pyrevit import revit, forms, script

# --- Main Logic ---
doc = revit.doc
uidoc = revit.uidoc

# ระบุที่อยู่ไฟล์ UI.xaml ที่เราเพิ่งสร้าง
xaml_file = op.join(op.dirname(__file__), 'UI.xaml')

def get_rotation_axis(element):
    """หาแกนหมุนจาก Connector ที่เชื่อมต่ออยู่"""
    try:
        mep_model = element.MEPModel
        if not mep_model: return None
        conns = list(mep_model.ConnectorManager.Connectors)
        
        connected = [c for c in conns if c.IsConnected]
        target_conn = None
        
        if connected:
            target_conn = connected[0]
        elif conns:
            target_conn = conns[0]
            
        if target_conn:
            origin = target_conn.Origin
            basis_z = target_conn.CoordinateSystem.BasisZ
            return Line.CreateBound(origin, origin + (basis_z * 10))
    except:
        return None
    return None

class RotateFittingWindow(forms.WPFWindow):
    def __init__(self):
        # โหลดหน้าต่างจากไฟล์ .xaml แทน string
        forms.WPFWindow.__init__(self, xaml_file)
        self.selected_angle = None

    def angle_click(self, sender, args):
        try:
            val = float(sender.Tag)
            self.selected_angle = val
            self.Close()
        except:
            pass

    def ok_click(self, sender, args):
        try:
            val = float(self.custom_angle_box.Text)
            self.selected_angle = val
            self.Close()
        except:
            forms.alert("กรุณาระบุตัวเลขที่ถูกต้อง")

    def cancel_click(self, sender, args):
        self.Close()

# --- Execution ---

selection = revit.get_selection()
fittings = []

for el in selection:
    # --- ส่วนที่แก้ไขเพื่อรองรับ Revit 2026 ---
    try:
        # พยายามใช้ .Value สำหรับ Revit 2024, 2025, 2026+
        cat_id = el.Category.Id.Value
    except AttributeError:
        # หากไม่พบ .Value (Revit 2023 ลงไป) ให้ใช้ .IntegerValue
        cat_id = el.Category.Id.IntegerValue
    # ----------------------------------------

    if cat_id in [
        int(BuiltInCategory.OST_PipeFitting), 
        int(BuiltInCategory.OST_DuctFitting),
        int(BuiltInCategory.OST_PipeAccessory),
        int(BuiltInCategory.OST_DuctAccessory),
        int(BuiltInCategory.OST_PlumbingFixtures),
        int(BuiltInCategory.OST_MechanicalEquipment)
    ]:
        fittings.append(el)

if not fittings:
    forms.alert("กรุณาเลือก Fitting, Accessory หรือ Equipment อย่างน้อย 1 ชิ้น")
    script.exit()

# เรียกใช้ Class โดยไม่ต้องส่ง string เข้าไป
win = RotateFittingWindow()
win.ShowDialog()

if win.selected_angle is not None:
    angle_rad = math.radians(win.selected_angle)
    
    t = Transaction(doc, "Rotate Fitting UI")
    t.Start()
    
    success = 0
    fail = 0
    
    for fit in fittings:
        axis = get_rotation_axis(fit)
        if axis:
            try:
                ElementTransformUtils.RotateElement(doc, fit.Id, axis, angle_rad)
                success += 1
            except Exception as e:
                fail += 1
        else:
            fail += 1
            
    t.Commit()