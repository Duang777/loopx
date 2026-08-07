from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from loopx.http_server import CONTROL_SESSION_HEADER, create_app


ORIGIN = "http://127.0.0.1:8765"
NON_LOOPBACK_IP = ".".join(("192", "168", "1", "2"))


class _EmptyApplication:
    def describe_capabilities(self) -> tuple[object, ...]:
        return ()

    def list_goals(self) -> tuple[object, ...]:
        return ()


def _client(*, profile: str = "local_operator") -> TestClient:
    return TestClient(
        create_app(_EmptyApplication(), profile=profile),
        base_url=ORIGIN,
    )


def _same_origin_headers(**extra: str) -> dict[str, str]:
    return {
        "Origin": ORIGIN,
        "Referer": f"{ORIGIN}/operator",
        "Sec-Fetch-Site": "same-origin",
        **extra,
    }


def _new_session(client: TestClient) -> str:
    response = client.post(
        "/api/v1/control-sessions",
        json={},
        headers=_same_origin_headers(),
    )
    assert response.status_code == 201
    return response.json()["control_session_id"]


@pytest.mark.parametrize("bind_host", ["0.0.0.0", "localhost", NON_LOOPBACK_IP, "::"])
def test_factory_rejects_non_exact_loopback_bind(bind_host: str) -> None:
    with pytest.raises(ValueError, match="bind_host"):
        create_app(_EmptyApplication(), bind_host=bind_host)


@pytest.mark.parametrize(
    ("allowed_hosts", "public_origin"),
    [
        (("localhost:8765",), "http://localhost:8765"),
        ((f"{NON_LOOPBACK_IP}:8765",), f"http://{NON_LOOPBACK_IP}:8765"),
        (("example.test:8765",), "http://example.test:8765"),
    ],
)
def test_factory_rejects_non_numeric_loopback_authority(
    allowed_hosts: tuple[str, ...],
    public_origin: str,
) -> None:
    with pytest.raises(ValueError, match="127.0.0.1 or ::1"):
        create_app(
            _EmptyApplication(),
            allowed_hosts=allowed_hosts,
            public_origin=public_origin,
        )


def test_wrong_host_is_rejected_before_dispatch() -> None:
    response = _client().get(
        "/api/v1/health",
        headers={"Host": f"{NON_LOOPBACK_IP}:8765"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_host"


@pytest.mark.parametrize(
    ("headers", "expected_code"),
    [
        ({}, "origin_denied"),
        ({"Origin": "https://evil.test"}, "origin_denied"),
        ({"Origin": ORIGIN}, "referer_required"),
        (
            {"Origin": ORIGIN, "Referer": "https://evil.test/"},
            "referer_denied",
        ),
        (
            {"Origin": ORIGIN, "Referer": f"{ORIGIN}/"},
            "fetch_site_denied",
        ),
        (
            {
                "Origin": ORIGIN,
                "Referer": f"{ORIGIN}/",
                "Sec-Fetch-Site": "cross-site",
            },
            "fetch_site_denied",
        ),
    ],
)
def test_control_session_creation_fails_closed_on_cross_site_metadata(
    headers: dict[str, str],
    expected_code: str,
) -> None:
    response = _client().post(
        "/api/v1/control-sessions",
        json={},
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == expected_code


def test_non_json_write_is_rejected() -> None:
    response = _client().post(
        "/api/v1/control-sessions",
        content="{}",
        headers={**_same_origin_headers(), "Content-Type": "text/plain"},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "json_required"


def test_operator_acquire_takeover_release_demotes_old_session() -> None:
    client = _client()
    first = _new_session(client)
    second = _new_session(client)

    acquired = client.post(
        "/api/v1/operator/acquire",
        json={"confirmed": True},
        headers=_same_origin_headers(**{CONTROL_SESSION_HEADER: first}),
    )
    assert acquired.status_code == 200
    assert acquired.json()["role"] == "operator"

    occupied = client.post(
        "/api/v1/operator/acquire",
        json={"confirmed": True},
        headers=_same_origin_headers(**{CONTROL_SESSION_HEADER: second}),
    )
    assert occupied.status_code == 409
    assert occupied.json()["error"]["code"] == "operator_slot_occupied"

    takeover = client.post(
        "/api/v1/operator/takeover",
        json={"confirmed": True},
        headers=_same_origin_headers(**{CONTROL_SESSION_HEADER: second}),
    )
    assert takeover.status_code == 200
    assert takeover.json()["role"] == "operator"
    assert (
        client.get(
            "/api/v1/operator",
            headers={CONTROL_SESSION_HEADER: first},
        ).json()["role"]
        == "viewer"
    )

    old_release = client.post(
        "/api/v1/operator/release",
        json={"confirmed": True},
        headers=_same_origin_headers(**{CONTROL_SESSION_HEADER: first}),
    )
    assert old_release.status_code == 403
    released = client.post(
        "/api/v1/operator/release",
        json={"confirmed": True},
        headers=_same_origin_headers(**{CONTROL_SESSION_HEADER: second}),
    )
    assert released.status_code == 200
    assert released.json()["operator_slot_occupied"] is False


def test_operator_requests_require_confirmation_and_custom_session_header() -> None:
    client = _client()
    session = _new_session(client)
    missing_header = client.post(
        "/api/v1/operator/acquire",
        json={"confirmed": True},
        headers=_same_origin_headers(),
    )
    assert missing_header.status_code == 401
    unconfirmed = client.post(
        "/api/v1/operator/acquire",
        json={"confirmed": False},
        headers=_same_origin_headers(**{CONTROL_SESSION_HEADER: session}),
    )
    assert unconfirmed.status_code == 422


def test_read_only_profile_never_grants_operator() -> None:
    client = _client(profile="read_only")
    session = _new_session(client)
    response = client.post(
        "/api/v1/operator/acquire",
        json={"confirmed": True},
        headers=_same_origin_headers(**{CONTROL_SESSION_HEADER: session}),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "profile_read_only"


def test_server_restart_invalidates_control_sessions_and_operator_slot() -> None:
    first_client = _client()
    old_session = _new_session(first_client)
    assert (
        first_client.post(
            "/api/v1/operator/acquire",
            json={"confirmed": True},
            headers=_same_origin_headers(**{CONTROL_SESSION_HEADER: old_session}),
        ).status_code
        == 200
    )

    restarted = _client()
    status = restarted.get("/api/v1/operator")
    assert status.json()["operator_slot_occupied"] is False
    stale = restarted.post(
        "/api/v1/operator/acquire",
        json={"confirmed": True},
        headers=_same_origin_headers(**{CONTROL_SESSION_HEADER: old_session}),
    )
    assert stale.status_code == 401


def test_get_mutation_and_options_fail_without_cors_headers() -> None:
    client = _client()
    get_mutation = client.get("/api/v1/operator/acquire")
    assert get_mutation.status_code >= 400
    assert "access-control-allow-origin" not in get_mutation.headers

    preflight = client.options(
        "/api/v1/goals",
        headers={
            "Origin": "https://evil.test",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert preflight.status_code == 403
    assert preflight.json()["error"]["code"] == "cors_disabled"
    assert "access-control-allow-origin" not in preflight.headers
