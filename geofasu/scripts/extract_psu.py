# -*- coding: utf-8 -*-
"""
Extract features from an existing vector layer by PSU_number using QGIS 'Extract by Expression'.
"""

from qgis.core import QgsProcessingFeedback  # only import core classes needed
import processing  # import as a separate module, not from qgis.core

def extract_by_psu(input_layer, psu_number, feedback=None):
    """
    Filter a vector layer by PSU_number.

    :param input_layer: QgsVectorLayer to filter (output of ExcelToGeometry)
    :param psu_number: int, the PSU_number to filter
    :param feedback: QgsProcessingFeedback instance (optional)
    :return: filtered QgsVectorLayer in memory
    """
    if feedback is None:
        feedback = QgsProcessingFeedback()

    # Build expression
    expr = f'"PSU_number" = {psu_number}'

    # Run Extract by Expression
    result = processing.run(
        "native:extractbyexpression",
        {
            'INPUT': input_layer,
            'EXPRESSION': expr,
            'OUTPUT': 'memory:'
        },
        feedback=feedback
    )

    filtered_layer = result['OUTPUT']
    filtered_layer.setName(f"{input_layer.name()}_PSU_{psu_number}")
    feedback.pushInfo(f"Filtered layer created: {filtered_layer.name()}")

    return filtered_layer