import yaml


def get_hash(path: str) -> str:
    """
    Computes the MD5 hash of the file located at the specified path.

    Args:
        path (str): The file path of the file to be hashed.

    Returns:
        str: The hexadecimal representation of the MD5 hash of the file's contents.
    """
    import hashlib

    with open(path, "rb") as fh:
        str2hash = fh.read()
        result = hashlib.md5(str2hash)
    return result.hexdigest()


def parse_pacemaker(file_path: str, keys: list) -> dict:
    """
    Parses metadata from a Pacemaker YAML file and returns it as a dictionary.

    Args:
        file_path (str): The path to the YAML file of a potential created by pacemaker
        keys (list): A list of keys for the metadata dictionary.

    Returns:
        dict: A dictionary containing the parsed metadata.
    """
    md_dict = dict().fromkeys(keys)
    try:
        with open(file_path, "r") as file:
            data = yaml.safe_load(file)
    except yaml.YAMLError:
        raise ValueError(f"The provided file `{file_path}` is not a valid YAML format.")
    metadata = data.get("metadata", {})
    metadata = {key: value for key, value in metadata.items()}
    mapping = {
        "pacemaker_version": "SOFTWAREVERSION",
        "user": "USER_NAME",
        "intermediate_time": "DATE",
    }
    for k, kk in mapping.items():
        md_dict[kk] = metadata.get(k)
    md_dict["SOFTWARENAME"] = "pacemaker"
    date = md_dict.get("DATE")
    if date:
        md_dict["DATE"] = date.date().isoformat()
    md_dict["MD5_HASH"] = get_hash(file_path)
    return md_dict
