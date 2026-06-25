# -*- coding: utf-8 -*-
from __future__ import print_function

__title__ = "Get\nID"
__doc__ = "Get Element IDs of currently selected elements and copy them to clipboard."
__author__ = "P13"

import os
import sys
import clr
import System

clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from System.Windows import Clipboard
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType
from pyrevit import revit, DB, forms, script

doc = revit.doc
uidoc = revit.uidoc

def get_id_value(element_id):
    if hasattr(element_id, "Value"):
        return element_id.Value
    return element_id.IntegerValue

class SelectionRow(object):
    def __init__(self, id_str, category, name):
        self.Id = id_str
        self.Category = category
        self.Name = name

class GetIDWindow(forms.WPFWindow):
    def __init__(self, xaml_file_path):
        forms.WPFWindow.__init__(self, xaml_file_path)
        self.rows = []
        self.raw_id_string = ""
        
        # Wire Event Handlers
        if hasattr(self, 'btn_pick'): self.btn_pick.Click += self.on_pick_elements
        if hasattr(self, 'btn_copy_ids'): self.btn_copy_ids.Click += self.on_copy_ids
        if hasattr(self, 'btn_copy_tsv'): self.btn_copy_tsv.Click += self.on_copy_tsv
        
        self.load_selection()
        
    def load_selection(self):
        try:
            sel_ids = uidoc.Selection.GetElementIds()
            if not sel_ids or sel_ids.Count == 0:
                self.lbl_status.Text = "No active selection. Click 'Pick on Screen' to select."
                self.lbl_status.Foreground = System.Windows.Media.Brushes.Orange
                
                # Clear grid and text
                self.txt_raw_ids.Text = ""
                self.grid_selected.ItemsSource = None
                self.grid_selected.Items.Refresh()
                return
                
            id_list = []
            self.rows = []
            for eid in sel_ids:
                el = doc.GetElement(eid)
                if el:
                    # Get display ID
                    id_val = get_id_value(eid)
                    id_list.append(str(id_val))
                    
                    # Get category
                    cat_name = "-"
                    if el.Category:
                        cat_name = el.Category.Name
                    elif hasattr(el, "StyleType"):
                        cat_name = str(el.StyleType)
                        
                    # Get Name
                    name = el.Name
                    
                    self.rows.append(SelectionRow(str(id_val), cat_name, name))
            
            # Format raw ID string
            self.raw_id_string = ", ".join(id_list)
            self.txt_raw_ids.Text = self.raw_id_string
            
            # Set items source
            self.grid_selected.ItemsSource = self.rows
            self.grid_selected.Items.Refresh()
            
            # Auto copy raw IDs to clipboard
            Clipboard.SetText(self.raw_id_string)
            self.lbl_status.Text = "Successfully copied {} IDs to clipboard!".format(len(id_list))
            self.lbl_status.Foreground = System.Windows.Media.Brushes.LightGreen
            
        except Exception as e:
            self.lbl_status.Text = "Error: {}".format(e)
            self.lbl_status.Foreground = System.Windows.Media.Brushes.Red

    def on_pick_elements(self, sender, args):
        self.Hide() # Hides the WPF dialog temporarily
        try:
            # Let the user select multiple elements in Revit
            picked_refs = uidoc.Selection.PickObjects(ObjectType.Element, "Select elements to get IDs, then click Finish in the Options Bar.")
            
            if picked_refs:
                sel_ids = [ref.ElementId for ref in picked_refs]
                id_list = []
                self.rows = []
                for eid in sel_ids:
                    el = doc.GetElement(eid)
                    if el:
                        id_val = get_id_value(eid)
                        id_list.append(str(id_val))
                        
                        cat_name = "-"
                        if el.Category:
                            cat_name = el.Category.Name
                        elif hasattr(el, "StyleType"):
                            cat_name = str(el.StyleType)
                            
                        name = el.Name
                        self.rows.append(SelectionRow(str(id_val), cat_name, name))
                
                # Format raw ID string
                self.raw_id_string = ", ".join(id_list)
                self.txt_raw_ids.Text = self.raw_id_string
                
                # Update Grid
                self.grid_selected.ItemsSource = self.rows
                self.grid_selected.Items.Refresh()
                
                # Auto copy to clipboard
                Clipboard.SetText(self.raw_id_string)
                self.lbl_status.Text = "Successfully copied {} picked IDs to clipboard!".format(len(id_list))
                self.lbl_status.Foreground = System.Windows.Media.Brushes.LightGreen
        except Exception as e:
            # PickObjects raises an OperationCanceledException (via COM/dotnet wrapping) if user cancels/presses Esc
            err_str = str(e)
            if "OperationCanceledException" in err_str or "canceled" in err_str.lower() or "cancel" in err_str.lower():
                self.lbl_status.Text = "Selection canceled."
                self.lbl_status.Foreground = System.Windows.Media.Brushes.Orange
            else:
                self.lbl_status.Text = "Error: {}".format(e)
                self.lbl_status.Foreground = System.Windows.Media.Brushes.Red
        finally:
            self.ShowDialog() # Restores/Shows the dialog modal again

    def on_copy_ids(self, sender, args):
        if self.raw_id_string:
            try:
                Clipboard.SetText(self.raw_id_string)
                forms.alert("Raw IDs copied to clipboard: {}".format(self.raw_id_string), title="Copied")
            except Exception as e:
                forms.alert("Failed to copy: {}".format(e))
        else:
            forms.alert("No IDs to copy.", title="Empty")

    def on_copy_tsv(self, sender, args):
        if not self.rows:
            forms.alert("No items to copy.", title="Empty")
            return
            
        lines = ["Element ID\tCategory\tName"]
        for r in self.rows:
            lines.append("{}\t{}\t{}".format(r.Id, r.Category, r.Name))
            
        text = "\r\n".join(lines)
        try:
            Clipboard.SetText(text)
            forms.alert("Copied detailed element info to clipboard.", title="Copied")
        except Exception as e:
            forms.alert("Failed to copy: {}".format(e))

def main():
    if not doc:
        forms.alert("No open Revit document found.", exitscript=True)
        
    xaml_path = script.get_bundle_file('ui.xaml')
    window = GetIDWindow(xaml_path)
    window.ShowDialog()

if __name__ == '__main__':
    main()
