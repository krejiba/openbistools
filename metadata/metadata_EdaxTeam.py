import struct
from datetime import date, time, datetime

"""
    functions to extract the (meta-)data from the SPC, SPD, and IPR files for EDS Spectra analysed with Edax TEAM
    SPD files contain the map data,
    SPC files contain the spectral information,
    IPR files contain spatial calibration data.

    Header information was taken from Hyperspy (hyperspy/hyperspy/io_plugins/edax.py), which in turn
    was taken from http://www.biochem.mpg.de/doc_tom/TOM_Release_2008/IOfun/tom_mrcread.html abd
    http://ami.scripps.edu/software/mrctools/mrc_specification.php
    (although neither of these pages exist anymore)
"""


###
### SPD data
###
def get_metadata_spd(file: str) -> dict:
    """Extracts metadata from SPD files (from Edax TEAM sofware for EDS spectra)


    Args:
        file (str): Name of the file to be parsed

    Returns:
        dict: data and metadata extracted from the file
    """

    struct_fmt = "<16sllllllll120s"
    struct_len = struct.calcsize(struct_fmt)

    struct_unpack = struct.Struct(struct_fmt).unpack_from

    with open(file, "rb") as f:
        raw_spd_data = f.read(struct_len)
        raw_spd_metadata = struct_unpack(raw_spd_data)

    spd_header = {
        "tag": raw_spd_metadata[0].decode("ascii").rstrip("\x00"),
        "version": raw_spd_metadata[1],
        "num_spectra": raw_spd_metadata[2],
        "num_pixels_x": raw_spd_metadata[3],
        "num_pixels_y": raw_spd_metadata[4],
        "num_channels": raw_spd_metadata[5],
        "count_bytes_channel": raw_spd_metadata[6],
        "data_offset": raw_spd_metadata[7],
        "num_frames": raw_spd_metadata[8],
        "file_name": raw_spd_metadata[9].decode("ascii").rstrip("\x00"),
    }

    return spd_header


### #################################################################################################################################
### SPC data
### #################################################################################################################################
def get_metadata_spc(file: str) -> dict:
    """Extracts metadata from SPC files (from Edax TEAM sofware for EDS spectra)


    Args:
        file (str): Name of the file to be parsed

    Returns:
        dict: data and metadata extracted from the file
    """
    struct_fmt = "<ff8shbbbbbbllhhhh 24s 256p8phhh5l5BBlll 12s lhhfllhhfhhHHHHHHHHHH 6s HLfffffffLffffffffffffffffff 24s HfLffHf 38s h48H48H48f48L48h 30s h48h48h48h192c 1s 80c 111s 48h48h 12s hfhLff64hLffh32c 16s h320c10h10ll64fh5fhh24h24f 598s 4096l256c256cf"
    struct_len = struct.calcsize(struct_fmt)

    struct_unpack = struct.Struct(struct_fmt).unpack_from

    with open(file, "rb") as f:
        raw_spc_data = f.read(struct_len)
        raw_spc_metadata = struct_unpack(raw_spc_data)

    spc_header = {
        "file_format_version": round(float(raw_spc_metadata[0]), 1),
        "application_version": round(float(raw_spc_metadata[1]), 1),
        "filename_old": raw_spc_metadata[2],
        "collect_year": raw_spc_metadata[3],
        "collect_day": raw_spc_metadata[4],
        "collect_month": raw_spc_metadata[5],
        "collect_minute": raw_spc_metadata[6],
        "collect_hour": raw_spc_metadata[7],
        "collect_hundredthsec": raw_spc_metadata[8],
        "collect_second": raw_spc_metadata[9],
        "filesize": raw_spc_metadata[10],
        "data_offset": raw_spc_metadata[11],
        "num_spectrum_points": raw_spc_metadata[12],
        "intersecting_distance": raw_spc_metadata[13],
        "working_distance": raw_spc_metadata[14],
        "scale_setting_distance": raw_spc_metadata[15],
        ###
        "filler_1": raw_spc_metadata[16],
        ###
        "spectrum_type_label": raw_spc_metadata[17],
        "image_filename": raw_spc_metadata[18],
        "spot_x": raw_spc_metadata[19],
        "spot_y": raw_spc_metadata[20],
        "image_adc": raw_spc_metadata[21],
        "analyzer_discriminator_values": raw_spc_metadata[22:27],
        "discriminator_enabled_flag": raw_spc_metadata[27:32],
        "pileup_processed_flag": raw_spc_metadata[32],
        "firmware_version": raw_spc_metadata[33],
        "pileup_processing_version": raw_spc_metadata[34],
        # 0=None, 10=Eucentric Crossx,11= Eucentric Surface 12= Side Entry - Side 13 = Side Entry - Top*
        "hitachi_nb5000_dual_stage_config": raw_spc_metadata[35],
        ###
        "filler_2": raw_spc_metadata[36],
        ###
        "events_per_channel": raw_spc_metadata[37],
        "adc_time_constant": raw_spc_metadata[38],
        # *Preset mode 1=clock, 2=count, 3=none, 4=live, 5=resume
        "analysis_type": raw_spc_metadata[39],
        "preset": raw_spc_metadata[40],
        "max_counts": raw_spc_metadata[41],
        "max_peak_channel_number": raw_spc_metadata[42],
        "x_ray_tube_z": raw_spc_metadata[43],
        "filter_z": raw_spc_metadata[44],
        "current": raw_spc_metadata[45],
        # *XRF Air= 0, Vacuum= 1, Helium= 2*
        "sample_condition": raw_spc_metadata[46],
        # *Bulk or thin*
        "sample_type": raw_spc_metadata[47],
        # *0=None, 1=Installed*
        "xray_collimator_installed": raw_spc_metadata[48],
        # *0=Mono, 1=Poly*
        "xray_capilary_type": raw_spc_metadata[49],
        # *Range : 20 – 5000 Microns*
        "xray_capilary_size": raw_spc_metadata[50],
        # *Range : 0 – 10000 Microns*
        "xray_filter_thickness": raw_spc_metadata[51],
        # *1= Spectrum Smoothed, Else 0*
        "spectrum_smoothing_flag": raw_spc_metadata[52],
        # *Eagle Detector 0=30mm, 1=80mm*
        "detector_size_sili": raw_spc_metadata[53],
        # *1= Peaks Recalibrated, Else 0*
        "spectrum_peak_calibration": raw_spc_metadata[54],
        # *0=None, 2=Eagle2, 3=Eagle3, 4-Xscope*
        "eagle_system": raw_spc_metadata[55],
        # sumPeakRemoved: 2 byte unsigned short; *1= Sum Peaks Removed, Else 0*
        "sum_peak_removed_flag": raw_spc_metadata[56],
        # *1= Team Spectrum, Else 0*
        "edax_software_type": raw_spc_metadata[57],
        ###
        "filler_3": raw_spc_metadata[58],
        ###
        "escape_peak_removal_flag": raw_spc_metadata[59],
        # *Hardware type 1=EDI1, 2=EDI2, 3=DPP2, 31=DPP-FR, 32=DPP-FR2, 4=DPP3, 5= APOLLO XLT/XLS/DPP-4 (EDPP)*
        "analyzer_type": raw_spc_metadata[60],
        "start_energy": raw_spc_metadata[61],
        "end_energy": raw_spc_metadata[62],
        "live_time": raw_spc_metadata[63],
        "tilt_angle": raw_spc_metadata[64],
        "takeoff_angle": raw_spc_metadata[65],
        "beam_current_factor": raw_spc_metadata[66],
        "detector_resolution": raw_spc_metadata[67],
        # *Detector Type: 1=Std-BE, 2=UTW, 3=Super UTW, 4=ECON 3/4 Open, 5=ECON 3/4 Closed, 6=ECON 5/6 Open,
        #                7=ECON 5/6 Closed, 8=TEMECON; Add + 10 For Sapphire SiLi Detectors, (11-18), which started shipping in 1996.
        #                30 = APOLLO 10 SDD, 31=APOLLO XV, 32 = APOLLO 10+, 40 = APOLLO 40 SDD ,50 = APOLLO-X, 51=APOLLO-XP, 52 = APOLLO-XL,
        #                53 = APOLLO XL-XRF, 60 =APOLLO-XLT-LS, 61 =APOLLO-XLT-NW, 62 =APOLLO-XLT-SUTW*
        "detector_type": raw_spc_metadata[68],
        "parlodion_light_shield_thickness": raw_spc_metadata[69],
        "aluminium_light_shield_thickness": raw_spc_metadata[70],
        "be_window_thickness": raw_spc_metadata[71],
        "gold_light_shield_thickness": raw_spc_metadata[72],
        "silicon_dead_layer_thickness": raw_spc_metadata[73],
        "silicon_live_layer_thickness": raw_spc_metadata[74],
        "xray_incidence_angle": raw_spc_metadata[75],
        "detector_azimuth_angle": raw_spc_metadata[76],
        "detector_elevation_angle": raw_spc_metadata[77],
        "k_line_b_coefficient": raw_spc_metadata[78],
        "k_line_c_coefficient": raw_spc_metadata[79],
        "tail_maximum_channel": raw_spc_metadata[80],
        "tail_height_adjustment_percentage": raw_spc_metadata[81],
        "acceleration_voltage": raw_spc_metadata[82],
        "ap_window_thickness": raw_spc_metadata[83],
        "x_tilt_angle_mdx": raw_spc_metadata[84],
        "y_tilt_angle_mdx": raw_spc_metadata[85],
        # *0 = N/A, 1 = YAG OUT, 2 = YAG IN*
        "yag_status": raw_spc_metadata[86],
        ###
        "filler_4": raw_spc_metadata[87],
        ###
        # *TEM or SEM data*
        "raw_data_type": raw_spc_metadata[88],
        "accumulated_background_counts": raw_spc_metadata[89],
        "accumulated_spectrum_counts": raw_spc_metadata[90],
        "average_spectral_counts": raw_spc_metadata[91],
        "std_deviation_spectral_counts": raw_spc_metadata[92],
        # *Peak to background setting. 0 = off, 1 = low, 2 = medium, 3 = high, 4 = user selected*
        "peak_to_background_setting": raw_spc_metadata[93],
        "peak_to_background_value": raw_spc_metadata[94],
        ###
        "filler_5": raw_spc_metadata[95],
        ###
        "number_peak_id_elements": raw_spc_metadata[96],
        "atomic_numbers_peak_id_elements": raw_spc_metadata[97:145],
        "line_numbers_peak_id_elements": raw_spc_metadata[145:193],
        "float_energy_identified_peaks": raw_spc_metadata[193:241],
        "height_counts_identified_peaks": raw_spc_metadata[241:289],
        "sorted_peak_height_identified_peaks": raw_spc_metadata[289:337],
        # ###
        "filler_5_1": raw_spc_metadata[337],
        ###
        "num_roi": raw_spc_metadata[338],
        "start_channel_roi": raw_spc_metadata[339:387],
        "end_channel_roi": raw_spc_metadata[387:435],
        "roi_enable_flags": raw_spc_metadata[435:483],
        "roi_names": b"".join(raw_spc_metadata[483:675]).decode("ascii").rstrip("\x00"),
        ###
        "filler_5_2": raw_spc_metadata[675],
        ###
        "user_id": b"".join(raw_spc_metadata[676:756]).decode("ascii").rstrip("\x00"),
        ###
        "filler_5_3": raw_spc_metadata[756],
        ###
        "sorted_roi_heights": raw_spc_metadata[757:805],
        "sca_number_per_roi": raw_spc_metadata[805:853],
        ###
        "filler_6": raw_spc_metadata[853],
        ###
        "background_width": raw_spc_metadata[854],
        "percentage_move_background_down_manual": raw_spc_metadata[855],
        "num_background_points": raw_spc_metadata[856],
        "background_method": raw_spc_metadata[857],
        "background_starting_energy": raw_spc_metadata[858],
        "background_ending_energy": raw_spc_metadata[859],
        "channel_number_background_point": raw_spc_metadata[860:924],
        # 1 = curve, 2 = linear.*
        "background_type": raw_spc_metadata[924],
        "first_concentration_bg_point": raw_spc_metadata[925],
        "second_concentration_bg_point": raw_spc_metadata[926],
        # *0 = Off, 1 = On*
        "concentration_method": raw_spc_metadata[927],
        "vision_job_filename": b"".join(raw_spc_metadata[928:960])
        .decode("ascii")
        .rstrip("\x00"),
        ###
        "filler_7": raw_spc_metadata[960],
        ###
        "number_displayed_labels": raw_spc_metadata[961],
        "labels": b"".join(raw_spc_metadata[962:1282])
        .decode("windows-1252")
        .replace("\x00", ""),
        "label_x_pos_as_counts": raw_spc_metadata[1282:1292],
        "label_y_pos_as_counts": raw_spc_metadata[1292:1302],
        "z_list_flag": raw_spc_metadata[1302],
        "percentage_move_background": raw_spc_metadata[1303:1367],
        "background_points_flag": raw_spc_metadata[1367],
        "background_points": raw_spc_metadata[1368:1373],
        "concentration_flag": raw_spc_metadata[1373],
        "number_elements": raw_spc_metadata[1374],
        "z_list_elements": raw_spc_metadata[1375:1399],
        "z_list_concentration": raw_spc_metadata[1399:1423],
        # ###
        "filler_8": raw_spc_metadata[1423],
        ###
        "counts_per_channel": raw_spc_metadata[1424:5520],
        "filename_32bit": b"".join(raw_spc_metadata[5520:5776])
        .decode("ascii")
        .rstrip("\x00"),
        "image_filename_32bit": b"".join(raw_spc_metadata[5776:6032])
        .decode("ascii")
        .rstrip("\x00"),
        "adc_time_constant_new": raw_spc_metadata[6032],
    }

    # convert preset modes / analysis type to human-readable text
    analysis_type_dict = {1: "clock", 2: "count", 3: "none", 4: "live", 5: "resume"}
    spc_header["analysis_type"] = analysis_type_dict[spc_header["analysis_type"]]

    yag_status_dict = {0: "n/a", 1: "yag out", 2: "yag in"}
    spc_header["yag_status"] = yag_status_dict[spc_header["yag_status"]]

    peak_to_background_dict = {0: "off", 1: "low", 2: "medium", 3: "high", 4: "user"}
    spc_header["peak_to_background_setting"] = peak_to_background_dict[
        spc_header["peak_to_background_setting"]
    ]

    sample_condition_dict = {0: "air", 1: "vacuum", 2: "helium"}
    spc_header["sample_condition"] = sample_condition_dict[
        spc_header["sample_condition"]
    ]

    sample_type_dict = {0: "bulk", 1: "thin"}
    spc_header["sample_type"] = sample_type_dict[spc_header["sample_type"]]

    # also other values but not yet known?
    # background_type_dict = {
    #     1 : 'curve',
    #     2 : 'linear'
    # }
    # spc_header['background_type'] = background_type_dict[spc_header['background_type']]

    # *0=None, 2=Eagle2, 3=Eagle3, 4-Xscope*
    eagle_system_dict = {0: "none", 1: "eagle2", 3: "eagle3", 4: "xscope"}
    spc_header["eagle_system"] = eagle_system_dict[spc_header["eagle_system"]]

    # combine date/time information into datetime object
    collection_date = date(
        year=spc_header["collect_year"],
        month=spc_header["collect_month"],
        day=spc_header["collect_day"],
    )
    collection_time = time(
        hour=spc_header["collect_hour"],
        minute=spc_header["collect_minute"],
        second=spc_header["collect_second"],
    )
    spc_header["collection_time"] = datetime.combine(collection_date, collection_time)

    return spc_header


### ###########################################################################################################################################
### IPR Data
### ###########################################################################################################################################


def get_metadata_ipr(file: str) -> dict:
    """Extracts metadata from IPR files (from Edax TEAM sofware for EDS spectra)


    Args:
        file (str): Name of the file to be parsed

    Returns:
        dict: data and metadata extracted from the file
    """

    struct_fmt = "HH8s HHHH HH HHhHH hh Hh HHHf Hhh hhh ff H128cfH16H"
    struct_len = struct.calcsize(struct_fmt)

    struct_unpack = struct.Struct(struct_fmt).unpack_from

    with open(file, "rb") as f:
        raw_ipr_data = f.read(struct_len)
        raw_ipr_metadata = struct_unpack(raw_ipr_data)

    ipr_header = {
        "version": raw_ipr_metadata[0],
        # *0=empty; 1=electron; 2=xmap; 3=disk; 4=overlay*
        "image_type": raw_ipr_metadata[1],
        "image_label": raw_ipr_metadata[2].decode("ascii").rstrip("\x00"),
        "min_collected_signal": raw_ipr_metadata[3],
        "max_collected_signal": raw_ipr_metadata[4],
        # #*color: 0=gray; 1=R; 2=G; 3=B; 4=Y; 5=M; 6=C; 8=overlay*
        "colour": raw_ipr_metadata[5],
        # #*0=clock; 1=live*
        "preset_mode": raw_ipr_metadata[6],
        # we get the correct value by reading the 4 bytes as 2 2-bytes unsigned short (instead of a 4 byte unsigned long) and hop over the next 2 bytes. not sure why.
        "xray_dwelltime_ms": raw_ipr_metadata[7],
        # #*0=ROI;  1=Net intensity; 2=K ratio; 3=Wt%;  4=Mthin2*
        "data_type": raw_ipr_metadata[9],
        "amplifier_pulse_processing_time_usec_old": raw_ipr_metadata[10],
        "unused_1": raw_ipr_metadata[11],
        "roi_starting_channel": raw_ipr_metadata[12],
        "roi_ending_channel": raw_ipr_metadata[13],
        "user_defined_min_signal_range": raw_ipr_metadata[14],
        "user_defined_max_signal_range": raw_ipr_metadata[15],
        "electron_detector_number": raw_ipr_metadata[16],
        "unused_2": raw_ipr_metadata[17],
        "conversion_type": raw_ipr_metadata[18],
        "num_reads_per_point": raw_ipr_metadata[19],
        "num_frames": raw_ipr_metadata[20],
        "dwell_time": raw_ipr_metadata[21],
        "acc_voltage_per_100V": raw_ipr_metadata[22],
        "sample_tilt_deg": raw_ipr_metadata[23],
        "takeoff_angle_deg": raw_ipr_metadata[24],
        # 2 byte unsigned short seems to give the correct value, then hop over the next. not sure why
        "magnification": raw_ipr_metadata[25],
        "working_distance_mm": raw_ipr_metadata[27],
        "microns_per_pixel_x": raw_ipr_metadata[28],
        "microns_per_pixel_y": raw_ipr_metadata[29],
        "num_comment_lines": raw_ipr_metadata[30],
        "comments": b"".join(raw_ipr_metadata[31:159]).decode("ascii").rstrip("\x00"),
        "unused3": raw_ipr_metadata[159],
        "num_overlay_elements": raw_ipr_metadata[160],
        "overlay_colours": raw_ipr_metadata[161:177],
    }

    return ipr_header
