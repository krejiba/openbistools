from decimal import Decimal, getcontext
import math


def get_vasp_struct_header(filename: str, num_lines: int = 7):
    """Reads the first lines from a VASP structure file."""
    try:
        with open(filename, "r") as fh:
            first_lines = [fh.readline() for _ in range(num_lines)]
        return "".join(first_lines)
    except FileNotFoundError:
        raise FileNotFoundError(f"File '{filename}' was not found.")
    except IOError as e:
        raise IOError(f"Error reading file '{filename}': {e}")


def decode_vasp_struct_header(txt: str, sep: str = " "):
    """Decodes the VASP structure header into a dictionary."""
    lines = txt.split("\n")
    if len(lines) < 7:
        raise ValueError("Header does NOT contain enough lines.")
    # Clean and normalize spacing

    lines = [sep.join(line.strip().split()) for line in lines]

    # Mapping header lines to specific keys

    header_info = {
        "UserComment": lines[0],
        "ScalingFactor": lines[1],
        "Lattice1": lines[2],
        "Lattice2": lines[3],
        "Lattice3": lines[4],
    }

    if lines[5].replace(sep, "").isalpha():
        header_info["SpeciesNames"] = lines[5]
        header_info["IonsPerSpecies"] = lines[6]
    else:
        header_info["IonsPerSpecies"] = lines[5]
    return header_info


def parse_vasp_struct(filename, keys):
    """Extracts relevant metadata from VASP structure file."""
    # Set precision

    getcontext().prec = 10

    with open(filename, "rb") as fh:
        header = fh.read(4096)
        if not (
            b"Poscar" in header
            or b"POSCAR" in header
            or b"Direct" in header
            or b"Cartesian" in header
        ):
            raise ValueError("This file parser is intended for VASP structure files")
    header = get_vasp_struct_header(filename)
    info = decode_vasp_struct_header(header)

    if "SpeciesNames" not in info:
        raise ValueError("Missing 'SpeciesNames' section in the header.")
    md_dict = dict.fromkeys(keys)  # Initialize dictionary with given keys

    # Determine the source of the file

    user_comment = info["UserComment"].lower()
    file_source = "UNKNOWN"
    if "pyiron" in user_comment:
        file_source = "PYIRON"
    elif "ovito" in user_comment:
        file_source = "OVITO"
    md_dict["FILE_SOURCE"] = file_source

    # Get Lattice parameters

    a1 = list(map(float, info["Lattice1"].split()))
    a2 = list(map(float, info["Lattice2"].split()))
    a3 = list(map(float, info["Lattice3"].split()))

    dot_product = lambda v1, v2: sum(i * j for i, j in zip(v1, v2))
    length = lambda v: math.sqrt(sum(i**2 for i in v))

    # Lengths of lattice vectors (in Angstroms)

    a = length(a1)
    b = length(a2)
    c = length(a3)

    # Angles between lattice vectors (in degrees)

    alpha = math.degrees(math.acos(dot_product(a2, a3) / (b * c)))
    beta = math.degrees(math.acos(dot_product(a1, a3) / (a * c)))
    gamma = math.degrees(math.acos(dot_product(a1, a2) / (a * b)))

    # Add rounded lattice parameters

    md_dict.update(
        {
            "BOX_LENGTH_A": +Decimal(a),
            "BOX_LENGTH_B": +Decimal(b),
            "BOX_LENGTH_C": +Decimal(c),
            "ANGLE_ALPHA": +Decimal(alpha),
            "ANGLE_BETA": +Decimal(beta),
            "ANGLE_GAMMA": +Decimal(gamma),
        }
    )

    atom_symbols = info["SpeciesNames"].split()
    atoms_unique = sorted(set(atom_symbols))
    atom_counts = list(map(int, info["IonsPerSpecies"].split()))

    # Composition details

    composition_info = {}
    for symbol, count in zip(atom_symbols, atom_counts):
        composition_info[symbol] = composition_info.get(symbol, 0) + count
    total_atoms = Decimal(sum(composition_info.values()))

    composition_details = {}
    for atom_id, (atom_symbol, atom_count) in enumerate(composition_info.items(), 1):
        atom_percent = Decimal(100) * (Decimal(atom_count) / total_atoms)
        composition_details.update(
            {
                f"ELEMENT_{atom_id}": atom_symbol,
                f"ELEMENT_{atom_id}_AT_PERCENT": +atom_percent,  # Rounded
                f"ELEMENT_{atom_id}_NUMBER": atom_count,
            }
        )
    md_dict.update(composition_details)

    md_dict.update(
        {
            "LIST_OF_SPECIES": ",".join(atoms_unique),  # Sorted alphabetically
            "NUMBER_OF_SPECIES": len(atoms_unique),
            "LIST_OF_ATOM_TYPES": ",".join(atom_symbols),
            "NUMBER_OF_ATOM_TYPES": len(atom_symbols),
            "NUMBER_OF_ATOMS": int(total_atoms),
        }
    )

    return md_dict
