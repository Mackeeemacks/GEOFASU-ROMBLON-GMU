# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import QVariant

from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProject,
    QgsSpatialIndex,
    QgsWkbTypes,
)


class ValidateEABarangayVerticesAlgorithm(QgsProcessingAlgorithm):
    EA_LAYER = "EA_LAYER"
    EA_ID_FIELD = "EA_ID_FIELD"
    BARANGAY_LAYER = "BARANGAY_LAYER"
    BARANGAY_ID_FIELD = "BARANGAY_ID_FIELD"
    TOLERANCE = "TOLERANCE"
    OUTPUT = "OUTPUT"
    OUTPUT_POLYGONS = "OUTPUT_POLYGONS"

    def name(self):
        return "validate_ea_barangay_vertices"

    def displayName(self):
        return "Validate EA–Barangay Vertex Snapping"

    def group(self):
        return "1MAP"

    def groupId(self):
        return "onemap"

    def shortHelpString(self):
        return (
            "Validates every vertex of each Enumeration Area (EA) polygon against "
            "its corresponding barangay polygon. The corresponding barangay is "
            "chosen spatially using the largest polygon overlap. The algorithm "
            "creates two outputs: (1) discrepancy points for EA vertices outside "
            "the assigned barangay, and (2) discrepancy polygons showing the exact "
            "parts of EAs which extend outside the barangay boundary."
        )

    def createInstance(self):
        return ValidateEABarangayVerticesAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.EA_LAYER,
                "EA polygon layer",
                [QgsProcessing.TypeVectorPolygon],
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                self.EA_ID_FIELD,
                "EA identifier field (optional)",
                parentLayerParameterName=self.EA_LAYER,
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.BARANGAY_LAYER,
                "Barangay polygon layer",
                [QgsProcessing.TypeVectorPolygon],
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                self.BARANGAY_ID_FIELD,
                "Barangay identifier / PSGC field (optional)",
                parentLayerParameterName=self.BARANGAY_LAYER,
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.TOLERANCE,
                "Tolerance (EA layer units)",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
                minValue=0.0,
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                "EA vertex discrepancies",
                QgsProcessing.TypeVectorPoint,
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_POLYGONS,
                "EA polygon discrepancies",
                QgsProcessing.TypeVectorPolygon,
            )
        )

    @staticmethod
    def _field_text(feature, field_name):
        if not field_name:
            return ""
        try:
            value = feature[field_name]
        except (KeyError, IndexError):
            return ""
        return "" if value is None else str(value)

    @staticmethod
    def _transformed_geometry(feature, transform):
        geom = QgsGeometry(feature.geometry())
        if transform is not None:
            geom.transform(transform)
        return geom

    @staticmethod
    def _as_multipolygon(geometry):
        geom = QgsGeometry(geometry)
        if geom.isNull() or geom.isEmpty():
            return geom

        if QgsWkbTypes.geometryType(geom.wkbType()) != QgsWkbTypes.PolygonGeometry:
            return QgsGeometry()

        if not QgsWkbTypes.isMultiType(geom.wkbType()):
            geom.convertToMultiType()

        return geom

    def processAlgorithm(self, parameters, context, feedback):
        ea_source = self.parameterAsSource(parameters, self.EA_LAYER, context)
        barangay_source = self.parameterAsSource(parameters, self.BARANGAY_LAYER, context)

        if ea_source is None:
            raise QgsProcessingException("Unable to load the EA polygon layer.")
        if barangay_source is None:
            raise QgsProcessingException("Unable to load the barangay polygon layer.")

        ea_id_field = self.parameterAsString(parameters, self.EA_ID_FIELD, context)
        barangay_id_field = self.parameterAsString(
            parameters, self.BARANGAY_ID_FIELD, context
        )
        tolerance = self.parameterAsDouble(parameters, self.TOLERANCE, context)

        point_fields = QgsFields()
        point_fields.append(QgsField("ea_fid", QVariant.LongLong))
        point_fields.append(QgsField("ea_id", QVariant.String, len=120))
        point_fields.append(QgsField("brgy_fid", QVariant.LongLong))
        point_fields.append(QgsField("brgy_id", QVariant.String, len=120))
        point_fields.append(QgsField("vertex_no", QVariant.Int))
        point_fields.append(QgsField("distance", QVariant.Double, len=20, prec=8))
        point_fields.append(QgsField("error_type", QVariant.String, len=40))

        polygon_fields = QgsFields()
        polygon_fields.append(QgsField("ea_fid", QVariant.LongLong))
        polygon_fields.append(QgsField("ea_id", QVariant.String, len=120))
        polygon_fields.append(QgsField("brgy_fid", QVariant.LongLong))
        polygon_fields.append(QgsField("brgy_id", QVariant.String, len=120))
        polygon_fields.append(QgsField("disc_area", QVariant.Double, len=20, prec=8))
        polygon_fields.append(QgsField("pct_ea", QVariant.Double, len=12, prec=4))
        polygon_fields.append(QgsField("error_type", QVariant.String, len=40))

        point_sink, point_sink_id = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            point_fields,
            QgsWkbTypes.Point,
            ea_source.sourceCrs(),
        )
        if point_sink is None:
            raise QgsProcessingException(
                "Could not create the vertex discrepancy output layer."
            )

        polygon_sink, polygon_sink_id = self.parameterAsSink(
            parameters,
            self.OUTPUT_POLYGONS,
            context,
            polygon_fields,
            QgsWkbTypes.MultiPolygon,
            ea_source.sourceCrs(),
        )
        if polygon_sink is None:
            raise QgsProcessingException(
                "Could not create the polygon discrepancy output layer."
            )

        barangay_features = {f.id(): f for f in barangay_source.getFeatures()}
        barangay_index = QgsSpatialIndex()
        for feature in barangay_features.values():
            barangay_index.addFeature(feature)

        to_barangay_crs = None
        to_ea_crs = None
        if ea_source.sourceCrs() != barangay_source.sourceCrs():
            project = QgsProject.instance()
            to_barangay_crs = QgsCoordinateTransform(
                ea_source.sourceCrs(),
                barangay_source.sourceCrs(),
                project,
            )
            to_ea_crs = QgsCoordinateTransform(
                barangay_source.sourceCrs(),
                ea_source.sourceCrs(),
                project,
            )

        total = ea_source.featureCount()
        checked_eas = 0
        checked_vertices = 0
        discrepancy_count = 0
        polygon_discrepancy_count = 0
        unmatched_eas = 0

        for current, ea_feature in enumerate(ea_source.getFeatures()):
            if feedback.isCanceled():
                break

            if total:
                feedback.setProgress(int(current * 100 / total))

            ea_geom = QgsGeometry(ea_feature.geometry())
            if ea_geom.isNull() or ea_geom.isEmpty():
                feedback.reportError(
                    "EA feature {} has empty geometry and was skipped.".format(
                        ea_feature.id()
                    )
                )
                continue

            candidate_bbox = ea_geom.boundingBox()
            if to_barangay_crs is not None:
                candidate_bbox = to_barangay_crs.transformBoundingBox(candidate_bbox)

            candidate_ids = barangay_index.intersects(candidate_bbox)

            best_barangay = None
            best_barangay_geom = None
            best_overlap_area = -1.0

            for candidate_id in candidate_ids:
                barangay_feature = barangay_features.get(candidate_id)
                if barangay_feature is None:
                    continue

                barangay_geom = self._transformed_geometry(
                    barangay_feature, to_ea_crs
                )
                if barangay_geom.isNull() or barangay_geom.isEmpty():
                    continue

                if not ea_geom.boundingBox().intersects(barangay_geom.boundingBox()):
                    continue

                intersection = ea_geom.intersection(barangay_geom)
                overlap_area = (
                    intersection.area()
                    if intersection is not None and not intersection.isEmpty()
                    else 0.0
                )

                if overlap_area > best_overlap_area:
                    best_overlap_area = overlap_area
                    best_barangay = barangay_feature
                    best_barangay_geom = barangay_geom

            vertices = list(ea_geom.vertices())
            checked_eas += 1
            checked_vertices += len(vertices)

            ea_id = self._field_text(ea_feature, ea_id_field)
            ea_area = ea_geom.area()

            if best_barangay is None or best_barangay_geom is None:
                unmatched_eas += 1

                for vertex_no, vertex in enumerate(vertices, start=1):
                    out_feature = QgsFeature(point_fields)
                    out_feature.setGeometry(
                        QgsGeometry.fromPointXY(QgsPointXY(vertex))
                    )
                    out_feature.setAttributes(
                        [
                            ea_feature.id(),
                            ea_id,
                            -1,
                            "",
                            vertex_no,
                            None,
                            "NO_BARANGAY_MATCH",
                        ]
                    )
                    point_sink.addFeature(out_feature, QgsFeatureSink.FastInsert)
                    discrepancy_count += 1

                unmatched_polygon = self._as_multipolygon(ea_geom)
                if not unmatched_polygon.isNull() and not unmatched_polygon.isEmpty():
                    polygon_feature = QgsFeature(polygon_fields)
                    polygon_feature.setGeometry(unmatched_polygon)
                    polygon_feature.setAttributes(
                        [
                            ea_feature.id(),
                            ea_id,
                            -1,
                            "",
                            ea_area,
                            100.0 if ea_area > 0 else None,
                            "NO_BARANGAY_MATCH",
                        ]
                    )
                    polygon_sink.addFeature(
                        polygon_feature, QgsFeatureSink.FastInsert
                    )
                    polygon_discrepancy_count += 1

                continue

            barangay_id = self._field_text(best_barangay, barangay_id_field)

            for vertex_no, vertex in enumerate(vertices, start=1):
                point_geom = QgsGeometry.fromPointXY(QgsPointXY(vertex))

                # intersects() is intentional: a vertex exactly on the barangay
                # boundary is valid, while contains() would reject it.
                inside_or_boundary = best_barangay_geom.intersects(point_geom)

                distance = 0.0
                if not inside_or_boundary:
                    distance = best_barangay_geom.distance(point_geom)

                valid = inside_or_boundary or (
                    tolerance > 0.0 and distance <= tolerance
                )

                if valid:
                    continue

                out_feature = QgsFeature(point_fields)
                out_feature.setGeometry(point_geom)
                out_feature.setAttributes(
                    [
                        ea_feature.id(),
                        ea_id,
                        best_barangay.id(),
                        barangay_id,
                        vertex_no,
                        distance,
                        "VERTEX_OUTSIDE_BARANGAY",
                    ]
                )
                point_sink.addFeature(out_feature, QgsFeatureSink.FastInsert)
                discrepancy_count += 1

            # Polygon discrepancy is EA minus the allowable barangay area.
            # When tolerance is greater than zero, buffer the barangay by that
            # tolerance so the polygon result follows the same tolerance rule
            # as the vertex checks.
            allowed_barangay_geom = QgsGeometry(best_barangay_geom)
            if tolerance > 0.0:
                allowed_barangay_geom = best_barangay_geom.buffer(tolerance, 8)

            outside_geom = ea_geom.difference(allowed_barangay_geom)

            if (
                outside_geom is not None
                and not outside_geom.isNull()
                and not outside_geom.isEmpty()
            ):
                outside_polygon = self._as_multipolygon(outside_geom)

                if not outside_polygon.isNull() and not outside_polygon.isEmpty():
                    discrepancy_area = outside_polygon.area()
                    pct_ea = (
                        (discrepancy_area / ea_area) * 100.0
                        if ea_area > 0
                        else None
                    )

                    polygon_feature = QgsFeature(polygon_fields)
                    polygon_feature.setGeometry(outside_polygon)
                    polygon_feature.setAttributes(
                        [
                            ea_feature.id(),
                            ea_id,
                            best_barangay.id(),
                            barangay_id,
                            discrepancy_area,
                            pct_ea,
                            "EA_OUTSIDE_BARANGAY",
                        ]
                    )
                    polygon_sink.addFeature(
                        polygon_feature, QgsFeatureSink.FastInsert
                    )
                    polygon_discrepancy_count += 1

        feedback.setProgress(100)
        feedback.pushInfo("EA features checked: {}".format(checked_eas))
        feedback.pushInfo("EA vertices checked: {}".format(checked_vertices))
        feedback.pushInfo("Discrepancy vertices: {}".format(discrepancy_count))
        feedback.pushInfo(
            "Polygon discrepancies: {}".format(polygon_discrepancy_count)
        )
        feedback.pushInfo(
            "EA features without barangay match: {}".format(unmatched_eas)
        )

        return {
            self.OUTPUT: point_sink_id,
            self.OUTPUT_POLYGONS: polygon_sink_id,
        }
