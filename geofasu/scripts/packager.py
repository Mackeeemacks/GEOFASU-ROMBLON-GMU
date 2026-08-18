# -*- coding: utf-8 -*-
import os
import shutil
from qgis.core import (
    QgsVectorLayer, QgsRasterLayer, QgsProject, QgsCoordinateReferenceSystem
)

def package_layers_for_qfield(layers, output_folder, project_name="_qfield.qgs", feedback=None):
    """
    Copy layers to output_folder and create a QField-ready project.
    
    Args:
        layers (list[QgsVectorLayer|QgsRasterLayer]): Layers to include
        output_folder (str): Destination folder for layers and project
        project_name (str): Name of the output QGS project
        feedback: Optional QgsProcessingFeedback-like object
    
    Returns:
        str: Full path to the QField-ready project
    """
    if not layers:
        raise Exception("No layers provided for packaging!")

    os.makedirs(output_folder, exist_ok=True)

    project = QgsProject.instance()
    project.clear()  # clear any existing project

    root = project.layerTreeRoot()

    # Maintain the same group structure as in QGIS (optional)
    group_map = {}

    for layer in layers:
        if not layer or not layer.isValid():
            if feedback:
                feedback.pushInfo(f"⚠️ Skipped invalid layer: {layer.name() if layer else 'None'}")
            continue

        src_path = layer.source()
        if not os.path.exists(src_path):
            if feedback:
                feedback.pushInfo(f"⚠️ Source file not found, skipped: {src_path}")
            continue

        # Copy layer file to output_folder
        dst_path = os.path.join(output_folder, os.path.basename(src_path))
        shutil.copy(src_path, dst_path)

        # Load the copied layer into the project
        if layer.type() == QgsVectorLayer.VectorLayer:
            new_layer = QgsVectorLayer(dst_path, layer.name(), "ogr")
        else:
            new_layer = QgsRasterLayer(dst_path, layer.name())

        if not new_layer.isValid():
            if feedback:
                feedback.pushInfo(f"⚠️ Copied layer invalid: {dst_path}")
            continue

        # Set CRS to EPSG:4326
        new_layer.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

        # Copy style from original layer
        try:
            new_layer.loadNamedStyle(layer.styleManager().currentStyle())
            new_layer.triggerRepaint()
        except Exception as e:
            if feedback:
                feedback.pushInfo(f"⚠️ Could not copy style for {layer.name()}: {e}")

        # Maintain group if any
        parent_group = layer.name()  # simple example, can be customized
        group = group_map.get(parent_group)
        if not group:
            group = root.addGroup(parent_group)
            group_map[parent_group] = group

        QgsProject.instance().addMapLayer(new_layer, False)
        group.addLayer(new_layer)

        if feedback:
            feedback.pushInfo(f"✅ Layer copied: {dst_path}")

    # Copy snapping configuration from existing project
    snap_cfg = QgsProject.instance().snappingConfig()
    snap_cfg.setEnabled(True)
    snap_cfg.setType(snap_cfg.type())
    snap_cfg.setMode(snap_cfg.mode())
    snap_cfg.setTolerance(snap_cfg.tolerance())
    snap_cfg.setUnits(snap_cfg.units())
    snap_cfg.setIntersectionSnapping(snap_cfg.intersectionSnapping())
    project.setSnappingConfig(snap_cfg)

    # Set project CRS
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

    # Save QField-ready project
    project_path = os.path.join(output_folder, project_name)
    project.write(project_path)

    if feedback:
        feedback.pushInfo(f"✅ QField project created: {project_path}")

    return project_path