# GEOFASU

**GEOFASU** is a QGIS plugin for LFS geographic pre-processing, QField field package preparation, and post-processing of validated GeoPackages with optional CSDBE cross-validation.

## 1. Prerequisites

Install the following before using GEOFASU:

- **QGIS 3.40.10 LTR**
- **Microsoft Excel / compatible `.xlsx` file**
- **QField** on the field device, when field packaging is required
- **CSPro 7.7**, only when CSDBE cross-validation will be used

For CSDBE processing, GEOFASU expects CSPro 7.7 at:

```text
C:\Program Files (x86)\CSPro 7.7\
```

---

# 2. Required File Structure

GEOFASU uses the following standard working directory:

```text
C:\PSA-GIS\
└── <PROVINCE>\
    └── GEOFASU\
        └── <YEAR>\
            └── <MONTH>\
                │
                ├── CADCS.pen
                │
                ├── FIELD VALIDATION OUTPUT\
                │   ├── DATA\
                │   │   ├── <sample>.csdbe
                │   │   ├── <sample>.csdbe
                │   │   └── ...
                │   │
                │   └── GEOPACKAGES\
                │       ├── PSU_10\
                │       │   └── <validated>.gpkg
                │       ├── PSU_11\
                │       │   └── <validated>.gpkg
                │       └── ...
                │
                ├── QField Packages\
                │   ├── PSU_10\
                │   ├── PSU_11\
                │   └── ...
                │
                └── GEOMS\
```

Example:

```text
C:\PSA-GIS\
└── ROMBLON\
    └── GEOFASU\
        └── 2026\
            └── JULY\
                ├── CADCS.pen
                ├── FIELD VALIDATION OUTPUT\
                │   ├── DATA\
                │   └── GEOPACKAGES\
                ├── QField Packages\
                └── GEOMS\
```

GEOFASU automatically determines the **Province, Year, and Month** from the LFS Sample Excel file.

---

# 3. Required Input Files

## LFS Sample Excel

Use the official LFS sample workbook containing:

```text
Sample SSU
Replacement SSU
```

Example:

```text
2026 LFS Jul Sample_Romblon_R7-22(RG2).xlsx
```

The Excel file may be selected from any location using **Browse**.

## CADCS.pen

Required only when **CSDBE processing** is enabled.

Copy the current rollout's:

```text
CADCS.pen
```

into the rollout folder:

```text
C:\PSA-GIS\<PROVINCE>\GEOFASU\<YEAR>\<MONTH>\CADCS.pen
```

Example:

```text
C:\PSA-GIS\ROMBLON\GEOFASU\2026\JULY\CADCS.pen
```

Always use the `CADCS.pen` belonging to the **same rollout** as the CSDBE files.

## CSDBE Files

Place the CSDBE files under:

```text
...\FIELD VALIDATION OUTPUT\DATA\
```

Example:

```text
JULY\
└── FIELD VALIDATION OUTPUT\
    └── DATA\
        ├── <expected file 1>.csdbe
        ├── <expected file 2>.csdbe
        └── ...
```

All expected CSDBE files must be present when CSDBE processing is enabled.

---

# 4. PRE-PROCESSING

Open:

```text
GEOFASU
→ PRE-PROCESS
```

### Step 1 — Read the Sample List

1. Click **Browse**.
2. Select the official LFS Sample Excel file.
3. Click **Read Sample List**.

GEOFASU automatically determines the Province, Year, Month, and working folders.

### Step 2 — Select PSU

Select the PSU to process.

Example:

```text
PSU_51
```

### Step 3 — Generate the PSU Project

Run the geometry/project generation.

The resulting QGIS project should normally contain:

```text
Selected LFS SSU
BARANGAY BOUNDARY
BASEMAP
```

### Step 4 — Inspect for QField

Under **QField Package**, click:

```text
Inspect Current Project
```

All required layers should show:

```text
Ready
```

There should be:

```text
Errors: 0
```

### Step 5 — Package for QField

Keep the recommended options checked:

```text
☑ Validate project before packaging
☑ Copy styles and project resources
☑ Preserve snapping configuration
☑ Make packaged project paths relative
```

Recommended extent:

```text
Barangay boundary
```

Click:

```text
Package for QField
```

The package is automatically created under:

```text
...\QField Packages\PSU_<NUMBER>\
```

Example:

```text
QField Packages\
└── PSU_51\
    ├── *_qfield.qgs
    ├── data.gpkg
    ├── reference\
    ├── basemap\
    └── package_manifest.json
```

Copy the **whole PSU folder** to the QField device.

Do not copy only `data.gpkg` or the `.qgs` file.

---

# 5. POST-PROCESSING

After field validation, copy the validated GeoPackages to:

```text
...\FIELD VALIDATION OUTPUT\GEOPACKAGES\
```

Example:

```text
GEOPACKAGES\
├── PSU_10\
│   └── <validated PSU 10>.gpkg
├── PSU_11\
│   └── <validated PSU 11>.gpkg
└── PSU_51\
    └── <validated PSU 51>.gpkg
```

Then open:

```text
GEOFASU
→ POST-PROCESS
```

### Step 1 — Read the Sample List

1. Select the same LFS Sample Excel file.
2. Click **Read Sample List**.

GEOFASU automatically detects the working folders and available GeoPackages.

### Step 2 — CSDBE Processing — Optional

If CSDBE validation is required, enable:

```text
☑ Enable CSDBE processing and household/update-code cross-validation
```

Before continuing, make sure:

```text
<MONTH>\
├── CADCS.pen
└── FIELD VALIDATION OUTPUT\
    └── DATA\
        ├── *.csdbe
        └── ...
```

is complete.

If a CSPro dictionary is required, follow the GEOFASU prompt to export/save the dictionary.

Then click:

```text
Process CSDBE
```

Wait for CSDBE processing to complete successfully.

If CSDBE validation is not required, leave the option unchecked.

### Step 3 — Load and Validate

Click:

```text
Load / Validate GeoPackages
```

GEOFASU will:

```text
Create PSU Master Table
        ↓
Merge GeoPackages
        ↓
Validate GEOIDs
        ↓
Validate CSDBE update codes (if enabled)
        ↓
Identify invalid/missing records
        ↓
Generate GEOMS outputs
```

---

# 6. Review the Results

Check the QGIS Layers panel after processing.

Typical groups are:

```text
INVALID FEATURES
├── MISSING SSUs
├── ORIGINAL SAMPLES WITH NO UPDATE CODES
└── CSDBE MATCH LOG - NOT MATCHED
```

```text
MERGED FEATURES
├── MERGED_GEOMS
└── PSU_MASTER_TABLE
```

When CSDBE processing is enabled:

```text
DATA
├── CSDBE HOUSEHOLDS
└── CSDBE MATCH LOG - ALL
```

Review **INVALID FEATURES** before accepting the final output.

Final files are written to:

```text
C:\PSA-GIS\<PROVINCE>\GEOFASU\<YEAR>\<MONTH>\GEOMS\
```

---

# 7. Quick Workflow

## Pre-Process

```text
Select LFS Excel
      ↓
Read Sample List
      ↓
Select PSU
      ↓
Generate Geometry / Project
      ↓
Inspect Current Project
      ↓
Errors = 0
      ↓
Package for QField
      ↓
Copy PSU folder to field device
```

## Post-Process

```text
Copy validated GPKGs to GEOPACKAGES
      ↓
Copy CSDBEs to DATA (if required)
      ↓
Copy current CADCS.pen to rollout folder
      ↓
Read Sample List
      ↓
Process CSDBE (optional)
      ↓
Load / Validate GeoPackages
      ↓
Review INVALID FEATURES
      ↓
Check GEOMS output
```

---

## Supported Environment

```text
QGIS     : 3.40.10 LTR
OS       : Windows 10/11 64-bit
CSPro    : 7.7 (for CSDBE processing)
QField   : Required for field deployment
```

**Important:** Always use the Sample Excel, CADCS.pen, CSDBE files, and validated GeoPackages belonging to the same LFS rollout.