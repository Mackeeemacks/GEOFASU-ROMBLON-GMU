from qgis.core import QgsField
from PyQt5.QtCore import QVariant


def add_lfs_geoid(layer):

    layer.startEditing()

    if layer.fields().indexFromName("LFS_geoid") < 0:
        layer.dataProvider().addAttributes(
            [QgsField("LFS_geoid", QVariant.String)]
        )
        layer.updateFields()

    idx = layer.fields().indexFromName("LFS_geoid")

    for f in layer.getFeatures():

        geoid = str(f["GEOID"]) if f["GEOID"] else ""
        bsn = f"{int(f['BSN']) if f['BSN'] else 0:04d}"
        husn = f"{int(f['HUSN']) if f['HUSN'] else 0:04d}"
        hsn = f"{int(f['HSN']) if f['HSN'] else 0:04d}"

        layer.changeAttributeValue(
            f.id(), idx, geoid + bsn + husn + hsn
        )

    layer.commitChanges()