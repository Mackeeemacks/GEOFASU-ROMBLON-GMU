from qgis.core import (
    QgsVectorLayer, QgsVectorFileWriter,
    QgsField, QgsFeature, QgsProject
)
from PyQt5.QtCore import QVariant
import os


def create_psu_master_table(excel_rows, output_path):

    field_names = [
        "GEOID","Round","Year","RG","Reg_Name","Prov_name","Mun_name",
        "PSU_Name","REG","PRV","MUN","BGY","EA","Replicate_Number",
        "PSU_number","BSN","HUSN","HSN","HH_Head","Address","WKT",
        "Remarks","Selected_SSU","inCentroid","orig_wkt"
    ]

    fields = [QgsField(n, QVariant.String) for n in field_names]
    fields.append(QgsField("LFS_geoid", QVariant.String))

    layer = QgsVectorLayer("None", "PSU_MASTER_TABLE", "memory")
    dp = layer.dataProvider()
    dp.addAttributes(fields)
    layer.updateFields()

    features = []

    for row in excel_rows:

        GEOID = str(row[0]).strip() if row[0] else ""

        BSN = f"{int(row[15]) if row[15] else 0:04d}"
        HUSN = f"{int(row[16]) if row[16] else 0:04d}"
        HSN = f"{int(row[17]) if row[17] else 0:04d}"

        LFS_geoid = GEOID + BSN + HUSN + HSN

        f = QgsFeature()
        f.setAttributes(list(row[:25]) + [LFS_geoid])
        features.append(f)

    dp.addFeatures(features)

    file_path = os.path.join(output_path, "PSU_MASTER_TABLE.gpkg")

    QgsVectorFileWriter.writeAsVectorFormat(
        layer, file_path, "UTF-8", layer.crs(), "GPKG"
    )

    final_layer = QgsVectorLayer(file_path, "PSU_MASTER_TABLE", "ogr")
    QgsProject.instance().addMapLayer(final_layer)

    return final_layer