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
import tempfile
from osgeo import gdal, ogr, osr
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
    psu_geoid=None,
    progress_callback=None,
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

    if not psu_geoid or not str(psu_geoid).isdigit():
        raise ValueError("A numeric PSU GEOID is required for MBTiles output.")
    target_path = os.path.join(output_folder, f"{psu_geoid}_img.mbtiles")
    output_for_gdal = target_path
    cache_file = None

    if shared_clip_cache_dir:
        os.makedirs(shared_clip_cache_dir, exist_ok=True)
        key = _clip_cache_key(geoid_prefix, raster_layer, buffered)
        cache_file = os.path.join(shared_clip_cache_dir, f"{geoid_prefix}_{key}.mbtiles")

        cached_layer = QgsRasterLayer(cache_file, "BASEMAP") if os.path.isfile(cache_file) else None
        if cached_layer is not None and cached_layer.isValid():
            _materialize_cached_clip(cache_file, target_path)
            result_layer = QgsRasterLayer(target_path, "BASEMAP")
            if result_layer.isValid():
                return result_layer
            _safe_remove(target_path)
        output_for_gdal = cache_file

    _safe_remove(output_for_gdal)

    def notify(percent, message):
        if progress_callback is not None:
            progress_callback(float(percent), message)

    def gdal_progress(start, span, message):
        last = [-1]
        def callback(fraction, _message, _data):
            percent = int(start + span * max(0.0, min(1.0, fraction)))
            if percent != last[0]:
                last[0] = percent
                notify(percent, message)
            return 0 if feedback.isCanceled() else 1
        return callback

    notify(0, "Preparing raster clip...")
    # Directly clip/reproject into a bounded GeoTIFF, then encode MBTiles.
    # The temporary files are never added to the QGIS layer tree.
    with tempfile.TemporaryDirectory(prefix="geofasu_mbtiles_") as temp_dir:
        mercator_tif = os.path.join(temp_dir, "mercator.tif")
        mask_geojson = os.path.join(temp_dir, "cutline.geojson")

        # Write the already-buffered barangay polygon as a real OGR cutline.
        # Avoid QGIS Processing's full-resolution GeoTIFF intermediate:
        # on high-resolution municipality rasters it can be enormous.
        driver = ogr.GetDriverByName("GeoJSON")
        cutline_ds = driver.CreateDataSource(mask_geojson)
        if cutline_ds is None:
            raise RuntimeError("Unable to create temporary clipping mask.")
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(32651)
        cutline_layer = cutline_ds.CreateLayer("cutline", srs=srs, geom_type=ogr.wkbUnknown)
        cutline_feature = ogr.Feature(cutline_layer.GetLayerDefn())
        cutline_feature.SetGeometry(ogr.CreateGeometryFromWkt(buffered.asWkt()))
        if cutline_layer.CreateFeature(cutline_feature) != 0:
            raise RuntimeError("Unable to write clipping mask geometry.")
        cutline_feature = None
        cutline_ds = None

        source_path = _physical_source_path(raster_layer)
        source_ds = gdal.Open(source_path)
        if source_ds is None:
            raise RuntimeError(f"Unable to open source raster: {source_path}")
        if source_ds.RasterCount < 1:
            raise RuntimeError("Source raster contains no raster bands.")

        # Estimate the output extent from the small barangay buffer, not
        # from the entire municipality source raster.
        mercator_crs = QgsCoordinateReferenceSystem("EPSG:3857")
        utm_crs = QgsCoordinateReferenceSystem("EPSG:32651")
        to_mercator = QgsCoordinateTransform(
            utm_crs, mercator_crs, QgsProject.instance().transformContext()
        )
        bounds = to_mercator.transformBoundingBox(buffered.boundingBox())
        width = bounds.width()
        height = bounds.height()
        if width <= 0 or height <= 0:
            raise RuntimeError("Invalid projected barangay bounds.")

        # Use a bounded output resolution from the outset. This prevents
        # expensive full-resolution clipping before the downsampling step.
        source_vrt = gdal.AutoCreateWarpedVRT(source_ds, None, "EPSG:3857")
        if source_vrt is None:
            raise RuntimeError("Unable to determine raster output resolution.")
        source_gt = source_vrt.GetGeoTransform()
        native_resolution = min(abs(source_gt[1]), abs(source_gt[5]))
        resolution = max(native_resolution, width / 8192.0, height / 8192.0)
        source_vrt = None
        source_ds = None

        notify(5, "Clipping and reprojecting barangay raster...")
        warped = gdal.Warp(
            mercator_tif, source_path,
            dstSRS="EPSG:3857",
            format="GTiff",
            cutlineDSName=mask_geojson,
            cropToCutline=True,
            outputBounds=[bounds.xMinimum(), bounds.yMinimum(),
                          bounds.xMaximum(), bounds.yMaximum()],
            outputBoundsSRS="EPSG:3857",
            xRes=resolution,
            yRes=resolution,
            multithread=False,
            warpMemoryLimit=128 * 1024 * 1024,
            callback=gdal_progress(5, 70, "Clipping and reprojecting raster..."),
            creationOptions=["TILED=YES", "COMPRESS=NONE", "BIGTIFF=IF_SAFER"],
        )
        if warped is None:
            raise RuntimeError("Unable to reproject clipped basemap to EPSG:3857.")
        warped = None
        if feedback.isCanceled():
            raise RuntimeError("Basemap processing canceled.")
        notify(75, "Encoding MBTiles (JPEG)...")

        tiles = gdal.Translate(
            output_for_gdal, mercator_tif,
            format="MBTILES",
            creationOptions=["TILE_FORMAT=JPEG", "QUALITY=95"],
            callback=gdal_progress(75, 25, "Encoding MBTiles (JPEG)..."),
        )
        if tiles is None:
            raise RuntimeError("Unable to convert clipped basemap to MBTiles.")
        tiles = None
        if feedback.isCanceled():
            raise RuntimeError("Basemap processing canceled.")
        notify(100, "MBTiles created.")

    # Reuse the finished tile archive. Avoid rebuilding overviews per PSU.
    # A later, optional overview pass may be added for very large archives.

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
