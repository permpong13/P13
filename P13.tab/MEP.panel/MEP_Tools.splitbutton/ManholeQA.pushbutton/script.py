# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import sys
import traceback

import clr
import System.Collections.Generic as SCG

from pyrevit import forms, revit, script


__title__ = "MH Connection QA"
__doc__ = "Run the bundled Home.dyn graph, then open the Manhole QA review UI."
__author__ = "OHM"


doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

COMMAND_DIR = os.path.dirname(__file__)
DYNAMO_GRAPH_NAME = "Home.dyn"


def get_dynamo_graph_path():
    dyn_path = os.path.join(COMMAND_DIR, DYNAMO_GRAPH_NAME)
    if not os.path.exists(dyn_path):
        forms.alert(
            "Dynamo graph was not found.\n\nPath:\n{}".format(dyn_path),
            title="Manhole QA",
            exitscript=True,
        )
    return dyn_path


def run_dynamo_graph(dyn_path):
    clr.AddReference("DynamoRevitDS")
    from Dynamo.Applications import DynamoRevit, DynamoRevitCommandData, JournalKeys

    journal_data = SCG.Dictionary[str, str]()
    journal_data[JournalKeys.ShowUiKey] = "false"
    journal_data[JournalKeys.AutomationModeKey] = "true"
    journal_data[JournalKeys.DynPathKey] = dyn_path
    journal_data[JournalKeys.DynPathExecuteKey] = "true"
    journal_data[JournalKeys.ForceManualRunKey] = "true"
    journal_data[JournalKeys.ModelShutDownKey] = "true"

    cmd_data = DynamoRevitCommandData()
    cmd_data.Application = __revit__
    cmd_data.JournalData = journal_data

    return DynamoRevit().ExecuteCommand(cmd_data)


def launch_qa_form():
    if COMMAND_DIR not in sys.path:
        sys.path.append(COMMAND_DIR)

    from ui.form import ManholeQAForm

    ManholeQAForm(doc, uidoc)


def main():
    output.print_md("# Manhole QA")

    dyn_path = get_dynamo_graph_path()
    output.print_md("Running Dynamo graph:")
    output.print_md("`{}`".format(dyn_path))

    try:
        run_dynamo_graph(dyn_path)
        output.print_md("Dynamo execution finished.")
    except Exception as exc:
        output.print_md("Dynamo execution failed: `{}`".format(exc))
        output.print_md("```text\n{}\n```".format(traceback.format_exc()))
        forms.alert(
            "Dynamo execution failed. The QA review UI will open so you can continue with the existing workflow.\n\n{}".format(exc),
            title="Manhole QA",
            warn_icon=True,
        )

    output.print_md("Opening QA review UI.")
    launch_qa_form()


if __name__ == "__main__":
    main()
