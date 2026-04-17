# -*- coding: utf-8 -*-
__title__ = "Tag Legend"
__doc__ = "Tag parameter values to Legend Components and remember your settings."

from itertools import izip
from pyrevit import revit, DB, script, HOST_APP, forms
from rpw.ui.forms import (FlexForm, Label, ComboBox, TextBox, Separator, Button, CheckBox)
from Autodesk.Revit.UI.Selection import ObjectType
import sys

# --- CONFIGURATION SETTINGS ---
cfg = script.get_config("TagLegend")

last_style_name = getattr(cfg, "last_style", None)
last_pos = getattr(cfg, "last_pos", "Bottom Left")
last_show_p = getattr(cfg, "last_show_p", False)
last_offset = getattr(cfg, "last_offset", "2.0")
last_keep_pos = getattr(cfg, "last_keep_pos", False)
last_sel_mode = getattr(cfg, "last_sel_mode", "All in View")

def get_param_value_formatted(param):
    if not param or not param.HasValue:
        return None
    val = param.AsValueString()
    if val:
        return val
    st = param.StorageType
    if st == DB.StorageType.String: return param.AsString()
    if st == DB.StorageType.Integer: return str(param.AsInteger())
    if st == DB.StorageType.Double: return "{:.2f}".format(param.AsDouble())
    return None

# --- PRE-CHECK ---
view = revit.active_view
if view.ViewType != DB.ViewType.Legend:
    forms.alert("View is not a Legend View", exitscript=True)

# --- UI PREPARATION ---
txt_types = DB.FilteredElementCollector(revit.doc).OfClass(DB.TextNoteType)
text_style_dict = {txt_t.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString(): txt_t for txt_t in txt_types}

positions_list = [
    "Top Left", "Top Centre", "Top Right",
    "Middle Left", "Middle Centre", "Middle Right",
    "Bottom Left", "Bottom Centre", "Bottom Right"
]

sel_modes = ["All in View", "Pick on Screen"]

components = [
    Label("Selection Method"),
    ComboBox("sel_mode", sel_modes, default=last_sel_mode),
    Separator(),
    Label("Pick Text Style"),
    ComboBox("textstyle", text_style_dict, default=last_style_name),
    Label("Pick Text Position (For New Tags)"),
    ComboBox("position", positions_list, default=last_pos),
    Label("Text Offset (mm)"),
    TextBox("offset", default=last_offset),
    Separator(),
    CheckBox('show_p_name', 'Show Parameter Name', default=last_show_p),
    CheckBox('keep_pos', 'Keep existing text positions (Update text only)', default=last_keep_pos),
    CheckBox('cleanup', 'Delete unused tags', default=True),
    Button("Next >")
]

form = FlexForm("Tag Legend v3.0", components)
if not form.show():
    sys.exit()

# --- SAVE SETTINGS ---
chosen_sel_mode = form.values["sel_mode"]
chosen_style = form.values["textstyle"]
chosen_pos = form.values["position"]
offset_val = form.values["offset"]
show_p_name = form.values["show_p_name"]
keep_pos = form.values["keep_pos"]
do_cleanup = form.values["cleanup"]

style_name = chosen_style.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
cfg.last_sel_mode = chosen_sel_mode
cfg.last_style = style_name
cfg.last_pos = chosen_pos
cfg.last_offset = offset_val
cfg.last_show_p = show_p_name
cfg.last_keep_pos = keep_pos
script.save_config()

# --- COMPONENT SELECTION LOGIC ---
legend_components = []

if chosen_sel_mode == "All in View":
    legend_components = DB.FilteredElementCollector(revit.doc, view.Id) \
        .OfCategory(DB.BuiltInCategory.OST_LegendComponents) \
        .WhereElementIsNotElementType() \
        .ToElements()
else:
    try:
        with forms.WarningBar(title="Select Elements, then click Finish (or Right-Click -> Finish)"):
            refs = revit.uidoc.Selection.PickObjects(ObjectType.Element, "Select Legend Components")
            
            for r in refs:
                el = revit.doc.GetElement(r.ElementId)
                if el and hasattr(el, "Category") and el.Category:
                    # แก้ไขการเปรียบเทียบ Category เพื่อรองรับการเปลี่ยนแปลง API ใน Revit 2024+
                    if el.Category.Id == DB.ElementId(DB.BuiltInCategory.OST_LegendComponents):
                        legend_components.append(el)
                        
    except Exception as e:
        if "OperationCanceledException" in str(type(e)):
            sys.exit()
        else:
            forms.alert("เกิดข้อผิดพลาดระหว่างการเลือกวัตถุ:\n{}".format(str(e)), exitscript=True)

if not legend_components:
    forms.alert("ไม่พบ Legend Component ในสิ่งที่คุณเลือกครับ (คุณอาจจะเลือกโดนแค่ Text หรือ Line)\nโปรดลองรันคำสั่งใหม่อีกครั้ง", exitscript=True)

# --- LOGIC ---
try:
    user_offset = float(offset_val)
except:
    user_offset = 2.0 

scale = float(view.Scale)/100
text_offset = user_offset * scale

def get_type_element(lc):
    comp_name = lc.get_Parameter(DB.BuiltInParameter.LEGEND_COMPONENT).AsValueString()
    if not comp_name or " : " not in comp_name: 
        return None
        
    fragments = comp_name.split(" : ")
    if len(fragments) >= 3:
        f_name, t_name = fragments[1], fragments[-1]
    elif len(fragments) == 2:
        f_name, t_name = fragments[0], fragments[-1]
    else:
        return None
    
    collector = DB.FilteredElementCollector(revit.doc).WhereElementIsElementType()
    for t in collector:
        type_name_param = t.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
        if type_name_param and type_name_param.AsString() == t_name:
            fam = t.Family
            if fam and fam.Name == f_name:
                return t
    return None

types_on_legend = [get_type_element(lc) for lc in legend_components]
params_set = set()
for t in types_on_legend:
    if t:
        for p in t.Parameters:
            params_set.add(p.Definition.Name)

if not params_set:
    forms.alert("ไม่พบ Type Parameter ให้ดึงข้อมูลใน Legend Component ที่คุณเลือกครับ", exitscript=True)

selected_parameters = forms.SelectFromList.show(sorted(list(params_set)),
                                                title="Select Parameters to Display",
                                                multiselect=True)
if not selected_parameters: sys.exit()

# --- EXECUTION ---
with revit.Transaction("Tag Legend Components"):
    
    all_existing_notes = DB.FilteredElementCollector(revit.doc, view.Id) \
        .OfClass(DB.TextNote) \
        .ToElements()
    managed_notes = [n for n in all_existing_notes if n.TextNoteType.Id == chosen_style.Id]

    if do_cleanup and not keep_pos and chosen_sel_mode == "All in View":
        for note in managed_notes:
            revit.doc.Delete(note.Id)
        managed_notes = [] 

    for l, ton in izip(legend_components, types_on_legend):
        if not ton: continue
            
        display_texts = []
        for sp in selected_parameters:
            p = ton.LookupParameter(sp)
            val = get_param_value_formatted(p)
            if val:
                line = "{}: {}".format(sp, val) if show_p_name else val
                display_texts.append(line)

        if not display_texts: continue
        final_text = "\n".join(display_texts)

        bb = l.get_BoundingBox(view)
        mid_x = (bb.Max.X + bb.Min.X) / 2
        mid_y = (bb.Max.Y + bb.Min.Y) / 2
        
        updated_existing = False
        
        if keep_pos and managed_notes:
            lc_pt = DB.XYZ(mid_x, mid_y, 0)
            closest_note = None
            min_dist = float('inf')
            
            for n in managed_notes:
                nc = n.Coord
                n_pt = DB.XYZ(nc.X, nc.Y, 0)
                d = lc_pt.DistanceTo(n_pt)
                if d < min_dist:
                    min_dist = d
                    closest_note = n
            
            if closest_note:
                closest_note.Text = final_text
                managed_notes.remove(closest_note)
                updated_existing = True
        
        if not updated_existing:
            pos_map = {
                "Top Left": DB.XYZ(bb.Min.X, bb.Max.Y + text_offset, 0),
                "Top Centre": DB.XYZ(mid_x, bb.Max.Y + text_offset, 0),
                "Top Right": DB.XYZ(bb.Max.X, bb.Max.Y + text_offset, 0),
                "Middle Left": DB.XYZ(bb.Min.X - text_offset, mid_y, 0),
                "Middle Centre": DB.XYZ(mid_x, mid_y, 0),
                "Middle Right": DB.XYZ(bb.Max.X + text_offset, mid_y, 0),
                "Bottom Left": DB.XYZ(bb.Min.X, bb.Min.Y - text_offset, 0),
                "Bottom Centre": DB.XYZ(mid_x, bb.Min.Y - text_offset, 0),
                "Bottom Right": DB.XYZ(bb.Max.X, bb.Min.Y - text_offset, 0)
            }
            
            opts = DB.TextNoteOptions(chosen_style.Id)
            
            if "Centre" in chosen_pos:
                opts.HorizontalAlignment = DB.HorizontalTextAlignment.Center
            elif "Right" in chosen_pos:
                opts.HorizontalAlignment = DB.HorizontalTextAlignment.Left if "Middle" in chosen_pos else DB.HorizontalTextAlignment.Right
            elif "Left" in chosen_pos:
                opts.HorizontalAlignment = DB.HorizontalTextAlignment.Right if "Middle" in chosen_pos else DB.HorizontalTextAlignment.Left

            if "Top" in chosen_pos:
                opts.VerticalAlignment = DB.VerticalTextAlignment.Bottom
            elif "Middle" in chosen_pos:
                opts.VerticalAlignment = DB.VerticalTextAlignment.Middle
            elif "Bottom" in chosen_pos:
                opts.VerticalAlignment = DB.VerticalTextAlignment.Top

            DB.TextNote.Create(revit.doc, view.Id, pos_map[chosen_pos], final_text, opts)

    if do_cleanup and keep_pos and chosen_sel_mode == "All in View":
        for orphan in managed_notes:
            revit.doc.Delete(orphan.Id)

print("Success: Tagged {} components.".format(len(legend_components)))