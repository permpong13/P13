# -*- coding: utf-8 -*-
"""
pyRevit - Reload families from a selected folder (including subfolders)
with these rules:

- DO NOT open .RFA to read internal family name (no safe_read_family_name_from_rfa)
- Match by file name:  <FamilyName>.rfa  => FamilyName must already exist in the project
- Include subfolders (recursive)
- Show UI list (multi-select) to choose which families to reload
- Show progress as: current/total and percent
- Check existing families in the current Revit model for "corrupt/suspect" (best-effort):
    Try doc.EditFamily(family). If it fails => mark as SUSPECT/CORRUPT.
  If a family is SUSPECT/CORRUPT, the script will reload it even if not selected.
- Report what the script is doing during the process (live output + progress bar)

Important note:
Revit API does not provide a true "corrupt" flag. This script uses a practical best-effort check:
if EditFamily throws an exception, we treat it as SUSPECT/CORRUPT and force reload.
"""

import os
import clr

from pyrevit import forms, script

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    Transaction,
    FilteredElementCollector,
    Family,
    IFamilyLoadOptions,
    FamilySource,
)

# ------------------------------------------------------------
# Family load options: overwrite parameter values, choose file
# ------------------------------------------------------------
class FamLoadOpts(IFamilyLoadOptions):
    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        overwriteParameterValues.Value = True
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        source.Value = FamilySource.Family
        overwriteParameterValues.Value = True
        return True


# ------------------------------------------------------------
# UI item
# ------------------------------------------------------------
class ChoiceItem(object):
    def __init__(self, fam_name, fam_obj, path, status, status_note):
        self.fam_name = fam_name
        self.fam_obj = fam_obj
        self.path = path
        self.status = status
        self.status_note = status_note

    @property
    def name(self):
        # what shows in SelectFromList
        note = (" - " + self.status_note) if self.status_note else ""
        return u"[{status}] {fam}  |  {path}{note}".format(
            status=self.status, fam=self.fam_name, path=self.path, note=note
        )

    def __str__(self):
        return self.name


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def iter_rfa_files_recursive(root_folder):
    for dirpath, dirnames, filenames in os.walk(root_folder):
        for fn in filenames:
            if fn.lower().endswith(".rfa"):
                yield os.path.join(dirpath, fn)

def file_to_familyname(rfa_path):
    # NO opening rfa, just filename => family name
    return os.path.splitext(os.path.basename(rfa_path))[0]

def build_existing_family_map(project_doc):
    # case-insensitive lookup: lower-name -> (actual_name, family_obj)
    fams = FilteredElementCollector(project_doc).OfClass(Family).ToElements()
    m = {}
    for f in fams:
        if f and f.Name:
            m[f.Name.lower()] = (f.Name, f)
    return m

def check_family_suspect_corrupt(project_doc, fam_obj):
    """
    Best-effort check:
    Try EditFamily. If it throws, mark as SUSPECT/CORRUPT.
    If it opens, close it (no save) and mark OK.
    """
    try:
        fam_doc = project_doc.EditFamily(fam_obj)
        try:
            # If we can open it, that's a good sign.
            return ("OK", "")
        finally:
            # Close family doc without saving
            fam_doc.Close(False)
    except Exception as ex:
        msg = str(ex)
        # keep note short
        if len(msg) > 160:
            msg = msg[:160] + "..."
        return ("SUSPECT/CORRUPT", msg)


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
doc = __revit__.ActiveUIDocument.Document
output = script.get_output()

output.print_md("# Reload Families From Folder (Existing Only)")
output.print_md("- Match by filename: `<FamilyName>.rfa` must exist in the current model\n"
                "- Recursive subfolder scan\n"
                "- Best-effort corrupt check on *existing model families* (EditFamily)\n"
                "- SUSPECT/CORRUPT families will be reloaded automatically\n")

# Pick folder
root = forms.pick_folder(title="Select root folder containing .RFA files (includes subfolders)")
if not root:
    forms.alert("No folder selected.", exitscript=True)

output.print_md("**Selected folder:** `{}`".format(root))

# Existing families in model
output.print_md("\n## Step 1: Read existing families in current model")
existing_map = build_existing_family_map(doc)
output.print_md("- Found **{}** families in the model.".format(len(existing_map)))

# Scan folder
output.print_md("\n## Step 2: Scan folder (recursive) for .RFA")
rfa_paths = list(iter_rfa_files_recursive(root))
output.print_md("- Found **{}** `.rfa` files.".format(len(rfa_paths)))

if not rfa_paths:
    forms.alert("No .RFA files found (including subfolders).", exitscript=True)

# Build candidates (existing only) based on filename matching
output.print_md("\n## Step 3: Match files to existing families (by filename)")
candidates = []
skipped_new = []      # file not found in model
duplicates = {}       # fam_lower -> list(paths)

# First collect matches & duplicates
for fp in rfa_paths:
    fam_guess = file_to_familyname(fp)
    key = fam_guess.lower()
    if key in existing_map:
        duplicates.setdefault(key, []).append(fp)
    else:
        skipped_new.append((fp, fam_guess))

# Choose which file to use if duplicates: take the newest (by modified time)
chosen_paths = {}
for fam_lower, paths in duplicates.items():
    if len(paths) == 1:
        chosen_paths[fam_lower] = paths[0]
    else:
        newest = max(paths, key=lambda p: os.path.getmtime(p))
        chosen_paths[fam_lower] = newest

# Progress: corrupt/suspect check of matched families (best-effort)
output.print_md("\n## Step 4: Check matched families in the model (OK vs SUSPECT/CORRUPT)")
matched_keys = list(chosen_paths.keys())
total_check = len(matched_keys)

if total_check == 0:
    output.print_md("- No matched files. (All are new names not in the model)")
    forms.alert("No reloadable families found.\nAll .RFA filenames do not match existing family names.", exitscript=True)

with forms.ProgressBar(
    title="Checking families in model: {value}/{max_value} ({percent}%)",
    cancellable=True,
    step=1,
    max_value=total_check
) as pb:
    for i, fam_lower in enumerate(matched_keys, start=1):
        if pb.cancelled:
            forms.alert("Cancelled during model family checking.", exitscript=True)

        percent = int(round((float(i) / float(total_check)) * 100.0))
        pb.title = "Checking families in model: {}/{} ({}%)".format(i, total_check, percent)
        pb.update_progress(i, total_check)

        actual_name, fam_obj = existing_map[fam_lower]
        fp = chosen_paths[fam_lower]

        status, note = check_family_suspect_corrupt(doc, fam_obj)
        candidates.append(ChoiceItem(actual_name, fam_obj, fp, status, note))

        # Live reporting
        if status == "OK":
            output.print_md("- ✅ **{}** OK | `{}`".format(actual_name, fp))
        else:
            output.print_md("- ⚠️ **{}** SUSPECT/CORRUPT | `{}`".format(actual_name, fp))
            output.print_md("  - Note: `{}`".format(note))

# Summary
output.print_md("\n## Summary")
output.print_md("- Reload candidates (existing in model): **{}**".format(len(candidates)))
output.print_md("- Skipped (filename not found in model): **{}**".format(len(skipped_new)))

# UI list select
output.print_md("\n## Step 5: Select which families to reload")
output.print_md("Tip: SUSPECT/CORRUPT families will be reloaded automatically even if not selected.")

selected = forms.SelectFromList.show(
    sorted(candidates, key=lambda x: (0 if x.status != "OK" else 1, x.fam_name.lower())),
    multiselect=True,
    title="Select families to reload (Existing only; SUSPECT/CORRUPT will auto-reload)",
    button_name="Reload"
)

# Determine forced reload set (suspect/corrupt)
forced = [c for c in candidates if c.status != "OK"]

# Build final queue: union(selected, forced)
final_queue = []
seen = set()

def add_item(it):
    k = it.fam_name.lower()
    if k not in seen:
        seen.add(k)
        final_queue.append(it)

if selected:
    for it in selected:
        add_item(it)
for it in forced:
    add_item(it)

if not final_queue:
    forms.alert("Nothing to reload (no selection and no SUSPECT/CORRUPT families).", exitscript=True)

output.print_md("\n## Step 6: Reload families (transaction)")
output.print_md("- Selected: **{}**".format(len(selected) if selected else 0))
output.print_md("- Forced (SUSPECT/CORRUPT): **{}**".format(len(forced)))
output.print_md("- Total to reload: **{}**".format(len(final_queue)))

opts = FamLoadOpts()
loaded = []
failed = []

total_reload = len(final_queue)

with forms.ProgressBar(
    title="Reloading: {value}/{max_value} ({percent}%)",
    cancellable=True,
    step=1,
    max_value=total_reload
) as pb:

    t = Transaction(doc, "Reload families from folder (existing only)")
    t.Start()

    for i, item in enumerate(final_queue, start=1):
        if pb.cancelled:
            t.RollBack()
            forms.alert("Cancelled during reload. Transaction rolled back.", exitscript=True)

        percent = int(round((float(i) / float(total_reload)) * 100.0))
        pb.title = "Reloading: {}/{} ({}%)".format(i, total_reload, percent)
        pb.update_progress(i, total_reload)

        forced_tag = " (FORCED)" if item.status != "OK" else ""
        output.print_md("\n### Reloading: **{}**{}".format(item.fam_name, forced_tag))
        output.print_md("- Source: `{}`".format(item.path))
        output.print_md("- Status before reload: **{}**".format(item.status))

        try:
            fam_ref = clr.Reference[Family]()
            ok = doc.LoadFamily(item.path, opts, fam_ref)
            if ok:
                loaded.append(item)
                output.print_md("- ✅ Reload OK (overwrite enabled)")
            else:
                failed.append((item, "LoadFamily returned False"))
                output.print_md("- ❌ Reload failed (LoadFamily returned False)")
        except Exception as ex:
            failed.append((item, str(ex)))
            output.print_md("- ❌ Exception: `{}`".format(ex))

    t.Commit()

# Final report
output.print_md("\n# Result")
output.print_md("- ✅ Reloaded: **{}**".format(len(loaded)))
output.print_md("- ❌ Failed: **{}**".format(len(failed)))

if failed:
    output.print_md("\n## Failed details")
    for item, msg in failed:
        output.print_md("- **{}** | `{}` | `{}`".format(item.fam_name, item.path, msg))

forms.alert("Done.\nReloaded: {}\nFailed: {}".format(len(loaded), len(failed)))