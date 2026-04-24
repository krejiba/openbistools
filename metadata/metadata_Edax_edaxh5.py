import h5py
from datetime import datetime


def parse_edaxh5(path, keys):
    metadata = dict.fromkeys(keys)
    try:
        with h5py.File(path, "r") as file:
            project_name_list = list(file.keys())
            sample_name_list = []
            area_name_list = []
            for project in project_name_list:
                sample_list = list(file[project].keys())
                sample_name_list.extend(sample_list)
                for sample in sample_list:
                    area_list = list(file[project][sample].keys())
                    area_name_list.extend(area_list)
        sample_name_list = sorted(set(sample_name_list))
        area_name_list = sorted(set(area_name_list))
        metadata["PROJECT_NAME"] = project_name_list[0] if project_name_list else None
        metadata["NUM_SAMPLES"] = len(sample_name_list)
        metadata["NUM_AREAS"] = len(area_name_list)
        metadata["SAMPLE_NAME"] = ",".join(sample_name_list)
        metadata["AREA_NAME"] = ",".join(area_name_list)
        if len(sample_name_list) and len(area_name_list) == 1:
            project = project_name_list[0]
            sample = sample_name_list[0]
            area = area_name_list[0]
            with h5py.File(path, "r") as file:
                ebsd_keys = list(file[project][sample][area].keys())
                map_keys = [
                    k
                    for k in ebsd_keys
                    if k.lower().startswith("ebsd") and "map" in k.lower()
                ]
                if len(map_keys) == 1:
                    map_name = map_keys[0]
                    map_dataset = file[project][sample][area][map_name]
                    host_params = map_dataset["HOSTPARAMS"]
                    host_params = {
                        name: host_params[name][:] for name in host_params.dtype.names
                    }
                    metadata["ACCELERATING_VOLTAGE"] = float(
                        host_params["KV"]
                    )  # already in kV
                    grid_type = map_dataset["Sample"]["Grid Type"][0].decode()
                    metadata["EBSD_GRID_TYPE"] = (
                        "SQUARE_GRID" if grid_type == "SqrGrid" else "HEXAGONAL_GRID"
                    )
                    metadata["EBSD_X_STEP_UM"] = float(
                        map_dataset["Sample"]["Step X"][0]
                    )  # already in um
                    metadata["EBSD_Y_STEP_UM"] = float(
                        map_dataset["Sample"]["Step Y"][0]
                    )  # already in um
                    metadata["EBSD_X_CELLS"] = int(
                        map_dataset["Sample"]["Number Of Columns"][0]
                    )
                    metadata["EBSD_Y_CELLS"] = int(
                        map_dataset["Sample"]["Number Of Rows"][0]
                    )
                patterns_keys = [
                    k for k in ebsd_keys if k.lower().startswith("pattern-")
                ]
                metadata["CONTAINS_PATTERNS"] = len(patterns_keys) > 0
    except KeyError as e:
        pass
    return metadata
