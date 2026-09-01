from typing import Dict, List, Set, Optional
import streamlit as st
from pybis import Openbis
import warnings
import networkx as nx
import plotly.graph_objects as go
import plotly.io as pio
import json
import datetime
from pandas import DataFrame
import pandas as pd


warnings.filterwarnings(action="ignore", category=FutureWarning)
warnings.filterwarnings(action="ignore", category=pd.errors.PerformanceWarning)


TERMINAL_OBJECT_TYPES = [
    "PUBLICATION",
    "ELECTRON_MICROSCOPE",
    "MECH_TEST_DEVICE",
    "FURNACE",
    "INSTRUMENT",
    "CHEMICAL",
    "PREPARATION_MATERIAL",
    "SOFTWARE",
    "INTERATOMIC_POTENTIAL",
    "PSEUDOPOTENTIAL",
    "COMPUTE_RESOURCE",
    "CRYSTALLINE_MATERIAL",
    "AMORPHOUS_MATERIAL",
    "MATERIAL",
    "ELECTRODE",
]

OBJECT_TYPES_COLORS = {
    "SAMPLE": "#0069b0",
    "SAMPLE_STORAGE": "#166499",
    "HEAT_TREATMENT_PROTOCOL": "#ef5350",
    "CASTING_PROTOCOL": "#f44336",
    "MOLD": "#772823",
    "THIN_FILM_SYNTHESIS": "#b71c1c",
    "CUTTING_PROTOCOL": "#fdd835",
    "FIB_MILLING_PROTOCOL": "#fff59d",
    "METALLOGRAPHY_PROTOCOL": "#004d40",
    "METALLOGRAPHY_GRINDING_PROTOCOL": "#00796b",
    "METALLOGRAPHY_POLISHING_PROTOCOL": "#009688",
    "METALLOGRAPHY_ELECTROPOLISHING_PROTOCOL": "#4db6ac",
    "METALLOGRAPHY_POLISHING_WITH_ETCHING_PROTOCOL": "#b2dfdb",
    "MICRO_MECH_EXP": "#1a237e",
    "MECH_EXP": "#3f51b5",
    "MECH_TEST_PROTOCOL": "#9fa8da",
    "MECH_TEST_DEVICE": "#f8bbd0",
    "ELECTRON_MICROSCOPE": "#f06292",
    "FURNACE": "#e91e63",
    "INSTRUMENT": "#880e4f",
    "SOFTWARE": "#ffcc80",
    "CHEMICAL": "#ffccbc",
    "PREPARATION_MATERIAL": "#ff8a65",
    "POINT_MEASUREMENT": "#9c27b0",
    "SEM_EXP": "#9c27b0",
    "EXPERIMENTAL_STEP": "#ba68c8",
    "ENTRY": "#e1bee7",
    "COMPUTE_RESOURCE": "#b7ccc5",
    "INTERATOMIC_POTENTIAL": "#7fffd4",
    "PSEUDOPOTENTIAL": "#a1e6cf",
    "SIMULATION_EXP": "#afb42b",
    "SIMULATION_ARTEFACT": "#cddc39",
    "EBSDSIM_SCREENPATTERN_PROTOCOL": "#33691e",
    "EBSDSIM_MONTECARLO_PROTOCOL": "#689f38",
    "EBSDSIM_MASTER_PROTOCOL": "#8bc34a",
    "PYIRON_JOB_GENERIC": "#3592cb",
    "PYIRON_JOB_LAMMPS": "#81d4fa",
    "PYIRON_JOB_VASP": "#03a9f4",
    "PYIRON_JOB_MURNAGHAN": "#01579b",
    "PUBLICATION": "#b0bec5",
    "ENGINEERED_MATERIAL": "#57f9ff",
    "CRYSTALLINE_MATERIAL": "#1af7ff",
    "AMORPHOUS_MATERIAL": "#1af7ff",
    "MATERIAL": "#138387",
    "ELECTRODE": "#f4f345",
    "ELECTROCHEM_PROTOCOL": "#f7f89b",
    "CALPHAD_DATABASE": "#5eeb34",
    "PHASE_DIAGRAM": "#252850",
}


set_diff = set(TERMINAL_OBJECT_TYPES).difference(OBJECT_TYPES_COLORS)
set_diff_str = ", ".join(set_diff)
assert len(set_diff) == 0, f"Please include a color for {set_diff_str}"


class DualKeyDict(dict):
    def __init__(self):
        super().__init__()
        self.__key2_to_key1 = {}
        self.__key1_to_key2 = {}

    def __getitem__(self, key):
        if key in self.__key2_to_key1:
            key1 = self.__key2_to_key1[key]
            return super().__getitem__(key1)
        elif key in self:
            return super().__getitem__(key)
        else:
            raise KeyError(f"Key {key} not found!")

    def get_secondary_key(self, key):
        return self.__key1_to_key2[key]

    def __setitem__(self, key, value):
        if key not in self.__key2_to_key1:
            super().__setitem__(key, value)
        else:
            key1 = self.__key2_to_key1[key]
            super().__setitem__(key1, value)

    def __contains__(self, key):
        return super().__contains__(key) or key in self.__key2_to_key1

    def __repr__(self):
        items = []
        for key1, value in self.items():
            key2 = self.__key1_to_key2[key1]
            items.append(f"({repr(key1)}, {repr(key2)}): {repr(value)}")
        return "{" + ", ".join(items) + "}"

    def add(self, key1, key2, value):
        super().__setitem__(key1, value)
        self.__key2_to_key1[key2] = key1
        self.__key1_to_key2[key1] = key2


class OpenbisRelatedObjectsFinder:
    """
    A class to query an openBIS instance for samples and create a graph based on the results.

    Attributes:
        openbis_client (pybis.Openbis): An openBIS client after login.
        object_cache (dict): A dictionary containing metadata about all the objects.
        property_types (dict): A mapping from the codes of the propertyTypes to their labels.
    """

    def __init__(self, openbis_client: Openbis):
        """
        Initializes the object and caches the relevant metadata.
        """
        self.openbis_client = openbis_client
        self._cache_property_types()
        self._cache_objects()

    def find_related_objects(
        self,
        permid: str,
        skip_terminal: bool = False,
        stop_protocol: bool = False,
        skip_simulation: bool = False,
        collections: Optional[List[str]] = None,
        elements: Optional[List[str]] = None,
    ) -> nx.DiGraph:
        """
        Finds related objects recursively, forming a graph.

        Args:
            permid (str): The permId of the first object (of type `SAMPLE`). We start by looking at objects linked to it.
            skip_terminal (bool, optional): A flag indicating whether to include terminal objects.
                                            Default is `False`.
            stop_protocol (bool, optional): A flag indicating whether to stop searching when reaching protocols.
                                            Default is `False`.
            skip_simulation (bool, optional): A flag indicating whether to include simulation-related objects.
                                              Default is `False`.
            collections (list, optional): A list of permIds of collections used to restrict search.
                                          Default is `False`.
        Returns:
            graph (networkx.DiGraph): A networkx directed graph with objects as nodes.

        Notes:
            - Protocols are objectTypes that have codes ending with `_PROTOCOL`.
            - This method might modify the `object_cache` and `property_types` attributes of the class.


        """
        # Initialize

        visited = set()  # Tracks visited nodes, a node is identified using its permId
        relationships = []  # Stores [parent, child] relationships
        nodes = {}  # Stores node properties
        collections = collections or []

        # Start the recursive fetching with the main object

        self._fetch_related_objects_recursive(
            permid,
            nodes,
            relationships,
            visited,
            skip_terminal,
            stop_protocol,
            skip_simulation,
            collections,
            elements,
        )

        # Pack the results in a networkx directed graph

        graph = nx.DiGraph()
        for permid, node in nodes.items():
            graph.add_node(permid, **node)
        for parent, child in relationships:
            if parent in graph and child in graph:
                graph.add_edge(parent, child)
        return graph

    def _fetch_related_objects_recursive(
        self,
        permid: str,
        nodes: Dict[str, Dict[str, Optional[str | Dict | DataFrame]]],
        relationships: List[List[str]],
        visited: Set[str],
        skip_terminal: bool,
        stop_protocol: bool,
        skip_simulation: bool,
        collections: List[str],
        elements: List[str],
    ):
        """
        Recursively fetches parents and children of the given object,
        stopping if no more parents or children exist (terminal nodes).

        Args:
            permid (str): The permId of the current object.
            nodes (dict): A dictionary containing metadata about the about the objects encountered so far.
            relationships (list): A list containing parent-child relationships between the objects encountered so far.
            visited (set): A set containing the permIds of the objects encountered so far.
            skip_terminal (bool): A flag indicating whether to include terminal objects.
            stop_protocol (bool): A flag indicating whether to stop searching when reaching protocols.
            skip_simulation (bool): A flag indicating whether to include simulation-related objects.
            collections (list): A list of permIds of collections used to restrict search.
        """
        if permid in visited:
            return
        visited.add(permid)

        current_object_info = self.object_cache[permid]

        if current_object_info["experiment_permid"] is None:
            return
        # Get necessary metadata for current object

        current_object_code = current_object_info["code"]
        current_object_type = current_object_info["type"]
        current_object_location = current_object_info["location"]
        current_object_collection = current_object_info["experiment_permid"]
        current_object_elements = current_object_info["list_of_elements"]

        # Check if any of the search restrictions should be applied

        skip_simulation_test = skip_simulation and self.is_simulation_related(
            current_object_type, current_object_location
        )
        skip_terminal_test = skip_terminal and (
            current_object_type in TERMINAL_OBJECT_TYPES
        )
        skip_collection_test = (
            (len(collections) > 0)
            and (current_object_type == "SAMPLE")
            and (current_object_collection not in collections)
        )
        skip_elements_test = (
            elements is not None
            and len(elements) > 0
            and (current_object_type == "SAMPLE")
            and all(item not in elements for item in current_object_elements.split(","))
        )

        if (
            skip_terminal_test
            or skip_simulation_test
            or skip_collection_test
            or skip_elements_test
        ):
            return
        # Get metadata for the nodes of graph

        experiment = current_object_info["experiment_code"]
        project = current_object_info["project_code"]
        datasets = self.openbis_client.get_datasets(
            props="*", sample=self.object_cache.get_secondary_key(permid)
        )

        datasets_df = datasets.df
        describe_df = None

        # Store metadata in a dictionary

        nodes[permid] = {
            "properties": current_object_info["properties"],
            "name": current_object_info["name"],
            "permid": permid,
            "code": current_object_code,
            "type": current_object_type,
            "experiment": experiment,
            "project": project,
            "datasets": datasets_df.type.value_counts().to_dict(),
            "datasets_summary": describe_df,
        }
        if stop_protocol and current_object_type.endswith("_PROTOCOL"):
            return
        if current_object_type in TERMINAL_OBJECT_TYPES:
            return
        # Fetch the identifiers of parents and children of the current object (A -> B == A is a parent of B)

        relatives = [
            (parent, 1) for parent in current_object_info["parents"]
        ]  # parent -> current_object
        relatives += [
            (child, -1) for child in current_object_info["children"]
        ]  # current_object -> child

        for relative_identifier, order in relatives:
            if relative_identifier not in self.object_cache:
                relative = self.openbis_client.get_object(
                    relative_identifier, props="*"
                )
                # Update cache if neessary

                if relative.experiment is None:
                    relative_experiment_code = None
                    relative_experiment_permid = None
                else:
                    relative_experiment_code = relative.experiment.code
                    relative_experiment_permid = relative.experiment.permId
                if relative.project is None:
                    relative_project_code = None
                else:
                    relative_project_code = relative.project.code
                self.object_cache.add(
                    relative.permId,
                    relative.identifier,
                    {
                        "permid": relative.permId,
                        "identifier": relative.identifier,
                        "code": relative.code,
                        "type": relative.type.code,
                        "experiment_code": relative_experiment_code,
                        "experiment_permid": relative_experiment_permid,
                        "project_code": relative_project_code,
                        "parents": relative.parents,
                        "children": relative.children,
                        "name": relative.p["$name"],
                        "location": relative.p["location"],
                        "list_of_elements": relative.p["list_of_elements"],
                        "properties": relative.props.all(),
                    },
                )
            # Get necessary metadata for linked object

            relative_info = self.object_cache[relative_identifier]
            relative_permid = relative_info["permid"]
            relative_type = relative_info["type"]
            relative_location = relative_info["location"]
            relative_collection = relative_info["experiment_permid"]
            relative_elements = relative_info["list_of_elements"]

            if relative_collection == None:
                continue
            # Check if any of the search restrictions should be applied

            skip_simulation_test = skip_simulation and self.is_simulation_related(
                relative_type, relative_location
            )
            skip_terminal_test = skip_terminal and (
                relative_type in TERMINAL_OBJECT_TYPES
            )
            skip_collection_test = (
                (len(collections) > 0)
                and (relative_type == "SAMPLE")
                and (relative_collection not in collections)
            )
            skip_elements_test = (
                elements is not None
                and len(elements) > 0
                and (relative_elements == "SAMPLE")
                and all(item not in elements for item in relative_elements.split(","))
            )
            if not (
                skip_terminal_test
                or skip_simulation_test
                or skip_collection_test
                or skip_elements_test
            ):
                relationships.append([relative_permid, permid][::order])
            self._fetch_related_objects_recursive(
                relative_permid,
                nodes,
                relationships,
                visited,
                skip_terminal,
                stop_protocol,
                skip_simulation,
                collections,
                elements,
            )

    def _cache_objects(self):
        """
        Fetches metadata regarding all objects at startup.

        This method modifies the `object_cache` attribute of the class.

        Returns:
            None
        """
        batch_size = 1000
        results = []
        for object_type in self.property_types["object_types"]:
            start = 0
            if object_type in ["CRYSTALLINE_MATERIAL", "MATERIAL"]:
                continue
            while True:
                df = self.openbis_client.get_objects(
                    type=object_type,
                    attrs=[
                        "experiment.permId",
                        "experiment.code",
                        "project.code",
                        "parents",
                        "children",
                    ],
                    props="*",
                    start_with=start,
                    count=batch_size,
                ).df
                if len(df):
                    results.append(df)
                    start += batch_size
                else:
                    break

        objects_df = pd.concat(results, axis=0, ignore_index=True)
        for key in self.property_types["property_types"]:
            if key not in objects_df.columns:
                objects_df[key] = ""
        objects_df["columns"] = objects_df["type"].map(
            lambda x: self.property_types["object_types"].get(x, [])
        )
        objects_df["properties"] = objects_df.apply(
            lambda x: x[x["columns"]].to_dict(), axis=1
        )
        objects_df.columns = objects_df.columns.str.lower()
        objects_df["experiment_permid"] = objects_df["experiment.permid"].apply(
            lambda x: dict(x).get("permId")
        )
        objects_df["code"] = objects_df["identifier"].str.split("/").str[-1]
        objects_df["experiment_code"] = objects_df["experiment.code"]
        objects_df["project_code"] = objects_df["project.code"]
        objects_df["name"] = objects_df["$name"]

        self.object_cache = DualKeyDict()

        cols = [
            "permid",
            "identifier",
            "code",
            "type",
            "experiment_code",
            "experiment_permid",
            "project_code",
            "parents",
            "children",
            "name",
            "location",
            "list_of_elements",
            "properties",
        ]
        objects_df = objects_df[cols]

        for _, row in objects_df.iterrows():
            key1, key2, value = row["permid"], row["identifier"], row.to_dict()
            self.object_cache.add(key1, key2, value)

    def _cache_property_types(self):
        """
        Fetches metadata regarding all propertyTypes at startup.

        This method modifies the `property_types` attribute of the class.

        Returns:
            None
        """
        property_types = {
            "property_types": {},
            "object_types": {},
            "dataset_types": {},
        }
        for object_type in self.openbis_client.get_object_types():
            df = object_type.get_property_assignments().df
            if "code" in df.columns:
                property_types["object_types"][object_type.code] = df["code"].to_list()
        for dataset_type in self.openbis_client.get_dataset_types():
            df = dataset_type.get_property_assignments().df
            if "propertyType" in df.columns:
                property_types["dataset_types"][dataset_type.code] = df[
                    "propertyType"
                ].to_list()
        property_types_df = self.openbis_client.get_property_types().df
        property_types_df = property_types_df.set_index("code")
        property_types["property_types"] = property_types_df["label"].to_dict()
        self.property_types = property_types

    def is_simulation_related(self, object_type_code: str, location: str) -> bool:
        """
        Determines whether an object is related to a simulation based on its type and location.

        Args:
            object_type (str): The type of the object (e.g., "SAMPLE", "SEM_EXP", "SIMULATION_EXP").
            location (str): The location of the object (e.g., "virtual", ...).

        Returns:
            bool: `True` if the object is related to a simulation, otherwise `False`.
        """
        return (
            (object_type_code == "SAMPLE" and location == "virtual")
            or ("SIM" in object_type_code)
            or ("PYIRON" in object_type_code)
            or ("POTENTIAL" in object_type_code)
        )


class OpenbisHierarchicalGraphPlotter:
    def __init__(self, graph=nx.DiGraph(), file_path: str = "", property_types=None):
        self.graph = graph
        if file_path:
            self._load_graph_from_file(file_path)
        self.property_types = property_types

    def _load_graph_from_file(self, file_path):
        """Loads the graph from a JSON file."""
        with open(file_path, "r") as fh:
            data = fh.read()
            self.graph = nx.node_link_graph(json.loads(data))

    def generate_figure(self, datasets_metadata_cols=2, column_max_chars=30):
        """Generates the figure for the hierarchical graph visualization."""
        pos = self._hierarchical_layout(self.graph)
        edge_traces = self._create_edge_traces(pos)
        node_trace = self._create_node_trace(
            pos, datasets_metadata_cols, column_max_chars
        )
        legend_traces = self._create_legend_traces()
        layout = self._create_layout()
        return go.Figure(
            data=edge_traces + [node_trace] + legend_traces,
            layout=layout,
        )

    def _create_edge_traces(self, pos):
        """Creates the edge traces for the graph."""
        edge_traces = []
        object_types = nx.get_node_attributes(self.graph, "type")
        for object_type, edge_color in OBJECT_TYPES_COLORS.items():
            edge_trace = self._create_single_edge_trace(
                object_type, edge_color, pos, object_types
            )
            edge_traces.append(edge_trace)
        return edge_traces

    def _create_single_edge_trace(self, object_type, edge_color, pos, object_types):
        """Creates a single edge trace based on object type."""
        edge_x, edge_y = [], []
        for edge in self.graph.edges():
            if object_types[edge[0]] == object_type:
                x0, y0 = pos[edge[0]]
                x1, y1 = pos[edge[1]]
                edge_x += [x0, x1, None]
                edge_y += [y0, y1, None]
        return go.Scatter(
            x=edge_x,
            y=edge_y,
            mode="lines+markers",
            line=dict(width=1, color=edge_color),
            marker=dict(symbol="arrow-up", size=10, angleref="previous"),
            hoverinfo="none",
            showlegend=False,
        )

    def _create_node_trace(self, pos, datasets_metadata_cols, column_max_chars):
        """Creates the node trace."""
        (
            node_x,
            node_y,
            hovertext,
            node_colors,
            node_sizes,
            line_colors,
            object_types,
        ) = ([], [], [], [], [], [], [])
        for i, (node, data) in enumerate(self.graph.nodes(data=True)):
            x, y = pos[node]
            node_x.append(x)
            node_y.append(y)
            metadata_str = self._generate_node_metadata(
                node, data, datasets_metadata_cols, column_max_chars
            )
            hovertext.append(metadata_str)
            node_color = OBJECT_TYPES_COLORS.get(data.get("type"), "#808080")
            node_size = 20 if data.get("type") == "SAMPLE" else 12
            line_color = "#ff0000" if i == 0 else "#ffffff"
            node_colors.append(node_color)
            node_sizes.append(node_size)
            line_colors.append(line_color)
            object_types.append(data.get("type"))

        return go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers",
            hoverinfo="text",
            hoverlabel=dict(font_family="Noto Sans Mono, monospace"),  # Monospace
            text=hovertext,
            marker=dict(
                showscale=False,
                color=node_colors,
                size=node_sizes,
                line_color=line_colors,
                line_width=2,
                opacity=0.75,
            ),
            showlegend=False,
        )

    def _generate_node_metadata(
        self, node, data, datasets_metadata_cols, column_max_chars
    ):
        """Generates the metadata string for each node."""
        name = data.get("name")
        object_type = data.get("type")
        project = data.get("project")
        experiment = data.get("experiment")
        permId = node
        comments = self._extract_comments(data)
        properties_text = self._generate_properties_text(data)
        datasets_text = self._generate_datasets_text(
            data, datasets_metadata_cols, column_max_chars
        )
        metadata_str = (
            f"Name: <b>{name}</b><br>Type: <b>{object_type}</b><br>PermId: {permId}<br>"
            + f"Project: {project}<br>Experiment: {experiment}<br>Comments: {comments}<br>Properties:<br>{properties_text}"
        )
        if datasets_text:
            metadata_str += f"Datasets:<br>{datasets_text}"
        return metadata_str

    def _extract_comments(self, data):
        """Extracts and formats the comments for a node."""
        comments = data.get("properties", {}).get("COMMENTS")
        if isinstance(comments, str) and comments:
            return comments.replace("\n", "|")[:50]
        return ""

    def _generate_properties_text(self, data):
        """Generates the properties text for the node metadata."""
        properties_text = ""
        for key, value in data.get("properties", {}).items():
            key = key.upper()
            if key in ["$NAME", "COMMENTS"]:
                continue
            key = self.property_types.get(key, key)
            if value and str(value) != "nan":
                value = str(value)[:50]  # Truncate
                if isinstance(value, datetime.datetime):
                    value = value.isoformat()
                properties_text += f">>> {key}: {value}<br>"
        return properties_text

    def _generate_datasets_text(self, data, datasets_metadata_cols, column_max_chars):
        """Generates the datasets text for the node metadata."""
        datasets_text = ""
        for key, value in sorted(data.get("datasets", {}).items()):
            key = key.upper()
            if key in ["$NAME"]:
                continue
            key = self.property_types.get(key, key)
            if value and str(value) != "nan":
                datasets_text += f">>> {key}: {value}<br>"
        describe_df = data.get("datasets_summary")
        if describe_df is not None:
            describe_df = describe_df.drop(
                ["$NAME", "S3_DOWNLOAD_LINK"], axis=1, errors="ignore"
            )
            describe_df = describe_df.rename(columns=self.property_types)
            for i in range(0, len(describe_df.columns), datasets_metadata_cols):
                section = describe_df.iloc[:, i : i + datasets_metadata_cols]
                section_str = section.to_string(
                    justify="left", index=False, col_space=column_max_chars
                )
                datasets_text += section_str.replace("\n", "<br>") + "<br>"
        return datasets_text

    def _create_legend_traces(self):
        """Creates the legend traces for the graph."""
        return [
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                name=k,
                marker=dict(size=10, color=v, opacity=0.75),
            )
            for k, v in OBJECT_TYPES_COLORS.items()
            if k in set(nx.get_node_attributes(self.graph, "type").values())
        ]

    def _create_layout(self):
        """Creates the layout for the graph figure."""
        return go.Layout(
            title="Extended Hierarchical Graph",
            titlefont_size=16,
            showlegend=True,
            hoverlabel=dict(align="left"),
            hovermode="closest",
            margin=dict(b=0, l=0, r=0, t=40),
            xaxis=dict(showgrid=False, zeroline=False, visible=False),
            yaxis=dict(showgrid=False, zeroline=False, visible=False),
            clickmode="event+select",
        )

    def _hierarchical_layout(self, graph, width=1.0, height=1.0):
        """Computes the hierarchical layout (similar to a tree layout) of a directed graph."""
        pos = {}
        levels = self._compute_levels(graph)
        level_widths = self._compute_level_widths(levels)
        y_spacing = height / (len(levels) - 1) if len(levels) > 1 else height
        for level, nodes in levels.items():
            x_spacing = width / (level_widths[level] + 1)
            for i, node in enumerate(nodes):
                pos[node] = (x_spacing * (i + 1), -y_spacing * level)
        return pos

    def _compute_levels(self, G):
        """Computes the levels of the nodes."""
        levels = {}

        def recurse(node, level):
            if level not in levels:
                levels[level] = []
            levels[level].append(node)
            for child in G.successors(node):
                recurse(child, level + 1)

        roots = [n for n, d in G.in_degree() if d == 0]
        for root in roots:
            recurse(root, 0)
        return levels

    def _compute_level_widths(self, levels):
        """Computes the number of nodes at each level."""
        return {level: len(nodes) for level, nodes in levels.items()}


st.set_page_config(
    page_title="View samples",
    page_icon="media/SFB1394_icon.jpg",
    layout="wide",
)


try:
    _ = st.session_state.setup_done
    if "finder" not in st.session_state:
        with st.spinner("Tracking sample lineage ..."):
            st.session_state.finder = OpenbisRelatedObjectsFinder(st.session_state.oBis)
    if "figure" not in st.session_state:
        st.session_state.figure = None
except AttributeError as e:
    st.switch_page("Hello.py")
st.sidebar.image("media/SFB1394_TitleImage_Cropped.png")
st.sidebar.write("Logged into openBIS: ", st.session_state.logged_in)
st.sidebar.write("OpenBIS Upload OK: ", st.session_state.openbis_upload_allowed)
st.sidebar.write("S3 Upload OK: ", st.session_state.s3_upload_ok)
st.sidebar.write("S3 Download OK: ", st.session_state.s3_download_ok)


st.title("Interactive Hierarchical Graph")
st.write(
    """
    - Please choose either a Sample or Project to start search. 
    - Hover on each object to get some relevant information.  
    - Metadata extracted from uploaded files may also be available when hovering.
    """
)

with st.form("Choice"):

    if st.session_state.setup_done:
        projects_df = st.session_state.oBis.get_projects().df.set_index("permId")
        project_mapping = projects_df["code"].to_dict()
        collections_df = st.session_state.oBis.get_experiments(
            type="COLLECTION",
            props=["$name"],
            where={"$DEFAULT_OBJECT_TYPE": "SAMPLE"},
        ).df.set_index("permId")
        collection_mapping = collections_df["$NAME"].to_dict()

        with st.spinner("Finding your samples"):
            samples_df = st.session_state.oBis.get_objects(
                type="SAMPLE", props=["$name"]
            ).df.set_index("permId")
            sample_mapping = samples_df["$NAME"].to_dict()
        sample = st.selectbox(
            label="Choose Sample",
            options=sorted(sample_mapping.keys(), reverse=True),
            index=None,
            format_func=lambda permid: f"{sample_mapping.get(permid)} ({permid})",
            disabled=not st.session_state.setup_done,
        )
        project = st.selectbox(
            label="Choose Project",
            options=sorted(
                project_mapping.keys(), key=lambda permid: project_mapping[permid]
            ),
            index=None,
            format_func=lambda permid: f"{project_mapping.get(permid)} ({permid})",
            disabled=not st.session_state.setup_done,
        )

        st.divider()

        collections = st.multiselect(
            label="Choose Collection(s)",
            options=sorted(collection_mapping.keys(), reverse=True),
            format_func=lambda permid: f"{collection_mapping.get(permid)} ({permid})",
            disabled=not st.session_state.setup_done,
            help="Restrict search by providing collection(s). Only collections with a default object type *Sample* will appear here.",
        )

        ELEMENTS = """
        H,He,Li,Be,B,C,N,O,F,Ne,Na,Mg,Al,Si,P,S,Cl,Ar,K,Ca,Sc,Ti,V,Cr,Mn,Fe,Co,Ni,Cu,
        Zn,Ga,Ge,As,Se,Br,Kr,Rb,Sr,Y,Zr,Nb,Mo,Tc,Ru,Rh,Pd,Ag,Cd,In,Sn,Sb,Te,I,Xe,Cs,Ba,
        La,Ce,Pr,Nd,Pm,Sm,Eu,Gd,Tb,Dy,Ho,Er,Tm,Yb,Lu,Hf,Ta,W,Re,Os,Ir,Pt,Au,Hg,Tl,Pb,Bi,
        Po,At,Rn,Fr,Ra,Ac,Th,Pa,U,Np,Pu,Am,Bk,Cf,Es,Fm,Md,No,Lr,Rf,Db,Sg,Hs,Bh,Hs,Mt,Ds,Rg,Cn,
        Nh,Fl,Mc,Lv,Ts,Og
        """
        element_list = "".join(ELEMENTS.split()).split(",")
        assert len(element_list) == 118
        elements = st.multiselect(
            label="Choose Elements(s)",
            options=element_list,
            disabled=not st.session_state.setup_done,
            help="Restrict search by providing element(s) contained in Sample.  \n"
            + "Any sample containing all or any of the selected elements will be returned, "
            + "including combinations with additional elements.",
        )

        col1a, col2a, col3a = st.columns(3)
        col1b, col2b = st.columns(2)
        with col1a:
            stop_protocol = st.toggle(
                label="Terminate search at Protocols",
                help="When activated restricts sample search by skipping samples linked through a common protocol",
                disabled=not st.session_state.setup_done,
            )
        with col2a:
            skip_simulation = st.toggle(
                label="Ignore Simulations",
                help="When activated restricts sample search by skipping samples used in simulations (Location = virtual)",
                disabled=not st.session_state.setup_done,
            )
        with col3a:
            skip_terminal = st.toggle(
                label="Exclude terminal object types",
                help=f"Skips: {', '.join(sorted(TERMINAL_OBJECT_TYPES))}",
                disabled=not st.session_state.setup_done,
            )
        with col1b:
            confirm_btn = st.form_submit_button(
                label="Generate Graph",
                type="primary",
                disabled=not st.session_state.setup_done,
            )
        with col2b:
            clear_btn = st.form_submit_button("Clear Figure")
        if clear_btn:
            if "figure" in st.session_state:
                st.session_state["figure"] = None
        if confirm_btn:

            st.session_state.figure = None

            if not ((sample is not None) ^ (project is not None)):
                st.warning("Choose either a Sample or a Project")
            else:
                with st.spinner("Creating graph from data ..."):
                    try:
                        finder = st.session_state.finder
                        property_types = finder.property_types["property_types"]

                        if sample is not None:
                            graph = finder.find_related_objects(
                                permid=sample,
                                skip_terminal=skip_terminal,
                                stop_protocol=stop_protocol,
                                skip_simulation=skip_simulation,
                                collections=collections,
                                elements=elements,
                            )
                            plotter = OpenbisHierarchicalGraphPlotter(
                                graph, property_types=property_types
                            )
                            if len(graph) == 0:
                                st.toast(
                                    "No samples were found with the requested criteria"
                                )
                            st.session_state.figure = plotter.generate_figure()
                        if project is not None:
                            project_graph = nx.DiGraph()
                            sample_permids = st.session_state.oBis.get_objects(
                                type="SAMPLE", project=project
                            ).df.permId
                            for sample in sample_permids:
                                if sample not in project_graph.nodes.keys():
                                    graph = finder.find_related_objects(
                                        permid=sample,
                                        skip_terminal=skip_terminal,
                                        stop_protocol=stop_protocol,
                                        skip_simulation=skip_simulation,
                                        collections=collections,
                                        elements=elements,
                                    )
                                    project_graph.update(graph)
                            if len(project_graph) == 0:
                                st.toast(
                                    "No samples were found with the requested criteria"
                                )
                            plotter = OpenbisHierarchicalGraphPlotter(
                                project_graph, property_types=property_types
                            )
                            st.session_state.figure = plotter.generate_figure()
                    except Exception:
                        st.error(
                            "Error while fetching data. Please try logging in again if the problem persists."
                        )

if st.session_state.figure is not None:
    event = st.plotly_chart(
        st.session_state.figure,
        width="stretch",
        key="hierarchical-graph",
        on_select="rerun",
        selection_mode="points",
    )
    html_string = pio.to_html(st.session_state.figure)
    st.download_button(
        label="Download Figure as HTML",
        data=html_string,
        file_name="figure.html",
        mime="text/html",
    )
    if len(event.selection.points) and "text" in event.selection.points[0]:
        for e in event.selection.points[0]["text"].split("<br>"):
            if "PermId: " in e:
                permid = e.split("PermId: ")[1]
                query = (
                    f'?menuUniqueId={{"type":"ADVANCED_SEARCH","id":"ADVANCED_SEARCH"}}'
                    + f"&viewName=showViewSamplePageFromPermId&viewData={permid}"
                )
                base_url = ":".join(st.session_state.oBis.url.split(":", 2)[:2])
                link = base_url + query
                st.page_link(link, label=f"Go back to openBIS ({permid})")
