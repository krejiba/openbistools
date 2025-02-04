#!/usr/bin/env python
# -*- coding: utf-8 -*-


"""
Copyright [2024] [Ulrich Kerzel, Khalil Rejiba]

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Multi-page streamlit app used to upload/download data

"""
import warnings
import argparse
import streamlit as st
from streamlit import config as st_config
import os
import time
from pybis import Openbis
import pandas as pd
from configparser import ConfigParser
from io import StringIO
import boto3
from botocore.errorfactory import ClientError
from pybis_tools import check_role, get_full_identifier

OPENBIS_URL = "https://openbis.imm.rwth-aachen.de/openbis/webapp/eln-lims/:8443"
COSCINE_URL = "https://coscine-s3-01.s3.fds.rwth-aachen.de"
COSCINE_PORT = "9021"

# Define DataSet types to ignore in this tool

FORBIDDEN_DATASET_TYPES = [
    "ELN_PREVIEW",  # From OpenBIS
    "SEQ_FILE",  # From OpenBIS
    "MICROSCOPY_IMG_CONTAINER",  # From OpenBIS
    "SE",  # Custom but no longer used
]


# Define Object types to include when uploading using this tool

ALLOWED_OBJECT_TYPES = [
    "EXPERIMENTAL_STEP",
    "SIMULATION_EXP",
    "SIMULATION_ARTEFACT",
    "SEM_EXP",
    "SAMPLE",
    "EBSD_SIM",
    "TENSILE_EXPERIMENT",
    "TENSILE_TEST_PROTOCOL",
    "CUTTING_PROTOCOL",
    "FIB_MILLING_PROTOCOL",
    "MICRO_MECH_EXP",
]

warnings.filterwarnings(action='ignore', category=FutureWarning)


## ============================================================================
## Helper functions
## ============================================================================

def init_session_state(temp_dir: str, demo_mode=False):
    # Initialize Streamlit Session State
    SESSION_DEFAULTS = {
        "oBis": None,
        "ds_type_set": set(),
        "openbis_username": "",
        "openbis_upload_allowed": False,
        "s3_upload_allowed": False,
        # 'obis_token': '',
        "experiments": {},
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
        "is_crc": False,
        "temp_dir": "./tmp",
    }

    for k, v in SESSION_DEFAULTS.items():
        if k not in st.session_state:
            setattr(st.session_state, k, v)

    st.session_state.temp_dir = temp_dir
    st.session_state.max_size = st_config.get_option("server.maxUploadSize") # Mb
    st.session_state.demo_mode = demo_mode


def openbis_login():
    """
    Performs startup tasks (login to OpenBIS and identification of roles and permissions).
    """

    username = None
    try:
        st.session_state.oBis = Openbis(OPENBIS_URL, verify_certificates=True)
        st.session_state.oBis.set_token(
            st.session_state.obis_token,
            save_token=True,
        )
        username = st.session_state.oBis._get_username()

        st.session_state.logged_in = True
        st.session_state.openbis_username = username
    except Exception as e:
        st.error(f"Cannot connect to openBIS: {e}", icon="🔥")
        st.snow()
        st.stop()
    # Check if user is allowed to upload to openBIS directly
    # .i.e. all users who have an OBSERVER role in the space IMM

    st.session_state.openbis_upload_allowed = check_role(
        oBis=st.session_state.oBis,
        username=st.session_state.openbis_username,
    )

    # Check if user is allowed to upload data to Coscine
    # .i.e. all users who have a USER role (or higher) in one of the projects

    PUBLIC_CRC_PROJECTS = ["CRC1394_DEMO", "CRC1394_COSCINE"]
    person = st.session_state.oBis.get_person(username)
    roles = person.get_roles().df  # Roles excluding inherited roles from group

    # Identify roles inherited from group

    roles_group = st.session_state.oBis.get_groups().df
    roles_group = roles_group[roles_group.users.str.contains(username)]
    roles_group = roles_group.tail(1)

    # Add roles inherited from group

    if len(roles_group):
        group_code = roles_group.code.item()
        group = st.session_state.oBis.get_group(group_code)
        roles_group = group.get_roles().df
        roles = pd.concat([roles, roles_group], axis=0)
    # CRC Membership test (We exclude OBSERVER roles)

    is_crc = False
    roles = roles[roles.role.isin(["USER", "POWER_USER", "ADMIN"])]
    for project_code in roles.project.unique():
        if (
            project_code.startswith("CRC1394_")
            and project_code not in PUBLIC_CRC_PROJECTS
        ):
            is_crc = True
            break
    st.session_state.is_crc = is_crc
    st.session_state.s3_upload_allowed = is_crc


def find_relevant_locations(username, include_samples=True):
    """Fetches all ELN entries the user can link to."""

    # Add spaces corresponding to research projects (+ user's personal space)

    space_list = [
        username.upper(),
        "CRC1394",
        "TRR188",
        "CRC761",
        "CSC",
        "IMM_SPACE",
        "IMM_NANOMECHANICS",
    ]
    # Add spaces in inventory (DEPRECATED)

    space_list += [
        "EXPERIMENTS",
        "SAMPLES",
        "METHODS",
        "SIMULATION",
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

    for space_id, space_name in enumerate(space_list, 1):
        space = st.session_state.oBis.get_space(space_name)
        experiments = space.get_experiments()

        progress_bar = st.progress(0, text=f"{space_id}/{len(space_list)}")

        for i, exp in enumerate(experiments, 1):
            progress_bar.progress(i / len(experiments), text=f"{space_id}/{len(space_list)}")

            # We know this is either an Experiment or a Collection

            name = exp.p.get("$name") if exp.p.get("$name") is not None else exp.code
            list_item = exp.project.code + sep + name + " (%s) " % exp.permId
            list_item = space_name + sep + list_item
            
            st.session_state.experiments[list_item] = exp.identifier

            exp_objects = exp.get_objects()
            for exp_obj in exp_objects:
                if exp_obj.type in allowed_object_types:
                    identifier, list_item = get_full_identifier(exp, exp_obj, sep, True)
                    list_item = space_name + sep + list_item
                    st.session_state.experiments[list_item] = identifier

        progress_bar.empty()
    exp_list = sorted(st.session_state.experiments.keys())
    exp_list = list(exp_list)
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

    # Configuration files are stored in an experiment in OpenBIS.

    CFG_EXP_LIST = [
        "/CRC1394/CRC1394_COSCINE/CRC1394_COSCINE_CONFIG",
        "/TRR188/TRR188_COSCINE/TRR188_COSCINE_CONFIG",
    ]
    
    st.session_state.s3_download_ok = False

    for config_expertiment in CFG_EXP_LIST:
        if config_expertiment in st.session_state.experiments.values():
            st.session_state.s3_download_ok = True
            datasets = st.session_state.oBis.get_datasets(
                experiment=config_expertiment,
            )
            for ds in datasets:
                fname = ds.file_list[0].split("/")[-1]
                ds.download(
                    destination=st.session_state.temp_dir,
                    create_default_folders=False,
                )
                local_path = st.session_state.temp_dir + "/" + fname

                s3client, bn, dmscode = get_s3client(local_path, True)
                st.session_state.s3_clients[dmscode] = s3client
                st.session_state.s3_bucket_names[dmscode] = bn


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


def get_s3client(config_file=None, from_path=False):
    """Read in the config file and parse the configuration settings.

    Args:
        config (opened file): file-like object
    """
    parser = ConfigParser(
        allow_no_value=True,
        defaults={
            "s3_endpoint_url": COSCINE_URL,
            "s3_endpoint_port": COSCINE_PORT,
        },
    )

    if config_file is None:
        try:
            s3_client = boto3.client(
            service_name="s3",
            endpoint_url=f'{COSCINE_URL}:{COSCINE_PORT}',
            aws_access_key_id=st.secrets['s3_access_key'],
            aws_secret_access_key=st.secrets['s3_access_secret']
            )
            return s3_client, st.secrets['s3_bucket'], 'S3_NFDI_DEMO_01'
        except FileNotFoundError:
            return None, "", ""
    elif from_path:
        # Open file to access content

        with open(config_file, "r") as fh:
            string_data = fh.read()
    else:
        # Need to convert to string as the file is already opened

        stringio = StringIO(config_file.getvalue().decode("utf-8"))
        string_data = stringio.read()
    parser.read_string(string_data)

    s3_endpoint_url = parser.get("s3", "s3_endpoint_url")
    s3_endpoint_port = parser.get("s3", "s3_endpoint_port")
    s3_key = parser.get("s3", "s3_access_key")
    s3_secret = parser.get("s3", "s3_access_secret")
    s3_bucket_name = parser.get("s3", "s3_bucket")

    obis_dmscode = parser.get("openBIS", "dms_code")

    s3_url = s3_endpoint_url + ":" + str(s3_endpoint_port)

    s3_client = boto3.client(
        service_name="s3",
        endpoint_url=s3_url,
        aws_access_key_id=s3_key,
        aws_secret_access_key=s3_secret,
    )

    return s3_client, s3_bucket_name, obis_dmscode


def check_s3():
    try:
        response = st.session_state.s3_client.list_objects_v2(
            Bucket=st.session_state.s3_bucket_name
        )
    except ClientError as e:
        st.write(e.response)
        error_code = e.response["Error"]["Code"]
        if error_code == "403":
            st.error("Access denied!", icon="🔥")
        elif error_code == "SignatureDoesNotMatch":
            st.error("Access denied!", icon="🔥")
        elif error_code == "404":
            st.error("Bucket does not exist!", icon="🔥")
        st.session_state.s3_upload_ok = False
        st.stop()
    else:
        if response["Name"] == st.session_state.s3_bucket_name:
            st.session_state.s3_upload_ok = True
            return True


## ============================================================================
## Main Part
## ============================================================================


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--temp_dir", type=str, required=False, default="./tmp",
        help='Path to where the data will be staged (and later deleted)'
    )
    parser.add_argument(
        "--demo_mode", type=bool, required=False, default=False,
        help='Switch to demo_mode'
    )
    args = parser.parse_args()
    init_session_state(temp_dir=args.temp_dir, demo_mode=args.demo_mode)

    # Page Config

    st.set_page_config(
        page_title="Web Tool to link and upload data to openBIS",
        page_icon="media/SFB1394_icon.jpg",
        layout="wide",
    )

    # Prompt user to choose next page after succesful login

    st.sidebar.success("Choose what to do  \nafter login is successful")

    # Clean up temporary directory
    if os.path.isdir(st.session_state.temp_dir):
        for file in os.scandir(st.session_state.temp_dir):
            if file.is_file:
                os.unlink(file.path)
    else:
        os.makedirs(st.session_state.temp_dir)
    # Display Welcome section

    st.title("SFB/CRC 1394 openBIS Linked Files")
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

    st.subheader("Log into openBIS and configure access to Coscine")

    placeholder1 = st.empty()

    # Prompt user to login to opemBIS

    with placeholder1.form("Form_oBis_Login"):
        st.write("Enter openBIS session token")
        token = st.text_input(
            "Enter your openBIS session token",
            label_visibility="collapsed",
            placeholder="Go to /Utilities /User Profile",
        )
        include_samples = st.toggle(
            "Are you uploading data to samples?",
            help="Only relevant for users uploading simulation data",
        )
        st.session_state.include_samples = include_samples
        if include_samples:
            spinner_message = "Trying to locate your samples and experiments"
        else:
            spinner_message = "Trying to locate your experiments"
        login_btn = st.form_submit_button(
            "openBIS Login",
            type="primary",
        )
        if login_btn and len(token) > 0:
            st.session_state.obis_token = token
            if not st.session_state.logged_in:
                openbis_login()
            username = check_openbis_login_success()
            if username is not None:
                st.success(
                    f"Hello {username}, login to openBIS was successful",
                    icon="✅",
                )
            with st.spinner(spinner_message):
                find_relevant_locations(username, include_samples)
            with st.spinner("Configuring download from Coscine"):
                configure_download_from_coscine()
            if st.session_state.logged_in and not st.session_state.is_crc:
                st.session_state.setup_done = True
            placeholder1.empty()
    placeholder2 = st.empty()

    # Prompt user to upload credentials needed for upload to Coscine

    if st.session_state.demo_mode and not st.session_state.setup_done:
        if not st.session_state.s3_client:
            client, bucket, dmscode = get_s3client()
            st.session_state.s3_client = client
            st.session_state.s3_bucket_name = bucket
            st.session_state.obis_dmscode = dmscode
        response = check_s3()
        st.session_state.setup_done = True
    elif st.session_state.is_crc and not st.session_state.setup_done:
        with placeholder2.form("Form_S3_credentials"):
            st.write("Enter S3 storage credentials (to upload to Coscine)")
            s3_credentials = st.file_uploader(
                "Choose a file",
                accept_multiple_files=False,
                label_visibility="collapsed",
                type=["cfg"],
            )
            config_btn = st.form_submit_button("Configure S3", type="primary")
            if config_btn:
                placeholder1.empty()
                placeholder2.empty()
                if not st.session_state.s3_client:
                    client, bucket, dmscode = get_s3client(s3_credentials)
                    st.session_state.s3_client = client
                    st.session_state.s3_bucket_name = bucket
                    st.session_state.obis_dmscode = dmscode
                response = check_s3()
                st.session_state.setup_done = True
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
        st.write("Logged into openBIS: ", st.session_state.logged_in)
        st.write("openBIS Upload OK: ", st.session_state.openbis_upload_allowed)
        st.write("Coscine Upload OK: ", st.session_state.s3_upload_ok)
        st.write("Coscine Download OK: ", st.session_state.s3_download_ok)
        st.write("You can now either upload (link) or download (show) data !")


if __name__ == "__main__":
    main()
