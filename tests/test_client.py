from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
import responses

from octodns_spatiumddi.client import SpatiumDDIClient


def _page_of(url: str | None) -> str:
    assert url is not None
    return parse_qs(urlsplit(url).query)["page"][0]


BASE = "https://spatium.example.com"
GROUP_ID = UUID("11111111-1111-1111-1111-111111111111")
ZONE_ID = UUID("22222222-2222-2222-2222-222222222222")


def _client() -> SpatiumDDIClient:
    return SpatiumDDIClient(url=BASE, token="t0ken", retries=0)


@responses.activate
def test_list_groups_url_and_auth() -> None:
    responses.get(
        f"{BASE}/api/v1/dns/groups",
        json=[{"id": str(GROUP_ID), "name": "default"}],
        status=200,
    )
    groups = _client().list_groups()
    assert [(g.id, g.name) for g in groups] == [(GROUP_ID, "default")]
    assert responses.calls[0].request.headers["Authorization"] == "Bearer t0ken"


@responses.activate
def test_list_zones_path() -> None:
    responses.get(
        f"{BASE}/api/v1/dns/groups/{GROUP_ID}/zones",
        json=[
            {
                "id": str(ZONE_ID),
                "group_id": str(GROUP_ID),
                "view_id": None,
                "name": "example.com",
                "ttl": 3600,
            }
        ],
        status=200,
    )
    zones = _client().list_zones(GROUP_ID)
    assert zones[0].name == "example.com"
    assert zones[0].ttl == 3600


def _record(name: str, value: str) -> dict[str, object]:
    return {
        "id": str(UUID(int=abs(hash(name)) % (1 << 128))),
        "zone_id": str(ZONE_ID),
        "view_id": None,
        "name": name,
        "fqdn": f"{name}.example.com.",
        "record_type": "A",
        "value": value,
        "ttl": 3600,
        "priority": None,
        "weight": None,
        "port": None,
        "auto_generated": False,
    }


@responses.activate
def test_list_records_legacy_bare_array() -> None:
    # Older SpatiumDDI returned a bare JSON array.
    responses.get(
        f"{BASE}/api/v1/dns/groups/{GROUP_ID}/zones/{ZONE_ID}/records",
        json=[],
        status=200,
    )
    assert _client().list_records(GROUP_ID, ZONE_ID) == []


@responses.activate
def test_list_records_paginated_envelope() -> None:
    # Newer SpatiumDDI wraps records in a page envelope. Regression test for
    # the ValidationError raised when iterating the dict keys ('items', ...).
    responses.get(
        f"{BASE}/api/v1/dns/groups/{GROUP_ID}/zones/{ZONE_ID}/records",
        json={
            "items": [_record("a", "10.0.0.1"), _record("b", "10.0.0.2")],
            "total": 2,
            "page": 1,
            "page_size": 1000,
        },
        status=200,
    )
    records = _client().list_records(GROUP_ID, ZONE_ID)
    assert [r.name for r in records] == ["a", "b"]


@responses.activate
def test_list_records_follows_multiple_pages() -> None:
    # total exceeds a single page: the client must walk every page so large
    # zones are not silently truncated.
    url = f"{BASE}/api/v1/dns/groups/{GROUP_ID}/zones/{ZONE_ID}/records"
    responses.get(
        url,
        json={
            "items": [_record(f"p1-{i}", "10.0.0.1") for i in range(1000)],
            "total": 1500,
            "page": 1,
            "page_size": 1000,
        },
        status=200,
    )
    responses.get(
        url,
        json={
            "items": [_record(f"p2-{i}", "10.0.0.2") for i in range(500)],
            "total": 1500,
            "page": 2,
            "page_size": 1000,
        },
        status=200,
    )
    records = _client().list_records(GROUP_ID, ZONE_ID)
    assert len(records) == 1500
    assert _page_of(responses.calls[0].request.url) == "1"
    assert _page_of(responses.calls[1].request.url) == "2"


@responses.activate
def test_non_2xx_raises_value_error() -> None:
    responses.get(f"{BASE}/api/v1/dns/groups", json={"detail": "nope"}, status=401)
    with pytest.raises(ValueError, match="401"):
        _client().list_groups()


@responses.activate
def test_retry_on_5xx_then_success() -> None:
    url = f"{BASE}/api/v1/dns/groups"
    responses.get(url, status=503)
    responses.get(url, status=503)
    responses.get(url, json=[{"id": str(GROUP_ID), "name": "default"}], status=200)

    c = SpatiumDDIClient(url=BASE, token="t", retries=3)
    groups = c.list_groups()
    assert len(groups) == 1
    assert len(responses.calls) == 3
