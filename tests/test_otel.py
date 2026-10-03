"""The OpenTelemetry link (mnemonica.otel) — the Go otelx contract.

End-to-end with the SDK's InMemorySpanExporter: stamped constructions on
the request span, a linked span started after the request ended, the
error path carrying the lineage graph — sync and async. Instance ids on
spans must equal utils.lineage ids (the join key).
"""

import asyncio
import json
import subprocess
import sys
from collections.abc import Iterator
from typing import Any, cast

import pytest
from helpers import construct
from opentelemetry import trace as trace_api
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from mnemonica import (
    ErroredInstance,
    Mnemonic,
    WrongArgumentsUsed,
    createTypesCollection,
    getProps,
    otel,
    utils,
)


@pytest.fixture
def tracer_exporter() -> Iterator[tuple[Any, InMemorySpanExporter]]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield provider.get_tracer("mnemonica-otel-test"), exporter
    provider.shutdown()


def _span(exporter: InMemorySpanExporter, name: str) -> ReadableSpan:
    for span in exporter.get_finished_spans():
        if span.name == name:
            return span
    raise AssertionError(f"span {name!r} not found")


def _fixture(stamp: bool = True) -> tuple[Any, Any, Any]:
    collection = createTypesCollection({"name": "otel"})

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.Name = name

    def admin_handler(self: Any, role: str) -> None:
        self.Role = role

    Admin = User.define("Admin", admin_handler)
    if stamp:
        otel.stamp_constructions(collection)
    return collection, User, Admin


def _stamp_attributes(
    tracer: Any, exporter: InMemorySpanExporter
) -> tuple[ReadableSpan, Any, Any]:
    _, User, Admin = _fixture()
    with tracer.start_as_current_span("request"):
        user = User("ada")
        admin = Admin.of(user, "root")
    span = _span(exporter, "request")
    return span, user, admin


def test_stamp_constructions_on_request_span(
    tracer_exporter: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = tracer_exporter
    span, user, admin = _stamp_attributes(tracer, exporter)
    attributes = dict(span.attributes or {})
    assert attributes[otel.ATTR_INSTANCE_ID] == utils.id_of(admin)
    assert attributes[otel.ATTR_PARENT_ID] == utils.id_of(user)
    assert attributes[otel.ATTR_TYPE_COLLECTION] == "otel"
    assert attributes[otel.ATTR_TYPE_PATH] == "User.Admin"


def test_root_has_no_parent_attribute(
    tracer_exporter: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = tracer_exporter
    _, User, _ = _fixture()
    with tracer.start_as_current_span("request"):
        User("ada")
    attributes = dict(_span(exporter, "request").attributes or {})
    assert attributes[otel.ATTR_INSTANCE_ID]
    assert otel.ATTR_PARENT_ID not in attributes


def test_stamp_without_span_is_a_noop(
    tracer_exporter: tuple[Any, InMemorySpanExporter],
) -> None:
    _, exporter = tracer_exporter
    _, User, _ = _fixture()
    user = User("ada")  # no current span
    assert user.Name == "ada"
    assert exporter.get_finished_spans() == ()


def test_errored_construction_is_stamped(
    tracer_exporter: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = tracer_exporter
    _, User, _ = _fixture()

    def failing(self: Any) -> None:
        raise ValueError("boom")

    Failing = User.define("Failing", failing)
    errored = None
    with tracer.start_as_current_span("request"):
        User("ada")
        try:
            Failing.of(User("grace"))
        except ErroredInstance as caught:
            errored = caught
    assert errored is not None
    attributes = dict(_span(exporter, "request").attributes or {})
    # the LAST construction on the span wins the stamp: the errored one
    assert attributes[otel.ATTR_INSTANCE_ID] == utils.id_of(errored)
    assert attributes[otel.ATTR_TYPE_PATH] == "User.Failing"


def test_start_linked_span_after_request_ended(
    tracer_exporter: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = tracer_exporter
    _, User, Admin = _fixture()
    with tracer.start_as_current_span("request") as request_span:
        user = User("ada")
        admin = Admin.of(user, "root")
    request_context = request_span.get_span_context()

    # work that outlives the request: linked via the recorded context
    worker = otel.start_linked_span(tracer, "worker", admin)
    worker.end()
    worker_span = _span(exporter, "worker")
    assert len(worker_span.links) == 1
    linked = worker_span.links[0].context
    assert linked.trace_id == request_context.trace_id
    assert linked.span_id == request_context.span_id

    # an instance constructed without any span: a plain span, no links
    plain = User("plain")
    plain_worker = otel.start_linked_span(tracer, "plain-worker", plain)
    plain_worker.end()
    assert _span(exporter, "plain-worker").links == ()

    # not an instance at all: still a plain span
    foreign_worker = otel.start_linked_span(tracer, "foreign", cast(Any, object()))
    foreign_worker.end()
    assert _span(exporter, "foreign").links == ()


def test_start_linked_span_with_invalid_recorded_context(
    tracer_exporter: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = tracer_exporter
    _, User, _ = _fixture()
    user = User("ada")
    record = getProps(user)
    assert record is not None
    record["otel_span_context"] = trace_api.INVALID_SPAN_CONTEXT
    span = otel.start_linked_span(tracer, "plain", user)
    span.end()
    assert _span(exporter, "plain").links == ()


def test_record_lineage_carriers(
    tracer_exporter: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = tracer_exporter
    _, User, _ = _fixture()
    with tracer.start_as_current_span("request"):
        user = User("ada")

    # carrier 1: a blocked construction (ErroredInstance IS the instance)
    def failing(self: Any) -> None:
        raise ValueError("boom")

    Failing = User.define("Failing", failing)
    with pytest.raises(ErroredInstance) as caught:
        Failing.of(user)
    errored = caught.value

    with tracer.start_as_current_span("handle-error") as handle:
        otel.record_lineage(cast(Any, errored), span=handle)
    event = _error_event(_span(exporter, "handle-error"))
    assert event[otel.ATTR_INSTANCE_ID] == utils.id_of(errored)
    graph = json.loads(event[otel.ATTR_LINEAGE_GRAPH])
    assert graph["version"] == "1"
    assert utils.id_of(errored) in graph["nodes"]

    # carrier 2: utils.exception carries another instance
    carrier = utils.exception(user, ValueError("job failed"))
    with tracer.start_as_current_span("handle-exception") as handle2:
        otel.record_lineage(carrier, span=handle2)
    event2 = _error_event(_span(exporter, "handle-exception"))
    assert event2[otel.ATTR_INSTANCE_ID] == utils.id_of(user)

    # an errored instance whose carried instance lost its record: its own
    # record is a utils.exception record (no lineage of its own) → refused
    broken = utils.exception(user, ValueError("x"))
    broken_record = getProps(broken)
    assert broken_record is not None
    broken_record["instance"] = object()
    with pytest.raises(WrongArgumentsUsed, match="no exportable instance"):
        otel.record_lineage(broken)

    # unsupported carrier: no event, WrongArgumentsUsed
    with pytest.raises(WrongArgumentsUsed):
        otel.record_lineage(cast(Any, ValueError("bare")))


def _error_event(span: ReadableSpan) -> dict[str, Any]:
    for event in span.events:
        if event.name == otel.EVENT_ERROR:
            return dict(event.attributes or {})
    raise AssertionError("mnemonica.error event not found")


def test_end_to_end(tracer_exporter: tuple[Any, InMemorySpanExporter]) -> None:
    tracer, exporter = tracer_exporter
    _, User, Admin = _fixture()

    with tracer.start_as_current_span("http-request") as request_span:
        user = User("ada")
        admin = Admin.of(user, "root")
    request_context = request_span.get_span_context()

    # the worker runs AFTER the request ended — in its own task
    async def worker() -> None:
        span = otel.start_linked_span(tracer, "background-job", admin)
        with trace_api.use_span(span, end_on_exit=False):
            otel.record_lineage(
                utils.exception(admin, ValueError("job failed")), span=span
            )
        span.end()

    asyncio.run(worker())

    worker_span = _span(exporter, "background-job")
    assert len(worker_span.links) == 1
    assert worker_span.links[0].context.trace_id == request_context.trace_id

    event = _error_event(worker_span)
    assert event[otel.ATTR_INSTANCE_ID] == utils.id_of(admin)
    graph = json.loads(event[otel.ATTR_LINEAGE_GRAPH])
    assert utils.id_of(admin) in graph["nodes"]
    assert utils.id_of(user) in graph["nodes"]

    request = dict(_span(exporter, "http-request").attributes or {})
    assert request[otel.ATTR_INSTANCE_ID] == utils.id_of(admin)
    assert request[otel.ATTR_PARENT_ID] == utils.id_of(user)
    assert request[otel.ATTR_TYPE_PATH] == "User.Admin"


def test_async_constructions_are_stamped_and_linked(
    tracer_exporter: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = tracer_exporter
    collection = createTypesCollection({"name": "otel"})

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.Name = name

    @User.define
    class AsyncAdmin(User):
        async def __ainit__(self, role: str) -> None:
            self.Role = role

    otel.stamp_constructions(collection)

    async def request() -> Any:
        with tracer.start_as_current_span("request"):
            user = User("ada")
            admin = await construct(user, "AsyncAdmin", "root")
        return admin

    admin = asyncio.run(request())

    attributes = dict(_span(exporter, "request").attributes or {})
    assert attributes[otel.ATTR_INSTANCE_ID] == utils.id_of(admin)
    assert attributes[otel.ATTR_TYPE_PATH] == "User.AsyncAdmin"

    async def worker() -> None:
        span = otel.start_linked_span(tracer, "worker", admin)
        span.end()

    asyncio.run(worker())
    worker_span = _span(exporter, "worker")
    request_span = _span(exporter, "request")
    assert len(worker_span.links) == 1
    request_context = request_span.get_span_context()
    assert request_context is not None
    assert worker_span.links[0].context.span_id == request_context.span_id


def test_core_import_does_not_require_otel() -> None:
    # a fresh interpreter: importing mnemonica must not pull opentelemetry
    code = (
        "import sys, mnemonica;"
        "sys.exit(1 if any(m.startswith('opentelemetry') for m in sys.modules)"
        " else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_otel_helpers_require_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    # simulate the extra missing: the module imports, the helpers explain
    monkeypatch.setitem(sys.modules, "opentelemetry", None)

    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.Name = name

    otel.stamp_constructions(collection)
    with pytest.raises(ImportError, match=r"mnemonica\[otel\]"):
        User("ada")  # the hook fires and needs the trace API
    with pytest.raises(ImportError, match=r"mnemonica\[otel\]"):
        otel.start_linked_span(cast(Any, None), "x", object())
    with pytest.raises(ImportError, match=r"mnemonica\[otel\]"):
        otel.record_lineage(cast(Any, None), span=cast(Any, None))
