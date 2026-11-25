P13.extension

![Autodesk Revit](https://img.shields.io/badge/Autodesk%20Revit-2024%20%7C%202025%20%7C%202026-0696D7)
![pyRevit](https://img.shields.io/badge/Powered%20by-pyRevit-orange)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D4)

P13.extension is a 100% free, open-source, multi-version pyRevit toolset for BIM automation in Autodesk Revit 2024, 2025, and 2026. It consolidates 70 production-ready utilities for model QA/QC, shared coordinates, view-filter transfers, annotation cleanup, Excel data exchange, model management, MEP workflows, and repetitive documentation tasks into one unified Revit ribbon tab.

Developed and maintained by Permpong Taweekul (P13) for practical deployment in live engineering and architectural BIM projects.

Revit compatibility

Supported versions: Autodesk Revit 2024, 2025, and 2026

Primary validation environment: Optimized and fully tested with Autodesk Revit 2026

Runtime support: Built with cross-version handling across .NET Framework (Revit 2024) and .NET 8 (Revit 2025-2026), as well as IronPython and CPython engines

Prerequisites:

Windows OS

A pyRevit installation compatible with your Revit version

Microsoft Excel or project-specific shared parameters/families where required by specialized workflows

Key highlights & recent Pro upgrades

Synchronization & smart extension updater

Sync Owner: Synchronizes workshared models with Central while preserving checked-out elements and workset ownership.

Update (Pro Edition): Background update checker with conditional HTTP (ETag) caching, pre-update commit preview dialog, progress indicator, Windows long-path support, locked-DLL rename handling, automatic cleanup of deprecated commands, and a Shift+Click maintenance menu (Force Re-Sync, commit log, log viewer, and cache reset).

View filters & graphics

Filter Transfer (Unified Copy & Paste): Revit-native WPF dialog modeled after Visibility/Graphic Overrides featuring interactive destination cards (Active View, Selected Views, View Templates), live RGB swatches, bulk multi-selection (Shift+Click, Ctrl+Click, Ctrl+A, Spacebar), and standalone Schema v3.0+ JSON presets that serialize full filter rules (AND/OR logic, categories, parameters, and worksets).

Line Color & Workset Color: Rapid visual inspection using temporary projection/cut color overrides and parameter/workset color themes.

Modify, grids & annotation cleanup

Grids 2D (Pro Edition): Native WPF grid-status table displaying live 2D/3D end states, elbow indicators, and Scope Box locks with three modes: Safe 2D (preserves existing 2D curves and custom elbows without shifting endpoints), Reset & Set 2D, and Revert to 3D.

Overkill View: Cleans overlapping Detail/Model/Room Separation Lines and exact duplicate Dimensions, Independent Tags, Text Notes, and Detail Items inside a single undoable Revit transaction, with optional line-weight preservation and a cleanup summary.

Chain Dim, Grid Bubble Manager, Grid Dimension & Numbering: Fast documentation and category-grouped auto/manual numbering workflows.

Spot-Coordinate Alignment: Aligns Spot Coordinate text left, right, top, or bottom, distributes text evenly, or restores native positions without shifting referenced model points.

Calculation & model checking

Element Calculations: Automated elevation, offset, and sill/head parameter calculations for walls, structural columns, doors, windows, base levels, and areas (including Thai Rai-Ngan-Square Wa conversion and cost estimation).

QA/QC Selection: Instant Element ID extraction and multi-ID/GUID search.

Shared coordinates & survey workflows

Survey & GIS Integration: Real-world Northing/Easting calculation and movement accounting for Project Base Point and True North rotation, CSV/Excel coordinate placement, and direct Thailand UTM (Zone 47N/48N) to Google Maps launch.

Schedules, sheets & project management

Excel & Cross-Project Exchange: Round-trip schedule export/import/sync with Excel, batch sheet creation from Excel clipboard data, and cross-project copying for sheets, legends, and drafting views.

15 Dedicated Managers: Focused management interfaces for Families, Filters, Phasing, Dependent Views, Imported CAD, Keynotes, Parameters, Selection Filters (S-Filter), Sheets, Batch PDF/CAD Export (SuperSheet), View Templates (Template Manager Pro), Views, and Worksets.

MEP workflows

Pipe, Fitting & Manhole Automation: Manhole QA and invert synchronization, multi-connector pipe/duct extension (Pipe Bloom), bottom-of-pipe (Pipe BOP), high-ratio slope tags (1:750+), automated flow-arrow placement (Pipe Flow), connector-axis fitting rotation, and taggable sloped/skewed MEP wall openings.

Command reference

The catalog below lists all 70 executable commands included in the P13 ribbon tab (excluding container pulldowns, split buttons, and stacks).

A-Sync panel

Command

What it does

Sync Owner

Saves and synchronizes the active workshared model with Central while retaining checked-out elements and workset ownership for continued exclusive editing.

Update

Checks the GitHub main branch in the background with ETag caching, previews recent commits, updates P13.extension safely (handling locked files and long paths), cleans up removed tools, and reloads pyRevit. Supports Shift+Click maintenance tools.

Calculation panel

Command

What it does

Base Level Parameter

Reads each element's host level elevation and writes it to the Base_Level parameter across multiple selected categories.

Columns Cal

Calculates structural-column base level, top level, base offset, and top offset values and writes the required parameters.

Door Cal

Calculates Top of Door, Bottom of Door, and Base_Level from the level elevation, sill height, and door height.

Windows Cal

Calculates Top of Windows, Bottom of Windows, and Base_Level from the level elevation, sill height, and window height.

Wall Cal

Calculates wall top and bottom elevation values from the base level, base offset, and unconnected height.

Smart Area

Measures an area from picked boundary points or a temporary drawn element, converts it to Rai-Ngan-Square Wa, estimates cost, supports accumulated totals, and copies results to the clipboard.

Check panel

Command

What it does

Get ID

Reads Element IDs from the current selection and copies them to the clipboard.

Search ID

Finds and selects model elements from Element IDs, Unique IDs, or GUIDs.

Coordinate panel

Command

What it does

Families Coord

Calculates real-world northing/easting for family instances from the Project Base Point and project rotation, updates N_Coordinate and E_Coordinate, supports grouped elements, remembers category selections, and exports a CSV report.

Google Maps

Converts picked Revit coordinates to UTM and WGS84 latitude/longitude, determines Thailand UTM Zone 47N or 48N, and opens the position in Google Maps.

Move N/E

Moves one or more selected elements to specified real-world northing/easting coordinates while accounting for the Project Base Point and True North rotation.

Filter panel

Command

What it does

Filter Transfer

Unified view-filter manager (consolidating Copy-F and Paste-F) with a Revit-style WPF UI, standalone Schema v3.0+ JSON rule presets, live RGB swatches, bulk selection shortcuts, and one-click transfer to active views, selected views, or view templates.

Import / Export panel

Import

Command

What it does

CSV to Detail Items

Converts survey eastings/northings to Revit coordinates and places Detail Items in plan views. Updates point parameters and falls back to simple drawn geometry if no suitable Detail Item family exists.

CSV to Families

Places family instances from CSV survey coordinates with dynamic parameter mapping, family-type matching, level/elevation control, and remembered import settings.

Excel to Families

Places family instances from Excel eastings/northings, matches family types, selects host levels, and calculates height or cut-off offsets.

Legends and drafting

Command

What it does

Copy Legends & Drafting to Revit

Batch-copies legends and drafting views to other open Revit projects, converting content and managing duplicate names.

Copy Legends to Sheet

Copies or synchronizes legend placement and viewport types across sheets.

Filled Regions

Generates a Filled Region legend with configurable sample sizes, labels, and scale-aware graphics.

Tag Legend

Creates or updates tags for legend components using selected parameters and automatic placement.

Schedules and Excel

Command

What it does

Export Schedules to Excel

Exports selected schedules to Excel and embeds the metadata required for safe update-only import.

Import Schedules from Excel

Reads a P13 schedule export and updates parameters on existing Revit elements.

Import Schedules

Copies schedules from another currently open Revit document into the active project.

Sync Schedules with Excel

Performs directional synchronization between Revit schedules and existing P13 Excel or CSV exports.

Sheets

Command

What it does

Copy Sheets Across Projects

Copies sheets, title blocks, annotations, and supported viewports between open Revit projects.

Sheets from Excel Clipboard

Batch-creates sheets from rows copied from Excel and checks for duplicate sheet data before creation.

Line Color panel

Command

What it does

Set Color

Opens a color picker and applies the chosen projection, cut-line, and cut-pattern color override to selected elements in the active view.

Reset

Removes the P13 line-color overrides and restores normal view graphics.

Manager panel

Command

What it does

Change Phasing

Filters elements, expands supported nested groups, and batch-updates phase data while remembering selections.

Duplicate Dependent Views

Creates the requested number of dependent views from selected eligible primary views in one validated, rollback-safe batch.

Family Manager

Reviews families and types in a grid, supports favorites and batch actions, edits supported names, and exports family information to Excel.

Filters Manager

Reviews filter/template usage, removes selected unused items safely, and batch-applies view templates with result reporting.

G-Status

Creates or updates g_Element Status and assigns status values by workset.

Import CAD Manager

Searches, filters, reviews, explodes, or deletes imported CAD instances from a DataGrid interface.

Keynote Manager

Manages keynote data through the pyRevit keynote database workflow.

Parameters

Exports and imports project-parameter definitions with JSON, detects unused parameters, and supports controlled batch management.

S-Filter

Filters host or linked-model elements using categories, custom groups, and parameter rules; supports highlighting and remembered filter setups.

Sheet Manager

Manages sheets, views, revisions, placeholders, View/Sheet Sets, profiles, view placement, and Excel-compatible CSV round trips from one searchable interface.

SuperSheet

Batch-exports sheets with configurable formats, PDF options, and rule-based output naming.

Template Manager Pro

Audits template usage, searches and filters by status/type, safely renames/duplicates/deletes, compares settings, manages controlled parameters, applies compatible templates, imports from open projects, and exports UTF-8 CSV reports.

View Manager

Searches and filters views with multiple rules, performs batch view operations, and remembers export settings.

Workset Color

Builds view filters and color themes from workset or parameter values, including transparency control for model analysis.

Workset Manager

Creates, renames, searches, sets active, cleans empty worksets, moves elements between worksets, and manages granular item/family-type ownership profiles through reusable JSON files.

MEP panel

Command

What it does

69

Sets the writable Comments parameter on the current selection.

Manhole QA

Scans manholes and connected conduits, presents connection data in a modeless QA interface, and synchronizes supported manhole values.

Pipe Bloom

Extends pipes or ducts from multiple connectors, detects systems, adjusts direction, and creates elbows automatically.

Pipe BOP

Calculates pipe start/end bottom elevations and writes B-Start and BOP.Cal values for tagging.

Pipe Slope Ratio

Writes a taggable Slope_Ratio text value such as 1:750 for pipes and floors, including ratios above Revit's 1:500 tag display limit.

Pipe Flow

Analyzes slope, elevation, connected equipment, systems, and neighboring pipes to estimate flow direction, then places and rotates Detail Item arrows at configurable spacing.

Rotate Fitting

Detects connector-based rotation axes and batch-rotates pipe/duct fittings, accessories, and supported equipment using preset or custom angles.

Sync MH Absolute Clean

Clears stale manhole text values and recalculates directional invert levels and dimensions only where the required direction and pipe width are valid.

Wall Opening

Detects intersections between MEP elements and host/linked walls, places specialized taggable opening families, calculates sloped/skewed sizes, synchronizes parameters, updates existing openings, and numbers them by category group.

Modify panel

Command

What it does

Chain Dim

Creates one sorted chain dimension from window-selected families or picked references with horizontal, vertical, or aligned placement.

Cut Wall Angle

Uses a remembered line-based Void family to cut a selected wall along a user-defined angled line without changing the original wall parameters.

DisAllow Beam-Joint

Disables joins at the start, end, or both ends of selected structural framing elements in a batch operation.

Grid Bubble Manager

Shows, hides, toggles, or smart-places grid bubbles for selected, window-selected, continuously picked, or all visible grids without changing grid geometry.

Grid Dimension

Groups and dimensions parallel straight grids from the selection or active view, using the chosen side and offset.

Grids 2D

Opens a live WPF grid-extent status table and converts visible grids using Safe 2D (preserving existing 2D curves and elbows), Reset & Set 2D, or Revert to 3D modes while respecting Scope Box locks.

Overkill View

Cleans overlapping lines and exact duplicate dimensions, tags, text notes, and Detail Items from the active view, with category-specific modes and an undoable result summary.

Number Auto

Filters by category and family type, previews elements, sorts by X/Y/Z direction, writes formatted category-grouped numbers, supports Live Pick, and round-trips the list through CSV.

Number Manual

Numbers interactively picked elements into a chosen instance, built-in, shared, or type parameter with remembered prefixes and digit formatting.

Spot Coordinates panel

Command

What it does

Align-L

Aligns the text edges of selected Spot Coordinates to the left while preserving their referenced model points.

Align-R

Aligns the text edges of selected Spot Coordinates to the right while preserving their referenced model points.

Align-T

Aligns the text edges of selected Spot Coordinates to the top while preserving their referenced model points.

Align Bot

Aligns the text edges of selected Spot Coordinates to the bottom while preserving their referenced model points.

Dis-Hor

Evenly distributes selected Spot Coordinate text horizontally while keeping the outermost annotations fixed.

Dis-Ver

Evenly distributes selected Spot Coordinate text vertically while keeping the outermost annotations fixed.

Reset

Restores the native text position of selected Spot Coordinates.

Z-Support panel

Command

What it does

Support P13

Opens the supporter hub with Ko-fi (Stripe global checkout), GitHub Sponsors, scannable Ko-fi Mobile QR and PromptPay / ASEAN QR codes (with click-to-zoom), repository sharing links, and the community Suggest a Tool Idea dialog. (Shift+Click opens Ko-fi directly.)

Installation

Install a pyRevit version compatible with your Autodesk Revit release (2024-2026).

Clone or download this repository.

Place P13.extension inside your pyRevit extensions folder:

%APPDATA%\pyRevit\Extensions\P13.extension


Reload pyRevit (or restart Revit) and open the P13 ribbon tab.

Quick install via PowerShell (Git)

git clone https://github.com/permpong13/P13.git "$env:APPDATA\pyRevit\Extensions\P13.extension"


Tip: Once installed, standard users can update directly inside Revit at any time using P13 > A-Sync > Update (or Shift+Click on Update for Force Re-Sync). If a .git checkout already exists on a developer machine, pull updates via Git instead of cloning over the existing folder.

Usage and safety

Test model-modifying commands on a detached or backed-up model before production rollout.

Review the active view, current selection, and dialog options carefully before confirming batch operations.

Ensure required shared parameters and custom families are loaded for specialized project workflows (such as taggable MEP wall openings or coordinate parameters).

All model-modifying operations run inside standard Revit transactions and can be reverted immediately with Revit Undo (Ctrl+Z).

Keep pyRevit and P13.extension updated together when migrating across major Revit releases.

Support development & share workflow ideas

P13.extension is 100% free and open-source — every tool is unlocked for everyone with no paywalls or license keys. If these tools save hours on your projects, optional tips and sponsorships directly fund ongoing maintenance, testing, and compatibility updates for future Revit versions.

1. Ko-fi (Worldwide — Card, Apple Pay, Google Pay)

Buy Tee a coffee with instant global checkout powered by Stripe (no account required), and feel free to attach a note with repetitive Revit tasks you wish could be automated:

Support P13 on Ko-fi (ko-fi.com/permpong13)

2. GitHub Sponsors

Support P13 with a one-time or monthly contribution on GitHub:

![Sponsor P13 on GitHub](https://img.shields.io/badge/GitHub%20Sponsors-Support%20P13-24292F?logo=githubsponsors&logoColor=white)

3. In-Revit QR Scan & Idea Box (P13 > Z-Support > Support P13)

Inside Revit, open P13 > Z-Support > Support P13 to:

Scan the Ko-fi Mobile QR (worldwide phone camera checkout via Apple Pay, Google Pay, or card).

Scan the PromptPay / ASEAN Cross-Border QR (for Thai banking apps and supported regional apps).

Click Suggest a Tool Idea to share workflow pain points and inspire future open-source scripts.

Repository & community

Source code: github.com/permpong13/P13

Bug reports & tool ideas: GitHub Issues

Author

Permpong Taweekul (P13)Engineer & BIM Automation Developer

ภาษาไทย

P13.extension คือชุดเครื่องมืออัตโนมัติบน pyRevit แบบฟรีและโอเพนซอร์ส 100% สำหรับ Autodesk Revit 2024, 2025 และ 2026 (พัฒนาและทดสอบหลักบน Revit 2026) ออกแบบมาเพื่อลดงานซ้ำซ้อน เพิ่มความแม่นยำของข้อมูลโมเดล และยกระดับการทำงาน BIM ในโครงการจริง ครอบคลุมทั้งระบบอัปเดตอัตโนมัติ งานคำนวณพารามิเตอร์ งานตรวจสอบโมเดล พิกัดสำรวจ การจัดการ View Filter การรับ-ส่งข้อมูล Excel งานจัดการมาตรฐานโครงการ งานระบบ MEP และชุดจัดการเส้นซ้ำหรือจัดระเบียบแบบก่อสร้างรวม 70 คำสั่งในแถบเดียว

ร่วมสนับสนุนและเสนอไอเดียเครื่องมือใหม่

เครื่องมือทุกปุ่มใน P13.extension เปิดให้ใช้งานฟรีทั้งหมดโดยไม่มีการล็อกฟีเจอร์ หากชุดเครื่องมือนี้ช่วยประหยัดเวลาทำงานของคุณ สามารถร่วมสนับสนุนค่ากาแฟเพื่อเป็นกำลังใจในการดูแลและอัปเดตเวอร์ชันใหม่ หรือร่วมเสนอไอเดียคำสั่งที่อยากให้พัฒนาต่อได้ผ่านช่องทางต่อไปนี้:

Ko-fi (ทั่วโลก — บัตรเครดิต/เดบิต, Apple Pay, Google Pay ผ่าน Stripe): ko-fi.com/permpong13

GitHub Sponsors: github.com/sponsors/permpong13

PromptPay QR / Ko-fi QR และกล่องเสนอไอเดียภายในโปรแกรม Revit: เปิดที่แถบคำสั่ง P13 > Z-Support > Support P13 (หรือกด Shift+Click ที่ปุ่มเพื่อเปิดหน้า Ko-fi ทันที)
