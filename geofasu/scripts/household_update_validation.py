# -*- coding: utf-8 -*-
"""Cross-match CSDBE household CSV records with a merged QGIS layer.

Creates canvas-ready diagnostic layers that explain every match decision.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
import csv
import re

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsVectorLayer,
    QgsWkbTypes,
)

CSV_COMPONENTS = (
    ("PRV", 3),
    ("MUN", 2),
    ("BGY", 3),
    ("EA", 6),
    ("BSN", 4),
    ("HUSN", 4),
    ("HSN", 4),
)


@dataclass(frozen=True)
class HouseholdUpdateValidationResult:
    csv_file: Path
    csv_record_count: int
    csv_unique_geoid_count: int
    layer_feature_count: int
    matched_count: int
    mismatch_count: int
    csv_not_found_count: int
    csv_conflict_count: int
    invalid_geoid_count: int
    diagnostic_layer: QgsVectorLayer
    inconsistent_layer: Optional[QgsVectorLayer]

    @property
    def inconsistency_count(self) -> int:
        return (
            self.mismatch_count
            + self.csv_not_found_count
            + self.csv_conflict_count
            + self.invalid_geoid_count
        )

    @property
    def is_consistent(self) -> bool:
        return self.inconsistency_count == 0


def _canonical_field_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def _field_lookup(layer: QgsVectorLayer) -> Dict[str, str]:
    return {
        _canonical_field_name(field.name()): field.name()
        for field in layer.fields()
    }


def _resolve_layer_field(
    layer: QgsVectorLayer,
    aliases: Iterable[str],
    description: str,
) -> str:
    lookup = _field_lookup(layer)
    for alias in aliases:
        actual = lookup.get(_canonical_field_name(alias))
        if actual:
            return actual

    available = ", ".join(field.name() for field in layer.fields())
    raise ValueError(
        f"The merged GeoPackage does not contain the required {description} field.\n\n"
        f"Accepted names: {', '.join(aliases)}\n\n"
        f"Available fields:\n{available}"
    )


def _clean_numeric_text(value, label: str) -> str:
    if value is None:
        raise ValueError(f"{label} is blank.")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} is blank.")
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    text = re.sub(r"\s+", "", text)
    if not text.isdigit():
        raise ValueError(f"{label} is not numeric: {value!r}")
    return text


def _normalize_numeric_component(value, width: int, label: str) -> str:
    text = _clean_numeric_text(value, label)
    if len(text) > width:
        raise ValueError(f"{label} is longer than {width} digits: {text}")
    return text.zfill(width)


def _normalize_base_geoid(value) -> Tuple[str, str]:
    """Return raw-clean base and PRV+MUN+BGY+EA 14-digit base.

    Supports a 16-digit GEOID containing a two-digit region prefix by removing
    the first two digits. Longer household-like values use their first 14-digit
    base after the same region-prefix handling.
    """
    raw = _clean_numeric_text(value, "Base GEOID")
    working = raw

    if len(working) >= 16:
        # Standard full geographic GEOID may be REG(2)+PRV(3)+MUN(2)+BGY(3)+EA(6).
        working = working[2:]

    if len(working) > 14:
        working = working[:14]

    if len(working) > 14:
        raise ValueError(f"Base GEOID is longer than 14 digits after normalization: {working}")

    return raw, working.zfill(14)


def _normalize_update_code(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    compact = re.sub(r"\s+", "", text)
    return compact.zfill(9) if compact.isdigit() else compact.upper()


def _read_household_csv(csv_file: str) -> Tuple[Dict[str, Set[str]], int]:
    path = Path(csv_file)
    if not path.is_file():
        raise FileNotFoundError(f"The exported CSDBE household CSV was not found:\n{path}")

    records: Dict[str, Set[str]] = {}
    row_count = 0

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("The CSDBE CSV has no header row.")

        header_lookup = {
            _canonical_field_name(name): name
            for name in reader.fieldnames
            if name is not None
        }

        required = [name for name, _ in CSV_COMPONENTS] + ["UPDCODE"]
        missing = [
            name for name in required
            if _canonical_field_name(name) not in header_lookup
        ]
        if missing:
            raise ValueError(
                "The CSDBE CSV is missing required columns:\n"
                + "\n".join(missing)
                + "\n\nAvailable columns:\n"
                + ", ".join(reader.fieldnames)
            )

        for csv_row_number, row in enumerate(reader, start=2):
            if not any(str(value or "").strip() for value in row.values()):
                continue
            try:
                parts = [
                    _normalize_numeric_component(
                        row[header_lookup[_canonical_field_name(name)]],
                        width,
                        name,
                    )
                    for name, width in CSV_COMPONENTS
                ]
            except ValueError as exc:
                raise ValueError(f"Invalid CSDBE CSV row {csv_row_number}: {exc}") from exc

            household_geoid = "".join(parts)
            update_code = _normalize_update_code(
                row[header_lookup[_canonical_field_name("UPDCODE")]]
            )
            records.setdefault(household_geoid, set()).add(update_code)
            row_count += 1

    return records, row_count


def _diagnostic_fields() -> QgsFields:
    fields = QgsFields()
    definitions = (
        ("SOURCE_FID", QVariant.LongLong, 20),
        ("BASE_FIELD", QVariant.String, 40),
        ("BASE_RAW", QVariant.String, 40),
        ("BASE_PAD14", QVariant.String, 14),
        ("BSN_RAW", QVariant.String, 30),
        ("BSN_PAD4", QVariant.String, 4),
        ("HUSN_RAW", QVariant.String, 30),
        ("HUSN_PAD4", QVariant.String, 4),
        ("HSN_RAW", QVariant.String, 30),
        ("HSN_PAD4", QVariant.String, 4),
        ("MERGED_HH_GEOID", QVariant.String, 26),
        ("CSV_LOOKUP_GEOID", QVariant.String, 26),
        ("LAYER_UPDCODE", QVariant.String, 30),
        ("CSV_UPDCODE", QVariant.String, 100),
        ("MATCH_STATUS", QVariant.String, 24),
        ("MATCH_REASON", QVariant.String, 254),
        ("MATCH_PARAMS", QVariant.String, 254),
    )
    for name, field_type, length in definitions:
        fields.append(QgsField(name, field_type, len=length))
    return fields


def _memory_layer_like(source: QgsVectorLayer, name: str) -> QgsVectorLayer:
    geometry_name = QgsWkbTypes.displayString(source.wkbType())
    uri = f"{geometry_name}?crs={source.crs().authid()}"
    layer = QgsVectorLayer(uri, name, "memory")
    if not layer.isValid():
        raise RuntimeError(f"Could not create diagnostic layer: {name}")
    layer.dataProvider().addAttributes(_diagnostic_fields())
    layer.updateFields()
    return layer


def validate_household_update_codes(
    merged_layer: QgsVectorLayer,
    csv_file: str,
) -> HouseholdUpdateValidationResult:
    """Compare CSV UPDCODE with merged Update Codes and build detailed logs."""
    if merged_layer is None or not merged_layer.isValid():
        raise ValueError("The merged GeoPackage layer is invalid.")

    csv_records, csv_row_count = _read_household_csv(csv_file)

    # Prefer GEOID. Fall back to LFS GEOID only when GEOID is unavailable.
    base_geoid_field = _resolve_layer_field(
        merged_layer,
        ("GEOID", "LFS GEOID", "LFS_GEOID"),
        "base GEOID",
    )
    bsn_field = _resolve_layer_field(
        merged_layer,
        ("BSN", "Building Serial Number", "Building Serial No"),
        "BSN",
    )
    husn_field = _resolve_layer_field(
        merged_layer,
        ("HUSN", "Housing Unit Serial Number", "Housing Unit Serial No"),
        "HUSN",
    )
    hsn_field = _resolve_layer_field(
        merged_layer,
        ("HSN", "Household Serial Number", "Household Serial No"),
        "HSN",
    )
    update_code_field = _resolve_layer_field(
        merged_layer,
        ("Update Codes", "Update Code", "UPDCODE", "UPDATE_CODES", "UPDATE_CODE"),
        "Update Codes",
    )

    diagnostic_layer = _memory_layer_like(merged_layer, "CSDBE MATCH LOG - ALL")
    inconsistent_layer = _memory_layer_like(merged_layer, "CSDBE MATCH LOG - NOT MATCHED")
    all_features: List[QgsFeature] = []
    bad_features: List[QgsFeature] = []

    matched_count = mismatch_count = csv_not_found_count = 0
    csv_conflict_count = invalid_geoid_count = 0

    for source_feature in merged_layer.getFeatures():
        base_raw_value = source_feature[base_geoid_field]
        bsn_raw_value = source_feature[bsn_field]
        husn_raw_value = source_feature[husn_field]
        hsn_raw_value = source_feature[hsn_field]
        layer_code = _normalize_update_code(source_feature[update_code_field])

        base_raw = "" if base_raw_value is None else str(base_raw_value).strip()
        bsn_raw = "" if bsn_raw_value is None else str(bsn_raw_value).strip()
        husn_raw = "" if husn_raw_value is None else str(husn_raw_value).strip()
        hsn_raw = "" if hsn_raw_value is None else str(hsn_raw_value).strip()
        base_pad = bsn_pad = husn_pad = hsn_pad = household_geoid = csv_display = ""

        try:
            base_raw_clean, base_pad = _normalize_base_geoid(base_raw_value)
            base_raw = base_raw_clean
            bsn_pad = _normalize_numeric_component(bsn_raw_value, 4, "BSN")
            husn_pad = _normalize_numeric_component(husn_raw_value, 4, "HUSN")
            hsn_pad = _normalize_numeric_component(hsn_raw_value, 4, "HSN")
            household_geoid = base_pad + bsn_pad + husn_pad + hsn_pad
            csv_codes = csv_records.get(household_geoid)

            if csv_codes is None:
                status = "CSV_NOT_FOUND"
                reason = "Constructed 26-digit merged household GEOID does not exist in the CSV index."
                csv_not_found_count += 1
            elif len(csv_codes) > 1:
                status = "CSV_CONFLICT"
                csv_display = "|".join(sorted(csv_codes))
                reason = "The same CSV household GEOID has more than one distinct UPDCODE."
                csv_conflict_count += 1
            else:
                csv_display = next(iter(csv_codes))
                if csv_display == layer_code:
                    status = "MATCH"
                    reason = "Household GEOID and normalized update code are equal."
                    matched_count += 1
                else:
                    status = "CODE_MISMATCH"
                    reason = "Household GEOID exists, but CSV UPDCODE differs from merged Update Codes."
                    mismatch_count += 1

        except ValueError as exc:
            status = "INVALID_GEOID"
            reason = str(exc)
            invalid_geoid_count += 1

        params = (
            f"{base_geoid_field}={base_raw!r}->{base_pad}; "
            f"BSN={bsn_raw!r}->{bsn_pad}; HUSN={husn_raw!r}->{husn_pad}; "
            f"HSN={hsn_raw!r}->{hsn_pad}"
        )
        values = [
            source_feature.id(), base_geoid_field, base_raw, base_pad,
            bsn_raw, bsn_pad, husn_raw, husn_pad, hsn_raw, hsn_pad,
            household_geoid, household_geoid, layer_code, csv_display,
            status, reason, params,
        ]

        log_feature = QgsFeature(diagnostic_layer.fields())
        log_feature.setGeometry(source_feature.geometry())
        log_feature.setAttributes(values)
        all_features.append(log_feature)

        if status != "MATCH":
            bad_feature = QgsFeature(inconsistent_layer.fields())
            bad_feature.setGeometry(source_feature.geometry())
            bad_feature.setAttributes(values)
            bad_features.append(bad_feature)

    diagnostic_layer.dataProvider().addFeatures(all_features)
    diagnostic_layer.updateExtents()

    if bad_features:
        inconsistent_layer.dataProvider().addFeatures(bad_features)
        inconsistent_layer.updateExtents()
    else:
        inconsistent_layer = None

    return HouseholdUpdateValidationResult(
        csv_file=Path(csv_file),
        csv_record_count=csv_row_count,
        csv_unique_geoid_count=len(csv_records),
        layer_feature_count=merged_layer.featureCount(),
        matched_count=matched_count,
        mismatch_count=mismatch_count,
        csv_not_found_count=csv_not_found_count,
        csv_conflict_count=csv_conflict_count,
        invalid_geoid_count=invalid_geoid_count,
        diagnostic_layer=diagnostic_layer,
        inconsistent_layer=inconsistent_layer,
    )