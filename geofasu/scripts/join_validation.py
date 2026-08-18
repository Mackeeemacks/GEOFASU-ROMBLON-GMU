import processing
from qgis.core import QgsProject


def get_unjoinable_psu(table_layer, merged_layer):

    result = processing.run(
        "native:joinattributestable",
        {
            'INPUT': table_layer,
            'FIELD': 'LFS_geoid',
            'INPUT_2': merged_layer,
            'FIELD_2': 'LFS_geoid',
            'FIELDS_TO_COPY': [],
            'METHOD': 1,
            'DISCARD_NONMATCHING': False,
            'PREFIX': '',
            'OUTPUT': 'memory:',
            'NON_MATCHING': 'memory:'
        }
    )

    layer = result['NON_MATCHING']

    # ✅ Only add to canvas if there are features
    if layer and layer.featureCount() > 0:
        layer.setName("MISSING SSUs")
        QgsProject.instance().addMapLayer(layer)
        return layer

    # ❌ Do nothing if empty
    return None