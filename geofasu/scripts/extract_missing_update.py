import processing
from qgis.core import QgsProject

def extract_missing_update(merged_layer):
    """
    Extract features from MERGED_GEOMS where:
    - Selected_SSU = 1
    - Update Codes is NULL or empty
    Returns a memory layer named "Missing Update Code".
    """

    if not merged_layer or not merged_layer.isValid():
        print("Invalid input layer")
        return None

    # Build expression: Selected_SSU = 1 AND ("Update Codes" IS NULL OR "Update Codes" = '')
    expr = '"Selected_SSU" = 1 AND ("Update Codes" IS NULL OR "Update Codes" = \'\')'

    result = processing.run(
        "native:extractbyexpression",
        {
            'INPUT': merged_layer,
            'EXPRESSION': expr,
            'OUTPUT': 'memory:'
        }
    )

    missing_layer = result['OUTPUT']

    if missing_layer and missing_layer.isValid() and missing_layer.featureCount() > 0:
        missing_layer.setName("ORIGINAL SAMPLES WITH NO UPDATE CODES")
        QgsProject.instance().addMapLayer(missing_layer)
        print(f"Missing Update Code layer created with {missing_layer.featureCount()} features")
        return missing_layer
    else:
        print("No features found for Missing Update Code")
        return None