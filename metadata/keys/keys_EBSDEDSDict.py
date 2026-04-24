# These are the keys of the dictionary that are used in the definiton of
# the datatype in openBIS
# i.e. the automatic metadata extraction script needs to fill these keys and
# and pass them on to openBIS when registering a file of type "EBSD_EXP_DATA",
# "EBSD-EDS_DATA", or "EDS_DATA".

keys_EBSDEDSDictGeneric = [
    "PROJECT_NAME",
    "SAMPLE_NAME",
    "AREA_NAME",  # 'AREA_NAME_1', 'AREA_NAME_2', 'AREA_NAME_3', 'AREA_NAME_4', 'AREA_NAME_5', 'AREA_NAME_6',
    "NUM_SAMPLES",
    "NUM_AREAS",
    "SOFTWAREVERSION",
    "ACCELERATING_VOLTAGE",
    "DATETIME",
    "DATE",
    "TIME",
    "EBSD_GRID_TYPE",
    "EBSD_X_STEP_UM",
    "EBSD_Y_STEP_UM",
    "EBSD_X_CELLS",
    "EBSD_Y_CELLS",
    "EBSD_GRID_TYPE",
    "CONTAINS_PATTERNS",
]

keys_EBSDEDSDict = keys_EBSDEDSDictGeneric + []

keys_EDSDict = keys_EBSDEDSDictGeneric + []

keys_EBSDDict = keys_EBSDEDSDictGeneric + []
