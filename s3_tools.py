#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
This file holds the helper code for interacting with the S3 part of the coscine storage system.
"""

import logging
import ntpath

# S3 via boto3 client
import boto3
import botocore
from botocore.client import Config
from botocore.errorfactory import ClientError


# https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3-uploading-files.html

## ###############################################################
##
## ###############################################################


def get_s3_client(url: str, key: str, secret: str) -> boto3.client:
    """Creates an Boto3 S3 client.

    Args:
        url (str): URL endpoint of the S3 object store
        key (str): access key (read or write)
        secret (str): secret for the above access key

    Returns:
        _type_: Boto3 S3 client
    """
    logging.info("S3 URL: {}".format(url))
    s3_client = None
    

    if url is not None and key is not None and secret is not None:
        if "datastorage.nrw" in url.lower():
            config = Config(
                signature_version="s3v4", s3={"addressing_style": "virtual"}
            )
        else:
            config = Config(signature_version="s3v4")

        s3_client = boto3.client(
            service_name="s3",
            endpoint_url=url,
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            config=config,
        )

    return s3_client


## ###############################################################
##
## ###############################################################


def s3_file_exists(filename: str, bucket: str, s3_client: boto3.client) -> bool:
    """Checks if a given file exists on the S3 object store already.
        If the file does not yet exist, the server responds with an (HTML) error "404", otherwise the file exists.
        If the (HTML) error "403" is returned by the server, access is denied.

    Args:
        TODO: check if this makes sense...
        filename (str): file to be checked on S3
        bucket (str): Name of the S3 bucket
        s3_client : Boto3 S3 client

    Raises:
        e: exception from the Boto3 S3 client

    Returns:
        _type_: _description_
    """

    try:
        s3_client.head_object(Bucket=bucket, Key=filename)
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        elif e.response["Error"]["Code"] == "403":
            logging.error("S3: access denied")
            raise e
        else:
            raise e
    return True


## ###############################################################
##
## ###############################################################


def s3_file_upload(
    filename_fqdn: str, bucket: str, object_name: str, s3_client: boto3.client
) -> None:
    """Upload file to S3 bucket

        TODO: do something more clever if the file exists than just write / overwrite

    Args:
        filename_fqdn (str): file (including path) to be uploaded
        bucket (str): Name of the S3 bucket
        object_name (str): Name of the file on the S3 bucket (does not have to be the same as the filename)
        s3_client: Boto3 S3 client

    Raises:
        e: exceptions from Boto3 client

    """

    filename = ntpath.basename(filename_fqdn)

    if s3_client is None:
        logging.error("S3 client invalid")
        raise ValueError("The S3 client was NOT setup correctly.")
    else:
        file_exists = s3_file_exists(filename=filename, bucket=bucket, s3_client=s3_client)  # type: ignore

        logging.debug("File exists: ", file_exists)

        # TODO: do something more clever than to just overwrite the file.

        try:
            s3_client.upload_file(filename_fqdn, bucket, object_name)
        except ClientError as e:
            logging.error("S3 upload failed")
            logging.error(e)
            raise e
