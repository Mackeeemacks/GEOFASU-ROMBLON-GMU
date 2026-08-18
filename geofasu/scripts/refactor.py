def build_refactor_params(input_layer):
    return {
        "FIELDS_MAPPING": [
            {'expression': '"GEOID"', 'length': 0, 'name': 'GEOID', 'precision': 0, 'sub_type': 0, 'type': 10, 'type_name': 'text'},
            {'expression': '"Round"', 'length': 0, 'name': 'Round', 'precision': 0, 'sub_type': 0, 'type': 4, 'type_name': 'int8'},
            {'expression': '"Year"', 'length': 0, 'name': 'Year', 'precision': 0, 'sub_type': 0, 'type': 4, 'type_name': 'int8'},
            {'expression': '"RG"', 'length': 0, 'name': 'RG', 'precision': 0, 'sub_type': 0, 'type': 4, 'type_name': 'int8'},
            {'expression': '"REG"', 'length': 0, 'name': 'REG', 'precision': 0, 'sub_type': 0, 'type': 4, 'type_name': 'int8'},
            {'expression': '"PRV"', 'length': 0, 'name': 'PRV', 'precision': 0, 'sub_type': 0, 'type': 4, 'type_name': 'int8'},
            {'expression': '"MUN"', 'length': 0, 'name': 'MUN', 'precision': 0, 'sub_type': 0, 'type': 4, 'type_name': 'int8'},
            {'expression': '"BGY"', 'length': 0, 'name': 'BGY', 'precision': 0, 'sub_type': 0, 'type': 4, 'type_name': 'int8'},
            {'expression': '"EA"', 'length': 0, 'name': 'EA', 'precision': 0, 'sub_type': 0, 'type': 10, 'type_name': 'text'},
            {'expression': '"Replicate_Number"', 'length': 0, 'name': 'Replicate_Number', 'precision': 0, 'sub_type': 0, 'type': 4, 'type_name': 'int8'},
            {'expression': '"PSU_number"', 'length': 0, 'name': 'PSU_number', 'precision': 0, 'sub_type': 0, 'type': 4, 'type_name': 'int8'},
            {'expression': '"BSN"', 'length': 0, 'name': 'BSN', 'precision': 0, 'sub_type': 0, 'type': 4, 'type_name': 'int8'},
            {'expression': '"HUSN"', 'length': 0, 'name': 'HUSN', 'precision': 0, 'sub_type': 0, 'type': 4, 'type_name': 'int8'},
            {'expression': '"HSN"', 'length': 0, 'name': 'HSN', 'precision': 0, 'sub_type': 0, 'type': 4, 'type_name': 'int8'},
            {'expression': '"PSU_Name"', 'length': 0, 'name': 'PSU_Name', 'precision': 0, 'sub_type': 0, 'type': 10, 'type_name': 'text'},
            {'expression': '"HH_Head"', 'length': 0, 'name': 'HH_Head', 'precision': 0, 'sub_type': 0, 'type': 10, 'type_name': 'text'},
            {'expression': '"Address"', 'length': 0, 'name': 'Address', 'precision': 0, 'sub_type': 0, 'type': 10, 'type_name': 'text'},
            {'expression': '"HH_Members"', 'length': 0, 'name': 'HH_Members', 'precision': 0, 'sub_type': 0, 'type': 10, 'type_name': 'text'},
            {'expression': '"WKT"', 'length': 0, 'name': 'WKT', 'precision': 0, 'sub_type': 0, 'type': 10, 'type_name': 'text'},
            {'expression': '"Remarks"', 'length': 0, 'name': 'Remarks', 'precision': 0, 'sub_type': 0, 'type': 10, 'type_name': 'text'},
            {'expression': '"Selected_SSU"', 'length': 0, 'name': 'Selected_SSU', 'precision': 0, 'sub_type': 0, 'type': 10, 'type_name': 'text'},
            {'expression': '"n_hhhead"', 'length': 0, 'name': 'N_HHEAD', 'precision': 0, 'sub_type': 0, 'type': 10, 'type_name': 'text'},
            {'expression': '"n_address"', 'length': 0, 'name': 'N_ADDRESS', 'precision': 0, 'sub_type': 0, 'type': 10, 'type_name': 'text'},
            {'expression': '"Update Codes"', 'length': 0, 'name': 'N_UCODE', 'precision': 0, 'sub_type': 0, 'type': 10, 'type_name': 'text'},
            {'expression': '"n_remarks"', 'length': 0, 'name': 'N_REMARKS', 'precision': 0, 'sub_type': 0, 'type': 10, 'type_name': 'text'}
        ],
        "INPUT": input_layer,
        "OUTPUT": "memory:"
    }