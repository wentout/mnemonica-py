"""The OpenTelemetry link (optional extra: ``pip install mnemonica[otel]``).

The core package never imports opentelemetry: this module does, lazily —
`import mnemonica` and even `import mnemonica.otel` work without the
extra; only calling the helpers requires it.

The attribute contract is cross-language (shared with the Go port's
otelx module), so a trace and a lineage graph join on the same names —
and on the same instance ids, which come from `utils.lineage`'s lazy
id_of:

- ``stamp_constructions(collection)`` registers hooks so every
  construction — successful or errored — stamps the four attributes on
  the span CURRENT at construction (Python resolves it from the
  contextvars context), and records that SpanContext on the instance's
  context record (a small immutable value; weakly safe).
- ``start_linked_span(tracer, name, instance)`` starts a span for work
  that outlives the request, LINKED (``trace.Link``) to the span current
  when the instance was constructed — so an asyncio task or thread that
  runs after the request still joins its trace.
- ``record_lineage(error, span=None)`` adds a span event
  ``mnemonica.error`` carrying the carried instance's lineage graph JSON
  in one attribute. Carriers: ``ErroredInstance`` (a blocked
  construction or a ``utils.exception`` result).
"""

import json
from typing import TYPE_CHECKING, Any, cast

from mnemonica.errors import ErroredInstance, WrongArgumentsUsed
from mnemonica.props import get_props
from mnemonica.types import MnemonicaType
from mnemonica.utils.lineage import id_of, lineage

if TYPE_CHECKING:
    from opentelemetry.context import Context
    from opentelemetry.trace import Span, Tracer

# the cross-language attribute contract (same names as the Go port's
# otelx, so a Jaeger trace and a lineage graph join on them)
ATTR_INSTANCE_ID = "mnemonica.instance.id"
ATTR_PARENT_ID = "mnemonica.parent.id"
ATTR_TYPE_COLLECTION = "mnemonica.type.collection"
ATTR_TYPE_PATH = "mnemonica.type.path"
# the error-path event carries the lineage graph JSON in ONE attribute
# (no per-attribute count pressure; value length is unlimited)
ATTR_LINEAGE_GRAPH = "mnemonica.lineage.graph"
EVENT_ERROR = "mnemonica.error"

# the record key holding the SpanContext current at construction
_RECORD_SPAN_CONTEXT = "otel_span_context"


def _trace_api() -> Any:
    """The opentelemetry trace API, imported lazily so the core and even
    this module import without the optional extra."""
    try:
        from opentelemetry import trace
    except ImportError as error:
        raise ImportError(
            "mnemonica[otel] is required for tracing: pip install 'mnemonica[otel]'"
        ) from error
    result: Any = trace
    return result


def _recorded_span_context(instance: object) -> Any:
    """The SpanContext current at the instance's construction, or None."""
    record = get_props(instance)
    if record is None:
        result: Any = None
        return result
    context = record.get(_RECORD_SPAN_CONTEXT)
    result = context
    return result


def _stamp(hook_data: dict[str, Any]) -> None:
    """The postCreation/creationError hook: stamp the contract attributes
    on the current span and record its SpanContext on the instance."""
    trace = _trace_api()
    span = trace.get_current_span()
    context = span.get_span_context()
    if not context.is_valid:
        return  # no span to stamp: skip before formatting any ids
    instance = hook_data["inheritedInstance"]
    parent = hook_data["existentInstance"]
    mn_type = cast(MnemonicaType, hook_data["type"])
    attributes: dict[str, Any] = {
        ATTR_INSTANCE_ID: id_of(instance),
        ATTR_TYPE_COLLECTION: mn_type.mn_collection.name,
        ATTR_TYPE_PATH: mn_type.mn_path,
    }
    if parent is not None:
        attributes[ATTR_PARENT_ID] = id_of(parent)
    span.set_attributes(attributes)
    record = get_props(instance)
    assert record is not None  # every constructed instance has a record
    record[_RECORD_SPAN_CONTEXT] = context


def stamp_constructions(collection: Any) -> None:
    """Register the stamping hooks on a collection (C5.1). Every
    construction from then on — successful or errored — stamps the four
    contract attributes on the span current at construction."""
    collection.registerHook("postCreation", _stamp)
    collection.registerHook("creationError", _stamp)


def start_linked_span(
    tracer: "Tracer",
    name: str,
    instance: object,
    *,
    context: "Context | None" = None,
) -> "Span":
    """Start a span for work on `instance` that outlives the request: when
    the instance carries a recorded SpanContext, the new span is LINKED
    to the construction span (trace.Link). Without one: a plain span.
    The caller owns the span's lifetime (end() it)."""
    trace = _trace_api()
    recorded = _recorded_span_context(instance)
    links = None
    if recorded is not None and recorded.is_valid:
        links = [trace.Link(recorded)]
    span = tracer.start_span(name, context=context, links=links)
    result = span
    return result


def _carried_instance(error: BaseException) -> object:
    """The instance carried by an ErroredInstance: a utils.exception
    result carries another instance; a blocked construction's errored
    instance IS the carried instance (its own record is complete)."""
    if not isinstance(error, ErroredInstance):
        raise WrongArgumentsUsed(
            f"record_lineage: {type(error).__name__} carries no instance"
        )
    record = get_props(error)
    assert record is not None  # every ErroredInstance carries a record
    carried: Any = record.get("instance", error)
    if carried is error or get_props(carried) is None:
        # fall back to the carrier itself — but only a FULL construction
        # record exports (a utils.exception record around an unexported
        # instance carries no lineage of its own)
        if "collection" not in record:
            raise WrongArgumentsUsed(
                "record_lineage: the carrier has no exportable instance"
            )
        result: object = error
        return result
    result = carried
    return result


def record_lineage(error: BaseException, span: "Span | None" = None) -> None:
    """Attach the carried instance's lineage graph JSON to a span as an
    event named ``mnemonica.error`` — rendering beside the error in every
    trace viewer. `span` defaults to the current span."""
    trace = _trace_api()
    target_span = span if span is not None else trace.get_current_span()
    target = cast("Span", target_span)
    instance = _carried_instance(error)
    graph = lineage(instance)
    raw = json.dumps(graph, sort_keys=True, separators=(",", ":"))
    target.add_event(
        EVENT_ERROR,
        attributes={
            ATTR_INSTANCE_ID: id_of(instance),
            ATTR_LINEAGE_GRAPH: raw,
        },
    )
