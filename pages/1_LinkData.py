import streamlit as st
import time
import os
from datetime import datetime, timezone
from decimal import Decimal
from botocore.exceptions import ClientError
from boto3.exceptions import S3UploadFailedError
import pandas as pd
import uuid
import warnings

DEMO_METADATA_URL = "https://sfb1394-metadata.streamlit.app"

# PyBIS helper code we need to register the file


from pybis_tools import (
    get_dms_info,
    register_file,
    get_file_metadata,
    get_info_from_identifier,
)

# Idnetify available metadata extractors


from data_handling_tools import get_metadata

# Utility to update experiment list


from Hello import find_relevant_locations, ALLOWED_OBJECT_TYPES

warnings.filterwarnings(action="ignore", category=FutureWarning)


# rewrite as stages?
# https://discuss.streamlit.io/t/multi-step-form-interaction/55600/2

## ----------------------------------------------------------------------------
## Helper functions
## ----------------------------------------------------------------------------


def format_func(code: str) -> str:
    """Maps OpenBIS dataset type codes to corresponding display text."""
    display_text = st.session_state.oBis.get_dataset_type(code).description
    if display_text is not None:
        return display_text
    match code:
        # case "CODE":
        #     return "DISPLAY_TEXT"

        case _:
            return " ".join(part.capitalize() for part in code.split("_"))


def display_linked_samples():
    """Presents information about linked samples"""
    full_identifier = st.session_state.experiments[st.session_state.experiment]
    exp_identifier, obj_identifier = get_info_from_identifier(full_identifier)

    if obj_identifier is not None:
        openbis_object = st.session_state.oBis.get_object(obj_identifier)

        # User uploads data to Sample (e.g. structure file)
        if openbis_object.type == "SAMPLE":
            msg = f"You will upload data to sample *{openbis_object.permId}*.  \n"
            sample_name = openbis_object.p["$name"].strip()  # Compulsory
            sample_dim = openbis_object.p.sample_dim.replace("*", "x")  # Compulsory
            comments = openbis_object.p.comments  # Optional
            comments = "None" if comments is None else comments.strip()
            comments = comments[:100]
            props = openbis_object.p()
            props = {
                k: v[:5]
                for k, v in sorted(props.items())
                if v is not None and k.startswith("element")
            }
            desc = "".join(props.values())
            msg = f"You will upload data to Sample **{sample_name}** *{openbis_object.permId}*  \n"
            msg += f"├──  Composition: **{desc}**  \n"
            msg += f"├──  Dimensions: **{sample_dim}**  \n"
            msg += f"├──  Comments: **{comments}**  \n"
            msg += f"Please change the sample if that is not the desired outcome."
            st.markdown(msg)
            return

    def find_linked_samples(object_code):
        """Returns a list of samples directly linked to the selected object."""

        object = st.session_state.oBis.get_object(object_code)
        samples = []
        relative_identifier = None
        for relative_identifier in object.children + object.parents:
            relative = st.session_state.oBis.get_object(relative_identifier)
            if relative.type not in ALLOWED_OBJECT_TYPES:
                continue
            if relative.type == "SAMPLE":
                samples.append(relative)
        return samples

    with st.spinner("Finding samples..."):
        try:
            openbis_object = st.session_state.oBis.get_object(obj_identifier)
            samples = find_linked_samples(obj_identifier)
            object_or_experiment = openbis_object
            is_default_experiment = False
        except AttributeError:
            experiment = st.session_state.oBis.get_experiment(exp_identifier)
            samples = experiment.get_objects(type="SAMPLE")
            object_or_experiment = experiment
            is_default_experiment = True
    msg = f"You will upload data to experiment *{object_or_experiment.permId}*.  \n"
    for sample in samples:
        sample_name = sample.p["$name"].strip()  # Compulsory
        sample_dim = sample.p.sample_dim.replace("*", "x")  # Compulsory
        sample_subtype = sample.p.sample_subtype  # Optional
        comments = sample.p.comments  # Optional
        if comments:
            comments = (
                "None" if comments is None else comments.strip().replace("\n", ", ")
            )
            comments = comments[:100]
        else:
            comments = "None"
        props = sample.p()
        props = {
            k: v[:5]
            for k, v in sorted(props.items())
            if v is not None and k.startswith("element")
        }
        desc = "".join(props.values())
        if sample_subtype is not None:
            sample_name = sample_name + f" ({sample_subtype})"
        msg += f"├──  Directly linked to Sample **{sample_name}** *{sample.permId}*  \n"
        msg += f"├────  Composition: **{desc}**  \n"
        msg += f"├────  Dimensions: **{sample_dim}**  \n"
        msg += f"├────  Comments: **{comments}**  \n"
    msg += f"Please update the experiment if that is not the desired outcome."
    if len(samples) == 0:
        insert_text = "default" if is_default_experiment else ""
        st.warning(
            "No samples are direclty linked to this " + insert_text + " experiment!"
        )
    st.markdown(
        msg,
        help="Only directly linked samples are fetched.",
    )


def link_file(
    file_name: str,
    prefix: str,
    dss_code: str,
    properties: dict,
    placeholder,
) -> str:
    """
    Uploads data to S3 and links data to an entry in openBIS.

    Args:
        file_name (str): File name (without path) of the file to process.
        prefix (str): User-specified string to prepend to the uploaded data file(s).
        dss_code (str): Code of the openBIS DSS to use when linking the file.
        properties (dict): File properties and metadata.

    Returns:
        str: openBIS perm-ID of the linked file after successful registration.
    """

    new_file_name = prefix + file_name  # prefix ends with _
    try:
        dms_path, dms_id = get_dms_info(
            oBis=st.session_state.oBis,
            filename=new_file_name,
            dms_code=st.session_state.obis_dmscode,
        )
    except Exception as e:
        st.error("External storage not found in openBIS", icon="🔥")
        st.stop()
    # get basic metadata from the file

    file_name_fqdn = st.session_state.temp_dir + "/" + file_name
    file_metadata = None
    try:
        file_metadata = get_file_metadata(
            filename=file_name_fqdn, dms_path=dms_path, compute_crc32=False
        )
    except Exception as e:
        st.error("File metadata could not be created", icon="🔥")
    # no parents in simple tool

    parent_ids = []

    full_identifier = st.session_state.experiments[st.session_state.experiment]
    experiment_name, object_name = get_info_from_identifier(full_identifier)

    token = st.session_state.openbis_token

    ## upload file to S3

    try:
        with st.spinner("Uploading data to S3..."):
            response = st.session_state.s3_client.upload_file(
                file_name_fqdn,
                st.session_state.s3_bucket_name,
                new_file_name,
            )

        if file_metadata is not None:
            linked_permID = register_file(
                oBis=st.session_state.oBis,
                file_metadata=file_metadata,
                dms_path=dms_path,
                dms_id=dms_id,
                dss_code=dss_code,
                object_name=object_name,
                experiment_name=experiment_name,
                properties=properties,
                data_set_code=None,
                data_set_type=st.session_state.ds_type,
                parent_ids=parent_ids,
            )
            placeholder.success(
                f"File added as link in openBIS with ID {linked_permID}",
                icon="✅",
            )

            # check if the file is actually there
            # by calling "head_object" on that file in our bucket

            try:
                st.session_state.s3_client.head_object(
                    Bucket=st.session_state.s3_bucket_name, Key=new_file_name
                )
                url = st.session_state.s3_client.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": st.session_state.s3_bucket_name,
                        "Key": new_file_name,
                    },
                    ExpiresIn=604800,  # 1 WEEK
                    HttpMethod="GET",
                )
                ds = st.session_state.oBis.get_dataset(linked_permID)
                ds.p["s3_download_link"] = url
                ds.save()
            except ClientError as e:
                st.write(e.response)
                error_code = e.response["Error"]["Code"]
                if error_code == "403":
                    st.error("Access denied!", icon="🔥")
                elif error_code == "SignatureDoesNotMatch":
                    st.error("Access denied!", icon="🔥")
                elif error_code == "404":
                    st.error("Failed to upload file!", icon="🔥")
            else:
                placeholder.success(
                    f"File uploaded successfully as {new_file_name}", icon="✅"
                )
    except S3UploadFailedError:
        st.error(
            "S3 upload client was not set up properly! Please check the config file."
        )
        linked_permID = None

    # remove local file

    os.unlink(file_name_fqdn)

    return linked_permID


## ############################################################################
## Upload to openBIS
## ############################################################################


def upload_to_openbis(file_name: str, prefix: str, properties: dict, placeholder):
    """Upload file directly to openBIS, including metadata

    Args:
        file_name (str): file name (w/o path) of the file to process
        prefix (str): user-specified string that should be pre-pended
            to the uploaded data file(s)
        properties (dict): file properties and metatdata

    Returns:
        str : permID of the uploaded file
    """

    # Add prefix to filename

    new_file_name = prefix + file_name  # prefix ends with _
    os.replace(
        st.session_state.temp_dir + "/" + file_name,
        st.session_state.temp_dir + "/" + new_file_name,
    )

    file_name_fqdn = st.session_state.temp_dir + "/" + new_file_name

    full_identifier = st.session_state.experiments[st.session_state.experiment]
    experiment_name, object_name = get_info_from_identifier(full_identifier)

    permid = None

    placeholder.write(f"Uploading file {new_file_name} to openBIS")

    # Filter to remove all null properties

    properties_no_nulls = dict()
    for k, v in properties.items():
        if v is not None:
            properties_no_nulls[k] = v
    ds_new = st.session_state.oBis.new_dataset(
        type=st.session_state.ds_type,
        object=object_name,
        experiment=experiment_name,
        files={file_name_fqdn},
        props=properties_no_nulls,
    )
    # st.write(ds_new)

    with st.spinner("Uploading data ..."):
        permid = ds_new.save()
    placeholder.success(f"File uploaded to openBIS with ID {permid}", icon="✅")

    # remove local file

    os.unlink(file_name_fqdn)

    return permid


## ----------------------------------------------------------------------------
## Main Streamlit App
## ----------------------------------------------------------------------------


st.set_page_config(
    page_title="Register data in openBIS",
    page_icon="media/SFB1394_icon.jpg",
    layout="wide",
)

try:
    _ = st.session_state.setup_done
    st.session_state.prefix = None
    if st.session_state.get("options") is None:
        st.session_state.options = {}
    if st.session_state.get("uploader_key") is None:
        st.session_state.uploader_key = "uploader"
except AttributeError as e:
    st.switch_page(page="Hello.py")
st.sidebar.image("media/SFB1394_TitleImage_Cropped.png")
st.sidebar.write("Logged into openBIS: ", st.session_state.logged_in)
st.sidebar.write("OpenBIS Upload OK: ", st.session_state.openbis_upload_allowed)
st.sidebar.write("S3 Upload OK: ", st.session_state.s3_upload_ok)
st.sidebar.write("S3 Download OK: ", st.session_state.s3_download_ok)
st.sidebar.write("S3 Resource: ", st.session_state.obis_dmscode)
st.sidebar.write("Upload to Samples: ", st.session_state.include_samples)


##  Form 1: Log into openBIS and configure S3


st.title("Register Data in openBIS")
st.write(
    "Please use script-based methods if your data is larger than 5 GB in total (at least until new resources are available)"
)

with st.form("Form_DS_Exp"):

    st.subheader("Step 2: Choose Dataset Type & Experiment to link data to.")

    refresh_btn = st.form_submit_button(
        "Refresh",
        type="primary",
        disabled=not st.session_state.setup_done,
        help="Click if you added ELN entries after login",
    )

    if refresh_btn:
        with st.spinner("Please wait ..."):
            allowed_object_types = find_relevant_locations(
                username=st.session_state.openbis_username,
                include_samples=st.session_state.include_samples,
            )
        allowed_object_types_display = [
            " ".join(part.capitalize() for part in code.split("_"))
            for code in allowed_object_types
        ]
        allowed_object_types_display_str = ", ".join(allowed_object_types_display)
        st.warning(
            "You can upload to a Default Experiment "
            f"or one of following: {allowed_object_types_display_str}"
        )
    st.selectbox(
        "Choose a dataset type",
        sorted(st.session_state.ds_type_set, key=format_func),
        index=None,
        placeholder="Select Dataset Type",
        key="ds_type",
        disabled=not st.session_state.logged_in,
        format_func=format_func,
    )
    if st.session_state.include_samples:
        msg = "Choose an experiment / a sample"
    else:
        msg = "Choose an experiment"
    st.selectbox(
        msg,
        st.session_state.experiment_name_list,
        index=None,
        placeholder="Select experiment",
        key="experiment",
        disabled=not st.session_state.logged_in,
    )

    choose_dataset_btn = st.form_submit_button(
        "Submit",
        type="primary",
        disabled=not st.session_state.setup_done,
        help="Confirm choice",
    )

    if choose_dataset_btn:
        if st.session_state.experiment is not None:
            valid_upload_location = True
            st.session_state.disable_upload = True
            # We would like regular users to not upload data to Collections using this GUI

            experiment_id = st.session_state.experiments[st.session_state.experiment]
            try:
                experiment = st.session_state.oBis.get_experiment(experiment_id)
                if experiment.attrs.type == "COLLECTION":
                    st.error(
                        "You are not allowed to upload to Collections using this tool",
                        icon="🔥",
                    )
                    valid_upload_location = False
            except ValueError:
                pass  # This is expected for objects
            if st.session_state.ds_type is not None and valid_upload_location:
                # We show linked samples to help prevent erroneous uploads

                display_linked_samples()

                st.session_state.disable_upload = False
                if st.session_state.ds_type in [
                    "SEM_DATA",
                    "TEM_DATA",
                    "STEM-EDS_DATA",
                ]:
                    st.warning(
                        "STEM acquired in an SEM should should be uploaded as SEM"
                    )
                if st.session_state.ds_type in [
                    "EBSD_EXP_DATA",
                    "EDS_DATA",
                    "EBSD-EDS_DATA",
                ]:
                    st.warning(
                        "Please note that we have these dataset types: EBSD, EDS and EBSD+EDS"
                    )
                if st.session_state.ds_type == "ELECTROCHEM_DATA":
                    st.warning(
                        "Please note that we have these dataset types: SVET, SIET, PDP, OCP, XPS, XRR, EIS"
                    )
                if st.session_state.ds_type == "RAW_DATA":
                    st.warning("Please use domain-specific datasetTypes instead")


## Form 3: Choose metadata extractor, upload file to Streamlit,
##         upload to Coscine and link data (and metadata) in openBIS


with st.form("Form_Link"):
    st.subheader("Step 3: Registering file & settings")
    data_set_name = st.text_input(
        "Enter a name under which the data will appear in openBIS",
        help="You can use this to easily find the files in the openBIS User Interface"
        " - Avoid using commas or periods",
        placeholder="mandatory",
        key="data_set_name",
        disabled=st.session_state.disable_upload,
    )

    data_set_comments = st.text_area(
        "Enter comments on the files",
        help="You can use this to add useful information about the file(s) \
            you are uploading (e.g. corrupted, incomplete acquisition, etc.)",
        placeholder="optional",
        key="data_set_comments",
        disabled=st.session_state.disable_upload,
    )

    if st.session_state.ds_type == "APT_DATA":
        oBis = st.session_state.oBis
        st.text("Enter metadata manually")
        dataset_type = oBis.get_dataset_type(st.session_state.ds_type)
        assignments = dataset_type.get_property_assignments().df
        props = assignments.code.to_list()
        manual = [p for p in props if p.startswith("TEMP_")]
        data = [
            [
                code,
                oBis.get_property_type(code).dataType,
                oBis.get_property_type(code).label,
                None,
                (
                    oBis.get_terms(
                        oBis.get_property_type(code).vocabulary
                    ).df.code.to_list()
                    if oBis.get_property_type(code).dataType == "CONTROLLEDVOCABULARY"
                    else None
                ),
            ]
            for code in manual
        ]
        manual_df = pd.DataFrame(
            data, columns=["Code", "Datatype", "Field", "Value", "Possible Values"]
        )
        manual_df.set_index("Code", drop=True, inplace=True)
        manual_entry = st.data_editor(
            key="manual_metadata",
            data=manual_df,
            column_config={
                "Code": None,
                "Datatype": None,
                "Field": st.column_config.TextColumn(disabled=True),
                "Value": st.column_config.Column(width="medium"),
                "Possible Values": st.column_config.Column(width="large"),
            },
        )
        real_values = manual_entry.loc[manual_entry.Datatype == "REAL", "Value"]
        real_values = real_values.str.replace(",", ".")
        manual_entry.loc[manual_entry.Datatype == "REAL", "Value"] = real_values
    else:
        manual_entry = None
    if st.session_state.s3_upload_ok:
        prefix = ""
        # prefix = st.text_input(
        #     "Enter an additional prefix for the file",
        #     help="You can use this to easily find the files in the Coscine User Interface, if needed",
        #     placeholder="optional",
        #     key="prefix",
        #     disabled=st.session_state.disable_upload,
        # )
    metadata_extractors = []
    match st.session_state.ds_type:
        case "SEM_DATA":
            metadata_extractors = [
                "IMM Tescan Clara",
                "IMM FEI Helios",
                "IMM Zeiss Leo",
                "GfE Zeiss Gemini 300",
                "KKS Zeiss Supra 55 VP",
                "MCh FEI Helios",
                "MPIE FEI Helios",
                "MPIE FEI Scios",
                "MPIE FEI Scios",
                "MPIE Zeiss Sigma",
            ]
        case "TEM_DATA":
            metadata_extractors = [
                "Thermo Scientific Velox Software emd",
                "Gatan Microscopy Suite dm3/dm4",
            ]
        case "EBSD_EXP_DATA":
            metadata_extractors = [
                "EDAX TEAM zip",
                "EDAX edaxh5",
                "AZtecCrystal h5iona",
            ]
        case "EBSD-EDS_DATA":
            metadata_extractors = [
                "EDAX TEAM zip",
                "EDAX edaxh5",
                "AZtecCrystal h5iona",
            ]
        case "EDS_DATA":
            metadata_extractors = ["EDAX TEAM zip"]
        case "EBSD_SIM_INTERNAL" | "EBSD_SIM_MASTERPATTERN" | "EBSD_SIM_SCREENPATTERN":
            metadata_extractors = ["EMSOFT_H5"]
        case "CRYS-STRUCT_DATA":
            metadata_extractors = ["VASP", "LAMMPS"]
        case "INTERATOMIC_POTENTIAL_DATA":
            metadata_extractors = ["PACEMAKER"]
    st.selectbox(
        "Choose a metadata extractor",
        metadata_extractors,
        index=None,
        placeholder="Choose an extractor",
        key="extractor",
        disabled=not len(metadata_extractors),
        help=f"Try out [here]({DEMO_METADATA_URL}) first",
    )

    if st.session_state.ds_type == "CRYS-STRUCT_DATA":
        oBis = st.session_state.oBis
        styles = sorted(
            oBis.get_terms(
                oBis.get_property_type("LAMMPS_UNIT_STYLE").vocabulary
            ).df.code.to_list()
        )
        lammps_unit_style = st.selectbox(
            "Choose LAMMPS unit style",
            options=styles,
            index=styles.index("METAL"),
            # index=None,
        )
    else:
        lammps_unit_style = None
    uploaded_files = st.file_uploader(
        "Choose a file",
        accept_multiple_files=True,
        disabled=st.session_state.disable_upload,
        help="If metadata extraction is available, \
            make sure to upload files that can be parsed by the same metadata extractor",
        key=st.session_state.uploader_key,
    )

    s3_upload_allowed = st.session_state.s3_upload_allowed
    s3_upload_configured = st.session_state.s3_upload_ok
    openbis_upload_allowed = st.session_state.openbis_upload_allowed
    if s3_upload_allowed and not s3_upload_configured:
        st.warning("Please set up s3 properly")

    if s3_upload_allowed and s3_upload_configured and openbis_upload_allowed:
        upload_target = st.radio(
            "Choose upload target",
            ["Coscine", "openBIS"],
            captions=[
                "Upload to S3 and register in openBIS (if your project has Coscine Storage)",
                "Upload to openBIS directly",
            ],
            index=0,
            disabled=st.session_state.disable_upload,
        )
        register_msg = "Register data"
    else:
        if openbis_upload_allowed:
            upload_target = "openBIS"
        elif s3_upload_allowed:
            upload_target = "Coscine"
        else:
            upload_target = "Coscine"
        register_msg = f"Register data and upload to {upload_target}"
    register_btn = st.form_submit_button(
        register_msg,
        type="primary",
        disabled=not st.session_state.setup_done or st.session_state.disable_upload,
    )

    if register_btn:
        is_manual_valid = True
        is_name_valid = True

        property_types = (
            st.session_state.oBis.get_dataset_type(st.session_state.ds_type)
            .get_property_assignments()
            .df
        )
        property_types.set_index("code", inplace=True)

        # Validate manually entered metadata

        if manual_entry is not None:
            for _, row in manual_entry.iterrows():
                if row["Value"] is not None and row["Value"] != "":

                    if row["Datatype"] == "CONTROLLEDVOCABULARY":
                        if row["Value"] not in row["Possible Values"]:
                            property_label = row["Field"]
                            value = row["Value"]
                            values = row["Possible Values"]
                            st.error(
                                f"{property_label} value: {value} is not one of {values}!"
                            )
                            is_manual_valid = False
                    if row["Datatype"] == "INTEGER":
                        property_label = row["Field"]
                        value = row["Value"]
                        if not value.isnumeric():
                            st.error(f"{property_label} value: {value} not an integer!")
                            is_manual_valid = False
                    if row["Datatype"] == "REAL":
                        property_label = row["Field"]
                        value = row["Value"]
                        try:
                            float(value)
                        except:
                            st.error(f"{property_label} value: {value} not a decimal!")
                            is_manual_valid = False
        if data_set_name is None or data_set_name == "":
            st.error("Please assign a meaningful name before registering the data")
            is_name_valid = False
        if is_name_valid and is_manual_valid:
            data_set_name = data_set_name.strip()
            if upload_target == "openBIS":
                data_set_name = data_set_name.replace(",", "")
            counter = 0
            permids = []
            if uploaded_files is not None:
                uploaded_files = sorted(uploaded_files, key=lambda x: x.name)
            progress_text = "Upload ongoing. Please wait."
            progress_bar = st.progress(0, text=progress_text)

            for i, uploaded_file in enumerate(uploaded_files, 1):

                placeholder = st.empty()
                progress_bar.progress(i / len(uploaded_files), text=progress_text)
                file_name = uploaded_file.name
                placeholder.write(f"Now process file: {file_name}")

                # store file locally (to operate on for openBIS)

                if upload_target == "openBIS":
                    file_name = file_name.strip()
                    file_name = file_name.replace(",", "")
                    file_name = "".join(file_name.split())
                file_path = os.path.join(st.session_state.temp_dir, file_name)
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                # generate prefix to ensure each file is unique

                username = st.session_state.oBis._get_username()
                dataset_type = st.session_state.ds_type
                time_stamp = datetime.now(timezone.utc)
                time_stamp = time_stamp.strftime("%Y-%m-%dT%H-%M-%S.%f")

                prefix = time_stamp + "_" + dataset_type + "_" + username + "_"
                if st.session_state.prefix not in [None, ""]:
                    prefix = prefix + st.session_state.prefix + "_"
                # extract metadata if available

                properties = {
                    "$name": data_set_name + "_" + str(counter),
                    "comments": st.session_state.data_set_comments,
                }
                if lammps_unit_style is not None:
                    properties["lammps_unit_style"] = lammps_unit_style
                    st.session_state.options["lammps_unit_style"] = (
                        lammps_unit_style.lower()
                    )
                if manual_entry is not None:
                    for _, row in manual_entry.iterrows():
                        if row["Value"] is not None and row["Value"] != "":
                            if row["Datatype"] == "INTEGER":
                                value = int(row["Value"])
                            else:
                                value = row["Value"]
                            properties[row.name.lower()] = value
                metadata_dict = {}

                file_name_fqdn = st.session_state.temp_dir + "/" + file_name

                try:
                    metadata_dict = get_metadata(
                        file_name_fqdn=file_name_fqdn,
                        data_set_type=st.session_state.ds_type,
                        metadata_parser=st.session_state.extractor,
                        options=st.session_state.options,
                    )
                except Exception as e:
                    st.toast(e)
                # Convert decimal to float as required by pybis 1.37.0
                # FIXME Add types to metadata parsers

                for k, v in metadata_dict.items():
                    if (
                        v is not None
                        and property_types.loc[k.upper(), "dataType"] == "REAL"
                    ):
                        metadata_dict[k] = float(v)
                # add metadata to properties

                properties = {**properties, **metadata_dict}

                # metadata extraction

                with st.sidebar:
                    st.subheader(f"Extracted Metadata from {file_name}")
                    st.write(properties)
                # link file to openBIS

                permid = None
                if upload_target == "openBIS":
                    permid = upload_to_openbis(
                        file_name=file_name,
                        prefix=prefix,
                        properties=properties,
                        placeholder=placeholder,
                    )
                else:
                    # retrieve the external data store representation of the bucket

                    dss_code = st.session_state.oBis.get_datastores()["code"][0]
                    permid = link_file(
                        file_name=file_name,
                        prefix=prefix,
                        dss_code=dss_code,
                        properties=properties,
                        placeholder=placeholder,
                    )
                time.sleep(1)
                placeholder.empty()

                # st.write("File uploaded to openBIS with permID: ", permID)

                permids.append(permid)
                counter = counter + 1
            progress_bar.empty()
            if counter > 0 and None not in permids:
                st.success(
                    f"Files added succesfully "
                    "(Click on Submit before uploading new files, "
                    "This will remove the already uploaded files)",
                    icon="✅",
                )
        st.session_state.uploader_key = uuid.uuid4()
