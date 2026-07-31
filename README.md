# P13.extension

![Autodesk Revit](https://img.shields.io/badge/Autodesk%20Revit-2024%20%7C%202025%20%7C%202026-0696D7)
![pyRevit](https://img.shields.io/badge/Powered%20by-pyRevit-orange)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D4)

P13.extension is a multi-version pyRevit toolset for BIM automation in Autodesk Revit 2024, 2025, and 2026. It groups production utilities for model checking, shared coordinates, annotation cleanup, data exchange, model management, MEP workflows, and repetitive documentation tasks into one Revit ribbon tab.

The extension is developed and maintained by Permpong Taweekul (P13) for practical use in live BIM projects.

## Revit compatibility

- Autodesk Revit 2024, 2025, and 2026
- Optimized and fully tested with Autodesk Revit 2026
- Most tools are designed for cross-version Revit API compatibility
- Behavior of some advanced commands may vary in Revit 2024–2025
- A pyRevit installation compatible with the selected Revit version
- Windows

Revit 2025–2026 use the .NET 8 runtime, while Revit 2024 uses the earlier .NET Framework runtime. P13.extension contains compatibility handling for many API differences, but Autodesk Revit 2026 remains the primary development and validation environment.

Some commands integrate with Microsoft Excel or other project-specific data sources. Those commands may require the relevant desktop application, file access, or project parameters.

## P13 Revit MCP

P13 includes a provider-neutral local MCP bridge for AI clients such as
Antigravity, Codex, Claude, and other MCP-compatible hosts. The secured HTTP
endpoint uses reserved port `8013`, while the reference
`mcp-server-for-revit-python` can remain on port `8000`. Per-user secrets are
stored outside the extension, HTTP requires bearer authentication, and Revit
model-writing tools require explicit confirmation.

Privacy defaults hide the Revit document title and full file path from AI
providers. Remote AI use requires visible confirmation, result history is
opt-in per task, and SuperSheet profiles/export paths are stored under the
current user's `%APPDATA%` rather than inside the public extension. Review
[`mcp_server/SECURITY.md`](mcp_server/SECURITY.md) before publishing or
deploying P13.

The **P13 AI Console** ribbon command provides an in-Revit launcher for Codex
using an existing ChatGPT sign-in, OpenAI API, Anthropic, Google Gemini,
OpenRouter, Ollama, LM Studio, and custom
OpenAI-compatible endpoints. Users can discover or enter a model ID, submit a
natural-language Revit task, and decide whether that individual task is
read-only or may perform confirmed writes. The AI process runs outside Revit
and starts its own stdio MCP connection, so it does not require port `8013` and
does not block Revit while tools execute.

Installation, client configuration, security, and worldwide distribution are
documented in [`mcp_server/README.md`](mcp_server/README.md) and
[`mcp_server/SECURITY.md`](mcp_server/SECURITY.md).

## Main features

### AI and MCP automation

- Choose an AI provider and model for each task.
- Use the Codex CLI and an existing ChatGPT sign-in without an API key.
- Use cloud APIs, local Ollama or LM Studio models, or a custom compatible API.
- Inspect the active Revit document through allowlisted P13 MCP tools.
- Keep model writes disabled by default and enable them explicitly per task.
- Run AI work outside the Revit process to preserve UI responsiveness.

### Synchronization

- Synchronize central models with configurable ownership handling.
- Support synchronization workflows intended for managed BIM environments.

### Calculation and model data

- Calculate and update values for walls, columns, doors, windows, levels, and areas.
- Reduce repetitive parameter entry and improve consistency across model elements.

### Model checking

- Read selected Revit element IDs.
- Find elements by ID for troubleshooting, coordination, and QA/QC.

### Coordinates and location

- Review and manage family coordinates.
- Support shared-coordinate and project-location workflows.
- Open geographic locations in Google Maps.
- Move supported content using northing and easting workflows.

### View filters and graphics

- Copy and paste view-filter states.
- Apply predefined line colors for visual checking.
- Reset temporary line-color changes.
- Review worksets with color-based visualization.

### Import and export

- Import families and Detail Items from CSV or Excel-based data.
- Export Revit schedules to Excel.
- Import and synchronize schedules from Excel.
- Create sheets from Excel clipboard data.
- Copy sheets between projects.
- Copy legends and drafting views between Revit projects.
- Place legends on sheets and generate supporting drafting content.

### Model and project management

- Manage families, parameters, filters, phases, imported CAD files, keynotes, templates, views, sheets, and worksets.
- Provide focused management dialogs for reviewing and updating project standards.
- Support selection and status workflows for large BIM models.

### Modify and annotation tools

- Create chain dimensions.
- Control wall joins and angled wall cuts.
- Convert grids to view-specific 2D extents.
- Number elements using category-based grouping.
- Clean duplicate and overlapping content in the active view with **Overkill View**.

Overkill View supports:

- Detail Lines, Model Lines, and Room Separation Lines
- Dimensions
- Independent Tags
- Text Notes
- Detail Items of the same family type and placement geometry
- Optional preservation of different line weights
- A cleanup summary showing how many elements were removed

All cleanup operations run inside a Revit transaction and can be undone with the standard Revit Undo command.

### MEP tools

- Review manhole data and synchronize supported manhole parameters.
- Calculate or update pipe bottom-of-pipe and flow-related data.
- Rotate supported fittings.
- Create and manage specialized wall-opening families for taggable wall openings.

Wall-opening workflows use dedicated custom families because native rectangular Revit wall openings do not expose the required taggable parameters.

## Command reference

The following catalog explains what the commands currently included in the **P13** ribbon can do.

### A-Sync panel

| Command | What it does |
| --- | --- |
| **Sync Owner** | Saves and synchronizes the active workshared model with Central while retaining checked-out elements and workset ownership for continued exclusive editing. |
| **Update** | Checks the GitHub `main` branch, downloads updated P13.extension files, skips locked files, and reloads pyRevit. Its ribbon icon indicates whether the installed version is current. |

### Calculation panel

| Command | What it does |
| --- | --- |
| **Base Level Parameter** | Reads each element's host level elevation and writes it to the `Base_Level` parameter. Supports multiple selected categories. |
| **Columns Cal** | Calculates structural-column base level, top level, base offset, and top offset values and writes the required parameters. |
| **Door Cal** | Calculates `Top of Door`, `Bottom of Door`, and `Base_Level` from the level elevation, sill height, and door height. |
| **Windows Cal** | Calculates `Top of Windows`, `Bottom of Windows`, and `Base_Level` from the level elevation, sill height, and window height. |
| **Wall Cal** | Calculates wall top and bottom elevation values from the base level, base offset, and unconnected height. |
| **Smart Area** | Measures an area from picked boundary points or a temporary drawn element, converts it to Rai-Ngan-Square Wa, estimates cost, supports accumulated totals, and copies results to the clipboard. |

### Check panel

| Command | What it does |
| --- | --- |
| **Get ID** | Reads Element IDs from the current selection and copies them to the clipboard. |
| **Search ID** | Finds and selects model elements from Element IDs, Unique IDs, or GUIDs. |

### Coordinate panel

| Command | What it does |
| --- | --- |
| **Families Coord** | Calculates real-world northing/easting for family instances from the Project Base Point and project rotation, updates `N_Coordinate` and `E_Coordinate`, supports grouped elements, remembers category selections, and exports a CSV report. |
| **Google Maps** | Converts picked Revit coordinates to UTM and WGS84 latitude/longitude, determines Thailand UTM Zone 47N or 48N, and opens the position in Google Maps. |
| **Move N/E** | Moves one or more selected elements to specified real-world northing/easting coordinates while accounting for the Project Base Point and True North rotation. |

### Filter panel

| Command | What it does |
| --- | --- |
| **Copy-F** | Captures view-filter states as named presets with selective copy options. |
| **Paste-F** | Applies stored filter states and graphic overrides to active views, selected views, or view templates and can pull missing filters into the target. |

### Import / Export panel

#### Import

| Command | What it does |
| --- | --- |
| **CSV to Detail Items** | Converts survey eastings/northings to Revit coordinates and places Detail Items in plan views. Updates point parameters and falls back to simple drawn geometry if no suitable Detail Item family exists. |
| **CSV to Families** | Places family instances from CSV survey coordinates with dynamic parameter mapping, family-type matching, level/elevation control, and remembered import settings. |
| **Excel to Families** | Places family instances from Excel eastings/northings, matches family types, selects host levels, and calculates height or cut-off offsets. |

#### Legends and drafting

| Command | What it does |
| --- | --- |
| **Copy Legends & Drafting to Revit** | Batch-copies legends and drafting views to other open Revit projects, converting content and managing duplicate names. |
| **Copy Legends to Sheet** | Copies or synchronizes legend placement and viewport types across sheets. |
| **Filled Regions** | Generates a Filled Region legend with configurable sample sizes, labels, and scale-aware graphics. |
| **Tag Legend** | Creates or updates tags for legend components using selected parameters and automatic placement. |

#### Schedules and Excel

| Command | What it does |
| --- | --- |
| **Export Schedules to Excel** | Exports selected schedules to Excel and embeds the metadata required for safe update-only import. |
| **Import Schedules from Excel** | Reads a P13 schedule export and updates parameters on existing Revit elements. |
| **Import Schedules** | Copies schedules from another currently open Revit document into the active project. |
| **Sync Schedules with Excel** | Performs directional synchronization between Revit schedules and existing P13 Excel or CSV exports. |

#### Sheets

| Command | What it does |
| --- | --- |
| **Copy Sheets Across Projects** | Copies sheets, title blocks, annotations, and supported viewports between open Revit projects. |
| **Sheets from Excel Clipboard** | Batch-creates sheets from rows copied from Excel and checks for duplicate sheet data before creation. |

### Line Color panel

| Command | What it does |
| --- | --- |
| **Green, Orange, Red, Azure, Blue, Magenta, Grey, Light Grey** | Applies the selected review color to supported selected elements for fast visual coordination and checking. |
| **Reset** | Removes the P13 line-color overrides and restores the normal view graphics. |

### Manager panel

| Command | What it does |
| --- | --- |
| **Change Phasing** | Filters elements, expands supported nested groups, and batch-updates phase data while remembering selections. |
| **Family Manager** | Reviews families and types in a grid, supports favorites and batch actions, edits supported names, and exports family information to Excel. |
| **Filters Manager** | Reviews filter/template usage, removes selected unused items safely, and batch-applies view templates with result reporting. |
| **G-Status** | Creates or updates `g_Element Status` and assigns status values by workset. |
| **Import CAD Manager** | Searches, filters, reviews, explodes, or deletes imported CAD instances from a DataGrid interface. |
| **Keynote Manager** | Manages keynote data through the pyRevit keynote database workflow. |
| **Parameters** | Exports and imports project-parameter definitions with JSON, detects unused parameters, and supports controlled batch management. |
| **S-Filter** | Filters host or linked-model elements using categories, custom groups, and parameter rules; supports highlighting and remembered filter setups. |
| **Sheet Manager** | Manages sheets, views, revisions, placeholders, View/Sheet Sets, profiles, view placement, and Excel-compatible CSV round trips from one searchable interface. |
| **SuperSheet** | Batch-exports sheets with configurable formats, PDF options, and rule-based output naming. |
| **Template Manager Pro** | Audits template usage, searches and filters by status/type, safely renames/duplicates/deletes, compares settings, manages controlled parameters, applies compatible templates, imports from open projects, and exports UTF-8 CSV reports with remembered folders. |
| **View Manager** | Searches and filters views with multiple rules, performs batch view operations, and remembers export settings. |
| **Workset Color** | Builds view filters and color themes from workset or parameter values, including transparency control for model analysis. |
| **Workset Manager** | Creates, renames, searches, sets active, cleans empty worksets, moves elements between worksets, and manages granular item/family-type ownership profiles through reusable JSON files. |

### MEP panel

| Command | What it does |
| --- | --- |
| **Manhole QA** | Scans manholes and connected conduits, presents connection data in a modeless QA interface, and synchronizes supported manhole values. |
| **Pipe Bloom** | Extends pipes or ducts from multiple connectors, detects systems, adjusts direction, and creates elbows automatically. |
| **Pipe BOP** | Calculates pipe start/end bottom elevations and writes `B-Start` and `BOP.Cal` values for tagging. |
| **Pipe Flow** | Analyzes slope, elevation, connected equipment, systems, and neighboring pipes to estimate flow direction, then places and rotates Detail Item arrows at configurable spacing. |
| **Rotate Fitting** | Detects connector-based rotation axes and batch-rotates pipe/duct fittings, accessories, and supported equipment using preset or custom angles. |
| **Sync MH Absolute Clean** | Clears stale manhole text values and recalculates directional invert levels and dimensions only where the required direction and pipe width are valid. |
| **Wall Opening** | Detects intersections between MEP elements and host/linked walls, places specialized taggable opening families, calculates sloped/skewed sizes, synchronizes parameters, updates existing openings, and numbers them by category group. |

### Modify panel

| Command | What it does |
| --- | --- |
| **Chain Dim** | Creates one sorted chain dimension from window-selected families or picked references with horizontal, vertical, or aligned placement. |
| **Cut Wall Angle** | Uses a remembered line-based Void family to cut a selected wall along a user-defined angled line without changing the original wall parameters. |
| **DisAllow Beam-Joint** | Disables joins at the start, end, or both ends of selected structural framing elements in a batch operation. |
| **Grids 2D** | Converts both ends of all grids visible in the active view to view-specific 2D extents without changing their 3D extents in other views. |
| **Overkill View** | Cleans overlapping lines and exact duplicate dimensions, tags, text notes, and Detail Items from the active view, with category-specific modes and an undoable result summary. |
| **Number Auto** | Filters by category and family type, previews elements, sorts by X/Y/Z direction, writes formatted category-grouped numbers, supports Live Pick, and round-trips the list through CSV. |
| **Number Manual** | Numbers interactively picked elements into a chosen instance, built-in, shared, or type parameter with remembered prefixes and digit formatting. |

### Z-Support panel

| Command | What it does |
| --- | --- |
| **Donate Support** | Displays PayPal and PromptPay QR codes and provides access to the P13 GitHub repository. |

## Installation

1. Install a pyRevit version that supports your Autodesk Revit version (2024–2026).
2. Clone or download this repository.
3. Place `P13.extension` in the pyRevit extensions directory:

   ```text
   %APPDATA%\pyRevit\Extensions\P13.extension
   ```

4. Reload pyRevit or restart Revit.
5. Open the **P13** ribbon tab.

Example clone command:

```powershell
git clone https://github.com/permpong13/P13.git "$env:APPDATA\pyRevit\Extensions\P13.extension"
```

If a folder with the same name already exists, back it up or update the existing Git checkout instead of cloning over it.

## Usage and safety

- Test model-modifying commands on a detached or backed-up model before production deployment.
- Review the active view, current selection, and dialog options before confirming an operation.
- Ensure required shared parameters and custom families are available for project-specific workflows.
- Use Revit Undo immediately if a result is not expected.
- Keep pyRevit and this extension updated together when migrating Revit versions.

## Support development

P13.extension is maintained as a practical BIM automation toolkit. Donations help support ongoing development, Revit-version updates, testing, maintenance, and new production tools.

### PayPal

- PayPal username: **@PERMPONGTAWEEKUL**
- Donate securely through PayPal.Me: **[paypal.me/PERMPONGTAWEEKUL](https://www.paypal.me/PERMPONGTAWEEKUL)**

[![Support P13.extension with PayPal](https://img.shields.io/badge/PayPal-Support%20P13.extension-0070BA?logo=paypal&logoColor=white)](https://www.paypal.me/PERMPONGTAWEEKUL)

You can also open **P13 > Z-Support > Donate Support** inside Revit to display the available donation QR codes.

Donations are optional and do not affect access to the extension.

## Repository

- Source code: [github.com/permpong13/P13](https://github.com/permpong13/P13)
- Issues and suggestions: [GitHub Issues](https://github.com/permpong13/P13/issues)

## Author

**Permpong Taweekul (P13)**<br>
BIM Automation Engineer and Software Developer

---

## ภาษาไทย

P13.extension คือชุดเครื่องมือ pyRevit สำหรับ Autodesk Revit 2024–2026 โดยพัฒนาและทดสอบหลักกับ Revit 2026 เพื่อช่วยลดงานซ้ำ เพิ่มความถูกต้องของข้อมูล และสนับสนุนกระบวนการ BIM ในงานจริง ครอบคลุมงานตรวจสอบโมเดล พิกัด การจัดการข้อมูล การนำเข้าและส่งออก Excel งานเอกสาร งาน MEP และเครื่องมือจัดการโครงการ

ผู้ใช้งานสามารถสนับสนุนการพัฒนาและดูแลเครื่องมือได้ผ่าน [PayPal.Me ของ @PERMPONGTAWEEKUL](https://www.paypal.me/PERMPONGTAWEEKUL) หรือเปิดคำสั่ง **P13 > Z-Support > Donate Support** ภายใน Revit
