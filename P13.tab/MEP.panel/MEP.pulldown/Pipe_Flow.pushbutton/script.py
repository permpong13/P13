# -*- coding: utf-8 -*-
__title__ = "Pipes Flow\nDirections"
__author__ = "Tee_เพิ่มพงษ์"
__doc__ = "สร้างลูกศรแสดงทิศทางการไหลบนท่อทั้งหมดในมุมมองที่ใช้งานอยู่ โดยสามารถเลือก Family ที่ใช้แสดงลูกศรได้ และให้ทิศทางการไหลอ้างอิงจากความลาดเอียง (Slope) ของท่อ"

import clr
import sys
import math
import os

# Revit API References
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Plumbing import Pipe
from System.Windows.Forms import *
from System.Drawing import *

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

# -----------------------------
# Helper Functions
# -----------------------------

def meters_to_feet(m):
    return m * 3.28084

def get_all_detail_family_symbols(doc):
    """ดึง Family Symbols ทั้งหมดที่เป็น Detail Items หรือ Annotation"""
    all_symbols_info = []
    
    try:
        collector = FilteredElementCollector(doc).OfClass(FamilySymbol)
        
        for symbol in collector:
            try:
                if symbol.Category is None:
                    continue
                    
                category_name = ""
                try:
                    category_name = symbol.Category.Name
                except:
                    continue
                
                # รับเฉพาะ Detail Items และ Annotation
                valid_categories = ['detail', 'annotation', 'symbol', 'mark', 'generic']
                if any(keyword in category_name.lower() for keyword in valid_categories):
                    class SymbolInfo:
                        def __init__(self, symbol, family_name, symbol_name, category_name):
                            self.symbol = symbol
                            self.family_name = family_name
                            self.symbol_name = symbol_name
                            self.category_name = category_name
                    
                    family_name = "Unknown"
                    try:
                        if symbol.Family:
                            family_name = symbol.Family.Name
                    except:
                        pass
                    
                    symbol_name = "Unknown"
                    try:
                        symbol_name = symbol.Name
                    except:
                        pass
                    
                    symbol_info = SymbolInfo(
                        symbol=symbol,
                        family_name=family_name,
                        symbol_name=symbol_name,
                        category_name=category_name
                    )
                    all_symbols_info.append(symbol_info)
                    
            except Exception:
                continue
        
        # ตรวจสอบจาก Family ด้วย
        family_collector = FilteredElementCollector(doc).OfClass(Family)
        
        for family in family_collector:
            try:
                if family.FamilyCategory is None:
                    continue
                    
                category_name = ""
                try:
                    category_name = family.FamilyCategory.Name
                except:
                    continue
                
                valid_categories = ['detail', 'annotation', 'symbol', 'mark', 'generic']
                if any(keyword in category_name.lower() for keyword in valid_categories):
                    symbol_ids = family.GetFamilySymbolIds()
                    
                    for symbol_id in symbol_ids:
                        symbol = doc.GetElement(symbol_id)
                        if symbol is not None:
                            symbol_exists = False
                            for existing_symbol in all_symbols_info:
                                if existing_symbol.symbol.Id == symbol.Id:
                                    symbol_exists = True
                                    break
                            
                            if not symbol_exists:
                                class SymbolInfo:
                                    def __init__(self, symbol, family_name, symbol_name, category_name):
                                        self.symbol = symbol
                                        self.family_name = family_name
                                        self.symbol_name = symbol_name
                                        self.category_name = category_name
                                
                                family_name = "Unknown"
                                try:
                                    family_name = family.Name
                                except:
                                    pass
                                
                                symbol_name = "Unknown"
                                try:
                                    symbol_name = symbol.Name
                                except:
                                    pass
                                
                                symbol_info = SymbolInfo(
                                    symbol=symbol,
                                    family_name=family_name,
                                    symbol_name=symbol_name,
                                    category_name=category_name
                                )
                                all_symbols_info.append(symbol_info)
                            
            except Exception:
                continue
        
        # กรองเฉพาะ Symbols ที่สามารถใช้งานได้
        valid_symbols = []
        for symbol_info in all_symbols_info:
            try:
                if (symbol_info.symbol.Family is not None and 
                    symbol_info.symbol.Category is not None):
                    valid_symbols.append(symbol_info)
            except:
                continue
        
        # เรียงลำดับตามชื่อ Family และชื่อ Type
        valid_symbols.sort(key=lambda x: (x.family_name, x.symbol_name))
        
        return valid_symbols
                
    except Exception as e:
        return []

def get_pipe_slope_info(pipe):
    """
    ตรวจสอบข้อมูล Slope ของท่อ
    คืนค่า: (slope_value, slope_direction)
    """
    try:
        # พารามิเตอร์ Slope
        slope_param = pipe.LookupParameter("Slope")
        
        # พารามิเตอร์ Slope Direction
        slope_direction_param = pipe.LookupParameter("Slope Direction")
        
        slope_value = 0.0
        slope_direction = -1
        
        if slope_param and slope_param.StorageType == StorageType.Double:
            slope_value = slope_param.AsDouble()
        
        if slope_direction_param and slope_direction_param.StorageType == StorageType.Integer:
            slope_direction = slope_direction_param.AsInteger()
        
        return slope_value, slope_direction
        
    except Exception:
        return 0.0, -1

def get_pipe_geometry_direction(pipe, curve):
    """
    ตรวจสอบทิศทางของท่อจาก geometry โดยดูจากจุดเริ่มต้นและสิ้นสุด
    """
    try:
        start_point = curve.GetEndPoint(0)
        end_point = curve.GetEndPoint(1)
        
        # คำนวณเวกเตอร์ทิศทาง
        direction_vector = (end_point - start_point).Normalize()
        
        return direction_vector, start_point, end_point
    except Exception:
        return XYZ(1, 0, 0), None, None

def get_flow_direction_from_connections(pipe, curve):
    """
    ตรวจสอบทิศทางการไหลจากการเชื่อมต่อกับ fittings พิเศษ
    """
    try:
        # ตรวจสอบ Connectors ของท่อ
        connectors = pipe.ConnectorManager.Connectors
        
        for connector in connectors:
            # ตรวจสอบว่าเชื่อมต่อกับอะไรบ้าง
            all_refs = connector.AllRefs
            
            for ref in all_refs:
                if ref.Owner.Id != pipe.Id:  # ไม่ใช่ตัวท่อเอง
                    connected_element = ref.Owner
                    
                    # ตรวจสอบประเภทขององค์ประกอบที่เชื่อมต่อ
                    if connected_element.Category is not None:
                        category_name = connected_element.Category.Name.lower()
                        
                        # ถ้าเชื่อมต่อกับปั๊ม, วาล์ว, หรืออุปกรณ์พิเศษ
                        if any(keyword in category_name for keyword in ['pump', 'valve', 'equipment']):
                            # ตรวจสอบพารามิเตอร์ Flow Direction ถ้ามี
                            flow_dir_param = connected_element.LookupParameter("Flow Direction")
                            if flow_dir_param and flow_dir_param.HasValue:
                                flow_dir = flow_dir_param.AsString()
                                if "in" in flow_dir.lower():
                                    return XYZ.BasisX, "เชื่อมต่อกับ " + category_name + " (ไหลเข้า)"
                                elif "out" in flow_dir.lower():
                                    return XYZ.BasisX.Negate(), "เชื่อมต่อกับ " + category_name + " (ไหลออก)"
        
        return None, "ไม่พบข้อมูลการเชื่อมต่อ"
    except Exception:
        return None, "ข้อผิดพลาดในการตรวจสอบการเชื่อมต่อ"

def get_flow_direction_from_system(pipe):
    """
    ตรวจสอบทิศทางการไหลจากระบบท่อ
    """
    try:
        # ตรวจสอบระบบท่อ
        system = pipe.MEPSystem
        if system is not None:
            system_type = system.GetType().Name.lower()
            system_name = system.Name.lower() if system.Name else ""
            
            # วิเคราะห์จากชื่อระบบและประเภท
            if any(keyword in system_type or keyword in system_name 
                   for keyword in ['supply', 'hot', 'cold', 'domestic', 'feed']):
                return "SUPPLY", "ระบบ " + system_name + " (Supply)"
            elif any(keyword in system_type or keyword in system_name 
                     for keyword in ['return', 'waste', 'drain', 'vent']):
                return "RETURN", "ระบบ " + system_name + " (Return)"
        
        return None, "ไม่พบข้อมูลระบบ"
    except Exception:
        return None, "ข้อผิดพลาดในการตรวจสอบระบบ"

def analyze_neighbor_pipes(pipe, all_pipes):
    """
    วิเคราะห์ทิศทางการไหลจากท่อข้างเคียง
    """
    try:
        pipe_location = pipe.Location
        if not hasattr(pipe_location, 'Curve'):
            return None
        
        current_curve = pipe_location.Curve
        current_start = current_curve.GetEndPoint(0)
        current_end = current_curve.GetEndPoint(1)
        
        # หาท่อที่เชื่อมต่อกัน
        connected_pipes = []
        for other_pipe in all_pipes:
            if other_pipe.Id == pipe.Id:
                continue
            
            other_location = other_pipe.Location
            if not hasattr(other_location, 'Curve'):
                continue
            
            other_curve = other_location.Curve
            other_start = other_curve.GetEndPoint(0)
            other_end = other_curve.GetEndPoint(1)
            
            # ตรวจสอบว่าท่อเชื่อมต่อกันหรือไม่
            if (current_start.DistanceTo(other_start) < 0.1 or 
                current_start.DistanceTo(other_end) < 0.1 or
                current_end.DistanceTo(other_start) < 0.1 or
                current_end.DistanceTo(other_end) < 0.1):
                connected_pipes.append(other_pipe)
        
        # วิเคราะห์ทิศทางจากท่อที่เชื่อมต่อ
        if connected_pipes:
            # ในที่นี้ใช้การวิเคราะห์อย่างง่าย - สามารถพัฒนาต่อได้
            return "วิเคราะห์จากท่อข้างเคียง"
        
        return None
        
    except Exception:
        return None

def smart_flow_direction_detection(pipe, curve, all_pipes_in_view):
    """
    ใช้ rule-based system ในการวิเคราะห์ทิศทางการไหลอย่างชาญฉลาด
    """
    try:
        rules = []
        
        # Rule 1: ตรวจสอบ Slope (วิธีเดิมแต่ปรับปรุง)
        slope_value, slope_direction = get_pipe_slope_info(pipe)
        if abs(slope_value) > 0.001 and slope_direction in [0, 1]:
            if slope_direction == 0:
                rules.append(("SLOPE", 0.9, "เริ่มต้น → สิ้นสุด"))
            else:
                rules.append(("SLOPE", 0.9, "สิ้นสุด → เริ่มต้น"))
        
        # Rule 2: ตรวจสอบระดับความสูง
        start_point = curve.GetEndPoint(0)
        end_point = curve.GetEndPoint(1)
        elevation_diff = end_point.Z - start_point.Z
        
        if abs(elevation_diff) > 0.1:  # ต่างกันมากกว่า 0.1 ฟุต
            if elevation_diff < 0:
                rules.append(("ELEVATION", 0.8, "เริ่มต้น → สิ้นสุด"))
            else:
                rules.append(("ELEVATION", 0.8, "สิ้นสุด → เริ่มต้น"))
        
        # Rule 3: ตรวจสอบการเชื่อมต่อกับ fittings พิเศษ
        connector_direction, connector_info = get_flow_direction_from_connections(pipe, curve)
        if connector_direction:
            rules.append(("CONNECTION", 0.7, connector_info))
        
        # Rule 4: ตรวจสอบระบบท่อ
        system_direction, system_info = get_flow_direction_from_system(pipe)
        if system_direction:
            if system_direction == "SUPPLY":
                rules.append(("SYSTEM", 0.6, "เริ่มต้น → สิ้นสุด"))
            elif system_direction == "RETURN":
                rules.append(("SYSTEM", 0.6, "สิ้นสุด → เริ่มต้น"))
        
        # Rule 5: วิเคราะห์จากท่อข้างเคียง
        neighbor_direction = analyze_neighbor_pipes(pipe, all_pipes_in_view)
        if neighbor_direction:
            rules.append(("NEIGHBOR", 0.5, neighbor_direction))
        
        # คำนวณทิศทางสุดท้ายโดยใช้ weighted voting
        if rules:
            start_to_end_score = 0
            end_to_start_score = 0
            
            for rule_type, weight, direction in rules:
                if "เริ่มต้น → สิ้นสุด" in direction:
                    start_to_end_score += weight
                elif "สิ้นสุด → เริ่มต้น" in direction:
                    end_to_start_score += weight
            
            if start_to_end_score > end_to_start_score:
                final_direction = (end_point - start_point).Normalize()
                confidence = start_to_end_score / (start_to_end_score + end_to_start_score)
                confidence_percent = "{:.1%}".format(confidence)
                return final_direction, "SMART (เริ่มต้น → สิ้นสุด, ความมั่นใจ: " + confidence_percent + ")"
            else:
                final_direction = (start_point - end_point).Normalize()
                confidence = end_to_start_score / (start_to_end_score + end_to_start_score)
                confidence_percent = "{:.1%}".format(confidence)
                return final_direction, "SMART (สิ้นสุด → เริ่มต้น, ความมั่นใจ: " + confidence_percent + ")"
        
        # หากไม่มี rule ใดๆ ใช้ geometry direction
        geometry_direction = (end_point - start_point).Normalize()
        return geometry_direction, "SMART (ใช้ geometry, ไม่มีข้อมูลเพียงพอ)"
        
    except Exception as e:
        geometry_direction = (curve.GetEndPoint(1) - curve.GetEndPoint(0)).Normalize()
        return geometry_direction, "SMART (ข้อผิดพลาด: " + str(e) + ")"

def calculate_correct_flow_direction(pipe, curve, all_pipes_in_view=None):
    """
    คำนวณทิศทางการไหลที่ถูกต้อง (ใช้ SMART detection ถ้ามีข้อมูลท่อทั้งหมด)
    """
    try:
        if all_pipes_in_view is not None:
            # ใช้ SMART detection
            return smart_flow_direction_detection(pipe, curve, all_pipes_in_view)
        else:
            # ใช้วิธีเดิม
            slope_value, slope_direction = get_pipe_slope_info(pipe)
            geometry_direction, start_point, end_point = get_pipe_geometry_direction(pipe, curve)
            
            has_valid_slope = (abs(slope_value) > 0.0001 and slope_direction in [0, 1])
            
            if has_valid_slope:
                if slope_direction == 0:
                    return geometry_direction, "SLOPE (เริ่มต้น → สิ้นสุด)", slope_value, slope_direction
                elif slope_direction == 1:
                    return geometry_direction.Negate(), "SLOPE (สิ้นสุด → เริ่มต้น)", slope_value, slope_direction
            else:
                return geometry_direction, "ไม่มี SLOPE (ใช้ทิศทาง geometry)", slope_value, slope_direction
                
    except Exception:
        try:
            geometry_direction, _, _ = get_pipe_geometry_direction(pipe, curve)
            return geometry_direction, "ข้อผิดพลาด (ใช้ทิศทาง geometry)", 0.0, -1
        except:
            return XYZ(1, 0, 0), "ข้อผิดพลาด (ใช้ทิศทางเริ่มต้น)", 0.0, -1

class PipeFlowArrowForm(Form):
    def __init__(self, families_data):
        self.families_data = families_data
        self.selected_family_symbol = None
        self.spacing_meters = 5.0
        self.use_smart_detection = True  # ใช้ SMART detection โดยค่าเริ่มต้น
        self.InitializeComponent()
    
    def InitializeComponent(self):
        self.Text = "Pipe Flow Arrows - เลือก Family และระยะห่าง"
        self.Size = Size(500, 450)
        self.StartPosition = FormStartPosition.CenterScreen
        self.Font = Font("Microsoft Sans Serif", 9)
        
        # Label สำหรับเลือก Family
        self.lbl_family = Label()
        self.lbl_family.Text = "เลือก Family ลูกศร:"
        self.lbl_family.Location = Point(20, 20)
        self.lbl_family.Size = Size(150, 20)
        self.Controls.Add(self.lbl_family)
        
        # ComboBox สำหรับเลือก Family
        self.cb_family = ComboBox()
        self.cb_family.Location = Point(180, 20)
        self.cb_family.Size = Size(280, 20)
        self.cb_family.DropDownStyle = ComboBoxStyle.DropDownList
        self.cb_family.SelectedIndexChanged += self.on_family_selected
        self.Controls.Add(self.cb_family)
        
        # Label สำหรับเลือก Type
        self.lbl_type = Label()
        self.lbl_type.Text = "เลือก Type:"
        self.lbl_type.Location = Point(20, 60)
        self.lbl_type.Size = Size(150, 20)
        self.Controls.Add(self.lbl_type)
        
        # ComboBox สำหรับเลือก Type
        self.cb_type = ComboBox()
        self.cb_type.Location = Point(180, 60)
        self.cb_type.Size = Size(280, 20)
        self.cb_type.DropDownStyle = ComboBoxStyle.DropDownList
        self.cb_type.SelectedIndexChanged += self.on_type_selected
        self.Controls.Add(self.cb_type)
        
        # Checkbox สำหรับใช้ SMART detection
        self.cb_smart = CheckBox()
        self.cb_smart.Text = "ใช้ SMART Flow Detection (Rule-Based AI)"
        self.cb_smart.Location = Point(20, 100)
        self.cb_smart.Size = Size(300, 20)
        self.cb_smart.Checked = True
        self.cb_smart.CheckedChanged += self.on_smart_changed
        self.Controls.Add(self.cb_smart)
        
        # Label สำหรับระยะห่าง
        self.lbl_spacing = Label()
        self.lbl_spacing.Text = "ระยะห่างระหว่างลูกศร (เมตร):"
        self.lbl_spacing.Location = Point(20, 130)
        self.lbl_spacing.Size = Size(200, 20)
        self.Controls.Add(self.lbl_spacing)
        
        # TextBox สำหรับป้อนระยะห่าง
        self.txt_spacing = TextBox()
        self.txt_spacing.Text = "5.0"
        self.txt_spacing.Location = Point(220, 130)
        self.txt_spacing.Size = Size(100, 20)
        self.txt_spacing.TextChanged += self.on_spacing_changed
        self.Controls.Add(self.txt_spacing)
        
        # Radio buttons สำหรับระยะห่างที่ใช้บ่อย
        self.radio_5m = RadioButton()
        self.radio_5m.Text = "5 เมตร"
        self.radio_5m.Location = Point(20, 160)
        self.radio_5m.Size = Size(80, 20)
        self.radio_5m.Checked = True
        self.radio_5m.CheckedChanged += self.on_radio_5m_changed
        self.Controls.Add(self.radio_5m)
        
        self.radio_10m = RadioButton()
        self.radio_10m.Text = "10 เมตร"
        self.radio_10m.Location = Point(110, 160)
        self.radio_10m.Size = Size(80, 20)
        self.radio_10m.CheckedChanged += self.on_radio_10m_changed
        self.Controls.Add(self.radio_10m)
        
        self.radio_custom = RadioButton()
        self.radio_custom.Text = "กำหนดเอง"
        self.radio_custom.Location = Point(200, 160)
        self.radio_custom.Size = Size(100, 20)
        self.radio_custom.CheckedChanged += self.on_radio_custom_changed
        self.Controls.Add(self.radio_custom)
        
        # Label แสดงข้อมูล Family
        self.lbl_info = Label()
        self.lbl_info.Text = "ข้อมูล Family:"
        self.lbl_info.Location = Point(20, 190)
        self.lbl_info.Size = Size(440, 150)
        self.lbl_info.BorderStyle = BorderStyle.FixedSingle
        self.Controls.Add(self.lbl_info)
        
        # ปุ่มตกลง
        self.btn_ok = Button()
        self.btn_ok.Text = "ตกลง"
        self.btn_ok.Location = Point(300, 350)
        self.btn_ok.Size = Size(80, 30)
        self.btn_ok.Click += self.on_ok_click
        self.Controls.Add(self.btn_ok)
        
        # ปุ่มยกเลิก
        self.btn_cancel = Button()
        self.btn_cancel.Text = "ยกเลิก"
        self.btn_cancel.Location = Point(390, 350)
        self.btn_cancel.Size = Size(80, 30)
        self.btn_cancel.Click += self.on_cancel_click
        self.Controls.Add(self.btn_cancel)
        
        self.load_families()
    
    def load_families(self):
        """โหลดรายการ Family ลงใน ComboBox"""
        try:
            family_names = []
            for symbol_info in self.families_data:
                family_name = symbol_info.family_name
                if family_name and family_name not in family_names:
                    family_names.append(family_name)
            
            family_names.sort()
            
            for name in family_names:
                self.cb_family.Items.Add(name)
            
            if self.cb_family.Items.Count > 0:
                self.cb_family.SelectedIndex = 0
                
        except Exception:
            pass
    
    def on_family_selected(self, sender, event):
        """เมื่อเลือก Family ให้โหลด Type ที่เกี่ยวข้อง"""
        try:
            if self.cb_family.SelectedIndex < 0:
                return
            
            selected_family = self.cb_family.SelectedItem.ToString()
            self.cb_type.Items.Clear()
            
            # รวบรวม Type ทั้งหมดของ Family ที่เลือก
            type_list = []
            for symbol_info in self.families_data:
                if symbol_info.family_name == selected_family:
                    type_list.append(symbol_info)
            
            # เรียงลำดับ Type ตามชื่อ
            type_list.sort(key=lambda x: x.symbol_name)
            
            for symbol_info in type_list:
                display_name = symbol_info.symbol_name
                self.cb_type.Items.Add((display_name, symbol_info))
            
            if self.cb_type.Items.Count > 0:
                self.cb_type.SelectedIndex = 0
                
            self.update_info()
            
        except Exception:
            pass
    
    def on_type_selected(self, sender, event):
        """เมื่อเลือก Type ให้อัพเดทข้อมูล"""
        self.update_info()
    
    def on_smart_changed(self, sender, event):
        """เมื่อเปลี่ยนการตั้งค่า SMART detection"""
        self.use_smart_detection = self.cb_smart.Checked
        self.update_info()
    
    def on_spacing_changed(self, sender, event):
        """เมื่อแก้ไขระยะห่าง"""
        try:
            self.spacing_meters = float(self.txt_spacing.Text)
            self.radio_custom.Checked = True
        except:
            pass
    
    def on_radio_5m_changed(self, sender, event):
        if self.radio_5m.Checked:
            self.txt_spacing.Text = "5.0"
            self.spacing_meters = 5.0
    
    def on_radio_10m_changed(self, sender, event):
        if self.radio_10m.Checked:
            self.txt_spacing.Text = "10.0"
            self.spacing_meters = 10.0
    
    def on_radio_custom_changed(self, sender, event):
        if self.radio_custom.Checked:
            try:
                self.spacing_meters = float(self.txt_spacing.Text)
            except:
                self.spacing_meters = 5.0
    
    def update_info(self):
        """อัพเดทข้อมูล Family ที่เลือก"""
        try:
            if (self.cb_family.SelectedIndex >= 0 and 
                self.cb_type.SelectedIndex >= 0):
                
                family_name = self.cb_family.SelectedItem.ToString()
                display_name, symbol_info = self.cb_type.SelectedItem
                
                detection_method = "SMART Rule-Based AI" if self.use_smart_detection else "แบบเดิม (Slope + Geometry)"
                
                info_text = "Family: {}\nType: {}\nCategory: {}\n\nระยะห่าง: {} เมตร\nวิธีการตรวจจับ: {}\n\nหมายเหตุ:\n- SMART Detection ใช้ Rule-Based AI\n- วิเคราะห์จาก Slope, Elevation, Connection, System, Neighbor\n- คำนวณความมั่นใจของทิศทาง".format(
                    family_name,
                    symbol_info.symbol_name,
                    symbol_info.category_name,
                    self.spacing_meters,
                    detection_method
                )
                self.lbl_info.Text = info_text
                
        except Exception:
            pass
    
    def on_ok_click(self, sender, event):
        """เมื่อกดปุ่มตกลง"""
        try:
            if (self.cb_family.SelectedIndex < 0 or 
                self.cb_type.SelectedIndex < 0):
                MessageBox.Show("กรุณาเลือก Family และ Type", "ข้อผิดพลาด")
                return
            
            try:
                self.spacing_meters = float(self.txt_spacing.Text)
                if self.spacing_meters <= 0:
                    MessageBox.Show("กรุณาป้อนระยะห่างที่มากกว่า 0", "ข้อผิดพลาด")
                    return
            except:
                MessageBox.Show("กรุณาป้อนตัวเลขที่ถูกต้องสำหรับระยะห่าง", "ข้อผิดพลาด")
                return
            
            display_name, symbol_info = self.cb_type.SelectedItem
            self.selected_family_symbol = symbol_info.symbol
            self.use_smart_detection = self.cb_smart.Checked
            self.DialogResult = DialogResult.OK
            self.Close()
            
        except Exception as e:
            MessageBox.Show("เกิดข้อผิดพลาด: " + str(e), "ข้อผิดพลาด")
    
    def on_cancel_click(self, sender, event):
        """เมื่อกดปุ่มยกเลิก"""
        self.DialogResult = DialogResult.Cancel
        self.Close()

def place_arrow(doc, point, direction, symbol, view):
    """วางลูกศรและหมุนตามทิศทาง"""
    try:
        inst = doc.Create.NewFamilyInstance(point, symbol, view)
        angle = math.atan2(direction.Y, direction.X)
        axis = Line.CreateBound(point, point + XYZ.BasisZ)
        ElementTransformUtils.RotateElement(doc, inst.Id, axis, angle)
        return True
    except Exception:
        return False

# -----------------------------
# Main Function
# -----------------------------
def create_pipe_flow_arrows():
    from Autodesk.Revit.UI import TaskDialog
    
    try:
        view = doc.ActiveView
        if view.ViewType != ViewType.FloorPlan:
            TaskDialog.Show("Error", "Please open a Plan View before running this script.")
            return

        pipes = FilteredElementCollector(doc, view.Id).OfClass(Pipe).ToElements()
        if not pipes:
            TaskDialog.Show("Error", "No pipes found in the active view.")
            return

        # ดึงรายการ Family Symbols
        all_symbols_info = get_all_detail_family_symbols(doc)
        if not all_symbols_info:
            TaskDialog.Show("Error", "No Detail Item or Annotation Families found in project.")
            return

        # แสดงฟอร์มให้ผู้ใช้เลือก Family และระยะห่าง
        form = PipeFlowArrowForm(all_symbols_info)
        result = form.ShowDialog()
        
        if result != DialogResult.OK or not form.selected_family_symbol:
            return
        
        selected_symbol = form.selected_family_symbol
        spacing_meters = form.spacing_meters
        use_smart_detection = form.use_smart_detection
        spacing_feet = meters_to_feet(spacing_meters)

        # Activate symbol (separate transaction)
        if not selected_symbol.IsActive:
            t_act = Transaction(doc, "Activate Symbol")
            t_act.Start()
            selected_symbol.Activate()
            t_act.Commit()

        # === Main Transaction for placing arrows ===
        t = Transaction(doc, "Create Pipe Flow Arrows")
        t.Start()

        arrow_count = 0
        processed = 0
        smart_based_count = 0
        slope_based_count = 0
        geometry_based_count = 0
        confidence_scores = []

        for pipe in pipes:
            processed += 1
            loc = pipe.Location
            if not hasattr(loc, 'Curve'):
                continue

            curve = loc.Curve
            length = curve.Length
            if length < 0.1:
                continue

            # คำนวณทิศทางการไหล
            if use_smart_detection:
                # ใช้ SMART detection
                direction, direction_source = calculate_correct_flow_direction(pipe, curve, pipes)
                
                # ตรวจสอบความมั่นใจจาก direction_source
                if "ความมั่นใจ:" in direction_source:
                    try:
                        confidence_str = direction_source.split("ความมั่นใจ: ")[1].split("%")[0]
                        confidence_scores.append(float(confidence_str) / 100)
                    except:
                        confidence_scores.append(0.5)
                
                # นับสถิติ
                if "SMART" in direction_source:
                    smart_based_count += 1
                elif "SLOPE" in direction_source:
                    slope_based_count += 1
                else:
                    geometry_based_count += 1
                    
            else:
                # ใช้วิธีเดิม
                direction, direction_source, slope_value, slope_direction = calculate_correct_flow_direction(pipe, curve)
                
                # นับสถิติ
                if "SLOPE" in direction_source:
                    slope_based_count += 1
                else:
                    geometry_based_count += 1

            # Arrow placement
            if length < spacing_feet:
                distances = [length / 2.0]
            else:
                num_arrows = max(1, int(math.floor(length / spacing_feet)))
                distances = [(i + 1) * spacing_feet for i in range(num_arrows)]

            for dist in distances:
                if dist >= length:
                    dist = length - 0.5
                try:
                    param = dist / length
                    point = curve.Evaluate(param, True)
                    if place_arrow(doc, point, direction, selected_symbol, view):
                        arrow_count += 1
                except Exception:
                    continue

        t.Commit()

        # สรุปผลลัพธ์
        result_message = "Processed {} pipes\nPlaced {} flow arrows.\nSpacing: {} meters\n\n".format(
            processed, arrow_count, spacing_meters)
        
        if use_smart_detection:
            result_message += "SMART Flow Detection Results:\n"
            result_message += "- SMART Rule-Based: {} pipes\n".format(smart_based_count)
            if confidence_scores:
                avg_confidence = sum(confidence_scores) / len(confidence_scores)
                result_message += "- Average Confidence: {:.1%}\n".format(avg_confidence)
        else:
            result_message += "Flow Direction Analysis:\n"
            result_message += "- Based on SLOPE: {} pipes\n".format(slope_based_count)
            result_message += "- Based on geometry: {} pipes".format(geometry_based_count)

        TaskDialog.Show("Flow Arrows Created", result_message)

    except Exception as e:
        try:
            if 't' in locals() and t.GetStatus() == TransactionStatus.Started:
                t.RollBack()
        except:
            pass
        TaskDialog.Show("Script Error", str(e))

# -----------------------------
# Run
# -----------------------------
if __name__ == "__main__":
    create_pipe_flow_arrows()