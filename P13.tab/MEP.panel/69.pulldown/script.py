# -*- coding: utf-8 -*-
from pyrevit import revit, DB, forms

doc = revit.doc
uidoc = revit.uidoc

# Select elements to rename/modify
elem_ids = uidoc.Selection.GetElementIds()

if not elem_ids:
    forms.alert("Please select one or more elements before running this script.", title="No Elements Selected")
else:
    comments_value = forms.ask_for_string(
        default="New Comment Value", 
        title="Set Comments Parameter", 
        prompt="Enter comment value:"
    )
    if comments_value:
        # Start a transaction to modify the Revit database
        with revit.Transaction("Set Comments Parameter"):
            count = 0
            for elem_id in elem_ids:
                elem = doc.GetElement(elem_id)
                param = elem.LookupParameter("Comments")
                if param and not param.IsReadOnly:
                    param.Set(comments_value)
                    count += 1
            
            forms.alert("Successfully updated Comments for {} elements!".format(count), title="Transaction Complete")
