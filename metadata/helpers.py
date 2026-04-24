from decimal import Decimal


def flatten_dict(dictionary: dict, acc=None, parent_key=None, sep=".") -> dict:
    if not isinstance(dictionary, dict):
        return dictionary
    if acc is None:
        acc = {}
    for k, v in dictionary.items():
        k = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            flatten_dict(dictionary=v, acc=acc, parent_key=k)
            continue
        acc[k] = v
    return acc


def shape(collection):
    if isinstance(collection, list) or isinstance(collection, tuple):
        outermost_dim = len(collection)
        if outermost_dim:
            inner_shape = shape(collection[0])
        else:
            return ()
        return (outermost_dim, *inner_shape)
    else:
        return ()


def is_dec(txt: str) -> bool:
    import re

    return re.search(r"^[+-]?[0-9]*\.[0-9]+[eE]?[+-]?[0-9]+$", txt)


def is_int(txt: str) -> bool:
    import re

    return re.search(r"^[-+]?\d+$", txt)


def capitalize(txt: str) -> str:
    new_txt = txt[0].upper() + txt[1:]
    return new_txt


def convert_camelcase(txt: str, sep: str = "_") -> str:
    return "".join([capitalize(t) for t in txt.split(sep)])


def format_name(txt: str, sep: str = ".") -> str:
    import re

    new_txt = txt.replace(" ", "")

    # dm4
    new_txt = new_txt.replace("(", "[").replace(")", "]")

    # emi + ser
    new_txt = re.sub(r"-\d_", lambda m: m.group(0)[1], new_txt)
    last_section = new_txt.split(sep)[-1]
    if last_section in ["original_filename", "signal_type"]:
        last_section = convert_camelcase(last_section, "_")
    last_section = capitalize(last_section)

    pos = last_section.find("_")
    if pos > -1:
        last_section = last_section[:pos] + "[" + last_section[pos + 1 :] + "]"
    sections = [convert_camelcase(s, "_") for s in txt.split(sep)[:-1]]
    sections = sections + [last_section]
    new_txt = f"{sep}".join(sections)

    return new_txt


def clean(metadata_dict: dict, remove_prefix: str = "") -> dict:
    metadata_dict = flatten_dict(metadata_dict)
    metadata_dict = {
        k: (v.decode() if isinstance(v, bytes) else v) for k, v in metadata_dict.items()
    }
    metadata_dict = {
        k: (Decimal(v) if isinstance(v, str) and is_dec(v) else v)
        for k, v in metadata_dict.items()
    }
    metadata_dict = {
        k: (int(v) if isinstance(v, str) and is_int(v) else v)
        for k, v in metadata_dict.items()
    }
    metadata_dict = {
        k.replace("(", "[").replace(")", "]").replace(" ", ""): v
        for k, v in metadata_dict.items()
    }
    metadata_dict = {format_name(k): v for k, v in metadata_dict.items()}

    if len(remove_prefix):
        metadata_dict = {
            k.replace(remove_prefix, ""): v for k, v in metadata_dict.items()
        }
    return metadata_dict


def convert_value(value: str, actual_unit: str, desired_unit: str) -> Decimal:
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
        "µ": 1e-6,
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
    conversion_map = {k: Decimal(v) for k, v in conversion_map.items()}
    desired = conversion_map[desired_unit[0]]
    actual = conversion_map[actual_unit[0]]
    factor = actual / desired
    return Decimal(value) * factor
