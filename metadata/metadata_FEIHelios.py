from datetime import datetime
import struct
from decimal import Decimal, getcontext
from configparser import RawConfigParser
import sys

MAJOR_VERSION = sys.version_info.major
if MAJOR_VERSION == 2:
    # We have to use Python 2.7 for the Jython dropbox in openBIS
    from cStringIO import StringIO
elif MAJOR_VERSION == 3:
    from io import StringIO


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


def flatten_dict(dictionary, acc=None, parent_key=None, sep="."):
    """Recursively flattens a nested dictionary into a single-level dictionary.

    Args:
        dictionary (dict): The input dictionary to be flattened.
        acc (dict, optional): The accumulator dictionary.
            Used for storing flattened key-value pairs. Defaults to None.
        parent_key (str, optional): The parent key (used for recursion).
            Defaults to None.
        sep (str, optional): Separator character for joining keys.
            Defaults to '.'.

    Returns:
        dict: A flattened dictionary.
    """
    if not isinstance(dictionary, dict):
        return dictionary
    if acc is None:
        acc = {}
    for k, v in dictionary.items():
        k = parent_key + sep + k if parent_key else k
        if isinstance(v, dict):
            flatten_dict(dictionary=v, acc=acc, parent_key=k)
            continue
        acc[k] = v
    return acc


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
            assert n_channels == num_channels, "Inconsistent NumberOfChannels"
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
    """Extracts metadata from a *.tif recorded by the FEI Helios microscope.

    The FEI Helios (at least in the present version) includes the metadata in
    the TIF file akin to the .ini format recognised by the python configparser,
    i.e.
       [Field1]

       property1 = value1

       property2 = value2

       [Field2]

       property1 = value1

    etc.

    The metadata is at the end of the file and starts with the tag '[User]'.
    In a first step, we split the TIF file at this tag (and prepend it again)
    so that we are left with the configuration-like metadata.

    The metadata can also be indentified using TIFF TAG 34682

    Assumption 1: Date is formatted as "%m/%d/%Y".

    Assumption 2: Time is formatted as %I:%M:%S %p.

    Assumption 3: Most numeric values are is in SI units.

    Args:
        filename (str): Filename of the *.tif file recorded by a FEI Helios.

    Returns:
        dict: dictionary of extracted metadata

    """

    # Mapping from FEI metadata to OpenBIS properties
    field_map = {
        "Beam.BeamShiftX": "GUNSHIFTX",
        "Beam.BeamShiftY": "GUNSHIFTY",
        "Beam.HV": "ACCELERATING_VOLTAGE",
        "Beam.ScanRotation": "SCAN_ROTATION",
        "Beam.Spot": "SPOT_SIZE_SETTING",
        "Beam.StigmatorX": "STIGMATORX",
        "Beam.StigmatorY": "STIGMATORY",
        "Detectors.Mode": "DETECTOR1_TYPE",
        "Detectors.Name": "DETECTOR1_NAME",
        "EBeam.ApertureDiameter": "APERTURE_SIZE",
        "EBeam.BeamCurrent": "BEAM_CURRENT_NA",
        "EBeam.EmissionCurrent": "EMISSION_CURRENT_UA",  # usually empty
        "EBeam.LensMode": "LENS_MODE",
        "EBeam.SourceTiltX": "GUNTILTX",
        "EBeam.SourceTiltY": "GUNTILTY",
        "EScan.FrameTime": "FRAME_TIME",
        "EScan.LineTime": "LINE_TIME",
        "Scan.Dwelltime": "DWELL_TIME",
        "Scan.PixelHeight": "PIXEL_SIZE_X_NM",
        "Scan.PixelWidth": "PIXEL_SIZE_Y_NM",
        "Stage.StageR": "STAGE_ROTATION",
        "Stage.StageT": "STAGE_TILT_A",
        "Stage.StageTb": "STAGE_TILT_B",
        "Stage.StageX": "STAGE_X_MM",
        "Stage.StageY": "STAGE_Y_MM",
        "Stage.StageZ": "STAGE_Z_MM",
        "Stage.WorkingDistance": "WD",
        "System.Software": "SOFTWAREVERSION",
        "System.Source": "GUN_TYPE",
        "System.SystemType": "DEVICE_NAME",
        "User.User": "USER_NAME",
        "User.UserText": "INSTITUTION",
        "Vacuum.ChPressure": "CHAMBER_PRESSURE",
    }

    metadata_dict = dict.fromkeys(keys)

    # Set precision
    getcontext().prec = 10

    # Static information not found in the TIF
    manufacturer_name = "FEI"
    metadata_dict["DEVICE_MANUFACTURER"] = manufacturer_name

    # ############################ Parse Tif File ############################

    metadata_ini = None
    try:
        with open(filename, "rb") as f:
            raw_metadata = f.read().split(b"[User]")[1].decode("utf-8")
        metadata_ini = "[User]\r\n" + raw_metadata
        metadata_ini = metadata_ini.rstrip("\x00")  # Remove \x00 end-of-string
    except IndexError:
        raise ValueError("Was the file created by an FEI (Helios) microscope?")

    config = RawConfigParser(strict=False)
    config.optionxform = str
    # Convert string and pretend it is a file
    buffer = StringIO(metadata_ini)
    if MAJOR_VERSION == 2:
        config.readfp(buffer)
    elif MAJOR_VERSION == 3:
        config.read_file(buffer)

    # Convert ConfigParser's nested dictionary structure into a flat dictionary
    dictionary = {s: dict(config.items(s)) for s in config.sections()}
    metadata = flatten_dict(dictionary)

    # Copy Brightness and Contrast
    detector_name = metadata.get("Detectors.Name")
    brightness_key = "%s.Brightness" % detector_name
    contrast_key = "%s.Contrast" % detector_name
    metadata_dict["BRIGHTNESS"] = metadata.get(brightness_key)
    metadata_dict["CONTRAST"] = metadata.get(contrast_key)
    metadata_dict["IS_STEM"] = "STEM" in detector_name.upper()

    # Copy remaining
    for old_key in field_map:
        metadata_dict[field_map[old_key]] = metadata.get(old_key)

    # ######################## Convert DateTime Values ########################

    # Convert Time/Date into Datetime
    date_str = metadata.get("User.Date")  # Assumption 1
    time_str = metadata.get("User.Time")  # Assumption 2
    if date_str and time_str:
        try:
            date_str = datetime.strptime(date_str, "%m/%d/%Y").date()
            time_str = datetime.strptime(time_str, "%I:%M:%S %p").time()
            date_str = date_str.isoformat()
            time_str = time_str.isoformat()
            datetime_str = date_str + " " + time_str
            datetime_obj = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
            datetime_obj = datetime_obj.isoformat(" ")
            metadata_dict["DATETIME"] = datetime_str
            metadata_dict["DATE"] = date_str
            metadata_dict["TIME"] = time_str
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

    # Height and width should match
    w = metadata.get("Image.ResolutionX")
    h = metadata.get("Image.ResolutionY")  # Image Array Height excluding bar
    if h and w:
        assert width == int(w), (height, h, width, w)
        # Data Bar is vertically-appended to Image Array, not pasted on top
        metadata_dict["HAS_DATABAR"] = height != int(h)
        metadata_dict["DATABAR_SIZE"] = height - int(h)
        if metadata_dict["HAS_DATABAR"]:
            metadata_dict["DATABAR_START"] = int(h)
            metadata_dict["DATABAR_END"] = height - 1
    # Compute Horizontal Field of View / Image Width
    for key in ["EBeam.HFW", "EScan.HorFieldsize", "Scan.HorFieldsize"]:
        hfw = metadata.get(key)  # in m, Assumption 3
        if hfw:
            image_width_um = Decimal(hfw) / Decimal(1e-6)
            metadata_dict["HFW"] = image_width_um
            break
    psx = metadata.get("Scan.PixelWidth")  # in m, Assumption 3
    if hfw is None and psx:
        image_width_um = Decimal(width) * Decimal(psx) / Decimal(1e-6)
        metadata_dict["HFW"] = image_width_um

    # Compute Vertical Field of View / Image Height (without data bar)
    for key in ["EBeam.VFW", "EScan.VerFieldsize", "Scan.VerFieldsize"]:
        vfw = metadata.get(key)  # in m, Assumption 3
        if vfw:
            image_height_um = Decimal(vfw) / Decimal(1e-6)
            metadata_dict["VFW"] = image_height_um
            break
    psy = metadata.get("Scan.PixelHeight")  # in m, Assumption 3
    if vfw is None and h and psy:
        image_height_um = Decimal(h) * Decimal(psy) / Decimal(1e-6)
        metadata_dict["VFW"] = image_height_um

    # Compute Magnification
    real_width = metadata.get("Image.MagCanvasRealWidth")  # in m, Assumption 3
    if hfw and real_width:
        magnification = Decimal(real_width) / Decimal(hfw)
        metadata_dict["MAGNIFICATION_REAL"] = magnification

    # ####################### Convert Numerical Values #######################

    # Convert decimal values (Assumption 3)
    fields_with_units = [
        ("PIXEL_SIZE_X_NM", "nm", "1m"),
        ("PIXEL_SIZE_Y_NM", "nm", "1m"),
        ("APERTURE_SIZE", "um", "1m"),
        ("WD", "mm", "1m"),
        ("STAGE_X_MM", "mm", "1m"),
        ("STAGE_Y_MM", "mm", "1m"),
        ("STAGE_Z_MM", "mm", "1m"),
        ("DWELL_TIME", "us", "1s"),
        ("LINE_TIME", "ms", "1s"),
        ("ACCELERATING_VOLTAGE", "kV", "1V"),
        ("BEAM_CURRENT_NA", "nA", "1A"),
        ("EMISSION_CURRENT_UA", "uA", "1A"),
    ]
    for name, new_unit, old_unit in fields_with_units:
        val_str = metadata_dict.get(name)
        if val_str:
            metadata_dict[name] = convert_value(val_str, old_unit, new_unit)

    # Convert angles from radians to degrees
    rad2deg = Decimal(180) / Decimal("3.14159265359")
    for k in [
        "STAGE_TILT_A",
        "STAGE_TILT_B",
        "STAGE_ROTATION",
    ]:
        angle = metadata_dict.get(k)
        if angle:
            metadata_dict[k] = Decimal(angle) * rad2deg

    # Convert fractions to percentages
    for k in [
        "STIGMATORX",
        "STIGMATORY",
        "GUNTILTX",
        "GUNTILTY",
        "GUNSHIFTX",
        "GUNSHIFTY",
    ]:
        percentage = metadata_dict.get(k)
        if percentage:
            metadata_dict[k] = Decimal(percentage) * Decimal(100)

    # Cast Brightness and Contrast to decimal
    for k in ["BRIGHTNESS", "CONTRAST"]:
        v = metadata_dict.get(k)
        if v:
            if "_" in v:
                v, unit = v.split(" ")
            metadata_dict[k] = Decimal(v)

    # ############################### Clean up ###############################
    metadata_dict = {k: None if v == "" else v for k, v in metadata_dict.items()}

    # Remove manufacturer name from device name and add model
    # Remove " from device name
    device_name = metadata_dict.get("DEVICE_NAME")
    device_model = metadata.get("System.Type")
    if device_name and device_model:
        device_name = device_name.replace('"', "")
        device_name = device_name.replace(manufacturer_name, "").lstrip()
        metadata_dict["DEVICE_NAME"] = device_name + " " + device_model

    # # Remove - from spot size
    # spot_size_setting = metadata_dict.get('SPOT_SIZE_SETTING')
    # if spot_size_setting:
    #     spot_size_setting = spot_size_setting.replace('-', '')
    #     metadata_dict['SPOT_SIZE_SETTING'] = Decimal(spot_size_setting)

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

    # Add Build Number to Software Version
    software_version = metadata_dict.get("SOFTWAREVERSION")
    bn = metadata.get("System.BuildNr")
    if software_version and bn:
        software_version = software_version + ", build " + bn
        metadata_dict["SOFTWAREVERSION"] = software_version

    # ############################## Sanity Check #############################

    # Check if the keys match the schema
    set_a = set(metadata_dict.keys())
    set_b = set(keys)
    problematic_keys = set_a.symmetric_difference(set_b)
    assert set_a == set_b, "Problematic keys: %s" % problematic_keys

    return metadata_dict
