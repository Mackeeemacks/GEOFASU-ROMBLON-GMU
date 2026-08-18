# -*- coding: utf-8 -*-

from qgis.core import (
    QgsVectorLayer,
    QgsProcessing,
    QgsProcessingFeedback,
    QgsProcessingContext,
    QgsProject
)
import processing

def refactor_psu_layer(input_layer, context=None, feedback=None):
    if feedback is None:
        feedback = QgsProcessingFeedback()
    if context is None:
        context = QgsProcessingContext()

    # --- Define field mapping ---
    alg_params = {
        'FIELDS_MAPPING': [
            {'expression': '"GEOID"','length': 0,'name': 'GEOID','precision': 0,'sub_type': 0,'type': 4,'type_name': 'int8'},
            {'expression': '"Round"','length': 0,'name': 'Round','precision': 0,'sub_type': 0,'type': 2,'type_name': 'integer'},
            {'expression': '"Year"','length': 0,'name': 'Year','precision': 0,'sub_type': 0,'type': 2,'type_name': 'integer'},
            {'expression': '"RG"','length': 0,'name': 'RG','precision': 0,'sub_type': 0,'type': 2,'type_name': 'integer'},
            {'expression': '"Reg_Name"','length': 0,'name': 'Reg_Name','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"Prov_name"','length': 0,'name': 'Prov_name','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"Mun_name"','length': 0,'name': 'Mun_name','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"PSU_Name"','length': 0,'name': 'PSU_Name','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': 'lpad("REG",2,0)','length': 0,'name': 'REG','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': 'lpad("PRV",3,0)','length': 0,'name': 'PRV','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': 'lpad("MUN",2,0)','length': 0,'name': 'MUN','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': 'lpad("BGY",3,0)','length': 0,'name': 'BGY','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': 'lpad("EA",6,0)','length': 0,'name': 'EA','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"Replicate_Number"','length': 0,'name': 'Replicate_Number','precision': 0,'sub_type': 0,'type': 2,'type_name': 'integer'},
            {'expression': '"PSU_number"','length': 0,'name': 'PSU_number','precision': 0,'sub_type': 0,'type': 2,'type_name': 'integer'},
            {'expression': 'lpad("BSN",4,0)','length': 0,'name': 'BSN','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': 'lpad("HUSN",4,0)','length': 0,'name': 'HUSN','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': 'lpad("HSN",4,0)','length': 0,'name': 'HSN','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': 'lpad("BSN",4,0)','length': 0,'name': 'BSN_Orig','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': 'lpad("HUSN",4,0)','length': 0,'name': 'HUSN_Orig','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': 'lpad("HSN",4,0)','length': 0,'name': 'HSN_Orig','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"HH_Head"','length': 0,'name': 'HH_Head','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"HH_Head"','length': 0,'name': 'HH_Head_Orig','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"Address"','length': 0,'name': 'Address','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"Address"','length': 0,'name': 'Address_Orig','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"Remarks"','length': 0,'name': 'Remarks','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': 'CASE WHEN ("Selected_SSU" IS NULL or "Selected_SSU" = \'\') THEN \'1\' ELSE "Selected_SSU" END','length': 0,'name': 'Selected_SSU','precision': 0,'sub_type': 0,'type': 2,'type_name': 'integer'},
            {'expression': 'inCentroid','length': 0,'name': 'inCentroid','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': 'orig_wkt','length': 0,'name': 'orig_wkt','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"Update Codes"','length': 0,'name': 'Update Codes','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"UC_2_ind"','length': 0,'name': 'UC_2_ind','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"uc_6_ind"','length': 0,'name': 'uc_6_ind','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"n_hhhead"','length': 0,'name': 'n_hhhead','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"n_address"','length': 0,'name': 'n_address','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"n_husn"','length': 0,'name': 'n_husn','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"n_hsn"','length': 0,'name': 'n_hsn','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"m_uc_ind"','length': 0,'name': 'm_uc_ind','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'},
            {'expression': '"m_uc"','length': 0,'name': 'm_uc','precision': 0,'sub_type': 0,'type': 10,'type_name': 'text'}
        ],
        'INPUT': input_layer,
        'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
    }

    # --- Run Refactor Fields ---
    result = processing.run('native:refactorfields', alg_params, context=context, feedback=feedback)

    # --- Get the actual output layer object ---
    out_layer = result['OUTPUT']  # This is a QgsVectorLayer already in QGIS 3.32+

    return out_layer