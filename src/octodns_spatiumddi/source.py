from __future__ import annotations

import logging
import shlex
from collections.abc import Iterable
from typing import Any, Protocol
from uuid import UUID

from octodns.record import Record
from octodns.source.base import BaseSource
from octodns.zone import Zone

from octodns_spatiumddi.client import (
    GroupSummary,
    RecordResponse,
    SpatiumDDIClient,
    ViewResponse,
    ZoneResponse,
)
from octodns_spatiumddi.config import SpatiumDDIConfig


class _ClientProtocol(Protocol):
    def list_groups(self) -> list[GroupSummary]: ...
    def list_views(self, group_id: UUID) -> list[ViewResponse]: ...
    def list_zones(self, group_id: UUID) -> list[ZoneResponse]: ...
    def list_records(self, group_id: UUID, zone_id: UUID) -> list[RecordResponse]: ...


_SUPPORTED_TYPES: frozenset[str] = frozenset(
    {"A", "AAAA", "CNAME", "TXT", "MX", "NS", "SRV", "PTR", "CAA"}
)
_SINGLE_VALUE_TYPES: frozenset[str] = frozenset({"CNAME"})


class SpatiumDDISource(BaseSource):  # type: ignore[misc]
    SUPPORTS_GEO = False
    SUPPORTS_ROOT_NS = True
    SUPPORTS = _SUPPORTED_TYPES

    def __init__(
        self,
        id: str,
        *,
        client: _ClientProtocol | None = None,
        **kwargs: Any,
    ) -> None:
        self.log = logging.getLogger(f"SpatiumDDISource[{id}]")
        super().__init__(id)
        self.config = SpatiumDDIConfig(**kwargs)
        self.client: _ClientProtocol = client or SpatiumDDIClient(
            url=self.config.url,
            token=self.config.token.get_secret_value(),
            timeout=self.config.timeout,
            insecure=self.config.insecure,
            retries=self.config.retries,
        )
        self._group_id = self._resolve_group_id(self.config.group)
        self._view_id = self._resolve_view_id(self.config.view) if self.config.view else None
        self._zone_cache: dict[str, ZoneResponse] | None = None

    def populate(self, zone: Zone, target: bool = False, lenient: bool = False) -> bool:
        self.log.info("populate zone=%s target=%s lenient=%s", zone.name, target, lenient)
        zr = self._zone_for_name(zone.name)
        if zr is None:
            self.log.info("zone=%s not found", zone.name)
            return False

        raw_records = self.client.list_records(self._group_id, zr.id)
        records, stats = self._filter_records_with_stats(raw_records)
        self.log.info(
            "zone=%s fetched=%d kept=%d dropped=[view=%d, auto_generated=%d, "
            "pool_member=%d, unsupported_type=%d]",
            zone.name,
            len(raw_records),
            len(records),
            stats["view"],
            stats["auto_generated"],
            stats["pool_member"],
            stats["unsupported_type"],
        )
        for name, data in self._group_records(records, zr, zone.name):
            r = Record.new(zone, name, data, source=self, lenient=lenient)
            zone.add_record(r, lenient=lenient)
        self.log.info("populate zone=%s loaded %d record(s)", zone.name, len(zone.records))
        return True

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------
    def _resolve_group_id(self, name: str) -> UUID:
        matches = [g for g in self.client.list_groups() if g.name == name]
        if not matches:
            raise ValueError(f"SpatiumDDI group not found: {name!r}")
        if len(matches) > 1:
            raise ValueError(f"SpatiumDDI group name is ambiguous: {name!r}")
        return matches[0].id

    def _resolve_view_id(self, name: str) -> UUID:
        matches = [v for v in self.client.list_views(self._group_id) if v.name == name]
        if not matches:
            raise ValueError(f"SpatiumDDI view not found in group: {name!r}")
        if len(matches) > 1:
            raise ValueError(f"SpatiumDDI view name is ambiguous: {name!r}")
        return matches[0].id

    def _zone_for_name(self, zone_name: str) -> ZoneResponse | None:
        bare = zone_name.rstrip(".")
        if self._zone_cache is None:
            self._zone_cache = {
                z.name.rstrip("."): z
                for z in self.client.list_zones(self._group_id)
                if z.view_id == self._view_id
            }
        return self._zone_cache.get(bare)

    # ------------------------------------------------------------------
    # Filtering and grouping
    # ------------------------------------------------------------------
    def _filter_records(self, records: Iterable[RecordResponse]) -> Iterable[RecordResponse]:
        kept, _ = self._filter_records_with_stats(records)
        yield from kept

    def _filter_records_with_stats(
        self, records: Iterable[RecordResponse]
    ) -> tuple[list[RecordResponse], dict[str, int]]:
        stats = {"view": 0, "auto_generated": 0, "pool_member": 0, "unsupported_type": 0}
        kept: list[RecordResponse] = []
        for r in records:
            if r.view_id != self._view_id:
                stats["view"] += 1
                self.log.debug(
                    "drop record id=%s fqdn=%s reason=view (record_view=%s, source_view=%s)",
                    r.id,
                    r.fqdn,
                    r.view_id,
                    self._view_id,
                )
                continue
            if r.auto_generated and not self.config.include_auto_generated:
                stats["auto_generated"] += 1
                self.log.debug("drop record id=%s fqdn=%s reason=auto_generated", r.id, r.fqdn)
                continue
            if r.pool_member_id is not None and not self.config.include_pool_members:
                stats["pool_member"] += 1
                self.log.debug("drop record id=%s fqdn=%s reason=pool_member", r.id, r.fqdn)
                continue
            if r.record_type not in _SUPPORTED_TYPES:
                stats["unsupported_type"] += 1
                self.log.warning(
                    "skipping unsupported record type=%s name=%s id=%s",
                    r.record_type,
                    r.fqdn,
                    r.id,
                )
                continue
            kept.append(r)
        return kept, stats

    def _group_records(
        self,
        records: list[RecordResponse],
        zone_resp: ZoneResponse,
        zone_name: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        buckets: dict[tuple[str, str], list[RecordResponse]] = {}
        for r in records:
            rel = self._relative_name(r.fqdn, zone_name)
            if rel is None:
                self.log.warning(
                    "skipping record fqdn=%s not within zone=%s (id=%s)",
                    r.fqdn,
                    zone_name,
                    r.id,
                )
                continue
            buckets.setdefault((rel, r.record_type), []).append(r)

        out: list[tuple[str, dict[str, Any]]] = []
        for (name, type_), rows in buckets.items():
            if type_ in _SINGLE_VALUE_TYPES and len(rows) > 1:
                self.log.error(
                    "multiple %s records for name=%s in zone=%s; keeping first (id=%s)",
                    type_,
                    name,
                    zone_name,
                    rows[0].id,
                )
                rows = rows[:1]

            values = [self._format_value(type_, r) for r in rows]
            values = [v for v in values if v is not None]
            if not values:
                continue
            values.sort(key=_sort_key)

            ttl = next((r.ttl for r in rows if r.ttl is not None), zone_resp.ttl)
            data: dict[str, Any] = {"type": type_, "ttl": ttl}
            if type_ in _SINGLE_VALUE_TYPES:
                data["value"] = values[0]
            else:
                data["values"] = values
            out.append((name, data))
        return out

    @staticmethod
    def _relative_name(fqdn: str, zone_name: str) -> str | None:
        fqdn_norm = fqdn.rstrip(".")
        zone_norm = zone_name.rstrip(".")
        if fqdn_norm == zone_norm:
            return ""
        suffix = f".{zone_norm}"
        if not fqdn_norm.endswith(suffix):
            return None
        return fqdn_norm[: -len(suffix)]

    def _format_value(self, type_: str, r: RecordResponse) -> Any:
        match type_:
            case "A" | "AAAA" | "CNAME" | "NS" | "PTR":
                return r.value
            case "TXT":
                return r.value.replace(";", r"\;")
            case "MX":
                if r.priority is None:
                    self.log.warning("MX record missing priority id=%s", r.id)
                    return None
                return {"preference": r.priority, "exchange": r.value}
            case "SRV":
                if r.priority is None or r.weight is None or r.port is None:
                    self.log.warning("SRV record missing priority/weight/port id=%s", r.id)
                    return None
                return {
                    "priority": r.priority,
                    "weight": r.weight,
                    "port": r.port,
                    "target": r.value,
                }
            case "CAA":
                parsed = _parse_caa(r.value)
                if parsed is None:
                    self.log.warning("CAA record has invalid value=%r id=%s", r.value, r.id)
                    return None
                return parsed
            case _:
                return None


def _parse_caa(value: str) -> dict[str, Any] | None:
    try:
        parts = shlex.split(value)
    except ValueError:
        return None
    if len(parts) != 3:
        return None
    flags_str, tag, target = parts
    try:
        flags = int(flags_str)
    except ValueError:
        return None
    return {"flags": flags, "tag": tag, "value": target}


def _sort_key(value: Any) -> tuple[Any, ...]:
    if isinstance(value, dict):
        return tuple(sorted(value.items()))
    return (value,)
