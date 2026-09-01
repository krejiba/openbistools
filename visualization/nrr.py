import netCDF4 as nc4


def get_image(path: str):
    a = nc4.Dataset(path, "r")
    arr = a["data"][:]
    if arr.ndim != 2:
        raise NotImplementedError("Only 2D data supported")
    return arr
