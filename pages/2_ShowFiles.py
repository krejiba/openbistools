import streamlit as st
import os
import time
from datetime import datetime, date
import pandas as pd
from zipfile import ZIP_DEFLATED, ZipFile
import requests
from io import BytesIO
import base64
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
import numpy as np
import warnings
import re


from s3_tools import s3_file_exists, s3_file_upload
from pybis_tools import get_info_from_identifier

# Utility to update experiment list
from Hello import find_relevant_locations, SUBTYPES

# Utilities for preview
from visualization.tem import get_image_stack as get_tem_stack
from visualization.nrr import get_image as get_tem_image
from visualization.video_rendering import VideoRenderer
from visualization.presentation import (
    create_grid_from_ppt,
    create_grid_from_doc,
    create_grid_from_pdf,
)


warnings.filterwarnings(action="ignore", category=FutureWarning)

## ============================================================================
##  Helper Functions
## ============================================================================


def dataframe_with_selections(df):
    df_with_selections = df.copy()
    df_with_selections.insert(0, "Select", False)
    pt_df = st.session_state.oBis.get_property_types().df
    datatype_mapping = {}
    for col in df_with_selections.columns[12:]:
        if len(pt_df[pt_df.label == col]) == 1:
            datatype_mapping[col] = pt_df[pt_df.label == col]["dataType"].item()

    column_config = {
        "ELN": st.column_config.LinkColumn(display_text="Go"),
        "Select": st.column_config.CheckboxColumn(required=True),
        "Preview": st.column_config.ImageColumn(width="small"),
        "S3 Path": st.column_config.TextColumn(width="small"),
        "Registration Date": st.column_config.DatetimeColumn(
            format="YYYY-MM-DD HH:mm:ss"
        ),
        "Kind": None,
        "Size (Mb)": st.column_config.NumberColumn(),
    }
    column_config.update(
        {
            col: st.column_config.NumberColumn()
            for col, dtype in datatype_mapping.items()
            if dtype in ["INTEGER", "REAL"]
        }
    )

    # Get dataframe row-selections from user with st.data_editor
    edited_df = st.data_editor(
        df_with_selections,
        hide_index=True,
        column_config=column_config,
        disabled=df.columns,
    )

    # Filter the dataframe using the temporary column, then drop the column

    selected_rows = edited_df[edited_df.Select]
    return selected_rows.drop("Select", axis=1)


def generate_preview(pil_img: Image, img_height: int = 480, format: str = "JPEG"):
    buffer = BytesIO()
    if format != "GIF":
        original_mode = pil_img.mode
        if original_mode in ["RGB", "P", "CMYK"]:
            output_mode = "RGB"
        elif original_mode in ["F", "L", "LA", "I;16", "I;16B", "I;16L", "I;16N"]:
            output_mode = "L"
        elif original_mode == "RGBA":
            background = Image.new("RGB", pil_img.size, (255, 255, 255))
            background.paste(pil_img, (0, 0), pil_img)
            pil_img = background
            output_mode = "RGB"
        else:
            raise NotImplementedError(f"Unsupported mode {original_mode}")
        w, h = pil_img.size
        if output_mode == "L":
            img = np.array(pil_img)
            img = (img - img.min()) / (img.max() - img.min() + 1e-20)
            img = (img * 255).astype("uint8")
            pil_img = Image.fromarray(img)
        pil_img = pil_img.resize(
            size=(int(img_height * w / h), img_height),
            resample=Image.Resampling.BOX,
        )
        pil_img = pil_img.convert(output_mode)
        pil_img.save(buffer, format=format)
    else:
        pil_img.save(buffer, format=format, save_all=True)
    img_bytes = buffer.getvalue()
    img_base64 = base64.b64encode(img_bytes).decode("utf-8")
    preview = f"data:image/{format.lower()};base64,{img_base64}"
    pil_img.close()
    return preview


def get_img_preview_from_path(path: str):
    try:
        image = Image.open(path)
    except UnidentifiedImageError as e:
        image = Image.new("L", (64, 64))
        draw = ImageDraw.Draw(image)
        draw.text((2, 25), "Corrupted", fill=255, font=ImageFont.load_default())
    if image.mode in ["I;16", "I;16B", "I;16L", "I;16N"]:
        image = image.point(lambda i: i * (255.0 / 65535.0))
    if image.mode in ["F"]:
        min_val, max_val = image.getextrema()
        image = image.point(lambda i: (i - min_val) * 255.0 / (max_val - min_val))
    image = image.convert("RGB")
    desired_height = 1024
    height, width = image.size
    aspect_ratio = width / height
    desired_width = int(desired_height * aspect_ratio)
    return image.resize((desired_height, desired_width), Image.Resampling.LANCZOS)


## ============================================================================
##  Main app
## ============================================================================


st.set_page_config(
    page_title="Find data in openBIS",
    page_icon="media/SFB1394_icon.jpg",
    layout="wide",
)

try:
    _ = st.session_state.setup_done
    if "df_files" not in st.session_state:
        st.session_state.df_files = pd.DataFrame()
    if "df_all" not in st.session_state:
        st.session_state.df_all = pd.DataFrame()
    if "selection" not in st.session_state:
        st.session_state.selection = pd.DataFrame()
    if "selection_deletion" not in st.session_state:
        st.session_state.selection_deletion = pd.DataFrame()
    if "requested_deletion" not in st.session_state:
        st.session_state.requested_deletion = False
except AttributeError as e:
    st.switch_page("Hello.py")
st.sidebar.image("media/SFB1394_TitleImage_Cropped.png")
st.sidebar.write("Logged into openBIS: ", st.session_state.logged_in)
st.sidebar.write("OpenBIS Upload OK: ", st.session_state.openbis_upload_allowed)
st.sidebar.write("S3 Upload OK: ", st.session_state.s3_upload_ok)
st.sidebar.write("S3 Download OK: ", st.session_state.s3_download_ok)
st.sidebar.write("S3 Resource: ", st.session_state.obis_dmscode)


temp_dir = st.session_state.temp_dir
files_to_download = []
data_dicts = []
preview_dict = {
    "CRYS-STRUCT_DATA": "structure",
    "NANOINDENTATION_DATA": "micromechanical_testing",
    "PILLAR_COMPRESSION_DATA": "micromechanical_testing",
    "XRD-TEXT_DATA": "xrd",
    "XRD-THETA_DATA": "xrd",
    "EBSD_EXP_DATA": "ebsd_eds",
    "EBSD-EDS_DATA": "ebsd_eds",
    "EDS_DATA": "ebsd_eds",
    "EBSD_SIM_MASTERPATTERN": "ebsd_eds",
    "EBSD_SIM_SCRRENPATTERN": "ebsd_eds",
}

file_num_preview_limit = 500  # Total number of files
file_size_preview_limit = 500  # Individual file size


st.title("Show Linked Data in openBIS")
st.write(
    """
    - If you select multiple files to download, they will be compressed into a zip archive.  
    - A CSV file containing the metadata is included in the zip archive.  
    - Activating the preview feature can significantly delay the rendering of the results.  
    - Metadata can also be fetched.
    """
)

ELN_URL_QUERY_PREFIX = r"?menuUniqueId=%7B%22type%22:%22ADVANCED_SEARCH%22,%22id%22:%22ADVANCED_SEARCH%22%7D"


def create_dataset_href(openbis_client, permid):
    query = ELN_URL_QUERY_PREFIX + r"&viewName=showViewDataSetPageFromPermId&viewData="
    base_url = ":".join(openbis_client.url.split(":", 2)[:2])
    link = base_url + query + permid
    return link


def create_experiment_href(openbis_client, identifier):
    query = (
        ELN_URL_QUERY_PREFIX
        + f"&viewName=showExperimentPageFromIdentifier&viewData=[%22{identifier}%22,false]"
    )
    base_url = ":".join(openbis_client.url.split(":", 2)[:2])
    link = base_url + query
    return link


def create_object_href(openbis_client, permid):
    query = (
        ELN_URL_QUERY_PREFIX
        + f"&viewName=showViewSamplePageFromPermId&viewData=%22{permid}%22"
    )
    base_url = ":".join(openbis_client.url.split(":", 2)[:2])
    link = base_url + query
    return link


def strip_tags(text):
    if text:
        clean_text = re.sub(r"<.*?>", "", text)
        clean_text = " ".join(clean_text.strip().split())
        return clean_text
    else:
        return ""


def create_slides(
    openbis_client, data_dicts: list, output_path: str = "presentation.odp"
):
    from io import BytesIO
    from odf.opendocument import OpenDocumentPresentation
    from odf.style import Style, TextProperties, TableProperties, TableColumnProperties
    from odf.draw import Page, Frame, Image, TextBox
    from odf.text import P
    from odf.table import Table, TableRow, TableColumn, TableCell
    from odf.draw import Frame, Image
    from odf.text import P, A

    doc = OpenDocumentPresentation()

    text_style = Style(name="TextStyle", family="presentation")
    text_style.addElement(TextProperties(fontsize="14pt"))
    doc.styles.addElement(text_style)

    styles = doc.automaticstyles

    table_style = Style(name="FixedWidthTable", family="table")
    table_style.addElement(TableProperties(width="16cm"))
    styles.addElement(table_style)

    col_style = Style(name="FourColFixed", family="table-column")
    col_style.addElement(TableColumnProperties(columnwidth="4cm"))
    styles.addElement(col_style)

    para_style = Style(name="TableText12pt", family="paragraph")
    para_style.addElement(TextProperties(fontsize="8pt"))
    doc.automaticstyles.addElement(para_style)

    for idx, data in enumerate(data_dicts):
        permid = data["permId"]
        path = data["local_path"]
        metadata = data["props"]

        slide = Page(
            masterpagename="Standard", name=f"slide_{idx:03d}", stylename=text_style
        )
        doc.presentation.addElement(slide)

        img = get_img_preview_from_path(path)
        original_width, original_height = img.size

        fixed_width_cm = 16
        aspect_ratio = original_height / original_width
        new_height_cm = int(fixed_width_cm * aspect_ratio)
        buffer = BytesIO()
        img.save(buffer, "JPEG", quality=95, optimize=True)

        href = doc.addPictureFromString(
            mediatype="image/jpeg", content=buffer.getvalue()
        )
        image = Image(href=href)
        image_frame = Frame(
            width=f"{fixed_width_cm}cm", height=f"{new_height_cm}cm", x="1cm", y="1cm"
        )
        image_frame.addElement(image)
        slide.addElement(image_frame)

        text_frame = Frame(width="16cm", height="1cm", x="1cm", y="17cm")
        slide.addElement(text_frame)
        text_box = TextBox()
        text_frame.addElement(text_box)

        hyperlink_text = (
            f"{idx+1} / {len(data_dicts)} - Go to Dataset in openBIS ELN-LIMS"
        )
        hyperlink_url = create_dataset_href(openbis_client, permid)
        hyperlink = A(href=hyperlink_url, text=hyperlink_text)
        paragraph = P()
        paragraph.addElement(hyperlink)
        text_box.addElement(paragraph)

        table_frame = Frame(width="16cm", height="16cm", x="17cm", y="1cm")
        table = Table(name="Metadata Table", stylename=table_style)
        for _ in range(4):
            table.addElement(TableColumn(stylename=col_style))

        items = [(str(k), str(v)) for k, v in metadata.items() if k != "Download Link"]

        for i in range(0, len(items), 2):
            row = TableRow()
            k1, v1 = items[i]
            cell = TableCell()
            cell.addElement(P(stylename=para_style, text=k1))
            row.addElement(cell)
            cell = TableCell()
            cell.addElement(P(stylename=para_style, text=v1))
            row.addElement(cell)
            if i + 1 < len(items):
                k2, v2 = items[i + 1]
                cell = TableCell()
                cell.addElement(P(stylename=para_style, text=k2))
                row.addElement(cell)
                cell = TableCell()
                cell.addElement(P(stylename=para_style, text=v2))
                row.addElement(cell)
            else:
                row.addElement(TableCell())
                row.addElement(TableCell())
            table.addElement(row)

        table_frame.addElement(table)
        slide.addElement(table_frame)
        doc.save(output_path)


# Filter entries before form
filtered_keys = []
if st.session_state.logged_in:
    col1, col2, col3 = st.columns(3)
    with col1:
        projects = ["ALL"] + sorted(
            {
                key.split("//")[1]
                for key in st.session_state.experiments_with_data.keys()
                if len(key.split("//")) > 1
            }
        )
        project = st.selectbox(
            "Select project",
            projects,
            disabled=not st.session_state.logged_in,
            index=0,
        )
    with col2:
        object_types = ["ALL"] + sorted(
            {
                x[1]
                for x in st.session_state.experiments_with_data.values()
                if x[1] is not None
            }
        )
        selected_obj_type = st.selectbox(
            "Select experiment type",
            object_types,
            disabled=not st.session_state.logged_in,
            index=0,
            format_func=lambda code: (
                st.session_state.oBis.get_object_type(code).description
                if code != "ALL"
                else "ALL"
            ),
        )
    with col3:
        vocab_terms = st.session_state.oBis.get_terms().df
        vocab_terms = vocab_terms.set_index("code")["label"].to_dict()
        for ot_code, pt_code in SUBTYPES.items():
            if selected_obj_type == ot_code:
                sub_types = ["ALL"] + sorted(
                    {
                        x[2]
                        for x in st.session_state.experiments_with_data.values()
                        if x[2] is not None and x[2] != "" and x[1] == ot_code
                    }
                )
                selected_sub_type = st.selectbox(
                    "Select subtype",
                    sub_types,
                    disabled=not st.session_state.logged_in,
                    index=0,
                    format_func=lambda code: vocab_terms.get(code, "ALL"),
                )
                break
        else:
            selected_sub_type = "ALL"
    for key, value in st.session_state.experiments_with_data.items():
        if len(value) == 3:
            _, obj_type, sub_type = value
            parts = key.split("//")
            if (len(parts) > 1 and parts[1] == project) or (project == "ALL"):
                if obj_type == selected_obj_type or selected_obj_type == "ALL":
                    if obj_type in SUBTYPES and (
                        sub_type == selected_sub_type or selected_sub_type == "ALL"
                    ):
                        filtered_keys.append(key)
                    if obj_type not in SUBTYPES:
                        filtered_keys.append(key)

with st.form("Experiment"):

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
        "Find the entry where your data is linked",
        sorted(filtered_keys),
        index=None,
        placeholder="Select ELN entry",
        key="experiment",
        disabled=not st.session_state.logged_in,
        help="Only experiments with data are displayed here",
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        include_preview = st.toggle(
            "Preview",
            help="Only if you're not in a hurry, We post-process some of the images",
            disabled=not st.session_state.setup_done,
        )
    with col2:
        default_start = date(2024, 1, 1)
        default_end = date(2027, 12, 31)
        date_limits = st.date_input(
            "Limit dates (for preview)",
            value=(date(2024, 1, 1), date(2027, 12, 31)),
            disabled=not st.session_state.setup_done,
            help=f"Filter by registrationDate, only when number of files > {file_num_preview_limit}",
        )
        if date_limits is None or len(date_limits) != 2 or None in date_limits:
            start_date, end_date = default_start, default_end
        else:
            start_date, end_date = date_limits
        if start_date > end_date:
            start_date, end_date = end_date, start_date

    with col3:
        extensions = [
            "docx",
            "pptx",
            "pdf",
            "tif",
            "jpg",
            "png",
            "bmp",
            "dm4",
            "dm3",
            "emd",
            "h5",
            "zip",
            "ang",
            "osc",
            "edaxh5",
            "oh5",
            "up1",
            "up2",
            "h5oina",
            "sdf5",
            "nmd",
            "poscar",
            "contcar",
            "vasp",
            "data",
            "lmp",
            "out",
            "nc",
            "mp4",
            "avi",
        ]
        extensions = sorted(extensions)
        selected_extensions = st.multiselect(
            "Limit Extensions (for preview)",
            options=extensions,
            disabled=not st.session_state.setup_done,
            help="Only the selected extensions will be fetched. If empty, all extensions will be fetched",
        )
        if not selected_extensions:
            selected_extensions = extensions

    img_extensions = {ext.lstrip(".") for ext in Image.registered_extensions().keys()}
    ignore_non_image = st.toggle(
        label="Ignore non-image data when creating slides",
        disabled=not st.session_state.setup_done,
        help=f"Only image files are used. Supported extensions: *{', '.join(img_extensions)}*",
    )

    choose_exp_btn = st.form_submit_button(
        "Confirm",
        type="primary",
        disabled=not st.session_state.setup_done,
    )

    if choose_exp_btn and st.session_state.experiment is not None:

        entry = st.session_state.experiment
        identifier = st.session_state.experiments[entry]
        permid = entry.rsplit("(", 1)[1].split(")")[0]
        permid = permid.split(", ")[0]
        if identifier.count("/") == 3:
            url = create_experiment_href(st.session_state.oBis, identifier)
            num_datasets = (
                st.session_state.oBis.get_experiment(identifier)
                .props()
                .get("num_datasets", "")
            )
        elif identifier.count("/") == 4:
            url = create_object_href(st.session_state.oBis, permid)
            num_datasets = (
                st.session_state.oBis.get_object(permid).props().get("num_datasets", "")
            )
        else:
            url = ""
        st.markdown(f"[Open entry in ELN-LIMS ({num_datasets} datasets)]({url})")

        st.session_state.selection_deletion = pd.DataFrame()

        identifier = st.session_state.experiments[st.session_state.experiment]
        exp_name, object_name = get_info_from_identifier(identifier)

        datasets = st.session_state.oBis.get_datasets(
            experiment=exp_name,
            sample=object_name,
        )

        format_func = lambda code: st.session_state.oBis.get_property_type(code).label

        md_keys = set()

        for ds in datasets:
            md_keys.update(ds.p.all().keys())
        if "$name" in md_keys:
            md_keys.remove("$name")  # Already in dataframe
        md_keys = sorted(md_keys, key=format_func)

        options = st.multiselect(
            label="Choose metadata fields to display "
            "(re-click on Confirm to update table)",
            options=md_keys,
            key="metadata_options",
            format_func=lambda code: st.session_state.oBis.get_property_type(
                code
            ).label,
        )

        cols = [
            "ELN",
            "Preview",
            "Name",
            "Type",
            "Kind",
            "Registration Date",
            "permID",
            "Filename",
            "Extension",
            "S3 Path",
            "Size (Mb)",
        ]

        cols_all = cols + [
            st.session_state.oBis.get_property_type(key).label for key in md_keys
        ]

        for opt in options:
            opt = st.session_state.oBis.get_property_type(opt).label
            cols.append(opt)

        if datasets is not None and include_preview:
            permids_filtered = datasets.df.permId.to_list()
            n_files = len(datasets.df)
            if n_files > file_num_preview_limit:
                if date_limits and len(date_limits) == 2:
                    start_date, end_date = date_limits
                    registration_date = pd.to_datetime(datasets.df["registrationDate"])
                    mask = (registration_date >= pd.to_datetime(start_date)) & (
                        registration_date <= pd.to_datetime(end_date)
                    )
                    permids_filtered = datasets.df[mask].permId.to_list()
                    if len(permids_filtered) > file_num_preview_limit:
                        st.warning(
                            f"Skipping preview, too many files ({n_files} > {file_num_preview_limit})"
                        )
                        include_preview = False
                    else:
                        include_preview = True
        else:
            permids_filtered = []
        token = st.session_state.oBis.token

        spinner_text = f"Preparing {len(datasets)} files"
        if include_preview:
            spinner_text += f" (preview for {len(permids_filtered)})"

        with st.spinner(text=spinner_text):

            data = []
            data_all = []
            for ds in datasets:
                name = ds.p["$name"]
                permID = ds.permId
                attrs_dict = ds.attrs.all()
                dataset_type = attrs_dict["type"]
                kind = attrs_dict["kind"]
                reg_date = attrs_dict["registrationDate"]

                if kind == "LINK":
                    path = ds.data["linkedData"]["contentCopies"][0]["path"]
                    full_path = ds.data["linkedData"]["contentCopies"][0]["path"]
                    download_url = ds.p["s3_download_link"]
                    size = ds.get_dataset_files().df.fileLength.sum()
                else:
                    full_path = ds.file_list[0]
                    base_url = "/".join(st.session_state.oBis.url.split("/")[:3])
                    openbis_filename = ds.file_list[0]
                    download_url = f"{base_url}/datastore_server/{permID}/{openbis_filename}?sessionID={token}"
                    size = ds.data["physicalData"]["size"]
                    path = None

                filename = full_path.rsplit("/", 1)[1]
                extension = filename.split(".")[-1].lower()
                local_filename = temp_dir + "/" + filename
                preview_format = "JPEG"
                size_mb = size / (1024**2)

                preview = ""
                fetched_preview = False

                ext_map = {"jpeg": "jpg", "tiff": "tif"}
                mapped_extension = ext_map.get(extension, extension)

                if (
                    include_preview
                    and permID in permids_filtered
                    and (
                        (len(selected_extensions) > 0)
                        and (
                            mapped_extension in selected_extensions
                            or any(
                                ext in mapped_extension for ext in selected_extensions
                            )
                        )
                    )
                ):
                    if (
                        dataset_type in preview_dict
                        and "S3_OPENBIS_CACHE" in st.session_state.s3_clients
                    ):
                        # Previews are generated elsewhere (NOT on the spot)
                        cache_client = st.session_state.s3_clients["S3_OPENBIS_CACHE"]
                        cache_bucket = st.session_state.s3_bucket_names[
                            "S3_OPENBIS_CACHE"
                        ]
                        try:
                            prefix = preview_dict[dataset_type]
                            response = cache_client.get_object(
                                Bucket=cache_bucket,
                                Key=f"preview/{prefix}/{permID}.jpg",
                            )
                            if response["ResponseMetadata"]["HTTPStatusCode"] == 200:
                                img_data = response.get("Body").read()
                                img = Image.open(BytesIO(img_data))
                                fetched_preview = True
                            else:
                                img = Image.open("media/preview.jpg")
                        except Exception as e:
                            img = Image.open("media/preview.jpg")
                        preview = generate_preview(img, format=preview_format)

                    if not fetched_preview:
                        if size_mb > file_size_preview_limit:
                            st.toast(
                                f"{filename} is larger that {file_size_preview_limit} Mb ({size_mb:.2f} Mb)"
                            )
                        else:
                            if download_url is not None:
                                try:
                                    response = requests.get(download_url)
                                    if response.status_code != 200:
                                        source = (
                                            "Coscine" if kind == "LINK" else "openBIS"
                                        )
                                        raise RuntimeError(
                                            f"Cannot access file from {source}. You can still use the Download button."
                                        )
                                    data_bytes = BytesIO(response.content)
                                    if extension in [
                                        "jpg",
                                        "jpeg",
                                        "tiff",
                                        "tif",
                                        "tiff",
                                        "png",
                                        "bmp",
                                    ]:
                                        img = Image.open(data_bytes)

                                    else:
                                        with open(local_filename, "wb") as fh:
                                            fh.write(data_bytes.read())
                                        if (
                                            extension
                                            in VideoRenderer.ALLOWED_EXTENSIONS
                                        ):
                                            if (
                                                filename[4] == "-"
                                                and filename[10] == "T"
                                            ):
                                                name = filename.replace("_", "\n", 1)
                                                ds_type = dataset_type.replace("_", " ")
                                                name = name.replace(
                                                    f"{dataset_type}_", f"{ds_type} "
                                                )
                                                name = name.replace("_", "\n", 1)
                                            else:
                                                name = filename
                                            preview_format = "GIF"
                                            renderer = VideoRenderer()
                                            img = renderer.get_image(
                                                path=local_filename, name=name
                                            )
                                        elif extension in ["pptx"]:
                                            img = create_grid_from_ppt(local_filename)
                                        elif extension in ["docx"]:
                                            img = create_grid_from_doc(local_filename)
                                        elif extension in ["pdf"]:
                                            img = create_grid_from_pdf(local_filename)
                                        elif dataset_type == "TEM_DATA":
                                            if extension == "emd":
                                                img_array = get_tem_stack(
                                                    local_filename, False
                                                )
                                            elif extension in ["dm3", "dm4"]:
                                                img_array = get_tem_stack(
                                                    local_filename, False
                                                )
                                            elif extension in ["ser"]:
                                                img_array = get_tem_stack(
                                                    local_filename, False
                                                )
                                            else:
                                                img_array = np.array(
                                                    Image.open("media/preview.jpg")
                                                )
                                            img = Image.fromarray(img_array)
                                        elif dataset_type == "STEM_ALIGNED_DATA":
                                            if extension == "nc":
                                                img_array = get_tem_image(
                                                    local_filename
                                                )
                                            else:
                                                img_array = np.array(
                                                    Image.open("media/preview.jpg")
                                                )
                                            img = Image.fromarray(img_array)
                                        else:
                                            img = Image.open("media/preview.jpg")
                                    preview = generate_preview(
                                        img, format=preview_format
                                    )
                                except Exception as e:  # IOError,UnidentifiedImageError
                                    st.toast(e)

                    if os.path.exists(local_filename):
                        try:
                            os.unlink(local_filename)
                        except PermissionError:
                            pass

                try:
                    datetime.strptime(filename[:26], "%Y-%m-%dT%H-%M-%S.%f")
                    filename = filename[27:].replace(f"{dataset_type}_", "")
                    filename = "_".join(filename.split("_")[1:])
                except ValueError:
                    pass
                url = create_dataset_href(st.session_state.oBis, permID)
                entry = [
                    url,
                    preview,
                    name,
                    dataset_type,
                    kind,
                    reg_date,
                    permID,
                    filename,
                    extension,
                    path,
                    size_mb,
                ]
                data_all.append(entry + [ds.p[k] for k in md_keys])
                for opt in options:
                    entry.append(ds.p[opt])
                data.append(entry)
            st.session_state.df_files = pd.DataFrame(data, columns=cols)
            st.session_state.df_all = pd.DataFrame(data_all, columns=cols_all)

            if "Comments" in st.session_state.df_files.columns.to_list():
                st.session_state.df_files["Comments"] = st.session_state.df_files[
                    "Comments"
                ].apply(strip_tags)

        if len(st.session_state.df_files) == 0:
            st.warning("No datasets!")

placeholder = st.empty()

with placeholder.form("GetData"):

    if (
        st.session_state.df_files is not None
        and len(st.session_state.df_files)
        and st.session_state.experiment is not None
    ):

        selection = dataframe_with_selections(st.session_state.df_files)

        col1, col2, col3, col4, col5, col6 = st.columns(6)
        with col1:
            download_btn = st.form_submit_button(
                label="Download selection",
                type="primary",
            )
        with col2:
            download_all_btn = st.form_submit_button(
                label=f"Download all ({len(st.session_state.df_files)})",
                type="primary",
                help="Avoid with large files",
            )
        with col3:
            delete_btn = st.form_submit_button(
                label="Delete selection",
                type="primary",
            )
        with col4:
            delete_all_btn = st.form_submit_button(
                label=f"Delete all ({len(st.session_state.df_files)})",
                type="primary",
            )
        with col5:
            slides_btn = st.form_submit_button(
                label="Create slides",
                type="primary",
            )
        with col6:
            slides_all_btn = st.form_submit_button(
                label=f"Create slides ({len(st.session_state.df_files)})",
                type="primary",
            )

        if download_btn or download_all_btn or slides_btn or slides_all_btn:

            st.session_state.selection_deletion = pd.DataFrame()

            if download_btn or slides_btn:
                st.write("Your selection:")
                st.write(selection)

            if download_all_btn or slides_all_btn:
                selection = st.session_state.df_files
            st.session_state.selection = selection
            if ignore_non_image and slides_all_btn:
                img_extensions = {
                    ext.lstrip(".") for ext in Image.registered_extensions().keys()
                }
                selection = selection[selection.Extension.isin(img_extensions)]
            size_mb = selection["Size (Mb)"].sum()
            size_gb = size_mb / 1024
            max_size_gb = st.session_state.max_size // 1024

            if size_mb > st.session_state.max_size:
                st.error(
                    f"Too much data to download ({size_gb:.2f} Gb > {max_size_gb:d} Gb)   \n \
                        Please download files one by one"
                )
            else:
                oBis = st.session_state.oBis
                s3_clients = st.session_state.s3_clients.items()
                s3_bucket_names = st.session_state.s3_bucket_names
                if len(s3_bucket_names) == 0:
                    st.warning("You are not allowed to download files from Coscine")

                progress_bar = st.progress(0, text="Preparing files for download ...")

                for index, row in selection.reset_index().iterrows():
                    if len(selection) > 1:
                        progress_bar.progress(index / (len(selection) - 1))
                    placeholder = st.empty()

                    dataset = oBis.get_dataset(row["permID"])
                    mapping = {
                        code.lower(): oBis.get_property_type(code).label
                        for code in dataset.type.get_property_assignments().df.code.to_list()
                    }
                    data = {}
                    filename = dataset.file_list[0].split("/")[-1]
                    if filename.lower().endswith(
                        (
                            "jpg",
                            "jpeg",
                            "tiff",
                            "tif",
                            "tiff",
                            "png",
                            "bmp",
                        )
                    ):
                        local_path = temp_dir + "/" + filename
                        data["local_path"] = local_path
                        data["permId"] = dataset.permId
                        data["props"] = {
                            mapping[k]: v
                            for k, v in dataset.props.all().items()
                            if v is not None
                        }
                        data_dicts.append(data)

                    if row["Kind"] == "PHYSICAL":
                        ds = oBis.get_dataset(row["permID"])
                        file_list = ds.file_list
                        for path in file_list:
                            filename = path.rsplit("/", 1)[1]
                            files_to_download.append(filename)
                        ds.download(destination=temp_dir, create_default_folders=False)
                    elif row["Kind"] == "LINK":
                        s3_filename = row["S3 Path"].rsplit("/", 1)[1]
                        dms_df = oBis.get_external_data_management_systems().df
                        dms_df = dms_df.set_index("code")
                        bucket_name, s3_client = None, None
                        for dmscode, s3_client in s3_clients:
                            if dms_df["address"].loc[dmscode] in row["S3 Path"]:
                                bucket_name = s3_bucket_names[dmscode]
                                break
                        if bucket_name is None:
                            placeholder.warning(
                                f"Skipping {s3_filename}",
                            )
                            continue
                        if s3_file_exists(
                            filename=s3_filename,
                            bucket=bucket_name,
                            s3_client=s3_client,
                        ):
                            placeholder.success(
                                f"File {s3_filename} exists in Coscine",
                                icon="✅",
                            )
                            files_to_download.append(s3_filename)
                            with st.spinner("Getting file from S3"):
                                s3_client.download_file(
                                    Bucket=bucket_name,
                                    Key=s3_filename,
                                    Filename=temp_dir + "/" + s3_filename,
                                )
                            # time.sleep(1)

                            placeholder.empty()
                        else:
                            placeholder.error("File not found in Coscine", icon="🔥")
                progress_bar.empty()
            if download_btn or download_all_btn:
                data_dicts = []
            if slides_btn or slides_all_btn:
                files_to_download = []

        if delete_btn or delete_all_btn:
            st.session_state.requested_deletion = True
            if delete_all_btn:
                st.session_state.selection_deletion = st.session_state.df_files
            else:
                st.session_state.selection_deletion = selection

        # Dry run
        if len(st.session_state.selection_deletion):
            warning_messages = []
            for index, row in st.session_state.selection_deletion.iterrows():
                perm_id = row["permID"]
                ds = st.session_state.oBis.get_dataset(perm_id)
                # Design choice: only the person who uploaded the file can delete it in the GUI
                if st.session_state.openbis_username != ds.registrator:
                    warning_messages.append(
                        f"You're not allowed to delete this dataset: {perm_id}, registered by {ds.registrator}"
                    )
                    continue
                # We check if the s3 client is able to delete the file with the credentials given at login
                if row["Kind"] == "LINK":
                    s3_filename = row["S3 Path"].rsplit("/", 1)[1]
                    s3_client = st.session_state.s3_client
                    bucket_name = st.session_state.s3_bucket_name
                    dms_code = st.session_state.obis_dmscode
                    if s3_file_exists(
                        filename=s3_filename,
                        bucket=bucket_name,
                        s3_client=s3_client,
                    ):
                        try:
                            key = "dummy_file"
                            dummy_path = st.session_state.temp_dir + "/" + key
                            with open(dummy_path, "w") as f:
                                f.write("This is a test file.\n" * 1000)
                            s3_file_upload(dummy_path, bucket_name, key, s3_client)
                            s3_client.delete_object(Bucket=bucket_name, Key=key)
                            os.path.unlink(dummy_path)
                        except Exception as e:
                            if "AccessDenied" in str(e):
                                warning_messages.append(
                                    f"You're not allowed to delete this file: {s3_filename}  \n"
                                    + f"Access crendentials do not allow the DeleteObject operation  \n"
                                    + "Are you using the right Coscine config file?"
                                )
                    else:
                        warning_messages.append(
                            f"You're not allowed to delete this file: {s3_filename}  \n"
                            + f"Client cannot find file in bucket {bucket_name} registered with DMS code {dms_code}  \n"
                            + "Are you using the right Coscine config file?"
                        )
            if len(warning_messages):
                st.warning("  \n".join(warning_messages))
            st.write("Your selection:")
            st.write(st.session_state.selection_deletion)

        if st.session_state.requested_deletion and len(
            st.session_state.selection_deletion
        ):
            confirm_del_btn = st.form_submit_button(
                label="Confirm deletion",
                type="primary",
                disabled=not st.session_state.requested_deletion,
            )
        else:
            st.session_state.requested_deletion = False

        # Delete files upon confirmation
        if st.session_state.requested_deletion and confirm_del_btn:
            with st.spinner("Deleting ..."):
                for index, row in st.session_state.selection_deletion.iterrows():
                    perm_id = row["permID"]
                    ds = st.session_state.oBis.get_dataset(perm_id)

                    # Design choice: only the person who uploaded the file can delete it in the GUI
                    if st.session_state.openbis_username != ds.registrator:
                        continue

                    # We check if the s3 client is able to delete the file with the credentials given at login
                    if row["Kind"] == "LINK":
                        s3_filename = row["S3 Path"].rsplit("/", 1)[1]
                        s3_client = st.session_state.s3_client
                        bucket_name = st.session_state.s3_bucket_name
                        dms_code = st.session_state.obis_dmscode

                        if s3_file_exists(
                            filename=s3_filename,
                            bucket=bucket_name,
                            s3_client=s3_client,
                        ):
                            try:
                                s3_client.delete_object(
                                    Bucket=bucket_name, Key=s3_filename
                                )
                                ds.delete(
                                    reason="Requested deletion through companion app."
                                )
                            except Exception as e:
                                continue

                    # For data stored on server
                    if row["Kind"] == "PHYSICAL":
                        ds.delete(reason="Requested deletion through companion app.")

            st.session_state.requested_deletion = False
            placeholder.empty()


# maybe a more elaborate logic with python tempdirs
# it seems to work at the moment - but keep in mind

if len(files_to_download) > 1:
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    zip_name = "openBIS_download_" + timestamp + ".zip"
    st.session_state.df_all.drop("Preview", axis=1).to_csv(
        temp_dir + "/metadata.csv", index=False, encoding="utf-8-sig"
    )
    with st.spinner("Creating zip archive"):
        with ZipFile(temp_dir + "/" + zip_name, "w", ZIP_DEFLATED) as zf:
            for file in files_to_download:
                zf.write(
                    filename=temp_dir + "/" + file,
                    arcname=file,
                )
            zf.write(temp_dir + "/metadata.csv", arcname="metadata.csv")
    with open(temp_dir + "/" + zip_name, "rb") as f:
        download_btn = st.download_button(
            label="Download zip archive",
            data=f,
            file_name=zip_name,
        )
elif len(files_to_download) == 1:
    with open(temp_dir + "/" + files_to_download[0], "rb") as f:
        download_btn = st.download_button(
            label="Download file",
            data=f,
            file_name=files_to_download[0],
        )

if len(data_dicts) > 0:
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    odp_name = "openBIS_download_" + timestamp + ".odp"
    odp_path = temp_dir + "/" + odp_name
    with st.spinner("Creating presentation"):
        create_slides(st.session_state.oBis, data_dicts, odp_path)
    with open(odp_path, "rb") as f:
        download_btn_presentation = st.download_button(
            label="Download presentation",
            data=f,
            file_name=odp_name,
        )

#
# cleanup
#


for file in os.scandir(temp_dir):
    if file.is_file():
        try:
            os.unlink(file)
        except PermissionError:
            pass
