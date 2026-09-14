# -*- coding: utf-8 -*-
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import (
    QDialog, QFileDialog, QMessageBox, QApplication, QProgressDialog,
    QTableWidgetItem, QHeaderView
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QBrush
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsProject, QgsProcessingFeedback, QgsVectorFileWriter, QgsCoordinateReferenceSystem,
    QgsRasterLayer, QgsSnappingConfig, QgsTolerance
)
import os, re, shutil
from pathlib import Path

# Import scripts
from .scripts.extract_psu import extract_by_psu
from .scripts.refactor_sample import refactor_psu_layer
from .scripts.load_style_samples import load_style
from .scripts.load_bgy import load_barangay_layer_smart
from .scripts.clip_raster_by_bgy import clip_raster_by_bgy_memory
from .scripts.qfield_package_inspector import inspect_current_project
from .scripts.qfield_packager import package_current_project

# Load UI
FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), 'geofasu_dialog_base.ui')
)


class geofasuDialog(QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # --- Connect buttons ---
        self.pbBrowseExcel.clicked.connect(self.browse_excel)
        self.pbBrowseOutput.clicked.connect(self.browse_output)
        self.pbLoadSSU.clicked.connect(self.load_psu_list)
        self.pbGenerateGeometry.clicked.connect(self.generate_geometry)
        self.pbBulkGenerate.clicked.connect(self.on_bulk_generate_clicked)
        self.pbInspectQField.clicked.connect(self.inspect_qfield_project)
        self.pbPackageQField.clicked.connect(self.package_qfield_project)

        self.cbpsu_list.currentIndexChanged.connect(self.update_selected_psu_paths)
        self.project_abbreviation.textChanged.connect(
            self.on_project_abbreviation_changed
        )

        # Project abbreviation controls generated names and paths.
        self.project_abbreviation.setText("LFS")
        self.project_abbreviation.setMaxLength(20)
        self.project_abbreviation.setToolTip(
            "Short project code used in generated layer names, filenames, "
            "QGIS project names and folders. Examples: LFS, GATS, HSDV."
        )

        # Basemap extraction/loading is optional.
        self.chkLoadBasemap.setChecked(True)
        self.chkLoadBasemap.setToolTip(
            "When enabled, GEOFASU clips/extracts the basemap using the "
            "barangay boundary and loads it into the generated project. "
            "When disabled, raster processing is skipped entirely."
        )

        # Bulk generation options. QField packages depend on QGIS projects.
        self.chkBulkCreateQGIS.setChecked(True)
        self.chkBulkCreateQField.setChecked(False)
        self.chkBulkCreateQGIS.setToolTip(
            "Generate one independent QGIS project for every PSU in the loaded list."
        )
        self.chkBulkCreateQField.setToolTip(
            "After each PSU QGIS project is generated, create its QField package "
            "using the options in Section 5."
        )
        self.chkBulkCreateQField.toggled.connect(
            self.on_bulk_qfield_toggled
        )

        # Output path display-only
        self.output_path.setReadOnly(True)
        self.output_path.setToolTip(
            "The output folder is generated automatically from the selected PSU."
        )

        self.qfield_package_path.setReadOnly(True)
        self.qfield_package_path.setToolTip(
            "Default QField package folder for the currently selected PSU."
        )

        self.pbPackageQField.setEnabled(False)
        self.pbPackageQField.setToolTip(
            "Inspect the current project first. Packaging is enabled "
            "when no blocking errors are found."
        )

        self._last_qfield_inspection = None

        self.tblQFieldLayers.setColumnCount(5)
        self.tblQFieldLayers.setHorizontalHeaderLabels([
            "Layer",
            "Type",
            "Provider",
            "Proposed Action",
            "Status",
        ])
        header = self.tblQFieldLayers.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 5):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeToContents
            )
        self.tblQFieldLayers.verticalHeader().setVisible(False)
        self.tblQFieldLayers.setAlternatingRowColors(True)
        self.tblQFieldLayers.setSelectionBehavior(
            self.tblQFieldLayers.SelectRows
        )
        self.tblQFieldLayers.setEditTriggers(
            self.tblQFieldLayers.NoEditTriggers
        )

        # --- Keep layer references to avoid deletion ---
        self.lfs_layer = None
        self.bgy_layer = None
        self.clipped_raster = None
        self.generated_project_path = None

        # Bulk/performance state. Source municipality rasters are cached only
        # for the lifetime of this dialog so repeated PSUs do not reopen the
        # same large GeoPackage raster.
        self._source_raster_cache = {}
        self._barangay_source_cache = {}
        self._bulk_running = False
        self._bulk_cancel_requested = False

        # In-window preprocessing progress indicator.
        self.progressPreprocess.setRange(0, 100)
        self.progressPreprocess.setValue(0)
        self.progressPreprocess.setFormat("%p%")
        self.lblPreprocessProgress.setText("Ready")

    # =========================================================
    # Helper: Month Name
    # =========================================================
    @staticmethod
    def month_name(m):
        months = [
            "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
            "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"
        ]
        return months[m - 1] if 1 <= m <= 12 else "UNKNOWN"

    # =========================================================
    # In-window Pre-Processing Progress
    # =========================================================
    def _set_preprocess_progress(self, value, text=None):
        value = max(0, min(100, int(round(value))))
        self.progressPreprocess.setValue(value)
        if text is not None:
            self.lblPreprocessProgress.setText(str(text))
        QApplication.processEvents()

    def _reset_preprocess_progress(self, text="Ready"):
        self.progressPreprocess.setValue(0)
        self.lblPreprocessProgress.setText(text)
        QApplication.processEvents()

    def _paths_for_psu_data(self, data):
        """Return output/QField folders without changing combo-box selection."""
        project_code = self.current_project_abbreviation(required=False) or "PROJECT"
        year = int(data.get("Year", 0))
        rnd = int(data.get("Round", 0))
        psu_number = data.get("PSU_number")
        province = str(data.get("Prov_name", "PROVINCE")).strip().upper()

        try:
            rollout_root = self.build_project_rollout_root(
                province=province,
                year=year,
                round_number=rnd,
            )
        except Exception:
            rollout_root = os.path.join(
                "C:/PSA-GIS", province, "GEOFASU", str(year), project_code
            )

        return (
            os.path.join(rollout_root, f"PSU_{psu_number}"),
            os.path.join(rollout_root, "QField Packages", f"PSU_{psu_number}"),
        )

    # =========================================================
    # Browse Excel
    # =========================================================
    def browse_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Excel file", "", "Excel Files (*.xlsx)"
        )
        if path:
            self.ssu_list_path.setText(path)

    # =========================================================
    # Browse Output Folder
    # =========================================================
    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_path.setText(folder)

    # =========================================================
    # Load PSU List
    # =========================================================
    def load_psu_list(self):
        excel_path = self.ssu_list_path.text()
        if not excel_path:
            QMessageBox.warning(self, "Missing File", "Select Excel file first.")
            return

        try:
            self._set_preprocess_progress(5, "Reading PSU list...")
            from openpyxl import load_workbook
            wb = load_workbook(excel_path, data_only=True, read_only=True)
            if "Sample PSU" not in wb.sheetnames:
                raise Exception("Sheet 'Sample PSU' not found.")

            ws = wb["Sample PSU"]
            self.cbpsu_list.clear()

            for row in ws.iter_rows(min_row=2, values_only=True):
                geoid, reg_name, prov_name, mun_name, psu_name, psu_number, rep, rnd, year, rg = row
                if psu_number is None or geoid is None:
                    continue

                number = int(psu_number)
                text = f"{number} ({mun_name}, {psu_name})"
                geoid_str = str(geoid)
                geoid_prefix = geoid_str[2:5] + geoid_str[5:7]

                data = {
                    "Prov_name": prov_name,
                    "PSU_number": number,
                    "Mun_name": mun_name,
                    "PSU_name": psu_name,
                    "Replicate_Number": rep,
                    "Round": rnd,
                    "Year": year,
                    "Geoid_prefix": geoid_prefix
                }
                self.cbpsu_list.addItem(text, data)

            try:
                wb.close()
            except Exception:
                pass

            self._set_preprocess_progress(100, f"PSU list loaded: {self.cbpsu_list.count()} PSU(s).")
            QMessageBox.information(self, "Loaded", "PSU list loaded.")
            if self.cbpsu_list.count() > 0:
                self.update_selected_psu_paths()

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # =========================================================
    # Project Abbreviation / Naming
    # =========================================================
    @staticmethod
    def normalize_project_abbreviation(value):
        value = str(value or "").strip().upper()
        value = re.sub(r"[^A-Z0-9]+", "_", value)
        value = re.sub(r"_+", "_", value).strip("_")
        return value

    def current_project_abbreviation(self, required=True):
        code = self.normalize_project_abbreviation(
            self.project_abbreviation.text()
        )

        if required and not code:
            raise ValueError(
                "Enter a Project Abbreviation first. "
                "Examples: LFS, GATS, HSDV."
            )

        return code

    def on_project_abbreviation_changed(self):
        raw = self.project_abbreviation.text()
        upper = raw.upper()

        if raw != upper:
            cursor = self.project_abbreviation.cursorPosition()
            self.project_abbreviation.blockSignals(True)
            self.project_abbreviation.setText(upper)
            self.project_abbreviation.setCursorPosition(
                min(cursor, len(upper))
            )
            self.project_abbreviation.blockSignals(False)

        if self.cbpsu_list.currentIndex() >= 0:
            self.update_selected_psu_paths()

    def build_project_key(self, year, round_number):
        """
        LFS is monthly:
            2026_JAN_LFS
            2026_FEB_LFS

        Other projects do not include LFS round/month:
            2026_GATS
            2026_HSDV
        """
        project_code = self.current_project_abbreviation()
        year = int(year)

        if project_code == "LFS":
            round_number = int(round_number)

            if not 1 <= round_number <= 12:
                raise ValueError(
                    f"Invalid LFS round/month: {round_number}. "
                    "Expected a value from 1 to 12."
                )

            month_abbr = self.month_name(round_number)[:3]
            return f"{year}_{month_abbr}_{project_code}"

        return f"{year}_{project_code}"

    def build_project_rollout_root(
        self,
        province,
        year,
        round_number,
    ):
        """
        LFS:
            C:/PSA-GIS/ROMBLON/GEOFASU/2026/JANUARY

        Other projects:
            C:/PSA-GIS/ROMBLON/GEOFASU/2026/GATS
            C:/PSA-GIS/ROMBLON/GEOFASU/2026/HSDV
        """
        project_code = self.current_project_abbreviation()
        province = str(
            province or "PROVINCE"
        ).strip().upper()
        year = int(year)

        root = os.path.join(
            "C:/PSA-GIS",
            province,
            "GEOFASU",
            str(year),
        )

        if project_code == "LFS":
            round_number = int(round_number)

            if not 1 <= round_number <= 12:
                raise ValueError(
                    f"Invalid LFS round/month: {round_number}."
                )

            return os.path.join(
                root,
                self.month_name(round_number),
            )

        return os.path.join(
            root,
            project_code,
        )

    # =========================================================
    # Selected PSU Path Builders
    # =========================================================
    def update_selected_psu_paths(self):
        idx = self.cbpsu_list.currentIndex()

        if idx < 0:
            self.output_path.clear()
            self.qfield_package_path.clear()
            return

        data = self.cbpsu_list.itemData(idx) or {}
        output_folder, qfield_folder = self._paths_for_psu_data(data)
        self.output_path.setText(output_folder)
        self.qfield_package_path.setText(qfield_folder)

        self.tblQFieldLayers.setRowCount(0)
        self._last_qfield_inspection = None
        self.pbPackageQField.setEnabled(False)

        project_code = self.current_project_abbreviation(required=False) or "PROJECT"
        try:
            project_key = self.build_project_key(
                year=int(data.get("Year", 0)),
                round_number=int(data.get("Round", 0)),
            )
        except Exception:
            project_key = project_code

        self.lblQFieldStatus.setText(
            f"{project_key} selected. Generate the PSU project, "
            "then inspect it for QField package readiness."
        )

    def update_default_output_path(self):
        """Backward-compatible alias."""
        self.update_selected_psu_paths()

    # =========================================================
    # QField Milestone 1 — Project Inspection
    # =========================================================
    def inspect_qfield_project(self):
        package_folder = self.qfield_package_path.text().strip()

        if self.cbpsu_list.currentIndex() < 0:
            QMessageBox.warning(
                self,
                "No PSU Selected",
                "Select a PSU before inspecting the current project."
            )
            return

        if not package_folder:
            QMessageBox.warning(
                self,
                "Missing Package Destination",
                "The QField package destination could not be determined."
            )
            return

        try:
            result = inspect_current_project(
                package_folder=package_folder,
            )

            self.tblQFieldLayers.setRowCount(
                len(result.layer_results)
            )

            error_items = []
            warning_items = []

            for row_index, item in enumerate(result.layer_results):
                values = [
                    item.layer_name,
                    item.layer_type,
                    item.provider,
                    item.proposed_action,
                    item.status,
                ]

                if item.status == "Error":
                    row_background = QColor("#fee2e2")
                    row_foreground = QColor("#991b1b")
                    error_items.append(
                        f"{item.layer_name}: {item.message}"
                    )

                elif item.status == "Warning":
                    row_background = QColor("#fef3c7")
                    row_foreground = QColor("#92400e")
                    warning_items.append(
                        f"{item.layer_name}: {item.message}"
                    )

                else:
                    row_background = QColor("#ecfdf5")
                    row_foreground = QColor("#166534")

                for column_index, value in enumerate(values):
                    table_item = QTableWidgetItem(str(value))
                    table_item.setToolTip(item.message)

                    table_item.setBackground(
                        QBrush(row_background)
                    )
                    table_item.setForeground(
                        QBrush(row_foreground)
                    )

                    self.tblQFieldLayers.setItem(
                        row_index,
                        column_index,
                        table_item
                    )

            self.tblQFieldLayers.resizeRowsToContents()

            self._last_qfield_inspection = result
            self.pbPackageQField.setEnabled(
                result.error_count == 0
            )

            if result.error_count > 0:
                self.lblQFieldStatus.setText(
                    "Project inspection failed. "
                    f"{result.error_count} blocking error(s) and "
                    f"{result.warning_count} warning(s) were found. "
                    "Resolve all red rows before packaging."
                )

            elif result.warning_count > 0:
                self.lblQFieldStatus.setText(
                    "Project inspection passed with warnings. "
                    f"{result.warning_count} warning(s) should be reviewed "
                    "before production packaging."
                )

            else:
                self.lblQFieldStatus.setText(
                    "Project inspection passed. "
                    f"{result.ready_count} item(s) are ready for "
                    "the proposed QField package actions."
                )

            message_parts = [
                "Inspection completed.",
                "",
                f"Ready: {result.ready_count}",
                f"Warnings: {result.warning_count}",
                f"Errors: {result.error_count}",
            ]

            if error_items:
                message_parts.extend([
                    "",
                    "BLOCKING ERRORS:",
                ])

                for index, message in enumerate(
                    error_items,
                    start=1,
                ):
                    message_parts.append(
                        f"{index}. {message}"
                    )

            if warning_items:
                message_parts.extend([
                    "",
                    "WARNINGS:",
                ])

                for index, message in enumerate(
                    warning_items,
                    start=1,
                ):
                    message_parts.append(
                        f"{index}. {message}"
                    )

            if result.error_count > 0:
                message_parts.extend([
                    "",
                    "Resolve the blocking errors shown above before "
                    "QField packaging is enabled."
                ])

                QMessageBox.warning(
                    self,
                    "QField Project Inspection",
                    "\n".join(message_parts)
                )

            else:
                message_parts.extend([
                    "",
                    "No blocking errors were found. Package for QField is now enabled."
                ])

                QMessageBox.information(
                    self,
                    "QField Project Inspection",
                    "\n".join(message_parts)
                )

        except Exception as e:
            QMessageBox.critical(
                self,
                "QField Inspection Error",
                str(e)
            )


    # =========================================================
    # QField Milestone 2 — Package Current Project
    # =========================================================
    def package_qfield_project(self):
        package_folder = self.qfield_package_path.text().strip()

        if self.cbpsu_list.currentIndex() < 0:
            QMessageBox.warning(
                self,
                "No PSU Selected",
                "Select a PSU before creating a QField package."
            )
            return

        current_project_file = str(
            QgsProject.instance().fileName() or ""
        ).strip()

        if (
            not current_project_file
            or not os.path.isfile(current_project_file)
        ):
            QMessageBox.warning(
                self,
                "Project Not Saved",
                "Generate or save the current PSU project before packaging."
            )
            return

        if not package_folder:
            QMessageBox.warning(
                self,
                "Missing Package Destination",
                "Select a PSU first so the QField package destination "
                "can be determined."
            )
            return

        # Always run the latest inspection before packaging.
        try:
            inspection = inspect_current_project(
                package_folder=package_folder,
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "QField Inspection Error",
                str(e)
            )
            return

        if (
            self.chkQFieldValidate.isChecked()
            and inspection.error_count > 0
        ):
            self._last_qfield_inspection = inspection
            self.pbPackageQField.setEnabled(False)

            QMessageBox.warning(
                self,
                "QField Packaging Blocked",
                "The current project has blocking QField package errors.\n\n"
                "Run Inspect Current Project and resolve all red rows first."
            )
            return

        package_path = Path(package_folder)

        if (
            package_path.exists()
            and any(package_path.iterdir())
        ):
            answer = QMessageBox.question(
                self,
                "Replace Existing QField Package",
                "The QField package folder already contains files:\n\n"
                f"{package_folder}\n\n"
                "Delete the existing package contents and create a new "
                "package for this PSU?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )

            if answer != QMessageBox.Yes:
                return

            try:
                shutil.rmtree(package_path)
            except OSError as exc:
                QMessageBox.critical(
                    self,
                    "Cannot Replace QField Package",
                    "The existing package folder could not be removed.\n\n"
                    f"{package_folder}\n\n"
                    f"Error:\n{exc}"
                )
                return

        package_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        QApplication.setOverrideCursor(
            Qt.WaitCursor
        )

        progress = QProgressDialog(
            "Creating QField package...",
            "",
            0,
            0,
            self,
        )
        progress.setWindowTitle(
            "GEOFASU — QField Package"
        )
        progress.setWindowModality(
            Qt.WindowModal
        )
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()

        try:
            canvas_extent = None

            if (
                self.cmbQFieldExtent.currentText()
                == "Current map canvas"
            ):
                from qgis.utils import iface

                canvas_extent = (
                    iface.mapCanvas().extent()
                )

            result = package_current_project(
                package_folder=package_folder,
                extent_mode=(
                    self.cmbQFieldExtent
                    .currentText()
                ),
                canvas_extent=canvas_extent,
                copy_styles_resources=(
                    self.chkQFieldStyles
                    .isChecked()
                ),
                preserve_snapping=(
                    self.chkQFieldSnapping
                    .isChecked()
                ),
                relative_paths=(
                    self.chkQFieldRelativePaths
                    .isChecked()
                ),
            )

            self.lblQFieldStatus.setText(
                "QField package created successfully. "
                f"{len(result.packaged_layers)} layer(s) packaged."
            )

            QMessageBox.information(
                self,
                "QField Package Complete",
                "The QField cable package was created successfully.\n\n"
                f"Package folder:\n{result.package_folder}\n\n"
                f"QField project:\n{result.packaged_project_file}\n\n"
                f"Offline data:\n{result.offline_database}\n\n"
                f"Manifest:\n{result.manifest_file}\n\n"
                "Copy the complete PSU package folder to the QField device."
            )

            # The packager reloads the original desktop project.
            # Re-inspect it so the UI reflects the restored project.
            self.inspect_qfield_project()

        except Exception as e:
            QMessageBox.critical(
                self,
                "QField Packaging Error",
                str(e)
            )

        finally:
            progress.close()
            QApplication.restoreOverrideCursor()

    # =========================================================
    # Remove Temporary Processing Layers
    # =========================================================
    @staticmethod
    def remove_temporary_processing_layers():
        """
        Remove generic temporary memory layers named "output" created by
        QGIS Processing.

        Only generic temporary layers are removed. Intentionally named
        memory layers are left untouched.
        """
        project = QgsProject.instance()
        layer_ids_to_remove = []

        for layer_id, layer in project.mapLayers().items():
            try:
                provider = str(
                    layer.providerType() or ""
                ).casefold()
            except Exception:
                provider = ""

            try:
                layer_name = str(
                    layer.name() or ""
                ).strip().casefold()
            except Exception:
                layer_name = ""

            if (
                provider == "memory"
                and layer_name == "output"
            ):
                layer_ids_to_remove.append(
                    layer_id
                )

        if layer_ids_to_remove:
            project.removeMapLayers(
                layer_ids_to_remove
            )

        return len(layer_ids_to_remove)

    # =========================================================
    # Prepare New QGIS Project for Selected PSU
    # =========================================================
    def prepare_project_for_generation(self):
        """
        Prepare a completely clean QGIS project before generating a PSU.

        GEOFASU uses one independent QGIS project per PSU. When the user
        generates another PSU, layers/groups from the previously generated
        PSU must never be carried into the new project.

        If the current project contains unsaved changes, the user may save,
        discard, or cancel before the project is cleared.

        Returns:
            True  - generation may continue.
            False - generation was cancelled.
        """
        project = QgsProject.instance()

        current_project_file = str(
            project.fileName() or ""
        ).strip()

        # -----------------------------------------------------
        # Protect unsaved changes in the current project.
        # -----------------------------------------------------
        if project.isDirty() and project.mapLayers():
            current_name = (
                os.path.basename(current_project_file)
                if current_project_file
                else "Untitled Project"
            )

            answer = QMessageBox.question(
                self,
                "Start New PSU Project",
                "The current QGIS project contains unsaved changes.\n\n"
                f"Current project:\n{current_name}\n\n"
                "Save the current project before generating the selected PSU?\n\n"
                "Yes = Save and continue\n"
                "No = Discard changes and continue\n"
                "Cancel = Keep the current project and stop generation",
                QMessageBox.Yes
                | QMessageBox.No
                | QMessageBox.Cancel,
                QMessageBox.Yes,
            )

            if answer == QMessageBox.Cancel:
                return False

            if answer == QMessageBox.Yes:
                if not current_project_file:
                    save_path, _ = QFileDialog.getSaveFileName(
                        self,
                        "Save Current QGIS Project",
                        "",
                        "QGIS Project (*.qgs *.qgz)",
                    )

                    if not save_path:
                        return False

                    current_project_file = save_path

                if not project.write(
                    current_project_file
                ):
                    QMessageBox.critical(
                        self,
                        "Save Failed",
                        "The current QGIS project could not be saved.\n\n"
                        f"{current_project_file}"
                    )
                    return False

        # -----------------------------------------------------
        # Release Python references to old PSU layers.
        # -----------------------------------------------------
        self.lfs_layer = None
        self.bgy_layer = None
        self.clipped_raster = None
        self.generated_project_path = None

        # The inspection belongs to the previous project.
        self._last_qfield_inspection = None
        self.tblQFieldLayers.setRowCount(0)
        self.pbPackageQField.setEnabled(False)

        # -----------------------------------------------------
        # Clear the active QGIS project.
        # This creates the blank project which the new PSU will populate.
        # -----------------------------------------------------
        try:
            project.setDirty(False)
        except Exception:
            pass

        project.clear()

        project.setCrs(
            QgsCoordinateReferenceSystem(
                "EPSG:4326"
            )
        )

        self.lblQFieldStatus.setText(
            "New PSU project started. Generating geometry..."
        )

        return True

    # =========================================================
    # Bulk Generation Options
    # =========================================================
    def on_bulk_qfield_toggled(self, checked):
        """QField packaging requires the corresponding QGIS PSU project."""
        if checked:
            self.chkBulkCreateQGIS.setChecked(True)
            self.chkBulkCreateQGIS.setEnabled(False)
        else:
            self.chkBulkCreateQGIS.setEnabled(True)

    def _build_main_sample_layer(self, path, feedback):
        """Build the combined temporary SSU/replacement point layer."""
        num_pat = re.compile(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?')
        main_layer = QgsVectorLayer(
            "Point?crs=EPSG:4326",
            "SSU + Replacement (temp)",
            "memory"
        )
        main_dp = main_layer.dataProvider()

        primary_sheets = [
            'Sample SSU',
            'Selected Samples',
            'AONCR-SAMPLE HH',
        ]
        replacement_sheet = 'Replacement SSU'
        layers = []
        wkt_fields = {}

        for name in primary_sheets + [replacement_sheet]:
            uri = f'{path}|layername={name}'
            lyr = QgsVectorLayer(
                uri,
                name.lower().replace(' ', '_'),
                'ogr'
            )
            if not lyr.isValid():
                continue

            wkt_field = next(
                (
                    field.name()
                    for field in lyr.fields()
                    if 'wkt' in field.name().lower()
                ),
                None,
            )
            if not wkt_field:
                continue

            layers.append(lyr)
            wkt_fields[lyr] = wkt_field

        if not layers:
            raise RuntimeError(
                "No valid sample sheets with a WKT field were found."
            )

        main_fields = layers[0].fields()
        main_dp.addAttributes(main_fields)
        main_layer.updateFields()

        for lyr in layers:
            for feat in lyr.getFeatures():
                wkt = feat[wkt_fields[lyr]]
                geom = QgsGeometry.fromWkt(str(wkt or ""))

                if geom.isNull():
                    nums = num_pat.findall(str(wkt))
                    if len(nums) >= 2:
                        geom = QgsGeometry.fromPointXY(
                            QgsPointXY(
                                float(nums[0]),
                                float(nums[1]),
                            )
                        )

                if geom.isNull():
                    continue

                nf = QgsFeature(main_fields)
                nf.setGeometry(geom)
                nf.setAttributes(feat.attributes())
                main_dp.addFeature(nf)

        main_layer.updateExtents()
        return main_layer

    def _build_psu_feature_index(self, main_layer):
        """Index temporary sample features once for fast bulk PSU extraction."""
        field_index = main_layer.fields().indexFromName("PSU_number")
        if field_index < 0:
            return {}

        index = {}
        for feature in main_layer.getFeatures():
            raw_value = feature[field_index]
            try:
                key = int(raw_value)
            except Exception:
                key = str(raw_value)
            index.setdefault(key, []).append(QgsFeature(feature))
        return index

    def _layer_from_psu_feature_index(self, main_layer, feature_index, psu_number):
        """Create a small memory layer from the pre-indexed features of one PSU."""
        try:
            key = int(psu_number)
        except Exception:
            key = str(psu_number)

        features = feature_index.get(key, [])
        if not features:
            raise RuntimeError(f"No sample features were found for PSU_{psu_number}.")

        layer = QgsVectorLayer(
            f"Point?crs={main_layer.crs().authid() or 'EPSG:4326'}",
            f"SSU_PSU_{psu_number}",
            "memory",
        )
        provider = layer.dataProvider()
        provider.addAttributes(main_layer.fields())
        layer.updateFields()
        provider.addFeatures([QgsFeature(feature) for feature in features])
        layer.updateExtents()
        return layer

    def _generate_psu_project_core(
        self,
        path,
        psu_data,
        output_folder,
        main_layer=None,
        feedback=None,
        feature_index=None,
        render_canvas=True,
        bulk_mode=False,
        progress_callback=None,
    ):
        """Generate one independent PSU GeoPackage/QGIS project.

        ``bulk_mode`` avoids expensive canvas redraws and raster pyramid
        creation. ``feature_index`` lets bulk runs extract PSU features from
        an in-memory index instead of rescanning the whole sample layer for
        every PSU.
        """
        def report(value, text):
            if progress_callback is not None:
                progress_callback(value, text)

        project_code = self.current_project_abbreviation()
        psu_number = psu_data.get("PSU_number")
        geoid_prefix = psu_data.get("Geoid_prefix")

        if psu_number is None:
            raise RuntimeError("PSU number is missing.")

        os.makedirs(output_folder, exist_ok=True)
        feedback = feedback or QgsProcessingFeedback()

        report(4, f"PSU_{psu_number}: preparing sample data...")
        if main_layer is None:
            main_layer = self._build_main_sample_layer(path, feedback)

        if feature_index is not None:
            filtered_layer = self._layer_from_psu_feature_index(
                main_layer,
                feature_index,
                psu_number,
            )
        else:
            filtered_layer = extract_by_psu(
                main_layer,
                psu_number,
                feedback,
            )

        report(12, f"PSU_{psu_number}: preparing geometry...")
        refactored_layer = refactor_psu_layer(
            filtered_layer,
            context=None,
            feedback=feedback,
        )

        year = int(psu_data["Year"])
        rnd = int(psu_data["Round"])
        rep = psu_data.get("Replicate_Number")
        try:
            rep = int(rep)
        except Exception:
            rep = str(rep)

        prov_name = str(psu_data["Prov_name"]).strip().upper()
        project_key = self.build_project_key(
            year=year,
            round_number=rnd,
        )
        base_name = (
            f"{project_key}_{prov_name}"
            f"_SELECTED_SSU_R{rep}_PSU_{psu_number}"
        )

        filename = f"{base_name}.gpkg"
        output_file = os.path.join(output_folder, filename)

        if os.path.isfile(output_file):
            try:
                os.remove(output_file)
            except OSError as exc:
                raise RuntimeError(
                    "Existing PSU GeoPackage could not be replaced.\n\n"
                    f"{output_file}\n\n{exc}"
                ) from exc

        report(22, f"PSU_{psu_number}: writing GeoPackage...")
        write_result = QgsVectorFileWriter.writeAsVectorFormat(
            refactored_layer,
            output_file,
            "UTF-8",
            QgsCoordinateReferenceSystem("EPSG:4326"),
            "GPKG",
        )
        writer_error = (
            write_result[0]
            if isinstance(write_result, tuple)
            else write_result
        )
        if writer_error != QgsVectorFileWriter.NoError:
            raise RuntimeError(
                "Could not write PSU GeoPackage.\n\n"
                f"{output_file}\n\nWriter error: {writer_error}"
            )

        self.lfs_layer = QgsVectorLayer(output_file, filename, "ogr")
        if not self.lfs_layer.isValid():
            raise RuntimeError(
                "Generated PSU GeoPackage could not be loaded.\n\n"
                f"{output_file}"
            )
        self.lfs_layer.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        self.lfs_layer.setName(base_name)

        project = QgsProject.instance()
        snap_cfg = project.snappingConfig()
        snap_cfg.setEnabled(True)
        snap_cfg.setType(QgsSnappingConfig.Vertex)
        snap_cfg.setMode(QgsSnappingConfig.AllLayers)
        snap_cfg.setTolerance(12)
        snap_cfg.setUnits(QgsTolerance.Pixels)
        snap_cfg.setIntersectionSnapping(False)
        project.setSnappingConfig(snap_cfg)

        self.bgy_layer = None
        self.clipped_raster = None
        basemap_error = None

        report(34, f"PSU_{psu_number}: loading barangay boundary...")
        bgy_layer = load_barangay_layer_smart(
            self.lfs_layer,
            geoid_prefix=geoid_prefix,
            output_folder=output_folder,
            source_layer_cache=self._barangay_source_cache,
        )

        if bgy_layer:
            self.bgy_layer = bgy_layer
            self.bgy_layer.setName("BARANGAY BOUNDARY")
            self.bgy_layer.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

            if self.chkLoadBasemap.isChecked():
                report(46, f"PSU_{psu_number}: clipping basemap...")
                try:
                    clipped_raster = clip_raster_by_bgy_memory(
                        bgy_layer,
                        geoid_prefix,
                        output_folder,
                        feedback=feedback,
                        source_raster_cache=self._source_raster_cache,
                        # Bulk clips are already small; building pyramids for
                        # every PSU adds substantial overhead.
                        build_overviews=not bulk_mode,
                        shared_clip_cache_dir=(
                            os.path.join(
                                os.path.dirname(output_folder),
                                ".geofasu_cache",
                                "basemaps",
                            )
                            if bulk_mode else None
                        ),
                    )
                    if clipped_raster and clipped_raster.isValid():
                        self.clipped_raster = clipped_raster
                except Exception as exc:
                    # Basemap is optional; keep project generation moving.
                    basemap_error = str(exc)
                    self.clipped_raster = None
        else:
            basemap_error = "Barangay boundary was not available."

        report(72, f"PSU_{psu_number}: applying styles and layer groups...")
        try:
            load_style(self.lfs_layer, "samples_rep_layer.qml")
            if self.bgy_layer and self.bgy_layer.isValid():
                load_style(self.bgy_layer, "bgy_boundary.qml")
        except Exception:
            pass

        root = project.layerTreeRoot()
        project_group = root.addGroup(f"{project_code} Layers")
        base_group = root.addGroup("Base Layer")

        project.addMapLayer(self.lfs_layer, False)
        node = project_group.addLayer(self.lfs_layer)
        node.setExpanded(False)

        if self.bgy_layer and self.bgy_layer.isValid():
            project.addMapLayer(self.bgy_layer, False)
            node = base_group.addLayer(self.bgy_layer)
            node.setExpanded(False)

        if (
            self.chkLoadBasemap.isChecked()
            and self.clipped_raster
            and self.clipped_raster.isValid()
        ):
            basemap_group = root.addGroup("Basemap")
            project.addMapLayer(self.clipped_raster, False)
            node = basemap_group.addLayer(self.clipped_raster)
            node.setItemVisibilityChecked(False)
            node.setExpanded(False)

        combined_extent = self.lfs_layer.extent()
        if self.bgy_layer and self.bgy_layer.isValid():
            combined_extent.combineExtentWith(self.bgy_layer.extent())
        if self.clipped_raster and self.clipped_raster.isValid():
            combined_extent.combineExtentWith(self.clipped_raster.extent())

        # Canvas rendering is one of the largest sources of bulk UI delay.
        # Only redraw for an interactive/single PSU generation; bulk mode
        # redraws once at the very end.
        if render_canvas:
            from qgis.utils import iface
            iface.mapCanvas().setExtent(combined_extent)
            iface.mapCanvas().refresh()

        report(84, f"PSU_{psu_number}: saving QGIS project...")
        self.remove_temporary_processing_layers()

        project_filename = f"{base_name}.qgs"
        self.generated_project_path = os.path.join(
            output_folder,
            project_filename,
        )

        project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        project.setTitle(base_name)
        if not project.write(self.generated_project_path):
            raise RuntimeError(
                "The generated QGIS project could not be saved.\n\n"
                f"{self.generated_project_path}"
            )

        self.remove_temporary_processing_layers()
        report(100, f"PSU_{psu_number}: project created.")

        return {
            "psu_number": psu_number,
            "project_key": project_key,
            "base_name": base_name,
            "output_folder": output_folder,
            "output_file": output_file,
            "project_file": self.generated_project_path,
            "combined_extent": combined_extent,
            "basemap_loaded": bool(
                self.clipped_raster and self.clipped_raster.isValid()
            ),
            "basemap_error": basemap_error,
        }

    def _bulk_package_current_project(self, package_folder, canvas_extent_override=None):
        """Package the active PSU project for QField without popup dialogs."""
        inspection = inspect_current_project(
            package_folder=package_folder,
        )

        if (
            self.chkQFieldValidate.isChecked()
            and inspection.error_count > 0
        ):
            raise RuntimeError(
                f"QField inspection found {inspection.error_count} "
                "blocking error(s)."
            )

        package_path = Path(package_folder)
        if package_path.exists():
            shutil.rmtree(package_path)
        package_path.mkdir(parents=True, exist_ok=True)

        canvas_extent = None
        if self.cmbQFieldExtent.currentText() == "Current map canvas":
            if canvas_extent_override is not None:
                canvas_extent = canvas_extent_override
            else:
                from qgis.utils import iface
                canvas_extent = iface.mapCanvas().extent()

        return package_current_project(
            package_folder=package_folder,
            extent_mode=self.cmbQFieldExtent.currentText(),
            canvas_extent=canvas_extent,
            copy_styles_resources=self.chkQFieldStyles.isChecked(),
            preserve_snapping=self.chkQFieldSnapping.isChecked(),
            relative_paths=self.chkQFieldRelativePaths.isChecked(),
        )

    def on_bulk_generate_clicked(self):
        """Start a bulk run or request cancellation of the active run."""
        if self._bulk_running:
            self._bulk_cancel_requested = True
            self.pbBulkGenerate.setText("Cancelling after current step...")
            self.pbBulkGenerate.setEnabled(False)
            self._set_preprocess_progress(
                self.progressPreprocess.value(),
                "Cancellation requested. Finishing the current operation...",
            )
            return

        self.bulk_generate_projects()

    def bulk_generate_projects(self):
        """Generate all loaded PSUs using staged bulk processing.

        Stage 1 prepares workbook/index data once.
        Stage 2 generates all QGIS projects with rendering disabled and a
        persistent shared barangay-basemap cache.
        Stage 3 creates QField packages only after every QGIS project has been
        generated, avoiding repeated generate/package/generate context switching.
        """
        if self.cbpsu_list.count() <= 0:
            QMessageBox.warning(
                self,
                "No PSU List",
                "Read the sample list before starting bulk processing."
            )
            return

        create_qgis = self.chkBulkCreateQGIS.isChecked()
        create_qfield = self.chkBulkCreateQField.isChecked()
        if create_qfield:
            create_qgis = True

        if not create_qgis and not create_qfield:
            QMessageBox.warning(
                self,
                "Nothing Selected",
                "Select at least one bulk output option."
            )
            return

        path = self.ssu_list_path.text().strip()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(
                self,
                "Missing File",
                "Select a valid sample workbook first."
            )
            return

        try:
            self.current_project_abbreviation()
        except ValueError as exc:
            QMessageBox.warning(self, "Project Abbreviation Required", str(exc))
            return

        psu_count = self.cbpsu_list.count()
        mode_text = (
            "QGIS projects and QField packages"
            if create_qfield else "QGIS projects"
        )
        answer = QMessageBox.question(
            self,
            "Bulk Generate All PSUs",
            f"GEOFASU will generate {mode_text} for {psu_count} PSU(s).\n\n"
            "High-speed staged mode will:\n"
            "• read and index the sample workbook once;\n"
            "• keep map rendering disabled during generation;\n"
            "• reuse municipality barangay sources;\n"
            "• clip identical barangay basemaps only once and reuse them;\n"
            "• generate all QGIS projects first; and\n"
            "• create QField packages afterward as a separate stage.\n\n"
            "Existing generated outputs for processed PSUs may be replaced.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        if not self.prepare_project_for_generation():
            return

        from qgis.utils import iface
        canvas = iface.mapCanvas()
        old_render_flag = canvas.renderFlag()
        original_index = self.cbpsu_list.currentIndex()

        successes = []
        failures = []
        qfield_successes = []
        qfield_failures = []
        package_queue = []
        last_success_index = None
        last_extent = None

        self._bulk_running = True
        self._bulk_cancel_requested = False
        self.pbBulkGenerate.setText("Cancel Bulk Processing")
        self._set_preprocess_progress(0, "Stage 1/3: Reading sample workbook...")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        try:
            canvas.setRenderFlag(False)
        except Exception:
            pass

        try:
            # -------------------------------------------------
            # STAGE 1 — Build shared in-memory data once.
            # -------------------------------------------------
            feedback = QgsProcessingFeedback()
            main_layer = self._build_main_sample_layer(path, feedback)
            self._set_preprocess_progress(4, "Stage 1/3: Indexing PSU sample features...")
            feature_index = self._build_psu_feature_index(main_layer)

            psu_jobs = []
            for index in range(psu_count):
                data = self.cbpsu_list.itemData(index) or {}
                output_folder, package_folder = self._paths_for_psu_data(data)
                psu_jobs.append({
                    "index": index,
                    "data": data,
                    "psu_number": data.get("PSU_number", index + 1),
                    "output_folder": output_folder,
                    "package_folder": package_folder,
                })

            # -------------------------------------------------
            # STAGE 2 — QGIS projects.
            # 6..72% of overall progress.
            # -------------------------------------------------
            qgis_start = 6.0
            qgis_end = 72.0 if create_qfield else 98.0
            qgis_span = qgis_end - qgis_start

            for job_pos, job in enumerate(psu_jobs):
                if self._bulk_cancel_requested:
                    break

                index = job["index"]
                psu_data = job["data"]
                psu_number = job["psu_number"]

                # Keep singleton project empty between PSUs, but never render it.
                if job_pos > 0:
                    project = QgsProject.instance()
                    try:
                        project.setDirty(False)
                    except Exception:
                        pass
                    self.lfs_layer = None
                    self.bgy_layer = None
                    self.clipped_raster = None
                    self.generated_project_path = None
                    project.clear()
                    project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

                def mapped_progress(local_value, local_text, pos=job_pos):
                    fraction = (pos + (float(local_value) / 100.0)) / psu_count
                    overall = qgis_start + (fraction * qgis_span)
                    self._set_preprocess_progress(
                        overall,
                        f"Stage 2/3 — QGIS projects: {local_text} "
                        f"({pos + 1}/{psu_count})",
                    )

                try:
                    result = self._generate_psu_project_core(
                        path=path,
                        psu_data=psu_data,
                        output_folder=job["output_folder"],
                        main_layer=main_layer,
                        feedback=feedback,
                        feature_index=feature_index,
                        render_canvas=False,
                        bulk_mode=True,
                        progress_callback=mapped_progress,
                    )
                    successes.append(psu_number)
                    last_success_index = index
                    last_extent = result.get("combined_extent")
                    package_queue.append({
                        **job,
                        "project_file": result.get("project_file"),
                        "extent": result.get("combined_extent"),
                    })
                except Exception as exc:
                    failures.append((psu_number, str(exc)))

            # -------------------------------------------------
            # STAGE 3 — QField packages after QGIS generation.
            # -------------------------------------------------
            if create_qfield and not self._bulk_cancel_requested:
                package_total = len(package_queue)
                package_start = 72.0
                package_end = 99.0
                package_span = package_end - package_start

                for package_pos, job in enumerate(package_queue):
                    if self._bulk_cancel_requested:
                        break

                    psu_number = job["psu_number"]
                    project_file = str(job.get("project_file") or "")
                    overall = package_start + (
                        (package_pos / max(1, package_total)) * package_span
                    )
                    self._set_preprocess_progress(
                        overall,
                        f"Stage 3/3 — QField packages: PSU_{psu_number} "
                        f"({package_pos + 1}/{package_total})",
                    )

                    try:
                        project = QgsProject.instance()
                        try:
                            project.setDirty(False)
                        except Exception:
                            pass
                        project.clear()
                        if not project.read(project_file):
                            raise RuntimeError(
                                "Could not load generated QGIS project for QField packaging:\n"
                                f"{project_file}"
                            )

                        self._bulk_package_current_project(
                            job["package_folder"],
                            canvas_extent_override=job.get("extent"),
                        )
                        qfield_successes.append(psu_number)
                    except Exception as exc:
                        qfield_failures.append((psu_number, str(exc)))

                    self._set_preprocess_progress(
                        package_start + (
                            ((package_pos + 1) / max(1, package_total)) * package_span
                        ),
                        f"Stage 3/3 — QField packages: finished PSU_{psu_number} "
                        f"({package_pos + 1}/{package_total})",
                    )

        finally:
            # Retain barangay source cache for this dialog session because it is
            # lightweight and saves expensive MAP LAYERS directory scans on the
            # next bulk run. Raster providers are released after the run.
            self._source_raster_cache.clear()

            try:
                canvas.setRenderFlag(old_render_flag)
            except Exception:
                pass

            QApplication.restoreOverrideCursor()
            self._bulk_running = False
            self.pbBulkGenerate.setEnabled(True)
            self.pbBulkGenerate.setText("Bulk Generate All PSUs")

        # Load only the final successfully generated desktop project into QGIS.
        if last_success_index is not None:
            self.cbpsu_list.setCurrentIndex(last_success_index)
            self.update_selected_psu_paths()
            final_project_file = None
            for item in reversed(package_queue):
                if item["index"] == last_success_index:
                    final_project_file = item.get("project_file")
                    break
            if final_project_file and os.path.isfile(final_project_file):
                try:
                    project = QgsProject.instance()
                    try:
                        project.setDirty(False)
                    except Exception:
                        pass
                    project.clear()
                    project.read(final_project_file)
                except Exception:
                    pass
        elif 0 <= original_index < psu_count:
            self.cbpsu_list.setCurrentIndex(original_index)
            self.update_selected_psu_paths()

        if last_extent is not None:
            try:
                canvas.setExtent(last_extent)
                canvas.refresh()
            except Exception:
                pass

        self._last_qfield_inspection = None
        self.tblQFieldLayers.setRowCount(0)
        self.pbPackageQField.setEnabled(False)

        completed = len(successes)
        qfield_completed = len(qfield_successes)
        cancelled = self._bulk_cancel_requested
        all_failures = failures + qfield_failures

        if cancelled:
            self._set_preprocess_progress(
                self.progressPreprocess.value(),
                f"Bulk processing cancelled. {completed} QGIS project(s) created.",
            )
        else:
            self._set_preprocess_progress(
                100,
                f"Bulk processing complete. {completed}/{psu_count} QGIS project(s) created.",
            )

        summary = [
            "Bulk processing finished." if not cancelled else "Bulk processing cancelled.",
            "",
            f"PSUs requested: {psu_count}",
            f"QGIS projects created: {completed}",
        ]
        if create_qfield:
            summary.append(f"QField packages created: {qfield_completed}")
        summary.append(f"QGIS generation failures: {len(failures)}")
        if create_qfield:
            summary.append(f"QField packaging failures: {len(qfield_failures)}")

        if all_failures:
            summary.extend(["", "FAILED ITEMS:"])
            shown = 0
            for psu_number, error in all_failures:
                if shown >= 10:
                    break
                summary.append(f"PSU_{psu_number}: {error}")
                shown += 1
            if len(all_failures) > 10:
                summary.append(f"...and {len(all_failures) - 10} more failure(s).")

        if all_failures:
            QMessageBox.warning(self, "Bulk Processing Complete", "\n".join(summary))
        else:
            QMessageBox.information(self, "Bulk Processing Complete", "\n".join(summary))

    # =========================================================
    # Generate Geometry
    # =========================================================
    def generate_geometry(self):
        """Generate the currently selected PSU using the optimized core."""
        try:
            project_code = self.current_project_abbreviation()
        except ValueError as exc:
            QMessageBox.warning(
                self,
                "Project Abbreviation Required",
                str(exc),
            )
            return

        path = self.ssu_list_path.text().strip()
        if not path:
            QMessageBox.warning(self, "Missing File", "Select Excel file first.")
            return
        if not os.path.isfile(path):
            QMessageBox.warning(
                self,
                "Missing File",
                "The selected Excel file does not exist.\n\n" + path,
            )
            return

        idx = self.cbpsu_list.currentIndex()
        if idx < 0:
            QMessageBox.warning(
                self,
                "No PSU Selected",
                "Select a PSU before generating geometry.",
            )
            return

        psu_data = self.cbpsu_list.itemData(idx) or {}
        psu_number = psu_data.get("PSU_number")
        if psu_number is None:
            QMessageBox.warning(
                self,
                "Invalid PSU",
                "The selected PSU does not contain a PSU number.",
            )
            return

        output_folder, _ = self._paths_for_psu_data(psu_data)
        if not output_folder:
            QMessageBox.warning(
                self,
                "Missing Output Folder",
                "The selected PSU output folder could not be determined.",
            )
            return
        os.makedirs(output_folder, exist_ok=True)

        if not self.prepare_project_for_generation():
            return

        self._source_raster_cache.clear()
        self._set_preprocess_progress(0, f"Starting PSU_{psu_number}...")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        try:
            feedback = QgsProcessingFeedback()
            self._set_preprocess_progress(3, "Reading sample workbook...")
            main_layer = self._build_main_sample_layer(path, feedback)

            result = self._generate_psu_project_core(
                path=path,
                psu_data=psu_data,
                output_folder=output_folder,
                main_layer=main_layer,
                feedback=feedback,
                feature_index=None,
                render_canvas=True,
                bulk_mode=False,
                progress_callback=self._set_preprocess_progress,
            )

            self.output_path.setText(output_folder)
            _, qfield_folder = self._paths_for_psu_data(psu_data)
            self.qfield_package_path.setText(qfield_folder)

            self._set_preprocess_progress(96, "Inspecting QField readiness...")
            # Keep existing inspection behavior for the interactive single-PSU
            # workflow. Bulk mode intentionally avoids these per-PSU popups.
            self.inspect_qfield_project()
            self._set_preprocess_progress(100, f"PSU_{psu_number} complete.")

            basemap_text = "Basemap: skipped by user."
            if self.chkLoadBasemap.isChecked():
                if result.get("basemap_loaded"):
                    basemap_text = "Basemap: extracted and loaded."
                elif result.get("basemap_error"):
                    basemap_text = (
                        "Basemap: not available.\n"
                        + str(result.get("basemap_error"))
                    )
                else:
                    basemap_text = "Basemap: not available."

            QMessageBox.information(
                self,
                "Done",
                f"{result['project_key']} PSU geometry and QGIS project were "
                "generated successfully.\n\n"
                f"GeoPackage:\n{result['output_file']}\n\n"
                f"QGIS project:\n{result['project_file']}\n\n"
                f"{basemap_text}\n\n"
                "QField package readiness was also inspected.\n\n"
                "This PSU is now the active QGIS project.",
            )

        except Exception as exc:
            self._set_preprocess_progress(
                self.progressPreprocess.value(),
                f"PSU_{psu_number} failed.",
            )
            QMessageBox.critical(self, "Error", str(exc))
        finally:
            self._source_raster_cache.clear()
            QApplication.restoreOverrideCursor()

