# -*- coding: utf-8 -*-
"""Calculate wall elevations and configure the P13 wall tag for the project."""

import os
import tempfile

from pyrevit import revit, DB, script, forms


__title__ = "Wall Top\nCal"

doc = revit.doc
app = doc.Application
output = script.get_output()

WALL_TAG_FILE_NAME = "Wall Tag by P13.rfa"
WALL_TAG_FAMILY_NAME = "Wall Tag by P13"
WALL_TAG_TYPE_NAME = "Wall Tag"
WALL_TAG_CONFIG_KEY = "wall_tag_family_path"
WALL_TAG_CONFIG_NAME = "WallCal"


def _element_id_value(element_id):
    """Return a stable numeric value for ElementId across supported Revit builds."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def _is_wall_tag_family(family):
    """Match the supplied family by its Revit family name."""
    if not family:
        return False
    try:
        family_name = family.Name.strip().lower()
        target_name = WALL_TAG_FAMILY_NAME.lower()
        return family_name == target_name or family_name.endswith(target_name)
    except Exception:
        return False


def _find_wall_tag_family(document):
    for family in DB.FilteredElementCollector(document).OfClass(DB.Family):
        if _is_wall_tag_family(family):
            return family
    return None


def _get_symbol_name(symbol):
    """Read a type name safely across Revit/IronPython wrapper variants."""
    try:
        name = getattr(symbol, "Name", None)
        if name:
            return str(name)
    except Exception:
        pass

    try:
        name_parameter = symbol.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
        if name_parameter and name_parameter.HasValue:
            name = name_parameter.AsString()
            if name:
                return str(name)
    except Exception:
        pass

    return "Unnamed Wall Tag"


def _find_wall_tag_symbol(document, family):
    """Find the preferred wall tag type, with a safe first-type fallback."""
    if not family:
        return None

    fallback = None
    for symbol_id in family.GetFamilySymbolIds():
        symbol = document.GetElement(symbol_id)
        if not symbol or not symbol.Category:
            continue
        try:
            if symbol.Category.BuiltInCategory != DB.BuiltInCategory.OST_WallTags:
                continue
        except Exception:
            continue

        if fallback is None:
            fallback = symbol
        if _get_symbol_name(symbol).strip().lower() == WALL_TAG_TYPE_NAME.lower():
            return symbol

    return fallback


def _get_wall_tag_file_path():
    """Resolve the bundled RFA, using a remembered picker path only if needed."""
    script_dir = os.path.dirname(__file__)
    bundled_path = os.path.join(script_dir, WALL_TAG_FILE_NAME)
    if os.path.isfile(bundled_path):
        return bundled_path

    config = script.get_config(WALL_TAG_CONFIG_NAME)
    saved_path = config.get_option(WALL_TAG_CONFIG_KEY, "")
    if saved_path and os.path.isfile(saved_path):
        return saved_path

    picked_path = forms.pick_file(
        file_ext="rfa",
        title="Select {}".format(WALL_TAG_FILE_NAME)
    )
    if not picked_path:
        return None

    config.set_option(WALL_TAG_CONFIG_KEY, picked_path)
    script.save_config()
    return picked_path


def ensure_p13_wall_tag_default(document):
    """Load the P13 wall tag and make its preferred type the project default.

    This function is intentionally independent from wall calculation so the tag
    is configured even when the model contains no walls.
    """
    family = _find_wall_tag_family(document)
    family_path = None

    if not family:
        family_path = _get_wall_tag_file_path()
        if not family_path:
            return "missing_file", None

        load_transaction = DB.Transaction(document, "Load P13 Wall Tag Family")
        load_transaction.Start()
        try:
            loaded = document.LoadFamily(family_path)
            load_transaction.Commit()
        except Exception as error:
            if load_transaction.HasStarted() and not load_transaction.HasEnded():
                load_transaction.RollBack()
            return "load_failed: {}".format(error), None

        family = _find_wall_tag_family(document)
        if not family and not loaded:
            return "load_failed: Revit did not load the family", None

    symbol = _find_wall_tag_symbol(document, family)
    if not symbol:
        return "type_not_found", None

    wall_tag_category_id = DB.ElementId(DB.BuiltInCategory.OST_WallTags)
    try:
        current_default_id = document.GetDefaultFamilyTypeId(wall_tag_category_id)
        if (_element_id_value(current_default_id) ==
                _element_id_value(symbol.Id)):
            return "already_default", symbol
    except Exception as error:
        return "default_check_failed: {}".format(error), symbol

    default_transaction = DB.Transaction(document, "Set P13 Wall Tag as Project Default")
    default_transaction.Start()
    try:
        document.SetDefaultFamilyTypeId(wall_tag_category_id, symbol.Id)
        default_transaction.Commit()
        return "set_default", symbol
    except Exception as error:
        if default_transaction.HasStarted() and not default_transaction.HasEnded():
            default_transaction.RollBack()
        return "default_set_failed: {}".format(error), symbol


def setup_parameter(document, application, param_name, param_type, all_cat_names):
    """Find or create a shared parameter and bind it to the requested categories."""
    existing_def = None
    existing_binding = None

    iterator = document.ParameterBindings.ForwardIterator()
    while iterator.MoveNext():
        if iterator.Key.Name == param_name:
            existing_def = iterator.Key
            existing_binding = iterator.Current
            break

    if existing_def and existing_binding:
        cat_set = existing_binding.Categories
        needs_update = False
        for category_name in all_cat_names:
            try:
                built_in_category = getattr(DB.BuiltInCategory, category_name)
                category = document.Settings.Categories.get_Item(built_in_category)
                if (category and category.AllowsBoundParameters and
                        not cat_set.Contains(category)):
                    cat_set.Insert(category)
                    needs_update = True
            except Exception:
                continue

        if needs_update:
            rebind_transaction = DB.Transaction(
                document, "Update {} Categories".format(param_name)
            )
            rebind_transaction.Start()
            try:
                new_binding = application.Create.NewInstanceBinding(cat_set)
                document.ParameterBindings.ReInsert(existing_def, new_binding)
                rebind_transaction.Commit()
                return "updated"
            except Exception:
                if (rebind_transaction.HasStarted() and
                        not rebind_transaction.HasEnded()):
                    rebind_transaction.RollBack()
                return "exists"
        return "exists"

    shared_parameter_file = application.OpenSharedParameterFile()
    original_shared_parameter_path = application.SharedParametersFilename

    if not shared_parameter_file:
        temporary_shared_parameter_path = os.path.join(
            tempfile.gettempdir(), "Auto_SharedParams_Revit.txt"
        )
        if not os.path.exists(temporary_shared_parameter_path):
            with open(temporary_shared_parameter_path, "w") as shared_file:
                shared_file.write("")
        try:
            application.SharedParametersFilename = temporary_shared_parameter_path
            shared_parameter_file = application.OpenSharedParameterFile()
        except Exception:
            shared_parameter_file = None

    if not shared_parameter_file:
        return "sp_error"

    target_definition = None
    for group in shared_parameter_file.Groups:
        for definition in group.Definitions:
            if definition.Name == param_name:
                target_definition = definition
                break
        if target_definition:
            break

    if not target_definition:
        group = shared_parameter_file.Groups.get_Item("Data")
        if not group:
            group = shared_parameter_file.Groups.Create("Data")
        try:
            if param_type == "Text":
                options = DB.ExternalDefinitionCreationOptions(
                    param_name, DB.SpecTypeId.String.Text
                )
            else:
                options = DB.ExternalDefinitionCreationOptions(
                    param_name, DB.SpecTypeId.Length
                )
            target_definition = group.Definitions.Create(options)
        except AttributeError:
            if param_type == "Text":
                options = DB.ExternalDefinitionCreationOptions(
                    param_name, DB.ParameterType.Text
                )
            else:
                options = DB.ExternalDefinitionCreationOptions(
                    param_name, DB.ParameterType.Length
                )
            target_definition = group.Definitions.Create(options)

    try:
        application.SharedParametersFilename = original_shared_parameter_path
    except Exception:
        pass

    if not target_definition:
        return "def_not_found"

    category_set = application.Create.NewCategorySet()
    for category_name in all_cat_names:
        try:
            built_in_category = getattr(DB.BuiltInCategory, category_name)
            category = document.Settings.Categories.get_Item(built_in_category)
            if category and category.AllowsBoundParameters:
                category_set.Insert(category)
        except Exception:
            continue

    if category_set.IsEmpty:
        return "no_categories"

    binding = application.Create.NewInstanceBinding(category_set)
    parameter_transaction = DB.Transaction(
        document, "Setup Parameter: {}".format(param_name)
    )
    parameter_transaction.Start()
    try:
        try:
            document.ParameterBindings.Insert(
                target_definition, binding, DB.GroupTypeId.Data
            )
        except AttributeError:
            document.ParameterBindings.Insert(
                target_definition, binding, DB.BuiltInParameterGroup.PG_DATA
            )
        parameter_transaction.Commit()
        return "created"
    except Exception:
        if (parameter_transaction.HasStarted() and
                not parameter_transaction.HasEnded()):
            parameter_transaction.RollBack()
        return "bind_error"


def is_element_in_group(element):
    try:
        group_id = getattr(element, "GroupId", DB.ElementId.InvalidElementId)
        return group_id and group_id != DB.ElementId.InvalidElementId
    except Exception:
        return False


def allow_vary_between_groups(document, parameter_names):
    vary_status = dict((name, False) for name in parameter_names)
    iterator = document.ParameterBindings.ForwardIterator()
    while iterator.MoveNext():
        definition = iterator.Key
        if (definition.Name in vary_status and
                isinstance(definition, DB.InternalDefinition)):
            try:
                if not definition.VariesAcrossGroups:
                    definition.SetAllowVaryBetweenGroups(document, True)
                vary_status[definition.Name] = definition.VariesAcrossGroups
            except Exception:
                vary_status[definition.Name] = getattr(
                    definition, "VariesAcrossGroups", False
                )
    return vary_status


output.print_md("# **Wall Parameter Update**")

tag_status, tag_symbol = ensure_p13_wall_tag_default(doc)
if tag_status == "set_default":
    output.print_md(
        "- Loaded **{}** and set type **{}** as the project wall tag default.".format(
            WALL_TAG_FAMILY_NAME, _get_symbol_name(tag_symbol)
        )
    )
elif tag_status == "already_default":
    output.print_md(
        "- **{} : {}** is already the project wall tag default.".format(
            WALL_TAG_FAMILY_NAME, _get_symbol_name(tag_symbol)
        )
    )
else:
    output.print_md(
        "- **Wall tag setup warning:** {}. Wall calculation will continue.".format(
            tag_status
        )
    )


output.print_md("### **Checking and Preparing Wall Parameters**")
wall_categories = ["OST_Walls"]

status_base = setup_parameter(doc, app, "Base_Level", "Text", wall_categories)
status_bottom = setup_parameter(
    doc, app, "Level_Bottom_of_Column", "Length", wall_categories
)
status_top = setup_parameter(doc, app, "Top of Wall", "Length", wall_categories)

if status_base == "created":
    output.print_md("- Created **Base_Level** (Text).")
elif status_base in ["exists", "updated"]:
    output.print_md("- **Base_Level** is ready for use.")

if status_bottom == "created":
    output.print_md("- Created **Level_Bottom_of_Column**.")
if status_top == "created":
    output.print_md("- Created **Top of Wall**.")
output.print_md("---")


walls = (
    DB.FilteredElementCollector(doc)
    .OfCategory(DB.BuiltInCategory.OST_Walls)
    .WhereElementIsNotElementType()
    .ToElements()
)

if not walls:
    forms.alert("No walls were found in the model.", exitscript=True)

output.print_md("### **Found {} wall(s)**".format(len(walls)))


wall_transaction = DB.Transaction(doc, "Set Wall Elevation Parameters")
wall_transaction.Start()

group_vary_status = allow_vary_between_groups(
    doc, ["Base_Level", "Level_Bottom_of_Column", "Top of Wall"]
)

success_count = 0
error_log = []
skipped_group_count = 0
total_elements = len(walls)
is_cancelled = False

with forms.ProgressBar(
        title="Calculating wall parameters... ({value} of {max_value})",
        cancellable=True) as progress_bar:
    for index, wall in enumerate(walls):
        if progress_bar.cancelled:
            is_cancelled = True
            break

        try:
            in_group = is_element_in_group(wall)
            if in_group:
                skipped_group_count += 1
                continue

            base_level_parameter = wall.get_Parameter(
                DB.BuiltInParameter.WALL_BASE_CONSTRAINT
            )
            if not base_level_parameter:
                continue

            base_level_id = base_level_parameter.AsElementId()
            if base_level_id == DB.ElementId.InvalidElementId:
                continue

            base_level = doc.GetElement(base_level_id)
            if not base_level:
                continue
            base_elevation = base_level.Elevation

            base_offset_parameter = wall.get_Parameter(
                DB.BuiltInParameter.WALL_BASE_OFFSET
            )
            base_offset = (
                base_offset_parameter.AsDouble()
                if base_offset_parameter else 0.0
            )

            height_parameter = wall.LookupParameter("Unconnected Height")
            if not height_parameter:
                height_parameter = wall.get_Parameter(
                    DB.BuiltInParameter.WALL_USER_HEIGHT_PARAM
                )
            if not height_parameter or not height_parameter.HasValue:
                continue

            unconnected_height = height_parameter.AsDouble()
            top_of_wall_value = (
                base_elevation + base_offset + unconnected_height
            )
            bottom_value = base_elevation + base_offset

            base_parameter = wall.LookupParameter("Base_Level")
            if base_parameter and not base_parameter.IsReadOnly:
                if in_group and not group_vary_status.get("Base_Level", False):
                    skipped_group_count += 1
                elif base_parameter.StorageType == DB.StorageType.String:
                    base_parameter.Set("{:.3f}".format(base_elevation * 0.3048))
                elif base_parameter.StorageType == DB.StorageType.Double:
                    base_parameter.Set(base_elevation)

            bottom_parameter = wall.LookupParameter("Level_Bottom_of_Column")
            if bottom_parameter and not bottom_parameter.IsReadOnly:
                if (in_group and
                        not group_vary_status.get("Level_Bottom_of_Column", False)):
                    skipped_group_count += 1
                else:
                    bottom_parameter.Set(bottom_value)

            top_parameter = wall.LookupParameter("Top of Wall")
            if top_parameter and not top_parameter.IsReadOnly:
                if in_group and not group_vary_status.get("Top of Wall", False):
                    skipped_group_count += 1
                else:
                    top_parameter.Set(top_of_wall_value)
                    success_count += 1
            elif not top_parameter:
                error_log.append(
                    "Wall ID {}: Parameter 'Top of Wall' was not found".format(
                        _element_id_value(wall.Id)
                    )
                )

        except Exception as error:
            error_log.append(
                "Wall ID {}: {}".format(_element_id_value(wall.Id), error)
            )

        progress_bar.update_progress(index + 1, total_elements)

wall_transaction.Commit()


output.print_md("---")
output.print_md("### **Result**")
if is_cancelled:
    output.print_md(
        "- **Cancelled by user.** Changes completed before cancellation were saved."
    )

output.print_md(
    "- Updated **{}** wall(s) out of **{}**.".format(
        success_count, total_elements
    )
)

if skipped_group_count > 0:
    output.print_md(
        "- Skipped {} grouped-wall operation(s) to avoid forcing an Ungroup workflow.".format(
            skipped_group_count
        )
    )

if error_log:
    output.print_md("### **Warnings**")
    for message in list(set(error_log))[:15]:
        output.print_md("- " + message)

output.print_md("**Finished - wall parameters are up to date.**")
