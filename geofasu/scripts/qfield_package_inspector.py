# -*- coding: utf-8 -*-
"""Milestone 1 QField package inspection helpers for GEOFASU."""

from dataclasses import dataclass
from pathlib import Path
from typing import List

from qgis.core import QgsMapLayer, QgsProject, QgsRasterLayer, QgsVectorLayer


@dataclass(frozen=True)
class QFieldLayerInspection:
    layer_id: str
    layer_name: str
    layer_type: str
    provider: str
    source: str
    proposed_action: str
    status: str
    message: str


@dataclass(frozen=True)
class QFieldProjectInspection:
    project_file: str
    package_folder: str
    layer_results: List[QFieldLayerInspection]
    error_count: int
    warning_count: int
    ready_count: int

    @property
    def can_continue(self) -> bool:
        return self.error_count == 0


def _clean_source(source: str) -> str:
    text = str(source or "").strip()
    return text.split("|", 1)[0] if "|" in text else text


def _classify_layer(layer: QgsMapLayer) -> tuple[str, str]:
    if isinstance(layer, QgsRasterLayer):
        return "Raster", "Copy"

    if isinstance(layer, QgsVectorLayer):
        name = layer.name().upper()
        if "SELECTED_SSU" in name or "SELECTED SSU" in name:
            return "Vector", "Offline editable"
        return "Vector", "Copy read-only"

    return "Other", "Review"


def _inspect_layer(layer: QgsMapLayer) -> QFieldLayerInspection:
    layer_type, proposed_action = _classify_layer(layer)

    try:
        provider = layer.providerType()
    except Exception:
        provider = ""

    try:
        source = layer.source()
    except Exception:
        source = ""

    status = "Ready"
    message = "Layer is suitable for the proposed package action."

    if not layer.isValid():
        status = "Error"
        message = "Layer is invalid and cannot be packaged."

    elif provider.casefold() == "memory":
        status = "Error"
        message = (
            "Memory layers are temporary. Save this layer to a persistent "
            "file before packaging."
        )

    else:
        physical_source = _clean_source(source)

        if (
            physical_source
            and (
                ":" in physical_source[:3]
                or physical_source.startswith("/")
                or physical_source.startswith("\\\\")
            )
            and not Path(physical_source).exists()
        ):
            status = "Error"
            message = f"Source file is missing or inaccessible: {physical_source}"

        if (
            status == "Ready"
            and isinstance(layer, QgsVectorLayer)
            and proposed_action == "Offline editable"
        ):
            try:
                pk_indexes = layer.dataProvider().pkAttributeIndexes()
                if not pk_indexes:
                    status = "Warning"
                    message = (
                        "No provider primary key was detected. Verify offline "
                        "editing compatibility before production packaging."
                    )
            except Exception:
                status = "Warning"
                message = (
                    "Primary-key compatibility could not be verified for this "
                    "editable layer."
                )

    return QFieldLayerInspection(
        layer_id=layer.id(),
        layer_name=layer.name(),
        layer_type=layer_type,
        provider=provider,
        source=source,
        proposed_action=proposed_action,
        status=status,
        message=message,
    )


def inspect_current_project(package_folder: str) -> QFieldProjectInspection:
    project = QgsProject.instance()

    project_file = str(project.fileName() or "").strip()
    package_folder = str(package_folder or "").strip()

    results = [_inspect_layer(layer) for layer in project.mapLayers().values()]

    errors = sum(item.status == "Error" for item in results)
    warnings = sum(item.status == "Warning" for item in results)
    ready = sum(item.status == "Ready" for item in results)

    if not project_file or not Path(project_file).is_file():
        results.insert(
            0,
            QFieldLayerInspection(
                layer_id="__PROJECT__",
                layer_name="QGIS PROJECT",
                layer_type="Project",
                provider="",
                source=project_file,
                proposed_action="Save before packaging",
                status="Error",
                message="The current QGIS project has not been saved to disk.",
            ),
        )
        errors += 1

    if not package_folder:
        results.insert(
            0,
            QFieldLayerInspection(
                layer_id="__PACKAGE__",
                layer_name="QFIELD PACKAGE",
                layer_type="Destination",
                provider="",
                source="",
                proposed_action="Resolve destination",
                status="Error",
                message="The QField package destination is blank.",
            ),
        )
        errors += 1
    elif project_file:
        try:
            if Path(package_folder).resolve() == Path(project_file).resolve().parent:
                results.insert(
                    0,
                    QFieldLayerInspection(
                        layer_id="__PACKAGE__",
                        layer_name="QFIELD PACKAGE",
                        layer_type="Destination",
                        provider="",
                        source=package_folder,
                        proposed_action="Use separate package folder",
                        status="Error",
                        message=(
                            "The package destination must be separate from the "
                            "source QGIS project folder."
                        ),
                    ),
                )
                errors += 1
        except OSError:
            pass

    return QFieldProjectInspection(
        project_file=project_file,
        package_folder=package_folder,
        layer_results=results,
        error_count=int(errors),
        warning_count=int(warnings),
        ready_count=int(ready),
    )