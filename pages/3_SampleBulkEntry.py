import streamlit as st
import os
import time
from datetime import datetime
import pandas as pd
import warnings

from Hello import find_relevant_locations

# Validation
COMPULSORY_COLUMNS = [
    "Name",
    "Location",
    "Sample Dimensions",
    "Date",
    "Element 1",
    "% Element 1",
]
ALLOWED_LOCATIONS = ""
TERMS_CRYSTAL_TYPE = set()
ATOMIC_SYMBOLS, SUBSTRATES = [], []
if st.session_state.logged_in:
    ALLOWED_LOCATIONS = (
        "RWTH,RUB,MPIE,FJZ,LEM3,EMPA,BAM,HZG,GFZ,TUDA,TUD,UDE,LEUPHANA,TUM"
    )
    TERMS_CRYSTAL_TYPE = set(
        st.session_state.oBis.get_terms(vocabulary="CRYSTAL_TYPE").df.code.tolist()
    )
    SUBSTRATES = set(
        st.session_state.oBis.get_terms(
            vocabulary="THIN_FILM_SUBSTRATE_VOCAB"
        ).df.code.tolist()
    )
    validation_plugin_code = st.session_state.oBis.get_object_type(
        "SAMPLE"
    ).validationPlugin
    validation_plugin = st.session_state.oBis.get_plugin(validation_plugin_code)
    # st.write(validation_plugin.script)
    code_str = validation_plugin.script
    import re, ast
    from ase.data import chemical_symbols

    match = re.search(r"ATOMIC_SYMBOLS\s*=\s*(\[[^\]]*\])", code_str, re.DOTALL)
    try:
        ATOMIC_SYMBOLS = (
            ast.literal_eval(match.group(1)) if match else chemical_symbols[1:]
        )
    except Exception:
        ATOMIC_SYMBOLS = chemical_symbols[1:]


def perform_validation(df: pd.DataFrame) -> bool:
    """Performs validation based on jython script SampleValidator.py."""

    detected_columns = set(df.columns.to_list())
    template = pd.read_excel("media/OpenBISSampleEntryTemplate.ods", engine="odf")
    allowed_columns = set(template.columns.to_list())

    if not detected_columns.issubset(set(allowed_columns)):
        col_names = ", ".join(template.columns.to_list())
        not_expected = detected_columns.difference(set(allowed_columns))
        msg = f"**Columns do not match!**  \n"
        msg += f"**Expected**: {col_names}  \n"
        msg += f"**Found**: {not_expected}"
        st.error(msg)
        return False
    if len(df) < 1:
        st.error("No sample detected")
        return False
    if df[COMPULSORY_COLUMNS].isnull().values.any():
        col_names = ", ".join(COMPULSORY_COLUMNS)
        st.error(f"One of **{col_names}** is empty.")
        return False
    element_cols = [
        col for col in detected_columns if "Element" in col and "%" not in col
    ]
    for element in set(df[element_cols].dropna(axis=1).values.flatten()):
        if element not in ATOMIC_SYMBOLS:
            st.error(
                f"*{element}* is not an atomic symbol. Please use **atomic symbols**!"
            )
            return False
    is_valid_total = lambda x: x > 99.999 and x < 100.001
    percent_cols = [col for col in detected_columns if "% Element" in col]
    percents = df[percent_cols].apply(
        lambda x: pd.to_numeric(
            x.astype("str").str.replace(",", ".").replace("nan", "0")
        ),
        axis=1,
    )

    if not percents.dropna(axis=1).sum(axis=1).apply(is_valid_total).all():
        st.error("Make sure percentages add up to **100%**")
        return False
    prefixes = ALLOWED_LOCATIONS.split(",")
    is_valid_location = (
        lambda x: any(x.startswith(prefix) for prefix in prefixes)
        or x == "processed"
        or x == "virtual"
    )
    if not df["Location"].apply(is_valid_location).all():
        msg = "Location should be **processed** or **virtual**  \n"
        msg += "or **ORGANIZATION**-GROUP\:ROOMNUMBER,  \n"
        msg += f"**ORGANIZATION** must be one of the following: **{ALLOWED_LOCATIONS}**"
        st.error(msg)
        return False
    is_valid_date = (
        lambda x: len(x) == 10
        and x[4] == "-"
        and x[7] == "-"
        and x.replace("-", "").isdigit()
    )
    if not df["Date"].apply(is_valid_date).all():
        msg = "**Date** should be **YYYY-MM-DD**\n"
        st.error(msg)
        return False
    for vocab, terms in [
        ("Crystal Type", TERMS_CRYSTAL_TYPE),
        ("Substrate", SUBSTRATES),
    ]:
        not_null_values = set(df[vocab].dropna().unique())
        if not df[vocab].isna().all() and not not_null_values.issubset(terms):
            msg = f"**{vocab}** should be one of the following:  \n"
            msg += ", ".join(terms)
            st.error(msg)
            return False
    object_permids = []
    for col_name in ["Parents", "Children"]:
        col = df[col_name].fillna("").str.strip().str.replace(r"\s+", " ", regex=True)
        col = col.str.replace(", ", ",").str.split(",")
        object_permids.extend(col.explode().tolist())
    object_permids = set(object_permids)
    object_permids.remove("")

    for perm_id in set(object_permids):
        try:
            st.session_state.oBis.get_object(perm_id)
        except ValueError:
            st.error(
                f"**Parent/Child** Object with permId = {perm_id} does **NOT** exist!"
            )
            return False
    st.success("Valid spreadsheet")
    return True


def create_parent_object(tag: str, permid: str, sample_props: dict, collection: str):
    """
    Creates a parent object based on provided tag.

    Args:
        tag (str): A tag that determines the type of object to be created.
        permid (str): The permId of the current sample for which we want to add a parent.
        sample_props (dict): A dictionary containing sample properties.
        collection (str): A collection / default experiment where the object will reside.

    Raises:
        KeyError: If the required keys ('$name' or 'date') are not found in `sample_props`.
        Exception: If object creation fails.
    """
    properties = {
        "$name": sample_props["$name"] + st.session_state[f"parent-{tag}-suffix"],
        "start_date": sample_props["date"],
    }
    if tag == "thinfilmsynthesis":
        object_type_code = "THIN_FILM_SYNTHESIS"
    elif tag == "mech":
        object_type_code = "TENSILE_EXPERIMENT"
    elif tag == "micromech":
        object_type_code = "MICRO_MECH_EXP"
        properties.update(
            {
                "tip_type": "BERKOVICH",
                "tip_material": "DIAMOND_TIP",
                "test_type": "NANOINDENTATION",
            }
        )
    else:
        object_type_code = "EXPERIMENTAL_STEP"
    if st.session_state[f"create-parent-{tag}"]:
        new_obj = st.session_state.oBis.new_object(
            type=object_type_code,
            props=properties,
            children=[permid],
            experiment=collection,  # User is expected to move it after creation
        )
        new_obj.save()


def create_child_object(tag: str, permid: str, sample_props: dict, collection: str):
    """
    Creates a child object based on provided tag.

    Args:
        tag (str): A tag that determines the type of object to be created.
        permid (str): The permId of the current sample for which we want to add a child.
        sample_props (dict): A dictionary containing sample properties.
        collection (str): A collection / default experiment where the object will reside.

    Raises:
        KeyError: If the required keys ('$name' or 'date') are not found in `sample_props`.
        Exception: If object creation fails.
    """
    if tag == "sem":
        object_type_code = "SEM_EXP"
    else:
        object_type_code = "EXPERIMENTAL_STEP"
    if st.session_state[f"create-child-{tag}"]:
        properties = {
            "$name": sample_props["$name"] + st.session_state[f"child-{tag}-suffix"],
            "start_date": sample_props["date"],
        }
        new_obj = st.session_state.oBis.new_object(
            type=object_type_code,
            props=properties,
            parents=[permid],
            experiment=collection,
        )
        new_obj.save()


warnings.filterwarnings(action="ignore", category=FutureWarning)


st.set_page_config(
    page_title="Enter samples",
    page_icon="media/SFB1394_icon.jpg",
    layout="wide",
)


try:
    _ = st.session_state.setup_done
except AttributeError as e:
    st.switch_page("Hello.py")
st.sidebar.image("media/SFB1394_TitleImage_Cropped.png")
st.sidebar.write("Logged into openBIS: ", st.session_state.logged_in)
st.sidebar.write("OpenBIS Upload OK: ", st.session_state.openbis_upload_allowed)
st.sidebar.write("S3 Upload OK: ", st.session_state.s3_upload_ok)
st.sidebar.write("S3 Download OK: ", st.session_state.s3_download_ok)


st.title("Enter Samples from spreadsheet")

st.warning(
    f"""
    * Please use **atomic symbols and atomic percentages**! Decimal separator can be a comma or a point.  
    * **Sample Dimensions** is compulsory, **Date** is compulsory and should be entered as follows: **YYYY-MM-DD**  
    * Location should be **processed** or **virtual** or **ORGANIZATION**-GROUP\:ROOMNUMBER,  
      * **ORGANIZATION** must be one of the following: **{ALLOWED_LOCATIONS.replace(",", ", ")}**  
      * **virtual** is used for simulation samples  
      * **processed** is used for physical samples that are no longer available due to significant transformation  
    * Please enter Parents and Children as comma-seperated permIds or identifiers  
    * Please enter Space Group as a number between 1 and 230  
    * Phases should be indicated as comma seperated text (e.g. \`Ferrite, Cementite`) if characterization already occurred  
    """
)

download_btn = st.download_button(
    label="Download template file",
    data=open("media/OpenBISSampleEntryTemplate.ods", "rb"),
    file_name="OpenBISSampleEntryTemplate.ods",
)

spreadsheet = st.file_uploader(
    "Upload filled spreadsheet (do no modify the header)",
    accept_multiple_files=False,
    type=["ods"],
    disabled=not st.session_state.setup_done,
)

st.session_state.table_loaded = False
if spreadsheet:

    df = pd.read_excel(spreadsheet, engine="odf", dtype={"Substrate Orientation": str})

    if perform_validation(df):
        for col_name in ["Parents", "Children"]:
            df[col_name] = df[col_name].fillna("")
            df[col_name] = df[col_name].str.strip()
            df[col_name] = df[col_name].str.replace(r"\s+", " ", regex=True)
            df[col_name] = df[col_name].str.replace(", ", ",")
            df[col_name] = df[col_name].str.split(",")
        float_columns = [col for col in df.columns if "% Element" in col] + [
            "Weight (g)"
        ]
        for col_name in float_columns:
            df[col_name] = pd.to_numeric(
                df[col_name].apply(
                    lambda x: (str(x).replace(",", ".").replace("nan", ""))
                )
            )
        sample_ot = st.session_state.oBis.get_object_type("SAMPLE")
        mapper = dict()
        for pt_code in sample_ot.get_property_assignments().df.code.to_list():
            property_type = st.session_state.oBis.get_property_type(pt_code)
            mapper[property_type.label] = property_type.code.lower()
        mapper["Is Transformed"] = "is_transformed"
        df = df.rename(columns=mapper)
        df = df.astype(object).where(pd.notnull(df), None)
        df["composition_desc"] = "ATOMIC_FRACTION"
        st.session_state.table_loaded = True
        st.session_state.samples_df = df
with st.form("EnterSamples"):

    refresh_btn = st.form_submit_button(
        "Refresh",
        type="primary",
        disabled=not (st.session_state.setup_done and st.session_state.table_loaded),
        help="Click if you added ELN entries after login",
    )

    if refresh_btn:
        with st.spinner("Please wait ..."):
            _ = find_relevant_locations(
                username=st.session_state.openbis_username,
                include_samples=st.session_state.include_samples,
            )
    collections_of_samples = dict()
    for display_name, identifier in st.session_state.experiments.items():
        if identifier.count("/") == 3:
            collection = st.session_state.oBis.get_experiment(identifier)
            if (
                collection.type == "COLLECTION"
                and collection.p.get("$default_object_type") == "SAMPLE"
            ):
                collections_of_samples[display_name] = identifier
    st.selectbox(
        "Choose in which Collection your samples will be created",
        list(collections_of_samples.keys()),
        index=None,
        placeholder="Select collection",
        key="collection",
        disabled=not st.session_state.table_loaded,
        help="Only collections with Sample as default object type will appear here",
    )

    msg = "You should move the entry after creation and modify the metadata."

    st.write(f"Create parents (*{msg}*)")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.checkbox(
            "Create Experimental Step",
            key="create-parent-exp",
            disabled=not st.session_state.table_loaded,
            help="Casting, Arc Melting, Metallography, etc.",
        )
        st.text_input(
            "Suffix",
            value="_Synthesis",
            key="parent-exp-suffix",
            disabled=not st.session_state.table_loaded,
            help="The suffix will be appended to the sample name",
        )
    with col2:
        st.checkbox(
            "Create Film Synthesis Experiment",
            key="create-parent-thinfilmsynthesis",
            disabled=not st.session_state.table_loaded,
            help="Thin Film Deposition",
        )
        st.text_input(
            "Suffix",
            value="_ThinFilmSynthesis",
            key="parent-thinfilmsynthesis-suffix",
            disabled=not st.session_state.table_loaded,
            help="The suffix will be appended to the sample name",
        )
    with col3:
        st.checkbox(
            "Create Mechanical Experiment",
            key="create-parent-mech",
            disabled=not st.session_state.table_loaded,
            help="Tensile, Compression, Bending",
        )
        st.text_input(
            "Suffix",
            value="_Compression",
            key="parent-mech-suffix",
            disabled=not st.session_state.table_loaded,
            help="The suffix will be appended to the sample name",
        )
    with col4:
        st.checkbox(
            "Create Micro Mechanical Experiment",
            key="create-parent-micromech",
            disabled=not st.session_state.table_loaded,
            help="Nanoindenation, Micro Pillar Compression",
        )
        st.text_input(
            "Suffix",
            value="_SRJT",
            key="parent-micromech-suffix",
            disabled=not st.session_state.table_loaded,
            help="The suffix will be appended to the sample name",
        )
    st.write(f"Create children (*{msg}*)")
    col1, col2 = st.columns(2)
    with col1:
        st.checkbox(
            "Create SEM Experiment",
            key="create-child-sem",
            disabled=not st.session_state.table_loaded,
            help="SEM, EBSD, EDS",
        )
        st.text_input(
            "Suffix",
            value="_SEM",
            key="child-sem-suffix",
            disabled=not st.session_state.table_loaded,
            help="The suffix will be appended to the sample name",
        )
    with col2:
        st.checkbox(
            "Create Experimental Step",
            key="create-child-exp",
            disabled=not st.session_state.table_loaded,
            help="TEM, XRD, LiMi, etc.",
        )
        st.text_input(
            "Suffix",
            value="_TEM",
            key="child-exp-suffix",
            disabled=not st.session_state.table_loaded,
            help="The suffix will be appended to the sample name",
        )
    confirm_btn = st.form_submit_button(
        "Create Samples in OpenBIS",
        type="primary",
        disabled=not st.session_state.table_loaded,
    )

    if confirm_btn:
        collection_name = collections_of_samples[st.session_state.collection]

        try:
            st.session_state.oBis.get_collection(collection_name)
        except ValueError:
            st.error("Collection not found!")
            collection_name = None
        if collection_name:
            progress_text = "Creating samples. Please wait."
            progress_bar = st.progress(0, text=progress_text)

            df = st.session_state.samples_df

            new_permids = []

            for i, row in df.iterrows():
                progress_bar.progress((i + 1) / len(df), text=progress_text)
                row = row.dropna()
                props = row.to_dict()
                parents = props.pop("Parents", [])
                children = props.pop("Children", [])
                if "" in parents:
                    parents.remove("")
                if "" in children:
                    children.remove("")
                new_sample = st.session_state.oBis.new_object(
                    type="SAMPLE",
                    props=props,
                    parents=parents,
                    children=children,
                    experiment=collection_name,
                )
                new_sample.save()
                permid = new_sample.permId

                new_permids.append(permid)

                for tag in ["exp", "thinfilmsynthesis", "mech", "micromech"]:
                    create_parent_object(tag, permid, props, collection_name)
                for tag in ["sem", "exp"]:
                    create_child_object(tag, permid, props, collection_name)
            progress_bar.empty()
            st.success(
                f"Samples added succesfully. \n",
                icon="✅",
            )
            permids = ", ".join(new_permids)
            st.text(f"Sample permIds: {permids}")
            st.session_state.table_loaded = False
            st.session_state.samples_df = None
