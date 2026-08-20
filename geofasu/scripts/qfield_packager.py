# -*- coding: utf-8 -*-
"""
GEOFASU QField cable package engine.

Milestone 2:
- Packages the current saved PSU project into:
    ...\QField Packages\PSU_<n>
- Converts the generated selected-SSU project layer to offline data.gpkg.
- Copies vector reference datasets read-only.
- Copies raster/basemap datasets and common sidecar files.
- Saves a portable relative-path QGIS project.
- Preserves the source desktop project by reloading it after packaging.
- Writes package_manifest.json.

This is a focused GEOFASU implementation using QGIS APIs. It does not
require QFieldSync to be installed.
"""

from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
import json
import os
import re
import shutil

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsMapLayer,
    QgsOfflineEditing,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication


FID_NULL = -4294967296


@dataclass(frozen=True)
class PackageLayerResult:
    layer_name: str
    layer_type: str
    action: str
    packaged_source: str


@dataclass(frozen=True)
class QFieldPackageResult:
    package_folder: str
    packaged_project_file: str
    offline_database: str
    manifest_file: str
    packaged_layers: list[PackageLayerResult]


def _clean_provider_path(source: str) -> str:
    text = str(source or "").strip()
    return text.split("|", 1)[0] if "|" in text else text


def _uri_suffix(source: str) -> str:
    text = str(source or "")
    if "|" not in text:
        return ""
    return "|" + text.split("|", 1)[1]


def _safe_filename(text: str, fallback: str = "layer") -> str:
    value = re.sub(r'[<>:"/\\|?*]+', "_", str(text or "").strip())
    value = re.sub(r"\s+", "_", value).strip("._ ")
    return value or fallback


def _is_editable_lfs_layer(layer: QgsMapLayer) -> bool:
    if not isinstance(layer, QgsVectorLayer):
        return False

    name = layer.name().upper()

    return (
        "SELECTED_SSU" in name
        or "SELECTED SSU" in name
    )


def _copy_file(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _copy_shapefile_family(source: Path, target_folder: Path) -> Path:
    target_folder.mkdir(parents=True, exist_ok=True)
    stem = source.stem

    for item in source.parent.glob(stem + ".*"):
        if item.is_file():
            shutil.copy2(
                item,
                target_folder / item.name
            )

    copied_shp = target_folder / source.name

    if not copied_shp.is_file():
        raise FileNotFoundError(
            f"Failed to copy shapefile dataset:\n{source}"
        )

    return copied_shp


def _copy_vector_dataset(
    layer: QgsVectorLayer,
    destination_folder: Path,
) -> str:
    """
    Copy a file-backed reference vector dataset.

    GeoPackage/SQLite files are copied whole. Shapefile sidecars are copied
    together. The original provider URI suffix (e.g. layername=...) is kept.
    """
    source_uri = layer.source()
    physical_source = Path(
        _clean_provider_path(source_uri)
    )

    if not physical_source.is_file():
        raise FileNotFoundError(
            "Reference vector source does not exist:\n"
            f"{physical_source}"
        )

    suffix = physical_source.suffix.casefold()

    if suffix == ".shp":
        copied = _copy_shapefile_family(
            physical_source,
            destination_folder,
        )
    else:
        copied = _copy_file(
            physical_source,
            destination_folder / physical_source.name,
        )

    return str(copied) + _uri_suffix(source_uri)


def _copy_raster_dataset(
    layer: QgsRasterLayer,
    destination_folder: Path,
) -> str:
    """
    Copy a raster plus common same-file sidecars.
    """
    source = Path(
        _clean_provider_path(layer.source())
    )

    if not source.is_file():
        raise FileNotFoundError(
            f"Raster source does not exist:\n{source}"
        )

    destination_folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    copied = _copy_file(
        source,
        destination_folder / source.name,
    )

    # Common raster sidecars.
    sidecar_candidates = [
        source.with_name(source.name + ".aux.xml"),
        source.with_name(source.name + ".ovr"),
        source.with_suffix(source.suffix + ".xml"),
        source.with_suffix(".tfw"),
        source.with_suffix(".jgw"),
        source.with_suffix(".pgw"),
        source.with_suffix(".wld"),
    ]

    seen = set()

    for sidecar in sidecar_candidates:
        key = str(sidecar).casefold()

        if key in seen:
            continue

        seen.add(key)

        if sidecar.is_file():
            _copy_file(
                sidecar,
                destination_folder / sidecar.name,
            )

    return str(copied)


def _copy_project_resources(
    source_project_folder: Path,
    package_folder: Path,
) -> None:
    """
    Copy conservative project companion resources.

    Project layer styles are already stored in the .qgs project. This helper
    additionally copies common QML/image resources located directly in the
    source PSU folder.
    """
    resources_folder = package_folder / "resources"

    extensions = {
        ".qml",
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
    }

    copied_any = False

    for item in source_project_folder.iterdir():
        if (
            item.is_file()
            and item.suffix.casefold() in extensions
        ):
            resources_folder.mkdir(
                parents=True,
                exist_ok=True,
            )
            shutil.copy2(
                item,
                resources_folder / item.name,
            )
            copied_any = True

    if (
        resources_folder.exists()
        and not copied_any
    ):
        resources_folder.rmdir()


def _resolve_aoi(
    project: QgsProject,
    extent_mode: str,
    canvas_extent: Optional[QgsRectangle],
) -> tuple[Optional[QgsRectangle], Optional[QgsCoordinateReferenceSystem]]:
    """
    Return an AOI rectangle and its CRS.

    Supported modes:
      - Barangay boundary
      - Current map canvas
      - Entire packaged layers
    """
    mode = str(extent_mode or "").strip().casefold()

    if mode == "entire packaged layers":
        return None, None

    if mode == "current map canvas":
        if canvas_extent is None or canvas_extent.isEmpty():
            raise RuntimeError(
                "Current map canvas extent is empty."
            )

        return (
            QgsRectangle(canvas_extent),
            project.crs(),
        )

    # Default: Barangay boundary.
    boundary_layer = None

    for layer in project.mapLayers().values():
        if (
            isinstance(layer, QgsVectorLayer)
            and layer.name().strip().upper() == "BARANGAY BOUNDARY"
        ):
            boundary_layer = layer
            break

    if boundary_layer is None:
        raise RuntimeError(
            "BARANGAY BOUNDARY layer was not found. "
            "Choose another package extent or generate the PSU project again."
        )

    extent = boundary_layer.extent()

    if extent.isEmpty():
        raise RuntimeError(
            "BARANGAY BOUNDARY has an empty extent."
        )

    return (
        QgsRectangle(extent),
        boundary_layer.crs(),
    )


def _select_offline_features(
    project: QgsProject,
    layers: Iterable[QgsVectorLayer],
    aoi_rect: Optional[QgsRectangle],
    aoi_crs: Optional[QgsCoordinateReferenceSystem],
) -> bool:
    """
    Select the portion of offline layers intersecting AOI.

    Returns True when QgsOfflineEditing should use selected features.
    """
    if aoi_rect is None or aoi_crs is None:
        for layer in layers:
            layer.removeSelection()

        return False

    for layer in layers:
        layer.removeSelection()

        if not layer.isSpatial():
            continue

        transform = QgsCoordinateTransform(
            aoi_crs,
            layer.crs(),
            project,
        )

        layer_rect = transform.transformBoundingBox(
            aoi_rect
        )

        layer.selectByRect(layer_rect)

        # QgsOfflineEditing interprets "no selection" as all features.
        # Use an impossible FID when the AOI legitimately contains no
        # features so we do not unexpectedly package the full dataset.
        if layer.selectedFeatureCount() == 0:
            layer.selectByIds([FID_NULL])

    return True


def _relative_project_setting(project: QgsProject, enabled: bool) -> None:
    if not enabled:
        return

    if hasattr(Qgis, "FilePathType"):
        project.setFilePathStorage(
            Qgis.FilePathType.Relative
        )


def _create_manifest(
    package_folder: Path,
    source_project: Path,
    packaged_project: Path,
    offline_database: Path,
    extent_mode: str,
    layers: list[PackageLayerResult],
) -> Path:
    manifest_path = (
        package_folder
        / "package_manifest.json"
    )

    payload = {
        "package_type": "GEOFASU_QFIELD_CABLE",
        "version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "source_project": str(source_project),
        "packaged_project": packaged_project.name,
        "offline_database": (
            offline_database.name
            if offline_database.is_file()
            else ""
        ),
        "extent_mode": extent_mode,
        "layers": [
            asdict(layer)
            for layer in layers
        ],
    }

    manifest_path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return manifest_path


def package_current_project(
    package_folder: str,
    extent_mode: str,
    canvas_extent: Optional[QgsRectangle],
    copy_styles_resources: bool = True,
    preserve_snapping: bool = True,
    relative_paths: bool = True,
) -> QFieldPackageResult:
    """
    Package the current saved QGIS PSU project for cable transfer to QField.

    The current singleton QgsProject is temporarily transformed into the
    package copy. The source project is always reloaded before this function
    returns or raises.
    """
    project = QgsProject.instance()

    original_project_path = Path(
        str(project.fileName() or "").strip()
    )

    if not original_project_path.is_file():
        raise FileNotFoundError(
            "The current QGIS project must be saved before packaging."
        )

    package_folder_path = Path(
        str(package_folder or "").strip()
    )

    if not str(package_folder_path):
        raise RuntimeError(
            "The QField package destination is blank."
        )

    if (
        package_folder_path.resolve()
        == original_project_path.parent.resolve()
    ):
        raise RuntimeError(
            "The QField package folder must be separate from "
            "the source PSU project folder."
        )

    # Source project is saved first so reload is deterministic.
    if not project.write(
        str(original_project_path)
    ):
        raise RuntimeError(
            "The source QGIS project could not be saved before packaging."
        )

    # Start with a clean target directory. The dialog asks for confirmation
    # before calling this function when the folder already has contents.
    package_folder_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    packaged_project_path = (
        package_folder_path
        / f"{original_project_path.stem}_qfield.qgs"
    )

    offline_db_path = (
        package_folder_path
        / "data.gpkg"
    )

    packaged_layers: list[PackageLayerResult] = []

    try:
        # Write a working clone into the package folder.
        if not project.write(
            str(packaged_project_path)
        ):
            raise RuntimeError(
                "Could not create the packaged QGIS project."
            )

        source_project_folder = (
            original_project_path.parent
        )

        reference_folder = (
            package_folder_path
            / "reference"
        )
        basemap_folder = (
            package_folder_path
            / "basemap"
        )

        offline_layers: list[QgsVectorLayer] = []

        # Work on a list copy because data sources will be changed in place.
        for layer in list(
            project.mapLayers().values()
        ):
            if not layer.isValid():
                raise RuntimeError(
                    f'Layer "{layer.name()}" is invalid.'
                )

            provider = str(
                layer.providerType() or ""
            ).casefold()

            if provider == "memory":
                raise RuntimeError(
                    f'Layer "{layer.name()}" is temporary memory data.'
                )

            if _is_editable_lfs_layer(layer):
                assert isinstance(layer, QgsVectorLayer)

                offline_layers.append(layer)

                packaged_layers.append(
                    PackageLayerResult(
                        layer_name=layer.name(),
                        layer_type="Vector",
                        action="Offline editable",
                        packaged_source="data.gpkg",
                    )
                )

            elif isinstance(layer, QgsVectorLayer):
                new_source = _copy_vector_dataset(
                    layer,
                    reference_folder,
                )

                provider_name = layer.providerType()

                layer.setDataSource(
                    new_source,
                    layer.name(),
                    provider_name,
                )
                layer.setReadOnly(True)

                packaged_layers.append(
                    PackageLayerResult(
                        layer_name=layer.name(),
                        layer_type="Vector",
                        action="Copy read-only",
                        packaged_source=new_source,
                    )
                )

            elif isinstance(layer, QgsRasterLayer):
                new_source = _copy_raster_dataset(
                    layer,
                    basemap_folder,
                )

                layer.setDataSource(
                    new_source,
                    layer.name(),
                    layer.providerType(),
                )

                packaged_layers.append(
                    PackageLayerResult(
                        layer_name=layer.name(),
                        layer_type="Raster",
                        action="Copy",
                        packaged_source=new_source,
                    )
                )

            else:
                # Unsupported non-vector/non-raster project layers are not
                # included in this focused field package.
                project.removeMapLayer(
                    layer.id()
                )

        if not offline_layers:
            raise RuntimeError(
                "No generated SELECTED_SSU project layer was found for "
                "offline editing."
            )

        if copy_styles_resources:
            _copy_project_resources(
                source_project_folder,
                package_folder_path,
            )

        aoi_rect, aoi_crs = _resolve_aoi(
            project,
            extent_mode,
            canvas_extent,
        )

        only_selected = _select_offline_features(
            project,
            offline_layers,
            aoi_rect,
            aoi_crs,
        )

        offline_editing = QgsOfflineEditing()

        is_success = (
            offline_editing.convertToOfflineProject(
                str(package_folder_path),
                offline_db_path.name,
                [
                    layer.id()
                    for layer in offline_layers
                ],
                only_selected,
                containerType=(
                    QgsOfflineEditing
                    .ContainerType
                    .GPKG
                ),
                layerNameSuffix=None,
            )
        )

        if not is_success:
            raise RuntimeError(
                "QGIS Offline Editing failed to create data.gpkg."
            )

        # Portable-project safety options.
        _relative_project_setting(
            project,
            relative_paths,
        )

        if not preserve_snapping:
            snapping = project.snappingConfig()
            snapping.setEnabled(False)
            project.setSnappingConfig(snapping)

        # QField/offline projects are more reliable without transaction mode.
        if hasattr(Qgis, "TransactionMode"):
            project.setTransactionMode(
                Qgis.TransactionMode.Disabled
            )

        if hasattr(Qgis, "ProjectFlag"):
            try:
                project.setFlag(
                    Qgis.ProjectFlag.EvaluateDefaultValuesOnProviderSide,
                    False,
                )
            except Exception:
                pass

        # Store useful package metadata.
        project.writeEntry(
            "geofasu",
            "/qfieldPackage",
            True,
        )
        project.writeEntry(
            "geofasu",
            "/originalProjectPath",
            str(original_project_path),
        )
        project.writeEntry(
            "geofasu",
            "/packageExtentMode",
            str(extent_mode),
        )

        if not project.write(
            str(packaged_project_path)
        ):
            raise RuntimeError(
                "The packaged QGIS project could not be saved."
            )

        manifest_path = _create_manifest(
            package_folder_path,
            original_project_path,
            packaged_project_path,
            offline_db_path,
            extent_mode,
            packaged_layers,
        )

        return QFieldPackageResult(
            package_folder=str(
                package_folder_path
            ),
            packaged_project_file=str(
                packaged_project_path
            ),
            offline_database=str(
                offline_db_path
            ),
            manifest_file=str(
                manifest_path
            ),
            packaged_layers=packaged_layers,
        )

    finally:
        # Always restore the untouched desktop PSU project.
        QCoreApplication.processEvents()
        project.clear()
        QCoreApplication.processEvents()

        if not project.read(
            str(original_project_path)
        ):
            raise RuntimeError(
                "QField packaging finished, but GEOFASU could not reload "
                "the original desktop QGIS project:\n"
                f"{original_project_path}"
            )

        QCoreApplication.processEvents()