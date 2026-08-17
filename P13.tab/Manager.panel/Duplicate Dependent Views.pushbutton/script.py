# -*- coding: utf-8 -*-
"""Create multiple Revit dependent views from one or more primary views."""
from __future__ import print_function

import traceback

from pyrevit import DB, forms, revit, script


doc = revit.doc
uidoc = revit.uidoc
logger = script.get_logger()

DEPENDENT_OPTION = DB.ViewDuplicateOption.AsDependent
INVALID_ID_VALUE = -1
MAX_DEPENDENTS_PER_VIEW = 100


def element_id_value(element_id):
    """Return an ElementId value across Revit API versions."""
    try:
        return element_id.Value
    except Exception:
        return element_id.IntegerValue


def is_primary_view(view):
    """Return True when the view is not already a dependent view."""
    try:
        return element_id_value(view.GetPrimaryViewId()) == INVALID_ID_VALUE
    except Exception:
        return False


def can_create_dependent(view):
    """Check the exact Revit duplication mode before opening a transaction."""
    try:
        if view.IsTemplate or not is_primary_view(view):
            return False

        view_type = view.ViewType.ToString()
        if view_type in ("Internal", "ProjectBrowser", "SystemBrowser"):
            return False

        return view.CanViewBeDuplicated(DEPENDENT_OPTION)
    except Exception:
        return False


class ViewChoice(object):
    """Display record for the multi-select view picker."""

    def __init__(self, view):
        self.view_id = view.Id
        self.view_type = view.ViewType.ToString()
        self.view_name = view.Name
        self.display_name = "{} | {} [ID {}]".format(
            self.view_type,
            self.view_name,
            element_id_value(view.Id),
        )

    def __str__(self):
        return self.display_name


def collect_eligible_views():
    """Collect eligible primary views in stable category-grouped order."""
    choices = []
    views = DB.FilteredElementCollector(doc).OfClass(DB.View).WhereElementIsNotElementType()
    for view in views:
        if not can_create_dependent(view):
            continue
        try:
            choices.append(ViewChoice(view))
        except Exception:
            continue

    # Keep the picker grouped by ViewType rather than using a global sequence.
    choices.sort(key=lambda item: (
        item.view_type.lower(),
        item.view_name.lower(),
        element_id_value(item.view_id),
    ))
    return choices


def get_selected_eligible_views(eligible_by_id):
    """Use View elements selected in the Project Browser when available."""
    selected = []
    for element_id in uidoc.Selection.GetElementIds():
        view = doc.GetElement(element_id)
        if not view or element_id_value(view.Id) not in eligible_by_id:
            continue
        selected.append(view)

    selected.sort(key=lambda view: (
        view.ViewType.ToString().lower(),
        view.Name.lower(),
        element_id_value(view.Id),
    ))
    return selected


def choose_source_views(eligible_choices):
    """Prefer Project Browser selection and fall back to a multi-select picker."""
    eligible_by_id = {
        element_id_value(choice.view_id): choice for choice in eligible_choices
    }
    selected_views = get_selected_eligible_views(eligible_by_id)
    if selected_views:
        return selected_views

    selected_choices = forms.SelectFromList.show(
        eligible_choices,
        title="Select Primary Views",
        prompt="Select one or more primary views for dependent view creation.",
        name_attr="display_name",
        multiselect=True,
        button_name="Continue",
    )
    if not selected_choices:
        return []

    selected_views = []
    for choice in selected_choices:
        view = doc.GetElement(choice.view_id)
        if view and can_create_dependent(view):
            selected_views.append(view)
    return selected_views


def ask_dependent_count():
    """Ask for the number of dependents created per selected primary view."""
    value = forms.ask_for_string(
        default="3",
        prompt="Number of dependent views to create for each selected primary view:",
        title="Batch Dependent Views",
    )
    if value is None:
        return None

    try:
        count = int(str(value).strip())
    except Exception:
        forms.alert(
            "Enter a whole number between 1 and {}.".format(MAX_DEPENDENTS_PER_VIEW),
            title="Invalid Dependent View Count",
        )
        return None

    if count < 1 or count > MAX_DEPENDENTS_PER_VIEW:
        forms.alert(
            "Enter a whole number between 1 and {}.".format(MAX_DEPENDENTS_PER_VIEW),
            title="Invalid Dependent View Count",
        )
        return None
    return count


def create_dependent_views(source_views, count):
    """Create all dependents atomically in one Revit transaction."""
    transaction = DB.Transaction(doc, "P13 Batch Create Dependent Views")
    created_ids = []
    try:
        transaction.Start()
        for source_view in source_views:
            # Re-check the document state immediately before mutation.
            if not source_view.IsValidObject or not can_create_dependent(source_view):
                raise RuntimeError(
                    "View '{}' is no longer eligible for dependent duplication.".format(
                        source_view.Name
                    )
                )

            for _ in range(count):
                created_ids.append(source_view.Duplicate(DEPENDENT_OPTION))

        transaction.Commit()
        return created_ids
    except Exception:
        try:
            if transaction.GetStatus() == DB.TransactionStatus.Started:
                transaction.RollBack()
        except Exception:
            pass
        raise


def show_result(source_views, count, created_ids):
    """Show a concise result and the generated Revit names."""
    created_names = []
    for element_id in created_ids:
        created_view = doc.GetElement(element_id)
        if created_view:
            created_names.append(created_view.Name)

    message = (
        "Created {} dependent view(s) from {} primary view(s).\n\n"
        "Revit assigned the dependent view names automatically."
    ).format(len(created_ids), len(source_views))
    if created_names:
        preview = created_names[:12]
        message += "\n\nCreated views:\n- " + "\n- ".join(preview)
        if len(created_names) > len(preview):
            message += "\n- ... and {} more".format(len(created_names) - len(preview))
    forms.alert(message, title="Dependent Views Created")


def main():
    eligible_choices = collect_eligible_views()
    if not eligible_choices:
        forms.alert(
            "No primary views can be duplicated as dependent views in this project.",
            title="Batch Dependent Views",
        )
        return

    source_views = choose_source_views(eligible_choices)
    if not source_views:
        return

    count = ask_dependent_count()
    if count is None:
        return

    total_count = len(source_views) * count
    source_names = [view.Name for view in source_views[:8]]
    summary = (
        "Create {} dependent view(s) from {} selected primary view(s)?\n\n"
        "Each primary view will receive {} new dependent view(s)."
    ).format(total_count, len(source_views), count)
    if source_names:
        summary += "\n\nPrimary views:\n- " + "\n- ".join(source_names)
        if len(source_views) > len(source_names):
            summary += "\n- ... and {} more".format(len(source_views) - len(source_names))

    if not forms.alert(summary, title="Confirm Dependent View Creation", yes=True, no=True):
        return

    try:
        created_ids = create_dependent_views(source_views, count)
    except Exception as error:
        logger.error(traceback.format_exc())
        forms.alert(
            "The batch operation failed. No partial changes were kept.\n\n{}".format(error),
            title="Dependent View Creation Failed",
        )
        return

    try:
        show_result(source_views, count, created_ids)
    except Exception as error:
        logger.error(traceback.format_exc())
        forms.alert(
            "The dependent views were created, but the result dialog could not be displayed.\n\n{}".format(error),
            title="Dependent Views Created",
        )


if __name__ == "__main__":
    main()
