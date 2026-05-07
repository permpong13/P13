# -*- coding: utf-8 -*-
from pyrevit import revit, DB, forms, script
from System.Collections.Generic import List

# 1. Get Active Document and Application
doc = revit.doc
app = doc.Application

# 2. Collect all open documents except the active one and linked models
open_docs = [d for d in app.Documents if not d.IsLinked and d.Title != doc.Title]

if not open_docs:
    forms.alert("No other Revit models are currently open. Please open the source model first.", exitscript=True)

# 3. Create a wrapper for Document selection
class DocOption(forms.TemplateListItem):
    @property
    def name(self):
        return self.item.Title

doc_options = [DocOption(d) for d in open_docs]

# Prompt user to select the source document
source_doc = forms.SelectFromList.show(
    doc_options,
    title="Select Source Model",
    button_name="Select Document",
    multiselect=False
)

if not source_doc:
    script.exit()

# 4. Collect Schedules from the selected Source Document
schedules = DB.FilteredElementCollector(source_doc)\
              .OfClass(DB.ViewSchedule)\
              .ToElements()

# Filter out view templates and internal schedules
# แก้ไขจุดนี้: กรอง Template และตารางที่ซ่อนอยู่ของระบบ (มักมีชื่อขึ้นต้นด้วย < )
valid_schedules = [s for s in schedules if not s.IsTemplate and not s.Name.startswith("<")]

if not valid_schedules:
    forms.alert("No valid schedules found in the selected model.", exitscript=True)

# 5. Create a wrapper for Schedule selection
class ScheduleOption(forms.TemplateListItem):
    @property
    def name(self):
        return self.item.Name

schedule_options = [ScheduleOption(s) for s in valid_schedules]

# Prompt user to select which schedules to import
selected_schedules = forms.SelectFromList.show(
    schedule_options,
    title="Select Schedules to Import",
    button_name="Import Schedules",
    multiselect=True
)

if not selected_schedules:
    script.exit()

# 6. Prepare ElementIds for copying
schedule_ids = [s.Id for s in selected_schedules]
id_list = List[DB.ElementId](schedule_ids)
copy_options = DB.CopyPasteOptions()

# 7. Execute the import within a Transaction in the Active Document
with revit.Transaction("Import Schedules"):
    try:
        # Copy elements from source_doc to active doc
        copied_ids = DB.ElementTransformUtils.CopyElements(
            source_doc,
            id_list,
            doc,
            DB.Transform.Identity,
            copy_options
        )
        
        forms.alert("Successfully imported {} schedule(s).".format(len(copied_ids)), title="Success")
        
    except Exception as e:
        forms.alert("An error occurred during import:\n{}".format(e), title="Error")