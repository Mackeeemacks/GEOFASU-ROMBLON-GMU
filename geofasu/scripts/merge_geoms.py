from qgis.core import QgsVectorLayer, QgsProject
import processing
import os


def merge_geoms(gpkg_files, output_path):

    merged_file = os.path.join(output_path, "MERGED_GEOMS.gpkg")

    processing.run(
        "native:mergevectorlayers",
        {
            'LAYERS': gpkg_files,
            'CRS': QgsVectorLayer(gpkg_files[0], '', 'ogr').crs(),
            'OUTPUT': merged_file
        }
    )

    layer = QgsVectorLayer(merged_file, "MERGED_GEOMS", "ogr")
    QgsProject.instance().addMapLayer(layer)

    return layer