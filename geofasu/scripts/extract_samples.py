import processing
from qgis.core import QgsProject


def extract_missing_original_samples(unmatched_layer):

    result = processing.run(
        "native:extractbyattribute",
        {
            'INPUT': unmatched_layer,
            'FIELD': 'Selected_SSU',
            'OPERATOR': 0,
            'VALUE': '1',
            'OUTPUT': 'memory:'
        }
    )

    layer = result['OUTPUT']

    if layer:
        layer.setName("Missing Original Samples")
        QgsProject.instance().addMapLayer(layer)

    return layer