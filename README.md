# P13.extension

![Autodesk Revit](https://img.shields.io/badge/Autodesk%20Revit-2024%20%7C%202025%20%7C%202026-0696D7)
![pyRevit](https://img.shields.io/badge/Powered%20by-pyRevit-orange)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D4)
<img width="1851" height="99" alt="image" src="https://github.com/user-attachments/assets/f2afc1c0-1c2f-4b7a-a92f-771f50810416" />
**P13.extension** is a collection of pyRevit tools built for day-to-day BIM production in **Autodesk Revit 2024, 2025, and 2026**.

Most of these scripts started out as small fixes for repetitive tasks on real engineering and architectural projects—cleaning up messy 2D views, checking survey coordinates, pushing schedules back and forth with Excel, managing sheets and templates, and handling MEP piping details—and grew into a single ribbon tab.

Maintained by **Permpong Taweekul (P13)**. Free and open-source, with no locked tools or license keys.

---

## Compatibility & requirements

- **Revit versions:** 2024, 2025, and 2026 (primarily developed and tested in **Revit 2026**)
- **Runtime:** Handles API differences between .NET Framework (Revit 2024) and .NET 8 (Revit 2025–2026)
- **Requirements:** Windows + a matching [pyRevit](https://github.com/pyrevitlabs/pyRevit) installation
- **Optional:** Microsoft Excel and project-specific shared parameters or custom families for certain workflows (such as coordinate write-back or taggable wall openings)

---

## What's inside the P13 tab
### Calculation — Elevations, levels & area
<img width="293" height="95" alt="image" src="https://github.com/user-attachments/assets/b1d456eb-a643-49f9-87ec-8f40445e43f7" />


- **Element elevation calculators:** Writes host level elevations, top/bottom levels, and sill/head offsets to parameters for walls (`Wall Cal`), structural columns (`Columns Cal`), doors (`Door Cal`), windows (`Windows Cal`), and multi-category elements (`Base_Level Parameter`).
- **Smart Area:** Measures picked boundaries, converts areas to Thai units (*Rai–Ngan–Square Wa*), estimates rough cost, tracks running totals, and copies results to the clipboard.

### Check Tools & Coordinate — QA/QC and survey points
<img width="207" height="99" alt="image" src="https://github.com/user-attachments/assets/8dd4d867-8d73-4b33-88a4-6fe9e452756d" />



- **Get ID / Search ID:** Copies selected Element IDs or finds elements by Element ID, UniqueId, or GUID during clash checks and model audits.
- **Survey & real-world coordinates:** `Families Coord` and `Pole Found. Coord` calculate Northing/Easting values from the Project Base Point and True North rotation and export CSV reports. `Move N/E` moves elements to exact survey coordinates, and `Google Maps` opens picked UTM locations (Thailand Zones 47N/48N) in your browser.

### Import & Export — Excel, schedules, legends & sheets
<img width="305" height="100" alt="image" src="https://github.com/user-attachments/assets/094ba5fa-9e3f-4381-a333-867db06ad8a7" />
<img width="307" height="203" alt="image" src="https://github.com/user-attachments/assets/e81ecc57-50c5-439b-a797-70c7c14cba4b" />
<img width="297" height="174" alt="image" src="https://github.com/user-attachments/assets/cac92647-36bb-49ff-9c00-42cd86310091" />
<img width="374" height="142" alt="image" src="https://github.com/user-attachments/assets/50f185c3-f60d-44f2-a29a-0aa64b2de81a" />
<img width="300" height="203" alt="image" src="https://github.com/user-attachments/assets/65b1f13e-fc0d-4a5b-bbac-a454e3e6747b" />
- **Schedules:** Export schedules to Excel, import edited parameter values back safely, sync changes, or copy schedules from another open Revit file.
- **Survey placement:** Place families or detail items in bulk from CSV or Excel Northing/Easting tables.
- **Legends & drafting:** Batch-copy legends and drafting views across open projects, sync legend positions across sheets, tag legend components, and generate Filled Region legends.
- **Sheets:** Create sheets from copied Excel rows or copy complete sheets (title blocks, annotations, and supported viewports) between projects.

### Manager — Project & model cleanup
<img width="602" height="192" alt="image" src="https://github.com/user-attachments/assets/ffbd9fc2-2da4-4ae7-bb59-6bb7cc009f43" />
- **Sheets & views:** `Sheet Manager`, `Sheet Turbo Renamer`, `SuperSheet Exporter` (batch PDF/CAD export with naming rules), `View Manager`, `Duplicate Dependent Views`, and `Template Manager`.
- **Content & standards:** `Families Manager`, `Parameter Manager` (JSON export/import and unused parameter checks), `Keynote Manager`, and `ImportCAD Manager` (find, explode, or purge CAD imports/links).
- **Worksets, phases & color checks:** `Workset Manager`, `Change Phasing` (supports nested groups), `G-Element Status`, and `Spectrum Color` (color-codes views by workset or parameter values).

### Modify, Grids, Filter, Line Color & Spot Coordinate
<img width="317" height="98" alt="image" src="https://github.com/user-attachments/assets/c33d14aa-ed21-4274-986c-e566d18e2552" />
<img width="178" height="170" alt="image" src="https://github.com/user-attachments/assets/8d64c9f8-06dd-49fe-9ca2-09f51efcaf1b" />
<img width="215" height="130" alt="image" src="https://github.com/user-attachments/assets/f3841c2f-15fa-4440-b2f0-551ebc4381ff" />
<img width="101" height="98" alt="image" src="https://github.com/user-attachments/assets/f18d2d3d-0995-476e-bc3a-09434f11fec3" />
- **View cleanup & detailing:** `Overkill View` removes overlapping lines and duplicate dimensions, tags, text notes, and detail items in one undoable step. Also includes `Chain Dim`, `Cut Wall Angle`, `DisAllow Beam-Joint`, and `Number Auto` (directional auto-numbering and manual pick numbering).
- **Grids:** `Grid Bubble Manager`, `Grid Dimension`, and `Grids 2D` (switches grids to 2D view-specific extents without resetting custom line ends or elbows, with an option to reset to 3D extents when needed).
- **Filters & visual overrides:** `Filter Transfer` saves and applies view filters, filter rules, and V/G overrides across views, View Templates, and projects; `Filter Select` selects elements by category and parameter rules (including linked models); `Line Color` (`Set Color` / `Reset`) applies quick element color overrides.
- **Spot Coordinates:** Aligns (`Align-L/R/T/Bot`), evenly distributes, or resets Spot Coordinate text without shifting the referenced model point.

### MEP — Piping, manholes & openings
<img width="187" height="348" alt="image" src="https://github.com/user-attachments/assets/8024978f-71c0-4529-b6df-4f3a2c9af0e6" />

- Grouped under the **MEP (`Bloom Pipes`)** panel: extend multiple pipes or ducts with auto-elbows (`Pipe Bloom`), write bottom-of-pipe values (`Pipe BOP`), format high slope ratios like `1:750` for tagging, place flow-direction arrows (`Pipe Flow`), rotate fittings around connector axes, check/sync manhole inverts (`Manhole QA`), and place taggable sloped/skewed MEP wall openings.

---

## Installation

1. Install **pyRevit** for your Revit version (2024–2026).
2. Clone or download this repo into your pyRevit extensions folder:
   ```text
   %APPDATA%\pyRevit\Extensions\P13.extension
   ```
3. Reload pyRevit (or restart Revit) to load the **P13** tab.

**PowerShell one-liner (Git):**

```powershell
git clone https://github.com/permpong13/P13.git "$env:APPDATA\pyRevit\Extensions\P13.extension"
```

Once installed, you can grab future updates anytime from **P13 > A-Sync > Update** inside Revit. (If you cloned with Git for development, `.git` folders are left untouched so you won't overwrite local work.)

---

## Notes before running on live models

- Try batch commands on a detached or backup model first if you haven't used them on your current setup.
- Check your active view and selection before running bulk edits—every model change runs inside a standard Revit transaction, so `Ctrl+Z` (Undo) will roll it back if something looks off.
- Commands that write to specific parameters (like `Base_Level`, `N_Coordinate`, or wall-opening tags) expect those shared parameters or families to exist in the project.

---

## Support & feedback

Every tool in `P13.extension` is free to use at work or on personal projects. If these scripts save you a few hours of clicking, you can buy me a coffee to help cover ongoing maintenance and testing for new Revit releases—or drop an idea for a repetitive task you'd like to see automated next.

- **Ko-fi (Card, Apple Pay, Google Pay via Stripe):** [ko-fi.com/permpong13](https://ko-fi.com/permpong13)
- **GitHub Sponsors:** [github.com/sponsors/permpong13](https://github.com/sponsors/permpong13)
- **Inside Revit (`P13 > ZZ-Support > Support P13`):** Includes **Ko-fi QR**, **PromptPay / ASEAN QR** for banking apps, and a **Suggest a Tool Idea** box.

[![Sponsor P13 on GitHub](https://img.shields.io/badge/GitHub%20Sponsors-Support%20P13-24292F?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/permpong13)

---

## Links & author

- **Repository:** [github.com/permpong13/P13](https://github.com/permpong13/P13)
- **Bug reports & tool ideas:** [GitHub Issues](https://github.com/permpong13/P13/issues)
- **Author:** **Permpong Taweekul (P13)** — Engineer & BIM Automation Developer

---

## ภาษาไทย

**P13.extension** คือชุดเครื่องมือเสริมบน **pyRevit** สำหรับ **Autodesk Revit 2024, 2025 และ 2026** (พัฒนาและใช้งานหลักบน Revit 2026) รวบรวมสคริปต์ที่สร้างขึ้นจากหน้างานจริงเพื่อลดงานกดซ้ำๆ ไม่ว่าจะเป็นงานคำนวณค่าระดับ งานเช็กพิกัดสำรวจ N/E และเปิดดูตำแหน่งบน Google Maps งานดึง-ส่งตาราง Schedule กับ Excel งานจัดการ Sheet/View/Template ชุดใหญ่ การโอนย้าย View Filter ข้ามไฟล์ การลบเส้นและแท็กซ้อนทับด้วย Overkill View ไปจนถึงงานท่อและบ่อพักฝั่ง MEP

เครื่องมือทุกตัวเปิดให้ใช้งานฟรีทั้งหมด หากสคริปต์ชุดนี้ช่วยให้คุณปิดงานได้เร็วขึ้น สามารถแวะเลี้ยงกาแฟสนับสนุนการดูแลและอัปเดตโค้ด หรือฝากไอเดียเครื่องมือที่อยากให้ทำเพิ่มได้ที่:

- **Ko-fi (รองรับบัตรเครดิต/เดบิต, Apple Pay, Google Pay):** [ko-fi.com/permpong13](https://ko-fi.com/permpong13)
- **GitHub Sponsors:** [github.com/sponsors/permpong13](https://github.com/sponsors/permpong13)
- **สแกน PromptPay QR / Ko-fi QR ในโปรแกรม Revit:** เปิดที่แถบ **P13 > ZZ-Support > Support P13** (หรือกด `Shift+Click` ที่ปุ่มเพื่อเปิดหน้าเว็บ Ko-fi ทันที)
