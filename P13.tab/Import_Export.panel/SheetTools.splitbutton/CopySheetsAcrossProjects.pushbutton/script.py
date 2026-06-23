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
            print("   Drafting view '{}' is already placed on another sheet. Created new duplicate view '{}'.".format(src_view_name, unique_name))
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
            print("   Reusing existing unplaced drafting view '{}' and updating contents.".format(src_view_name))
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
        batch_sub = SubTransaction(dest_doc)
        batch_sub.Start()
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
            batch_sub.Commit()
        except Exception as e:
            batch_sub.RollBack()
            # Fallback: copy elements one-by-one if batch copy fails
            print("   Warning: Batch copy failed for drafting view '{}' detail elements: {}. Trying one-by-one...".format(src_view_name, e))
            copied_count = 0
            for el_id in elements_to_copy:
                single_sub = SubTransaction(dest_doc)
                single_sub.Start()
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
                    single_sub.Commit()
                except Exception as single_ex:
                    single_sub.RollBack()
                    logger.debug("Failed to copy element {}: {}".format(el_id, single_ex))
            print("   Finished copying detail elements one-by-one (Copied: {}/{})".format(copied_count, len(elements_to_copy)))

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
                    print("   Plan view '{}' is already placed on another sheet. Created duplicate view '{}'.".format(src_view_name, unique_name))
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
            print("   Reusing existing unplaced plan view '{}' and updating details.".format(src_view_name))
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
                    print("   Level '{}' did not exist in target project. Copied level successfully.".format(src_level_name))
                except Exception as lvl_ex:
                    raise Exception("Associated Level '{}' not found in target and could not be copied: {}".format(src_level_name, lvl_ex))

        if not target_level:
            raise Exception("No associated level found for plan view '{}'.".format(src_view_name))

        # 4. Create the view plan
        unique_name = get_unique_view_name(dest_doc, src_view_name)
        dest_view = ViewPlan.Create(dest_doc, dest_type.Id, target_level.Id)
        dest_view.Name = unique_name
        dest_view.Scale = src_view.Scale
        print("   Created new plan view '{}' on level '{}'.".format(unique_name, get_element_name(target_level)))

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
        batch_sub = SubTransaction(dest_view.Document)
        batch_sub.Start()
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
            batch_sub.Commit()
        except Exception as e:
            batch_sub.RollBack()
            # Fallback: copy elements one-by-one if batch copy fails
            print("   Warning: Batch copy failed for plan view '{}' annotations: {}. Trying one-by-one...".format(src_view_name, e))
            copied_count = 0
            for el_id in elements_to_copy:
                single_sub = SubTransaction(dest_view.Document)
                single_sub.Start()
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
                    single_sub.Commit()
                except Exception as single_ex:
                    single_sub.RollBack()
                    logger.debug("Failed to copy element {}: {}".format(el_id, single_ex))
            print("   Finished copying annotations one-by-one (Copied: {}/{})".format(copied_count, len(elements_to_copy)))

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




def get_titleblock_identity(titleblock_type):
    """Return a stable family/type identity for matching titleblocks."""
    family_name = ""
    type_name = get_element_name(titleblock_type)
    try:
        family_name = titleblock_type.FamilyName
    except Exception:
        try:
            family_name = get_element_name(titleblock_type.Family)
        except Exception:
            family_name = ""
    return family_name, type_name


def find_or_copy_titleblock_type(source_doc, dest_doc, source_type_id, copy_options):
    """Find a matching titleblock type in the destination or copy it from source."""
    if not source_type_id or source_type_id == ElementId.InvalidElementId:
        return ElementId.InvalidElementId

    src_type = source_doc.GetElement(source_type_id)
    if not src_type:
        return ElementId.InvalidElementId

    src_family_name, src_type_name = get_titleblock_identity(src_type)
    for dest_type in FilteredElementCollector(dest_doc).OfCategory(BuiltInCategory.OST_TitleBlocks).WhereElementIsElementType():
        dest_family_name, dest_type_name = get_titleblock_identity(dest_type)
        if dest_family_name == src_family_name and dest_type_name == src_type_name:
            return dest_type.Id

    copied_type_ids = ElementTransformUtils.CopyElements(
        source_doc,
        List[ElementId]([source_type_id]),
        dest_doc,
        Transform.Identity,
        copy_options
    )
    if copied_type_ids:
        return copied_type_ids[0]

    return ElementId.InvalidElementId


def get_source_titleblock(source_sheet):
    """Return the first titleblock instance on a sheet, if one exists."""
    source_doc = source_sheet.Document
    titleblocks = FilteredElementCollector(source_doc, source_sheet.Id).OfCategory(BuiltInCategory.OST_TitleBlocks).WhereElementIsNotElementType().ToElements()
    if titleblocks:
        return titleblocks[0]
    return None


def copy_parameter_value(source_param, target_param):
    """Copy one writable parameter value when storage types are compatible."""
    if not source_param or not target_param:
        return
    if target_param.IsReadOnly:
        return
    if source_param.StorageType != target_param.StorageType:
        return
    try:
        if source_param.StorageType == StorageType.String:
            target_param.Set(source_param.AsString() or "")
        elif source_param.StorageType == StorageType.Integer:
            target_param.Set(source_param.AsInteger())
        elif source_param.StorageType == StorageType.Double:
            target_param.Set(source_param.AsDouble())
        elif source_param.StorageType == StorageType.ElementId:
            target_param.Set(source_param.AsElementId())
    except Exception as ex:
        logger.debug("Failed to copy parameter '{}': {}".format(source_param.Definition.Name, ex))


def copy_matching_parameters(source_element, target_element, skip_names=None):
    """Copy matching writable parameters by definition name."""
    if not source_element or not target_element:
        return
    skip_names = skip_names or set()
    target_params = {}
    for target_param in target_element.Parameters:
        try:
            target_params[target_param.Definition.Name] = target_param
        except Exception:
            pass

    for source_param in source_element.Parameters:
        try:
            param_name = source_param.Definition.Name
        except Exception:
            continue
        if param_name in skip_names:
            continue
        if param_name in target_params:
            copy_parameter_value(source_param, target_params[param_name])


def copy_titleblock_instance_parameters(source_titleblock, new_sheet):
    """Copy instance parameters from source titleblock to the new sheet titleblock."""
    if not source_titleblock:
        return
    dest_doc = new_sheet.Document
    dest_titleblocks = FilteredElementCollector(dest_doc, new_sheet.Id).OfCategory(BuiltInCategory.OST_TitleBlocks).WhereElementIsNotElementType().ToElements()
    if dest_titleblocks:
        copy_matching_parameters(source_titleblock, dest_titleblocks[0])


def get_sheet_annotation_ids(source_sheet):
    """Collect sheet-owned annotation elements that are safe to copy sheet-to-sheet."""
    source_doc = source_sheet.Document
    element_ids = []
    for el in FilteredElementCollector(source_doc, source_sheet.Id).WhereElementIsNotElementType():
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
        element_ids.append(el.Id)
    return element_ids


def match_or_copy_viewport_type(source_doc, dest_doc, source_type_id, copy_options):
    """Find or copy the viewport type used by the source viewport."""
    if not source_type_id or source_type_id == ElementId.InvalidElementId:
        return None
    src_vp_type = source_doc.GetElement(source_type_id)
    if not src_vp_type:
        return None

    for target_type in FilteredElementCollector(dest_doc).OfCategory(BuiltInCategory.OST_Viewports).WhereElementIsElementType().ToElements():
        if target_type.Name == src_vp_type.Name:
            return target_type

    try:
        copied_type_ids = ElementTransformUtils.CopyElements(
            source_doc,
            List[ElementId]([src_vp_type.Id]),
            dest_doc,
            Transform.Identity,
            copy_options
        )
        if copied_type_ids:
            return dest_doc.GetElement(copied_type_ids[0])
    except Exception as ex:
        logger.debug("Failed to copy viewport type directly: {}".format(ex))
    return None


def resolve_target_view(source_doc, dest_doc, vp, copy_options):
    """Copy or find the destination view required for a viewport."""
    target_view_id = None
    view_name = vp['view_name']
    view_type = vp['view_type']

    if view_type == ViewType.DraftingView:
        return copy_drafting_view_across_docs(source_doc.GetElement(vp['view_id']), dest_doc, copy_options)

    if view_type == ViewType.Legend:
        return copy_legend_view_across_docs(source_doc.GetElement(vp['view_id']), dest_doc, copy_options)

    if view_type in [ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan, ViewType.AreaPlan]:
        return copy_plan_view_across_docs(source_doc.GetElement(vp['view_id']), dest_doc, copy_options)

    existing_view = None
    for view in FilteredElementCollector(dest_doc).OfClass(View):
        if get_element_name(view) == view_name and view.ViewType == view_type:
            existing_view = view
            break

    if not existing_view:
        print("   Model view '{}' ({}) was not found in target project. Skipping viewport placement.".format(view_name, view_type))
        return None

    viewports_in_dest = FilteredElementCollector(dest_doc).OfClass(Viewport).ToElements()
    placed_view_ids = {item.ViewId for item in viewports_in_dest}
    if existing_view.Id not in placed_view_ids:
        return existing_view.Id

    try:
        if existing_view.CanBeDuplicated():
            new_v_id = existing_view.Duplicate(ViewDuplicateOption.WithDetailing)
            duplicated_view = dest_doc.GetElement(new_v_id)
            base_name = get_element_name(existing_view)
            new_name = base_name + " - Copy"
            name_counter = 1
            existing_names = {get_element_name(v) for v in FilteredElementCollector(dest_doc).OfClass(View)}
            while new_name in existing_names:
                new_name = "{} - Copy {}".format(base_name, name_counter)
                name_counter += 1
            duplicated_view.Name = new_name
            print("   View '{}' was already placed. Created duplicate '{}' for placement.".format(base_name, new_name))
            target_view_id = new_v_id
        else:
            print("   Model view '{}' is already placed on another sheet and cannot be duplicated.".format(view_name))
    except Exception as ex:
        print("   Failed to duplicate view '{}': {}".format(view_name, ex))

    return target_view_id


def copy_sheet_across_docs(source_sheet, dest_doc, options):
    """Copy a sheet without modifying or rolling back the source document."""
    source_doc = source_sheet.Document
    copy_options = CopyPasteOptions()
    copy_options.SetDuplicateTypeNamesHandler(CopyUseDestination())

    existing_sheets = FilteredElementCollector(dest_doc).OfClass(ViewSheet).ToElements()
    existing_numbers = {sheet.SheetNumber for sheet in existing_sheets}

    original_number = source_sheet.SheetNumber
    target_number = original_number
    counter = 1
    while target_number in existing_numbers:
        target_number = "{}_COPY{}".format(original_number, counter)
        counter += 1

    viewport_ids = source_sheet.GetAllViewports()
    viewports = [source_doc.GetElement(vp_id) for vp_id in viewport_ids]
    vp_details = []
    for vp in viewports:
        view = source_doc.GetElement(vp.ViewId)
        detail_param = vp.get_Parameter(BuiltInParameter.VIEWPORT_DETAIL_NUMBER)
        vp_details.append({
            'view_id': vp.ViewId,
            'view_name': get_element_name(view),
            'view_type': view.ViewType,
            'center': vp.GetBoxCenter(),
            'type_id': vp.GetTypeId(),
            'detail_number': detail_param.AsString() if detail_param else None
        })

    sched_details = []
    for sched in FilteredElementCollector(source_doc, source_sheet.Id).OfClass(ScheduleSheetInstance):
        if sched.IsTitleblockRevisionSchedule:
            continue
        sched_view = source_doc.GetElement(sched.ScheduleId)
        sched_details.append({
            'schedule_id': sched.ScheduleId,
            'schedule_name': get_element_name(sched_view),
            'point': sched.Point
        })

    source_titleblock = get_source_titleblock(source_sheet)
    source_titleblock_type_id = source_titleblock.GetTypeId() if source_titleblock else ElementId.InvalidElementId

    transaction = Transaction(dest_doc, "Copy Sheet - {}".format(original_number))
    transaction.Start()
    try:
        target_titleblock_type_id = find_or_copy_titleblock_type(
            source_doc,
            dest_doc,
            source_titleblock_type_id,
            copy_options
        )
        new_sheet = ViewSheet.Create(dest_doc, target_titleblock_type_id)
        new_sheet.SheetNumber = target_number
        new_sheet.Name = source_sheet.Name
        copy_matching_parameters(source_sheet, new_sheet, set(["Sheet Number", "Sheet Name"]))
        copy_titleblock_instance_parameters(source_titleblock, new_sheet)

        if target_number != original_number:
            print("Warning: Sheet number '{}' already exists in target project. Renamed copy to '{}'.".format(original_number, target_number))

        annotation_ids = get_sheet_annotation_ids(source_sheet)
        if annotation_ids:
            anno_sub = SubTransaction(dest_doc)
            anno_sub.Start()
            try:
                copied_ids = ElementTransformUtils.CopyElements(
                    source_sheet,
                    List[ElementId](annotation_ids),
                    new_sheet,
                    None,
                    copy_options
                )
                for dest_id, source_id in zip(copied_ids, annotation_ids):
                    try:
                        new_sheet.SetElementOverrides(dest_id, source_sheet.GetElementOverrides(source_id))
                    except Exception:
                        pass
                print("   Copied {} annotation elements (Text, Lines, Detail Items).".format(len(copied_ids)))
                anno_sub.Commit()
            except Exception as ex:
                anno_sub.RollBack()
                print("   Warning: Failed to copy sheet annotations: {}".format(ex))

        if options.op_copy_vports.state:
            for vp in vp_details:
                view_name = vp['view_name']
                vp_subtrans = SubTransaction(dest_doc)
                vp_subtrans.Start()
                try:
                    target_view_id = resolve_target_view(source_doc, dest_doc, vp, copy_options)
                    if target_view_id:
                        new_vp = Viewport.Create(dest_doc, new_sheet.Id, target_view_id, vp['center'])
                        target_vp_type = match_or_copy_viewport_type(source_doc, dest_doc, vp['type_id'], copy_options)
                        if target_vp_type:
                            new_vp.ChangeTypeId(target_vp_type.Id)

                        if vp['detail_number']:
                            try:
                                new_vp.get_Parameter(BuiltInParameter.VIEWPORT_DETAIL_NUMBER).Set(vp['detail_number'])
                            except Exception as ex:
                                logger.debug("Could not set detail number: {}".format(ex))

                        print("   Placed viewport for view: {}".format(view_name))
                        vp_subtrans.Commit()
                    else:
                        vp_subtrans.RollBack()
                except Exception as ex:
                    vp_subtrans.RollBack()
                    print("   Failed to place viewport for view '{}': {}".format(view_name, ex))

        if options.op_copy_schedules.state:
            for sched in sched_details:
                sched_name = sched['schedule_name']
                sched_subtrans = SubTransaction(dest_doc)
                sched_subtrans.Start()
                try:
                    target_sched_id = None
                    existing_sched = None
                    for target_schedule in FilteredElementCollector(dest_doc).OfClass(ViewSchedule):
                        if get_element_name(target_schedule) == sched_name and not target_schedule.IsTitleblockRevisionSchedule:
                            existing_sched = target_schedule
                            break

                    if existing_sched:
                        target_sched_id = existing_sched.Id
                    else:
                        copied_schedule_ids = ElementTransformUtils.CopyElements(
                            source_doc,
                            List[ElementId]([sched['schedule_id']]),
                            dest_doc,
                            Transform.Identity,
                            copy_options
                        )
                        if copied_schedule_ids:
                            target_sched_id = copied_schedule_ids[0]

                    if target_sched_id:
                        ScheduleSheetInstance.Create(dest_doc, new_sheet.Id, target_sched_id, sched['point'])
                        print("   Placed schedule: {}".format(sched_name))
                        sched_subtrans.Commit()
                    else:
                        sched_subtrans.RollBack()
                except Exception as ex:
                    sched_subtrans.RollBack()
                    print("   Failed to place schedule '{}': {}".format(sched_name, ex))

        transaction.Commit()
        print("Sheet '{} - {}' copied successfully.".format(new_sheet.SheetNumber, new_sheet.Name))

    except Exception as ex:
        if transaction.GetStatus() == TransactionStatus.Started:
            transaction.RollBack()
        print("Failed to copy sheet: {}".format(ex))
        raise


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
        title="Select Source Project",
        button_name="Next",
        multiselect=False
    )
    if not source_title:
        return
    source_doc = doc_options[source_title]

    # 3. Select Sheets to Copy from Source Project
    selected_sheets = forms.select_sheets(
        title="Select Sheets to Copy",
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
        title="Select Target Project",
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
        title="Select Copy Options",
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
            print("Error copying sheet {} - {}: {}".format(sheet.SheetNumber, sheet.Name, e))

    print("\nCopy process completed.")


if __name__ == '__main__':
    main()
