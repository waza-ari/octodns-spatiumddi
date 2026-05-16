from uuid import UUID

import pytest
import responses

from octodns_spatiumddi.client import SpatiumDDIClient

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


@responses.activate
def test_list_records_path() -> None:
    responses.get(
        f"{BASE}/api/v1/dns/groups/{GROUP_ID}/zones/{ZONE_ID}/records",
        json=[],
        status=200,
    )
    assert _client().list_records(GROUP_ID, ZONE_ID) == []


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
