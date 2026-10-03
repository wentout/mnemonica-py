"""C7 — utils, with the JS doc examples ported as tests.

Covers extract, pick, parent (incl. dotted contiguous paths), clone,
fork (same-parent, new-args, and the DAG `.call` form), sibling,
exception, merge, parse (the FIXED parent-instance semantics), toJSON,
and collectConstructors.
"""

import json
from typing import Any, cast

import pytest
from helpers import construct, null_handler

from mnemonica import (
    ErroredInstance,
    Mnemonic,
    WrongArgumentsUsed,
    WrongInstanceInvocation,
    WrongModificationPattern,
    createTypesCollection,
    getProps,
    utils,
)


def _pipeline(collection: Any) -> tuple[Any, Any, Any, Any]:
    """The FOR_HUMANS pipeline example: request → route → page → response."""

    def request_handler(self: Any, method: str) -> None:
        self.method = method

    def route_handler(self: Any, handler: str) -> None:
        self.handler = handler

    def page_handler(self: Any, body: str) -> None:
        self.body = body

    def response_handler(self: Any, status: int) -> None:
        self.status = status

    RequestData = collection.define("RequestData", request_handler)
    RouteData = RequestData.define("RouteData", route_handler)
    PageData = RouteData.define("PageData", page_handler)
    ResponseData = PageData.define("ResponseData", response_handler)
    req = RequestData("GET")
    route = RouteData.of(req, "route-handler")
    page = PageData.of(route, "page-body")
    res = ResponseData.of(page, 200)
    return req, route, page, res


# --- extract ---------------------------------------------------------------


def test_extract_flattens_user_fields_along_the_chain() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    admin = construct(User("ada"), "Admin", "root")
    extracted = utils.extract(admin)
    assert extracted == {"role": "root", "name": "ada"}
    # the parent link and the context record stay internal
    assert "_mn_parent" not in extracted


def test_extract_nearest_value_wins() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    admin = construct(User("ada"), "Admin", "root")
    admin.name = "eve"
    extracted = utils.extract(admin)
    assert extracted["name"] == "eve"
    assert utils.extract(admin)["name"] == "eve"


def test_extract_of_object_without_dict_raises() -> None:
    with pytest.raises(WrongInstanceInvocation):
        utils.extract(cast(Any, 5))


# --- pick ------------------------------------------------------------------


def test_pick_spread_and_list_forms() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    admin = construct(User("ada"), "Admin", "root")
    assert utils.pick(admin, "name") == {"name": "ada"}
    assert utils.pick(admin, ["role", "name"]) == {
        "role": "root",
        "name": "ada",
    }
    # a key missing along the chain lands as None (the JS undefined)
    assert utils.pick(admin, "missing") == {"missing": None}


def test_pick_of_object_without_dict_raises() -> None:
    with pytest.raises(WrongInstanceInvocation):
        utils.pick(cast(Any, 5), "name")


def test_pick_never_exposes_the_parent_slot() -> None:
    collection = createTypesCollection()
    User = collection.define("User", null_handler)
    parent_slot = "_mn_parent"
    assert utils.pick(User(), parent_slot) == {parent_slot: None}


# --- parent ----------------------------------------------------------------


def test_parent_immediate_and_by_name() -> None:
    collection = createTypesCollection()
    req, route, page, res = _pipeline(collection)

    assert utils.parent(res) is page
    assert utils.parent(res, "RouteData") is route
    # the instance itself is never a candidate
    assert utils.parent(res, "ResponseData") is None
    # no such ancestor
    assert utils.parent(res, "Widget") is None
    # root: no parent
    assert utils.parent(req) is None


def test_parent_dotted_path_is_contiguous() -> None:
    collection = createTypesCollection()
    _, route, page, res = _pipeline(collection)

    # contiguous match upwards returns the LAST segment's instance
    assert utils.parent(res, "RequestData.RouteData") is route
    assert utils.parent(res, "RouteData.PageData") is page
    # non-contiguous: RouteData is not the direct parent of the
    # PageData-matched instance
    assert utils.parent(res, "RouteData.PageData.RouteData") is None
    assert utils.parent(res, "RequestData.PageData") is None
    # the contiguous verification runs out of chain: RequestData is the
    # root, so nothing can match above it
    assert utils.parent(route, "Widget.RequestData") is None


def test_parent_of_non_mnemonica_is_none() -> None:
    class Plain:
        pass

    assert utils.parent(Plain()) is None


# --- clone / fork ----------------------------------------------------------


def test_clone_root_and_subtype() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    user: User = User("ada")
    cloned_user = utils.clone(user)
    assert cloned_user is not user
    assert cloned_user.name == "ada"
    assert isinstance(cloned_user, User)

    admin: Admin = construct(user, "Admin", "root")
    cloned_admin = utils.clone(admin)
    assert cloned_admin is not admin
    assert cloned_admin.role == "root"
    assert cloned_admin.name == "ada"  # read-through to the same parent
    assert utils.parent(cloned_admin) is user  # same parent, not the clone


def test_fork_with_original_and_new_args() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    user: User = User("ada")
    admin: Admin = construct(user, "Admin", "root")

    same = utils.fork(admin)()
    assert same.role == "root"
    changed = utils.fork(admin)("sudo")
    assert changed.role == "sudo"
    assert changed.name == "ada"
    assert isinstance(changed, Admin)


def test_fork_call_onto_another_parent_is_a_dag() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    first: User = User("ada")
    second: User = User("grace")
    admin: Admin = construct(first, "Admin", "root")

    dag: Any = utils.fork(admin).call(second, "sudo")
    assert isinstance(dag, Admin)
    assert utils.parent(dag) is second
    assert dag.name == "grace"
    assert dag.role == "sudo"


def test_fork_of_non_instance_raises() -> None:
    with pytest.raises(WrongInstanceInvocation):
        utils.fork(cast(Any, object()))


# --- sibling ---------------------------------------------------------------


def test_sibling_by_call_and_by_attribute() -> None:
    collection = createTypesCollection()
    User = collection.define("User", null_handler)
    collection.define("Widget", null_handler)
    user = User()

    siblings = utils.sibling(user)
    assert siblings("Widget") is collection.lookup("Widget")
    widget_attr = "Widget"
    assert getattr(siblings, widget_attr) is collection.lookup("Widget")
    # unknown sibling → None (the JS undefined)
    assert siblings("Missing") is None
    assert getattr(siblings, widget_attr) is not None


def test_sibling_of_non_instance_raises() -> None:
    with pytest.raises(WrongInstanceInvocation):
        utils.sibling(cast(Any, object()))


def test_sibling_dunder_probe_is_refused() -> None:
    # copy/pickle protocols probe instances for dunder hooks; answering
    # those from the collection would corrupt them (same rule as
    # Mnemonic.__getattr__)
    import copy

    collection = createTypesCollection()
    User = collection.define("User", null_handler)
    siblings = utils.sibling(User())
    dunder = "__not_a_real_dunder__"
    assert getattr(siblings, dunder, None) is None
    copied = copy.copy(siblings)
    assert copied("User") is User


# --- exception -------------------------------------------------------------


def test_exception_carries_data_via_get_props() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    user = User("ada")
    error = ValueError("boom")
    exc = utils.exception(user, error, 1, 2, 3)
    assert isinstance(exc, BaseException)
    record = getProps(exc)
    assert record is not None
    assert record["args"] == (1, 2, 3)
    assert record["originalError"] is error
    assert record["instance"] is user
    # the error chains onto the wrapped error (the JS existentInstance)
    assert utils.parent(exc) is error


def test_exception_inherits_packaged_error_data() -> None:
    collection = createTypesCollection()

    def bad_handler(self: object) -> None:
        raise ValueError("boom")

    Bad = collection.define("Bad", bad_handler)
    with pytest.raises(ErroredInstance) as caught:
        Bad()
    packaged = caught.value
    packaged_record = getProps(packaged)
    assert packaged_record is not None

    user = collection.define("User", null_handler)()
    exc = utils.exception(user, packaged)
    record = getProps(exc)
    assert record is not None
    assert record["exceptionReason"] is packaged_record["exceptionReason"]
    assert record["reasons"] is packaged_record["reasons"]
    assert record["originalError"] is packaged


def test_exception_of_non_instance_raises() -> None:
    with pytest.raises(WrongArgumentsUsed):
        utils.exception(cast(Any, object()), ValueError("boom"))


def test_exception_wrapping_unpackaged_error_inherits_nothing() -> None:
    # a wrapped error whose record carries no packaged data (an exception
    # made from an instance, say) contributes no inherited fields
    collection = createTypesCollection()
    User = collection.define("User", null_handler)
    user = User()
    first = utils.exception(user, ValueError("boom"))
    record = getProps(utils.exception(user, first))
    assert record is not None
    assert "exceptionReason" not in record
    assert record["originalError"] is first


# --- merge -----------------------------------------------------------------


def test_merge_chains_a_onto_b() -> None:
    collection = createTypesCollection()

    def user_handler(self: Any) -> None:
        self.name = "Alice"
        self.age = 30

    User = collection.define("User", user_handler)

    def role_handler(self: Any) -> None:
        self.role = "admin"

    Role = collection.define("Role", role_handler)

    user = User()
    role = Role()
    merged = utils.merge(user, role)
    assert isinstance(merged, User)
    assert utils.parent(merged) is role
    assert utils.extract(merged) == {
        "name": "Alice",
        "age": 30,
        "role": "admin",
    }


def test_merge_with_extra_args() -> None:
    collection = createTypesCollection()

    def user_handler(self: Any, name: str) -> None:
        self.name = name

    def role_handler(self: Any) -> None:
        self.role = "admin"

    User = collection.define("User", user_handler)
    Role = collection.define("Role", role_handler)
    merged = utils.merge(User("alice"), Role(), "bob")
    assert merged.name == "bob"
    assert merged.role == "admin"


def test_merge_of_non_instance_raises() -> None:
    with pytest.raises(WrongArgumentsUsed, match="mnemonica instance"):
        utils.merge(cast(Any, object()), object())


def test_merge_onto_wrong_kind_parent_respects_strict_chain() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    @collection.define
    class Widget(Mnemonic):
        def __init__(self, sku: str) -> None:
            self.sku = sku

    admin: Any = construct(User("ada"), "Admin", "root")
    widget = Widget("w1")
    with pytest.raises(WrongModificationPattern, match="User"):
        utils.merge(admin, widget)


# --- parse -----------------------------------------------------------------


def test_parse_shape_and_fixed_parent() -> None:
    collection = createTypesCollection()
    req, _, page, res = _pipeline(collection)

    parsed = utils.parse(res)
    assert parsed["name"] == "ResponseData"
    assert parsed["self"] is res
    assert parsed["props"] == utils.extract(res)
    # FIXED JS semantics: the parent INSTANCE, as utils.parent returns
    assert parsed["parent"] is page
    assert parsed["parent"] is utils.parent(res)

    parsed_req = utils.parse(req)
    assert parsed_req["parent"] is None  # root → None


def test_parse_of_layer_or_nothing_raises() -> None:
    collection = createTypesCollection()
    User = collection.define("User", null_handler)
    with pytest.raises(WrongModificationPattern):
        utils.parse(cast(Any, None))
    with pytest.raises(WrongModificationPattern):
        utils.parse(cast(Any, object()))
    # a mnemonica TYPE is not an instance
    with pytest.raises(WrongArgumentsUsed):
        utils.parse(cast(Any, User))


# --- toJSON ----------------------------------------------------------------


def test_to_json_matches_the_js_shape() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    admin = construct(User("ada"), "Admin", "root")
    assert utils.toJSON(admin) == '{"role":"root","name":"ada"}'


def test_to_json_skips_none_and_wraps_unsupported() -> None:
    collection = createTypesCollection()

    def widget_handler(self: Any) -> None:
        self.sku = "w1"
        self.missing = None
        self.tags = {"a", "b"}

    Widget = collection.define("Widget", widget_handler)
    encoded = utils.toJSON(Widget())
    assert '"sku":"w1"' in encoded
    assert "missing" not in encoded
    assert "not supported by JSON.stringify" in encoded


def test_to_json_of_fieldless_instance_is_the_empty_object() -> None:
    collection = createTypesCollection()
    Empty = collection.define("Empty", null_handler)
    # deviation: JS returns "{" here (invalid JSON; bug, reported to
    # viktor) — the port produces valid JSON
    assert utils.toJSON(Empty()) == "{}"


def test_to_json_escapes_keys() -> None:
    # deviation: JS writes `"${name}"` raw, so a quoted key produces
    # invalid JSON there; the port always produces valid JSON
    collection = createTypesCollection()

    def tricky_handler(self: Any) -> None:
        setattr(self, 'say "hi"', 1)

    Tricky = collection.define("Tricky", tricky_handler)
    encoded = utils.toJSON(Tricky())
    assert json.loads(encoded) == {'say "hi"': 1}


# --- collectConstructors ----------------------------------------------------


def test_collect_constructors_along_the_chain() -> None:
    collection = createTypesCollection()
    req, _, _, res = _pipeline(collection)

    assert utils.collectConstructors(res, True) == [
        "ResponseData",
        "PageData",
        "RouteData",
        "RequestData",
        "Mnemonic",
        "Mnemosyne",
    ]
    lookup = utils.collectConstructors(req)
    assert lookup == {
        "RequestData": True,
        "Mnemonic": True,
        "Mnemosyne": True,
    }
    # None contributes nothing
    assert utils.collectConstructors(cast(Any, None), True) == []


def test_collect_constructors_of_plain_object() -> None:
    assert utils.collectConstructors({}, True) == ["Object"]
    assert utils.collectConstructors(object(), True) == ["Object"]


# --- DAG chain walk robustness ----------------------------------------------


def test_extract_terminates_on_dict_less_chain_node() -> None:
    # a DAG parent without __dict__ (strictChain off) must not break the
    # chain walk
    collection = createTypesCollection()
    User = collection.define("User", null_handler)
    Loose = User.define("Loose", null_handler, {"strictChain": False})
    dag: Any = Loose.of(cast(Any, 42))
    assert utils.extract(dag) == {}
    assert utils.parent(dag, "User") is None

    # a named plain-object parent matches its class name (the JS
    # constructor.name rule) but carries no record, so a dotted
    # verification through it fails instead of crashing
    class Plain:
        pass

    dag2: Any = Loose.of(Plain())
    assert utils.parent(dag2, "Widget.Plain") is None
