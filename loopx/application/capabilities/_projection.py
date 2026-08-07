from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..errors import StateUnavailable


def mapping(value: object, *, resource: str, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise StateUnavailable(details={"resource": resource, "field": field})
    return value


def sequence(value: object, *, resource: str, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise StateUnavailable(details={"resource": resource, "field": field})
    return value


def text(record: Mapping[str, object], field: str, *, resource: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise StateUnavailable(details={"resource": resource, "field": field})
    return value


def optional_text(
    record: Mapping[str, object],
    field: str,
    *,
    resource: str,
) -> str | None:
    if record.get(field) is None:
        return None
    return text(record, field, resource=resource)


def boolean(record: Mapping[str, object], field: str, *, resource: str) -> bool:
    value = record.get(field)
    if not isinstance(value, bool):
        raise StateUnavailable(details={"resource": resource, "field": field})
    return value


def optional_boolean(
    record: Mapping[str, object],
    field: str,
    *,
    resource: str,
) -> bool | None:
    if record.get(field) is None:
        return None
    return boolean(record, field, resource=resource)


def integer(record: Mapping[str, object], field: str, *, resource: str) -> int:
    value = record.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise StateUnavailable(details={"resource": resource, "field": field})
    return value


def optional_integer(
    record: Mapping[str, object],
    field: str,
    *,
    resource: str,
) -> int | None:
    if record.get(field) is None:
        return None
    return integer(record, field, resource=resource)


def text_tuple(value: object, *, resource: str, field: str) -> tuple[str, ...]:
    return tuple(
        text({field: item}, field, resource=resource)
        for item in sequence(value, resource=resource, field=field)
    )
