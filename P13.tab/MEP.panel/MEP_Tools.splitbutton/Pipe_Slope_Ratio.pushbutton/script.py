# -*- coding: utf-8 -*-
"""Write a taggable 1:xxx slope ratio to selected pipes or pipes in the active view."""

import math
import os
import tempfile

from pyrevit import DB, forms, revit, script

PARAMETER_NAME = "Slope_Ratio"
TARGET_CATEGORIES = ["OST_PipeCurves", "OST_Floors"]
doc = revit.doc
app = doc.Application
output = script.get_output()


def get_or_create_shared_parameter(document, application, parameter_name):
    """Ensure a text instance parameter exists and is bound to pipe curves."""
    iterator = document.ParameterBindings.ForwardIterator()
    while iterator.MoveNext():
        definition = iterator.Key
        if definition.Name == parameter_name:
            binding = iterator.Current
            category_set = binding.Categories
            missing_category = False
            for category_name in TARGET_CATEGORIES:
                try:
                    category = document.Settings.Categories.get_Item(
                        getattr(DB.BuiltInCategory, category_name))
                    if category and category.AllowsBoundParameters and not category_set.Contains(category):
                        category_set.Insert(category)
                        missing_category = True
                except Exception:
                    continue

            # Reinsert the binding in Data so an existing parameter is also
            # corrected when it was previously placed in another group.
            transaction_name = "Update Slope Ratio Parameter Group"
            if missing_category:
                transaction_name = "Update Slope Ratio Categories and Group"
            transaction = DB.Transaction(document, transaction_name)
            transaction.Start()
            try:
                new_binding = application.Create.NewInstanceBinding(category_set)
                try:
                    document.ParameterBindings.ReInsert(
                        definition, new_binding, DB.GroupTypeId.Data)
                except AttributeError:
                    document.ParameterBindings.ReInsert(
                        definition, new_binding, DB.BuiltInParameterGroup.PG_DATA)
                transaction.Commit()
            except Exception:
                transaction.RollBack()
                raise
            return definition

    original_shared_file = application.SharedParametersFilename
    try:
        shared_file = application.OpenSharedParameterFile()
        if not shared_file:
            temporary_shared_file = os.path.join(
                tempfile.gettempdir(), "P13_Slope_Ratio_SharedParameters.txt")
            if not os.path.exists(temporary_shared_file) or os.path.getsize(temporary_shared_file) == 0:
                with open(temporary_shared_file, "w") as handle:
                    handle.write(
                        "# This is a Revit shared parameter file.\n"
                        "# Do not edit manually.\n"
                        "*META VERSION MINVERSION\n"
                        "META 2 1\n"
                        "*GROUP ID NAME\n"
                        "*PARAM GUID NAME DATATYPE DATACATEGORY GROUP VISIBLE DESCRIPTION USERMODIFIABLE\n")
            application.SharedParametersFilename = temporary_shared_file
            shared_file = application.OpenSharedParameterFile()
        if not shared_file:
            raise Exception("Revit could not open a shared parameter file.")

        target_definition = None
        for group in shared_file.Groups:
            for definition in group.Definitions:
                if definition.Name == parameter_name:
                    target_definition = definition
                    break
            if target_definition:
                break
        if not target_definition:
            group = shared_file.Groups.get_Item("P13")
            if not group:
                group = shared_file.Groups.Create("P13")
            try:
                options = DB.ExternalDefinitionCreationOptions(
                    parameter_name, DB.SpecTypeId.String.Text)
            except AttributeError:
                options = DB.ExternalDefinitionCreationOptions(
                    parameter_name, DB.ParameterType.Text)
            target_definition = group.Definitions.Create(options)

        category_set = application.Create.NewCategorySet()
        for category_name in TARGET_CATEGORIES:
            category = document.Settings.Categories.get_Item(
                getattr(DB.BuiltInCategory, category_name))
            if category and category.AllowsBoundParameters:
                category_set.Insert(category)
        binding = application.Create.NewInstanceBinding(category_set)
        transaction = DB.Transaction(document, "Create Slope Ratio Parameter")
        transaction.Start()
        try:
            try:
                document.ParameterBindings.Insert(
                    target_definition, binding, DB.GroupTypeId.Data)
            except AttributeError:
                document.ParameterBindings.Insert(
                    target_definition, binding, DB.BuiltInParameterGroup.PG_DATA)
            transaction.Commit()
        except Exception:
            transaction.RollBack()
            raise
        return target_definition
    finally:
        if original_shared_file and application.SharedParametersFilename != original_shared_file:
            try:
                application.SharedParametersFilename = original_shared_file
            except Exception:
                pass


def collect_pipes():
    selected_elements = [element for element in revit.get_selection()
                         if isinstance(element, (DB.Plumbing.Pipe, DB.Floor))]
    if selected_elements:
        return selected_elements, "Selection"

    pipes = DB.FilteredElementCollector(doc, doc.ActiveView.Id) \
        .OfCategory(DB.BuiltInCategory.OST_PipeCurves) \
        .WhereElementIsNotElementType() \
        .ToElements()
    floors = DB.FilteredElementCollector(doc, doc.ActiveView.Id) \
        .OfCategory(DB.BuiltInCategory.OST_Floors) \
        .WhereElementIsNotElementType() \
        .ToElements()
    elements = []
    elements.extend(pipes)
    elements.extend(floors)
    return ([element for element in elements
             if isinstance(element, (DB.Plumbing.Pipe, DB.Floor))], "Active View")


def read_slope(pipe):
    if isinstance(pipe, DB.Plumbing.Pipe):
        parameter = pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPE_SLOPE)
        if not parameter or not parameter.HasValue:
            return None
        try:
            return abs(parameter.AsDouble())
        except Exception:
            return None

    # Floors do not expose the same RBS slope parameter as pipes. Read the
    # normal of the highest upward planar face and derive rise/run from it.
    options = DB.Options()
    options.IncludeNonVisibleObjects = True
    geometry = pipe.get_Geometry(options)
    best_slope = [None]

    def inspect_geometry(geometry_objects):
        if not geometry_objects:
            return
        for geometry_object in geometry_objects:
            if isinstance(geometry_object, DB.Solid):
                for face in geometry_object.Faces:
                    if not isinstance(face, DB.PlanarFace):
                        continue
                    normal = face.FaceNormal
                    if normal.Z <= 0.01:
                        continue
                    horizontal_normal = math.sqrt(normal.X * normal.X + normal.Y * normal.Y)
                    slope = horizontal_normal / abs(normal.Z)
                    if best_slope[0] is None or slope > best_slope[0]:
                        best_slope[0] = slope
            elif isinstance(geometry_object, DB.GeometryInstance):
                inspect_geometry(geometry_object.GetInstanceGeometry())

    inspect_geometry(geometry)
    return best_slope[0]


def format_ratio(slope):
    if slope is None or slope <= 0.0000001:
        return "Flat"
    ratio = int(math.floor((1.0 / slope) + 0.5))
    return "1:{}".format(max(1, ratio))


def display_name(pipe):
    try:
        if isinstance(pipe, DB.Plumbing.Pipe):
            parameter = pipe.LookupParameter("Size")
            return parameter.AsValueString() if parameter else "Pipe"
        type_parameter = pipe.get_Parameter(DB.BuiltInParameter.ELEM_TYPE_PARAM)
        return type_parameter.AsValueString() if type_parameter else "Floor"
    except Exception:
        return "Floor" if isinstance(pipe, DB.Floor) else "Pipe"


def element_category(pipe):
    return "Pipe" if isinstance(pipe, DB.Plumbing.Pipe) else "Floor"


def element_id_value(element_id):
    """Return an ElementId value across Revit API generations."""
    value = getattr(element_id, "Value", None)
    if value is not None:
        return value
    return getattr(element_id, "IntegerValue", str(element_id))


def main():
    pipes, scope = collect_pipes()
    if not pipes:
        forms.alert("No pipes were found in the selection or active view.", title="Pipe Slope Ratio")
        return
    try:
        get_or_create_shared_parameter(doc, app, PARAMETER_NAME)
    except Exception as error:
        forms.alert(
            "Unable to create or bind the shared parameter '{}'.\n\n{}".format(
                PARAMETER_NAME, error), title="Pipe Slope Ratio")
        return

    updated = 0
    flat_count = 0
    missing_slope = 0
    read_only = 0
    skipped_groups = 0
    rows = []
    transaction = DB.Transaction(doc, "Write Pipe Slope Ratios")
    transaction.Start()
    try:
        for pipe in pipes:
            if pipe.GroupId != DB.ElementId.InvalidElementId:
                skipped_groups += 1
                continue
            slope = read_slope(pipe)
            if slope is None:
                missing_slope += 1
                continue
            ratio_text = format_ratio(slope)
            if ratio_text == "Flat":
                flat_count += 1
            parameter = pipe.LookupParameter(PARAMETER_NAME)
            if not parameter:
                continue
            if parameter.IsReadOnly:
                read_only += 1
                continue
            parameter.Set(ratio_text)
            updated += 1
            rows.append((element_id_value(pipe.Id), element_category(pipe),
                         display_name(pipe), slope * 100.0, ratio_text))
        transaction.Commit()
    except Exception:
        transaction.RollBack()
        raise

    output.print_md("## Pipe Slope Ratio")
    output.print_md("- Scope: **{}**".format(scope))
    output.print_md("- Taggable parameter: **{}**".format(PARAMETER_NAME))
    output.print_md("- Updated: **{}**".format(updated))
    if flat_count:
        output.print_md("- Flat pipes: **{}** (`Flat`)".format(flat_count))
    if missing_slope:
        output.print_md("- Missing slope: **{}**".format(missing_slope))
    if read_only:
        output.print_md("- Read-only parameters: **{}**".format(read_only))
    if skipped_groups:
        output.print_md("- Skipped grouped pipes: **{}**".format(skipped_groups))
    if rows:
        output.print_md("\n| Element ID | Category | Type / Size | Slope (%) | Tag value |")
        output.print_md("| --- | --- | --- | ---: | --- |")
        for row in rows[:50]:
            output.print_md("| {} | {} | {} | {:.4f} | `{}` |".format(*row))
        if len(rows) > 50:
            output.print_md("\n_Showing the first 50 results._")
    if updated:
        output.print_md(
            "\nAdd the shared parameter **{}** to the pipe tag family to display the value.".format(
                PARAMETER_NAME))


try:
    main()
except Exception as error:
    forms.alert("Pipe slope ratio failed.\n\n{}".format(error), title="Pipe Slope Ratio")
