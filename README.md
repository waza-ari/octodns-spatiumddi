<h1 align="center">octodns-spatiumddi</h1>

<p align="center">
  <strong>An <a href="https://github.com/octodns/octodns">octoDNS</a> source for <a href="https://github.com/spatiumddi/spatiumddi">SpatiumDDI</a> — read zones and records from SpatiumDDI and sync them anywhere octoDNS goes.</strong>
</p>

<p align="center">
  <a href="https://pypi.python.org/pypi/octodns-spatiumddi"><img src="https://img.shields.io/pypi/v/octodns-spatiumddi" alt="PyPI"/></a>
  <a href="https://pypi.python.org/pypi/octodns-spatiumddi"><img src="https://img.shields.io/pypi/pyversions/octodns-spatiumddi" alt="Python versions"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/pypi/l/octodns-spatiumddi" alt="License"/></a>
  <img src="https://img.shields.io/badge/status-alpha-orange" alt="Status: alpha"/>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/lint-ruff-FCC21B" alt="Lint: ruff"/></a>
  <a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/type%20checked-mypy-blue" alt="Type checked: mypy"/></a>
</p>

---

> ⚠️ **Alpha software.** Both this provider and [SpatiumDDI](https://github.com/spatiumddi/spatiumddi) itself are under active development. APIs, schemas, configuration keys, and defaults **may change without notice** between releases. Pin your versions, watch the changelog, and don't put it in front of anything you care about until both projects stabilise. Bug reports and PRs welcome.

---

## Contents

- [What this is](#what-this-is)
- [Install](#install)
- [Getting started](#getting-started)
- [Full configuration reference](#full-configuration-reference)
- [Supported record types](#supported-record-types)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

## What this is

`octodns-spatiumddi` is a **source-only** [octoDNS](https://github.com/octodns/octodns) provider for [SpatiumDDI](https://github.com/spatiumddi/spatiumddi).

It reads zones and records from a SpatiumDDI instance and lets octoDNS sync them to any supported provider (YAML files, Route 53, Cloudflare, NS1, …). It does **not** write back to SpatiumDDI — SpatiumDDI remains the source of truth.

Typical use cases:

- Mirror SpatiumDDI-managed zones into an upstream authoritative DNS provider (Route 53, Azure DNS, etc.).
- Export the live state of every zone to YAML for review, diffing, or backup.
- Drive multi-target replication: one SpatiumDDI, many downstream providers.

## Install

```sh
pip install octodns-spatiumddi
# or
uv add octodns-spatiumddi
```

## Getting started

Minimal configuration that reads one zone from SpatiumDDI and dumps it to a YAML file:

```yaml
providers:
  spatiumddi:
    class: octodns_spatiumddi.SpatiumDDISource
    url: https://spatium.example.com
    token: env/SPATIUMDDI_TOKEN
    group: production

  yaml-out:
    class: octodns.provider.yaml.YamlProvider
    directory: ./out
    default_ttl: 3600

zones:
  example.com.:
    sources:
      - spatiumddi
    targets:
      - yaml-out
```

Run it:

```sh
export SPATIUMDDI_TOKEN=...
octodns-sync --config-file=config.yaml         # dry run
octodns-sync --config-file=config.yaml --doit  # apply
```

### Running the bundled example

A complete runnable configuration lives in [`examples/config.yaml`](examples/config.yaml). It reads zones from SpatiumDDI and writes them as octoDNS YAML files into `examples/out/`.

```sh
export SPATIUMDDI_URL=https://spatium.example.com
export SPATIUMDDI_TOKEN=...
export SPATIUMDDI_GROUP=production

# Dry run — shows the diff, writes nothing
octodns-sync --config-file=examples/config.yaml

# Apply — writes per-zone YAML files into examples/out/
octodns-sync --config-file=examples/config.yaml --doit
```

Edit `examples/config.yaml` to add more zones under `zones:`. Names must match SpatiumDDI exactly (with the trailing dot).

## Full configuration reference

Every option, with defaults and notes. This is the same configuration shipped in [`examples/config.yaml`](examples/config.yaml).

```yaml
providers:
  spatiumddi:
    class: octodns_spatiumddi.SpatiumDDISource

    # Base URL of your SpatiumDDI instance (required, no trailing slash).
    # Must use http:// or https://. Validated at startup.
    url: env/SPATIUMDDI_URL

    # Bearer token for SpatiumDDI's API (required).
    # Use octoDNS' env/VAR interpolation so the secret stays out of YAML.
    # The token is stored as pydantic.SecretStr and never logged.
    token: env/SPATIUMDDI_TOKEN

    # SpatiumDDI DNS group name (required).
    # Looked up against /api/v1/dns/groups at startup; resolves to a UUID.
    # Each source instance is scoped to one group. To pull from multiple
    # groups, define one provider entry per group.
    group: env/SPATIUMDDI_GROUP

    # SpatiumDDI view name (Optional, default: unset).
    # When set, only zones and records in this view are read.
    # When unset, only zones and records with view_id=null are read —
    # so leave this unset if you do not use views in SpatiumDDI.
    # view: internal

    # Disable TLS verification (Optional, default: false).
    # Useful when SpatiumDDI is fronted by an internal CA whose root is not
    # in the system trust store. Avoid in production.
    # insecure: false

    # Per-request timeout in seconds (Optional, default: 30).
    # Applies to both connect and read phases of every API call.
    # timeout: 30

    # Retry budget for 5xx and connection errors (Optional, default: 3).
    # Uses urllib3.Retry with exponential backoff. 4xx responses are not
    # retried — those are surfaced immediately.
    # retries: 3

    # Include SpatiumDDI's auto-generated records (Optional, default: true).
    # SpatiumDDI flags records it created itself (reverse PTRs spawned from
    # IPAM, NS records derived from SOA, etc.) as `auto_generated=true`.
    # Set false to exclude them from the octoDNS view of the zone.
    # include_auto_generated: true

    # Include records that are members of a load-balancing pool
    # (Optional, default: false).
    # SpatiumDDI's pool members carry `pool_member_id` and are managed by
    # the pool, not addressed directly. Including them duplicates state
    # owned by the pool. Leave off unless you know you need them.
    # include_pool_members: false
```

## Supported record types

`A`, `AAAA`, `CNAME`, `TXT`, `MX`, `NS`, `SRV`, `PTR`, `CAA`.

Unknown record types are logged at `WARNING` and skipped — they don't fail the sync.

Records with `auto_generated=true` are included by default. Records that are pool members are excluded by default. Both behaviours are configurable.

## Troubleshooting

Every `populate` call emits a summary line like:

```
SpatiumDDISource[spatiumddi] zone=example.com. fetched=42 kept=39
  dropped=[view=0, auto_generated=2, pool_member=1, unsupported_type=0]
```

Use it to see exactly which filter removed a record. For per-record reasoning, set the log level to `DEBUG`.

If `kept=0` and `dropped[view]` is non-zero, your zone is in a SpatiumDDI view but `view:` is unset (or set to the wrong view) in YAML.

If a zone is missing entirely (`populate` returns `False`), confirm the zone name in YAML matches SpatiumDDI exactly — including views — and that your token has read access to that group.

## Development

Built with [uv](https://github.com/astral-sh/uv) and [task](https://taskfile.dev).

```sh
task          # list tasks
task setup    # uv sync + install pre-commit hooks
task test     # run pytest with coverage
task lint     # ruff + mypy
task fmt      # auto-fix and format
task check    # lint + test
task sync-example         # dry-run the bundled example
task sync-example-apply   # apply the bundled example
```

Pull requests run lint, type checks, and tests automatically via GitHub Actions. Tagged releases publish to TestPyPI and then to PyPI on manual approval.
