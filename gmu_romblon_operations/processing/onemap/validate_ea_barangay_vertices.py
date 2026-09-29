# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import QVariant

from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
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
            "chosen spatially using the largest polygon overlap. Vertices outside "
            "the assigned barangay are written to a discrepancy point layer."
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

        fields = QgsFields()
        fields.append(QgsField("ea_fid", QVariant.LongLong))
        fields.append(QgsField("ea_id", QVariant.String, len=120))
        fields.append(QgsField("brgy_fid", QVariant.LongLong))
        fields.append(QgsField("brgy_id", QVariant.String, len=120))
        fields.append(QgsField("vertex_no", QVariant.Int))
        fields.append(QgsField("distance", QVariant.Double, len=20, prec=8))
        fields.append(QgsField("error_type", QVariant.String, len=40))

        sink, sink_id = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            QgsWkbTypes.Point,
            ea_source.sourceCrs(),
        )
        if sink is None:
            raise QgsProcessingException("Could not create the discrepancy output layer.")

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

            if best_barangay is None or best_barangay_geom is None:
                unmatched_eas += 1
                for vertex_no, vertex in enumerate(vertices, start=1):
                    out_feature = QgsFeature(fields)
                    out_feature.setGeometry(QgsGeometry.fromPointXY(vertex))
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
                    sink.addFeature(out_feature, QgsFeatureSink.FastInsert)
                    discrepancy_count += 1
                continue

            barangay_id = self._field_text(best_barangay, barangay_id_field)

            for vertex_no, vertex in enumerate(vertices, start=1):
                point_geom = QgsGeometry.fromPointXY(vertex)

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

                out_feature = QgsFeature(fields)
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
                sink.addFeature(out_feature, QgsFeatureSink.FastInsert)
                discrepancy_count += 1

        feedback.setProgress(100)
        feedback.pushInfo("EA features checked: {}".format(checked_eas))
        feedback.pushInfo("EA vertices checked: {}".format(checked_vertices))
        feedback.pushInfo("Discrepancy vertices: {}".format(discrepancy_count))
        feedback.pushInfo("EA features without barangay match: {}".format(unmatched_eas))

        return {self.OUTPUT: sink_id}
