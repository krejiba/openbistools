from typing import Dict, List, Tuple, Optional
from decimal import Decimal, getcontext
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
import os


MASS_LOOKUP = {
    "H": 1.008,
    "He": 4.0026,
    "Li": 6.94,
    "Be": 9.0122,
    "B": 10.81,
    "C": 12.011,
    "N": 14.007,
    "O": 15.999,
    "F": 18.998,
    "Ne": 20.18,
    "Na": 22.99,
    "Mg": 24.305,
    "Al": 26.982,
    "Si": 28.085,
    "P": 30.974,
    "S": 32.06,
    "Cl": 35.45,
    "Ar": 39.95,
    "K": 39.098,
    "Ca": 40.078,
    "Sc": 44.956,
    "Ti": 47.867,
    "V": 50.942,
    "Cr": 51.996,
    "Mn": 54.938,
    "Fe": 55.845,
    "Co": 58.933,
    "Ni": 58.693,
    "Cu": 63.546,
    "Zn": 65.38,
    "Ga": 69.723,
    "Ge": 72.63,
    "As": 74.922,
    "Se": 78.971,
    "Br": 79.904,
    "Kr": 83.798,
    "Rb": 85.468,
    "Sr": 87.62,
    "Y": 88.906,
    "Zr": 91.224,
    "Nb": 92.906,
    "Mo": 95.95,
    "Tc": 97,
    "Ru": 101.07,
    "Rh": 102.91,
    "Pd": 106.42,
    "Ag": 107.87,
    "Cd": 112.41,
    "In": 114.82,
    "Sn": 118.71,
    "Sb": 121.76,
    "Te": 127.6,
    "I": 126.9,
    "Xe": 131.29,
    "Cs": 132.91,
    "Ba": 137.33,
    "La": 138.91,
    "Ce": 140.12,
    "Pr": 140.91,
    "Nd": 144.24,
    "Pm": 145,
    "Sm": 150.36,
    "Eu": 151.96,
    "Gd": 157.25,
    "Tb": 158.93,
    "Dy": 162.5,
    "Ho": 164.93,
    "Er": 167.26,
    "Tm": 168.93,
    "Yb": 173.05,
    "Lu": 174.97,
    "Hf": 178.49,
    "Ta": 180.95,
    "W": 183.84,
    "Re": 186.21,
    "Os": 190.23,
    "Ir": 192.22,
    "Pt": 195.08,
    "Au": 196.97,
    "Hg": 200.59,
    "Tl": 204.38,
    "Pb": 207.2,
    "Bi": 208.98,
    "Po": 209,
    "At": 210,
    "Rn": 222,
    "Fr": 223,
    "Ra": 226,
    "Ac": 227,
    "Th": 232.04,
    "Pa": 231.04,
    "U": 238.03,
    "Np": 237,
    "Pu": 244,
    "Am": 243,
    "Bk": 247,
    "Cf": 251,
    "Es": 252,
    "Fm": 257,
    "Md": 258,
    "No": 259,
    "Lr": 262,
    "Rf": 267,
    "Db": 268,
    "Hs": 269,
    "Bh": 270,
    "Mt": 277,
    "Ds": 281,
    "Rg": 282,
    "Cn": 285,
    "Nh": 286,
    "Mc": 290,
    "Lv": 293,
    "Og": 294,
}


def get_element_symbol(mass: float, max_deviation: float = 0.1) -> Tuple[str, float]:
    """Infers chemical symbol from atomic mass.

    Args:
        mass (float): The atomic mass for which the element symbol needs to be inferred. Defaults to 0.1.
        max_deviation (float): The maximum acceptable deviation to match the mass with a known element.

    Returns:
        tuple: A tuple containing the atomic symbol and the known atomic mass.

    Raises:
        ValueError: If no element matches the given mass within the maximum deviation.

    Notes:
        - The function excludes elements with no stable isotopes.
        - Source for atomic mass data:
          International Union of Pure and Applied Chemistry - Commission on Isotopic Abundances and Atomic Weights
          IUPAC CIAAW 2021
          For more information, visit: https://iupac.org/what-we-do/periodic-table-of-elements/
    """

    # Ignore elements with no stable isotopes

    mass_lookup = {k: v for k, v in MASS_LOOKUP.items() if isinstance(v, float)}

    # Find the element closest to the given mass
    matches = []
    for symbol, known_mass in mass_lookup.items():
        if abs(mass - known_mass) < max_deviation:
            matches.append((symbol, known_mass))
    if len(matches) == 1:
        return matches[0]
    raise ValueError(
        f"Cannot infer symbol from mass {mass} with deviation of {max_deviation}. Found {len(matches)} matches."
    )


def get_lammps_file_size(filename: str) -> int:
    """
    Determines the size of a LAMMPS structure file after validating its content.

    Args:
        filename (str): The path to the LAMMPS structure file to be analyzed.

    Returns:
        int: The size of the file in bytes.

    Raises:
        ValueError: If the file is not a valid LAMMPS structure.
    """

    with open(filename, "rb") as fh:
        header = fh.read(2048)
        if b"atom types" not in header:
            raise ValueError("This file parser is intended for LAMMPS structure files")
        sections = [b"Masses", b"Atoms"]
        for section_name in sections:
            if section_name not in header:
                raise ValueError(
                    f"{section_name} section is expected in a LAMMPS structure file"
                )
        fh.seek(0, os.SEEK_END)
        file_size = fh.tell()
    return file_size


def parse_atoms_chunk(
    chunk_lines: List[str], symbols: Dict[int, str]
) -> Dict[str, int]:
    """
    Parses a chunk of lines from the Atoms section of a LAMMPS structure file.

    Args:
        chunk_lines (list of str): A list of strings where each string represents a line from the file.
        symbols (dict): A dictionary that maps atom type IDs (integers) to their respective atomic symbols (strings).

    Returns:
        dict: A dictionary where the keys are atomic symbols (strings) and the values are
              the counts (integers) of atoms of each type found in the chunk of lines.

    Notes:
        - The function assumes that each line in `chunk_lines` contains at least 5 space-separated fields,
        with the second field representing the atom type ID.
        - If an atom type ID is not found in the `symbols` dictionary, it will be ignored.
    """
    composition_info = {}
    for line in chunk_lines:
        line = line.strip()
        if len(line.split()) > 4:
            type_id = int(line.split()[1])
            atom_symbol = symbols.get(type_id, None)
            if atom_symbol:
                composition_info[atom_symbol] = composition_info.get(atom_symbol, 0) + 1
    return composition_info


def process_atoms_chunk(
    filename: str,
    start_pos: int,
    symbols: Dict[int, str],
    chunk_size: int,
) -> Dict[str, int]:
    """
    Processes a chunk of lines from the Atoms section of a LAMMPS structure file.

    Args:
        filename (str): The path to the file to read the chunk from.
        start_pos (int): The position in the file from which to start reading the chunk.
        symbols (dict): A dictionary that maps atom type IDs (integers) to their respective atomic symbols (strings).
        chunk_size (int): The number of bytes to read.
    Returns:
        dict: A dictionary where the keys are atomic symbols (strings) and the values are
              the counts (integers) of atoms of each type found in the chunk of lines.

    """
    with open(filename, "r") as file:
        file.seek(start_pos - 1)
        last_char = file.read(1)

        buffer = file.read(chunk_size)
        lines = buffer.split("\n")
        chunk_lines = [line + "\n" for line in lines[:-1]]

        if last_char != "\n":
            chunk_lines.pop(0)
        last_line = lines[-1]
        if not buffer.endswith("\n"):
            next_char = file.read(1)
            while next_char != "\n" and next_char:
                last_line += next_char
                next_char = file.read(1)
        chunk_lines.append(last_line + "\n")

        total = sum(len(line) for line in chunk_lines)

        return parse_atoms_chunk(chunk_lines, symbols)


def process_mass_line(
    mass_line: str,
    symbols: Dict[int, str],
    masses: Dict[int, float],
    max_deviation: float,
) -> None:
    """
    Processes a line from the `Masses` section of a LAMMPS structure file
    and updates the `symbols` and `masses` dictionaries with the extracted information.

    Args:
        mass_line (str): A single line from the 'Masses' section of the LAMMPS file.
                          The line should contain an atom type ID followed by its mass.
                          Optionally, a comment with an atomic symbol may follow.
        symbols (dict): A dictionary that maps atom type IDs (integers) to their respective atomic symbols (strings).
        masses (dict): A dictionary that stores atom type IDs (integers) and their respective masses (floats).
        max_deviation (float): A threshold for deviation when matching the atomic mass to the symbol.

    Raises:
        ValueError: If there is a mismatch between the atom symbol from the comment
                    and the identified atom symbol based on the mass,
                    or if the comment does not correspond to a valid atomic symbol.

    Notes:
        - The function expects the mass line to be in the format `type_id mass [# symbol]`.
        - If a comment is present after the mass, it is assumed to be the atomic symbol.
          The function verifies its correctness against known atomic masses.
        - This function modifies the `symbols` and `masses` dictionaries in place.
    """
    line_parts = mass_line.split()
    if len(line_parts) >= 2:
        type_id = int(line_parts[0])
        mass = float(line_parts[1])
        masses[type_id] = mass
        atom_symbol, known_mass = get_element_symbol(mass, max_deviation)
        if len(line_parts) > 2 and "#" in mass_line:
            symbol = mass_line.replace(" ", "").split("#")[-1]
            symbol = "".join(filter(str.isalpha, symbol))
            if symbol.lower() in set(map(str.lower, MASS_LOOKUP.keys())):
                if atom_symbol == symbol:
                    # print(f'({potential_symbol}, {mass}) = ({atom_symbol}, {known_mass} +/- {max_deviation})')

                    symbols[type_id] = symbol
                else:
                    raise ValueError(
                        f"Symbol from comment {symbol} with mass {mass} differs from symbol {atom_symbol} with mass {known_mass} +/- {max_deviation}"
                    )
            else:
                raise ValueError(
                    f"No atomic symbol can be recognised from comment {symbol}."
                )
        symbols[type_id] = atom_symbol


def process_atoms_parallel(
    filename: str,
    atoms_start_pos: int,
    symbols: Dict[int, str],
    chunk_size: int,
    num_chunks: int,
):
    """
    Processes lines from the Atoms section of a LAMMPS structure file.

    Args:
        filename (str): The path to the LAMMPS structure file to be processed.
        atoms_start_pos (int): The position of the Atoms sections in the file.
        symbols (dict): A dictionary that maps atom type IDs (integers) to their respective atomic symbols (strings).
        chunk_size (int): The number of bytes to process per chunk.
        num_chunks (int): The number of chunks.

    Returns:
        Dict[str, int]: A dictionary where the keys are atom symbols (str) and the values are the counts
                        of each atom symbol across all chunks.
    """

    composition_info = {}

    def task(chunk_index: int):
        start_pos = atoms_start_pos + chunk_index * chunk_size
        chunk_composition = process_atoms_chunk(
            filename, start_pos, symbols, chunk_size
        )
        return chunk_composition

    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(task, i): i for i in range(num_chunks)}
        for future in as_completed(futures):
            chunk_composition_info = future.result()
            for atom_symbol, count in chunk_composition_info.items():
                composition_info[atom_symbol] = (
                    composition_info.get(atom_symbol, 0) + count
                )
    return composition_info


def get_compostition_info(
    filename: str, max_deviation: float = 0.1
) -> Tuple[Dict[str, int], List[str]]:
    """
    Reads a LAMMPS structure file and returns a dictionary containing the count of each atom type in the file.

    Args:
        filename (str): The path to the LAMMPS structure file to be processed.
        max_deviation (float, optional): A threshold for deviation when matching the atomic mass to the symbol.
                                         Default is 0.1.

    Returns:
        dict: A dictionary where the keys are atomic symbols (strings) and the values are
              the counts (integers) of atoms of each type found in the structure file.

    Notes:
        - It processes the file in chunks for faster results when dealing with large files.
        - The function assumes that the structure file follows LAMMPS format conventions
          and contains both `Masses` and `Atoms` sections.
    """
    file_size = get_lammps_file_size(filename)

    with open(filename, "r") as file:
        masses_section_found = False
        masses = dict()
        symbols = dict()
        total_number_of_atoms = 0

        line = file.readline()
        while line:
            line = line.strip()
            if line.endswith(" atoms"):
                total_number_of_atoms = int(line.split()[0])
            elif "atom types" in line:
                atom_types = int(line.split()[0])
            elif line.startswith("Masses"):
                masses_section_found = True
            elif line.startswith("Atoms"):
                atoms_start_pos = file.tell()
                break
            if masses_section_found and line:
                process_mass_line(line, symbols, masses, max_deviation)
            line = file.readline()

        atom_types = [get_element_symbol(m, max_deviation)[0] for m in masses.values()]

        chunk_size = 20971520  # 20 Mb
        composition_info = dict()
        num_chunks = (file_size - atoms_start_pos) // chunk_size + 1
        if len(masses) == 1:
            atom_symbol = symbols[1]
            composition_info[atom_symbol] = total_number_of_atoms
            return composition_info, atom_types
        if num_chunks == 1:
            composition_info = process_atoms_chunk(
                filename, atoms_start_pos, symbols, file_size
            )
        else:
            composition_info = process_atoms_parallel(
                filename, atoms_start_pos, symbols, chunk_size, num_chunks
            )
        # assert total_number_of_atoms == sum(composition_info.values())
        # assert atom_types == len(composition_info)
    return composition_info, atom_types


def get_metadata_header(
    filename: str, unit_style: str = "metal"
) -> Dict[str, Decimal | int | str]:
    """Parses metadata from the header of a LAMMPS structure file.

    Args:
        filename (str): The path to the LAMMPS structure file to parse.

        unit_style (str, optional): The unit style used in the LAMMPS simulation. Defaults to 'metal'.

    Returns:
        dict: A dictionary containing the extracted metadata.

    Raises:
        ValueError: If the provided `unit_style` is invalid or if `lj` is used as the unit style.

    Notes:
        - The unit style used in the LAMMPS simulation affects the box dimensions.
          Expected values include `si`, `cgs`, `micro`, `nano`, `real`, `metal`, and `electron`.
        - Lennard-Jones (`lj`) unit style is not supported as further input might be needed to extract meaningful meatadata.
    """
    md_dict = {}

    scaling_factors = {
        "si": Decimal(1e10),
        "cgs": Decimal(1e8),
        "micro": Decimal(1e4),
        "nano": Decimal(10),
        "real": Decimal(1),
        "metal": Decimal(1),
        "electron": Decimal(0.529177249),
    }
    scaling_factor = scaling_factors.get(unit_style)
    if scaling_factor is None:
        if unit_style == "lj":
            raise ValueError(
                "unit_style: lj does NOT allow computing of metadata (unitless)."
            )
        else:
            raise ValueError(
                f"unit_style: {unit_style} is not a valid LAMMPS unit style."
            )
    md_dict["LAMMPS_UNIT_STYLE"] = unit_style.upper()

    source_map = {
        "pyiron": "PYIRON",
        "ovito": "OVITO",
        "write_data": "LAMMPS",
    }

    box_data = [0] * 9
    box_keys = ["xlo xhi", "ylo yhi", "zlo zhi", "xy xz yz"]
    all_keys = " ".join(box_keys).split(" ")

    with open(filename, "r") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            line = " ".join(line.split())
            if i == 0:
                line_lower = line.lower()
                filesource = next(
                    (key for key in source_map if key in line_lower), None
                )
                filesource = source_map.get(filesource, "UNKNOWN")
                md_dict["FILE_SOURCE"] = filesource
            if "atoms" in line:
                md_dict["NUMBER_OF_ATOMS"] = int(line.split()[0])
            if "atom types" in line:
                md_dict["NUMBER_OF_ATOM_TYPES"] = int(line.split()[0])
            for key_str in box_keys:
                if key_str in line:
                    line_keys = key_str.split()
                    num_keys = len(line_keys)
                    pos = all_keys.index(line_keys[0])
                    box_data[pos : pos + num_keys] = list(
                        map(float, line.split()[:num_keys])
                    )
            if "Velocities" in line:
                break
    xlo, xhi, ylo, yhi, zlo, zhi, xy, xz, yz = box_data
    a1 = [xhi - xlo, 0, 0]
    a2 = [xy, yhi - ylo, 0]
    a3 = [xz, yz, zhi - zlo]

    dot_product = lambda x, y: sum(i * j for i, j in zip(x, y))
    length = lambda x: math.sqrt(sum(i**2 for i in x))

    a = length(a1)
    b = length(a2)
    c = length(a3)

    alpha = math.degrees(math.acos(dot_product(a2, a3) / (b * c)))
    beta = math.degrees(math.acos(dot_product(a1, a3) / (a * c)))
    gamma = math.degrees(math.acos(dot_product(a1, a2) / (a * b)))

    # unary plus triggers rounding

    md_dict["BOX_LENGTH_A"] = +Decimal(a) * scaling_factor
    md_dict["BOX_LENGTH_B"] = +Decimal(b) * scaling_factor
    md_dict["BOX_LENGTH_C"] = +Decimal(c) * scaling_factor
    md_dict["ANGLE_ALPHA"] = +Decimal(alpha)
    md_dict["ANGLE_BETA"] = +Decimal(beta)
    md_dict["ANGLE_GAMMA"] = +Decimal(gamma)

    return md_dict


def parse_lammps_struct(
    filename: str, keys: List[str], unit_style: str = "metal"
) -> Dict[str, Optional[Decimal | int | str]]:
    """
    Extracts relevant metadata from a LAMMPS structure file.

    Args:
        filename (str): The path to the LAMMPS structure file.
        keys (List[str]): A list of keys that define the metadata schema.
        unit_style (str, optional): The unit style used in the LAMMPS file (default is 'metal').

    Returns:
        Dict[str, Optional[Decimal | int | str]]: A dictionary containing the extracted metadata.

    Raises:
        ValueError: If the keys in the dictionary do not match the expected schema.

    Note:
        - We use the mass to determine the atom type. If multiple atom types share the same mass,
        they are collapsed into one atom type.

    """
    # Set precision

    getcontext().prec = 10

    md_dict = dict.fromkeys(keys)

    get_lammps_file_size(filename)  # Validate

    header_metadata = get_metadata_header(filename, unit_style)

    composition_info, atom_types = get_compostition_info(filename)

    total = Decimal(sum(composition_info.values()))

    composition_details = {}
    for i, (atom_symbol, atom_count) in enumerate(composition_info.items(), 1):
        atom_percent = Decimal(100) * (Decimal(atom_count) / total)
        composition_details[f"ELEMENT_{i}"] = atom_symbol
        composition_details[f"ELEMENT_{i}_AT_PERCENT"] = +atom_percent  # rounded
        composition_details[f"ELEMENT_{i}_NUMBER"] = atom_count
    md_dict = {**md_dict, **header_metadata, **composition_details}

    expected_1 = md_dict["NUMBER_OF_ATOMS"]
    found_1 = sum(composition_info.values())
    message_1 = f"Total number of atoms from header ({expected_1}) do not match the counted particles ({found_1})"
    expected_2 = md_dict["NUMBER_OF_ATOM_TYPES"]
    found_2 = len(composition_info)
    message_2 = f"Number of atom types from header ({expected_2}) do not match the counted particle types ({found_2})"
    assert expected_1 == found_1, message_1
    # assert expected_2 == found_2, message_2

    md_dict["LIST_OF_ATOM_TYPES"] = ",".join(atom_types)
    md_dict["LIST_OF_SPECIES"] = ",".join(sorted(composition_info.keys()))
    md_dict["NUMBER_OF_SPECIES"] = len(composition_info)

    # ############################## Sanity Check #############################

    # Check if the keys match the schema

    set_a = set(md_dict.keys())
    set_b = set(keys)
    problematic_keys = set_a.symmetric_difference(set_b)
    assert set_a == set_b, "Problematic keys: %s" % problematic_keys

    return md_dict
