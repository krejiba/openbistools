#!/usr/bin/env python
# -*- coding: utf-8 -*-


"""
Copyright [2025] [Ulrich Kerzel, Khalil Rejiba]

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Multi-page streamlit app used to augment the functionality of openBIS ELN-LIMS

"""
import warnings
import argparse
import streamlit as st
from streamlit import config as st_config
import os
from datetime import datetime
from pybis import Openbis
import pandas as pd
from configparser import ConfigParser
from io import StringIO
import boto3
from botocore.errorfactory import ClientError
from botocore.client import Config
from pybis_tools import check_role, get_full_identifier


OPENBIS_URL = "https://openbis.imm.rwth-aachen.de/openbis/webapp/eln-lims/:8443"
COSCINE_URL = "https://global.datastorage.nrw:443"
# COSCINE_URL = "https://coscine-s3-01.s3.fds.rwth-aachen.de:9021"  # RWTH-RDS-S3
# COSCINE_URL = "https://coscine-nrw-s3-01.s3.fds.nrw:9021" # NRW-RDS-S3


# Define DataSet types to ignore in this tool


FORBIDDEN_DATASET_TYPES = [
    "ELN_PREVIEW",  # From OpenBIS
    "SEQ_FILE",  # From OpenBIS
    "MICROSCOPY_IMG_CONTAINER",  # From OpenBIS
]

# Define Object types to include when uploading using this tool


ALLOWED_OBJECT_TYPES = [
    "EXPERIMENTAL_STEP",
    "SIMULATION_EXP",
    "SIMULATION_ARTEFACT",
    "INTERATOMIC_POTENTIAL",
    "PSEUDOPOTENTIAL",
    "FITTING_DATAFRAME",
    "SEM_EXP",
    "MICRO_MECH_EXP",
    "MECH_EXP",
    "MECH_TEST_PROTOCOL",
    "HEAT_TREATMENT_PROTOCOL",
    "CASTING_PROTOCOL",
    "CUTTING_PROTOCOL",
    "FIB_MILLING_PROTOCOL",
    "ELECTROCHEM_PROTOCOL",
    "THIN_FILM_SYNTHESIS",
    "CALPHAD_DATABASE",
    "PHASE_DIAGRAM",
    "SAMPLE",  # Only structure files
    "PUBLICATION",
    "SOFTWARE",
]

SUBTYPES = {
    "EXPERIMENTAL_STEP": "EXP_TYPE",
    "SIMULATION_EXP": "SIMULATION_TYPE",
    "MICRO_MECH_EXP": "TEST_TYPE",
    "MECH_EXP": "DEFORMATION_MODE",
}

warnings.filterwarnings(action="ignore", category=FutureWarning)

## ============================================================================
## Helper functions
## ============================================================================


def init_session_state(temp_dir: str, spaces: list, desktop: bool):
    # Initialize Streamlit Session State

    SESSION_DEFAULTS = {
        "oBis": None,
        "ds_type_set": set(),
        "openbis_username": "",
        "openbis_password": "",
        "openbis_token": "",
        "openbis_upload_allowed": False,
        "s3_upload_allowed": False,
        "experiments": {},
        "experiments_with_data": {},
        "experiment_name_list": [],
        "obis_dmscode": "",
        "logged_in": False,
        "setup_done": False,
        "disable_upload": True,
        "include_samples": False,
        "s3_clients": dict(),  # Read Clients
        "s3_client": None,  # Write Client
        "s3_bucket_names": dict(),
        "s3_bucket_name": "",
        "s3_upload_ok": False,
        "s3_download_ok": False,
        "temp_dir": "./tmp",
        "options": None,
        "bucket_fill_levels": {},
        "demo_mode": False,
        "spaces": spaces,
        "desktop": desktop,
        "files": None,
    }

    for k, v in SESSION_DEFAULTS.items():
        if k not in st.session_state:
            setattr(st.session_state, k, v)
    st.session_state.temp_dir = temp_dir
    st.session_state.max_size = st_config.get_option("server.maxUploadSize")  # Mb


def openbis_login(openbis_url, verify=True):
    """
    Performs startup tasks (login to OpenBIS and identification of roles and permissions).
    """

    username = None
    try:
        st.session_state.oBis = Openbis(openbis_url, verify_certificates=verify)
        if len(st.session_state.openbis_token):
            st.session_state.oBis.set_token(
                st.session_state.openbis_token,
                save_token=True,
            )
        else:
            st.session_state.oBis.login(
                username=st.session_state.openbis_username.strip(),
                password=st.session_state.openbis_password.strip(),
            )
        username = st.session_state.oBis._get_username()

        # Check if user is allowed to upload to openBIS directly
        # .i.e. all users who have an OBSERVER role in the space IMM
        st.session_state.openbis_upload_allowed = check_role(
            oBis=st.session_state.oBis,
            username=username,
        )

        # Check if user is allowed to upload data to Coscine
        allowed_users = (
            st.session_state.oBis.get_group("COSCINE_UPLOAD").get_members().df
        )
        allowed_users = allowed_users.permId.to_list()
        st.session_state.s3_upload_allowed = username in allowed_users

        st.session_state.logged_in = True
        st.session_state.openbis_username = username
        st.session_state.openbis_password = ""
        st.session_state.openbis_token = st.session_state.oBis.token

    except Exception as e:
        st.error(f"Cannot connect to openBIS {openbis_url}: {e}", icon="🔥")
        st.snow()
        st.stop()


def find_relevant_locations(username, include_samples=True):
    """Fetches all ELN entries the user can link to."""

    # Add spaces corresponding to research projects (+ user's personal space)

    space_list = st.session_state.spaces + [username.upper()]

    # Add spaces in inventory (DEPRECATED)

    space_list += [
        "PUBLICATIONS",
        "EQUIPMENT",
        # "EXPERIMENTS",
        # "SAMPLES",
        # "METHODS",
        # "SIMULATION",
    ]

    # We restrict which objects the user can upload to using this tool

    allowed_object_types = ALLOWED_OBJECT_TYPES

    if not include_samples and "SAMPLE" in allowed_object_types:
        allowed_object_types.remove("SAMPLE")
    spaces = st.session_state.oBis.get_spaces()
    # Adaptive space list

    space_list = [s.code for s in spaces if s.code in space_list]

    # Seperator used in display name for experiments and samples

    sep = "//"

    st.session_state.experiments = {}
    st.session_state.experiments_with_data = {}

    experiments = st.session_state.oBis.get_experiments(
        attrs=["code", "project.code"], props=["$NAME", "NUM_DATASETS"]
    ).df
    experiments["space"] = experiments.identifier.str.split("/").str[1]
    experiments = experiments[experiments.space.isin(space_list)]
    experiments = (
        experiments.sort_values("space")
        .rename(columns={"project.code": "project"})
        .reset_index()
    )

    total = len(experiments)

    progress_bar = st.progress(0)

    for i, exp in experiments.iterrows():
        permid = exp["permId"]
        identifier = exp["identifier"]
        name = exp["$NAME"]
        name = name if name not in (None, "") else exp["code"]
        space = exp["space"]
        project = exp["project"]
        progress_bar.progress(i / total, text=f"{space} - {i+1}/{total}")
        list_item = f"{space}{sep}{project}{sep}{name} ({permid})"
        st.session_state.experiments[list_item] = identifier
        if exp["NUM_DATASETS"]:
            try:
                if int(exp["NUM_DATASETS"]) > 0:
                    st.session_state.experiments_with_data[list_item] = (
                        identifier,
                        None,
                        None,
                    )
            except ValueError:
                # dynamic property pending evaluation - str
                pass

        exp_objects = st.session_state.oBis.get_objects(
            experiment=identifier,
            attrs=["code"],
            props=["$NAME", "NUM_DATASETS"] + list(SUBTYPES.values()),
        ).df
        exp_objects = exp_objects[
            (exp_objects.type.isin(allowed_object_types))
            | (exp_objects.type.str.startswith("PYIRON"))
        ].reset_index()
        for j, exp_obj in exp_objects.iterrows():
            exp_dict = exp.to_dict()
            obj_dict = exp_obj.to_dict()
            obj_type = obj_dict["type"]
            identifier, list_item = get_full_identifier(exp_dict, obj_dict, sep, True)
            st.session_state.experiments[list_item] = identifier
            if exp_obj["NUM_DATASETS"]:
                try:
                    if int(exp_obj["NUM_DATASETS"]) > 0:
                        st.session_state.experiments_with_data[list_item] = (
                            identifier,
                            obj_type,
                            obj_dict.get(SUBTYPES.get(obj_type)),
                        )
                except ValueError:
                    # dynamic property pending evaluation - str
                    pass

    progress_bar.empty()

    exp_list = sorted(st.session_state.experiments.keys())
    st.session_state.experiment_name_list = exp_list

    # Get all dataset types

    ds_types = st.session_state.oBis.get_dataset_types()
    ds_type_set = set(ds_types.df["code"].to_list())
    for ds_type in FORBIDDEN_DATASET_TYPES:
        ds_type_set.discard(ds_type)
    st.session_state.ds_type_set = ds_type_set
    return allowed_object_types


def configure_download_from_coscine():
    """Creates clients to read data from Coscine."""

    # CSV containing information about S3 buckets is stored in an experiment.

    CFG_EXP_LIST = [
        "/PUBLICATIONS/PUBLIC_REPOSITORIES/PUBLICATIONS_COLLECTION",
    ]

    # S3 Configuration files are stored in dummy experiments in OpenBIS.

    experiments = st.session_state.oBis.get_experiments().df.identifier.to_list()
    CFG_EXP_LIST = CFG_EXP_LIST + [
        exp for exp in experiments if exp.endswith("COSCINE_CONFIG")
    ]

    st.session_state.s3_download_ok = False

    for config_expertiment in CFG_EXP_LIST:
        st.session_state.s3_download_ok = True
        datasets = st.session_state.oBis.get_datasets(
            experiment=config_expertiment,
        )
        for ds in datasets:
            fname = ds.file_list[0].split("/")[-1]
            if fname.endswith((".cfg", ".csv")):
                ds.download(
                    destination=st.session_state.temp_dir,
                    create_default_folders=False,
                )
                local_path = st.session_state.temp_dir + "/" + fname
                if fname.endswith(".cfg"):
                    s3_client, bucket_name, dms_code = get_s3client(local_path, True)
                    st.session_state.s3_clients[dms_code] = s3_client
                    st.session_state.s3_bucket_names[dms_code] = bucket_name
                elif fname.endswith(".csv"):
                    levels_df = pd.read_csv(local_path)
                    levels_df["name"] = levels_df["name"] + levels_df["used_gb"].apply(
                        lambda x: f" ({x:} Gb)"
                    )
                    levels_df.set_index("name", inplace=True)
                    st.session_state.bucket_fill_levels = levels_df[
                        "used_percent"
                    ].to_dict()
                else:
                    raise NotImplementedError(f"Unexpected file {ds.permId}: {fname}")


def check_openbis_login_success():
    """Validates whether login to openBIS was successful or not."""
    try:
        username = st.session_state.oBis._get_username()
        return username
    except Exception as e:
        st.error(f"Login to openBIS failed: {e}")
        return None


##
## S3 client
##


def get_s3client(config_file=None, from_path=False, verify=True):
    """Read in the config file and parse the configuration settings.

    Args:
        config (opened file): file-like object
    """
    from urllib.parse import urlparse, urlunparse

    parsed_url = urlparse(COSCINE_URL)
    parser = ConfigParser(
        allow_no_value=True,
        defaults={
            "s3_endpoint_url": urlunparse(
                parsed_url._replace(netloc=parsed_url.hostname)
            ),
            "s3_endpoint_port": parsed_url.port,
        },
    )

    try:
        s3_bucket = st.secrets.get("s3_bucket", "")
    except (FileNotFoundError, KeyError):
        s3_bucket = ""

    # Checks if the client can be instantiated using secrets
    if s3_bucket and config_file is None:
        s3_client = boto3.client(
            service_name="s3",
            endpoint_url=COSCINE_URL,
            aws_access_key_id=st.secrets["s3_access_key"],
            aws_secret_access_key=st.secrets["s3_access_secret"],
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )
        return s3_client, st.secrets["s3_bucket"], st.secrets["dms_code"]

    if config_file:
        if from_path:
            # Open file to access content

            with open(config_file, "r") as fh:
                string_data = fh.read()
        else:
            # Need to convert to string as the file is already opened

            stringio = StringIO(config_file.getvalue().decode("utf-8"))
            string_data = stringio.read()
        parser.read_string(string_data)
    else:
        st.error("Please set-up secrets for demo")
        st.stop()

    s3_endpoint_url = parser.get("s3", "s3_endpoint_url")
    s3_endpoint_port = parser.get("s3", "s3_endpoint_port")
    s3_key = parser.get("s3", "s3_access_key")
    s3_secret = parser.get("s3", "s3_access_secret")
    s3_bucket_name = parser.get("s3", "s3_bucket")

    obis_dmscode = parser.get("openBIS", "dms_code")

    s3_url = s3_endpoint_url + ":" + str(s3_endpoint_port)
    if "datastorage.nrw" in s3_endpoint_url.lower():
        config = Config(signature_version="s3v4", s3={"addressing_style": "virtual"})
    else:
        config = Config(signature_version="s3v4")

    s3_client = boto3.client(
        service_name="s3",
        endpoint_url=s3_url,
        aws_access_key_id=s3_key,
        aws_secret_access_key=s3_secret,
        config=config,
        verify=verify,
    )

    return s3_client, s3_bucket_name, obis_dmscode


def check_read_s3():
    st.session_state.s3_upload_ok = False
    try:
        response = st.session_state.s3_client.list_objects_v2(
            Bucket=st.session_state.s3_bucket_name
        )
        st.session_state.s3_upload_ok = True
    except ClientError as e:
        error_code = e.response["ResponseMetadata"]["HTTPStatusCode"]
        error_message = e.response["Error"]["Message"]
        error_message = f"An error occured when linking the s3 storage: {error_message}"
        if error_code == 403:
            error_message = "Access denied!"
        elif error_code == 404:
            error_message = "Bucket does not exist!"
        return error_message
    else:
        if response["Name"] == st.session_state.s3_bucket_name:
            st.session_state.s3_upload_ok = True
        else:
            return "The s3 crendenials don't match."


def check_write_s3():
    object_key = "test-file.txt"
    data = "This is a test."
    try:
        response_put = st.session_state.s3_client.put_object(
            Bucket=st.session_state.s3_bucket_name,
            Key=object_key,
            Body=data,
        )
        response_delete = st.session_state.s3_client.delete_object(
            Bucket=st.session_state.s3_bucket_name,
            Key=object_key,
        )
        st.session_state.s3_upload_ok = True
    except ClientError as e:
        access_key = st.session_state.s3_client._request_signer._credentials.access_key
        warning_msg = (
            f"You might not be able to upload to Coscine using access key {access_key}"
        )
        st.session_state.s3_upload_ok = False
        return warning_msg


## ============================================================================
## Main Part
## ============================================================================


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--temp_dir",
        type=str,
        required=False,
        default="./tmp",
        help="Path to where the data will be staged (anbd later deleted)",
    )
    parser.add_argument(
        "--openbis_url", type=str, required=False, help="Default openBIS endpoint"
    )
    parser.add_argument(
        "--verify_openbis_cert",
        type=int,
        required=False,
        help="Flag to verify openbis certificates",
        choices=[0, 1],
        default=1,
    )
    parser.add_argument(
        "--coscine_url", type=str, required=False, help="Default Coscine endpoint"
    )
    parser.add_argument(
        "--verify_s3_cert",
        type=int,
        required=False,
        help="Flag to verify s3 certificates",
        choices=[0, 1],
        default=1,
    )
    parser.add_argument(
        "--demo_mode",
        action="store_true",
        help="Switch to demo mode where s3 bucket is configured from secrets",
    )
    parser.add_argument(
        "--spaces",
        nargs="+",
        help="Codes of shared spaces the users can upload data into.",
        default=[
            "CRC1394",
            "TRR188",
            "CRC761",
            "CSC",
            "IMM_SPACE",
            "IMM_NANOMECHANICS",
            "SPP2476",
        ],
    )
    parser.add_argument(
        "--desktop",
        type=int,
        required=False,
        help="Flag for desktop app",
        choices=[0, 1],
        default=0,
    )

    args = parser.parse_args()

    init_session_state(temp_dir=args.temp_dir, spaces=args.spaces, desktop=args.desktop)

    # Workaround for demo

    demo_mode = args.demo_mode
    if not demo_mode:
        demo_mode = os.environ.get("DEMO_MODE", "False").lower() == "true"
    st.session_state.demo_mode = demo_mode

    # Assign which openBIS instance you want to communicate with

    openbis_url = args.openbis_url
    if openbis_url is None:
        try:
            openbis_url = os.environ["OPENBIS_ENDPOINT"]
        except KeyError:
            openbis_url = OPENBIS_URL
    # Page Config

    st.set_page_config(
        page_title="openBIS Companion App - CRC1394",
        page_icon="media/SFB1394_icon.jpg",
        layout="wide",
    )

    # Prompt user to choose next page after succesful login

    st.sidebar.success("Choose what to do  \nafter login is successful")

    # Clean up temporary directory

    if os.path.isdir(st.session_state.temp_dir):
        for file in os.scandir(st.session_state.temp_dir):
            if file.is_file():
                os.unlink(file.path)
    else:
        os.makedirs(st.session_state.temp_dir)
    # Display Welcome section

    st.title("SFB/CRC 1394 openBIS Companion App")
    st.image("media/SFB1394_TitleImage_Cropped.png")
    st.markdown(
        """
        In SFB/CRC 1394, we organise all files in openBIS, however, 
        the files themselves are (typically) stored in an S3-bucket in Coscine.

        This web-app allows users to upload files to openBIS 
        or Coscine and link the data (and metadata, where applicable)
        to the description of an experiment in openBIS.
        """
    )
    st.info(
        """
    If this application substantially supports your research or is extended for new applications, please consider citing the associated publication:  
    Rejiba, K., Lee, S.-H., Gasper, C., Freund, M. S. D., Korte-Kerzel, S., & Kerzel, U. B. (2026).  
    *Towards Defect Phase Diagrams: From Research Data Management to Automated Workflows.*  
    **Advanced Engineering Materials.**  
    https://doi.org/10.1002/adem.202502882
    """
    )

    st.subheader("Log into openBIS and configure access to Coscine")

    placeholder1 = st.empty()

    # Prompt user to login to opemBIS

    with placeholder1.form("form-openbis-login"):
        st.write(
            "You can use the session token from the openBIS ELN-LIMS GUI to login to the companion app "
            ":red[**or**] your username and password."
        )
        col1, col2, col3 = st.columns([0.5, 0.25, 0.25])
        with col1:
            token = st.text_input(
                ":blue[Enter your openBIS session token]",
                placeholder="Go to /Utilities /User Profile",
            )
        with col2:
            username = st.text_input(
                ":violet[Enter your openBIS username]",
            )
        with col3:
            password = st.text_input(
                ":violet[Enter your openBIS password]",
                type="password",
            )

        help_str = "Only relevant for users uploading simulation data.  \n"
        help_str += "Experimental data should be uploaded to experiments.  \n"
        help_str += "Turn on if you want to access structure files."
        include_samples = st.toggle(
            "Are you uploading data to samples?",
            help=help_str,
        )
        if not st.session_state.setup_done:
            st.session_state.include_samples = include_samples
        if include_samples:
            spinner_message = "Trying to locate your samples and experiments"
        else:
            spinner_message = "Trying to locate your experiments"
        login_btn = st.form_submit_button(
            "openBIS Login",
            type="primary",
        )
        if login_btn and (len(token) > 0 or len(username) * len(password)):
            st.session_state.openbis_token = token
            st.session_state.openbis_username = username
            st.session_state.openbis_password = password
            if not st.session_state.logged_in:
                openbis_login(openbis_url, args.verify_openbis_cert == 1)
            username = check_openbis_login_success()
            if username is not None:
                user = st.session_state.oBis.get_user(username)
                first_name = user.firstName
                last_name = user.lastName
                full_name = f"{first_name} {last_name}"
                if full_name is None:
                    full_name = username
                st.success(
                    f"Hello {full_name}, login to openBIS was successful",
                    icon="✅",
                )
            with st.spinner(spinner_message):
                find_relevant_locations(username, include_samples)
            with st.spinner("Configuring download from Coscine"):
                configure_download_from_coscine()
            if st.session_state.logged_in and not st.session_state.s3_upload_allowed:
                st.session_state.setup_done = True
            placeholder1.empty()
    placeholder2 = st.empty()

    # Attempt to set up bucket from secrets

    if st.session_state.demo_mode and st.session_state.logged_in:
        client, bucket, dmscode = get_s3client()
        st.session_state.s3_client = client
        st.session_state.s3_bucket_name = bucket
        st.session_state.obis_dmscode = dmscode
        st.session_state.setup_done = True
        st.session_state.s3_upload_ok = True

    # Prompt user to upload credentials needed for upload to Coscine

    warning_msg, error_msg = None, None

    if st.session_state.s3_upload_allowed and not st.session_state.setup_done:
        with placeholder2.form("Form_S3_credentials"):
            st.write("Enter S3 storage credentials (to upload to Coscine)")
            st.write(
                "If you are not uploading files, you can click on *Configure S3* without uploading a config file."
            )
            help_text = ""
            with open("s3_credentials_demo.cfg", "r") as f:
                help_text = f.read().replace("#", "\#").replace("\n", "  \n")
            s3_credentials = st.file_uploader(
                "Choose a file",
                accept_multiple_files=False,
                type=["cfg"],
                help=help_text,
            )
            config_btn = st.form_submit_button("Configure S3", type="primary")
            if config_btn:
                if s3_credentials:
                    verify_s3 = args.verify_s3_cert == 1
                    client, bucket, dmscode = get_s3client(
                        s3_credentials,
                        from_path=False,
                        verify=verify_s3,
                    )
                else:
                    dmscode = next(iter(st.session_state.s3_clients))
                    client = st.session_state.s3_clients[dmscode]
                    bucket = st.session_state.s3_bucket_names[dmscode]

                placeholder1.empty()

                st.session_state.s3_client = client
                st.session_state.s3_bucket_name = bucket
                st.session_state.obis_dmscode = dmscode

                # Sanity checks on the upload client
                with st.spinner("Checking S3 ..."):
                    error_msg = check_read_s3()
                    warning_msg = check_write_s3()
                if error_msg is not None:
                    st.session_state.setup_done = False
                else:
                    st.session_state.setup_done = True

                placeholder2.empty()

    if st.session_state.setup_done:
        placeholder1.empty()
        placeholder2.empty()
        if st.session_state.s3_upload_ok:
            bucket = st.session_state.s3_bucket_name
            dms_code = st.session_state.obis_dmscode
            st.success(
                f"S3 storage **{dms_code}** found, bucket name: **{bucket}**",
                icon="✅",
            )
        elif warning_msg is not None:
            st.warning(warning_msg)

        st.write("Logged into openBIS: ", st.session_state.logged_in)
        st.write("openBIS Upload OK: ", st.session_state.openbis_upload_allowed)
        st.write("Coscine Upload OK: ", st.session_state.s3_upload_ok)
        st.write("Coscine Download OK: ", st.session_state.s3_download_ok)
        st.write("You can now either upload (link) or download (show) data !")

        if len(st.session_state.bucket_fill_levels):
            st.sidebar.header("S3 Buckets")
            buckets = list(st.session_state.bucket_fill_levels.items())
            num_columns = 2
            columns = st.sidebar.columns(num_columns)

            for index, (bucket_name, fill_level) in enumerate(buckets):
                col_index = index % num_columns
                with columns[col_index]:
                    st.text(bucket_name)
                    st.progress(fill_level / 100)

                if col_index == num_columns - 1:
                    columns = st.sidebar.columns(num_columns)
    else:
        if error_msg:
            st.error(f"Please provide a valid s3 config file: {error_msg}")

    # Generate Personal Access Token for scripts / uploading large files
    if st.session_state.setup_done:
        usr = st.session_state.oBis._get_username()
        user = st.session_state.oBis.get_user(usr, only_data=True)
        firstname = user["firstName"].upper().replace("-", "")
        lastname = user["lastName"].upper().replace("-", "")
        if st.button("Create Personal Access Token"):
            try:
                pat = st.session_state.oBis.get_or_create_personal_access_token(
                    sessionName=f"{firstname + lastname}_{datetime.now().isoformat()[:7]}",
                )
                st.markdown(
                    f"""
                **Your Personal Access Token:**  
                `{pat.permId}`

                **Valid until:**  
                {pat.validToDate}
                """
                )
            except Exception as e:
                st.warning(e)


if __name__ == "__main__":
    main()
