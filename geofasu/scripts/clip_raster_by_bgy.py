# -*- coding: utf-8 -*-
"""Fast barangay-basemap clipping for GEOFASU.

Bulk optimizations:
- direct geometry transform/buffer (no Processing reproject/buffer chain)
- source raster layers reused by caller cache
- persistent shared clip cache keyed by source raster + buffered barangay geometry
- cached clips are materialized into PSU folders using hard links when possible
- GDAL multithreaded warping
- no pyramid creation in bulk mode unless explicitly requested
"""

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import processing
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsProcessingFeedback,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)


def _buffered_geometry_utm51(bgy_layer: QgsVectorLayer, distance_m=200.0):
    geometries = [
        QgsGeometry(feature.geometry())
        for feature in bgy_layer.getFeatures()
        if feature.hasGeometry() and not feature.geometry().isNull()
    ]
    if not geometries:
        raise RuntimeError("BARANGAY BOUNDARY contains no usable geometry.")

    merged = QgsGeometry.unaryUnion(geometries)
    if merged.isNull() or merged.isEmpty():
        raise RuntimeError("Could not build a barangay boundary geometry.")

    target_crs = QgsCoordinateReferenceSystem("EPSG:32651")
    source_crs = bgy_layer.crs()
    if source_crs.isValid() and source_crs != target_crs:
        transform = QgsCoordinateTransform(
            source_crs,
            target_crs,
            QgsProject.instance().transformContext(),
        )
        result = merged.transform(transform)
        if result != 0:
            raise RuntimeError("Could not transform barangay boundary to EPSG:32651.")

    buffered = merged.buffer(float(distance_m), 5)
    if buffered.isNull() or buffered.isEmpty():
        raise RuntimeError("Could not create the barangay buffer.")
    return buffered


def _build_mask_from_geometry(buffered: QgsGeometry):
    mask_layer = QgsVectorLayer(
        "Polygon?crs=EPSG:32651",
        "GEOFASU raster clip mask",
        "memory",
    )
    provider = mask_layer.dataProvider()
    feature = QgsFeature()
    feature.setGeometry(QgsGeometry(buffered))
    provider.addFeature(feature)
    mask_layer.updateExtents()
    return mask_layer


def _source_raster(geoid_prefix: str, source_raster_cache=None):
    cache_key = str(geoid_prefix)
    if source_raster_cache is not None:
        cached = source_raster_cache.get(cache_key)
        if cached is not None and cached.isValid():
            return cached

    raster_path = os.path.join("C:/PSA-GIS/BASEMAP", f"{geoid_prefix}_img.gpkg")
    raster_layer = QgsRasterLayer(raster_path, f"{geoid_prefix}_img")
    if not raster_layer.isValid():
        raise FileNotFoundError(f"Raster layer not found or invalid: {raster_path}")

    if source_raster_cache is not None:
        source_raster_cache[cache_key] = raster_layer
    return raster_layer


def _physical_source_path(layer: QgsRasterLayer):
    return str(layer.source() or "").split("|", 1)[0]


def _clip_cache_key(geoid_prefix: str, raster_layer: QgsRasterLayer, buffered: QgsGeometry):
    source_path = _physical_source_path(raster_layer)
    try:
        stat = os.stat(source_path)
        source_sig = f"{os.path.abspath(source_path)}|{stat.st_size}|{stat.st_mtime_ns}"
    except OSError:
        source_sig = os.path.abspath(source_path)

    digest = hashlib.sha256()
    digest.update(str(geoid_prefix).encode("utf-8"))
    digest.update(source_sig.encode("utf-8", errors="ignore"))
    digest.update(bytes(buffered.asWkb()))
    return digest.hexdigest()[:24]


def _safe_remove(path: str):
    for candidate in (path, path + ".aux.xml", path + ".ovr"):
        try:
            if os.path.isfile(candidate):
                os.remove(candidate)
        except OSError:
            pass


def _materialize_cached_clip(cache_file: str, target_file: str):
    """Create PSU-local file cheaply. Hard-link on same volume, copy as fallback."""
    _safe_remove(target_file)
    Path(target_file).parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(cache_file, target_file)
        return "hardlink"
    except OSError:
        shutil.copy2(cache_file, target_file)
        return "copy"


def clip_raster_by_bgy_memory(
    bgy_layer: QgsVectorLayer,
    geoid_prefix: str,
    output_folder: str,
    feedback=None,
    source_raster_cache=None,
    build_overviews=False,
    shared_clip_cache_dir=None,
):
    """Clip basemap to the 200 m buffered barangay boundary.

    When ``shared_clip_cache_dir`` is supplied, identical barangay/source raster
    clips are generated once and then reused by later PSUs and later bulk runs.
    """
    if not bgy_layer or not bgy_layer.isValid():
        raise ValueError("Invalid BARANGAY BOUNDARY layer provided.")

    os.makedirs(output_folder, exist_ok=True)
    feedback = feedback or QgsProcessingFeedback()

    buffered = _buffered_geometry_utm51(bgy_layer, 200.0)
    mask_layer = _build_mask_from_geometry(buffered)
    raster_layer = _source_raster(geoid_prefix, source_raster_cache=source_raster_cache)

    target_path = os.path.join(output_folder, f"{geoid_prefix}_img_clipped.gpkg")
    output_for_gdal = target_path
    cache_file = None

    if shared_clip_cache_dir:
        os.makedirs(shared_clip_cache_dir, exist_ok=True)
        key = _clip_cache_key(geoid_prefix, raster_layer, buffered)
        cache_file = os.path.join(shared_clip_cache_dir, f"{geoid_prefix}_{key}.gpkg")

        cached_layer = QgsRasterLayer(cache_file, "BASEMAP") if os.path.isfile(cache_file) else None
        if cached_layer is not None and cached_layer.isValid():
            _materialize_cached_clip(cache_file, target_path)
            result_layer = QgsRasterLayer(target_path, "BASEMAP")
            if result_layer.isValid():
                return result_layer
            _safe_remove(target_path)
        output_for_gdal = cache_file

    _safe_remove(output_for_gdal)

    params = {
        "INPUT": raster_layer,
        "MASK": mask_layer,
        "SOURCE_CRS": None,
        "TARGET_CRS": None,
        "TARGET_EXTENT": None,
        "NODATA": None,
        "ALPHA_BAND": False,
        "CROP_TO_CUTLINE": True,
        "KEEP_RESOLUTION": True,
        "SET_RESOLUTION": False,
        "X_RESOLUTION": None,
        "Y_RESOLUTION": None,
        "MULTITHREADING": True,
        "OPTIONS": "",
        "DATA_TYPE": 0,
        "EXTRA": "-wo NUM_THREADS=ALL_CPUS",
        "OUTPUT": output_for_gdal,
    }
    processing.run("gdal:cliprasterbymasklayer", params, feedback=feedback)

    if build_overviews:
        try:
            subprocess.run(
                ["gdaladdo", "-r", "average", output_for_gdal, "2", "4", "8", "16"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    if cache_file:
        cache_layer = QgsRasterLayer(cache_file, "BASEMAP")
        if not cache_layer.isValid():
            raise RuntimeError(f"Raster clipping completed but cache output is invalid:\n{cache_file}")
        _materialize_cached_clip(cache_file, target_path)

    clipped_raster_layer = QgsRasterLayer(target_path, "BASEMAP")
    if not clipped_raster_layer.isValid():
        raise RuntimeError(
            "Raster clipping completed but the output could not be loaded:\n"
            f"{target_path}"
        )
    return clipped_raster_layer
