# -*- coding: utf-8 -*-
# ui/form.py — FIXED VERSION

import clr, math, os, csv, traceback

import clr, math, os, csv, traceback
clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")
clr.AddReference("PresentationFramework")
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Windows import Window, Visibility, TextDecorations, TextDecorationCollection
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, Color
from System.Collections.ObjectModel import ObservableCollection
from System.IO import File
import System

CLR_OK      = SolidColorBrush(Color.FromRgb(46,  125, 50))
CLR_CHANGED = SolidColorBrush(Color.FromRgb(230, 81,  0))
CLR_WARN    = SolidColorBrush(Color.FromRgb(183, 28,  28))
CLR_MUTED   = SolidColorBrush(Color.FromRgb(180, 180, 180))

def scan_manholes(doc, active_view_id, progress_callback=None):
    def eid(element_id):
        return getattr(element_id, "Value", getattr(element_id, "IntegerValue", str(element_id)))
    def get_workset_name(element):
        try: return doc.GetWorksetTable().GetWorkset(element.WorksetId).Name
        except: return "No Workset"

    try:
        view_equipments = FilteredElementCollector(doc, active_view_id)\
            .OfCategory(BuiltInCategory.OST_ElectricalEquipment)\
            .WhereElementIsNotElementType().ToElements()
        view_conduits = FilteredElementCollector(doc, active_view_id)\
            .OfCategory(BuiltInCategory.OST_Conduit)\
            .WhereElementIsNotElementType().ToElements()
        view_fittings = FilteredElementCollector(doc, active_view_id)\
            .OfCategory(BuiltInCategory.OST_ConduitFitting)\
            .WhereElementIsNotElementType().ToElements()
    except Exception as e:
        raise Exception("ไม่สามารถดึงข้อมูลใน View นี้ได้: " + str(e))

    # ✅ FIX 1: ใช้ is not None แทน hasattr
    valid_manholes = [m for m in view_equipments 
                      if m.LookupParameter("CNT_Connection 1") 
                      and m.Location is not None]
    total_manholes = len(valid_manholes)
    if total_manholes == 0: return []

    results = []
    for idx, manhole in enumerate(valid_manholes):
        try:
            transform = manhole.GetTransform()
            origin    = transform.Origin

            opt = Options()
            opt.ComputeReferences = True
            opt.DetailLevel = ViewDetailLevel.Fine
            geom = manhole.get_Geometry(opt)
            floor_candidates = {}

            def find_floors(geo):
                for obj in geo:
                    if isinstance(obj, Solid) and obj.Volume > 0:
                        for face in obj.Faces:
                            n = face.ComputeNormal(UV(0.5, 0.5))
                            if n.IsAlmostEqualTo(XYZ.BasisZ):
                                fz = face.Evaluate(UV(0.5, 0.5)).Z
                                if fz < (origin.Z - 0.5):
                                    k = round(fz, 4)
                                    floor_candidates[k] = floor_candidates.get(k, 0) + face.Area
                    elif isinstance(obj, GeometryInstance):
                        find_floors(obj.GetInstanceGeometry())

            find_floors(geom)
            base_z = max(floor_candidates, key=floor_candidates.get) if floor_candidates else manhole.get_BoundingBox(None).Min.Z

            main_s  = [[],[],[],[]]
            extra_s = [[],[],[],[]]
            has_fitting = [False, False, False, False]

            # ✅ FIX 2: ใช้ vector จากบ่อไป conduit แทน direction ของท่อ
            for conduit in view_conduits:
                if not hasattr(conduit.Location, "Curve"): continue
                curve = conduit.Location.Curve
                p0, p1 = curve.GetEndPoint(0), curve.GetEndPoint(1)
                dist0, dist1 = p0.DistanceTo(origin), p1.DistanceTo(origin)
                if min(dist0, dist1) > 10.0: continue

                closest_pt = p0 if dist0 < dist1 else p1
                vec_to_pt  = XYZ(closest_pt.X - origin.X, 
                                 closest_pt.Y - origin.Y, 
                                 closest_pt.Z - origin.Z)
                local_vec  = transform.Inverse.OfVector(vec_to_pt)

                is_extra = False
                c_type = doc.GetElement(conduit.GetTypeId())
                type_name = c_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString().lower() if c_type else ""
                if "without duct" in type_name or "without duct" in conduit.Name.lower():
                    is_extra = True

                # ✅ FIX 3: ใช้ atan2 แทน abs logic
                angle_deg = math.degrees(math.atan2(local_vec.Y, local_vec.X))
                if   angle_deg >= 135 or angle_deg <= -135: side = 0
                elif -135 < angle_deg <= -45:               side = 1
                elif  -45 < angle_deg <=  45:               side = 2
                else:                                        side = 3

                depth = closest_pt.Z - base_z
                if is_extra: extra_s[side].append(depth)
                else:        main_s[side].append(depth)

            # Fitting scan
            for fitting in view_fittings:
                if not fitting.Location: continue
                loc = fitting.Location
                pt = loc.Point if hasattr(loc, "Point") else \
                     loc.Curve.Evaluate(0.5, True) if hasattr(loc, "Curve") and loc.Curve else None
                if not pt or pt.DistanceTo(origin) > 10.0: continue

                vec = XYZ(pt.X - origin.X, pt.Y - origin.Y, pt.Z - origin.Z)
                lv  = transform.Inverse.OfVector(vec)
                angle_deg = math.degrees(math.atan2(lv.Y, lv.X))
                if   angle_deg >= 135 or angle_deg <= -135: has_fitting[0] = True
                elif -135 < angle_deg <= -45:               has_fitting[1] = True
                elif  -45 < angle_deg <=  45:               has_fitting[2] = True
                else:                                        has_fitting[3] = True

            def get_offset(z_list, base, has_fit):
                if not z_list: return None if has_fit else 0.0
                return min(z_list) - base

            def to_mm(val_ft):
                return round(val_ft * 304.8) if val_ft is not None else None

            new_main  = [to_mm(get_offset(main_s[i],  base_z, has_fitting[i])) for i in range(4)]
            new_extra = [to_mm(get_offset(extra_s[i], base_z, has_fitting[i])) for i in range(4)]

            def read_mm(name):
                p = manhole.LookupParameter(name)
                return round(p.AsDouble() * 304.8) if p else 0

            old_main  = [read_mm("CNT_Connection {}".format(i)) for i in range(1,5)]
            old_extra = [read_mm("CNT_Connection {} Extra".format(i)) for i in range(1,5)]

            final_main  = [new_main[i]  if new_main[i]  is not None else old_main[i]  for i in range(4)]
            final_extra = [new_extra[i] if new_extra[i] is not None else old_extra[i] for i in range(4)]

            has_change = (old_main != final_main or old_extra != final_extra)
            has_warn   = any(final_main[i] == 0 and old_main[i] > 0 for i in range(4))

            status = "warn" if has_warn else "changed" if has_change else "ok"

            results.append({
                "id": str(eid(manhole.Id)), "element": manhole,
                "ws": get_workset_name(manhole), "status": status,
                "old_main": old_main, "new_main": final_main,
                "old_extra": old_extra, "new_extra": final_extra,
            })
        except Exception as ex:
            print("Skipped manhole: " + str(ex))

        if progress_callback: progress_callback(idx + 1, total_manholes)

    return results

def commit_manholes(doc, records):
    TransactionManager.Instance.EnsureInTransaction(doc)
    for r in records:
        m = r["element"]
        for i in range(4):
            for suffix in ["", " Extra"]:
                p = m.LookupParameter("CNT_Connection {}{}".format(i+1, suffix))
                if not p or p.IsReadOnly: continue
                val_ft = r["new_{}".format("main" if not suffix else "extra")][i] / 304.8
                if abs(p.AsDouble() - val_ft) > 0.001: p.Set(val_ft)
    TransactionManager.Instance.TransactionTaskDone()

class ManholeRow(object):
    def __init__(self, record):
        self._record = record
        self._checked = False
    @property
    def checked(self): return self._checked
    @checked.setter
    def checked(self, v): self._checked = v
    @property
    def id(self): return self._record["id"]
    @property
    def ws(self): return self._record["ws"]
    @property
    def status(self): return self._record["status"]
    @property
    def status_label(self): return {"ok":"ไม่เปลี่ยน","changed":"เปลี่ยน","warn":"ตรวจสอบ"}.get(self._record["status"],"?")
    @property
    def element(self): return self._record["element"]

    def _v(self, n): return str(n) if n else "—"
    def _c(self, n, o):
        if n==0 and o>0: return CLR_WARN
        if n!=o: return CLR_CHANGED
        if n==0: return CLR_MUTED
        return CLR_OK

    @property
    def c1m(self): return self._v(self._record["new_main"][0])
    @property
    def c2m(self): return self._v(self._record["new_main"][1])
    @property
    def c3m(self): return self._v(self._record["new_main"][2])
    @property
    def c4m(self): return self._v(self._record["new_main"][3])
    @property
    def c1m_color(self): return self._c(self._record["new_main"][0], self._record["old_main"][0])
    @property
    def c2m_color(self): return self._c(self._record["new_main"][1], self._record["old_main"][1])
    @property
    def c3m_color(self): return self._c(self._record["new_main"][2], self._record["old_main"][2])
    @property
    def c4m_color(self): return self._c(self._record["new_main"][3], self._record["old_main"][3])
    @property
    def e1(self): return self._v(self._record["new_extra"][0])
    @property
    def e2(self): return self._v(self._record["new_extra"][1])
    @property
    def e3(self): return self._v(self._record["new_extra"][2])
    @property
    def e4(self): return self._v(self._record["new_extra"][3])
    @property
    def e1_color(self): return self._c(self._record["new_extra"][0], self._record["old_extra"][0])
    @property
    def e2_color(self): return self._c(self._record["new_extra"][1], self._record["old_extra"][1])
    @property
    def e3_color(self): return self._c(self._record["new_extra"][2], self._record["old_extra"][2])
    @property
    def e4_color(self): return self._c(self._record["new_extra"][3], self._record["old_extra"][3])

class DetailRow:
    def __init__(self, label, old, new):
        self.label = label
        self.old_val = "{} mm".format(old) if old is not None else "—"
        self.new_val = "{} mm".format(new) if new is not None else "—"
        changed = (old != new)
        self.val_color = CLR_WARN if (new==0 and old>0) else CLR_CHANGED if changed else CLR_OK
        self.val_weight = "SemiBold" if changed else "Normal"
        self.strike = TextDecorations.Strikethrough if changed else TextDecorationCollection()
        self.arrow_vis = Visibility.Visible if changed else Visibility.Collapsed

class ManholeQAForm(Window):
    def __init__(self, doc, uidoc):
        self.doc, self.uidoc, self.records, self.rows = doc, uidoc, [], ObservableCollection[ManholeRow]()
        xaml_path = os.path.join(os.path.dirname(__file__), "form.xaml")
        win = XamlReader.Parse(File.ReadAllText(xaml_path))

        self.grid = win.FindName("ListRecords")
        self.btn_scan, self.btn_commit, self.btn_export = win.FindName("BtnScan"), win.FindName("BtnCommit"), win.FindName("BtnExport")
        self.cb_dry, self.cb_ws, self.cb_status = win.FindName("ChkDryRun"), win.FindName("CbWorkset"), win.FindName("CbStatus")
        self.lbl_status, self.pb = win.FindName("LblStatus"), win.FindName("ScanProgress")
        self.stat_total, self.stat_ok, self.stat_ch, self.stat_warn = win.FindName("StatTotal"), win.FindName("StatOk"), win.FindName("StatChanged"), win.FindName("StatWarn")
        self.det_main, self.det_extra = win.FindName("DetailMain"), win.FindName("DetailExtra")
        self.grid.ItemsSource = self.rows

        self.btn_scan.Click += self.on_scan
        self.btn_commit.Click += self.on_commit
        self.btn_export.Click += self.on_export
        self.cb_status.SelectionChanged += self.on_filter
        self.cb_ws.SelectionChanged += self.on_filter
        self.grid.SelectionChanged += self.on_select_row

        try:
            for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset):
                self.cb_ws.Items.Add(ws.Name)
        except: pass
        self.cb_ws.Items.Insert(0, "ทั้งหมด")
        self.cb_ws.SelectedIndex = 0

        from System.Windows.Interop import WindowInteropHelper
        WindowInteropHelper(win).Owner = uidoc.Application.MainWindowHandle
        win.ShowDialog()

    def on_scan(self, s, e):
        from pyrevit import forms as pf
        try:
            if self.pb: self.pb.Visibility, self.pb.Value = Visibility.Visible, 0
            self.lbl_status.Content = "กำลังสแกน..."
            self.records = scan_manholes(self.doc, self.doc.ActiveView.Id, 
                lambda cur, tot: setattr(self.pb, "Value", (float(cur)/tot)*100 if tot>0 else 0) or setattr(self.lbl_status, "Content", "ประมวลผล {}/{}".format(cur, tot)))
            if not self.records:
                pf.alert("ไม่พบบ่อในView นี้", title="แจ้งเตือน")
            self.cb_status.SelectedIndex = 0
            self._refresh_rows()
        except Exception as ex:
            pf.alert("Error:\n" + traceback.format_exc(), title="Scan Error")
        finally:
            if self.pb: self.pb.Visibility = Visibility.Hidden

    def _refresh_rows(self):
        # ✅ FIX 4: ใช้ Content property
        sel_stat_item = self.cb_status.SelectedItem
        sel_stat = None
        if hasattr(sel_stat_item, "Content"):
            content_str = str(sel_stat_item.Content).strip()
            sel_stat = {"มีการเปลี่ยนแปลง":"changed","ต้องตรวจสอบ":"warn","ไม่มีการเปลี่ยนแปลง":"ok"}.get(content_str)

        sel_ws_item = self.cb_ws.SelectedItem
        sel_ws = "ทั้งหมด"
        if sel_ws_item:
            sel_ws = str(sel_ws_item).strip()

        self.rows.Clear()
        for r in self.records:
            if sel_stat and r["status"] != sel_stat: continue
            if sel_ws != "ทั้งหมด" and r["ws"] != sel_ws: continue
            self.rows.Add(ManholeRow(r))

        filtered = [r for r in self.records if (not sel_stat or r["status"]==sel_stat) and (sel_ws=="ทั้งหมด" or r["ws"]==sel_ws)]
        ok, ch, wa = sum(1 for r in filtered if r["status"]=="ok"), sum(1 for r in filtered if r["status"]=="changed"), sum(1 for r in filtered if r["status"]=="warn")
        self.stat_total.Text, self.stat_ok.Text, self.stat_ch.Text, self.stat_warn.Text = str(len(filtered)), str(ok), str(ch), str(wa)
        if "กำลัง" not in str(self.lbl_status.Content):
            self.lbl_status.Content = "รวม {} | ไม่เปลี่ยน {} | เปลี่ยน {} | ตรวจ {}".format(len(filtered), ok, ch, wa)

    def on_filter(self, s, e):
        if self.records: self._refresh_rows()

    def on_select_row(self, s, e):
        try:
            row = self.grid.SelectedItem
            if not isinstance(row, ManholeRow): return
            r = row._record
            self.det_main.ItemsSource = [DetailRow("Connection {}".format(i+1), r["old_main"][i], r["new_main"][i]) for i in range(4)]
            self.det_extra.ItemsSource = [DetailRow("Connection {} Extra".format(i+1), r["old_extra"][i], r["new_extra"][i]) for i in range(4)]
        except: pass

    def on_commit(self, s, e):
        from pyrevit import forms as pf
        if self.cb_dry.IsChecked: return pf.alert("Preview only")
        sel = [r._record for r in self.rows if r.checked]
        if not sel: return pf.alert("เลือกบ่อก่อน")
        commit_manholes(self.doc, sel)
        pf.alert("✅ Commit {} บ่อ".format(len(sel)))
        self.on_scan(None, None)

    def on_export(self, s, e):
        from System.Windows.Forms import SaveFileDialog, DialogResult
        from pyrevit import forms as pf
        dlg = SaveFileDialog(); dlg.Filter, dlg.FileName = "CSV|*.csv", "ManholeQA.csv"
        if dlg.ShowDialog() != DialogResult.OK: return
        with open(dlg.FileName, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["ID","WS","Status","C1o","C2o","C3o","C4o","C1n","C2n","C3n","C4n","E1o","E2o","E3o","E4o","E1n","E2n","E3n","E4n"])
            for r in self.records: w.writerow([r["id"],r["ws"],r["status"]]+r["old_main"]+r["new_main"]+r["old_extra"]+r["new_extra"])
        pf.alert("✅ {}".format(dlg.FileName))
