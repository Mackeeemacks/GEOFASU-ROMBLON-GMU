# -*- coding: utf-8 -*-
"""
Excel to Geometry  (merge Sample + Replacement, separate PSU as table, 2025-10-10 v9)

• Reads the primary sheet “Sample SSU” or, if missing, “AONCR-SAMPLE HH”.
• Reads optionally the “Replacement SSU” sheet (merged to main output).
• Reads optionally the “Sample PSU” sheet and outputs it as a non-spatial table.
• Detects the WKT column flexibly (ignores spaces/case, not fixed to column U).
• Converts single-point MULTIPOINT to POINT.
• Splits multi-point MULTIPOINTs into separate POINT features.
• Main output: POINT geometries; PSU output: table (no geometry).
• Compatible with QGIS 3.22 – 3.36.
"""
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing, QgsProcessingAlgorithm, QgsProcessingException,
    QgsProcessingParameterFile, QgsProcessingParameterCrs,
    QgsProcessingParameterFeatureSink, QgsFeatureSink,
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY, QgsWkbTypes
)
import os, re


class ExcelToGeometry(QgsProcessingAlgorithm):
    INPUT, CRS, OUTPUT_MAIN, OUTPUT_PSU = 'EXCEL', 'CRS', 'OUTPUT_MAIN', 'OUTPUT_PSU'

    # ---------- metadata ----------
    def tr(self, m): return QCoreApplication.translate('ExcelToGeometry', m)
    def name(self):        return 'excel_to_geometry'
    def displayName(self): return self.tr('Excel to Geometry (Sample + PSU Table)')
    def group(self):       return ''
    def groupId(self):     return ''
    def createInstance(self): return ExcelToGeometry()
    def shortHelpString(self):
        return self.tr(
            'Pick an Excel file (*.xlsx). The algorithm merges “Sample SSU” (or fallback '
            '“AONCR-SAMPLE HH”) with “Replacement SSU” into a POINT layer. If “Sample PSU” '
            'exists, it is loaded as a separate attribute-only table without geometry.'
        )

    # ---------- parameters ----------
    def initAlgorithm(self, _config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT,
                self.tr('Excel file (*.xlsx)'),
                behavior=QgsProcessingParameterFile.File,
                extension='xlsx'
            )
        )
        self.addParameter(
            QgsProcessingParameterCrs(
                self.CRS,
                self.tr('CRS for numeric coordinates (ignored for real WKT)'),
                defaultValue='EPSG:4326'
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_MAIN,
                self.tr('Output layer (Sample SSU + Replacement)')
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_PSU,
                self.tr('Output table (Sample PSU)'),
                optional=True
            )
        )

    # ---------- helpers ----------
    def detect_wkt_field(self, layer):
        for f in layer.fields():
            if 'wkt' in f.name().strip().lower():
                return f.name()
        return None

    def to_geom(self, txt, num_pat):
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

    def process_layer(self, layer, wkt_field, sink, feedback, num_pat):
        total = layer.featureCount()
        step = 100.0 / max(total, 1)
        done = imported = skipped = 0

        for feat in layer.getFeatures():
            if feedback.isCanceled():
                break
            done += 1
            geom = self.to_geom(feat[wkt_field], num_pat)
            if geom.isNull():
                skipped += 1
                feedback.setProgress(int(done * step))
                continue

            if geom.isMultipart():
                for pt in geom.asMultiPoint():
                    nf = QgsFeature(feat)
                    nf.setGeometry(QgsGeometry.fromPointXY(pt))
                    sink.addFeature(nf, QgsFeatureSink.FastInsert)
                    imported += 1
            else:
                nf = QgsFeature(feat)
                nf.setGeometry(geom)
                sink.addFeature(nf, QgsFeatureSink.FastInsert)
                imported += 1

            feedback.setProgress(int(done * step))

        return imported, skipped

    # ---------- core ----------
    def processAlgorithm(self, params, context, feedback):
        path = self.parameterAsFile(params, self.INPUT, context)
        if not os.path.isfile(path):
            raise QgsProcessingException(self.tr('File not found: ') + path)

        crs = self.parameterAsCrs(params, self.CRS, context)
        safe_path = path.replace('\\', '/')
        num_pat = re.compile(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?')

        primary_sheets = ['Sample SSU', 'Selected Samples', 'AONCR-SAMPLE HH']
        replacement_sheet = 'Replacement SSU'
        psu_sheet = 'Sample PSU'

        # --- Load and process primary (Sample SSU + Replacement)
        primary_layer = None
        layers, wkt_fields = [], {}
        for name in primary_sheets:
            uri = f'{safe_path}|layername={name}'
            lyr = QgsVectorLayer(uri, name.lower().replace(' ', '_'), 'ogr')
            if lyr.isValid():
                wkt_field = self.detect_wkt_field(lyr)
                if not wkt_field:
                    raise QgsProcessingException(self.tr(f'Column “WKT” not found in {name}.'))
                primary_layer = lyr
                layers.append(lyr)
                wkt_fields[lyr] = wkt_field
                feedback.pushInfo(self.tr(f'Using primary sheet: "{name}"'))
                break
        if primary_layer is None:
            raise QgsProcessingException(
                self.tr('No valid primary sheet found. Tried: ') + ', '.join(primary_sheets)
            )

        # Load optional replacement sheet
        uri = f'{safe_path}|layername={replacement_sheet}'
        lyr = QgsVectorLayer(uri, replacement_sheet.lower().replace(' ', '_'), 'ogr')
        if lyr.isValid():
            wkt_field = self.detect_wkt_field(lyr)
            if not wkt_field:
                raise QgsProcessingException(self.tr(f'Column “WKT” not found in {replacement_sheet}.'))
            layers.append(lyr)
            wkt_fields[lyr] = wkt_field
        else:
            feedback.pushInfo(self.tr('“Replacement SSU” sheet not found, skipping.'))

        # Create main sink (POINT)
        geom_type = QgsWkbTypes.Point
        sink_main, dest_main = self.parameterAsSink(
            params, self.OUTPUT_MAIN, context,
            layers[0].fields(), geom_type, crs
        )
        if sink_main is None:
            raise QgsProcessingException(self.invalidSinkError(params, self.OUTPUT_MAIN))

        # Process all SSU-related layers
        total_imported = total_skipped = 0
        for lyr in layers:
            imp, skip = self.process_layer(lyr, wkt_fields[lyr], sink_main, feedback, num_pat)
            total_imported += imp
            total_skipped += skip
        feedback.pushInfo(self.tr(f'Main layer: imported {total_imported}, skipped {total_skipped}.'))

        # --- Load “Sample PSU” as non-spatial table if exists
        uri = f'{safe_path}|layername={psu_sheet}'
        psu_lyr = QgsVectorLayer(uri, psu_sheet.lower().replace(' ', '_'), 'ogr')
        dest_psu = None
        if psu_lyr.isValid():
            sink_psu, dest_psu = self.parameterAsSink(
                params, self.OUTPUT_PSU, context,
                psu_lyr.fields(), QgsWkbTypes.NoGeometry, crs
            )
            if sink_psu is None:
                raise QgsProcessingException(self.invalidSinkError(params, self.OUTPUT_PSU))
            for feat in psu_lyr.getFeatures():
                sink_psu.addFeature(feat, QgsFeatureSink.FastInsert)
            feedback.pushInfo(self.tr(f'PSU sheet loaded as non-spatial table ({psu_lyr.featureCount()} rows).'))
        else:
            feedback.pushInfo(self.tr('“Sample PSU” sheet not found, skipping.'))

        results = {self.OUTPUT_MAIN: dest_main}
        if dest_psu:
            results[self.OUTPUT_PSU] = dest_psu
        return results
