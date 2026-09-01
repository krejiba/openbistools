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


Register external data in openBIS using the linked-data functionality.

Note:
The S3 protocol is not POSIX compliant, this means that an S3 storage does not behave like a filesystem
like we are used to from Linux, Windows or Macintosh computers. One particular consequence is that directories do not exist on S3 storage spaces.
Some S3 implementations do mimic the behaviour of directories. However, since the ITC may change the S3 storage system at any time,
we do not want to rely on a particular implementation.
Hence we use the S3 storage (as intended) as an object store, i.e. all data go into the same bucket (without sub-structure)

The file is copied to an external datastore (assuming S3 protocol), and then registered in openBIS as linkedData.
If the option --link_only is given, the file is only registered in openBIS, assuming that the file is moved to the external datastore manually.

Note: At the moment, the coscine implementation of S3 is only compatible with the BOTO3 client from Amazon.

"""

# python package to interact with openBIS
# see https://pypi.org/project/PyBIS/

from pybis import Openbis
import sys
import os
from pathlib import Path
import logging
import warnings
import argparse
import ast
from datetime import datetime, timezone
from decimal import Decimal

# configuration file

from configparser import ConfigParser


# all OpenBIS / PyBIS helper code we need to register the file

from pybis_tools import get_dms_info, register_file, get_file_metadata  # LINK
from pybis_tools import check_role, upload_data  # PHYSICAL

# S3 related tools

from s3_tools import get_s3_client, s3_file_upload

# Parser mapping

from data_handling_tools import get_metadata

# List of supported parsers

PARSERS = [
    "IMM_TescanClara",
    "IMM_TescanClaraSharkSEM",
    "IMM_FEIHelios",
    "IMM_ZeissLeo",
    "GFE_ZeissGemini",
    "KKS_ZeissSupra",
    "MPIE_ZeissSigma",
    "MPIE_ZeissMerlin",
    "VELOX_EMD",
    "GMS_DM",
    "EDAX_ZIP",
    "EDAXH5",
    "AZTECCRYSTAL",
    "LAMMPS",
    "VASP",
    "EMSOFT_H5",
    "PACEMAKER",
]

OPENBIS_URL = "https://openbis.imm.rwth-aachen.de/:8443"

EXPECTED_DICT_FORMAT = "{'key1':'value1','key2':value2}"
EXPECTED_DICT_FORMAT = f'"{EXPECTED_DICT_FORMAT}"'


def parse_options_dict(string: str) -> dict:
    try:
        options_dict = ast.literal_eval(string)
        if not isinstance(options_dict, dict):
            try:
                options_string = options_dict[1:-1]  # Remove curly brackets
                options_list = options_string.split(",")
                parsed_dict = {}
                for kv in options_list:
                    key, value = kv.split(":", 1)
                    parsed_dict[ast.literal_eval(key.strip())] = ast.literal_eval(
                        value.strip()
                    )
                options_dict = parsed_dict
            except:
                raise ValueError(
                    f"`{string}` was not parsed into a dictionary correctly."
                )
        return options_dict
    except (ValueError, SyntaxError):
        raise argparse.ArgumentTypeError(
            f"Invalid dictionary format: {options_dict} {type(options_dict)} {EXPECTED_DICT_FORMAT}"
        )


class ListDatasetTypesAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):

        warnings.filterwarnings(action="ignore", category=FutureWarning)
        logging.basicConfig(level=logging.INFO)
        token = namespace.openbis_token
        if token is None:
            try:
                token = os.environ["OPENBIS_TOKEN"]
            except KeyError as e:
                logging.critical("Environment variable OPENBIS_TOKEN not found.")
                sys.exit(0)
        msg = f"Displaying dataSet types available in the openBIS instance:\n{OPENBIS_URL}\n"
        openbis_client = Openbis(url=OPENBIS_URL, token=token, verify_certificates=True)

        ds_types = [
            f"{ds_type.code:<30}: {ds_type.description}"
            for ds_type in openbis_client.get_dataset_types()
            if ds_type.code != "ELN_PREVIEW"
        ]
        ds_types = sorted(ds_types, key=lambda x: x.split(":"[0]))
        available = "\n".join(ds_types)
        msg += f"Available dataSet types are:\n{available}"
        logging.info(msg)
        sys.exit(0)


###############################################################################
##
## main program
##
###############################################################################

if __name__ == "__main__":

    warnings.filterwarnings(action="ignore", category=FutureWarning)

    #
    # command line arguments
    #

    parser = argparse.ArgumentParser(
        description="Register (and upload) files from local file system",
        epilog="Run python registerLinkData.py (-token TOKEN) --list_dataset_types to display available dataSet types. ",
    )

    # Option to display available dataSet types

    parser.add_argument("--list_dataset_types", action=ListDatasetTypesAction, nargs=0)

    # Flag for debugging

    parser.add_argument("--debug", action="store_true")

    # S3 bucket information from config file

    parser.add_argument(
        "-config",
        "--config_file",
        help="Full path to the ConfigParser config file",
        type=str,
    )
    parser.add_argument(
        "--config_section_openbis",
        help="Name of the section with openbis details",
        type=str,
        default="openBIS",
    )
    parser.add_argument(
        "--config_section_s3",
        help="Name of the section with S3 details",
        type=str,
        default="s3",
    )

    # S3 bucket information

    parser.add_argument(
        "--s3_endpoint_url", help="URL of the S3 access endpoint", type=str
    )
    parser.add_argument(
        "--s3_endpoint_port",
        help="port of the S3 access endpoint",
        type=int,
    )
    parser.add_argument(
        "-s3_key",
        "--s3_access_key",
        help="ID of the access key (write access)",
        type=str,
    )
    parser.add_argument(
        "-s3_secret",
        "--s3_access_secret",
        help="Password for the access key (write access)",
        type=str,
    )
    parser.add_argument(
        "-bucket", "--s3_bucket", help="S3 bucket to write the file to", type=str
    )

    # openBIS
    # note the trailing '/' in the URL for the openBIS server

    parser.add_argument(
        "-obis", "--openbis_server", help="URL of the openBIS server", type=str
    )
    parser.add_argument(
        "-port", "--openbis_port", help="Port of the openBIS server", type=int
    )
    parser.add_argument(
        "-token", "--openbis_token", help="PAT or session token", type=str
    )
    parser.add_argument(
        "--dss_code", help="Code of the openBIS Data Storage Server (DSS)", type=str
    )
    parser.add_argument(
        "--dms_code", help="Code of the external Data Storage Server (DMS)", type=str
    )

    parser.add_argument(
        "-e",
        "--entry",
        help="Identifier or PermID of the ELN entry to which the file is linked to.",
        type=str,
        required=True,
    )
    parser.add_argument(
        "-t",
        "--dataset_type",
        help="openBIS data type of the file",
        type=str,
        required=True,
    )
    parser.add_argument(
        "-f",
        "--file",
        help="File that should be linked (directory is also supported)",
        type=str,
        required=True,
    )
    # not sure how data_set_code works, autogenerate a new one for now
    # parser.add_argument('--data_set_code', help='Code of the dataset to which the file is linked to, if not given, a new one will be autogenerated.', type=str)

    parser.add_argument(
        "--parent_ids",
        help="Parent datasets for the linked data, multiple parents allowed (white space separated)",
        nargs="+",
        type=str,
    )
    parser.add_argument(
        "-n",
        "--name",
        help="Name of the linked dataset in openBIS",
        type=str,
        required=True,
    )
    parser.add_argument(
        "-c",
        "--comments",
        help="Comments to add to the datasets",
        type=str,
        required=False,
    )
    parser.add_argument(
        "-m",
        "--mode",
        help="Upload mode: to S3, only register the link (assuming the file is already stored elsewhere), to openBIS (if permitted)",
        type=str,
        choices=["s3", "openbis", "link_only"],
        default="s3",
    )
    parser.add_argument(
        "-prefix",
        "--file_prefix",
        help="Add this prefix to all uploaded files to make them unique in S3",
        type=str,
    )

    # metadata extraction helpers - only use the ones we have coded so far

    parser.add_argument(
        "-parser",
        "--metadata_parser",
        help="Name of the metadata parser to be used on specific dataset types",
        type=str,
        choices=PARSERS,
    )

    parser.add_argument(
        "-options",
        "--parser_options",
        help=f"Dictionary argument in the format: {EXPECTED_DICT_FORMAT}",
        type=parse_options_dict,
    )

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    ##
    ## initialise arguments that can be taken from the config file to None
    ## either use values from config file or command lines
    ##

    obis_server_url = ":".join(OPENBIS_URL.split(":")[:2])
    obis_server_port = OPENBIS_URL.split(":")[2]
    dss_code = None
    dms_code = None

    s3_key = None
    s3_secret = None
    s3_bucket = None
    s3_url = None

    ##
    ## check if a config file is given and read parameters from config file
    ##

    config_file = args.config_file
    if config_file is None:
        logging.info("No configuration file provided, use arguments from command line")
    else:
        logging.info("Use settings from config file: {}".format(config_file))
        config = ConfigParser(
            allow_no_value=True,
            defaults={
                "openbis_server": ":".join(OPENBIS_URL.split(":")[:2]),
                "openbis_port": OPENBIS_URL.split(":")[2],
            },
        )
        config.read(args.config_file)

        obis_server_url = config.get(args.config_section_openbis, "openbis_server")
        obis_server_port = config.get(args.config_section_openbis, "openbis_port")
        dms_code = config.get(args.config_section_openbis, "dms_code")

        s3_endpoint_url = config.get(args.config_section_s3, "s3_endpoint_url")
        s3_endpoint_port = config.get(args.config_section_s3, "s3_endpoint_port")
        s3_key = config.get(args.config_section_s3, "s3_access_key")
        s3_secret = config.get(args.config_section_s3, "s3_access_secret")
        s3_bucket = config.get(args.config_section_s3, "s3_bucket")
    ##
    ## overwrite with the command line arguments, if any
    ##

    if args.openbis_server is not None:
        obis_server_url = args.openbis_server
    # openBIS server URL needs to end with a trailing '/'

    if not obis_server_url.endswith("/"):
        obis_server_url = obis_server_url + "/"
    if args.openbis_port is not None:
        obis_server_port = args.openbis_port
    obis_url = obis_server_url + ":" + str(obis_server_port)

    if args.dss_code is not None:
        dss_code = args.dss_code
    if args.mode != "openbis":
        if args.dms_code is not None:
            if dms_code is not None:
                assert dms_code == args.dms_code, "DMS code does not match!"
            dms_code = args.dms_code
        if args.s3_endpoint_url is not None:
            s3_endpoint_url = args.s3_endpoint_url
        if args.s3_endpoint_port is not None:
            s3_endpoint_port = args.s3_endpoint_port
        s3_url = s3_endpoint_url + ":" + str(s3_endpoint_port)

        if args.s3_access_key is not None:
            if s3_key is not None:
                assert s3_key == args.s3_access_key, "S3 key does not match!"
            s3_key = args.s3_access_key
        if args.s3_access_secret is not None:
            if s3_secret is not None:
                assert s3_secret == args.s3_access_secret, "S3 secret does not match!"
            s3_secret = args.s3_access_secret
        if args.s3_bucket is not None:
            if s3_bucket is not None:
                assert s3_bucket == args.s3_bucket, "S3 bucket does not match!"
            s3_bucket = args.s3_bucket
        # Sanity check for RWTH-RDS-S3
        # DataStorage.nrw (S3) keys do NOT have the prefix
        # assert s3_key.startswith("write_"), "Coscine S3 Key not for writing!" :
    ##
    ## read remaining command line arguments
    ##

    # always generate a new one for now.

    data_set_code = None

    if args.parent_ids is None:
        parent_ids = []
    else:
        parent_ids = args.parent_ids
    entry_identifier = args.entry
    data_set_type = args.dataset_type
    file_name_fqdn = args.file
    data_set_name = args.name
    comments = args.comments
    metadata_parser = args.metadata_parser
    parser_options = args.parser_options
    mode = args.mode

    logging.info("Will connect to openBIS server at URL: {}".format(obis_url))
    logging.debug("openBIS external data management system code: {}".format(dms_code))
    logging.debug("Name of the ELN entry to link file to: {}".format(entry_identifier))
    logging.debug("openBIS data type: {}".format(data_set_type))
    logging.debug("File (with path) to be linked: {}".format(file_name_fqdn))
    logging.debug("Data Set Code: {}".format(data_set_code))
    logging.debug("Parent IDs: {}".format(parent_ids))
    logging.debug("Name of the linked data in openBIS: {}".format(data_set_name))
    logging.debug("Metadata parser: {}".format(metadata_parser))

    logging.info("S3 endpoint URL and Port: {}".format(s3_url))
    logging.info("S3 bucket: {}".format(s3_bucket))

    ##
    ## check the openBIS access token
    ##

    logging.debug("Obtain openBIS access token")
    access_token = None

    # check environment variable OPENBIS_TOKEN

    if args.openbis_token is not None:
        access_token = args.openbis_token
    else:
        try:
            access_token = os.environ["OPENBIS_TOKEN"]
        except KeyError as e:
            logging.critical(
                "No token provided and environment variable OPENBIS_TOKEN not found"
            )
            logging.critical("Abort")
            sys.exit(0)
    logging.debug("Attempt connection to openBIS server")
    try:
        openbis_client = Openbis(
            url=obis_url, token=access_token, verify_certificates=True
        )
    except Exception as e:
        logging.critical("Cannot connect to openBIS server, error message:")
        logging.critical(e)
        logging.info(
            "If you are using a personal access token make sure to include `$pat-`"
        )
        logging.critical("Abort")
        sys.exit(0)
    logging.debug("Connection to openBIS server established.")

    ds_types = [ds_type.code for ds_type in openbis_client.get_dataset_types()]
    ds_types = sorted(ds_types)
    available = ", ".join(ds_types)
    msg = f"Available dataSet types are {available}"
    assert data_set_type in ds_types, msg

    # we need the DMS code so that OpenBIS knows which external data store the file is linked to

    if dms_code is None and mode != "openbis":
        logging.critical("No DMS Code specified, please provide one.")
        logging.critical("Abort")
        sys.exit(0)
    # check that either object or experiment is given

    try:
        object_identifier = None
        experiment_identifier = openbis_client.get_experiment(
            entry_identifier
        ).identifier
    except Exception:
        try:
            obj = openbis_client.get_object(entry_identifier)
            object_identifier = obj.identifier
            experiment_identifier = obj.experiment.identifier
        except Exception:
            logging.critical(
                "Please provide an identifier of the object or the experiment you want to link your data to"
            )
            logging.critical("Abort")
            sys.exit(0)
    # get username

    openbis_username = openbis_client._get_username()
    openbis_username = openbis_username.replace("$pat-", "")

    # check upload mode

    if (
        mode == "openbis"
        and check_role(oBis=openbis_client, username=openbis_username) == False
    ):
        mode = "s3"
    logging.info("Mode: {}".format(mode))

    #
    # generate a prefix to make files unique in the S3 object store
    # (remember: no directories / hierarchies)
    #

    time_stamp = datetime.now(timezone.utc)
    time_stamp = time_stamp.strftime("%Y-%m-%dT%H-%M-%S.%f")

    prefix = time_stamp + "_" + data_set_type + "_" + openbis_username + "_"
    if args.file_prefix is not None:
        prefix = prefix + args.file_prefix + "_"
    logging.debug("openBIS username: {}".format(openbis_username))
    logging.debug("timestamp: {}".format(time_stamp))
    logging.info("Prefix for all files: {}".format(prefix))

    # retrieve information about Data Storage Server (DSS)
    # if none specified, take the first one in the list from openBIS (normally, we only have one)

    if dss_code is None:
        dss_code = openbis_client.get_datastores()["code"][0]
        logging.info(
            "No OpenBIS DSS Code specified, take first one from server: {}".format(
                dss_code
            )
        )
    logging.debug("openBIS DSS code: {}".format(dss_code))

    #
    # even if we only want to link the file, we still need to extract some metadata from it,
    # at the minimum, the hash and filesize (in order to identify it)
    # but mostly all metadata is associated with a given file type
    #

    file_name_fqdn = Path(file_name_fqdn)

    if not file_name_fqdn.exists():
        logging.critical("Data to be linked not found: Path {} does NOT exist.")
        logging.critical("Abort")
        sys.exit(0)
    if file_name_fqdn.is_file():
        logging.debug("One file provided.")
        files = [file_name_fqdn]
    else:
        logging.debug("Directory provided.")
        logging.debug("Make sure all the files are parsable by the same parser.")
        files = list(file_name_fqdn.glob("*"))
    # Get property types for chosen dataset type

    property_types = (
        openbis_client.get_dataset_type(data_set_type).get_property_assignments().df
    )
    property_types.set_index("code", inplace=True)

    counter = 0

    for file_name_fqdn in files:
        file_name = file_name_fqdn.name
        file_name = prefix + file_name
        logging.info("Filename to be linked: {}".format(file_name))
        logging.info("Filename including prefix: {}".format(file_name))

        if prefix != "":
            destination = file_name_fqdn.parent / file_name
            destination.write_bytes(
                file_name_fqdn.read_bytes()
            )  # Copy under a new name
            file_name_fqdn = destination
        if mode != "openbis":
            try:
                dms_path, dms_id = get_dms_info(
                    oBis=openbis_client, filename=file_name, dms_code=dms_code
                )
            except Exception as e:
                logging.critical(
                    "External storage {} not found in openBIS.".format(dms_code)
                )
                logging.critical("Abort")
                sys.exit(0)
            logging.debug("Full path on external storage: {}".format(dms_path))
            logging.debug("DMS ID: {}".format(dms_id))

            logging.info(f"Processing {file_name_fqdn}")

            logging.info(
                "Get file details, including checksum... (may take long for large files)"
            )
            try:
                file_metadata = get_file_metadata(
                    filename=file_name_fqdn, dms_path=dms_path, compute_crc32=False
                )
                logging.debug("Generic metadata: {}".format(file_metadata))
            except Exception as e:
                logging.critical("Generic metadata could not be created: {}".format(e))
                logging.critical("Abort")
                sys.exit(0)
        logging.debug("Now run metadata parser (if available)")
        properties = {
            "$name": f"{data_set_name}_{counter}",
        }
        if comments:
            properties["comments"] = comments
        ##
        ## now try to get the metadata from the files
        ## This only works for specific dataset types with tailored scripts that extract the metadata from the file
        ## and fill in the corresponding fields in openBIS
        ##

        try:
            metadata = get_metadata(
                file_name_fqdn=file_name_fqdn,
                data_set_type=data_set_type,
                metadata_parser=metadata_parser,
                options=parser_options,
            )
        except Exception as e:
            metadata = {}
            logging.debug(
                "Error while parsing metadata\nFile: {}, DatasetType: {}, Parser: {}\nError: {}".format(
                    file_name_fqdn, data_set_type, metadata_parser, e
                )
            )
            logging.critical(
                "Dataset specific metadata could not be created: {}".format(e)
            )
            logging.critical("Uploading and registering the file nonetheless.")
        # Convert decimal to float as required by pybis 1.37.0
        # FIXME Add types to metadata parsers

        for k, v in metadata.items():
            if v is not None and property_types.loc[k.upper(), "dataType"] == "REAL":
                metadata[k] = float(v)
        # Filter to remove all null properties

        metadata = {k: v for k, v in metadata.items() if v is not None}

        logging.debug("Metadata from file :")
        logging.debug(metadata)

        properties = {**properties, **metadata}
        logging.debug("Merged properties dict.")
        logging.debug(properties)

        if mode == "s3":
            logging.info("Upload file to external datastore ...")
            s3_client = get_s3_client(url=s3_url, key=s3_key, secret=s3_secret)
            try:
                s3_file_upload(
                    filename_fqdn=file_name_fqdn,
                    bucket=s3_bucket,
                    object_name=file_name,
                    s3_client=s3_client,
                )
            except Exception as e:
                logging.error("Error uploading file to S3 !")
                logging.error(e)
                sys.exit(1)
        permid = None

        # LINK

        if mode == "s3" or mode == "link_only":
            logging.debug("Register linked data in openBIS ...")
            try:
                permid = register_file(
                    oBis=openbis_client,
                    file_metadata=file_metadata,
                    dms_path=dms_path,
                    dms_id=dms_id,
                    dss_code=dss_code,
                    data_set_code=data_set_code,
                    data_set_type=data_set_type,
                    properties=properties,
                    object_name=object_identifier,
                    experiment_name=experiment_identifier,
                    parent_ids=parent_ids,
                )
                if mode == "s3":
                    url = s3_client.generate_presigned_url(
                        "get_object",
                        Params={"Bucket": s3_bucket, "Key": file_name},
                        ExpiresIn=604800,  # 1 WEEK
                        HttpMethod="GET",
                    )
                    ds = openbis_client.get_dataset(permid)
                    ds.p["s3_download_link"] = url
                    ds.save()
            except Exception as e:
                logging.error("Encountered error when registering S3 file in openBIS !")
                logging.error(e)
                sys.exit(1)
        # PHYSICAL

        if mode == "openbis":
            logging.debug("Register and upload file to openBIS")
            try:
                permid = upload_data(
                    oBis=openbis_client,
                    username=openbis_username,
                    filename_fqdn=file_name_fqdn,
                    ds_type=data_set_type,
                    properties=properties,
                    object=object_identifier,
                    experiment=experiment_identifier,
                    parent_ids=parent_ids,
                )
            except Exception as e:
                logging.error("Encountered error when uploading file to openBIS !")
                logging.error(e)
                sys.exit(1)
        if permid is not None:
            logging.info(
                "File registered with new permID in openBIS: {}".format(permid)
            )
        counter += 1
        if prefix != "":
            destination.unlink()
    logging.info("All done.")
