---
name: cribl-search-packs
description: "Build and modify Cribl Search Packs — file layout, dashboards, saved searches, Datatypes, Macros, lookups, pack(…) references, global access, packaging (.crbl), and Dispensary standards. Use when authoring, exporting, importing, or debugging Cribl Search Packs."
argument-hint: "describe the Search Pack you want to build or modify"
desktop: full
---

# Building & Modifying Cribl Search Packs

> **Pack vs Stream Pack — intent check:** If the user is building a **Cribl Search Pack** (Dashboards, saved searches, Datatypes, Macros, lookups), use this skill. If they're building a **Cribl Stream/Edge Pack** (pipelines, routes, sources/destinations), use `/cribl-stream-packs` instead. If they only need dashboard JSON schema or migration, use `/cribl-dashboard-builder` — then package those dashboards into a Search Pack with this skill.

Authoritative working agreement for an LLM coding agent operating on a Cribl Search Pack repository or `.crbl` archive. Ground every change in real Search Pack YAML/JSON. Prefer official docs at https://docs.cribl.io/search/packs and Dispensary standards at https://docs.cribl.io/stream/packs-standards/#search-req.

---

## 1. What a Cribl Search Pack Is

A Search Pack is a portable bundle of preconfigured Cribl Search assets. It ships as a `.crbl` file (`gzip`-compressed `tar` archive). Packs help teams get started faster, demo Search capabilities, and move configurations across Organizations / Workspaces.

### Resources a Pack can contain

| Resource | On-disk location | Notes |
|---|---|---|
| Dashboards | `data/dashboards/<id>.json` | Same JSON schema as global Search dashboards |
| Saved searches | `default/saved-queries.yml` | Map keyed by saved-search ID |
| Datatypes (v1/v2) | `default/breakers.yml` | Search Datatypes are stored as breaker/ruleset entries |
| Macros | `default/macros.yml` | Map keyed by macro ID |
| Lookups | `data/lookups/<name>.csv` + `data/lookups/<name>.yml` | CSV data + YAML descriptor |

A Pack **cannot** reference other Packs. It **can** reference other resources within the same Pack, and global (non-Pack) resources. Global resources can reference Pack resources only when the Pack allows global access.

### Who can use Packs

Search **Admins** and **Editors** can view, install, create, modify, share, and export Packs. See Search Member Permissions in Cribl docs.

---

## 2. Pack File Structure (canonical)

After `tar -xzf <pack>.crbl`, the working tree looks like this (from real Dispensary / production Search Packs):

```
<pack-id>/
├── package.json                         # REQUIRED — pack manifest
├── README.md                            # REQUIRED for sharing / Dispensary
├── default/
│   ├── pack.yml                         # OPTIONAL logo (often base64 data-URI)
│   ├── macros.yml                       # Pack Macros
│   ├── saved-queries.yml                # Pack saved searches
│   └── breakers.yml                     # Pack Datatypes (rulesets)
└── data/
    ├── dashboards/                      # one JSON file per Dashboard
    │   └── <dashboard-id>.json
    └── lookups/                         # lookup CSV + descriptor pairs
        ├── <lookup-id>.csv
        └── <lookup-id>.yml
```

Rules the agent MUST respect:

- **Edit `default/` and `data/`** as the source of truth for Git / `.crbl` authoring. UI edits may create `local/` overlays after import — re-export or replace-import when shipping.
- **Pack ID** = `package.json` `name`. Must be unique in the Organization. Changing the Pack ID breaks `${pack(packId).…}` and `pack(packId).…` references — call this out in the README.
- **No symlinks** inside Pack archives.
- **No secrets** in lookups or configs. Export in merge mode strips encrypted fields; re-enter secrets after import.
- **Dashboard files** are named by dashboard ID (short alphanumeric ids like `bmp8tz2j1.json`), not display name.
- **Lookups** need both the CSV and the `.yml` descriptor (`id`, `size`, `mode`, `tags`, `rows`, `version`).

---

## 3. Manifest Files

### 3.1 `package.json`

```json
{
  "name": "cribl-search-windows-os",
  "version": "0.9.0",
  "author": "Your Name - Cribl",
  "description": "One-to-two sentence hook shown in the Dispensary.",
  "displayName": "Cribl Search Windows OS",
  "tags": {
    "streamtags": ["windows", "eventcode", "os"]
  },
  "exports": ["*"]
}
```

| Field | Purpose |
|---|---|
| `name` | Pack ID. Lowercase `[a-z0-9_-]+`. For Dispensary: `cribl-search-<focus>` or `cc-search-<focus>`. |
| `version` | SemVer. Bump on every ship. Min for Dispensary publication: `0.1.0`. Beta convention: `0.9.0`. |
| `displayName` | Human-readable title (spaces + conventional capitalization). |
| `description` | Short hook (1–2 sentences). |
| `exports` | `["*"]` = allow global access to Pack resources. `[]` / omit = Pack-scoped only. |
| `tags.streamtags` | Optional filter labels. |

Dispensary Pack ID format: `<contributor>-search-<integration>-<focus>` where contributor is `cribl` or `cc`. Do **not** include the word `pack` in the ID.

### 3.2 `default/pack.yml`

Often only holds the logo:

```yaml
logo: data:image/png;base64,...
```

Prefer a transparent PNG ≈280×50 px (max 2 MB / 350×350). You can also set the logo via Pack Settings → Display in the UI.

### 3.3 `README.md`

Required sections for Dispensary (Search Pack Deployment checklist):

1. **About This Pack** — why use it; datasets / data sources it targets.
2. **Deployment** — Dataset Provider, Dataset, Datatype, Macro setup steps. Call out the exact Pack ID users must keep if macros use `pack(packId)`.
3. **Upgrades** (recommended) — how to preserve user-modified lookups.
4. **Release Notes** — `Version X.Y.Z - YYYY-MM-DD` newest first; latest must match `package.json` version.
5. **Contributing** — actionable (e.g. Cribl Community Slack `#packs`).
6. **License** — Apache 2.0 for Cribl-built; public license for community.

No placeholder text. Trademark / product names must match vendor spelling.

---

## 4. Resource Schemas

### 4.1 Macros — `default/macros.yml`

Map keyed by macro ID:

```yaml
windows_log_dataset:
  lib: custom
  replacement: 'dataset="windows_log" '
  description: Primary Windows event-log dataset
  tags: windows
  createdBy: author
  created: 1758888506516
  modified: 1758888506516

search_failed_user_logon:
  lib: custom
  replacement: '${pack(cribl-search-windows-os).windows_log_dataset} Channel=="Security"| where EventID==4625'
  createdBy: author
  created: 1758900801847
  modified: 1759434128839
```

- `replacement` is the Macro body (KQL fragment or full query snippet).
- Prefer **dataset Macros** so customers edit one place when their dataset names differ.
- Inside the same Pack, `${macroId}` works. From outside (or when you want an explicit Pack-qualified ref), use `${pack(packId).macroId}`.

### 4.2 Saved searches — `default/saved-queries.yml`

```yaml
windows_assets:
  name: windows_assets
  description: Build / refresh the windows_assets lookup
  isPrivate: false
  query: >-
    ${pack(cribl-search-windows-os).search_windows_state}
    | summarize latest_activity_time=max(_time) by host
    | export mode=overwrite to lookup windows_assets
  earliest: -1h
  latest: now
  schedule:
    enabled: false
    cronSchedule: 0 0 * * *
    tz: UTC
    keepLastN: 2
    notifications:
      disabled: true
```

**Limitation:** You cannot configure Notifications on a saved search that resides inside a Pack.

**Limitation:** `| export to lookup pack(packId).lookupId` does **not** work. Export to a Pack-local lookup name from inside the Pack, or to a global lookup.

### 4.3 Datatypes — `default/breakers.yml`

Search Datatypes (including v2) ship as entries in `breakers.yml`. Each key is the Datatype ID:

```yaml
windows_datatype_for_pack:
  lib: custom
  description: Datatype rules for MS Windows formats
  tags: windows,eventlogclassic,eventlogxml
  minRawLength: 256
  rules:
    - condition: /LogName=(?:Security|Application|System)/.test(_raw)
      type: regex
      timestamp:
        type: auto
        length: 150
      # … parser / eventBreakerRegex / regexList …
```

Fully qualified ID when used globally: `packId.datatypeId`.

> Pack v2 Datatypes used in federated Dataset path filters resolve at search time even if the Pack does **not** allow global access. Global access only controls whether the Datatype appears in the global Datatypes listing.

**Uninstall hazard:** If a Pack with v2 Datatypes is referenced in a federated Dataset path filter, uninstalling the Pack breaks those searches. Update Dataset Datatype refs first.

**Limitation:** You can't reference a Datatype **from within** a Pack context the way you can Macros/lookups — Datatype assignment is on the Dataset / path filter.

### 4.4 Lookups — `data/lookups/`

```
data/lookups/EventID.csv
data/lookups/EventID.yml
```

Descriptor example:

```yaml
id: EventID.csv
size: 47065
mode: memory
tags: windows,eventid
rows: 591
version: gFzlzgmA
```

- No PII / customer data / secrets in lookup CSVs (Dispensary auto-rejects sensitive lookups).
- Keep CSVs reasonably sized for Git.

### 4.5 Dashboards — `data/dashboards/<id>.json`

Use the dashboard schema and parent-search patterns from `/cribl-dashboard-builder`. Minimal Pack dashboard shape:

```json
{
  "name": "Windows Overview",
  "elements": [ /* inputs, charts, markdown, … */ ],
  "groups": {},
  "schedule": { "enabled": false, "cronSchedule": "0 0 * * *", "tz": "UTC", "keepLastN": 2 }
}
```

In Pack dashboards / queries:

- Prefer `${pack(packId).macroId}` for dataset and filter Macros so global access works consistently.
- Prefer Pack saved searches via `packId.savedSearchId` when basing panels on saved searches from outside the Pack.
- Test every query with Cribl MCP (`cribl_runSearchQuery`) before baking into a dashboard. Pass it as `kqlQuery` (verbatim, no NLP rewriting) and run one search at a time — concurrent calls stall each other.

---

## 5. Reference Syntax Cheat Sheet

Official docs: https://docs.cribl.io/search/packs/#dependencies

### Macros

| From → To | Syntax |
|---|---|
| Global → global Macro | `${macroId}` |
| Global → Pack Macro (needs global access) | `${pack(packId).macroId}` |
| Pack → global Macro | `${pack(cribl).macroId}` |
| Pack → same-Pack Macro | `${macroId}` |
| Pack → other Pack Macro | **Not allowed** |

### Lookups

| From → To | Syntax |
|---|---|
| Global → global lookup | `\| lookup lookupId on field` |
| Global → Pack lookup (needs global access) | `\| lookup pack(packId).lookupId on field` |
| Pack → global lookup | `\| lookup pack(cribl).lookupId on field` |
| Pack → same-Pack lookup | `\| lookup lookupId on field` |
| Pack → other Pack lookup | **Not allowed** |

### Saved searches

| From → To | Syntax |
|---|---|
| Global → global | `savedSearchId` |
| Global → Pack (needs global access) | `packId.savedSearchId` |
| Pack → global | `cribl.savedSearchId` |
| Pack → same Pack | `savedSearchId` |

### Datatypes

| From → To | Syntax |
|---|---|
| Global → global | `datatypeId` |
| Global → Pack (needs global access*) | `packId.datatypeId` |
| From within a Pack | **Not supported** |

\*v2 Datatypes in federated path filters resolve regardless of global access.

---

## 6. UI Workflows (Create / Modify / Share)

Path: **Products → Search → Packs**.

### Create

1. **Add Pack → Create Pack**
2. Set Display name, Pack ID, Version, Description, Author, Tags
3. Optionally check **Allow global access**
4. Add resources via Pack tabs (Dashboards / Saved Searches / Datatypes / Macros / Lookups) — or author files and import
5. Set logo under Pack Settings → Display

### Import

- **Add from Dispensary** — https://packs.cribl.io/
- **Import from File** — `.crbl`
- **Import from URL**
- **Import from Git** — public `https://<repo>` or private `https://<user>:<token>@<repo>`; optional branch/tag

On ID collision: assign a **New Pack ID** or **Overwrite** (backup first). Cribl blocks overwrite if local modifications would be destroyed.

### Upgrade

Recommended: import the new version under a temporary Pack ID + Display name including the version → side-by-side compare → copy back any user-modified lookups → then overwrite the production Pack ID when confident.

### Share / move / clone

| Action | Effect |
|---|---|
| Allow global access | Pack Settings → Pack Info → check **Allow global access** (or `exports: ["*"]`) |
| Move resource out of Pack | Actions → Move → All Dashboards (or global) |
| Move global into Pack | From global page → Actions → Move → Packs → \<pack\> (resets Created/Modified by; discards prior share Permissions) |
| Move between Packs | Actions → Move → Packs → target |
| Clone | Saved to current UI context (Pack vs global) |
| Export | Actions → Export → `.crbl` (filename defaults to `packId_version`) |

Cribl sample resources must be **cloned** before move.

External dependency warning on export: `This Pack has external dependencies` — document those globals in the README.

---

## 7. End-to-End Authoring Workflow

```
1. Decide Pack ID (cribl-search-… / cc-search-… / internal id)
2. Scaffold package.json + README.md + empty default/*.yml + data/{dashboards,lookups}/
3. Create dataset Macros first (one Macro per customer-editable dataset name)
4. Add Datatype(s) in breakers.yml if raw data needs parsing
5. Add lookups (enrichment / MITRE / code tables) — no sensitive data
6. Write saved searches that use pack(packId) Macro refs; test via MCP
7. Build dashboards (/cribl-dashboard-builder); embed tested queries / parent searches
8. Set exports: ["*"] if resources should be usable outside the Pack
9. Fill README Deployment + Release Notes
10. Package and validate import into a clean Workspace
```

### Package a `.crbl`

From the pack root (directory that contains `package.json`):

> **macOS `tar`/bsdtar silently corrupts `.crbl` archives** — always build with GNU tar (`gtar`), never the OS-default `tar`. The same gotcha applies to Stream Packs.

```bash
brew install gnu-tar   # provides `gtar` — once per machine
gtar -cvz --exclude .DS_Store --exclude .git --exclude '*.crbl' \
  -f ../<pack-id>_<version>.crbl \
  package.json README.md default data
```

Verify:

```bash
tar -tzf ../<pack-id>_<version>.crbl | head
# must show package.json, default/, data/ — no symlinks
```

Bump **all** of: `package.json` version, README Release Notes, archive filename.

---

## 8. Pack Limitations (do not fight these)

- Packs can't reference other Packs.
- Packs can't override system limits or system Usage Group limits (e.g. Results limit 50 000 unless Admin uses `set max_results_per_search`).
- No Notifications on Pack-resident saved searches.
- Can't create/update Pack lookups via `| export to lookup pack(packId).id`.
- Uninstalling a Pack that owns v2 Datatypes referenced by federated Dataset path filters breaks those searches.
- Encrypted fields are stripped on export — re-enter secrets after import.

---

## 9. Validation Checklist

Before shipping:

- [ ] `package.json` `name` == intended Pack ID; SemVer bumped
- [ ] `exports` set intentionally (`["*"]` vs Pack-scoped)
- [ ] Every Macro / saved search / dashboard query uses correct `pack(packId)` refs for **this** Pack ID
- [ ] Lookups: CSV + `.yml` pair; no secrets/PII
- [ ] Datatypes in `breakers.yml` tested against sample raw events
- [ ] Dashboards open and panels return data (MCP + UI)
- [ ] README Deployment matches real dataset / datatype / macro names
- [ ] Release Notes top version == `package.json` version
- [ ] Fresh-Workspace import succeeds; Pack ID collision strategy documented
- [ ] If Dispensary-bound: ID matches `cribl-search-…` / `cc-search-…`; checklist at packs-standards satisfied

---

## 10. Related Skills & Docs

| Need | Skill / doc |
|---|---|
| Dashboard JSON, charts, parent searches, API deploy | `/cribl-dashboard-builder` |
| Stream/Edge Packs (pipelines, routes) | `/cribl-stream-packs` |
| General Search / KQL questions | `/cribl-product-skills` |
| Official Search Packs docs | https://docs.cribl.io/search/packs |
| Dispensary publication standards (Search reqs) | https://docs.cribl.io/stream/packs-standards/ |
| Packs Dispensary | https://packs.cribl.io/ |
| GitHub collaboration (pre-Dispensary) | https://github.com/criblpacks |

Reference Pack example (Dispensary): **Search Palo Alto Networks Traffic Pack**. Internal reference layouts also exist in production Packs such as `cribl-search-windows-os` (macros + breakers Datatype + lookups + dashboards + saved queries).
