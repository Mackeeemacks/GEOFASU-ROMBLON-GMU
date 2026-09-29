# -*- coding: utf-8 -*-
from qgis.core import QgsProcessingProvider

from .onemap.validate_ea_barangay_vertices import ValidateEABarangayVerticesAlgorithm


class GmuRomblonProvider(QgsProcessingProvider):
    def id(self):
        return "gmu_romblon_operations"

    def name(self):
        return "GMU Romblon Operations"

    def longName(self):
        return self.name()

    def loadAlgorithms(self):
        self.addAlgorithm(ValidateEABarangayVerticesAlgorithm())
