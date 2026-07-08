# P13.extension

P13.extension is a pyRevit toolset for BIM automation in Autodesk Revit 2026. It groups production utilities for model checking, shared coordinates, annotation cleanup, data exchange, model management, MEP workflows, and repetitive documentation tasks into one Revit ribbon tab.

The extension is developed and maintained by Permpong Taweekul (P13) for practical use in live BIM projects.

## Compatibility

- Autodesk Revit 2026
- pyRevit with Revit 2026 support
- Windows
- Revit 2026 / .NET 8 runtime

Some commands integrate with Microsoft Excel or other project-specific data sources. Those commands may require the relevant desktop application, file access, or project parameters.

## Main features

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

## Installation

1. Install a pyRevit version that supports Revit 2026.
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

P13.extension คือชุดเครื่องมือ pyRevit สำหรับ Autodesk Revit 2026 พัฒนาขึ้นเพื่อลดงานซ้ำ เพิ่มความถูกต้องของข้อมูล และสนับสนุนกระบวนการ BIM ในงานจริง ครอบคลุมงานตรวจสอบโมเดล พิกัด การจัดการข้อมูล การนำเข้าและส่งออก Excel งานเอกสาร งาน MEP และเครื่องมือจัดการโครงการ

ผู้ใช้งานสามารถสนับสนุนการพัฒนาและดูแลเครื่องมือได้ผ่าน [PayPal.Me ของ @PERMPONGTAWEEKUL](https://www.paypal.me/PERMPONGTAWEEKUL) หรือเปิดคำสั่ง **P13 > Z-Support > Donate Support** ภายใน Revit
