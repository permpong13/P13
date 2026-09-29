# -*- coding: utf-8 -*-
"""Calculate Pipe Start and End Bottom-of-Pipe (B.O.P.) elevations and set parameters for tagging."""

__title__ = "Pipe BOP\nCalculator"
__author__ = "Permpong Thaweekul (P13)"
__doc__ = "Calculates upper and lower Bottom-of-Pipe (BOP) elevations and stores them in taggable parameters."

import os
import tempfile
import math
from System.Collections.Generic import List
from pyrevit import revit, DB, script, forms

doc = revit.doc
app = doc.Application
output = script.get_output()

output.print_md("## **Pipe BOP & Slope Calculator**")

# =====================================================
# Shared-parameter setup
# =====================================================
def setup_parameter(doc, app, param_name, param_type, all_cat_names):
    existing_def = None
    existing_binding = None

    iterator = doc.ParameterBindings.ForwardIterator()
    while iterator.MoveNext():
        if iterator.Key.Name == param_name:
            existing_def = iterator.Key
            existing_binding = iterator.Current
            break

    # Update an existing binding with any missing categories.
    if existing_def and existing_binding:
        cat_set = existing_binding.Categories
        needs_update = False
        for c in all_cat_names:
            try:
                b_cat = getattr(DB.BuiltInCategory, c)
                cat = doc.Settings.Categories.get_Item(b_cat)
                if cat and cat.AllowsBoundParameters and not cat_set.Contains(cat):
                    cat_set.Insert(cat)
                    needs_update = True
            except: pass

        if needs_update:
            t_rebind = DB.Transaction(doc, "Update {} Categories".format(param_name))
            t_rebind.Start()
            try:
                new_binding = app.Create.NewInstanceBinding(cat_set)
                doc.ParameterBindings.ReInsert(existing_def, new_binding)
                t_rebind.Commit()
                return "updated"
            except:
                t_rebind.RollBack()
                return "exists"
        return "exists"

    # Create the shared parameter when it does not exist.
    sp_file = app.OpenSharedParameterFile()
    original_sp = app.SharedParametersFilename

    if not sp_file:
        temp_dir = tempfile.gettempdir()
        temp_sp_path = os.path.join(temp_dir, "Auto_SharedParams_Revit.txt")
        if not os.path.exists(temp_sp_path):
            with open(temp_sp_path, "w") as f: f.write("")
        try:
            app.SharedParametersFilename = temp_sp_path
            sp_file = app.OpenSharedParameterFile()
        except: pass

    if not sp_file: return "sp_error"

    target_def = None
    for group in sp_file.Groups:
        for definition in group.Definitions:
            if definition.Name == param_name:
                target_def = definition
                break
        if target_def: break

    if not target_def:
        group_name = "Data"
        group = sp_file.Groups.get_Item(group_name)
        if not group: group = sp_file.Groups.Create(group_name)
        try:
            if param_type == "Text":
                opt = DB.ExternalDefinitionCreationOptions(param_name, DB.SpecTypeId.String.Text)
            else:
                opt = DB.ExternalDefinitionCreationOptions(param_name, DB.SpecTypeId.Length)
            target_def = group.Definitions.Create(opt)
        except AttributeError:
            if param_type == "Text":
                opt = DB.ExternalDefinitionCreationOptions(param_name, DB.ParameterType.Text)
            else:
                opt = DB.ExternalDefinitionCreationOptions(param_name, DB.ParameterType.Length)
            target_def = group.Definitions.Create(opt)

    if original_sp and app.SharedParametersFilename != original_sp:
        try: app.SharedParametersFilename = original_sp
        except: pass

    if not target_def: return "def_not_found"

    cat_set = app.Create.NewCategorySet()
    for c in all_cat_names:
        try:
            b_cat = getattr(DB.BuiltInCategory, c)
            cat = doc.Settings.Categories.get_Item(b_cat)
            if cat and cat.AllowsBoundParameters:
                cat_set.Insert(cat)
        except: pass

    if cat_set.IsEmpty: return "no_categories"

    binding = app.Create.NewInstanceBinding(cat_set)
    t_param = DB.Transaction(doc, "Setup Parameter: {}".format(param_name))
    t_param.Start()
    try:
        try: doc.ParameterBindings.Insert(target_def, binding, DB.GroupTypeId.Data)
        except AttributeError: doc.ParameterBindings.Insert(target_def, binding, DB.BuiltInParameterGroup.PG_DATA)
        t_param.Commit()
        return "created"
    except:
        t_param.RollBack()
        return "bind_error"


# =====================================================
# Validate and prepare required parameters
# =====================================================
output.print_md("### **1. Checking project parameters**")
cat_pipes = ["OST_PipeCurves"]

status_start = setup_parameter(doc, app, "BOP_Start", "Length", cat_pipes)
status_end   = setup_parameter(doc, app, "BOP_End",   "Length", cat_pipes)

if status_start in ["created", "updated", "exists"] and status_end in ["created", "updated", "exists"]:
    output.print_md("✅ **'BOP_Start' and 'BOP_End' length parameters are ready.**")
else:
    output.print_md("⚠️ **Unable to set up parameters (BOP_Start: {}, BOP_End: {}).**".format(status_start, status_end))
    script.exit()

# =====================================================
# Collect pipes
# =====================================================
selection = revit.get_selection()
pipes = [el for el in selection if isinstance(el, DB.Plumbing.Pipe)]

is_selection_mode = True
if not pipes:
    is_selection_mode = False
    pipes = DB.FilteredElementCollector(doc, doc.ActiveView.Id) \
              .OfCategory(DB.BuiltInCategory.OST_PipeCurves) \
              .WhereElementIsNotElementType() \
              .ToElements()

if not pipes:
    output.print_md("❌ **No pipes were found in the selection or active view.**")
    script.exit()

output.print_md("---")
if is_selection_mode:
    output.print_md("### **2. Calculating BOP elevations (Selection Mode): {} pipe(s)**".format(len(pipes)))
else:
    output.print_md("### **2. Calculating BOP elevations (Active View Mode): {} pipe(s)**".format(len(pipes)))

# =====================================================
# Check out worksets when the project uses worksharing
# =====================================================
if doc.IsWorkshared:
    try:
        ws_ids = set()
        for p in pipes:
            if hasattr(p, 'WorksetId') and p.WorksetId != DB.WorksetId.InvalidWorksetId:
                ws_ids.add(p.WorksetId)
        if ws_ids:
            ws_list = List[DB.WorksetId]()
            for w_id in ws_ids:
                ws_list.Add(w_id)
            DB.WorksharingUtils.CheckoutWorksets(doc, ws_list)
    except Exception as ex:
        output.print_md("⚠️ **Some worksets could not be checked out: {}**".format(ex))

# =====================================================
# Allow varying values between group instances
# =====================================================
def set_allow_vary_between_groups(doc, param_name):
    iterator = doc.ParameterBindings.ForwardIterator()
    while iterator.MoveNext():
        definition = iterator.Key
        if definition.Name == param_name and isinstance(definition, DB.InternalDefinition):
            try:
                if not definition.VariesAcrossGroups:
                    definition.SetAllowVaryBetweenGroups(doc, True)
            except:
                pass
            break


def get_parameter_display_value(element, param_name):
    """Return a safe display value for an optional parameter."""
    param = element.LookupParameter(param_name)
    if not param:
        return "N/A"
    try:
        return param.AsString() or param.AsValueString() or "N/A"
    except:
        return "N/A"

# =====================================================
# Calculate and write BOP elevations
# =====================================================
t = DB.Transaction(doc, "Calculate Pipe BOP Parameters")
t.Start()

set_allow_vary_between_groups(doc, "BOP_Start")
set_allow_vary_between_groups(doc, "BOP_End")

success_count = 0
read_only_count = 0
group_skipped_count = 0
error_count = 0

summary_data = []
error_details = []

with forms.ProgressBar(title='Calculating BOP elevations... ({value} of {max_value})', cancellable=True) as pb:
    for index, pipe in enumerate(pipes):
        if pb.cancelled:
            break
        pb.update_progress(index + 1, len(pipes))
        
        # Skip grouped pipes because Revit blocks modifications to group members.
        if hasattr(pipe, 'GroupId') and pipe.GroupId != DB.ElementId.InvalidElementId:
            group_skipped_count += 1
            continue
            
        try:
            # Read the lower BOP directly from Revit's calculated parameter.
            # It has the same elevation datum as the value in Properties.
            lower_bop_param = pipe.get_Parameter(
                DB.BuiltInParameter.RBS_PIPE_BOTTOM_ELEVATION)
            if not lower_bop_param or not lower_bop_param.HasValue:
                raise Exception("Lower End Bottom Elevation is unavailable.")

            # The internal-origin coordinate is suitable only for the vertical
            # difference between endpoints. Applying that difference to Revit's
            # lower BOP retains the elevation datum used by the Properties palette.
            geom_curve = pipe.Location.Curve
            if not geom_curve:
                raise Exception("Pipe location curve is unavailable.")

            vertical_difference = abs(
                geom_curve.GetEndPoint(0).Z - geom_curve.GetEndPoint(1).Z)
            bop_low = lower_bop_param.AsDouble()
            bop_high = bop_low + vertical_difference
            
            # Read slope information.
            slope_param = pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPE_SLOPE)
            slope_val = slope_param.AsDouble() if slope_param else 0.0
            
            # Write BOP_Start for the upper end and BOP_End for the lower end.
            p_start = pipe.LookupParameter("BOP_Start")
            p_end = pipe.LookupParameter("BOP_End")
            
            if p_start and p_end:
                if not p_start.IsReadOnly and not p_end.IsReadOnly:
                    p_start.Set(bop_high)
                    p_end.Set(bop_low)
                    success_count += 1
                    
                    # Record result data for the report.
                    size_name = get_parameter_display_value(pipe, "Size")
                    sys_abbr = get_parameter_display_value(pipe, "System Abbreviation")
                    
                    bop_high_m = bop_high * 0.3048
                    bop_low_m = bop_low * 0.3048
                    slope_percent = slope_val * 100.0
                    
                    # Convert slope to a ratio, for example 1:100.
                    if slope_val > 0.0001:
                        slope_ratio = "1:{:.0f}".format(1.0 / slope_val)
                    else:
                        slope_ratio = "Flat"
                        
                    summary_data.append({
                        "id": pipe.Id.IntegerValue if hasattr(pipe.Id, "IntegerValue") else pipe.Id.Value,
                        "name": "{} {}".format(size_name, sys_abbr),
                        "slope": "{:.2f}% ({})".format(slope_percent, slope_ratio),
                        "b_start": "{:.3f} m".format(bop_high_m),
                        "bop_cal": "{:.3f} m".format(bop_low_m)
                    })
                else:
                    read_only_count += 1
            else:
                error_count += 1
                if len(error_details) < 10:
                    error_details.append(
                        "Pipe {}: BOP_Start or BOP_End is unavailable.".format(pipe.Id))
                
        except Exception as ex:
            error_count += 1
            if len(error_details) < 10:
                error_details.append("Pipe {}: {}".format(pipe.Id, ex))

t.Commit()

# =====================================================
# Report results
# =====================================================
output.print_md("### **Results**")
output.print_md("- Updated pipe(s): **{}**".format(success_count))
if group_skipped_count > 0:
    output.print_md("- Skipped grouped pipe(s): **{}**".format(group_skipped_count))
if read_only_count > 0:
    output.print_md("- ⚠️ Read-only parameter(s): **{}**".format(read_only_count))
if error_count > 0:
    output.print_md("- ❌ Technical errors: **{}**".format(error_count))
    for error_detail in error_details:
        output.print_md("  - {}".format(error_detail))

if success_count > 0:
    output.print_md("---")
    output.print_md("### **Updated data sample (first 10 pipes)**")
    output.print_md("| Pipe ID | Size & System | Slope | BOP_Start (BOP High) | BOP_End (BOP Low) |")
    output.print_md("| --- | --- | --- | --- | --- |")
    for row in summary_data[:10]:
        output.print_md("| {} | {} | {} | {} | {} |".format(
            row["id"], row["name"], row["slope"], row["b_start"], row["bop_cal"]
        ))
    output.print_md("---")
    output.print_md("Use the `BOP_Start` and `BOP_End` parameters in pipe tags and schedules.")
