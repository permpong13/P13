# -*- coding: utf-8 -*-
"""
Copy Sheets Across Projects
Created by Antigravity

This script copies selected sheets from the active document to another open document.
It preserves titleblocks, viewports (drafting views, legends, and schedules), and sheet annotations.
"""

__title__ = 'Copy Sheets\nAcross Projects'
__author__ = 'Antigravity'

import sys
from pyrevit import forms
from pyrevit import revit, DB, script
from Autodesk.Revit.DB import *
from System.Collections.Generic import List

# Setup logger
logger = script.get_logger()


class CopyUseDestination(IDuplicateTypeNamesHandler):
    """Resolves duplicate types by preferring the destination types."""
    def OnDuplicateTypeNamesFound(self, args):
        return DuplicateTypeAction.UseDestinationTypes


def get_id_value(element_id):
    """Safely get the integer/long value of an ElementId across Revit versions."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def get_element_name(element):
    """Safely get the name of an element or element type."""
    if not element:
        return ""
    try:
        return element.Name
    except Exception:
        pass
    try:
        p = element.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if p and p.HasValue:
            return p.AsString()
    except Exception:
        pass
    try:
        p = element.get_Parameter(BuiltInParameter.DATUM_TEXT)
        if p and p.HasValue:
            return p.AsString()
    except Exception:
        pass
    return ""


def get_unique_view_name(dest_doc, base_name):
    """Generates a unique view name in the destination document."""
    existing_names = set()
    for v in FilteredElementCollector(dest_doc).OfClass(View):
        name = get_element_name(v)
        if name:
            existing_names.add(name.lower())
    new_name = base_name
    counter = 1
    while new_name.lower() in existing_names:
        new_name = "{} ({})".format(base_name, counter)
        counter += 1
    return new_name


def copy_drafting_view_across_docs(src_view, dest_doc, copy_options):
    """Duplicates a Drafting View with its detail elements to another document."""
    # 1. Find a view family type for Drafting View in dest_doc
    drafting_types = [vt for vt in FilteredElementCollector(dest_doc).OfClass(ViewFamilyType) if vt.ViewFamily == ViewFamily.Drafting]
    if not drafting_types:
        raise Exception("No Drafting View type found in destination document.")
    drafting_view_type = drafting_types[0]
    
    # 2. Check if a view with the same name already exists in dest_doc
    existing_view = None
    src_view_name = get_element_name(src_view)
    for v in FilteredElementCollector(dest_doc).OfClass(View):
        if get_element_name(v) == src_view_name and v.ViewType == ViewType.DraftingView:
            existing_view = v
            break
            
    dest_view = None
    if existing_view:
        # Check if this view is already placed on any sheet in the target document
        viewports_in_dest = FilteredElementCollector(dest_doc).OfClass(Viewport).ToElements()
        placed_view_ids = {vp.ViewId for vp in viewports_in_dest}
        
        if existing_view.Id in placed_view_ids:
            # Already placed on a sheet, we must create a new one with a unique name
            unique_name = get_unique_view_name(dest_doc, src_view_name)
            dest_view = ViewDrafting.Create(dest_doc, drafting_view_type.Id)
            dest_view.Name = unique_name
            dest_view.Scale = src_view.Scale
            print("   ℹ️ Drafting view '{}' is already placed on another sheet. Created new duplicate view '{}'.".format(src_view_name, unique_name))
        else:
            # Exists but not placed on any sheet, we can reuse it!
            # Let's clean up any existing elements in it to update it with the latest content
            dest_view = existing_view
            dest_view.Scale = src_view.Scale
            
            elements_to_delete = []
            for el in FilteredElementCollector(dest_doc, dest_view.Id).WhereElementIsNotElementType():
                if el.Category and el.Id != dest_view.Id:
                    elements_to_delete.append(el.Id)
            if elements_to_delete:
                try:
                    dest_doc.Delete(List[ElementId](elements_to_delete))
                except Exception as del_ex:
                    logger.debug("Failed to delete existing view elements: {}".format(del_ex))
            print("   ℹ️ Reusing existing unplaced drafting view '{}' and updating contents.".format(src_view_name))
    else:
        # Does not exist, create it new
        unique_name = get_unique_view_name(dest_doc, src_view_name)
        dest_view = ViewDrafting.Create(dest_doc, drafting_view_type.Id)
        dest_view.Name = unique_name
        dest_view.Scale = src_view.Scale
        
    # 4. Collect all annotation/detail elements in the source drafting view
    elements_to_copy = []
    for el in FilteredElementCollector(src_view.Document, src_view.Id).WhereElementIsNotElementType():
        if el.Category and el.Id != src_view.Id:
            elements_to_copy.append(el.Id)
            
    # 5. Copy detail elements view-to-view
    if elements_to_copy:
        try:
            copied_elements = ElementTransformUtils.CopyElements(
                src_view,
                List[ElementId](elements_to_copy),
                dest_view,
                None,
                copy_options
            )
            # Sync graphic overrides
            for d_id, s_id in zip(copied_elements, elements_to_copy):
                try:
                    dest_view.SetElementOverrides(d_id, src_view.GetElementOverrides(s_id))
                except:
                    pass
        except Exception as e:
            # Fallback: copy elements one-by-one if batch copy fails
            print("   ⚠️ Batch copy failed for drafting view '{}' detail elements: {}. Trying one-by-one...".format(src_view_name, e))
            copied_count = 0
            for el_id in elements_to_copy:
                try:
                    single_copied = ElementTransformUtils.CopyElements(
                        src_view,
                        List[ElementId]([el_id]),
                        dest_view,
                        None,
                        copy_options
                    )
                    if single_copied:
                        copied_count += 1
                        try:
                            dest_view.SetElementOverrides(single_copied[0], src_view.GetElementOverrides(el_id))
                        except:
                            pass
                except Exception as single_ex:
                    logger.debug("Failed to copy element {}: {}".format(el_id, single_ex))
            print("   ✅ Finished copying detail elements one-by-one (Copied: {}/{})".format(copied_count, len(elements_to_copy)))
            
    return dest_view.Id


def copy_plan_view_across_docs(src_view, dest_doc, copy_options):
    """Duplicates a Plan View with its level, view settings, and detail elements to another document."""
    source_doc = src_view.Document
    src_view_name = get_element_name(src_view)
    
    # 1. Identify View Family Type in dest_doc
    src_type = source_doc.GetElement(src_view.GetTypeId())
    view_family = src_type.ViewFamily
    src_type_name = get_element_name(src_type)
    
    dest_types = [vt for vt in FilteredElementCollector(dest_doc).OfClass(ViewFamilyType) if vt.ViewFamily == view_family]
    if not dest_types:
        raise Exception("No matching ViewFamilyType for '{}' found in destination project.".format(view_family))
        
    dest_type = dest_types[0]
    for vt in dest_types:
        if get_element_name(vt) == src_type_name:
            dest_type = vt
            break
            
    # 2. Check if a view with the same name already exists in dest_doc
    existing_view = None
    for v in FilteredElementCollector(dest_doc).OfClass(View):
        if get_element_name(v) == src_view_name and v.ViewType == src_view.ViewType:
            existing_view = v
            break
            
    dest_view = None
    if existing_view:
        # Check if already placed on a sheet in target doc
        viewports_in_dest = FilteredElementCollector(dest_doc).OfClass(Viewport).ToElements()
        placed_view_ids = {vp.ViewId for vp in viewports_in_dest}
        
        if existing_view.Id in placed_view_ids:
            # Already placed on a sheet. We must duplicate it to place it on the new sheet.
            try:
                if existing_view.CanBeDuplicated():
                    new_v_id = existing_view.Duplicate(ViewDuplicateOption.WithDetailing)
                    dest_view = dest_doc.GetElement(new_v_id)
                    # Unique naming
                    unique_name = get_unique_view_name(dest_doc, src_view_name)
                    dest_view.Name = unique_name
                    print("   ℹ️ Plan view '{}' is already placed on another sheet. Created duplicate view '{}'.".format(src_view_name, unique_name))
                else:
                    raise Exception("View cannot be duplicated.")
            except Exception as dup_ex:
                raise Exception("Plan view '{}' already exists, is placed on another sheet, and cannot be duplicated: {}".format(src_view_name, dup_ex))
        else:
            # Reusing the existing unplaced view
            dest_view = existing_view
            dest_view.Scale = src_view.Scale
            
            # Clean up existing view-specific detailing to update with fresh source details
            elements_to_delete = []
            for el in FilteredElementCollector(dest_doc, dest_view.Id).WhereElementIsNotElementType():
                if el.OwnerViewId == dest_view.Id and el.Id != dest_view.Id:
                    elements_to_delete.append(el.Id)
            if elements_to_delete:
                try:
                    dest_doc.Delete(List[ElementId](elements_to_delete))
                except Exception as del_ex:
                    logger.debug("Failed to delete existing annotations in plan view: {}".format(del_ex))
            print("   ℹ️ Reusing existing unplaced plan view '{}' and updating details.".format(src_view_name))
    else:
        # 3. Handle Level copying / matching
        src_level = src_view.GenLevel
        target_level = None
        if src_level:
            src_level_name = get_element_name(src_level)
            for lvl in FilteredElementCollector(dest_doc).OfClass(Level):
                if get_element_name(lvl) == src_level_name:
                    target_level = lvl
                    break
            if not target_level:
                # Copy Level
                try:
                    copied_lvl_ids = ElementTransformUtils.CopyElements(
                        source_doc,
                        List[ElementId]([src_level.Id]),
                        dest_doc,
                        Transform.Identity,
                        copy_options
                    )
                    target_level = dest_doc.GetElement(copied_lvl_ids[0])
                    print("   ✅ Level '{}' did not exist in target project. Copied level successfully.".format(src_level_name))
                except Exception as lvl_ex:
                    raise Exception("Associated Level '{}' not found in target and could not be copied: {}".format(src_level_name, lvl_ex))
        
        if not target_level:
            raise Exception("No associated level found for plan view '{}'.".format(src_view_name))
            
        # 4. Create the view plan
        unique_name = get_unique_view_name(dest_doc, src_view_name)
        dest_view = ViewPlan.Create(dest_doc, dest_type.Id, target_level.Id)
        dest_view.Name = unique_name
        dest_view.Scale = src_view.Scale
        print("   ✅ Created new plan view '{}' on level '{}'.".format(unique_name, get_element_name(target_level)))
        
    # 5. Sync View settings (View Template, Crop, View Range)
    try:
        dest_view.CropBoxActive = src_view.CropBoxActive
        dest_view.CropBoxVisible = src_view.CropBoxVisible
        if src_view.CropBoxActive:
            dest_view.CropBox = src_view.CropBox
    except Exception as crop_ex:
        logger.debug("Failed to copy crop settings: {}".format(crop_ex))
        
    try:
        dest_view.SetViewRange(src_view.GetViewRange())
    except Exception as vr_ex:
        logger.debug("Failed to set view range: {}".format(vr_ex))
        
    try:
        src_template_id = src_view.ViewTemplateId
        if src_template_id != ElementId.InvalidElementId:
            src_template = source_doc.GetElement(src_template_id)
            src_template_name = get_element_name(src_template)
            dest_template = None
            for vt in FilteredElementCollector(dest_doc).OfClass(View):
                if vt.IsTemplate and get_element_name(vt) == src_template_name:
                    dest_template = vt
                    break
            if dest_template:
                dest_view.ViewTemplateId = dest_template.Id
    except Exception as temp_ex:
        logger.debug("Failed to match view template: {}".format(temp_ex))
        
    # 6. Copy 2D view-specific elements (annotations, text, dimensions)
    elements_to_copy = []
    for el in FilteredElementCollector(src_view.Document, src_view.Id).WhereElementIsNotElementType():
        if el.OwnerViewId == src_view.Id and el.Id != src_view.Id:
            elements_to_copy.append(el.Id)
            
    if elements_to_copy:
        try:
            copied_elements = ElementTransformUtils.CopyElements(
                src_view,
                List[ElementId](elements_to_copy),
                dest_view,
                None,
                copy_options
            )
            # Sync graphic overrides
            for d_id, s_id in zip(copied_elements, elements_to_copy):
                try:
                    dest_view.SetElementOverrides(d_id, src_view.GetElementOverrides(s_id))
                except:
                    pass
        except Exception as e:
            # Fallback: copy elements one-by-one if batch copy fails
            print("   ⚠️ Batch copy failed for plan view '{}' annotations: {}. Trying one-by-one...".format(src_view_name, e))
            copied_count = 0
            for el_id in elements_to_copy:
                try:
                    single_copied = ElementTransformUtils.CopyElements(
                        src_view,
                        List[ElementId]([el_id]),
                        dest_view,
                        None,
                        copy_options
                    )
                    if single_copied:
                        copied_count += 1
                        try:
                            dest_view.SetElementOverrides(single_copied[0], src_view.GetElementOverrides(el_id))
                        except:
                            pass
                except Exception as single_ex:
                    logger.debug("Failed to copy element {}: {}".format(el_id, single_ex))
            print("   ✅ Finished copying annotations one-by-one (Copied: {}/{})".format(copied_count, len(elements_to_copy)))
            
    return dest_view.Id


def copy_legend_view_across_docs(src_view, dest_doc, copy_options):
    """Copies a Legend view element directly to another document."""
    # 1. Check if a legend with the same name already exists in dest_doc
    existing_view = None
    src_view_name = get_element_name(src_view)
    for v in FilteredElementCollector(dest_doc).OfClass(View):
        if get_element_name(v) == src_view_name and v.ViewType == ViewType.Legend:
            existing_view = v
            break
            
    if existing_view:
        return existing_view.Id
        
    # 2. Copy the legend view itself doc-to-doc
    view_ids = List[ElementId]()
    view_ids.Add(src_view.Id)
    copied_ids = ElementTransformUtils.CopyElements(
        src_view.Document,
        view_ids,
        dest_doc,
        Transform.Identity,
        copy_options
    )
    
    if copied_ids:
        for c_id in copied_ids:
            new_v = dest_doc.GetElement(c_id)
            if isinstance(new_v, View) and new_v.ViewType == ViewType.Legend:
                if get_element_name(new_v) != src_view_name:
                    new_v.Name = src_view_name
                return new_v.Id
                
    raise Exception("Failed to copy Legend view element.")


class Option(forms.TemplateListItem):
    def __init__(self, op_name, default_state=False):
        super(Option, self).__init__(op_name, checked=default_state)
        self.checked = default_state
        self.state = default_state


class OptionSet:
    def __init__(self):
        self.op_copy_vports = Option("Copy Viewports (Drafting Views, Legends, etc.)", True)
        self.op_copy_schedules = Option("Copy Schedules", True)


def copy_sheet_across_docs(source_sheet, dest_doc, options):
    source_doc = source_sheet.Document
    
    # 1. Gather all existing sheet numbers in dest_doc to prevent collisions
    existing_sheets = FilteredElementCollector(dest_doc).OfClass(ViewSheet).ToElements()
    existing_numbers = {s.SheetNumber for s in existing_sheets}
    
    original_number = source_sheet.SheetNumber
    temp_number = original_number
    counter = 1
    while temp_number in existing_numbers:
        temp_number = "{}_COPY{}".format(original_number, counter)
        counter += 1
        
    # 2. Gather viewport and schedule details from the source sheet
    viewport_ids = source_sheet.GetAllViewports()
    viewports = [source_doc.GetElement(vp_id) for vp_id in viewport_ids]
    
    schedules = []
    col = FilteredElementCollector(source_doc, source_sheet.Id).OfClass(ScheduleSheetInstance)
    for sched in col:
        if not sched.IsTitleblockRevisionSchedule:
            schedules.append(sched)
            
    # Record viewport layout details
    vp_details = []
    for vp in viewports:
        view = source_doc.GetElement(vp.ViewId)
        vp_details.append({
            'view_id': vp.ViewId,
            'view_name': view.Name,
            'view_type': view.ViewType,
            'center': vp.GetBoxCenter(),
            'type_id': vp.GetTypeId(),
            'detail_number': vp.get_Parameter(BuiltInParameter.VIEWPORT_DETAIL_NUMBER).AsString() if vp.get_Parameter(BuiltInParameter.VIEWPORT_DETAIL_NUMBER) else None
        })
        
    # Record schedule layout details
    sched_details = []
    for sched in schedules:
        sched_view = source_doc.GetElement(sched.ScheduleId)
        sched_details.append({
            'schedule_id': sched.ScheduleId,
            'schedule_name': sched_view.Name,
            'point': sched.Point
        })

    # 3. Start a Temporary Transaction in the source document to clean up sheet for copying
    # (Since Viewports cannot be copied directly via ElementTransformUtils)
    t_source = Transaction(source_doc, "Temp Sheet Copy Prep")
    t_source.Start()
    try:
        # Delete viewports and schedules from the sheet in source
        for vp in viewports:
            source_doc.Delete(vp.Id)
        for sched in schedules:
            source_doc.Delete(sched.Id)
            
        # Temporarily rename the sheet number if there is a collision
        if temp_number != original_number:
            source_sheet.SheetNumber = temp_number
            
        # 4. Start Transaction in destination document to copy the sheet element
        t_dest = Transaction(dest_doc, "Copy Sheet - {}".format(original_number))
        t_dest.Start()
        try:
            copy_options = CopyPasteOptions()
            copy_options.SetDuplicateTypeNamesHandler(CopyUseDestination())
            
            # Copy the sheet element (this copies sheet, titleblock, and details on it)
            copied_ids = ElementTransformUtils.CopyElements(
                source_doc,
                List[ElementId]([source_sheet.Id]),
                dest_doc,
                Transform.Identity,
                copy_options
            )
            
            if not copied_ids:
                raise Exception("Failed to copy ViewSheet element.")
                
            new_sheet = dest_doc.GetElement(copied_ids[0])
            
            # Re-apply correct sheet numbers/names
            if temp_number != original_number:
                new_sheet.SheetNumber = temp_number
                print("⚠️ Sheet number '{}' already exists in target project. Renamed copy to '{}'.".format(original_number, temp_number))
            else:
                new_sheet.SheetNumber = original_number
                
            new_sheet.Name = source_sheet.Name
            
            # Copy sheet annotations (Text, Lines, Filled Regions, etc.)
            elements_to_copy = []
            col = FilteredElementCollector(source_doc, source_sheet.Id).WhereElementIsNotElementType()
            for el in col:
                if not el.Category:
                    continue
                if el.Id == source_sheet.Id:
                    continue
                cat_id = get_id_value(el.Category.Id)
                if cat_id == int(BuiltInCategory.OST_Viewports) or isinstance(el, Viewport):
                    continue
                if cat_id == int(BuiltInCategory.OST_TitleBlocks):
                    continue
                if isinstance(el, ScheduleSheetInstance):
                    continue
                if "guide" in el.Category.Name.lower():
                    continue
                elements_to_copy.append(el.Id)
                
            if elements_to_copy:
                try:
                    copied_el_ids = ElementTransformUtils.CopyElements(
                        source_sheet,
                        List[ElementId](elements_to_copy),
                        new_sheet,
                        None,
                        copy_options
                    )
                    # Sync graphic overrides
                    for d_id, s_id in zip(copied_el_ids, elements_to_copy):
                        try:
                            new_sheet.SetElementOverrides(d_id, source_sheet.GetElementOverrides(s_id))
                        except:
                            pass
                    print("   ✅ Copied {} annotation elements (Text, Lines, Detail Items).".format(len(copied_el_ids)))
                except Exception as ann_ex:
                    print("   ⚠️ Failed to copy sheet annotations: {}".format(ann_ex))
            
            # 5. Handle Copying Viewports
            if options.op_copy_vports.state:
                for vp in vp_details:
                    target_view_id = None
                    view_name = vp['view_name']
                    view_type = vp['view_type']
                    
                    if view_type == ViewType.DraftingView:
                        try:
                            target_view_id = copy_drafting_view_across_docs(
                                source_doc.GetElement(vp['view_id']),
                                dest_doc,
                                copy_options
                            )
                        except Exception as ex:
                            print("   ❌ Failed to copy drafting view '{}': {}".format(view_name, ex))
                            import traceback
                            traceback.print_exc()
                            
                    elif view_type == ViewType.Legend:
                        try:
                            target_view_id = copy_legend_view_across_docs(
                                source_doc.GetElement(vp['view_id']),
                                dest_doc,
                                copy_options
                            )
                        except Exception as ex:
                            print("   ❌ Failed to copy legend view '{}': {}".format(view_name, ex))
                            import traceback
                            traceback.print_exc()
                                
                    elif view_type in [ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan, ViewType.AreaPlan]:
                        try:
                            target_view_id = copy_plan_view_across_docs(
                                source_doc.GetElement(vp['view_id']),
                                dest_doc,
                                copy_options
                            )
                        except Exception as ex:
                            print("   ❌ Failed to copy plan view '{}': {}".format(view_name, ex))
                            import traceback
                            traceback.print_exc()
                                
                    else:
                        # For model views (Plan, Elevation, Section, 3D), look by name
                        existing_view = None
                        for v in FilteredElementCollector(dest_doc).OfClass(View):
                            if v.Name == view_name and v.ViewType == view_type:
                                existing_view = v
                                break
                                
                        if existing_view:
                            # Check if the view is already placed on a sheet in target doc
                            viewports_in_dest = FilteredElementCollector(dest_doc).OfClass(Viewport).ToElements()
                            placed_view_ids = {item.ViewId for item in viewports_in_dest}
                            
                            if existing_view.Id in placed_view_ids:
                                try:
                                    if existing_view.CanBeDuplicated():
                                        new_v_id = existing_view.Duplicate(ViewDuplicateOption.WithDetailing)
                                        duplicated_view = dest_doc.GetElement(new_v_id)
                                        # Generate unique name for duplicated view
                                        base_name = existing_view.Name
                                        new_name = base_name + " - Copy"
                                        name_counter = 1
                                        existing_names = {v.Name for v in FilteredElementCollector(dest_doc).OfClass(View)}
                                        while new_name in existing_names:
                                            new_name = "{} - Copy {}".format(base_name, name_counter)
                                            name_counter += 1
                                        duplicated_view.Name = new_name
                                        target_view_id = new_v_id
                                        print("   ℹ️ View '{}' was already placed. Created duplicate '{}' for placement.".format(base_name, new_name))
                                    else:
                                        print("   ❌ Model View '{}' is already placed on another sheet and cannot be duplicated.".format(view_name))
                                except Exception as dup_ex:
                                    print("   ❌ Failed to duplicate view '{}': {}".format(view_name, dup_ex))
                            else:
                                target_view_id = existing_view.Id
                        else:
                            print("   ❌ Model View '{}' ({}) was not found in target project. Skipping viewport placement.".format(view_name, view_type))
                            
                    # Place the viewport on the new sheet
                    if target_view_id:
                        try:
                            new_vp = Viewport.Create(dest_doc, new_sheet.Id, target_view_id, vp['center'])
                            
                            # Match Viewport Type (e.g. Title No Line, Show Title)
                            try:
                                src_vp_type = source_doc.GetElement(vp['type_id']) if vp['type_id'] else None
                                if src_vp_type:
                                    target_vp_type = None
                                    dest_vp_types = FilteredElementCollector(dest_doc).OfCategory(BuiltInCategory.OST_Viewports).WhereElementIsElementType().ToElements()
                                    for t in dest_vp_types:
                                        if t.Name == src_vp_type.Name:
                                            target_vp_type = t
                                            break
                                    if not target_vp_type:
                                        try:
                                            copied_t_ids = ElementTransformUtils.CopyElements(
                                                source_doc,
                                                List[ElementId]([src_vp_type.Id]),
                                                dest_doc,
                                                Transform.Identity,
                                                copy_options
                                            )
                                            target_vp_type = dest_doc.GetElement(copied_t_ids[0])
                                        except Exception as copy_type_ex:
                                            logger.debug("Failed to copy viewport type directly: {}".format(copy_type_ex))
                                    
                                    if target_vp_type:
                                        new_vp.ChangeTypeId(target_vp_type.Id)
                            except Exception as ex:
                                print("   ⚠️ Warning: Could not match/copy viewport type '{}': {}".format(src_vp_type.Name if 'src_vp_type' in locals() and src_vp_type else "Unknown", ex))
                                
                            # Set Detail Number
                            if vp['detail_number']:
                                try:
                                    new_vp.get_Parameter(BuiltInParameter.VIEWPORT_DETAIL_NUMBER).Set(vp['detail_number'])
                                except Exception as ex:
                                    logger.debug("Could not set detail number: {}".format(ex))
                                    
                            print("   ✅ Placed viewport for view: {}".format(view_name))
                        except Exception as ex:
                            print("   ❌ Failed to place viewport for view '{}': {}".format(view_name, ex))

            # 6. Handle Copying Schedules
            if options.op_copy_schedules.state:
                for sched in sched_details:
                    sched_name = sched['schedule_name']
                    # Find or copy schedule
                    target_sched_id = None
                    existing_sched = None
                    for s in FilteredElementCollector(dest_doc).OfClass(ViewSchedule):
                        if s.Name == sched_name and not s.IsTitleblockRevisionSchedule:
                            existing_sched = s
                            break
                            
                    if existing_sched:
                        target_sched_id = existing_sched.Id
                    else:
                        copied_s_ids = ElementTransformUtils.CopyElements(
                            source_doc,
                            List[ElementId]([sched['schedule_id']]),
                            dest_doc,
                            Transform.Identity,
                            copy_options
                        )
                        if copied_s_ids:
                            target_sched_id = copied_s_ids[0]
                            
                    if target_sched_id:
                        try:
                            ScheduleSheetInstance.Create(dest_doc, new_sheet.Id, target_sched_id, sched['point'])
                            print("   ✅ Placed schedule: {}".format(sched_name))
                        except Exception as ex:
                            print("   ❌ Failed to place schedule '{}': {}".format(sched_name, ex))
            
            t_dest.Commit()
            print("🎉 Sheet '{} - {}' copied successfully!".format(new_sheet.SheetNumber, new_sheet.Name))
            
        except Exception as ex:
            t_dest.RollBack()
            print("❌ Failed to copy sheet: {}".format(ex))
            raise ex
            
    finally:
        # 8. Roll back source temp transaction to restore source document viewports and numbers
        t_source.RollBack()


def main():
    # 1. Get all open project documents
    all_docs = [d for d in revit.doc.Application.Documents if not d.IsFamilyDocument]
    if not all_docs:
        forms.alert("No open project documents found.", title="Error")
        return
        
    if len(all_docs) < 2:
        forms.alert("Please open at least two project documents in the same Revit session.", title="Error")
        return
        
    # 2. Select Source Project
    doc_options = {d.Title: d for d in all_docs}
    source_title = forms.SelectFromList.show(
        sorted(doc_options.keys()),
        title="Select Source Project (เลือกโปรเจกต์ต้นฉบับ)",
        button_name="Next",
        multiselect=False
    )
    if not source_title:
        return
    source_doc = doc_options[source_title]
    
    # 3. Select Sheets to Copy from Source Project
    selected_sheets = forms.select_sheets(
        title="Select Sheets to Copy (เลือกแผ่นงานที่ต้องการคัดลอก)",
        button_name="Next",
        doc=source_doc,
        use_selection=(source_doc.Title == revit.doc.Title)
    )
    if not selected_sheets:
        return
        
    # 4. Select Target Project (excluding Source Project)
    target_docs = [d for d in all_docs if d.Title != source_doc.Title]
    target_options = {d.Title: d for d in target_docs}
    
    target_title = forms.SelectFromList.show(
        sorted(target_options.keys()),
        title="Select Target Project (เลือกโปรเจกต์ปลายทาง)",
        button_name="Next",
        multiselect=False
    )
    if not target_title:
        return
    dest_doc = target_options[target_title]
    
    # 5. Prompt Options UI
    op_set = OptionSet()
    options = forms.SelectFromList.show(
        [getattr(op_set, x) for x in dir(op_set) if x.startswith("op_")],
        title="Select Copy Options (เลือกการตั้งค่า)",
        button_name="Copy Now",
        multiselect=True
    )
    if options is None:
        return
        
    # Sync selected states
    for op in [getattr(op_set, x) for x in dir(op_set) if x.startswith("op_")]:
        if op.item in options:
            op.state = True
        else:
            op.state = False
            
    # 6. Execute sheet copying
    print("Starting sheet copy process...")
    print("Source Project: {}".format(source_doc.Title))
    print("Target Project: {}".format(dest_doc.Title))
    
    for sheet in selected_sheets:
        print("\nCopying sheet: {} - {}".format(sheet.SheetNumber, sheet.Name))
        try:
            copy_sheet_across_docs(sheet, dest_doc, op_set)
        except Exception as e:
            print("❌ Error copying sheet {} - {}: {}".format(sheet.SheetNumber, sheet.Name, e))
            
    print("\nCopy process completed.")


if __name__ == '__main__':
    main()
