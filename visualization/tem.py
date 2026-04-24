from pathlib import Path
import rsciio.digitalmicrograph as dm
import rsciio.emd as emd
import numpy as np


def get_image_stack(path: str, vertical: bool = True):
    """
    Loads and processes image stack from a `.dm3`, `.dm4`, or `.emd` file.

    This function reads an image stack from the specified file, processes the image data
    by normalizing it and casting to `uint8`, and returns the resulting image stack as a NumPy array.
    The images are stacked either vertically or horizontally depending on the `vertical` flag.

    Args:
        path (str): The file path to the TEM image file. This can be either a `.dm3`, `.dm4`, or `.emd` file.
        vertical (bool, optional): Whether to stack images vertically (True) or horizontally (False).
                                    Default is True (vertical stacking).

    Returns:
        numpy.ndarray: A 2D NumPy array containing the stacked images, with pixel values scaled to [0, 255].

    Raises:
        TypeError: If the file extension is not `.dm3`, `.dm4`, or `.emd`.
        RuntimeError: If the file contains no image data or if the dataset is empty.
    """
    ALLOWED_FILETYPES = ["dm3", "dm4", "emd"]
    path = Path(path)
    ext = path.suffix[1:]
    if ext in ALLOWED_FILETYPES[:2]:
        file_reader = dm.file_reader
    elif ext in ALLOWED_FILETYPES[2:3]:
        file_reader = emd.file_reader
    else:
        allowed = ", ".join(ALLOWED_FILETYPES)
        raise TypeError(f"This parser is intended for ({allowed}) files! Got {ext}.")
    try:
        file_content = file_reader(path)
    except Exception as e:
        raise TypeError(f"RosettaSciIO was not able to parse the {ext} file! {e}")
    arrays = []
    for dataset in file_content:
        if "data" in dataset:
            img = dataset["data"]
            if img.ndim == 3:
                img = img[-1]
            img = (img - img.min()) / (img.max() - img.min())
            img = img * 255
            img = img.astype("uint8")
            arrays.append(img)
    if len(arrays):
        if vertical:
            arrays = np.vstack(arrays)
        else:
            arrays = np.hstack(arrays)
    else:
        raise RuntimeError(f"Empty file: {path.name}")
    # FIXME Improve diffraction pattern image (gamma ?)

    return np.vstack(arrays)
