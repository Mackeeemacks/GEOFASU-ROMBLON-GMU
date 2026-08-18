from qgis.core import QgsVectorLayer, QgsProject, QgsProcessingFeedback, QgsVectorFileWriter
import os
import processing

def load_barangay_layer_smart(source_layer, geoid_prefix=None, base_folder=r"C:/PSA-GIS/MAP LAYERS", output_folder=None):
    """
    Load matching Barangay layer, join attributes by location with source_layer (LFS),
    save as GeoPackage in output_folder, and load in the canvas.
    """

    if not os.path.exists(base_folder):
        raise Exception(f"MAP LAYERS folder not found: {base_folder}")

    if geoid_prefix is None:
        raise Exception("GEOID prefix not provided.")

    if output_folder is None:
        raise Exception("Output folder not provided.")

    os.makedirs(output_folder, exist_ok=True)

    geoid_prefix = str(geoid_prefix)
    checked_layers = []

    # --- Find the original Barangay layer ---
    bgy_layer = None
    for root, _, files in os.walk(base_folder):
        for file in files:

            if not file.lower().endswith(".gpkg"):
                continue

            if not file.startswith(geoid_prefix):
                continue

            gpkg_path = os.path.join(root, file)
            container = QgsVectorLayer(gpkg_path, file, "ogr")
            if not container.isValid():
                checked_layers.append(f"{gpkg_path} (invalid container)")
                continue

            for sub in container.dataProvider().subLayers():
                parts = sub.split("!!::!!")
                if len(parts) < 2:
                    continue
                layer_name = parts[1]
                uri = f"{gpkg_path}|layername={layer_name}"
                layer = QgsVectorLayer(uri, layer_name, "ogr")
                checked_layers.append(f"{gpkg_path} -> {layer_name}")

                if not layer.isValid() or layer.geometryType() != 2:
                    continue
                if "bgy" not in layer_name.lower() and "barangay" not in layer_name.lower():
                    continue

                bgy_layer = layer
                break
            if bgy_layer:
                break
        if bgy_layer:
            break

    if bgy_layer is None:
        checked_str = "\n".join(checked_layers)
        raise Exception(
            f"No matching Barangay layer found.\n\n"
            f"Prefix used: {geoid_prefix}\n"
            f"Search folder:\n{base_folder}\n\n"
            f"Checked GeoPackages / Layers:\n{checked_str}"
        )

    # --- Perform Join Attributes by Location (intersect + within) ---
    feedback = QgsProcessingFeedback()
    join_params = {
        'INPUT': bgy_layer,
        'JOIN': source_layer,
        'JOIN_FIELDS': [],
        'PREDICATE': [0,5],  # intersect, within
        'METHOD': 1,  # take first match
        'DISCARD_NONMATCHING': True,
        'PREFIX': '',
        'OUTPUT': 'memory:'
    }

    joined_result = processing.run(
        'native:joinattributesbylocation',
        join_params,
        feedback=feedback
    )['OUTPUT']

    # --- Save to GeoPackage in output_folder ---
    output_file = os.path.join(output_folder, f"{geoid_prefix}_bgy.gpkg")
    QgsVectorFileWriter.writeAsVectorFormat(
        joined_result,
        output_file,
        "UTF-8",
        joined_result.crs(),
        "GPKG"
    )

    # --- Load the joined layer with custom name ---
    final_layer = QgsVectorLayer(output_file, "BARANGAY BOUNDARY", "ogr")
    #if final_layer.isValid():
    #    QgsProject.instance().addMapLayer(final_layer)
    return final_layer
    #else:
    #    raise Exception("Failed to load joined Barangay layer after saving.")
    