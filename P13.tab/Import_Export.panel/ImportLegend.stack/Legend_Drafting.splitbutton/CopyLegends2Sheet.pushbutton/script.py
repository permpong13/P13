# -*- coding: utf-8 -*-
"""
Copy & Update Legends (Sync Position)
- If missing: Create new.
- If exists: Move to match source location.
"""
from pyrevit import revit, DB, forms

# --- ฟังก์ชันช่วยดึงชื่อแบบปลอดภัย ---
def get_name_safe(element):
    if not element: return "Unknown"
    val = None
    p_view = element.get_Parameter(DB.BuiltInParameter.VIEW_NAME)
    if p_view: val = p_view.AsString()
    if not val:
        p_type = element.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
        if p_type: val = p_type.AsString()
    if not val:
        try: val = element.Name
        except: val = "Unnamed"
    return val if val else "Unnamed"

# --- เริ่มการทำงาน ---
doc = revit.doc
active_view = doc.ActiveView

# 1. ตรวจสอบ Sheet ต้นทาง
if not isinstance(active_view, DB.ViewSheet):
    forms.alert("กรุณาเปิดหน้า Sheet ต้นแบบก่อนครับ", exitscript=True)

# 2. ค้นหา Legend ใน Sheet นี้
viewports = [doc.GetElement(id) for id in active_view.GetAllViewports()]
legend_ports = []
for vp in viewports:
    view = doc.GetElement(vp.ViewId)
    if view.ViewType == DB.ViewType.Legend:
        legend_ports.append(vp)

if not legend_ports:
    forms.alert("ไม่พบ Legend ใน Sheet นี้ครับ", exitscript=True)

# สร้าง Dict ให้เลือก
vp_dict = {}
for vp in legend_ports:
    view_obj = doc.GetElement(vp.ViewId)
    type_id = vp.GetTypeId()
    type_obj = doc.GetElement(type_id) if type_id else None
    
    view_name = get_name_safe(view_obj)
    type_name = get_name_safe(type_obj)
    
    key_name = "{} (Title: {})".format(view_name, type_name)
    vp_dict[key_name] = vp

# 3. เลือก Legend (เลือกหลายตัวได้)
selected_vp_names = forms.SelectFromList.show(
    sorted(vp_dict.keys()),
    title='เลือก Legend ต้นแบบ (Create or Update)',
    multiselect=True
)

if selected_vp_names:
    # 4. เลือก Sheet ปลายทาง
    target_sheets = forms.select_sheets(
        title='เลือก Sheet ปลายทาง',
        include_placeholder=False
    )

    if target_sheets:
        t = DB.Transaction(doc, "Sync Legends")
        t.Start()
        
        created_count = 0
        updated_count = 0
        
        for sheet in target_sheets:
            if sheet.Id == active_view.Id: continue # ข้าม Sheet ตัวเอง

            # Map ViewId -> Viewport Element บน Sheet ปลายทาง เพื่อการค้นหาที่รวดเร็ว
            target_vps_map = {}
            for vp_id in sheet.GetAllViewports():
                vp = doc.GetElement(vp_id)
                target_vps_map[vp.ViewId] = vp
            
            for vp_name in selected_vp_names:
                source_vp = vp_dict[vp_name]
                source_view_id = source_vp.ViewId
                source_center = source_vp.GetBoxCenter()
                source_type_id = source_vp.GetTypeId()
                
                # เช็คว่า Sheet ปลายทางมี Legend นี้ไหม?
                if source_view_id in target_vps_map:
                    # --- กรณีมีอยู่แล้ว: ให้ย้ายตำแหน่ง (Update) ---
                    existing_vp = target_vps_map[source_view_id]
                    
                    # คำนวณระยะที่ต้องขยับ (Vector)
                    current_center = existing_vp.GetBoxCenter()
                    move_vector = source_center - current_center
                    
                    # ถ้าตำแหน่งไม่ตรงกัน ให้ย้าย
                    if not move_vector.IsZeroLength():
                        DB.ElementTransformUtils.MoveElement(doc, existing_vp.Id, move_vector)
                        updated_count += 1
                        print("ย้ายตำแหน่ง: {} บน {}".format(vp_name, sheet.SheetNumber))
                    
                    # อัปเดต View Title Type ให้เหมือนต้นฉบับด้วย
                    if existing_vp.GetTypeId() != source_type_id:
                        existing_vp.ChangeTypeId(source_type_id)

                else:
                    # --- กรณีไม่มี: สร้างใหม่ (Create) ---
                    try:
                        new_vp = DB.Viewport.Create(doc, sheet.Id, source_view_id, source_center)
                        new_vp.ChangeTypeId(source_type_id)
                        created_count += 1
                        
                        # อัปเดต map ทันที กันพลาด
                        target_vps_map[source_view_id] = new_vp
                        print("สร้างใหม่: {} บน {}".format(vp_name, sheet.SheetNumber))
                    except Exception as e:
                        print("Error สร้าง {} บน {}: {}".format(vp_name, sheet.SheetNumber, e))

        t.Commit()
        
        # รายงานผล
        msg = "✅ ทำงานเสร็จสิ้น"
        msg += "\n- สร้างใหม่: {} รายการ".format(created_count)
        msg += "\n- ปรับตำแหน่ง: {} รายการ".format(updated_count)
        
        forms.alert(msg, title="Sync Result")
    else:
        pass
else:
    pass