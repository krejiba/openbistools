import h5py
from datetime import datetime


def parse_h5oina(path, keys):
    metadata = dict.fromkeys(keys)
    try:
        with h5py.File(path, "r") as file:
            datetime_obj = datetime.fromisoformat(
                file["1/EBSD/Header/Acquisition Date"][0].decode()
            )
            metadata["DATETIME"] = datetime_obj.isoformat("T")
            metadata["DATE"] = datetime_obj.date().isoformat()
            metadata["TIME"] = datetime_obj.time().isoformat()
            metadata["EBSD_X_STEP_UM"] = float(
                file["1/EBSD/Header/X Step"][0]
            )  # already in um
            metadata["EBSD_Y_STEP_UM"] = float(
                file["1/EBSD/Header/Y Step"][0]
            )  # already in um
            metadata["EBSD_X_CELLS"] = int(file["1/EBSD/Header/X Cells"][0])
            metadata["EBSD_Y_CELLS"] = int(file["1/EBSD/Header/Y Cells"][0])
            metadata["SOFTWAREVERSION"] = file["Software Version"][0].decode()
            metadata["ACCELERATING_VOLTAGE"] = float(
                file["1/EBSD/Header/Beam Voltage"][0]
            )  # already in kV
            metadata["PROJECT_NAME"] = file["1/EBSD/Header/Project Label"][0].decode()
            metadata["SAMPLE_NAME"] = file["1/EBSD/Header/Specimen Label"][0].decode()
            metadata["AREA_NAME"] = file["1/EBSD/Header/Site Label"][0].decode()
            metadata["CONTAINS_PATTERNS"] = "Processed Patterns" in file["1/EBSD/Data"]
            has_sem = "Electron Image" in file["1"]
        metadata["NUM_SAMPLES"] = 1
        metadata["NUM_AREAS"] = 1
    except KeyError:
        pass
    return metadata
