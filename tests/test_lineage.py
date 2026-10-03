"""The lethe lineage export — the cross-language contract.

Every export validates against the lethe schema; the shared fixture is
reproduced byte-for-byte per the README's id-mapping rule; ids are lazy
and retain nothing; dedup at any depth, siblings, forks, $ref fields,
tagged placeholders, and cycles are covered. `mnemonica-lethe` (a path
dev-dependency) exposes the schema and the fixture as the SAME files.
"""

import gc
import json
import weakref
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from mnemonica_lethe import fixture_text, schema

from mnemonica import Mnemonic, createTypesCollection, utils

_SCHEMA_VALIDATOR: Any = Draft202012Validator(schema())


def _canonical(graph: dict[str, Any]) -> str:
    result = json.dumps(graph, sort_keys=True, separators=(",", ":"))
    return result


def _build_fixture_graph() -> tuple[dict[str, Any], dict[str, Any]]:
    """The lethe README's construction recipe, in Python."""
    collection = createTypesCollection({"name": "fixture"})

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.Name = name

    def admin_handler(self: Any, role: str) -> None:
        self.Role = role
        self.Attached = None

    Admin = User.define("Admin", admin_handler)

    def super_handler(self: Any, level: int) -> None:
        self.Level = level

    SuperAdmin = Admin.define("SuperAdmin", super_handler)

    u = User("ada")
    a1: Any = Admin.of(u, "root")
    a2: Any = Admin.of(u, "operator")
    s: Any = SuperAdmin.of(a1, 7)
    a1.Attached = u
    graph = utils.lineage([s, a2])
    instances = {"s": s, "a1": a1, "a2": a2, "u": u}
    return graph, instances


def _map_ids_to_placeholders(graph: dict[str, Any]) -> dict[str, Any]:
    """Apply the README's comparison rule: ids map 1:1 in first-encounter
    order (heads in argument order, then depth-first: node, its own-field
    $refs in field order, then parent)."""

    def encounter_refs(value: Any, visit: Any) -> None:
        # cast: isinstance-narrowing an Any leaves Unknown type arguments
        # that pyright strict rejects
        if isinstance(value, dict):
            mapping = cast(dict[Any, Any], value)  # type: ignore[redundant-cast]
            if "$ref" in mapping:
                visit(mapping["$ref"])
            else:
                for item in mapping.values():
                    encounter_refs(item, visit)
        elif isinstance(value, list):
            sequence = cast(list[Any], value)  # type: ignore[redundant-cast]
            for item in sequence:
                encounter_refs(item, visit)

    nodes = graph["nodes"]
    order: list[str] = []
    seen: set[str] = set()

    def encounter(node_id: str) -> None:
        if node_id in seen:
            return
        seen.add(node_id)
        order.append(node_id)
        node = nodes[node_id]
        for value in node["own"].values():
            encounter_refs(value, encounter)
        parent = node["parent"]
        if parent is not None:
            encounter(parent)

    for head in graph["heads"]:
        encounter(head)

    # the fixture's semantic placeholders, in first-encounter order
    placeholders = ["s", "a1", "u", "a2"]
    mapping = {real: placeholders[i] for i, real in enumerate(order)}

    def remap(value: Any) -> Any:
        # cast: isinstance-narrowing an Any leaves Unknown type arguments
        # that pyright strict rejects
        if isinstance(value, dict):
            dictionary = cast(dict[Any, Any], value)  # type: ignore[redundant-cast]
            if "$ref" in dictionary:
                return {"$ref": mapping[dictionary["$ref"]]}
            remapped: dict[str, Any] = {
                key: remap(item) for key, item in dictionary.items()
            }
            return remapped
        if isinstance(value, list):
            sequence = cast(list[Any], value)  # type: ignore[redundant-cast]
            return [remap(item) for item in sequence]
        return value

    remapped_heads = [mapping[head] for head in graph["heads"]]
    remapped_nodes = {}
    for node_id, node in nodes.items():
        remapped = remap(node)
        parent = node["parent"]
        remapped["parent"] = mapping[parent] if parent is not None else None
        remapped_nodes[mapping[node_id]] = remapped
    result: dict[str, Any] = {
        "version": graph["version"],
        "heads": remapped_heads,
        "nodes": remapped_nodes,
    }
    return result


def test_fixture_reproduced_byte_for_byte() -> None:
    graph, _ = _build_fixture_graph()
    remapped = _map_ids_to_placeholders(graph)
    produced = _canonical(remapped)
    expected = fixture_text().strip()
    assert produced == expected


def test_export_validates_against_the_schema() -> None:
    graph, _ = _build_fixture_graph()
    _SCHEMA_VALIDATOR.validate(graph)


def test_deepparse_is_instance_first_root_last() -> None:
    graph, instances = _build_fixture_graph()
    del graph
    s = instances["s"]
    snapshots = utils.deepParse(s)
    assert [snap["name"] for snap in snapshots] == [
        "SuperAdmin",
        "Admin",
        "User",
    ]
    assert snapshots[0]["self"] is s
    assert snapshots[-1]["parent"] is None


def test_dedup_at_any_depth_and_sibling_heads() -> None:
    graph, instances = _build_fixture_graph()
    del instances
    # u is shared by three nodes and appears exactly once
    u_id = next(
        node_id
        for node_id, node in graph["nodes"].items()
        if node["own"].get("Name") == "ada"
    )
    parent_edges = 0
    ref_edges = 0
    for node in graph["nodes"].values():
        if node["parent"] == u_id:
            parent_edges += 1
        for value in node["own"].values():
            if isinstance(value, dict):
                mapping = cast(dict[Any, Any], value)  # type: ignore[redundant-cast]
                if mapping.get("$ref") == u_id:
                    ref_edges += 1
    assert parent_edges == 2  # a1 and a2 are u's children
    assert ref_edges == 1  # a1.Attached points back at u
    assert len(graph["nodes"]) == 4
    assert len(graph["heads"]) == 2


def test_ref_field_and_null_field() -> None:
    graph, _ = _build_fixture_graph()
    nodes = list(graph["nodes"].values())
    admin_with_ref = next(node for node in nodes if node["own"].get("Role") == "root")
    admin_null = next(node for node in nodes if node["own"].get("Role") == "operator")
    attached = admin_with_ref["own"]["Attached"]
    assert isinstance(attached, dict) and "$ref" in attached
    # the $ref target is the exported user node (dedup, not a copy)
    target = graph["nodes"][attached["$ref"]]
    assert target["own"] == {"Name": "ada"}
    assert admin_null["own"]["Attached"] is None


def test_args_and_props_options() -> None:
    collection = createTypesCollection({"name": "argsy"})

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.Name = name

    def admin_handler(self: Any, role: str) -> None:
        self.role = role

    Admin = User.define("Admin", admin_handler)
    admin: Any = Admin.of(User("ada"), "root")
    plain = utils.lineage(admin)
    assert "args" not in plain["nodes"][plain["heads"][0]]
    assert "props" not in plain["nodes"][plain["heads"][0]]

    with_options = utils.lineage(admin, args=True, props=["timestamp"])
    node = with_options["nodes"][with_options["heads"][0]]
    assert node["args"] == ["root"]
    assert isinstance(node["props"]["timestamp"], int)
    _SCHEMA_VALIDATOR.validate(with_options)


def test_fork_exports_as_a_dag() -> None:
    collection = createTypesCollection({"name": "dag"})

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.Name = name

    def admin_handler(self: Any, role: str) -> None:
        self.role = role

    Admin = User.define("Admin", admin_handler)
    first = User("ada")
    second = User("grace")
    admin: Any = Admin.of(first, "root")
    forked: Any = utils.fork(admin).call(second, "sudo")
    graph = utils.lineage(forked)
    _SCHEMA_VALIDATOR.validate(graph)
    forked_node = graph["nodes"][graph["heads"][0]]
    assert forked_node["type"] == {
        "collection": "dag",
        "path": "User.Admin",
    }
    parent_node = graph["nodes"][forked_node["parent"]]
    assert parent_node["own"] == {"Name": "grace"}


def test_unsupported_values_become_tagged_placeholders() -> None:
    collection = createTypesCollection({"name": "odd"})

    @collection.define
    class Box(Mnemonic):
        def __init__(self) -> None:
            self.C = 1 + 2j
            self.F = len
            self.Nan = float("nan")
            self.Inf = float("inf")
            self.NInf = float("-inf")
            self.Pi = 3.14
            self.Raw = b"bytes"
            self.Set = {1, 2}

    cyclic: list[Any] = []
    cyclic.append(cyclic)

    dict_cycle: dict[str, Any] = {}
    dict_cycle["self"] = dict_cycle

    def cyclic_handler(self: Any) -> None:
        self.Cycle = cyclic
        self.DictCycle = dict_cycle

    WithCycle = Box.define("WithCycle", cyclic_handler)
    leaf: Any = WithCycle.of(Box())
    graph = utils.lineage(leaf)
    _SCHEMA_VALIDATOR.validate(graph)
    # the placeholder fields live on the Box parent node
    box_node = graph["nodes"][graph["nodes"][graph["heads"][0]]["parent"]]
    own = box_node["own"]
    assert own["C"] == {"$mnemonica": "unsupported", "kind": "complex"}
    assert own["F"]["kind"] == "func"
    assert own["Nan"]["kind"] == "nan"
    assert own["Inf"]["kind"] == "+inf"
    assert own["NInf"]["kind"] == "-inf"
    assert own["Pi"] == 3.14
    assert own["Raw"]["kind"] == "invalid"
    assert own["Set"]["kind"] == "invalid"
    cycle_node = graph["nodes"][graph["heads"][0]]
    # the list exports; its self-reference becomes the cycle placeholder
    assert cycle_node["own"]["Cycle"] == [
        {"$mnemonica": "unsupported", "kind": "cycle"}
    ]
    assert cycle_node["own"]["DictCycle"] == {
        "self": {"$mnemonica": "unsupported", "kind": "cycle"}
    }


def test_map_keys_placeholder_and_integer_keys() -> None:
    collection = createTypesCollection({"name": "keys"})

    @collection.define
    class Box(Mnemonic):
        def __init__(self) -> None:
            self.Mixed = {1: "one", "two": 2}
            self.TupleKeyed = {(1, 2): "nope"}

    box = Box()
    graph = utils.lineage(box)
    _SCHEMA_VALIDATOR.validate(graph)
    own = graph["nodes"][graph["heads"][0]]["own"]
    assert own["Mixed"] == {"1": "one", "two": 2}
    assert own["TupleKeyed"] == {"$mnemonica": "unsupported", "kind": "map-keys"}


def test_instance_field_cycle_is_a_ref_not_a_hang() -> None:
    collection = createTypesCollection({"name": "selfref"})

    @collection.define
    class Node(Mnemonic):
        Self: Any

        def __init__(self) -> None:
            self.Self = None

    node = Node()
    node.Self = node  # a field pointing at its own instance
    graph = utils.lineage(node)
    _SCHEMA_VALIDATOR.validate(graph)
    only = graph["nodes"][graph["heads"][0]]
    assert only["own"]["Self"] == {"$ref": graph["heads"][0]}


def test_ids_are_lazy_weak_and_never_retain() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.Name = name

    user = User("ada")
    reference = weakref.ref(user)
    graph = utils.lineage(user)
    del graph
    assert reference() is not None  # ids hold nothing; the caller does
    del user
    gc.collect()
    assert reference() is None  # an id'd instance is collectable


def test_collection_names_default_auto_and_given() -> None:
    from mnemonica.collection import default_collection

    assert default_collection().name == "defaultTypes"
    first_unnamed = createTypesCollection()
    second_unnamed = createTypesCollection()
    # automatic names are unique and in creation order
    assert first_unnamed.name.startswith("collection_")
    assert second_unnamed.name.startswith("collection_")
    assert first_unnamed.name != second_unnamed.name
    named = createTypesCollection({"name": "fixture"})
    assert named.name == "fixture"
    from mnemonica import OptionsError

    with pytest.raises(OptionsError, match="string"):
        createTypesCollection(cast(Any, {"name": 42}))


def test_type_define_config_rejects_name() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.Name = name

    from mnemonica import OptionsError

    def sneaky_handler(self: Any) -> None:
        pass

    with pytest.raises(OptionsError, match="collection option"):
        User.define("Sneaky", sneaky_handler, {"name": "nope"})
    with pytest.raises(OptionsError, match="collection option"):
        collection.define("SneakyRoot", sneaky_handler, {"name": "nope"})


def test_lineage_type_paths_use_the_chain_not_just_names() -> None:
    # two same-named types in different collections keep distinct paths
    left = createTypesCollection({"name": "left"})
    right = createTypesCollection({"name": "right"})

    def left_handler(self: Any) -> None:
        self.Kind = "left"

    def right_handler(self: Any) -> None:
        self.Kind = "right"

    LeftWidget = left.define("Widget", left_handler)
    RightWidget = right.define("Widget", right_handler)
    graph = utils.lineage([LeftWidget(), RightWidget()])
    _SCHEMA_VALIDATOR.validate(graph)
    by_collection = {
        node["type"]["collection"]: node["type"]["path"]
        for node in graph["nodes"].values()
    }
    assert by_collection == {"left": "Widget", "right": "Widget"}


def test_deepparse_of_non_instance_is_empty() -> None:
    assert utils.deepParse(cast(Any, object())) == []


def test_lineage_rejects_non_instances() -> None:
    from mnemonica import WrongModificationPattern

    with pytest.raises(WrongModificationPattern):
        utils.lineage([cast(Any, object())])
