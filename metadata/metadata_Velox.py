from pathlib import Path
import rsciio.emd as emd
from datetime import datetime
from .helpers import clean, convert_value
from decimal import Decimal, getcontext


def get_metadata(path: str) -> dict:
    """
    Extracts metadata key-value pairs from an `.emd` file.

    The keys mainly follow the RosettaSciIO nomenclature.

    Args:
        path (str): The file path to the `.emd` file.

    Returns:
        dict: A dictionary containing metadata related to the TEM data.

    Raises:
        TypeError: If the file extension is not `.emd`, or if the file cannot be parsed by RosettaSciIO.
        ValueError:
    """
    path = Path(path)
    ext = path.suffix[1:]
    if ext == "emd":
        file_reader = emd.file_reader
    else:
        raise TypeError(f"This parser is intended for emd files!")
    try:
        file_content = file_reader(path)
    except Exception as e:
        raise TypeError(f"RosettaSciIO was not able to parse the {ext} file!")
    if not isinstance(file_content, list):
        raise TypeError("File content is not a list!")
    num_datasets = len(file_content)

    raw_metadata = {}
    for dataset_idx, dataset in enumerate(file_content):
        if "original_metadata" in dataset and "metadata" in dataset:
            raw_metadata.update(
                {
                    f"Dataset{dataset_idx}." + k: v
                    for k, v in dataset["original_metadata"].items()
                }
            )
            raw_metadata.update(
                {
                    f"Dataset{dataset_idx}." + k: v
                    for k, v in dataset["metadata"].items()
                }
            )
    file_content = file_content[0]
    if "data" in dataset:
        ndim = dataset["data"].ndim
        if ndim == 2:
            num_frames = 1
            num_channels = 1
        elif ndim == 3:
            num_frames = dataset["data"].shape[0]
            num_channels = 1
        else:
            raise ValueError("4D image")
        datatype = str(dataset["data"].dtype)
        bitdepth_str = datatype.replace("uint", "").replace("int", "")
        bitdepth_str = bitdepth_str.replace("float", "")
        try:
            bitdepth = int(bitdepth_str)
        except ValueError:
            raise ValueError("Cannot convert Bit Depth to int !")
    del file_content
    metadata_dict = clean(raw_metadata)

    final_metadata_dict = {}
    for k, v in metadata_dict.items():
        if "Detector" in k or "Title" in k:
            new_key = k
        else:
            new_key = ".".join(k.split(".")[1:])
        final_metadata_dict[new_key] = v
    final_metadata_dict["NumberOfDatasets"] = num_datasets
    final_metadata_dict["NumberOfFrames"] = num_frames
    final_metadata_dict["NumberOfChannels"] = num_channels
    final_metadata_dict["DataType"] = datatype
    final_metadata_dict["BitDepth"] = bitdepth

    return final_metadata_dict


def filter_metadata(md_dict: dict, keys: list) -> dict:
    """
    Filters metadata extracted from a `.emd` file.

    The new keys match the openBIS schema.

    Args:
        md_dict (dict): The dictionary containing metadata related to the TEM data

    Returns:
        dict: A dictionary containing metadata to be used in openBIS.

    Raises:
        ValueError: If the pixels are not square.
    """
    field_map = {
        "CustomProperties.StemMagnification.Value": "MAGNIFICATION_REAL",
        "Instrument.ControlSoftwareVersion": "SOFTWAREVERSION",
        "Instrument.InstrumentClass": "DEVICE_NAME",
        "Instrument.Manufacturer": "DEVICE_MANUFACTURER",
        "Optics.AccelerationVoltage": "ACCELERATING_VOLTAGE",
        "Optics.BeamConvergence": "BEAM_CONVERGENCE_MRAD",
        "Optics.CameraLength": "CAMERA_LENGTH_MM",
        "Optics.ExtractorVoltage": "EXTRACTION_VOLTAGE",
        "Optics.IlluminationMode": "IS_STEM",
        "Optics.SpotIndex": "SPOT_SIZE_SETTING",
        "Scan.FrameTime": "FRAME_TIME",
        "Scan.ScanSize.Width": "DATA_SIZE_X",
        "Scan.ScanSize.Height": "DATA_SIZE_Y",
        "Scan.DwellTime": "DWELL_TIME",
        "Scan.LineTime": "LINE_TIME",
        "Stage.Position.X": "STAGE_X_UM",
        "Stage.Position.Y": "STAGE_Y_UM",
        "Stage.Position.Z": "STAGE_Z_UM",
        "Stage.AlphaTilt": "STAGE_TILT_A",
        "Stage.BetaTilt": "STAGE_TILT_B",
        "Stage.HolderType": "STAGE_HOLDER_TYPE",
        "BitDepth": "BIT_DEPTH",
        "DataType": "DATA_TYPE",
        "NumberOfFrames": "NUMBER_OF_FRAMES",
        "NumberOfChannels": "NUMBER_OF_CHANNELS",
        "NumberOfDatasets": "NUMBER_OF_DATASETS",
    }
    out_dict = dict.fromkeys(keys)

    # Set precision

    getcontext().prec = 10

    # Handle detectors' metadata

    for i in range(1, 1 + md_dict["NumberOfDatasets"]):
        detector_name = md_dict.get(f"Dataset{i-1}.BinaryResult.Detector")
        title = md_dict.get(f"Dataset{i-1}.General.Title")
        detector_idx = md_dict.get(f"Dataset{i-1}.BinaryResult.DetectorIndex")
        if detector_name and detector_idx is not None:
            if title != detector_name:
                detector_name = f"{title}({detector_name})"  # e.g. DCFI(HAADF)
            detector_prefix = f"Dataset{i-1}.Detectors.Detector-{detector_idx}."
            detector_type = md_dict.get(detector_prefix + "DetectorType")
            detector_gain = md_dict.get(detector_prefix + "Gain")
            detector_offset = md_dict.get(detector_prefix + "Offset")
            exposure = md_dict.get(detector_prefix + "ExposureTime")
            out_dict[f"DETECTOR{i}_NAME"] = detector_name
            out_dict[f"DETECTOR{i}_TYPE"] = detector_type
            out_dict[f"DETECTOR{i}_GAIN"] = detector_gain
            out_dict[f"DETECTOR{i}_OFFSET"] = detector_offset
            out_dict[f"EXPOSURE_TIME"] = exposure  # Same exposure for all detectors
    # Datetime

    date_str = md_dict.get("General.Date")
    time_str = md_dict.get("General.Time")
    if date_str and time_str:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        if "AM" in time_str or "PM" in time_str:
            time_obj = datetime.strptime(time_str, "%I:%M:%S %p").time()
        else:
            time_obj = datetime.strptime(time_str, "%H:%M:%S").time()
        out_dict["DATETIME"] = datetime.combine(date_obj, time_obj).isoformat(" ")
        out_dict["DATE"] = date_obj.isoformat()
        out_dict["TIME"] = time_obj.isoformat()
    pixel_x = md_dict.get("BinaryResult.PixelSize.Width")
    pixel_y = md_dict.get("BinaryResult.PixelSize.Height")
    unit_x = md_dict.get("BinaryResult.PixelUnitX")
    unit_y = md_dict.get("BinaryResult.PixelUnitY")

    if unit_x == unit_y:
        if len(unit_x) == 1:
            unit_x = "1" + unit_x
        if unit_x.startswith("1/"):
            out_dict["PIXEL_SIZE_X"] = convert_value(pixel_x, "nm", unit_x[2:])
            out_dict["PIXEL_SIZE_Y"] = convert_value(pixel_y, "nm", unit_x[2:])
            out_dict["PIXEL_UNIT_X"] = out_dict["PIXEL_UNIT_Y"] = "1/nm"
            imaging_mode = "DIFFRACTION"
        else:
            out_dict["PIXEL_SIZE_X"] = convert_value(pixel_x, unit_x, "nm")
            out_dict["PIXEL_SIZE_Y"] = convert_value(pixel_y, unit_x, "nm")
            out_dict["PIXEL_UNIT_X"] = out_dict["PIXEL_UNIT_Y"] = "nm"
            imaging_mode = "IMAGING"
        out_dict["TEM_IMAGING_MODE"] = imaging_mode
    else:
        raise ValueError("Different units used for pixels")
    # Copy remaining

    for old_key in field_map:
        out_dict[field_map[old_key]] = md_dict.get(old_key)
    # ####################### Convert Numerical Values #######################

    # Convert decimal values (Assumption SI units)

    fields_with_units = [
        ("CAMERA_LENGTH_MM", "mm", "1m"),
        ("STAGE_X_UM", "um", "1m"),
        ("STAGE_Y_UM", "um", "1m"),
        ("STAGE_Z_UM", "um", "1m"),
        ("DWELL_TIME", "us", "1s"),
        ("LINE_TIME", "ms", "1s"),
        ("ACCELERATING_VOLTAGE", "kV", "1V"),
    ]
    for name, new_unit, old_unit in fields_with_units:
        val_str = out_dict.get(name)
        if val_str:
            out_dict[name] = convert_value(val_str, old_unit, new_unit)
    # Convert Beam Convergence Angle

    beamangle = out_dict.get("BEAM_CONVERGENCE_MRAD")
    if beamangle:
        out_dict["BEAM_CONVERGENCE_MRAD"] = Decimal(beamangle) * Decimal(1000)
    # Convert angles from radians to degrees

    rad2deg = Decimal(180) / Decimal("3.14159265359")
    for k in [
        "STAGE_TILT_A",
        "STAGE_TILT_B",
    ]:
        angle = out_dict.get(k)
        if angle:
            out_dict[k] = Decimal(angle) * rad2deg
    # Round all decimals

    for k, v in out_dict.items():
        if isinstance(v, float):
            v = Decimal(v)
        if isinstance(v, Decimal):
            out_dict[k] = +v
    # ############################### Clean up ###############################

    # Flag for STEM images

    is_stem = out_dict.get("IS_STEM")
    is_stem = is_stem == "Probe"
    out_dict["IS_STEM"] = is_stem

    # Control for Microscope Manufacturer

    manufacturer = out_dict.get("DEVICE_MANUFACTURER")
    if manufacturer:
        for name in ["JEOL", "ZEISS", "FEI", "HITACHI"]:
            if name.lower() in manufacturer.lower():
                out_dict["DEVICE_MANUFACTURER"] = name
                break
    # ############################## Sanity Check #############################

    set_a = set(out_dict.keys())
    set_b = set(keys)
    assert set_a == set_b, print("Problem:", set_a.symmetric_difference(set_b))

    return out_dict


def parse(filename: str, keys: list) -> dict:
    """
    Extracts relevant TEM metadata from a Velox emd file.

    Args:
        filename (str): The path to the Velox emd file.
        keys (list): A list of keys that define the metadata schema.
    Returns:
        md_dict (dict): A dictionary containing the extracted metadata.
    """
    metadata = get_metadata(filename)
    md_dict = filter_metadata(metadata, keys)
    return md_dict
