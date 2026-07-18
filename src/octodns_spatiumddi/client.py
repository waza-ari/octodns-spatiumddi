from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import requests
import urllib3
from pydantic import BaseModel, ConfigDict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class GroupSummary(_ApiModel):
    id: UUID
    name: str


class ViewResponse(_ApiModel):
    id: UUID
    group_id: UUID
    name: str


class ZoneResponse(_ApiModel):
    id: UUID
    group_id: UUID
    view_id: UUID | None
    name: str
    ttl: int


class RecordResponse(_ApiModel):
    id: UUID
    zone_id: UUID
    view_id: UUID | None
    name: str
    fqdn: str
    record_type: str
    value: str
    ttl: int | None
    priority: int | None
    weight: int | None
    port: int | None
    auto_generated: bool
    pool_member_id: UUID | None = None


class SpatiumDDIClient:
    def __init__(
        self,
        url: str,
        token: str,
        *,
        timeout: float = 30.0,
        insecure: bool = False,
        retries: int = 3,
    ) -> None:
        self._base_url = url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        )
        if insecure:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            self._session.verify = False

        retry = Retry(
            total=retries,
            backoff_factor=0.5,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def _get(self, path: str) -> Any:
        resp = self._session.get(f"{self._base_url}{path}", timeout=self._timeout)
        if not resp.ok:
            raise ValueError(f"GET {path} failed: {resp.status_code} {resp.text}")
        return resp.json()

    def _get_paginated(self, path: str, *, page_size: int = 1000) -> list[Any]:
        """Fetch every item from a possibly-paginated list endpoint.

        Newer SpatiumDDI versions wrap list responses in a page envelope
        ``{"items": [...], "total": N, "page": P, "page_size": S}``. Older
        versions return a bare JSON array. This handles both, walking every
        page so large zones are not silently truncated by the server-side
        default page size.
        """
        items: list[Any] = []
        page = 1
        while True:
            sep = "&" if "?" in path else "?"
            data = self._get(f"{path}{sep}page={page}&page_size={page_size}")
            if not isinstance(data, dict):
                # Legacy bare-array response: no pagination to follow.
                return list(data)
            batch = data.get("items", [])
            items.extend(batch)
            total = data.get("total")
            if not batch:
                break
            if total is not None and len(items) >= total:
                break
            if len(batch) < page_size:
                break
            page += 1
        return items

    def list_groups(self) -> list[GroupSummary]:
        data = self._get("/api/v1/dns/groups")
        return [GroupSummary.model_validate(item) for item in data]

    def list_views(self, group_id: UUID) -> list[ViewResponse]:
        data = self._get(f"/api/v1/dns/groups/{group_id}/views")
        return [ViewResponse.model_validate(item) for item in data]

    def list_zones(self, group_id: UUID) -> list[ZoneResponse]:
        data = self._get(f"/api/v1/dns/groups/{group_id}/zones")
        return [ZoneResponse.model_validate(item) for item in data]

    def list_records(self, group_id: UUID, zone_id: UUID) -> list[RecordResponse]:
        data = self._get_paginated(f"/api/v1/dns/groups/{group_id}/zones/{zone_id}/records")
        return [RecordResponse.model_validate(item) for item in data]
