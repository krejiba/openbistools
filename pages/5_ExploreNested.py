import streamlit as st
import warnings
import json
import pandas as pd
import numpy as np
import json
import ast
import plotly.express as px

warnings.filterwarnings(action="ignore", category=FutureWarning)
warnings.filterwarnings(action="ignore", category=pd.errors.PerformanceWarning)

st.set_page_config(
    page_title="Explore nested propertiess",
    page_icon="media/SFB1394_icon.jpg",
    layout="wide",
)


try:
    setup_done = st.session_state.setup_done
except AttributeError as e:
    st.switch_page("Hello.py")
st.sidebar.image("media/SFB1394_TitleImage_Cropped.png")
st.sidebar.write("Logged into openBIS: ", st.session_state.logged_in)
st.sidebar.write("OpenBIS Upload OK: ", st.session_state.openbis_upload_allowed)
st.sidebar.write("S3 Upload OK: ", st.session_state.s3_upload_ok)
st.sidebar.write("S3 Download OK: ", st.session_state.s3_download_ok)

st.title("Explore nested properties and semantics")
st.write(
    """
    Some properties contain json like strings.
    Semantic annotations are displayed when available.
    """
)


def auto_chart(df, col):
    try:
        s = df[col]
        st.write(f"Missing values: {s.isna().sum()}")

        if not pd.api.types.is_numeric_dtype(s):
            counts = s.astype(str).value_counts(dropna=False).head(15)
            fig = px.bar(
                x=[str(x) for x in counts.index],
                y=counts.values.tolist(),
                labels={"x": col, "y": "Count"},
                title=col,
            )
            st.plotly_chart(fig, width="stretch")
            return

        if pd.api.types.is_float_dtype(s):
            st.write(s.describe().to_string())
            fig = px.histogram(
                x=s.dropna().tolist(),
                nbins=20,
                labels={"x": col},
                title=col,
            )
            st.plotly_chart(fig, width="stretch")
            return

        if pd.api.types.is_integer_dtype(s):
            st.write(s.describe().to_string())
            if s.nunique() < 30:
                counts = s.value_counts().sort_index()
                fig = px.bar(
                    x=[str(x) for x in counts.index],
                    y=counts.values.tolist(),
                    labels={"x": col, "y": "Count"},
                    title=col,
                )
            else:
                fig = px.histogram(
                    x=s.dropna().tolist(),
                    nbins=20,
                    labels={"x": col},
                    title=col,
                )
            st.plotly_chart(fig, width="stretch")
            return

        st.write(s.head().to_string())

    except BaseException:
        return


o = st.session_state.oBis
if setup_done:
    mapping = {
        code: o.get_property_type(code).label
        for code in o.get_property_types().df.code.to_list()
    }
    semantic_annotations_df = st.session_state.oBis.get_semantic_annotations().df
    semantic_mappings = (
        semantic_annotations_df.groupby("propertyType")["predicateAccessionId"]
        .apply(list)
        .to_dict()
    )
    semantic_mappings = {
        st.session_state.oBis.get_property_type(k).label: v
        for k, v in semantic_mappings.items()
    }
    json_dict = json.loads(
        o.get_object("/ELN_SETTINGS/GENERAL_ELN_SETTINGS").props("nested_properties")
    )
    projects = ["All"] + st.session_state.oBis.get_projects().df.identifier.to_list()
    selected_project = st.selectbox("Select projects:", projects, index=0)
    project = None if selected_project == "All" else selected_project
else:
    st.stop()


def get_entities(o, type, project, where, props, attrs):
    for getter_method in ("get_objects", "get_datasets"):
        try:
            entities = getattr(o, getter_method)(
                type=type,
                project=project,
                where=where,
                props=props,
                attrs=attrs,
            )
            if len(entities) == 0:
                continue
            else:
                return entities
        except Exception as e:
            continue
    return None


queries = [
    ("DEFECTS_INFO", "SAMPLE", {"defects": "*"}, None),
    ("IMAGE_CONTENT", "SEM_DATA", {"image_content": "*"}, ["registrator.permId"]),
]

for col_name, entity_type, where_dict, attrs_list in queries:
    st.write("---")
    try:
        text = o.get_object_type(entity_type).description
    except:
        try:
            text = o.get_dataset_type(entity_type).description
        except:
            text = ""
    if text:
        st.write(f"[{entity_type}] " + text)
    with st.spinner("Finding data..."):
        entities = get_entities(
            o,
            type=entity_type,
            project=project,
            where=where_dict,
            props="*",
            attrs=attrs_list,
        )
    if entities is None or len(entities) == 0:
        st.warning("No data matching the search criteria was found.")
        continue
    df = entities.df
    if col_name not in df.columns:
        st.warning("No data matching the search criteria was found.")
        continue
    if "registrator.permId" in df.columns:
        df["registrator"] = df["registrator.permId"].map(lambda x: dict(x)["permId"])
        df.drop(columns=["registrator.permId"], inplace=True)
    df.replace("", np.nan, inplace=True)
    df.dropna(axis=1, how="all", inplace=True)
    df = df[df[col_name].fillna("").str.startswith("{")]
    flat = pd.json_normalize(df[col_name].apply(ast.literal_eval), sep="_")
    flat.columns = ["+" + col for col in flat.columns]
    df = df.drop(columns=[col_name]).join(flat)
    df.rename(columns=mapping, inplace=True)
    df.rename(columns={"sample": "object"}, inplace=True)
    st.dataframe(df.astype(str))

    ncols = 4
    cols = st.columns(ncols)
    COLS_IGNORE = [
        "registrator.permId",
        "size",
        "status",
        "presentInArchive",
        "type",
        "permId",
        "identifier",
        "$name" "s3_download_link",
    ]
    valid_cols = [col for col in sorted(df.columns) if not df[col].isna().all()]
    valid_cols = [col for col in valid_cols if col not in COLS_IGNORE]

    for i, col in enumerate(valid_cols):
        with cols[i % ncols]:
            urls = semantic_mappings.get(col)
            match = next((k for k in json_dict.keys() if col.endswith(k)), None)
            header_col, link_col = st.columns([0.8, 0.2])
            header_col.markdown(f"**{col}**")

            if urls:
                col_display = " ".join(f"[🔗]({u})" for u in urls)
                link_col.markdown(col_display)
            elif match:
                quantity = json_dict[match]["quantity"]
                unit = json_dict[match]["unit"]
                urls = quantity + unit
                col_display = " ".join(f"[🔗]({u})" for u in urls)
                link_col.markdown(col_display)
            else:
                link_col.write("")

            with st.expander("More"):
                auto_chart(df, col)
