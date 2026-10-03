"""C9 — the laws, ported from JS core `test/hott-laws.js`.

Executable witnesses for the HoTT-correspondence claims the JS suite
pins as EXACT — as hypothesis property tests over randomized chains
(depths, values), so each law is checked as a LAW, not as one example.
The exact JS witness shapes (nominal refusal, spine extraction) are
pinned inside the property tests.
"""

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mnemonica import (
    AlreadyDeclared,
    Mnemonic,
    createTypesCollection,
    getProps,
    utils,
)

_DEPTHS = st.integers(min_value=1, max_value=6)
_VALUES = st.lists(st.text(min_size=1, max_size=8), min_size=7, max_size=7)


def _draw_depth_values(draw: Any) -> tuple[int, list[str]]:
    depth = draw.draw(_DEPTHS)
    values = draw.draw(_VALUES)
    return depth, values[: depth + 1]


def _make_types(collection: Any, depth: int) -> list[Any]:
    """A fresh root type with `depth` nested subtypes (Root → T1 → …)."""

    @collection.define
    class LawRoot(Mnemonic):
        def __init__(self, value: str) -> None:
            self.value = value

    types: list[Any] = [LawRoot]
    parent: Any = LawRoot
    for level in range(1, depth + 1):
        field = f"level_{level}"

        def handler(self: Any, value: str, _field: str = field) -> None:
            setattr(self, _field, value)

        subtype = parent.define(f"LawLevel{level}", handler)
        types.append(subtype)
        parent = subtype
    return types


def _build_chain(types: list[Any], values: list[str]) -> list[Any]:
    """Construct the chain, returning the instances root..leaf."""
    root: Any = types[0]
    instances = [root(values[0])]
    for level in range(1, len(types)):
        parent = instances[-1]
        constructor: Any = getattr(parent, f"LawLevel{level}")
        instances.append(constructor(values[level]))
    return instances


def _parents(instance: Any) -> list[Any]:
    """The chain of parent instances, nearest first (the identity path)."""
    nodes: list[Any] = []
    record = getProps(instance)
    assert record is not None
    parent = record["parent"]
    while parent is not None:
        nodes.append(parent)
        parent_record = getProps(parent)
        assert parent_record is not None
        parent = parent_record["parent"]
    return nodes


@given(st.data())
def test_path_types_the_chain_is_the_identity_path(draw: Any) -> None:
    """The parent instances are materially present along the parent link:
    walking it from the leaf yields the ancestors, nearest first."""
    depth, values = _draw_depth_values(draw)
    collection = createTypesCollection()
    types = _make_types(collection, depth)
    instances = _build_chain(types, values)
    leaf = instances[-1]
    expected = list(reversed(instances[:-1]))
    assert _parents(leaf) == expected


@given(st.data())
def test_monad_right_identity_parent_context_preserved(draw: Any) -> None:
    """Binding a subtype preserves the parent context: every ancestor
    type nominally identifies the leaf, and ancestor fields read through."""
    depth, values = _draw_depth_values(draw)
    collection = createTypesCollection()
    types = _make_types(collection, depth)
    instances = _build_chain(types, values)
    leaf = instances[-1]
    for type_index, ancestor in enumerate(types):
        assert isinstance(leaf, ancestor)
        if type_index == 0:
            assert leaf.value == values[0]
        else:
            assert getattr(leaf, f"level_{type_index}") == values[type_index]


@given(st.data())
def test_monad_associativity_linear_chain(draw: Any) -> None:
    """((root >>= T1) >>= T2) >>= … associates linearly: the full path
    is held and nominal identity holds at every level."""
    depth, values = _draw_depth_values(draw)
    collection = createTypesCollection()
    types = _make_types(collection, depth)
    instances = _build_chain(types, values)
    leaf = instances[-1]
    assert len(_parents(leaf)) == depth
    for type_index in range(depth + 1):
        assert isinstance(leaf, types[type_index])


def test_identity_is_nominal_shape_does_not_identify() -> None:
    """Two types with byte-identical constructor bodies are different
    types; the name is frozen and re-declaring refuses (AlreadyDeclared
    is the port of the JS ALREADY_DECLARED throw)."""
    collection = createTypesCollection()

    def make_handler() -> Any:
        def handler(self: Any, value: int) -> None:
            self.value = value

        return handler

    NominalA = collection.define("NominalA", make_handler())
    NominalB = collection.define("NominalB", make_handler())
    a = NominalA(1)
    b = NominalB(1)
    assert vars(a) == vars(b)  # same shape
    assert not isinstance(a, NominalB)
    assert not isinstance(b, NominalA)
    with pytest.raises(AlreadyDeclared):
        collection.define("NominalA", make_handler())


@given(st.data())
def test_path_uniqueness_order_determines_identity(draw: Any) -> None:
    """Same type, different construction paths: both are the subtype,
    but the carried context differs, and siblings share the parent live."""
    depth, values = _draw_depth_values(draw)
    other_values = [f"{v}!" for v in values]
    collection = createTypesCollection()
    types = _make_types(collection, depth)
    first = _build_chain(types, values)
    second = _build_chain(types, other_values)
    leaf_a = first[-1]
    leaf_b = second[-1]
    assert type(leaf_a) is type(leaf_b)
    assert leaf_a is not leaf_b
    assert leaf_a.value != leaf_b.value
    # the path is determined by its steps: re-walking a's ancestors
    # never reaches b's root
    assert second[0] not in _parents(leaf_a)
    # siblings share the parent live (C2.6): one parent, two children
    parent_a = _parents(leaf_a)[0]
    sibling: Any = getattr(parent_a, f"LawLevel{depth}")("sibling")
    assert _parents(sibling)[0] is parent_a


@given(st.data())
def test_comparators_comparable_spine_is_deterministic(draw: Any) -> None:
    """The naming-path comparator is a function of the chain: same path
    → same spine for every instance on it; different paths stay
    distinguishable; the comparator sees the spine, never the fiber."""
    depth, values = _draw_depth_values(draw)
    collection = createTypesCollection()
    types = _make_types(collection, depth)
    instances = _build_chain(types, values)
    leaf = instances[-1]
    # a proper ancestor (never the leaf itself, even at depth 1)
    mid = instances[(len(instances) - 1) // 2]
    spine = utils.collectConstructors(leaf, True)
    # same naming path → same comparator, whatever the instance
    sibling: Any = getattr(instances[-2], f"LawLevel{depth}")("other")
    assert utils.collectConstructors(sibling, True) == spine
    # determinism: same instance → same spine
    assert utils.collectConstructors(leaf, True) == spine
    # different paths stay distinguishable
    assert utils.collectConstructors(mid, True) != spine
    # the spine names the types along the chain, base markers last
    assert spine[-2:] == ["Mnemonic", "Mnemosyne"]
    assert spine[0] == f"LawLevel{depth}"
    # the comparator never identifies the fiber: same spine, different
    # instances
    assert sibling is not leaf
