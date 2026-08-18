# -*- coding: utf-8 -*-
"""
Helper functions to load Excel sheets and generate POINT geometries
and optionally a PSU non-spatial table.
"""

import os, re
from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY, QgsFeatureSink

def detect_wkt_field(layer):
    """Detect the WKT field in the given layer."""
    for f in layer.fields():
        if 'wkt' in f.name().strip().lower():
            return f.name()
    return None

def to_geom(txt, num_pat):
    """Convert WKT text to QgsGeometry; fallback to numeric coordinates."""
    txt = (txt or '').strip()
    g = QgsGeometry.fromWkt(txt)
    if not g.isNull():
        return g
    nums = num_pat.findall(txt)
    if len(nums) >= 2:
        try:
            return QgsGeometry.fromPointXY(QgsPointXY(float(nums[0]), float(nums[1])))
        except ValueError:
            pass
    return QgsGeometry()

def process_layer(layer, wkt_field, sink, feedback, num_pat, psu_number=None):
    """Process a single layer and insert features with geometry and attributes."""
    total = layer.featureCount()
    step = 100.0 / max(total, 1)
    done = imported = skipped = 0

    for feat in layer.getFeatures():
        if feedback and hasattr(feedback, "isCanceled") and feedback.isCanceled():
            break
        done += 1

        # Filter by PSU_number if provided
        if psu_number is not None:
            if "PSU_number" in feat.fields().names():
                if feat["PSU_number"] != psu_number:
                    continue
            else:
                continue

        geom = to_geom(feat[wkt_field], num_pat)
        if geom.isNull():
            skipped += 1
            if feedback:
                feedback.setProgress(int(done * step))
            continue

        # Split multipart points into single POINTs
        if geom.isMultipart():
            for pt in geom.asMultiPoint():
                nf = QgsFeature(sink.fields())
                nf.setAttributes(feat.attributes())
                nf.setGeometry(QgsGeometry.fromPointXY(pt))
                sink.addFeature(nf, QgsFeatureSink.FastInsert)
                imported += 1
        else:
            nf = QgsFeature(sink.fields())
            nf.setAttributes(feat.attributes())
            nf.setGeometry(geom)
            sink.addFeature(nf, QgsFeatureSink.FastInsert)
            imported += 1

        if feedback:
            feedback.setProgress(int(done * step))

    return imported, skipped

def excel_to_geometry(path, sink_main, sink_psu=None, psu_number=None, feedback=None):
    """
    Process Excel file, generate POINT features into sink_main,
    optionally fill sink_psu with Sample PSU table.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")

    safe_path = path.replace("\\", "/")
    num_pat = re.compile(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?')

    primary_sheets = ['Sample SSU', 'Selected Samples', 'AONCR-SAMPLE HH']
    replacement_sheet = 'Replacement SSU'
    psu_sheet = 'Sample PSU'

    layers, wkt_fields = [], {}

    # --- Load primary sheet
    primary_layer = None
    for name in primary_sheets:
        uri = f'{safe_path}|layername={name}'
        lyr = QgsVectorLayer(uri, name.lower().replace(' ', '_'), 'ogr')
        if lyr.isValid():
            wkt_field = detect_wkt_field(lyr)
            if not wkt_field:
                raise Exception(f'Column “WKT” not found in {name}.')
            primary_layer = lyr
            layers.append(lyr)
            wkt_fields[lyr] = wkt_field
            break
    if not primary_layer:
        raise Exception(f"No valid primary sheet found. Tried: {primary_sheets}")

    # --- Load replacement sheet if exists
    uri = f'{safe_path}|layername={replacement_sheet}'
    lyr = QgsVectorLayer(uri, replacement_sheet.lower().replace(' ', '_'), 'ogr')
    if lyr.isValid():
        wkt_field = detect_wkt_field(lyr)
        if not wkt_field:
            raise Exception(f'Column “WKT” not found in {replacement_sheet}.')
        layers.append(lyr)
        wkt_fields[lyr] = wkt_field

    # --- Process main layers
    total_imported = total_skipped = 0
    for lyr in layers:
        imp, skip = process_layer(lyr, wkt_fields[lyr], sink_main, feedback, num_pat, psu_number)
        total_imported += imp
        total_skipped += skip
    if feedback:
        feedback.pushInfo(f'Main layer: imported {total_imported}, skipped {total_skipped}.')

    # --- Optional PSU table
    if sink_psu:
        uri = f'{safe_path}|layername={psu_sheet}'
        psu_lyr = QgsVectorLayer(uri, psu_sheet.lower().replace(' ', '_'), 'ogr')
        if psu_lyr.isValid():
            for feat in psu_lyr.getFeatures():
                if psu_number is None or feat["PSU_number"] == psu_number:
                    nf = QgsFeature(sink_psu.fields())
                    nf.setAttributes(feat.attributes())
                    sink_psu.addFeature(nf, QgsFeatureSink.FastInsert)
            if feedback:
                feedback.pushInfo(f'PSU table loaded ({psu_lyr.featureCount()} rows).')