# -*- coding: utf-8 -*-
import os
import subprocess
from qgis.core import (
    QgsRasterLayer,
    QgsVectorLayer,
    QgsProject,
    QgsProcessingFeedback,
    QgsCoordinateReferenceSystem
)
import processing

def clip_raster_by_bgy_memory(bgy_layer: QgsVectorLayer, geoid_prefix: str, output_folder: str):
    """
    Clip a raster layer by 200m buffer around the BARANGAY BOUNDARY.
    Buffer is memory-only. Output raster is saved as GeoPackage.
    Also builds overviews (pyramids) for faster rendering.

    Parameters:
        bgy_layer (QgsVectorLayer): Polygon layer (BARANGAY BOUNDARY)
        geoid_prefix (str): e.g., '05911'
        output_folder (str): folder to save clipped raster
    Returns:
        QgsRasterLayer: clipped raster loaded in QGIS
    """

    if not bgy_layer or not bgy_layer.isValid():
        raise ValueError("Invalid BARANGAY BOUNDARY layer provided.")

    os.makedirs(output_folder, exist_ok=True)
    feedback = QgsProcessingFeedback()

    # --- Reproject to a projected CRS (meters) if needed ---
    target_crs = QgsCoordinateReferenceSystem("EPSG:32651")  # UTM Zone 51N
    if bgy_layer.crs().isGeographic():
        result = processing.run(
            "native:reprojectlayer",
            {
                'INPUT': bgy_layer,
                'TARGET_CRS': target_crs,
                'OUTPUT': 'memory:'
            },
            feedback=feedback
        )
        bgy_proj = result['OUTPUT']
    else:
        bgy_proj = bgy_layer

    # --- Buffer BARANGAY BOUNDARY by 200 meters (memory-only) ---
    buffer_result = processing.run(
        "native:buffer",
        {
            'INPUT': bgy_proj,
            'DISTANCE': 200,
            'SEGMENTS': 5,
            'DISSOLVE': True,
            'OUTPUT': 'memory:'
        },
        feedback=feedback
    )
    buffer_layer = buffer_result['OUTPUT']
    QgsProject.instance().addMapLayer(buffer_layer, False)  # hidden

    # --- Load raster from BASEMAP ---
    raster_path = os.path.join("C:/PSA-GIS/BASEMAP", f"{geoid_prefix}_img.gpkg")
    raster_layer = QgsRasterLayer(raster_path, f"{geoid_prefix}_img")
    if not raster_layer.isValid():
        raise FileNotFoundError(f"Raster layer not found or invalid: {raster_path}")

    # --- Clip raster using buffer polygon ---
    clipped_raster_path = os.path.join(output_folder, f"{geoid_prefix}_img_clipped.gpkg")
    processing.run(
        "gdal:cliprasterbymasklayer",
        {
            'INPUT': raster_layer,
            'MASK': buffer_layer,
            'CROP_TO_CUTLINE': True,
            'OUTPUT': clipped_raster_path
        },
        feedback=feedback
    )

    # --- Build overviews for faster rendering ---
    try:
        subprocess.run([
            "gdaladdo",
            "-r", "average",              # resampling method
            clipped_raster_path,
            "2", "4", "8", "16", "32"    # overview levels
        ], check=True)
    except Exception as e:
        print(f"Warning: could not build overviews: {str(e)}")

    # --- Load clipped raster into QGIS ---
    clipped_raster_layer = QgsRasterLayer(clipped_raster_path, "BASEMAP")
    return clipped_raster_layer