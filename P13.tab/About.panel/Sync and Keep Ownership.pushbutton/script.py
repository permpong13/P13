# -*- coding: utf-8 -*-
from __future__ import print_function

from Autodesk.Revit.DB import (
    RelinquishOptions,
    SynchronizeWithCentralOptions,
    TransactWithCentralOptions,
)
from pyrevit import forms, revit


__title__ = "Sync and\nKeep Ownership"
__author__ = "P13"


def show_error(message):
    forms.alert(message, title="Sync and Keep Ownership", warn_icon=True)


def sync_and_keep_ownership():
    doc = revit.doc

    if doc is None:
        show_error("No active Revit document is available.")
        return

    if not doc.IsWorkshared:
        show_error("The active model is not workshared.")
        return

    if doc.IsModifiable:
        show_error(
            "Revit is currently editing the model. Finish the active command "
            "or transaction, then run the sync again."
        )
        return

    transact_options = TransactWithCentralOptions()
    sync_options = SynchronizeWithCentralOptions()
    relinquish_options = RelinquishOptions(False)

    try:
        relinquish_options.CheckedOutElements = False
        relinquish_options.FamilyWorksets = False
        relinquish_options.StandardWorksets = False
        relinquish_options.UserWorksets = False
        relinquish_options.ViewWorksets = False

        sync_options.SetRelinquishOptions(relinquish_options)
        sync_options.SaveLocalBefore = True
        sync_options.SaveLocalAfter = True
        sync_options.Compact = False
        sync_options.Comment = "Synchronized with P13 Sync and Keep Ownership."

        doc.SynchronizeWithCentral(transact_options, sync_options)
    except Exception as exc:
        show_error("Synchronize with Central failed.\n\n{}".format(exc))
    finally:
        relinquish_options.Dispose()
        sync_options.Dispose()
        transact_options.Dispose()


if __name__ == "__main__":
    sync_and_keep_ownership()
