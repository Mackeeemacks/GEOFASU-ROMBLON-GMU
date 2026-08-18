# -*- coding: utf-8 -*-
"""
Helper: Apply QGIS layer style from QML file
"""
import os
from qgis.core import QgsVectorLayer

def load_style(layer: QgsVectorLayer, qml_filename: str):
    """
    Apply a QML style to a QgsVectorLayer.

    Parameters:
        layer (QgsVectorLayer): The layer to style
        qml_filename (str): Filename of QML style (can be relative to plugin folder)
    """
    if not layer or not layer.isValid():
        raise ValueError("Invalid layer provided.")

    # Determine full path relative to plugin folder
    plugin_dir = os.path.dirname(os.path.dirname(__file__))  # geofasu/
    qml_path = os.path.join(plugin_dir, 'qml', qml_filename)

    if not os.path.exists(qml_path):
        raise FileNotFoundError(f"QML style not found: {qml_path}")

    # Apply style
    layer.loadNamedStyle(qml_path)
    layer.triggerRepaint()