from datetime import datetime
import struct
from decimal import Decimal, getcontext
from math import floor


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


def get_tif_image_array(filename):
    """Extracts image  from a *.tif image.

    Args:
        filename (str): Filename of the *.tif file.

    Returns:
        :obj:`list` of :obj:`list`: image array as a list of lists of scalars

    """

    def divide_into_chunks(l, n):
        for i in range(0, len(l), n):
            yield l[i : i + n]

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

        desired_tags = set([256, 257, 258, 262, 277, 278, 273, 279])
        parsed_tags = set(ifd_entries.keys())

        if desired_tags.issubset(parsed_tags):
            width = ifd_entries[256][3]  # ImageWidth
            height = ifd_entries[257][3]  # ImageLength
            num_channels = ifd_entries[277][3]  # SamplesPerPixel
            n_channels = ifd_entries[258][2]  # Inferred number of channel
            if n_channels > 1:
                f.seek(ifd_entries[258][3])
                bit_depths = struct.unpack(
                    byte_order + "%sH" % n_channels, f.read(2 * n_channels)
                )
                bit_depth = bit_depths[0]
            else:
                bit_depth = ifd_entries[258][3]  # BitsPerSample
            # Sanity checks
            assert n_channels == num_channels, "Inconsistent NumberOfChannels"
            # PhotometricInterpretation should be consistent with the
            # number of channels
            photometric_interpretation = ifd_entries[262][3]
            if photometric_interpretation == 2:
                assert num_channels in [3, 4], "RGB? num_channels=%s" % num_channels
            elif photometric_interpretation in [0, 1, 3]:
                assert num_channels == 1, "Grayscale? num_channels=%s" % num_channels
            rows_per_strip = ifd_entries[278][3]  # RowsPerStrip

            strip_offsets = ifd_entries[273][3]  # StripOffsets
            strip_byte_counts = ifd_entries[279][3]  # StripByteCounts
            assert ifd_entries[273][2] == ifd_entries[279][2]
            num_strips = (height + rows_per_strip - 1) / rows_per_strip
            num_strips = floor(num_strips)  # StripsPerImage

            if bit_depth != 8:
                raise RuntimeError(
                    "Reading image array is only supported for 8-bit images"
                )

            if rows_per_strip == 2**32 - 1:
                offset = strip_offsets
                byte_count = strip_byte_counts
                f.seek(offset)
                row_contiguous = struct.unpack(
                    byte_order + "%sB" % byte_count, f.read(byte_count)
                )
                strip = list(divide_into_chunks(row_contiguous, n_channels))
                image_array = list(divide_into_chunks(strip, width))
            else:
                f.seek(strip_offsets)
                offsets = struct.unpack(
                    byte_order + "%sI" % num_strips, f.read(4 * num_strips)
                )
                f.seek(strip_byte_counts)
                bytes_counts = struct.unpack(
                    byte_order + "%sI" % num_strips, f.read(4 * num_strips)
                )
                image_array = []
                for offset, byte_count in zip(offsets, bytes_counts):
                    f.seek(offset)
                    row_contiguous = struct.unpack(
                        byte_order + "%sB" % byte_count, f.read(byte_count)
                    )
                    row = list(divide_into_chunks(row_contiguous, n_channels))
                    image_array.append(list(row))

        else:
            raise RuntimeError(
                "Baseline TIF tags are not parsed correctly !"
                + "Parser expects (inter alia) an uncompressed image."
            )
        return image_array


# # This version is not compatible with the Jython Dropbox in OpenBIS
# def get_tif_image_array(filename):
#     from PIL import Image
#     import numpy as np
#     img = np.array(Image.open(filename)).tolist()
#     return img


def get_metadata(filename, keys):
    """Extracts metadata from a *.tif recorded by the Zeiss Merlin microscope.

    The metadata are at the beginning of the file, one key-value pair per line.
    We open the file in binary mode and extract all relevant keys.
    This implies that all comparisons have to be made using binary format,
    and the values we found have to be converted/decoded from binary.

    Assumption 1: Time is already in ISO format.

    Assumption 2: Date is formatted as "%d %b %Y".

    Assumption 3: Square pixels.

    Args:
        filename (str): Filename of the *.tif file recorded by a Zeiss Merlin.

    Returns:
        dict: dictionary of extracted metadata

    """

    # Mapping from Zeiss metadata to OpenBIS properties
    field_map = {
        "Aperture Size": "APERTURE_SIZE",
        "Beam Current": "BEAM_CURRENT_NA",  # Might be incorrect
        "Beam Shift X": "BEAM_SHIFT_X",
        "Beam Shift Y": "BEAM_SHIFT_Y",
        "Brightness": "BRIGHTNESS",
        "Chamber": "CHAMBER_PRESSURE",
        "Contrast": "CONTRAST",
        "Cycle Time": "FRAME_TIME",
        "Date": "DATE",
        "Detector": "DETECTOR1_NAME",
        "Dwell Time": "DWELL_TIME",
        "EHT": "ACCELERATING_VOLTAGE",
        # "Focus": "DEPTHOFFOCUS",
        "Gun Shift X": "GUNSHIFTX",
        "Gun Shift Y": "GUNSHIFTY",
        "Gun Tilt X": "GUNTILTX",
        "Gun Tilt Y": "GUNTILTY",
        "Gun Vacuum": "GUN_VACUUM",
        "Height": "VFW",  # Includes databar height
        "Image Pixel Size": "PIXEL_SIZE_X_NM",
        "Line Time": "LINE_TIME",
        "Liner Tube": "EXTRACTION_VOLTAGE",
        "Mag": "MAGNIFICATION_REAL",
        "Reference Mag": "MAGNIFICATIONREFERENCE",
        "Scan Speed": "SCAN_SPEED",  # 1 - 15
        "Scan Rotation": "SCAN_ROTATION",
        "ScanGen Type": "SCAN_MODE",
        # "Sem": "DEVICE_NAME",
        "Spot Size": "SPOT_SIZE_SETTING",
        "Stage at R": "STAGE_ROTATION",
        "Stage at T": "STAGE_TILT_A",  # Always zero, Manually adjusted
        "Stage at X": "STAGE_X_MM",
        "Stage at Y": "STAGE_Y_MM",
        "Stage at Z": "STAGE_Z_MM",
        "Stigmation X": "STIGMATORX",
        "Stigmation Y": "STIGMATORY",
        "System Vacuum": "SYSTEM_VACUUM",
        "Time": "TIME",
        "Version": "SOFTWAREVERSION",
        "WD": "WD",
        "Width": "HFW",
    }

    metadata_dict = dict.fromkeys(keys)

    # Set precision
    getcontext().prec = 10

    # Static information not found in the TIF - Change if using another device
    metadata_dict["DEVICE_MANUFACTURER"] = "ZEISS"
    metadata_dict["DEVICE_NAME"] = "Merlin"
    metadata_dict["INSTITUTION"] = "MPIE"

    # ############################ Parse Tif File ############################

    metadata_tif = dict.fromkeys(field_map.keys())
    with open(filename, "rb") as f:
        metadata_lines = list(f.readlines())

    lines = []
    for line in metadata_lines:
        # Problematic unicode signs to remove if using ASCII
        line = line.replace(b"\xb0", b"deg")  # \xb0 (degree)
        line = line.replace(b"\xb5", b"u")  # \xb5 (mu)
        lines.append(line)

    found_zeiss_sem_marker = False
    for line in lines:
        if "DP_VENT_INVALID_REASON".encode("ascii") in line:
            found_zeiss_sem_marker = True
    if not found_zeiss_sem_marker:
        raise ValueError("Was the file created by a Zeiss (Merlin) microscope?")

    for line in lines:
        for key in field_map.keys():
            # Date and Time are separated by ":", all others by "="
            delim = b":" if key == "Date" or key == "Time" else b"="
            line_start = key.encode("ascii") + b" " + delim
            if line.startswith(line_start):
                value = line.split(delim, 1)[1]
                value = value.decode("ascii").strip()
                metadata_tif[key] = value

    # Copy
    for old_key in field_map:
        metadata_dict[field_map[old_key]] = metadata_tif.get(old_key)

    # ######################## Convert DateTime Values ########################

    # Convert Time/Date into Datetime
    date_str = metadata_tif.get("Date")  # Assumption 1
    time_str = metadata_tif.get("Time")  # Assumption 2
    if date_str and time_str:
        try:
            date_str = datetime.strptime(date_str, "%d %b %Y").date()
            time_str = datetime.strptime(time_str, "%H:%M:%S").time()
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

    # FIXME Locate Databar Merlin

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

    # Handle Pixel Size - Assumption 3
    metadata_dict["PIXEL_SIZE_Y_NM"] = metadata_dict.get("PIXEL_SIZE_X_NM")

    # Infer Detector Type from Detector Name
    detector_name = metadata_dict.get("DETECTOR1_NAME")
    if detector_name:
        for detector_type in ["SE", "BSE", "ESB", "BSD"]:
            if detector_name.startswith(detector_type):
                metadata_dict["DETECTOR1_TYPE"] = detector_type

    # Compute Horizontal Field of View / Image Width
    psx = metadata_dict.get("PIXEL_SIZE_X_NM")
    image_width_str = metadata_dict.get("HFW")
    if image_width_str is None and psx:
        psx = " ".join(psx.split())
        psx, unit = psx.split(" ")
        psx = convert_value(psx, unit, "um")
        image_width_um = Decimal(width) * psx
        metadata_dict["HFW"] = image_width_um

        # # Compute Vertical Field of View / Image Height
        # psy = metadata_dict.get("PIXEL_SIZE_Y_NM")
        # image_height_str = metadata_dict.get("VFW")
        # # image_height_str includes the databar size
        # if psy and metadata_dict["DATABAR_END"] == height - 1:
        #     height = height - metadata_dict["DATABAR_SIZE"]  # Exclude databar
        #     psy = " ".join(psy.split())
        #     psy, unit = psy.split(" ")
        #     psy = convert_value(psy, unit, "um")
        #     image_height_um = Decimal(height) * psy
        #     metadata_dict["VFW"] = image_height_um

        # ####################### Convert Numerical Values #######################

    pressure_conversion_to_pascal = {
        "Pa": Decimal(1),
        "mbar": Decimal(100),
        # "hPa": Decimal(100),
        # "kPa": Decimal(1000),
        # "bar": Decimal(100000),
        # "atm": Decimal("101325"),
        # "torr": Decimal("133.322"),
        # "psi": Decimal("6894.757"),
    }

    # Convert decimal values
    for k, v in metadata_dict.items():
        if v is not None and " " in str(v):
            v = " ".join(v.split())
            if k == "FRAME_TIME":
                frame_time, unit = v.split(" ")
                frame_time = Decimal(frame_time)
                # Convert from min to s
                if "min" in unit.lower():
                    frame_time = frame_time * Decimal(60)
                metadata_dict[k] = frame_time
                continue
            if k in ["CHAMBER_PRESSURE", "SYSTEM_VACUUM", "GUN_VACUUM"]:
                pressure, unit = v.split(" ")
                pressure = Decimal(pressure)
                # Convert from mbar to Pa
                factor = pressure_conversion_to_pascal.get(unit)
                if factor is None:
                    # Unsupported unit.
                    # We keep the original value and do not raise to avoid interrupting workflows.
                    pass
                else:
                    pressure *= factor
                metadata_dict[k] = pressure
                continue
            if k == "MAGNIFICATION_REAL":
                mag = v.split(" ")[0]
                mag = Decimal(mag)
                if "k" in v.lower():  # 80 kX = 80 000 X
                    mag = mag * Decimal(1000)
                metadata_dict[k] = mag
                continue
            if k in [
                "CONTRAST",
                "BRIGHTNESS",
                "GUNTILTX",
                "GUNTILTY",
                "GUNSHIFTX",
                "GUNSHIFTY",
                "STIGMATORX",
                "STIGMATORY",
                "BEAM_SHIFT_X",
                "BEAM_SHIFT_Y",
            ]:
                metadata_dict[k] = Decimal(v.split(" ")[0])
            if "deg" in v:
                angle, _ = v.split(" ")
                metadata_dict[k] = angle

    fields_with_units = [
        ("HFW", "um"),
        ("VFW", "um"),
        ("PIXEL_SIZE_X_NM", "nm"),
        ("PIXEL_SIZE_Y_NM", "nm"),
        ("APERTURE_SIZE", "um"),
        ("WD", "mm"),
        ("STAGE_X_MM", "mm"),
        ("STAGE_Y_MM", "mm"),
        ("STAGE_Z_MM", "mm"),
        ("DWELL_TIME", "us"),
        ("LINE_TIME", "ms"),
        ("ACCELERATING_VOLTAGE", "kV"),
        ("EXTRACTION_VOLTAGE", "1V"),
        ("BEAM_CURRENT_NA", "nA"),
    ]
    for name, new_unit in fields_with_units:
        val_str = metadata_dict.get(name)
        if val_str is not None and " " in str(val_str):
            val_str = " ".join(val_str.split())
            val_str, old_unit = val_str.split(" ")
            if len(unit) == 1:
                unit = "1" + unit
            metadata_dict[name] = convert_value(val_str, old_unit, new_unit)

    # Cast ScanSpeedSetting to integer
    scan_speed = metadata_dict.get("SCAN_SPEED")
    if scan_speed:
        metadata_dict["SCAN_SPEED"] = int(float(scan_speed))

    # ############################## Sanity Check #############################

    # Check if the keys match the schema
    set_a = set(metadata_dict.keys())
    set_b = set(keys)
    problematic_keys = set_a.symmetric_difference(set_b)
    assert set_a == set_b, "Problematic keys: %s" % problematic_keys

    return metadata_dict
