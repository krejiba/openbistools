from datetime import datetime
import struct
from decimal import Decimal, getcontext


def convert_value(value, actual_unit, desired_unit):
    """Converts a decimal value from one unit to another.

    Args:
        value (str): The value to be converted.
        actual_unit (str): The actual unit of the value.
        desired_unit (str): The desired unit for the conversion.

    Returns:
        Decimal: The converted value.
    """
    if actual_unit == desired_unit:
        return Decimal(value)
    conversion_map = {
        "f": 1e-15,
        "p": 1e-12,
        "n": 1e-9,
        "u": 1e-6,
        "m": 1e-3,
        "c": 1e-2,
        "d": 1e-1,
        "1": 1,
        "h": 1e2,
        "k": 1e3,
        "M": 1e6,
        "G": 1e9,
        "T": 1e12,
        "P": 1e15,
    }
    allowed = conversion_map.keys()
    assert len(actual_unit) == 2, "%s is NOT two characters" % actual_unit
    assert len(desired_unit) == 2, "%s is NOT two characters" % desired_unit
    assert actual_unit[0] in allowed, "%s not supported" % actual_unit[0]
    assert desired_unit[0] in allowed, "%s not supported" % desired_unit[0]

    conversion_map = {k: Decimal(v) for k, v in conversion_map.items()}
    desired = conversion_map[desired_unit[0]]
    actual = conversion_map[actual_unit[0]]
    factor = actual / desired
    return Decimal(value) * factor


def get_tif_baseline_tags(filename):
    """Extracts baseline tags from a *.tif image.

    The information is contained in the *.tif tags 256, 257, 277, and 258.

    Args:
        filename (str): Filename of the *.tif file.

    Returns:
        :obj:`tuple` of :obj:`int`: tuple containing width, height, number of
            channels, number of frames, bit depth (per channel), and a flag
            for a linear LookUpTable

    """

    with open(filename, "rb") as f:

        header = f.read(8)
        byte_order = header[:2]

        if len(header) != 8:
            raise RuntimeError(
                "Invalid header for TIF image!\nFile might be corrupted!"
            )

        if byte_order not in [b"II", b"MM"]:
            raise ValueError(
                "Only TIF(F) images can be processed by this function!\n"
                + "You provided: %s" % filename
            )

        byte_order = "<" if byte_order == b"II" else ">"

        num_frames = 0  # Number of IFDs

        # Offset to first IFD
        ifd_offset = struct.unpack(byte_order + "I", header[4:8])[0]

        while ifd_offset:
            num_frames = num_frames + 1
            f.seek(ifd_offset)
            # Get the number of tags
            num_entries = struct.unpack(byte_order + "H", f.read(2))[0]
            ifd_entries = {}
            for _ in range(num_entries):
                ifd_entry = struct.unpack(byte_order + "HHII", f.read(12))
                tag, datatype, num_values, val_offset = ifd_entry
                ifd_entries[tag] = ifd_entry
            ifd_offset = struct.unpack(byte_order + "I", f.read(4))[0]

        desired_tags = set([256, 257, 258, 262, 277])
        parsed_tags = set(ifd_entries.keys())

        if desired_tags.issubset(parsed_tags):
            width = ifd_entries[256][3]  # ImageWidth
            height = ifd_entries[257][3]  # ImageLength
            num_channels = ifd_entries[277][3]  # SamplesPerPixel

            n_channels = ifd_entries[258][2]  # Inferred number of channels
            if n_channels > 1:
                f.seek(ifd_entries[258][3])
                bit_depths = struct.unpack(
                    byte_order + "%sH" % n_channels, f.read(2 * n_channels)
                )
                bit_depth = bit_depths[0]
            else:
                bit_depth = ifd_entries[258][3]  # BitsPerSample

            is_linearlut = None
            colormap_entry = ifd_entries.get(320)  # ColorMap
            if colormap_entry:
                num_values = ifd_entries[320][2]
                colormap_offset = ifd_entries[320][3]
                f.seek(colormap_offset)
                lookup_table = struct.unpack(
                    byte_order + "%sH" % num_values, f.read(2 * num_values)
                )
                reds = list(lookup_table[0 : num_values // 3])
                greens = list(lookup_table[num_values // 3 : 2 * num_values // 3])
                blues = list(lookup_table[2 * num_values // 3 : num_values])
                differnce = lambda l1, l2: [i - j for i, j in zip(l1, l2)]
                reds_diff = differnce(reds[1:], reds[:-1])
                greens_diff = differnce(greens[1:], greens[:-1])
                blues_diff = differnce(blues[1:], blues[:-1])
                num_reds = len(set(reds_diff)) - 1
                num_greens = len(set(greens_diff)) - 1
                num_blues = len(set(blues_diff)) - 1
                is_linearlut = not all([num_reds, num_greens, num_blues])

            # Sanity checks
            assert n_channels == num_channels, "Inconsistent Number of Channels"
            # PhotometricInterpretation should be consistent with the
            # number of channels
            photometric_interpretation = ifd_entries[262][3]
            if photometric_interpretation == 2:
                assert num_channels in [3, 4], "RGB? num_channels=%s" % num_channels
            elif photometric_interpretation in [0, 1, 3]:
                assert num_channels == 1, "Grayscale? num_channels=%s" % num_channels
        else:
            raise RuntimeError(
                "Baseline TIF tags are not parsed correctly !"
                + "Parser expects (inter alia) an uncompressed image."
            )

        return width, height, num_channels, num_frames, bit_depth, is_linearlut


def get_metadata(filename, keys):
    """Extracts metadata from a *.tif recorded by the Tescan Clara microscope.

    The information is contained both in the *.tif file,
    as well a separate ASCII *.hdr file.
    However, it might not be possible to have both files available,
    so we only use the *.tif file.
    The relevant metadata is right at the end of the file,
    where each metadata parameter is in one line in the format key=value.

    Unfortunately, Tescan does not seem to use TIFF image tags for these,
    so we have to parse the file as binary (mode 'rb' - read only, binary).
    This implies that all comparisons have to be made using binary format,
    and the values we found have to be converted/decoded from binary.

    Assumption 1: Date and Time are already in ISO format.

    Assumption 2: Most numeric values are is in SI units.


    Args:
        filename (str): Filename of the *.tif file recorded by a Tescan Clara.
        keys (:obj:`list` of :obj:`str`, optional): metadata fields that should
            be extracted from the image. Defaults to keys_SEMDict.

    Returns:
        dict: dictionary of extracted metadata

    """

    # Mapping from Tescan metadata to OpenBIS properties
    field_map = {
        "Gun=": "GUN_TYPE",
        "GunShiftX": "GUNSHIFTX",
        "GunShiftY": "GUNSHIFTY",
        "HV": "ACCELERATING_VOLTAGE",
        "ScanRotation": "SCAN_ROTATION",
        "SpotSize": "SPOT_SIZE",
        "StigmatorX": "STIGMATORX",
        "StigmatorY": "STIGMATORY",
        "Detector0": "DETECTOR1_NAME",
        "Detector0Gain": "DETECTOR1_GAIN",
        "Detector0Offset": "DETECTOR1_OFFSET",
        "Detector1": "DETECTOR2_NAME",
        "Detector1Gain": "DETECTOR2_GAIN",
        "Detector1Offset": "DETECTOR2_OFFSET",
        "PredictedBeamCurrent": "BEAM_CURRENT_NA",
        "EmissionCurrent": "EMISSION_CURRENT_UA",
        "GunTiltX": "GUNTILTX",
        "GunTiltY": "GUNTILTY",
        "DwellTime": "DWELL_TIME",
        "PixelSizeX": "PIXEL_SIZE_X_NM",
        "PixelSizeY": "PIXEL_SIZE_Y_NM",
        "StageRotation": "STAGE_ROTATION",
        "StageTilt": "STAGE_TILT_A",
        "StageX": "STAGE_X_MM",
        "StageY": "STAGE_Y_MM",
        "StageZ": "STAGE_Z_MM",
        "WD": "WD",
        "SoftwareVersion": "SOFTWAREVERSION",
        "Device=": "DEVICE_NAME",
        "UserName": "USER_NAME",
        "Company": "INSTITUTION",
        "ChamberPressure": "CHAMBER_PRESSURE",
        "VirtualObserverDistance": "VIRTUALOBSERVERDISTANCE",
        "TubeVoltage": "EXTRACTION_VOLTAGE",
        "ScanSpeed": "SCAN_SPEED",
        "ScanMode": "SCAN_MODE",
        "PotentialMode": "POTENTIALMODE",
        "Magnification": "MAGNIFICATION_REAL",
        "MagnificationReference": "MAGNIFICATIONREFERENCE",
        "ImageStripSize": "DATABAR_SIZE",
        "Time": "TIME",
        "Date": "DATE",
    }

    metadata_dict = dict.fromkeys(keys)

    # Set precision
    getcontext().prec = 10

    # Static information not found in the TIF
    manufacturer_name = "TESCAN"
    metadata_dict["DEVICE_MANUFACTURER"] = manufacturer_name

    # ############################ Parse Tif File ############################

    lines = None
    with open(filename, "rb") as f:
        first_field = b"Company="
        raw = f.read()
        if first_field in raw:
            metadata_footer = first_field + raw.split(first_field)[-1]
            lines = metadata_footer.split(b"\n")[:-1]
        else:
            raise ValueError("Was the file created by a Tescan (Clara) microscope?")

    keys_clara = list(field_map.keys()) + ["DeviceModel"]
    for key_clara in keys_clara:
        for line in lines:
            if (line.startswith(key_clara.encode("ascii"))) and b"=" in line:
                value = line.split(b"=", 1)[1]
                try:
                    value = value.decode("utf-8")
                    key = field_map.get(key_clara, key_clara)
                    metadata_dict[key] = value.strip()
                except UnicodeDecodeError as e:
                    print("[WARN] Problem @ %s in %s" % (key_clara, filename))
                    print("%s is ignored!" % key_clara)
                break

    # ######################## Convert DateTime Values ########################

    # Convert Time/Date into Datetime
    date_str = metadata_dict.get("DATE")  # Assumption 1
    time_str = metadata_dict.get("TIME")  # Assumption 1
    if date_str and time_str:
        datetime_str = date_str + " " + time_str
        try:
            datetime_obj = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
            datetime_obj = datetime_obj.isoformat(" ")
            metadata_dict["DATETIME"] = datetime_obj
        except ValueError:
            raise ValueError("Wrong date/time format!")

    # ############################# Infer Values #############################

    # Get height, width, number of channels, number of frames, bit depth
    # and linear LUT flag from TIF tags
    baseline_tags = get_tif_baseline_tags(filename)
    width, height = baseline_tags[0:2]
    metadata_dict["DATA_SIZE_X"] = width
    metadata_dict["DATA_SIZE_Y"] = height
    metadata_dict["NUMBER_OF_CHANNELS"] = baseline_tags[2]
    metadata_dict["NUMBER_OF_FRAMES"] = baseline_tags[3]
    metadata_dict["BIT_DEPTH"] = baseline_tags[4]
    metadata_dict["LINEAR_LUT"] = baseline_tags[5]

    # Compute Horizontal Field of View / Image Width
    psx = metadata_dict.get("PIXEL_SIZE_X_NM")  # in m, Assumption 2
    if psx:
        image_width = Decimal(width) * Decimal(psx)
        image_width_um = image_width * Decimal(1e6)
        metadata_dict["HFW"] = image_width_um

    # Compute Vertical Field of View / Image Height (without data bar)
    psy = metadata_dict.get("PIXEL_SIZE_Y_NM")  # in m, Assumption 2
    bar_size = metadata_dict.get("DATABAR_SIZE")
    if psy and bar_size:
        image_height = (Decimal(height) - Decimal(bar_size)) * Decimal(psy)
        image_height_um = image_height * Decimal(1e6)
        metadata_dict["VFW"] = image_height_um
        metadata_dict["DATABAR_START"] = height - int(bar_size)
        metadata_dict["DATABAR_END"] = height - 1
        metadata_dict["DATABAR_SIZE"] = int(bar_size)  # Cast to integer
    metadata_dict["HAS_DATABAR"] = bar_size is not None

    # ####################### Convert Numerical Values #######################

    # Convert decimal values (Assumption 2)
    fields_with_units = [
        ("SPOT_SIZE", "nm", "1m"),
        ("PIXEL_SIZE_X_NM", "nm", "1m"),
        ("PIXEL_SIZE_Y_NM", "nm", "1m"),
        ("WD", "mm", "1m"),
        ("VIRTUALOBSERVERDISTANCE", "mm", "1m"),
        ("DEPTHOFFOCUS", "mm", "1m"),
        ("STAGE_X_MM", "mm", "1m"),
        ("STAGE_Y_MM", "mm", "1m"),
        ("STAGE_Z_MM", "mm", "1m"),
        ("DWELL_TIME", "us", "1s"),
        ("ACCELERATING_VOLTAGE", "kV", "1V"),
        ("BEAM_CURRENT_NA", "nA", "1A"),
        ("EMISSION_CURRENT_UA", "uA", "1A"),
    ]
    for name, new_unit, old_unit in fields_with_units:
        val_str = metadata_dict.get(name)
        if val_str:
            metadata_dict[name] = convert_value(val_str, old_unit, new_unit)

    # Cast ScanSpeedSetting to integer
    scan_speed = metadata_dict.get("SCAN_SPEED")
    if scan_speed:
        metadata_dict["SCAN_SPEED"] = int(float(scan_speed))

    # ############################### Clean up ###############################

    # Remove manufacturer name from device name and add model details
    device_name = metadata_dict.get("DEVICE_NAME")
    device_model = metadata_dict.get("DeviceModel")
    if device_name and device_model:
        device_name = device_name.replace(manufacturer_name, "").lstrip()
        metadata_dict["DEVICE_NAME"] = device_name + " " + device_model
        del metadata_dict["DeviceModel"]

    # Control for Institution Name
    institution_name = metadata_dict.get("INSTITUTION")
    found_name = False
    if institution_name:
        for institution_short_name in ["IMM", "MCh", "MPIE", "FZJ", "GfE", "KKS"]:
            if institution_short_name.lower() in institution_name.lower():
                metadata_dict["INSTITUTION"] = institution_short_name
                found_name = True
    if not found_name:
        metadata_dict["INSTITUTION"] = None

    # ############################## Sanity Check #############################

    # Check if the keys match the schema
    set_a = set(metadata_dict.keys())
    set_b = set(keys)
    problematic_keys = set_a.symmetric_difference(set_b)

    assert set_a == set_b, "Problematic keys: %s" % problematic_keys

    return metadata_dict
