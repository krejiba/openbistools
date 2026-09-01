#!/usr/bin/env python
# -*- coding: utf-8 -*-


"""
Helper code and tools, partly extracted from the PyBIS source code,
used to register linked datasets in OpenBIS
see also: https://sissource.ethz.ch/sispub/openbis/-/blob/master/api-openbis-python3-pybis/src/python/pybis/pybis.py
"""

from pybis import Openbis
from pybis.experiment import Experiment
from pybis.sample import Sample
import zlib
import os
import logging
import xxhash  # more efficient hash values than CRC32


##
## ######################################################################
##


def crc32(fileName: str):
    """since Python3 the zlib module returns unsigned integers (2.7: signed int)"""
    prev = 0
    for eachLine in open(fileName, "rb"):
        prev = zlib.crc32(eachLine, prev)
    # return as hex

    return "%x" % (prev & 0xFFFFFFFF)


##
## ######################################################################
##


def compute_xxhash64(path: str, block_size: int = 2**32) -> str:
    """
    Computes the xxHash (64-bit) digest for a given file.

    Args:
        path (str): full path to the file to be hashed.
        block_size (int, optional): The block size for reading the file (default is 4096).

    Returns:
        str: The hexadecimal representation of the xxHash digest.

    Raises:
        IOError: If the file cannot be read or xxHash computation fails.
    """
    try:
        with open(path, "rb") as file:
            h = xxhash.xxh64()
            for chunk in iter(lambda: file.read(block_size), b""):
                h.update(chunk)
        return h.hexdigest()
    except IOError as e:
        logging.error("xxHash could not be computed: %s" % e)
        raise e


##
## ######################################################################
##


def get_dms_info(oBis: Openbis, filename: str, dms_code: str) -> tuple[str, dict]:
    """
    Generates the full file path on the external storage.

    The full path consists of the external storage, the relative path,
    and the name of the file.

    Args:
        oBis (Openbis): Openbis instance object, connecting to the openBIS server.
        filename (str): Filename to be stored.
        dms_code (str): Code of the openBIS external data storage service.

    Returns:
        tuple of str, dict: The full path name on the external storage.
    """
    try:
        dms = oBis.get_external_data_management_system(dms_code)
    except ValueError as e:
        logging.debug("Error: %s" % e)
        raise e
    logging.debug("Data will be stored in: %s" % dms.urlTemplate)

    dms_id = oBis.external_data_managment_system_to_dms_id(dms_code)
    logging.debug("openBIS DMS ID %s" % dms_id)

    file_path = dms.urlTemplate + "/" + filename
    return file_path, dms_id


##
## ######################################################################
##


def retrieve_data_store_url(dss_code: str, oBis: Openbis) -> str:
    """
    Retrieves the URL of the openBIS data storage server (DSS).

    Args:
        dss_code (str): Identifier of the openBIS DSS server to handle the request.
        oBis (openbis): Openbis instance object, connecting to the openBIS server.

    Returns:
        str: URL + json that is used by openBIS to process the request.
    """
    data_stores = oBis.get_datastores()
    data_store = data_stores[data_stores["code"] == dss_code]
    download_url = data_store["downloadUrl"][0]
    return "%s/datastore_server/rmi-data-store-server-v3.json" % download_url


##
## ######################################################################
##


def get_data_store_url(obis_link_metadata: dict, oBis: Openbis) -> str:
    """
    Extracts the URL and relevant JSON file of the openBIS data storage server (DSS).

    The output should resemble the following:
    https://openbis-t.imm.rwth-aachen.de:443/datastore_server/rmi-data-store-server-v3.json.

    Args:
        obis_link_metadata (dict): openBIS metadata and instructions for linked files.
        oBis (Openbis): Openbis instance object, connecting to the openBIS server.

    Returns:
        str: The server URL and JSON file combination.
    """

    server_url = retrieve_data_store_url(
        obis_link_metadata["dataStoreId"]["permId"], oBis=oBis
    )
    logging.debug("DSS URL: %s" % server_url)

    return server_url


##
## ######################################################################
##


def get_file_metadata(
    filename: str, dms_path: str, compute_crc32: bool = False
) -> list:
    """
    Generates metadata on the file to be linked itself: file_size, checksum.
    Note: Also needs to include the full qualified path and filename on the external datastore.

    Args:
        filename (str): Name of the file for which the metadata is required.
        dms_path (str): Path on the external storage where the file is to be stored.
        compute_crc32 (bool, optional): Whether or not a CRC32 checksum is to be computed (default is False).

    Raises:
        FileNotFoundError: If the file cannot be found.

    Returns:
        list: List of metadata for the file to be registered in openBIS.
    """

    # based on code from:
    # https://sissource.ethz.ch/sispub/openbis/-/blob/master/api-openbis-python3-pybis/src/python/pybis/data_set.py
    # param contents: A list of dicts...

    if not os.path.isfile(filename):
        logging.critical("File not found: %s" % filename)
        raise FileNotFoundError("File %s not found" % filename)
    file_size = os.path.getsize(filename)
    file_crc32 = 0
    # CRC32 can be slow for large files.

    if compute_crc32:
        file_crc32 = crc32(filename)
    try:
        file_xxhash = compute_xxhash64(filename)
    except IOError as e:
        logging.error("xxHash not computed: %s" % e)
        raise e
    logging.debug("file size: %s" % file_size)
    logging.debug("file_crc32: %s" % file_crc32)
    logging.debug("XXHash: %s" % file_xxhash)

    content = {
        "fileLength": file_size,
        "crc32": file_crc32,
        "crc32Checksum": file_crc32,
        "checksum": file_xxhash,
        "checksumType": "xxHash",
        "directory": False,
        "path": dms_path,
    }
    file_metadata = [content]

    logging.debug("File metadata: %s" % file_metadata)

    return file_metadata


##
## ######################################################################
##


def create_obis_link_metadata(
    oBis: Openbis,
    dms_path: str,
    data_set_type: str,
    dss_code: str,
    dms_id: dict,
    parent_ids: list,
    properties: dict,
    object_name: str,
    experiment_name: str,
    data_set_code: str,
) -> dict:
    """
    Creates a metadata dictionary containing information on how openBIS should link the data,
    along with relevant metadata.

    Args:
        oBis (Openbis): Openbis instance object, connecting to the openBIS server.
        dms_path (str): Fully qualified path of the file on the external data store (including filename).
        data_set_type (str): openBIS data type for the linked file.
        dss_code (str): Identifier of the openBIS DSS server to handle the request.
        dms_id (dict): Details about the external storage (DMS).
        parent_ids (list): Parents of the file to be linked.
        properties (dict): Properties of the file in the ELN (e.g., name, metadata).
        object_name (str): String identifier of the sample to link this file to (must specify either sample or experiment).
        experiment_name (str): String identifier of the experiment to link the file to (must specify either sample or experiment).
        data_set_code (str): Code of the dataset to attach the file to. If None, a new one will be created.

    Returns:
        dict: A metadata dictionary for the file to be registered in openBIS.
    """

    data_set_creation = {
        "linkedData": {
            "@type": "as.dto.dataset.create.LinkedDataCreation",
            "contentCopies": [
                {
                    "@type": "as.dto.dataset.create.ContentCopyCreation",
                    "path": dms_path,
                    # "gitCommitHash": None,
                    # "gitRepositoryId": None,
                    "externalDmsId": dms_id,
                }
            ],
        },
        "typeId": {
            "@type": "as.dto.entitytype.id.EntityTypePermId",
            "permId": data_set_type,
        },
        "dataStoreId": {
            "permId": dss_code,
            "@type": "as.dto.datastore.id.DataStorePermId",
        },
        "parentIds": parent_ids,
        "measured": False,
        "properties": properties,
        "@type": "as.dto.dataset.create.DataSetCreation",
    }

    if object_name is not None:
        object_id = oBis.sample_to_sample_id(object_name)
        data_set_creation["sampleId"] = object_id
    elif experiment_name is not None:
        experiment_id = oBis.experiment_to_experiment_id(experiment_name)
        data_set_creation["experimentId"] = experiment_id
    if data_set_code is not None:
        data_set_creation["code"] = data_set_code
        data_set_creation["autoGeneratedCode"] = False
    else:
        data_set_creation["autoGeneratedCode"] = True
    logging.debug("openBIS link metadata dict: %s" % data_set_creation)

    return data_set_creation


##
## ######################################################################
##


def create_obis_link_request(
    obis_link_metadata: dict, file_metadata: list, token: str
) -> dict:
    """
    Combines openBIS metadata and file metadata into the service request
    that is then sent to the openBIS server.

    Args:
        obis_link_metadata (dict): openBIS metadata and instructions for linked files.
        file_metadata (list): Metadata about the file (CRC, path on DMS).
        token (str): openBIS access token (session token or personal access token).

    Returns:
        dict: Request to send to the openBIS server.
    """

    data_set_creation = {
        "fileMetadata": file_metadata,
        "metadataCreation": obis_link_metadata,
        "@type": "dss.dto.dataset.create.FullDataSetCreation",
    }

    request = {
        "method": "createDataSets",
        "params": [token, [data_set_creation]],
    }

    logging.debug("openBIS link request: %s" % request)

    return request


##
## ######################################################################
##


def register_file(
    oBis: Openbis,
    file_metadata: list,
    dms_path: str,
    dms_id: dict,
    dss_code: str,
    object_name: str,
    experiment_name: str,
    properties: dict,
    data_set_code: str,
    data_set_type: str,
    parent_ids: list,
) -> str:
    """
    Registers the file in openBIS as a linked file on the external storage system.
    Assumes that the file is copied to this system manually or by other means:
    This function only registers the metadata in openBIS.

    Args:
        oBis (Openbis): Openbis instance object, connecting to the openBIS server.
        file_metadata (list): Metadata about the file (CRC, path on DMS).
        dms_path (str): Fully qualified path of the file on the external data store (including filename).
        dms_id (dict): Details about the external storage (DMS).
        dss_code (str): Identifier of the openBIS DSS server to handle the request.
        object_name (str): String identifier of the object to link this file to (must specify either sample or experiment).
        experiment_name (str): String identifier of the experiment to link the file to (must specify either sample or experiment).
        properties (dict): Properties of the file in the ELN (e.g., name, metadata).
        data_set_code (str): Code of the dataset to attach the file to. If None, a new one will be created.
        data_set_type (str): openBIS data type for the linked file.
        parent_ids (list): Parents of the file to be linked.

    Raises:
        Exception: If the registration of the linked file in openBIS fails.

    Returns:
        str: openBIS permID of the newly linked file.
    """

    obis_link_metadata = create_obis_link_metadata(
        oBis=oBis,
        dms_path=dms_path,
        dms_id=dms_id,
        dss_code=dss_code,
        parent_ids=parent_ids,
        properties=properties,
        object_name=object_name,
        experiment_name=experiment_name,
        data_set_code=data_set_code,
        data_set_type=data_set_type,
    )
    logging.debug("openBIS link metadata: \n%s" % obis_link_metadata)

    obis_link_request = create_obis_link_request(
        obis_link_metadata=obis_link_metadata,
        file_metadata=file_metadata,
        token=oBis.token,
    )
    logging.debug("openBIS link request: \n%s" % obis_link_request)

    obis_dss_url = get_data_store_url(oBis=oBis, obis_link_metadata=obis_link_metadata)
    logging.debug("URL for the link request (DSS): %s" % obis_dss_url)

    # POST request to openBIS server

    try:
        response = oBis._post_request_full_url(obis_dss_url, obis_link_request)
        logging.debug("Server response to POST command: %s" % response)

        # openBIS permID of the newly linked dataset

        permid_linked_dataset = oBis.get_dataset(response[0]["permId"]).permId
        logging.debug("New openBIS permID %s" % permid_linked_dataset)
    except Exception as e:
        logging.error("Something went wrong in POST command: %s" % e)
        raise e
    return permid_linked_dataset


##
## ######################################################################
##


def check_role(
    oBis: Openbis,
    username: str,
    space: str = "IMM",
    project: str = "",
    role: str = "OBSERVER",
) -> bool:
    """
    Checks if a user has the specified role in a given space (or project).

    Args:
        oBis (Openbis): Openbis instance object, connecting to the openBIS server.
        username (str): OpenBIS username to check.
        space (str, optional): The space to check the role for (default is 'IMM').
        project (str, optional): The project to check the role for (default is '').
        role (str, optional): The role to enquire about (default is 'OBSERVER').

    Returns:
        bool: True if the user has the role, False otherwise.

    Raises:
        ValueError: If neither a space nor a project were provided.

    """

    person = oBis.get_person(username)

    # Get the pandas dataframe rather than the pyBIS Things
    roles = person.get_roles().df
    if len(project) > 0:
        roles = roles[roles.project == project]
    elif len(space) > 0:
        roles = roles[roles.space == space]
    else:
        raise ValueError("Either a space or a project needs to be provided")
    user_role = roles.role
    if user_role.eq(role).any():
        return True
    else:
        return False


##
## ######################################################################
##


def upload_data(
    oBis: Openbis,
    username: str,
    filename_fqdn: str,
    ds_type: str,
    properties: dict,
    object=None,
    experiment=None,
    parent_ids: list = [],
) -> str:
    """
    Uploads a file directly to the openBIS server.

    Args:
        oBis (Openbis): Openbis instance object, connecting to the openBIS server.
        username (str): OpenBIS username (to check if allowed to perform operation).
        filename_fqdn (str): Name of the file (including path) to be uploaded to openBIS.
        ds_type (str): DataSet type corresponding to the object types in openBIS.
        properties (dict): Properties of the file in the ELN (e.g., name, metadata).
        parent_ids (list, optional): List of parent IDs of datasets that should be linked as parents to this dataset. Note: only works for if the parent is also a dataset. Defaults to [].
        object (_type_, optional): Object the datset should be uploaded to. Either object or experiment must be specified. Defaults to None.
        experiment (_type_, optional): Experiment the dataset should be uploaded. Either object or experiment must be specified. Defaults to None.

    Raises:
        Exception: insufficient privileges or neither object or experiment is specified

    Returns:
        str: permId of the newly uploaded dataset
    """

    if check_role(oBis=oBis, username=username) == False:
        logging.debug("Upload to OpenBIS server is not possible.")
        raise Exception(
            "User has no permission to upload data directly to OpenBIS server"
        )
    if object == None and experiment == None:
        # logging.critical("Must specify either object or experiment to upload data to.")
        raise Exception("Must specify either object or experiment to upload data to.")
    logging.debug("Properties and metadata for the file to be uploaded:")
    logging.debug(properties)

    # Note: until "save" is called, ds_new has no type, no permId etc.

    ds_new = oBis.new_dataset(
        type=ds_type,
        object=object,
        experiment=experiment,
        files={filename_fqdn},
        props=properties,
    )
    ds_new.save()
    perm_id = ds_new.permId
    logging.info("Created new dataset with permID %s" % perm_id)

    # Add any parent datasets (e.g. if we have a derived dataset)

    ds_new.set_parents(parent_ids)
    ds_new.save()

    return perm_id


def get_full_identifier(
    exp_dict: dict,
    obj_dict: dict,
    sep: str = "//",
    include_permid_suffix: bool = False,
):
    """Returns an OpenBIS identifier that better reflects hierarchy (referred to as Path in ELN-LIMS GUI).

    In OpenBIS, the identifiers have 3 components.
        /SPACE/PROJECT/EXPERIMENT (Experiment = Collection)
        /SPACE/PROJECT/OBJECT (Object = Sample)
    We extend the identifiers (of objects).
        /SPACE/PROJECT/EXPERIMENT
        /SPACE/PROJECT/EXPERIMENT/OBJECT
    """

    space_code = exp_dict["space"]
    project_code = exp_dict["project"]
    experiment_or_collection_code = exp_dict["code"]
    object_code = obj_dict["code"]
    object_permid = obj_dict["permId"]

    # Fetch names for display purposes

    experiment_or_collection_name = exp_dict.get("$NAME")
    object_name = obj_dict.get("$NAME")

    # Create name from code if necessary

    if experiment_or_collection_name in (None, ""):
        parts = experiment_or_collection_code.split("_")
        parts = [part.title() for part in parts]
        experiment_or_collection_name = " ".join(parts)

    if object_name in (None, ""):
        object_name = object_code

    # Create full identifier

    object_identifier = obj_dict["identifier"]
    new_ending = f"{experiment_or_collection_code}/{object_code}"
    full_identifier = object_identifier.replace(object_code, new_ending)

    # Create display name with custom seperator
    display_name = sep.join(
        [space_code, project_code, experiment_or_collection_name, object_name]
    )
    if include_permid_suffix:
        display_name += f" ({object_permid}, {object_identifier})"

    return full_identifier, display_name


def get_info_from_identifier(full_identifier: str, sep: str = "/"):
    """Returns standard OpenBIS identifiers from full identifier."""

    # /SPACE/PROJECT/EXPERIMENT/OBJECT

    depth = full_identifier.count(sep)
    codes = full_identifier.split(sep)[1:]

    if depth == 4:  # Object/Sample
        space_code, project_code, experiment_code, object_code = codes
        experiment_identifier = sep.join(
            ["", space_code, project_code, experiment_code]
        )
        object_name = sep.join(["", space_code, project_code, object_code])
    if depth == 3:  # Experiment/Collection
        experiment_identifier = full_identifier
        object_name = None
    return experiment_identifier, object_name
