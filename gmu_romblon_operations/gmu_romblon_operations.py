# -*- coding: utf-8 -*-
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication
from qgis import processing

from .processing.provider import GmuRomblonProvider


class GmuRomblonOperations:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.onemap_toolbar = None
        self.validate_action = None

    def initGui(self):
        self.provider = GmuRomblonProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

        self.onemap_toolbar = self.iface.addToolBar("GMU Romblon Operations - 1MAP")
        self.onemap_toolbar.setObjectName("GmuRomblonOperations1MapToolbar")

        self.validate_action = QAction(
            "Validate EA–Barangay Vertex Snapping",
            self.iface.mainWindow()
        )
        self.validate_action.setToolTip(
            "Check every EA vertex against its corresponding barangay and create a discrepancy point layer."
        )
        self.validate_action.triggered.connect(self.run_vertex_validation)
        self.onemap_toolbar.addAction(self.validate_action)

    def unload(self):
        if self.validate_action is not None and self.onemap_toolbar is not None:
            self.onemap_toolbar.removeAction(self.validate_action)
            self.validate_action.deleteLater()
            self.validate_action = None

        if self.onemap_toolbar is not None:
            self.onemap_toolbar.deleteLater()
            self.onemap_toolbar = None

        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

    def run_vertex_validation(self):
        processing.execAlgorithmDialog(
            "gmu_romblon_operations:validate_ea_barangay_vertices",
            {}
        )
