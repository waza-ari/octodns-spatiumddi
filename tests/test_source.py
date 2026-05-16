from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from octodns.zone import Zone

from octodns_spatiumddi.client import (
    GroupSummary,
    RecordResponse,
    ViewResponse,
    ZoneResponse,
)
from octodns_spatiumddi.source import SpatiumDDISource

GROUP_ID = UUID("11111111-1111-1111-1111-111111111111")
VIEW_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ZONE_ID = UUID("22222222-2222-2222-2222-222222222222")


class FakeClient:
    def __init__(
        self,
        *,
        groups: list[GroupSummary] | None = None,
        views: list[ViewResponse] | None = None,
        zones: list[ZoneResponse] | None = None,
        records: list[RecordResponse] | None = None,
    ) -> None:
        self._groups = groups or [GroupSummary(id=GROUP_ID, name="default")]
        self._views = views or []
        self._zones = zones or []
        self._records = records or []

    def list_groups(self) -> list[GroupSummary]:
        return list(self._groups)

    def list_views(self, group_id: UUID) -> list[ViewResponse]:
        return [v for v in self._views if v.group_id == group_id]

    def list_zones(self, group_id: UUID) -> list[ZoneResponse]:
        return [z for z in self._zones if z.group_id == group_id]

    def list_records(self, group_id: UUID, zone_id: UUID) -> list[RecordResponse]:
        return [r for r in self._records if r.zone_id == zone_id]


def _zone_resp(view_id: UUID | None = None, ttl: int = 3600) -> ZoneResponse:
    return ZoneResponse(id=ZONE_ID, group_id=GROUP_ID, view_id=view_id, name="example.com", ttl=ttl)


def _record(
    *,
    name: str = "www",
    fqdn: str = "www.example.com",
    record_type: str = "A",
    value: str = "192.0.2.1",
    ttl: int | None = None,
    priority: int | None = None,
    weight: int | None = None,
    port: int | None = None,
    auto_generated: bool = False,
    pool_member_id: UUID | None = None,
    view_id: UUID | None = None,
    rid: str = "00000000-0000-0000-0000-000000000001",
) -> RecordResponse:
    return RecordResponse(
        id=UUID(rid),
        zone_id=ZONE_ID,
        view_id=view_id,
        name=name,
        fqdn=fqdn,
        record_type=record_type,
        value=value,
        ttl=ttl,
        priority=priority,
        weight=weight,
        port=port,
        auto_generated=auto_generated,
        pool_member_id=pool_member_id,
    )


def _make_source(client: FakeClient, **overrides: Any) -> SpatiumDDISource:
    kwargs: dict[str, Any] = {
        "url": "https://spatium.example.com",
        "token": "t",
        "group": "default",
    }
    kwargs.update(overrides)
    return SpatiumDDISource("test", client=client, **kwargs)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def test_group_not_found_raises() -> None:
    client = FakeClient(groups=[GroupSummary(id=GROUP_ID, name="other")])
    with pytest.raises(ValueError, match="group not found"):
        _make_source(client)


def test_view_not_found_raises() -> None:
    client = FakeClient(views=[])
    with pytest.raises(ValueError, match="view not found"):
        _make_source(client, view="missing")


def test_view_resolution_succeeds() -> None:
    client = FakeClient(views=[ViewResponse(id=VIEW_ID, group_id=GROUP_ID, name="internal")])
    src = _make_source(client, view="internal")
    assert src._view_id == VIEW_ID


# ---------------------------------------------------------------------------
# populate basics
# ---------------------------------------------------------------------------
def test_populate_returns_false_when_zone_missing() -> None:
    src = _make_source(FakeClient(zones=[]))
    z = Zone("example.com.", [])
    assert src.populate(z) is False
    assert len(z.records) == 0


def test_populate_multivalue_a_aggregated_and_sorted() -> None:
    records = [
        _record(value="192.0.2.5", rid="00000000-0000-0000-0000-000000000001"),
        _record(value="192.0.2.1", rid="00000000-0000-0000-0000-000000000002"),
    ]
    src = _make_source(FakeClient(zones=[_zone_resp()], records=records))
    z = Zone("example.com.", [])
    assert src.populate(z) is True
    assert len(z.records) == 1
    r = next(iter(z.records))
    assert r._type == "A"
    assert r.values == ["192.0.2.1", "192.0.2.5"]


def test_populate_apex_record() -> None:
    records = [_record(name="@", fqdn="example.com", value="192.0.2.10")]
    src = _make_source(FakeClient(zones=[_zone_resp()], records=records))
    z = Zone("example.com.", [])
    src.populate(z)
    r = next(iter(z.records))
    assert r.name == ""


def test_populate_skips_fqdn_outside_zone() -> None:
    records = [_record(fqdn="x.elsewhere.org", value="192.0.2.1")]
    src = _make_source(FakeClient(zones=[_zone_resp()], records=records))
    z = Zone("example.com.", [])
    src.populate(z)
    assert len(z.records) == 0


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
def test_auto_generated_included_by_default() -> None:
    records = [_record(auto_generated=True)]
    src = _make_source(FakeClient(zones=[_zone_resp()], records=records))
    z = Zone("example.com.", [])
    src.populate(z)
    assert len(z.records) == 1


def test_auto_generated_excluded_when_disabled() -> None:
    records = [_record(auto_generated=True)]
    src = _make_source(
        FakeClient(zones=[_zone_resp()], records=records), include_auto_generated=False
    )
    z = Zone("example.com.", [])
    src.populate(z)
    assert len(z.records) == 0


def test_pool_members_skipped_by_default() -> None:
    pool_id = UUID("33333333-3333-3333-3333-333333333333")
    records = [_record(pool_member_id=pool_id)]
    src = _make_source(FakeClient(zones=[_zone_resp()], records=records))
    z = Zone("example.com.", [])
    src.populate(z)
    assert len(z.records) == 0


def test_unknown_record_type_skipped_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    records = [_record(record_type="HTTPS", value="something")]
    src = _make_source(FakeClient(zones=[_zone_resp()], records=records))
    z = Zone("example.com.", [])
    with caplog.at_level("WARNING"):
        src.populate(z)
    assert len(z.records) == 0
    assert any("unsupported record type=HTTPS" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# Mapping per type
# ---------------------------------------------------------------------------
def test_ttl_falls_back_to_zone_ttl() -> None:
    records = [_record(ttl=None)]
    src = _make_source(FakeClient(zones=[_zone_resp(ttl=7200)], records=records))
    z = Zone("example.com.", [])
    src.populate(z)
    assert next(iter(z.records)).ttl == 7200


def test_txt_semicolon_escaped() -> None:
    records = [_record(record_type="TXT", value="v=spf1 include:_spf.example.com; -all")]
    src = _make_source(FakeClient(zones=[_zone_resp()], records=records))
    z = Zone("example.com.", [])
    src.populate(z)
    r = next(iter(z.records))
    assert r.values == [r"v=spf1 include:_spf.example.com\; -all"]


def test_mx_packed_with_preference() -> None:
    records = [
        _record(
            name="@",
            fqdn="example.com",
            record_type="MX",
            value="mail.example.com.",
            priority=10,
        )
    ]
    src = _make_source(FakeClient(zones=[_zone_resp()], records=records))
    z = Zone("example.com.", [])
    src.populate(z)
    r = next(iter(z.records))
    assert r.values[0].preference == 10
    assert r.values[0].exchange == "mail.example.com."


def test_srv_packed_with_target() -> None:
    records = [
        _record(
            name="_sip._tcp",
            fqdn="_sip._tcp.example.com",
            record_type="SRV",
            value="sip.example.com.",
            priority=10,
            weight=20,
            port=5060,
        )
    ]
    src = _make_source(FakeClient(zones=[_zone_resp()], records=records))
    z = Zone("example.com.", [])
    src.populate(z)
    r = next(iter(z.records))
    assert r.values[0].priority == 10
    assert r.values[0].weight == 20
    assert r.values[0].port == 5060
    assert r.values[0].target == "sip.example.com."


def test_caa_parsed_from_value() -> None:
    records = [
        _record(
            name="@",
            fqdn="example.com",
            record_type="CAA",
            value='0 issue "letsencrypt.org"',
        )
    ]
    src = _make_source(FakeClient(zones=[_zone_resp()], records=records))
    z = Zone("example.com.", [])
    src.populate(z)
    r = next(iter(z.records))
    assert r.values[0].flags == 0
    assert r.values[0].tag == "issue"
    assert r.values[0].value == "letsencrypt.org"


def test_cname_single_value_enforced(caplog: pytest.LogCaptureFixture) -> None:
    records = [
        _record(
            record_type="CNAME",
            value="a.example.com.",
            rid="00000000-0000-0000-0000-000000000001",
        ),
        _record(
            record_type="CNAME",
            value="b.example.com.",
            rid="00000000-0000-0000-0000-000000000002",
        ),
    ]
    src = _make_source(FakeClient(zones=[_zone_resp()], records=records))
    z = Zone("example.com.", [])
    with caplog.at_level("ERROR"):
        src.populate(z)
    r = next(iter(z.records))
    assert r._type == "CNAME"
    assert r.value == "a.example.com."
    assert any("multiple CNAME" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# View filtering
# ---------------------------------------------------------------------------
def test_zone_filtered_by_view_unset_only_null() -> None:
    zones = [
        _zone_resp(view_id=None),
        ZoneResponse(
            id=UUID("44444444-4444-4444-4444-444444444444"),
            group_id=GROUP_ID,
            view_id=VIEW_ID,
            name="example.com",
            ttl=3600,
        ),
    ]
    src = _make_source(FakeClient(zones=zones))
    src._zone_for_name("example.com.")
    assert src._zone_cache is not None
    assert next(iter(src._zone_cache.values())).view_id is None


def test_zone_filtered_by_view_set_matches_only() -> None:
    other_view = UUID("55555555-5555-5555-5555-555555555555")
    zones = [
        ZoneResponse(
            id=ZONE_ID,
            group_id=GROUP_ID,
            view_id=VIEW_ID,
            name="example.com",
            ttl=3600,
        ),
        ZoneResponse(
            id=UUID("66666666-6666-6666-6666-666666666666"),
            group_id=GROUP_ID,
            view_id=other_view,
            name="example.com",
            ttl=3600,
        ),
    ]
    client = FakeClient(
        views=[ViewResponse(id=VIEW_ID, group_id=GROUP_ID, name="internal")],
        zones=zones,
    )
    src = _make_source(client, view="internal")
    src._zone_for_name("example.com.")
    assert src._zone_cache is not None
    assert next(iter(src._zone_cache.values())).view_id == VIEW_ID
