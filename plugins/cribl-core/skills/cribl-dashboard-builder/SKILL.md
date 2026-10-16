---
name: cribl-dashboard-builder
description: "Build, test, and deploy dashboards in Cribl Search, and migrate dashboards from Splunk, Sumo Logic, Kibana, and Grafana. Use when creating, updating, or migrating Cribl Search dashboards or panels."
argument-hint: "describe the dashboard to build, or paste a dashboard from Splunk/Sumo/Kibana/Grafana to migrate"
desktop: degraded
desktop-note: Authoring and migration work in chat; the deploy and test steps need the Cribl CLI and a shell.
---

# Cribl Dashboard Builder & Migrator

This skill enables Claude to build production-quality Cribl Search dashboards and to migrate dashboards into Cribl Search from other vendors. It has two parts:

- **Part A — Building** dashboards from scratch by:
  1. Using the **Cribl MCP server** to discover datasets, test queries, and validate field names
  2. Using the **Cribl REST API** (via bash/curl) to create and update dashboards programmatically
- **Part B — Migrating** dashboards from Splunk, Sumo Logic, Elastic/Kibana, and Grafana into valid Cribl Search dashboard JSON. Migration parses the source format and translates queries, then emits Cribl JSON using all the schema, chart, parent-search, and deployment patterns defined in Part A.

When migrating, always build the Cribl output using the schema and rules in **Part A** — the migration layer only handles source-format parsing and query translation; the Cribl output structure, parent search patterns, chart configs, and deployment steps live in Part A.

## Deployment Config

- **Workspace base URL**: Read from env var `$CRIBL_ORG_URL` (e.g. `https://main-acme.cribl.cloud`)
- **API base**: `$CRIBL_ORG_URL/api/v1`
- **Dashboard endpoint**: `$CRIBL_ORG_URL/api/v1/m/default_search/search/dashboards`
- **Search worker group**: `default_search`

## Prerequisites

The user must have:
- A **Cribl MCP server** connected in their Claude environment (provides `cribl_runSearchQuery`, `cribl_listDatasets`, etc.)
- **Cribl Cloud API credentials** stored as env vars `CRIBL_CLIENT_ID` and `CRIBL_CLIENT_SECRET` (export them in your shell, or set them in `~/.claude/settings.json` under `env`). If not set, ask the user before attempting deployment.
- For migration only: all source index/dataset names mapped to Cribl dataset names

---

# PART A — BUILDING DASHBOARDS

## Workflow Overview

```
1. Discover datasets (MCP: cribl_listDatasets)
2. Sample fields with catch-all queries (MCP: cribl_runSearchQuery)
3. Write and test each dashboard query (MCP: cribl_runSearchQuery)
4. Fix any query errors, re-test
5. Assemble dashboard JSON
6. Push to Cribl via REST API (bash: curl)
7. Verify deployment (bash: curl GET)
```

IMPORTANT: Always test every query via the MCP server BEFORE putting it into a dashboard. Never guess at field names — always confirm them from actual query results.

---

## Step 1: Authentication

### Cribl Cloud OAuth Token

Cribl Cloud uses OAuth2 client credentials. The token endpoint is always `https://login.cribl.cloud/oauth/token` regardless of workspace.

Credentials are read from env vars `$CRIBL_CLIENT_ID` and `$CRIBL_CLIENT_SECRET`. If these are empty or unset, ask the user to provide them before proceeding with deployment.

```bash
# Verify credentials are available
if [ -z "$CRIBL_CLIENT_ID" ] || [ -z "$CRIBL_CLIENT_SECRET" ]; then
  echo "ERROR: CRIBL_CLIENT_ID and CRIBL_CLIENT_SECRET must be set."
  echo "Export them in your shell, or set them in ~/.claude/settings.json under env."
  exit 1
fi

curl -s -X POST 'https://login.cribl.cloud/oauth/token' \
  --header 'Content-Type: application/x-www-form-urlencoded' \
  --data 'grant_type=client_credentials' \
  --data "client_id=$CRIBL_CLIENT_ID" \
  --data "client_secret=$CRIBL_CLIENT_SECRET" \
  --data 'audience=https://api.cribl.cloud'
```

Response:
```json
{
  "access_token": "eyJhbG...",
  "scope": "user:read:workergroups ...",
  "expires_in": 86400,
  "token_type": "Bearer"
}
```

The token is valid for 24 hours. Store it in a variable for subsequent API calls.

### On-Prem Deployments

For self-managed Cribl, use the local auth endpoint:
```bash
curl -s -X POST 'https://your-leader:9000/api/v1/auth/login' \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"yourpassword"}'
```

---

## Step 2: Discover Datasets and Fields

### List Available Datasets

Use the MCP tool:
```
cribl_listDatasets()
```

This returns all datasets with their provider, type (s3, api_http, cribl_lake, etc.), and configuration.

### Sample Fields Before Writing Queries

**CRITICAL RULE**: Before writing any query that filters or aggregates on a field, first run a catch-all query with a small limit to see what fields actually exist in the dataset. **Never guess field names** — even plausible-sounding names like `bytes_total` may not exist (the real field might be `bytes`).

Use `kqlQuery` so the dataset name and query survive verbatim:

```
cribl_runSearchQuery(
  kqlQuery='dataset="DATASET_NAME" | limit 5',
  earliest="-4h",
  latest="now"
)
```

Examine the returned fields carefully. Note:
- Nested fields use dot notation in queries (e.g., `hostinfo.hostname`, `asset.ipv4`)
- API datasets (type `api_http`) are NOT time-filtered the same way as S3 datasets. They return live data from the API endpoint.

### Common MCP Pitfalls

1. **Never run searches concurrently.** Issue exactly one `cribl_runSearchQuery` at a time and wait for it to return. The server serializes search jobs: if you batch two calls in a single message, the second blocks, both stall, and the tool call eventually times out with no result. The same queries run one after another each complete in well under a second. This looks exactly like a dead MCP server or a too-wide time range, and it is neither — do not restart the container and do not narrow the window in response. When you need several searches, chain them sequentially.

2. **Prefer `kqlQuery` over `naturalLanguagePrompt`.** `kqlQuery` runs your KQL verbatim with no NLP conversion. `naturalLanguagePrompt` sends the request through a KQL generator that may rewrite it — most often mangling the dataset name (generating `dataset=cribl_logs` instead of yours) or hijacking datasets whose names resemble built-ins like `metrics`. Use `kqlQuery` for anything you already know how to write, including saved-search definitions and copy-pasted queries. Reserve `naturalLanguagePrompt` for genuine exploration, and when you use it, check the returned `generatedQuery` before trusting the result.

3. **Zero results**: If a query returns 0 results, check:
   - Is `executedQuery` in the response what you intended?
   - Is the time range appropriate? Try `-4h` or `-24h`.
   - Does the field name actually exist? Run the catch-all query first.
   - A fast, genuinely empty result is meaningful: a completed job with `totalEventCount: 0` means the data is not there, not that the query failed.

4. **Quoting**: The MCP sometimes uses single quotes, sometimes double. Both work in Cribl KQL. Note that `kqlQuery` values usually contain double-quoted dataset names, so wrap the argument in single quotes.

5. **Relative times only**: `earliest`/`latest` must be relative expressions (`-1h`, `-24h`, `-7d`, `now`). ISO 8601 and date-only strings are rejected by the API.

---

## Step 3: Write and Test Queries

### Cribl Search KQL Syntax Reference

**Filtering:**
```
dataset="my_dataset"
| where field == "value"
| where field > 100
| where state == "open" or state == "reopened"    // Use 'or', NOT '||'
```

**IMPORTANT**: Use the keyword `or` for logical OR. Do NOT use `||` — Cribl's parser interprets `||` as a pipe operator and the query will fail.

**Bare keyword search** — put a bare term right after the dataset selector to filter on raw text. This is the shortest way to hunt for an event in a log dataset, and it is pushed down rather than evaluated per-event:
```
dataset="my_dataset" ingest.ok | limit 1000
dataset="my_dataset" victron | limit 1000
```
Reach for this first when looking for a known string; move to `| where` once you need to compare parsed fields.

**Regex matching**: `| where field matches /pattern/` is rejected by the parser (`no viable alternative at input`). Use a bare keyword term, `| where field == "value"`, or verify the current regex operator in the docs before relying on it.

**Aggregation:**
```
| summarize count() by field
| summarize total=sum(bytes), avg_val=avg(duration) by source
| summarize count() by field1, field2
```

**Top-hitters (fast frequency count):**
```
| top-hitters 15 of source_ip
| top-hitters 25 of app
```
Returns a `count` field alongside the grouped field.

**Dedup and count by field (for maps):**
```
| summarize by country
```

**Time series:**
```
| timestats span=5m count() by severity
| timestats span=1h count=count() by action
| timestats span=8h bytes=sum(bytes)
```

**Projection and sorting:**
```
| project field1, field2, field3
| sort by count_ desc
| limit 20
```

**Extending (computed fields):**
```
| extend label=iif(isnotnull(field), "Yes", "No")
| extend proto=iif(protocol=="6","TCP",iif(protocol=="17","UDP","OTHER"))
```

**Conditional aggregation:**
```
| summarize failures=countif(action=="deny"), allows=countif(action=="allow")
```

**IP Geolocation Lookup (MaxMind MMDB):**
```
| ip-lookup 'GeoLite2-City' on source_ip
```
Use **single quotes** around the lookup file name. Returns these fields:
`country`, `country_code`, `city`, `region`, `region_code`, `continent`,
`continent_code`, `lat`, `lon`, `time_zone`, `postal`

Filter out unresolved IPs with `| where isnotnull(country)` after the lookup.

**Joins Between Datasets:**
Joins work between **API datasets** (api_http type). They do NOT work when either side is an S3 (v2) dataset.

```
dataset="api_dataset_1"
| join kind=inner (dataset="api_dataset_2" | project key, field1) on $left.joinkey == $right.key
```
Only `kind=inner` is supported.

### JSON Fields and Nested Objects (READ THIS before renaming nested fields)

**Extract with an explicit source:** `| extract source=_raw type=json` — NOT bare `| extract type=json`. Both default to `_raw`, but the explicit form is unambiguous and avoids confusion.

**`project-rename` and `extend` do NOT work on a field name that contains a dot.** Cribl parses `A.B` as nested access into an object `A`, so:
```
| project-rename Processname = EnvironmentData.ProcessName     // ❌ silently empty
| extend Processname = EnvironmentData.ProcessName             // ❌ silently empty
```
fail to populate the field whenever the source is a flattened/nested JSON path (`EnvironmentData.ProcessName`, `LogLevel.LogLevel`, `kubernetes.namespace_name`, `ErrorDetail.Code`, …). **This is the #1 migration mistake — do not emit `project-rename`/`extend` against dotted names.**

Two patterns that DO work for nested values:

**A — `extract_json` on a JSON string (robust default):**
```
| extend json_field = extract(@"...regex...", 1, log)   // json_field stays a STRING (α) — correct
| extend Processname = extract_json("$.EnvironmentData.ProcessName", json_field)
| extend Namespace   = extract_json("$.kubernetes.namespace_name", _raw)
```
`extract_json("$.path", <json-string>)` parses the string and pulls the path.

**B — `parse_json` then dot-access (cleaner, makes a real `{}` object):**
```
| extend json_field = parse_json(extract(@"...regex...", 1, log))   // json_field is an OBJECT {}
| extend Processname = tostring(json_field.EnvironmentData.ProcessName)
| extend Namespace   = tostring(parse_json(_raw).kubernetes.namespace_name)
```
`parse_json` turns the string into a dynamic object; dot-access + `tostring()` reads nested values. Both A and B run server-side — pick one style per dashboard.

**Dot-access only off a FIELD, never off a function call.** `tostring(parse_json(_raw).kubernetes.namespace_name)` is a **Cribl parse error** ("mismatched input '('"). Assign the parsed value to a field first, then dot-access the field:
```
| extend __raw = parse_json(_raw)
| extend Namespace = tostring(__raw.kubernetes.namespace_name)
```
`tostring(__json_field.EnvironmentData.X)` works because `__json_field` is a field. One bad function-call dot-access fails the whole search, so every parent-backed input/panel that depends on it silently falls back to its seed ("ALL").

**Do the extract ONCE in the parent.** Put the scan + JSON extract (and `parse_json`) in the hidden parent search; child panels reference the cached result and add only the per-field extends THEY use, placed AFTER their filters so the re-parse runs on the narrowed row set. A panel that summarizes by an already-flat field (e.g. `Application`) needs zero extracts.

**Query-backed input option tails:** end each input's option query with
`| summarize count() by Field | where isnotnull(Field) | project Field`
so the dropdown lists clean, deduped, non-null values.

**Wildcard equality:** a `*`/All selection in `| where Field == "$token$"` resolves to `Field == "*"`, which Cribl matches as the literal string `"*"` (→ no rows). For Splunk-converted dashboards where `*` means "match anything," rewrite `== "*"` to a no-op (`true`) or use `Field in ($token$)` (which expands `*` → `true`).

### Dataset Engine Types

Understanding the engine matters for framing:
- **Cribl Lakehouse Engine** (e.g. `criblcoffee_pan`): ClickHouse columnar tables with a write-through caching tier. S3-backed storage but NOT S3 scans — queries run at ClickHouse speed.
- **Federated V2** (e.g. `criblcoffee_historical_pan_traffic`): Federated queries to S3 using the V2 dataset format.
- **Federated V1** (e.g. `criblcoffee_historical_pan_traffic_v1`): Federated queries to S3 using the original V1 dataset/datatype. Slowest.

When discussing parent search performance benefits, use "Lakehouse Engine queries" not "S3 scans" for Lakehouse datasets.

---

## Step 4: Dashboard JSON Structure

### Actual Dashboard Export Structure

The correct top-level structure for creating a dashboard via the API is:

```json
{
  "id": "my_dashboard_id",
  "schedule": {
    "enabled": false,
    "cronSchedule": "0 0 * * *",
    "tz": "UTC",
    "keepLastN": 2
  },
  "groups": {},
  "name": "My Dashboard Name",
  "elements": [ ... ]
}
```

**Key points:**
- A top-level `id` is **required** by the API for creating dashboards
- `id` must match `^[a-zA-Z0-9_]+$` (letters, digits, and underscores ONLY — no hyphens, no spaces)
- Exported dashboards may omit `id` (the API adds it), but POSTs require it
- `schedule`, `groups`, and `name` are all inside the top-level object alongside `elements`
- `groups` is always `{}`

**Naming constraints:**
- Dashboard `id`: Must match `^[a-zA-Z0-9_]+$` (no hyphens, no spaces, no special chars)
- Dashboard `name`: Must match `^[a-zA-Z0-9 _-]+$` (no ampersands, no special chars)

### Input Elements

#### Time Range Input
```json
{
  "id": "time_input",
  "inputId": "TIME",
  "type": "input.timerange",
  "variant": "input",
  "title": "Time Range",
  "layout": { "x": 0, "y": 0, "w": 3, "h": 2 },
  "config": {
    "defaultValue": {
      "earliest": "-24h",
      "latest": "now",
      "timezone": "local"
    }
  }
}
```

**Important rules:**
- `variant: "input"` is required
- `inputId` is typically uppercase: `"TIME"`, not `"time_range"`
- Time tokens reference `inputId`: `$TIME.earliest$`, `$TIME.latest$`, `$TIME.timezone$`
- Valid relative time: `-1h`, `-24h`, `-8d@d`. **Invalid**: `-1h@h` (same unit snap is not allowed). Use `-1h@d` to snap to day, or just `-1h` with no snap.

#### Dynamic Dropdown (populated from search)
```json
{
  "id": "input_action",
  "inputId": "action_filter",
  "type": "input.dropdown",
  "variant": "input",
  "title": "Action",
  "layout": { "x": 4, "y": 0, "w": 4, "h": 2 },
  "config": {
    "defaultValue": "*",
    "field": "action"
  },
  "search": {
    "type": "inline",
    "query": "dataset=\"my_dataset\" | summarize by action",
    "earliest": "$TIME.earliest$",
    "latest": "$TIME.latest$",
    "timezone": "$TIME.timezone$"
  }
}
```

**IMPORTANT**: Use `input.dropdown` (NOT `input.select`). The dropdown type dynamically populates from the search result. `input.select` with static options does NOT work correctly.

#### Free Text Filter
```json
{
  "id": "input_srcaddr",
  "inputId": "srcaddr_filter",
  "type": "input.text",
  "variant": "input",
  "title": "Source IP (or *)",
  "layout": { "x": 8, "y": 0, "w": 4, "h": 2 },
  "config": { "defaultValue": "*" }
}
```

Apply text filter tokens in queries with short-circuit logic:
```
| where "$srcaddr_filter$" == "*" or source_ip == "$srcaddr_filter$"
```

### Visualization Panels

#### Standard Panel (independent search)
```json
{
  "id": "my_chart",
  "title": "My Chart Title",
  "type": "chart.column",
  "layout": { "x": 0, "y": 3, "w": 6, "h": 4 },
  "search": {
    "type": "inline",
    "query": "dataset=\"my_dataset\"\n| summarize count() by field",
    "earliest": "$TIME.earliest$",
    "latest": "$TIME.latest$",
    "timezone": "$TIME.timezone$"
  },
  "config": {
    "colorPalette": 0,
    "axis": {}
  }
}
```

**Rules for all chart panels:**
- `axis: {}` is required on every chart element
- `colorPalette` (integer) should be set on every chart
- `title` is required on visualization panels

#### Markdown Section Header
```json
{
  "id": "hdr_section",
  "type": "markdown.default",
  "variant": "markdown",
  "layout": { "x": 0, "y": 2, "w": 12, "h": 1 },
  "config": { "markdown": "## Section Title" }
}
```

`variant: "markdown"` is required on markdown elements.

### Parent Search Pattern

Use parent searches when multiple panels query the same dataset. The parent runs once; all child panels post-process its results from memory — dramatically reducing query count against the engine.

#### MANDATORY: Auto-detect parent-search opportunities during migration

When converting a dashboard from any source format (Splunk SimpleXML, Sumo, Kibana, Grafana, …), the very first pass after parsing the source XML/JSON MUST scan the queries for shared prefixes and refactor them into parents. **Do not emit a "1 panel : 1 query" Cribl dashboard if any base filter is duplicated.** Skipping this step burns customer cores and produces dashboards that fall over on large datasets.

Algorithm:

1. **Group queries by shared prefix.** Two queries belong in the same group if they:
   - reference the same dataset (`dataset="x"` or `index=x`)
   - apply the same dataset-level filters (sourcetype, source, host, base regex, the "find these records" phase)
   - apply the same shared transforms (`rex`/`extract`, `eval`/`extend`, `dedup`, basic shape-rewriting)
2. **For every group with ≥2 panels, build a parent.** The parent's query is the common prefix; its `| project` keeps only the columns at least one child needs.
3. **Promote computed fields to the parent.** If 5 panels each have `| extend tier = case(...)`, that `case` belongs in the parent — children just filter on `tier`.
4. **Children become minimal post-processors:** `| where`, `| summarize`, `| project`, `| sort`, `| limit`. A child whose query still contains the dataset name, the base sourcetype filter, or a repeated rex hasn't been refactored — go back and lift it.
5. **Pick the longest time window for the parent.** If children need 7d / 30d / 60d windows, the parent's `timeOverride` covers the 60d span; the 7d/30d children filter further with their own `timeOverride` or an inline `| where _time >= ago(Nd)`.

Concrete pattern signatures that ALWAYS yield a parent:

| Signature | Example |
|-----------|---------|
| **Same dataset, same sourcetype, same base contains/regex, different `where tier`** | 8 JVM-restart KPI panels filtering UI / MIF / CRN / RPT |
| **Same dataset, identical rex/extract pipeline, different aggregations** | SQL exec-time pie + column + queries-over-30s panels |
| **Same dataset, identical extract + eval pipeline, different `where host`** | Per-host heap-usage line charts (one per server) |
| **Multiple KPIs with the same base search but different time windows** | "Restarts in 7d" / "Restarts in 30d" / "Restarts in 60d" — one parent at 60d, three children filtering by time |

Rule of thumb: if you'd write the same SPL/KQL prefix twice, write a parent instead. A converted dashboard with N panels should typically have somewhere between 1 and 5 parent searches, not N independent fetches.

When discussing optimization with the user, quantify the win: "25 panels → 4 backing searches, ~6× fewer cores per dashboard refresh."

#### Parent Element
```json
{
  "id": "parent_traffic",
  "type": "list.events",
  "title": "Base Traffic Search",
  "hidePanel": true,
  "layout": { "x": 0, "y": 2, "w": 4, "h": 2 },
  "search": {
    "type": "inline",
    "query": "dataset=\"my_dataset\"\n| project _time, field1, field2, field3",
    "earliest": "$TIME.earliest$",
    "latest": "$TIME.latest$",
    "timezone": "$TIME.timezone$"
  },
  "config": {}
}
```

**Rules:**
- `"hidePanel": true` hides it from the rendered dashboard
- `type` must be `"list.events"`
- `title` is required even though the panel is hidden
- Parent uses `$TIME.*$` tokens like any other panel
- Parent can appear **anywhere** in the `elements` array — order does not matter
- Use `| project` in the parent to fetch only the fields child panels need
- Multiple parents are allowed — each feeds a different set of child panels

#### Child Panel
```json
{
  "id": "chart_action",
  "title": "Traffic by Action",
  "type": "chart.pie",
  "layout": { "x": 0, "y": 3, "w": 4, "h": 4 },
  "parentSearchId": "parent_traffic",
  "search": {
    "type": "inline",
    "query": "| summarize count() by action",
    "earliest": 0,
    "latest": "now",
    "parentSearchId": "parent_traffic"
  },
  "config": {
    "colorPalette": 3,
    "axis": {}
  }
}
```

**CRITICAL RULES for child panels:**
- `"parentSearchId"` must appear at **BOTH** the top-level element AND inside the `search` block
- Child query starts with `|` — no `dataset=` prefix
- Child `earliest` is `0` (integer), `latest` is `"now"` (string) — NO time tokens
- Child queries post-process the parent's already-fetched results

#### Two-Parent Example Pattern
```
parent_traffic  → pie_action, area_traffic, line_bytes, hbar_src, hbar_dst, col_apps, col_ports
parent_geo      → map_world, hbar_countries, hbar_country_bytes, pie_continent, col_cities, table_recent
```

Parent 1 fetches raw traffic fields. Parent 2 fetches the same data plus geo enrichment:
```
dataset="my_dataset"
| ip-lookup 'GeoLite2-City' on source_ip
| project _time, action, source_ip, ..., country, city, lat, lon, ...
```

### Chart Types Reference

| Type | Use For | Notes |
|------|---------|-------|
| `chart.column` | Bar charts, time series with categories | Default for most aggregations |
| `chart.horizontalBar` | Ranked lists, long category names | Good for top-N IPs, countries |
| `chart.pie` | Distribution/proportion of a single dimension | |
| `chart.line` | Continuous time series, trends | |
| `chart.area` | Stacked time series | Use with `customData.stack: true` |
| `chart.map` | Geographic choropleth | Requires `country` field and special config |
| `list.table` | Detailed data tables, drill-down | |
| `list.events` | Parent search container (hidden) | Always `hidePanel: true` |
| `markdown.default` | Section headers, descriptions | Always `variant: "markdown"` |

### Choropleth Map Panel

```json
{
  "id": "map_world",
  "title": "Traffic by Country",
  "type": "chart.map",
  "layout": { "x": 0, "y": 11, "w": 12, "h": 4 },
  "parentSearchId": "parent_geo",
  "search": {
    "type": "inline",
    "query": "| where isnotnull(country)\n| summarize by country",
    "earliest": 0,
    "latest": "now",
    "parentSearchId": "parent_geo"
  },
  "config": {
    "separator": true,
    "shouldApplyUserChartSettings": false,
    "mapDetails": {
      "mapSourceID": "World",
      "mapType": "Choropleth",
      "pointScale": 10
    },
    "legend": { "truncate": true }
  }
}
```

The map query must produce a `country` field. Use `| summarize by country` (not `summarize count() by country` — the map widget handles the counting internally).

### Marker Map Panel (Geo mode)

For lat/lon point data (GPS tracks, asset locations, incident sites), use `chart.map` in **Geo mode** — this replaces the "choropleth-only" impression left by the older docs. The query must project `Name`, `Latitude`, `Longitude`, plus a numeric channel that scales marker size.

```json
{
  "id": "map_route",
  "title": "Device Locations",
  "type": "chart.map",
  "layout": { "x": 0, "y": 12, "w": 12, "h": 6 },
  "parentSearchId": "parent_traffic",
  "search": {
    "type": "inline",
    "query": "| where isnotnull(latitude) and isnotnull(longitude)\n| extend Name = user, Latitude = latitude, Longitude = longitude\n| project Name, Latitude, Longitude, totalMins",
    "earliest": 0,
    "latest": "now",
    "parentSearchId": "parent_traffic"
  },
  "config": {
    "mapDetails": { "mapType": "Geo", "pointScale": 10 },
    "legend": { "truncate": true }
  }
}
```

**Not supported in either map mode:** connecting path lines between markers, HTML popups, per-marker color/icon override, clustering, heatmap overlay, custom tile URLs. For path-line visualizations (attack flows, GPS breadcrumbs with connections) use a Viz-Lab `geo-attack-flows` widget instead (see Part C).

### Panel Interactions (drilldown)

Cribl dashboards support click-to-act interactions on `list.table` and most chart panels. **Not supported on `chart.map` or gauge panels.** Add interactions at the element level, not inside `search`:

```json
{
  "id": "table_users",
  "title": "User Search Results",
  "type": "list.table",
  "layout": { "x": 0, "y": 5, "w": 12, "h": 5 },
  "search": { "...": "..." },
  "config": { "axis": {} },
  "interactions": [
    {
      "type": "addValueToInput",
      "trigger": "click",
      "targetDashboardId": "this_dashboard",
      "targetInputId": "d_name_filter",
      "value": "$rowData.d_name$"
    }
  ]
}
```

Three interaction types:
- `runSearch` — open a new search with a KQL query, referencing `$value$`, `$rowData.field$`, `$earliest$`, `$latest$`.
- `openLink` — open an external URL, same token substitutions available.
- `addValueToInput` — populate an input (this dashboard or another). Direct analog to Splunk's `<drilldown><set token>`.

Available tokens inside interaction fields:
- `$value$` — clicked cell's value
- `$field.name$` — clicked column name
- `$field.value$` — same as `$value$`
- `$rowData.<column>$` — any other column in the clicked row
- `$earliest$`, `$latest$` — panel's current time range
- `$environment.*$` — workspace metadata

Caveat: if the panel has its own time picker, either wire the interaction to a Time Range Input directly or omit time propagation — mismatched time state breaks the interaction at runtime.

### What Cribl dashboards do NOT support

Do not fabricate schema fields for these — the API silently accepts unknown properties and the element renders anyway, hiding the bug:

- **Multiselect input** — no `input.multiselect`. Only single-value Dropdown.
- **Checkbox / toggle input** — no `input.checkbox`. Simulate with a two-option Dropdown or a Text input.
- **Panel visibility gating** (`depends`, `rejects`, `visibleWhen`, `hidePanel` for anything other than `list.events` parent searches) — no reactive show/hide tied to input state. Emit the panel unconditionally; let its query return zero rows when the input is empty.
- **Reactive tokens** — no `<change>` / `<condition>` / `<set token>` / `<unset token>` event bus. Fold derived state into queries.
- **Chart brush / drag-select** — Interactions fire on single-point click only.
- **Forward or reverse geocoder** — no address↔lat/lon operator in KQL. Only `ip-lookup` for IP-to-geo. Workarounds: an `api_http` dataset pointed at Bing/Google Geocoding joined at query time, or a Stream pipeline that enriches events at ingest.
- **Data models** — no `from datamodel:` operator; substitute the underlying dataset plus the model's constraint filters.
- **Custom JS / CSS / inline HTML** — no `script=`, `stylesheet=`, or `<html>` blocks. Any interactivity beyond the four inputs and three interaction actions requires Viz-Lab.
- **Path lines on maps, HTML popups, marker clustering, heatmap overlays** — see Viz-Lab (Part C) for `geo-attack-flows` and related security-specific vizs.
- **Arbitrary job-SID references** — `parentSearchId` is intra-dashboard only; there is no `loadjob <any-sid>` equivalent for referencing external running jobs.

### Chart Config Options

**Color palette** (integer, 0-12+):
```json
"config": { "colorPalette": 4 }
```

**Per-series color override** — key must match the exact field name returned by the query:
```json
"config": {
  "seriesInfo": {
    "bytes": { "color": "#0077b6" },
    "count": { "color": "#60ba17" }
  }
}
```

Note: `top-hitters` returns a field named `count`. `summarize count() by field` returns `count_` (with underscore).

**Stacked area chart:**
```json
"config": {
  "colorPalette": 1,
  "axis": {},
  "customData": {
    "stack": true,
    "trellis": false,
    "seriesCount": 4
  }
}
```

`seriesCount` should match the number of distinct series values expected.

**Full config example:**
```json
"config": {
  "colorPalette": 0,
  "axis": {},
  "seriesInfo": {
    "count": { "color": "#cc4700" }
  },
  "customData": {
    "stack": false,
    "trellis": false
  }
}
```

### Layout Grid

The dashboard uses a 12-column grid:
- `x`: Column position (0-11)
- `y`: Row position (increments downward)
- `w`: Width in columns (1-12)
- `h`: Height in rows

**Input elements float above the grid** — chart panels can start at the same `y` as input elements without collision.

Common width patterns:
- Full width: `w: 12`
- Two columns: `w: 6` / `w: 6`
- Three columns: `w: 4` / `w: 4` / `w: 4`
- Three uneven: `w: 3` / `w: 5` / `w: 4`

### Linking Panels to Time Range

All standalone visualization panels reference the time range input:
```json
"earliest": "$TIME.earliest$",
"latest": "$TIME.latest$",
"timezone": "$TIME.timezone$"
```

The variable name (`TIME`) must match the `inputId` of the time range element. Child panels of a parent search use `"earliest": 0, "latest": "now"` instead.

---

## Step 5: Push to Cribl via REST API

### API Base URL

```bash
BASE="$CRIBL_ORG_URL/api/v1"  # replace with your org URL
```

Dashboard endpoint:
```
$BASE/m/default_search/search/dashboards
```

### Create a Dashboard

```bash
curl -s -X POST "$BASE/m/default_search/search/dashboards" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @/tmp/dashboard.json
```

### Update a Dashboard (PATCH)

```bash
curl -s -X PATCH "$BASE/m/default_search/search/dashboards/MY_DASHBOARD_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @/tmp/dashboard.json
```

### Idempotent Create-or-Update Pattern

```bash
HTTP=$(curl -s -o /tmp/resp.json -w "%{http_code}" -X POST "$BASE/m/default_search/search/dashboards" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @/tmp/dashboard.json)

if [ "$HTTP" = "400" ]; then
  curl -s -X PATCH "$BASE/m/default_search/search/dashboards/$DASHBOARD_ID" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d @/tmp/dashboard.json
fi
```

---

## Step 6: Common Patterns and Recipes

### Python Dashboard Builder Template

```python
import json

DATASET = 'dataset="my_dataset"'
INPUT_ID = "TIME"

def parent_search(query):
    return {
        "type": "inline",
        "query": query,
        "earliest": f"${INPUT_ID}.earliest$",
        "latest":   f"${INPUT_ID}.latest$",
        "timezone": f"${INPUT_ID}.timezone$"
    }

def child(query, parent_id):
    return {
        "type": "inline",
        "query": query,
        "earliest": 0,
        "latest": "now",
        "parentSearchId": parent_id
    }

def standalone(query):
    return {
        "type": "inline",
        "query": query,
        "earliest": f"${INPUT_ID}.earliest$",
        "latest":   f"${INPUT_ID}.latest$",
        "timezone": f"${INPUT_ID}.timezone$"
    }

def vis(id_, title, type_, x, y, w, h, query, parent_id, cfg):
    return {
        "id": id_, "title": title, "type": type_,
        "layout": {"x": x, "y": y, "w": w, "h": h},
        "parentSearchId": parent_id,
        "search": child(query, parent_id),
        "config": cfg
    }

def hdr(id_, y, text):
    return {
        "id": id_, "type": "markdown.default", "variant": "markdown",
        "layout": {"x": 0, "y": y, "w": 12, "h": 1},
        "config": {"markdown": f"## {text}"}
    }

def std(palette=0, series_info=None, custom=None):
    cfg = {"colorPalette": palette, "axis": {}}
    if series_info: cfg["seriesInfo"] = series_info
    if custom:      cfg["customData"] = custom
    return cfg

PARENT_ID = "parent_main"
elements = []

# Time input
elements.append({
    "id": "time_input", "inputId": INPUT_ID,
    "type": "input.timerange", "variant": "input",
    "title": "Time Range",
    "layout": {"x": 0, "y": 0, "w": 3, "h": 2},
    "config": {"defaultValue": {"earliest": "-24h", "latest": "now", "timezone": "local"}}
})

# Hidden parent
elements.append({
    "id": PARENT_ID, "type": "list.events",
    "title": "Base Search", "hidePanel": True,
    "layout": {"x": 0, "y": 2, "w": 4, "h": 2},
    "search": parent_search(f'{DATASET}\n| project _time, field1, field2, field3'),
    "config": {}
})

# Section + panels
elements.append(hdr("hdr_s1", 2, "📊 Overview"))
elements.append(vis(
    "pie_field1", "Field1 Distribution", "chart.pie",
    0, 3, 4, 4,
    "| summarize count() by field1",
    PARENT_ID, std(palette=3)
))

dashboard = {
    "id": "my_dashboard",
    "schedule": {"enabled": False, "cronSchedule": "0 0 * * *", "tz": "UTC", "keepLastN": 2},
    "groups": {},
    "name": "My Dashboard",
    "elements": elements
}

with open("/tmp/dashboard.json", "w") as f:
    json.dump(dashboard, f, indent=2)
```

### Geo-Enriched Dashboard Pattern

Two parents — one base, one geo-enriched:

```python
# Parent 1: raw traffic
{
    "id": "parent_traffic", "type": "list.events",
    "title": "Base Traffic", "hidePanel": True,
    "search": parent_search(
        'dataset="my_dataset"\n'
        '| project _time, action, source_ip, dest_ip, dest_port, app, bytes'
    )
}

# Parent 2: geo-enriched
{
    "id": "parent_geo", "type": "list.events",
    "title": "Geo-Enriched Traffic", "hidePanel": True,
    "search": parent_search(
        'dataset="my_dataset"\n'
        "| ip-lookup 'GeoLite2-City' on source_ip\n"
        '| project _time, action, source_ip, dest_ip, app, bytes,\n'
        '  country, country_code, city, region, continent, continent_code,\n'
        '  lat, lon, time_zone, postal'
    )
}
```

### Performance Comparison Dashboard (multiple datasets, same queries)

```python
DATASETS = [
    {"key": "lakehouse", "dataset": "criblcoffee_pan",                       "label": "🟢 Lakehouse Engine", "palette": 7, "color": "#60ba17", "x": 0},
    {"key": "v2",        "dataset": "criblcoffee_historical_pan_traffic",    "label": "🟡 V2 Federated S3",  "palette": 2, "color": "#ff9500", "x": 4},
    {"key": "v1",        "dataset": "criblcoffee_historical_pan_traffic_v1", "label": "🔴 V1 Federated S3",  "palette": 3, "color": "#cc4700", "x": 8},
]

# For each round, run the same query against all three datasets side by side
for ds in DATASETS:
    elements.append(chart(
        f"col_src_{ds['key']}",
        f"{ds['label']} — Top 25 Source IPs",
        "chart.column",
        ds["x"], y, 4, 4,
        f'dataset="{ds["dataset"]}" | top-hitters 25 of source_ip',
        ds["palette"],
        series_info={"count": {"color": ds["color"]}}
    ))
```

---

## Troubleshooting

### Common Errors and Fixes

| Error | Cause | Fix |
|---|---|---|
| `mismatched input '\|'` | Used `\|\|` for logical OR | Replace with `or` |
| `Illegal return statement` | `return __e` at module scope in Code function | Remove top-level `return`; just mutate `__e` directly |
| `Invalid relative time expression` | Used same unit for offset and snap e.g. `-1h@h` | Use `-1h` or snap to different unit: `-1h@d` |
| `Cannot read properties of undefined (reading 'name')` | `metadata.tags` are strings not objects | Not applicable to dashboards; for pipelines, tags must be `[{"name": "..."}]` |
| `should have required property 'queryId'` | `list.events` element missing required fields | Ensure `title` is present and search block is correct |
| Panels show wrong data | `parentSearchId` only set at top level | Set `parentSearchId` inside the `search` block too |
| Child panels not updating with time picker | Child using `$TIME.*$` tokens | Child panels must use `"earliest": 0, "latest": "now"` — no time tokens |
| Dropdown not populating | Used `input.select` | Use `input.dropdown` with `field` and `search` block |
| Map not rendering | Query produces wrong shape | Map needs `country` field; use `\| summarize by country` |
| `ip-lookup` returns no geo fields | Wrong quote style | Use **single quotes**: `ip-lookup 'GeoLite2-City' on field` |
| `should have required property 'id'` | Missing top-level `id` in dashboard JSON | Add `"id": "my_dashboard_name"` — required for API POST |
| `should match pattern "^[a-zA-Z0-9_]+$"` on `/id` | Dashboard `id` contains hyphens, spaces, or special chars | Use only letters, digits, and underscores in `id` |

### MCP Query Generation Issues

- **Searches wrong dataset**: Use exact phrasing: "Search the EXACT_DATASET_NAME dataset"
- **Adds unwanted filters**: Say "return 5 events no filters"
- **Check `generatedQuery`**: Always verify what the MCP actually ran vs. what you intended
- **Custom dataset names hijacked**: If dataset name resembles a built-in (e.g. `metrics`), the MCP may redirect to `cribl_metrics`. Build the dashboard without MCP validation for those panels and note the risk.

---

# PART B — MIGRATING FROM OTHER VENDORS

Converts dashboards from Splunk, Sumo Logic, Elastic/Kibana, and Grafana into valid Cribl Search dashboard JSON. This part only covers the source-format parsing and query translation layers. The Cribl output schema, parent search patterns, chart configs, and deployment steps are all in **Part A** above — emit all Cribl JSON using those rules.

## Migration Workflow

```
1. IDENTIFY   → Detect the source vendor and format version
2. PARSE      → Extract panels, queries, viz types, inputs, layout
3. TRANSLATE  → Convert queries to Cribl KQL
4. MAP        → Map viz types and input types to Cribl equivalents
5. GROUP      → Infer parent searches from shared base queries
6. EMIT       → Generate valid Cribl dashboard JSON (see Part A)
7. FLAG       → Document every panel that couldn't be fully translated
```

### Step 3 fallback: translate by hand, then verify

For complex queries that don't pattern-match cleanly (multi-line logic, `eval` chains, `parse regex`, `transaction`, subqueries), translate them by hand against the [Cribl Search KQL reference](https://docs.cribl.io/search/) and prove the result before emitting it:

1. Write the KQL, keeping one source command per line in a comment above it so the mapping stays reviewable.
2. Run it with `cribl_runSearchQuery(kqlQuery='…', earliest="-24h", latest="now")` and compare row counts and field names with the source dashboard's output for the same window.
3. If the source has no direct KQL equivalent, prefer pushing the work into a Stream pipeline (parse/extract at ingest) over an approximate query.

If a query still cannot be translated faithfully, emit the original as a comment and flag it:
```json
{
  "query": "// MIGRATION TODO: translate from SPL\n// index=security sourcetype=pan:traffic | stats count by src_ip\n| summarize count() by src_ip"
}
```

---

## Vendor 1: Splunk

### Format Detection

Splunk has two dashboard formats:

**SimpleXML** — legacy XML format, file extension `.xml`, starts with `<dashboard>` or `<form>`. Used in Classic Dashboards.

**Dashboard Studio** — JSON format, has top-level `"visualizations"`, `"dataSources"`, `"layout"` keys.

### Splunk SimpleXML Parser

Key elements to extract:

```xml
<dashboard>
  <label>Dashboard Title</label>
  <row>
    <panel>
      <title>Panel Title</title>
      <chart>                          <!-- or <table>, <single>, <map>, <event> -->
        <search>
          <query>index=firewall | stats count by src_ip</query>
          <earliest>-24h</earliest>
          <latest>now</latest>
        </search>
        <option name="charting.chart">bar</option>   <!-- viz type hint -->
      </chart>
    </panel>
  </row>
  <fieldset>
    <input type="time" token="time_tok">
      <label>Time Range</label>
      <default><earliest>-24h</earliest><latest>now</latest></default>
    </input>
    <input type="dropdown" token="env_tok">
      <label>Environment</label>
      <choice value="*">All</choice>
      <choice value="prod">Production</choice>
    </input>
  </fieldset>
</dashboard>
```

**Python parser:**
```python
import xml.etree.ElementTree as ET

def parse_splunk_xml(xml_str):
    root = ET.fromstring(xml_str)
    ns = ""  # SimpleXML has no namespace

    panels = []
    for row_i, row in enumerate(root.findall("row")):
        for col_i, panel in enumerate(row.findall("panel")):
            title = panel.findtext("title", "")
            for viz_tag in ["chart", "table", "single", "map", "event", "list"]:
                viz = panel.find(viz_tag)
                if viz is not None:
                    search = viz.find("search")
                    query  = search.findtext("query", "") if search else ""
                    earliest = search.findtext("earliest", "-24h") if search else "-24h"
                    latest   = search.findtext("latest", "now")    if search else "now"
                    chart_type = viz.find("option[@name='charting.chart']")
                    panels.append({
                        "title": title,
                        "source_viz": viz_tag,
                        "chart_type": chart_type.text if chart_type is not None else "column",
                        "query": query.strip(),
                        "earliest": earliest,
                        "latest": latest,
                        "row": row_i,
                        "col": col_i,
                    })

    inputs = []
    fieldset = root.find("fieldset")
    if fieldset:
        for inp in fieldset.findall("input"):
            inputs.append({
                "type": inp.get("type"),
                "token": inp.get("token"),
                "label": inp.findtext("label", ""),
                "choices": [c.get("value") for c in inp.findall("choice")],
                "default_earliest": inp.findtext("default/earliest"),
                "default_latest":   inp.findtext("default/latest"),
            })

    return {
        "title": root.findtext("label", "Migrated Dashboard"),
        "panels": panels,
        "inputs": inputs,
    }
```

### Splunk Dashboard Studio Parser

```python
import json

def parse_splunk_studio(json_str):
    d = json.loads(json_str)
    panels = []

    for viz_id, viz in d.get("visualizations", {}).items():
        ds_id  = viz.get("dataSources", {}).get("primary", "")
        ds     = d.get("dataSources", {}).get(ds_id, {})
        query  = ds.get("options", {}).get("query", "")
        panels.append({
            "title":      viz.get("title", viz_id),
            "source_viz": viz.get("type", "splunk.column"),
            "query":      query,
            "earliest":   ds.get("options", {}).get("earliest", "-24h"),
            "latest":     ds.get("options", {}).get("latest",   "now"),
        })

    inputs = []
    for inp in d.get("inputs", {}).values():
        inputs.append({
            "type":  inp.get("type"),
            "token": inp.get("options", {}).get("token"),
            "label": inp.get("title"),
        })

    return {
        "title":  d.get("title", "Migrated Dashboard"),
        "panels": panels,
        "inputs": inputs,
    }
```

### SPL → Cribl KQL Translation Table

Apply these rules in order. After rule-based translation, translate residual complex expressions by hand (Step 3 fallback).

| SPL | Cribl KQL | Notes |
|-----|-----------|-------|
| `index=myindex` | `dataset="myindex"` | Map index → dataset name |
| `sourcetype=pan:traffic` | `\| where sourcetype == "pan:traffic"` | Or omit if dataset scoped |
| `search field=value` | `\| where field == "value"` | |
| `search field=value*` | `\| where field startswith "value"` | Wildcard → startswith |
| `NOT field=value` | `\| where field != "value"` | |
| `\| where field="value"` | `\| where field == "value"` | `=` → `==` |
| `\| fields field1, field2` | `\| project field1, field2` | |
| `\| rename old AS new` | `\| extend new=old \| project-away old` | **If `old` is a dotted/nested path** (`A.B`), `extend new=old` fails — use `extract_json`/`parse_json` instead (see "JSON Fields and Nested Objects") |
| `\| spath input=field output=new path=a.b` | `\| extend new=extract_json("$.a.b", field)` | Nested JSON — NOT `project-rename`/`extend` on a dotted name |
| `\| rex field=_raw "...JSON..."` then nested ref | `parse_json(extract(...))` + `tostring(obj.a.b)` | See "JSON Fields and Nested Objects" |
| `\| stats count by field` | `\| summarize count() by field` | |
| `\| stats count AS cnt by field` | `\| summarize cnt=count() by field` | |
| `\| stats sum(bytes) by src` | `\| summarize bytes=sum(bytes) by src` | |
| `\| stats avg(dur) by host` | `\| summarize avg_dur=avg(dur) by host` | |
| `\| stats dc(field) by grp` | `\| summarize dcount(field) by grp` | |
| `\| stats count, sum(b) by f` | `\| summarize count(), total=sum(b) by f` | |
| `\| stats values(field) by grp` | `\| summarize make_set(field) by grp` | |
| `\| stats first(f) by grp` | `\| summarize any(f) by grp` | |
| `\| timechart count` | `\| timestats span=1h count=count()` | Default span 1h |
| `\| timechart span=5m count` | `\| timestats span=5m count=count()` | |
| `\| timechart span=5m count by field` | `\| timestats span=5m count=count() by field` | |
| `\| timechart sum(bytes) by host` | `\| timestats span=1h bytes=sum(bytes) by host` | |
| `\| top 10 field` | `\| top-hitters 10 of field` | |
| `\| rare field` | `\| summarize count() by field \| sort by count_ asc \| limit 10` | |
| `\| sort -count` | `\| sort by count_ desc` | |
| `\| sort +field` | `\| sort by field asc` | |
| `\| head 20` | `\| limit 20` | |
| `\| tail 20` | `\| sort by _time asc \| limit 20` | |
| `\| dedup field` | `\| summarize by field` | Approximate |
| `\| eval new=field1+field2` | `\| extend new=field1+field2` | |
| `\| eval label=if(x>0,"yes","no")` | `\| extend label=iif(x>0,"yes","no")` | |
| `\| eval f=coalesce(a,b)` | `\| extend f=coalesce(a,b)` | |
| `\| eval f=len(str)` | `\| extend f=strlen(str)` | |
| `\| eval f=lower(str)` | `\| extend f=tolower(str)` | |
| `\| eval f=upper(str)` | `\| extend f=toupper(str)` | |
| `\| eval f=substr(s,1,3)` | `\| extend f=substring(s,0,3)` | 0-indexed in KQL |
| `\| eval f=tostring(n)` | `\| extend f=tostring(n)` | Same |
| `\| eval f=tonumber(s)` | `\| extend f=toint(s)` | |
| `\| eval f=now()` | `\| extend f=now()` | Same |
| `\| lookup mytable.csv field` | `\| lookup field in "mytable.csv"` | Lookup must exist in Cribl |
| `\| iplocation src_ip` | `\| ip-lookup 'GeoLite2-City' on src_ip` | MMDB must be uploaded |
| `\| rex field=_raw "(?<name>pattern)"` | `// MANUAL: rex extraction` | Translate by hand |
| `\| transaction field` | `// MANUAL: transaction` | Translate by hand |
| `\| predict` | `// NO EQUIVALENT — remove panel` | Flag for user |
| `\| anomalydetection` | `// NO EQUIVALENT — remove panel` | Flag for user |
| `\| appendcols [...]` | `// MANUAL: appendcols` | Translate by hand |
| `\| join type=inner [...]` | `\| join kind=inner (...) on field` | S3 datasets unsupported |

**Token translation:**
```
$form.env$     →  $env_filter$     (match inputId)
$earliest$     →  $TIME.earliest$
$latest$       →  $TIME.latest$
```

### Splunk → Cribl Visualization Type Map

| Splunk charting.chart | Splunk panel type | Cribl Type |
|---|---|---|
| `bar` / `column` | chart | `chart.column` |
| `line` | chart | `chart.line` |
| `area` | chart | `chart.area` |
| `pie` | chart | `chart.pie` |
| `scatter` | chart | `chart.column` (flag) |
| `bubble` | chart | `chart.column` (flag) |
| `radialGauge` | chart | `chart.pie` (flag) |
| `fillerGauge` | chart | `chart.column` (flag) |
| `markerGauge` | chart | `chart.column` (flag) |
| — | table | `list.table` |
| — | single | `chart.column` (flag — no stat panel in Cribl) |
| — | map | `chart.map` |
| — | event | `list.events` |
| `splunk.bar` | Studio | `chart.column` |
| `splunk.line` | Studio | `chart.line` |
| `splunk.area` | Studio | `chart.area` |
| `splunk.pie` | Studio | `chart.pie` |
| `splunk.table` | Studio | `list.table` |
| `splunk.choropleth.svg` | Studio | `chart.map` |
| `splunk.singlevalue` | Studio | `chart.column` (flag) |
| `splunk.rectangle` | Studio | `markdown.default` (flag) |

### Splunk Input Type Map

| Splunk Input Type | Cribl Type | Notes |
|---|---|---|
| `time` | `input.timerange` | Map earliest/latest defaults. |
| `dropdown` | `input.dropdown` | Static `<choice>` list → emit as an inline search returning hardcoded rows, or populate from a real dataset query. |
| `text` | `input.text` | Direct mapping. |
| `checkbox` | Two-option `input.dropdown` (`Yes`/`No`) | No native checkbox. If the checkbox flips a control token that toggles panel visibility, drop the token — Cribl has no `depends`. |
| `radio` | `input.dropdown` | Same choice-to-search mapping as dropdown. |
| `multiselect` | `input.dropdown` **or** `input.text` (comma-list) | No native multi. Downgrade path depends on cardinality — see `references/splunk-xml-advanced.md` §2. Always flag the loss of multi-value UX in the report. |
| `link` (tab switch) | `markdown.default` | Flatten tabs into sections. |

**Advanced Splunk features not covered by this base table** — `<change>`/`<condition>`/`<set token>` reactive logic, `<drilldown><set token>`, chart `<selection>` brush, `depends="…"` panel gating, `<html>` custom UI, `script=`/`stylesheet=` hooks, `printgeocode`, `loadjob $sid$`, `from datamodel:`, Leaflet map path lines with HTML popups, and missing SPL commands (`spath`, `mv-expand`, `replace`, `accum`, `streamstats`, `eventstats`, `rangemap`, `strftime`/`strptime`, `substr`) — see **`references/splunk-xml-advanced.md`** for the conversion patterns, workarounds, and worked examples. Load that file whenever the source XML contains any of those constructs.

---

## Vendor 2: Sumo Logic

### Format Detection

Sumo Logic "Dashboard (New)" format is JSON from their API:
```
GET https://api.sumologic.com/api/v2/dashboards/{id}
```

Top-level keys: `title`, `description`, `panels`, `variables`, `layout`.

Legacy "Dashboard" format (pre-2020) is XML — treat similar to Splunk SimpleXML but with Sumo QL.

### Sumo Logic JSON Parser

```python
def parse_sumo_dashboard(json_str):
    d = json.loads(json_str)
    panels = []

    for panel in d.get("panels", []):
        # Sumo panels have queries array
        queries = panel.get("queries", [])
        query_str = queries[0].get("queryString", "") if queries else ""
        panels.append({
            "title":      panel.get("title", ""),
            "source_viz": panel.get("visualSettings", {}).get("general", {}).get("type", "bar"),
            "query":      query_str,
            "layout":     panel.get("layout", {}),  # {x, y, w, h} already!
        })

    inputs = []
    for var in d.get("variables", []):
        inputs.append({
            "type":         var.get("variableType"),  # "Text", "Dropdown"
            "name":         var.get("name"),
            "label":        var.get("displayName", var.get("name")),
            "default":      var.get("defaultValue", "*"),
            "source_query": var.get("lookupQueryDefinition", {}).get("queryString", ""),
        })

    return {
        "title":  d.get("title", "Migrated Dashboard"),
        "panels": panels,
        "inputs": inputs,
        "time_range": d.get("timeRange", {}),
    }
```

### Sumo Logic QL → Cribl KQL Translation Table

| Sumo Logic QL | Cribl KQL | Notes |
|---|---|---|
| `_index=security` | `dataset="security"` | |
| `_sourceCategory=prod/nginx` | `\| where sourceCategory == "prod/nginx"` | |
| `_sourceName=/var/log/syslog` | `\| where sourceName == "/var/log/syslog"` | |
| `_collector=my-collector` | `\| where collector == "my-collector"` | |
| `\| count by field` | `\| summarize count() by field` | |
| `\| count as cnt by field` | `\| summarize cnt=count() by field` | |
| `\| sum(bytes) by host` | `\| summarize bytes=sum(bytes) by host` | |
| `\| avg(dur) by src` | `\| summarize avg_dur=avg(dur) by src` | |
| `\| min(x), max(x) by field` | `\| summarize min_x=min(x), max_x=max(x) by field` | |
| `\| pct(field, 95) by grp` | `\| summarize p95=percentile(field,95) by grp` | |
| `\| count_distinct(field)` | `\| summarize dcount(field)` | |
| `\| timeslice 5m` | _(absorbed into timestats)_ | |
| `\| timeslice 5m \| count by _timeslice` | `\| timestats span=5m count=count()` | |
| `\| timeslice 1h \| sum(bytes) by _timeslice, host` | `\| timestats span=1h bytes=sum(bytes) by host` | |
| `\| top 10 field` | `\| top-hitters 10 of field` | |
| `\| topk(10, count)` | `\| sort by count_ desc \| limit 10` | |
| `\| where field = "value"` | `\| where field == "value"` | `=` → `==` |
| `\| where field matches /regex/` | `\| where field matches regex "regex"` | |
| `\| where !isnull(field)` | `\| where isnotnull(field)` | |
| `\| fields field1, field2` | `\| project field1, field2` | |
| `\| fields -field1` | `\| project-away field1` | |
| `\| sort by field asc` | `\| sort by field asc` | Same |
| `\| sort by field desc` | `\| sort by field desc` | Same |
| `\| limit 20` | `\| limit 20` | Same |
| `\| if(cond, t, f)` | `\| extend x=iif(cond,t,f)` | Wrap in extend |
| `\| concat(a,"-",b) as c` | `\| extend c=strcat(a,"-",b)` | |
| `\| num(field)` | `\| extend field=toint(field)` | |
| `\| toLower(field)` | `\| extend field=tolower(field)` | |
| `\| toUpper(field)` | `\| extend field=toupper(field)` | |
| `\| urldecode(field)` | `// MANUAL: urldecode` | |
| `\| parse "* [*] *" as a, b, c` | `// MANUAL: parse anchor` | |
| `\| parse regex "(?<name>pat)"` | `// MANUAL: parse regex` | |
| `\| geo lookup` | `\| ip-lookup 'GeoLite2-City' on src_ip` | |
| `\| lookup` | `\| lookup field in "file.csv"` | File must exist |
| `\| predict` | `// NO EQUIVALENT` | Flag for user |
| `\| outlier` | `// NO EQUIVALENT` | Flag for user |
| `\| sessionize` | `// NO EQUIVALENT` | Flag for user |
| `\| save` | `// NO EQUIVALENT — remove` | |
| `\| compare` | `// MANUAL: compare` | |
| `{{variable}}` token | `$variable_filter$` | Map variable name → inputId |

**Sumo time range translation:**
```python
def translate_sumo_time(time_range):
    t = time_range.get("type", "")
    if t == "BeginBoundedTimeRange":
        from_ = time_range.get("from", {})
        if from_.get("type") == "RelativeTimeRangeBoundary":
            return from_.get("relativeTime", "-1h"), "now"
    return "-1h", "now"
```

### Sumo Logic Visualization Type Map

| Sumo Type | Cribl Type |
|---|---|
| `bar` | `chart.column` |
| `column` | `chart.column` |
| `line` | `chart.line` |
| `area` | `chart.area` |
| `pie` | `chart.pie` |
| `table` | `list.table` |
| `map` | `chart.map` |
| `honeycomb` | `chart.pie` (flag) |
| `scatter` | `chart.column` (flag) |
| `bubble` | `chart.column` (flag) |
| `single_value` | `chart.column` (flag) |
| `svgmap` | `chart.map` |

### Sumo Variable → Cribl Input Map

| Sumo variableType | Cribl Type | Notes |
|---|---|---|
| `Text` | `input.text` | Map defaultValue |
| `Dropdown` | `input.dropdown` | If has `lookupQueryDefinition`, use as search |
| `Time range` | `input.timerange` | Map time range defaults |

**Sumo layout bonus:** Sumo's panel layout already uses `{x, y, w, h}` — translate directly to Cribl layout, scaling as needed (Sumo uses a 24-col grid; Cribl uses 12-col, so divide x and w by 2).

---

## Vendor 3: Elastic / Kibana

### Format Detection

Kibana dashboard exports are NDJSON (saved objects). Top-level type is `"dashboard"`, with embedded panel references to `"visualization"`, `"lens"`, `"maps"`, and `"search"` saved objects.

Export via: **Stack Management → Saved Objects → Export**

Or API: `GET /api/saved_objects/_export` with `{"type": ["dashboard"],"includeReferencesDeep": true}`

### Kibana Parser

```python
import json

def parse_kibana_export(ndjson_str):
    objects = [json.loads(line) for line in ndjson_str.strip().split("\n") if line]

    # Index by id for reference resolution
    obj_map = {o["id"]: o for o in objects}

    dashboard = next((o for o in objects if o["type"] == "dashboard"), None)
    if not dashboard:
        return None

    attrs = dashboard.get("attributes", {})
    panels_raw = json.loads(attrs.get("panelsJSON", "[]"))

    panels = []
    for panel in panels_raw:
        ref_id  = panel.get("panelRefName", "").replace("panel_", "")
        ref_obj = obj_map.get(ref_id, {})
        ref_attrs = ref_obj.get("attributes", {})

        # Lens visualization
        state = ref_attrs.get("state", {})
        layers = state.get("datasourceStates", {}).get("indexpattern", {}).get("layers", {})

        # Get index pattern title
        index_ref = next((r for r in ref_obj.get("references", [])
                         if r["type"] == "index-pattern"), {})
        index_title = obj_map.get(index_ref.get("id",""), {}).get("attributes", {}).get("title", "")

        viz_type = ref_attrs.get("visState") and json.loads(ref_attrs["visState"]).get("type", "")
        if not viz_type:
            viz_type = state.get("visualization", {}).get("preferredSeriesType", "bar")

        # Extract queries from filter/query
        query_str = ref_attrs.get("kibanaSavedObjectMeta", {})
        search_source = json.loads(query_str.get("searchSourceJSON", "{}")) if isinstance(query_str, dict) else {}
        filter_str = json.dumps(search_source.get("filter", []))

        panels.append({
            "title":       ref_attrs.get("title", panel.get("title", "")),
            "source_viz":  viz_type,
            "index":       index_title,
            "query":       search_source.get("query", {}).get("query", ""),
            "filters":     filter_str,
            "grid_data":   panel.get("gridData", {}),
        })

    return {
        "title":  attrs.get("title", "Migrated Dashboard"),
        "panels": panels,
        "inputs": [],  # Kibana controls parsed separately
    }
```

### Kibana/Lens Query Translation

Kibana queries use KQL (Kibana Query Language) OR Lucene. Neither is identical to Cribl KQL:

| Kibana KQL / Lucene | Cribl KQL | Notes |
|---|---|---|
| `field: value` | `\| where field == "value"` | |
| `field: (val1 OR val2)` | `\| where field == "val1" or field == "val2"` | |
| `field: value*` | `\| where field startswith "value"` | |
| `NOT field: value` | `\| where field != "value"` | |
| `field >= 100` | `\| where field >= 100` | Same |
| `field: [100 TO 200]` | `\| where field >= 100 and field <= 200` | |
| `field.nested: value` | `\| where field.nested == "value"` | Dotted access OK in `where`; but to RENAME/extract a nested value use `extract_json`/`parse_json`, never `project-rename` on a dotted name (see "JSON Fields and Nested Objects") |
| `_exists_: field` | `\| where isnotnull(field)` | |
| `@timestamp` | `_time` | Rename time field |

**Lens metric translations:**

| Kibana Lens Function | Cribl KQL |
|---|---|
| `count()` | `count()` |
| `sum(field)` | `sum(field)` |
| `average(field)` | `avg(field)` |
| `min(field)` | `min(field)` |
| `max(field)` | `max(field)` |
| `unique_count(field)` | `dcount(field)` |
| `percentile(field,95)` | `percentile(field, 95)` |
| `counter_rate(field)` | `// MANUAL: rate calculation` |
| `moving_average(...)` | `// NO EQUIVALENT` — flag |
| `cumulative_sum(...)` | `// NO EQUIVALENT` — flag |
| `differences(...)` | `// NO EQUIVALENT` — flag |

**Index pattern → dataset:**
```python
def index_to_dataset(index_pattern):
    # "logs-*" → use as-is or map to known dataset
    # "filebeat-*" → likely needs custom mapping
    # Strip wildcards for exact dataset name
    return index_pattern.rstrip("*-").replace("-", "_").replace(".", "_")
```

### Kibana Visualization Type Map

| Kibana Type | Cribl Type |
|---|---|
| `bar` / `horizontal_bar` | `chart.column` / `chart.horizontalBar` |
| `line` | `chart.line` |
| `area` | `chart.area` |
| `pie` / `donut` | `chart.pie` |
| `table` / `datatable` | `list.table` |
| `metric` (single value) | `chart.column` (flag) |
| `gauge` | `chart.column` (flag) |
| `goal` | `chart.column` (flag) |
| `heatmap` | `chart.column` (flag) |
| `timelion` | `chart.line` (flag — Timelion syntax not translatable) |
| `maps` (Elastic Maps) | `chart.map` |
| `vega` | `// NO EQUIVALENT` — flag |
| `tsvb` | `// MANUAL` (TSVB has complex pipeline syntax) |
| `tag_cloud` | `chart.horizontalBar` (flag) |

**Grid translation:** Kibana uses a 48-column grid (`gridData.w` and `gridData.x`). Divide by 4 to get Cribl 12-column values.

---

## Vendor 4: Grafana

### Format Detection

Grafana dashboard JSON has top-level keys: `"title"`, `"panels"`, `"templating"`, `"time"`, `"uid"`.

Export via: **Dashboard → Share → Export JSON** or API:
`GET /api/dashboards/uid/{uid}`

### Grafana Parser

```python
def parse_grafana_dashboard(json_str):
    d = json.loads(json_str)
    # Handle API wrapper
    if "dashboard" in d:
        d = d["dashboard"]

    panels = []

    def extract_panels(panel_list, row_y=0):
        for panel in panel_list:
            if panel.get("type") == "row":
                # Grafana rows contain nested panels
                extract_panels(panel.get("panels", []), panel.get("gridPos", {}).get("y", row_y))
                continue

            targets = panel.get("targets", [])
            queries = []
            for t in targets:
                # DataSource-specific query extraction
                expr   = t.get("expr", "")           # Prometheus PromQL
                query  = t.get("query", "")           # Generic / Loki
                raw_sql = t.get("rawSql", "")         # SQL
                q = expr or query or raw_sql or ""
                if q:
                    queries.append({
                        "query": q,
                        "legend": t.get("legendFormat", ""),
                        "datasource": t.get("datasource", {})
                    })

            grid = panel.get("gridPos", {"x": 0, "y": 0, "w": 12, "h": 4})
            panels.append({
                "title":      panel.get("title", ""),
                "source_viz": panel.get("type", "graph"),
                "queries":    queries,
                "grid":       grid,
                "datasource": panel.get("datasource", {}),
                "options":    panel.get("options", {}),
                "field_config": panel.get("fieldConfig", {}),
            })

    extract_panels(d.get("panels", []))

    inputs = []
    for tpl in d.get("templating", {}).get("list", []):
        inputs.append({
            "type":    tpl.get("type"),        # "query", "custom", "interval", "datasource", "textbox"
            "name":    tpl.get("name"),
            "label":   tpl.get("label", tpl.get("name")),
            "query":   tpl.get("query", ""),
            "options": tpl.get("options", []),
            "current": tpl.get("current", {}).get("value", ""),
        })

    return {
        "title":      d.get("title", "Migrated Dashboard"),
        "panels":     panels,
        "inputs":     inputs,
        "time":       d.get("time", {"from": "now-1h", "to": "now"}),
        "datasource": d.get("panels", [{}])[0].get("datasource", {}) if d.get("panels") else {},
    }
```

### Grafana Query Translation by Data Source

**Prometheus / PromQL → Cribl KQL:**

| PromQL | Cribl KQL | Notes |
|---|---|---|
| `http_requests_total` | `\| where __name__ == "http_requests_total"` | Metric name filter |
| `rate(metric[5m])` | `\| timestats span=5m rate=count()` | Approximate |
| `sum(metric) by (label)` | `\| summarize total=sum(value) by label` | |
| `avg(metric) by (label)` | `\| summarize avg_val=avg(value) by label` | |
| `histogram_quantile(0.95, ...)` | `\| summarize p95=percentile(value,95)` | |
| `metric{label="val"}` | `\| where label == "val"` | Label selector |
| `metric{label=~"val.*"}` | `\| where label matches regex "val.*"` | |
| `metric{label!="val"}` | `\| where label != "val"` | |
| Complex PromQL | `// MANUAL` | |

**Loki LogQL → Cribl KQL:**

| LogQL | Cribl KQL | Notes |
|---|---|---|
| `{job="nginx"}` | `\| where job == "nginx"` | Stream selector |
| `{app="web"} \|= "error"` | `\| where app == "web" and _raw contains "error"` | |
| `{app="web"} \|~ "err.*"` | `\| where app == "web" and _raw matches regex "err.*"` | |
| `\| json` | _(already parsed in Cribl)_ | |
| `\| logfmt` | _(already parsed in Cribl)_ | |
| `\| pattern` | `// MANUAL` | |
| `\| line_format` | `// MANUAL` | |
| `\| label_format` | `\| extend newname=oldname` | |
| `count_over_time({...}[5m])` | `\| timestats span=5m count=count()` | |
| `sum(rate({...}[5m])) by (label)` | `\| timestats span=5m count=count() by label` | |
| `bytes_over_time({...}[5m])` | `\| timestats span=5m bytes=sum(bytes)` | |

**Grafana Infinity / JSON / CSV datasource:**
These query external URLs or files. For Cribl, note the source URL in a comment and suggest the user set up an api_http dataset pointing to the same endpoint.

**Grafana Elasticsearch:**
Grafana sends JSON DSL queries to Elasticsearch. These are complex to translate directly — translate each one by hand (Step 3 fallback) and flag all of them.

**Grafana SQL (MySQL, PostgreSQL, ClickHouse):**
If the Cribl dataset is backed by the same DB (e.g., Lakehouse on ClickHouse), the SQL may translate directly. Otherwise translate by hand (Step 3 fallback).

### Grafana Visualization Type Map

| Grafana Type | Cribl Type |
|---|---|
| `graph` / `timeseries` | `chart.line` |
| `barchart` / `bargauge` | `chart.column` |
| `histogram` | `chart.column` |
| `piechart` / `donut` | `chart.pie` |
| `table` | `list.table` |
| `stat` (single value) | `chart.column` (flag) |
| `gauge` | `chart.column` (flag) |
| `heatmap` | `chart.column` (flag) |
| `geomap` | `chart.map` |
| `logs` | `list.events` |
| `news` | `markdown.default` (flag) |
| `text` (markdown) | `markdown.default` |
| `xychart` | `chart.line` |
| `candlestick` | `chart.line` (flag) |
| `nodeGraph` | `// NO EQUIVALENT` — flag |
| `traces` | `// NO EQUIVALENT` — flag |

**Grid translation:** Grafana uses a 24-column grid. Divide `x` and `w` by 2 for Cribl 12-column values.

### Grafana Template Variable → Cribl Input Map

| Grafana Type | Cribl Type | Notes |
|---|---|---|
| `query` | `input.dropdown` | Translate query to Cribl dataset query |
| `custom` | `input.dropdown` | Use options as static choices (not supported natively — use search returning hardcoded values) |
| `interval` | `input.timerange` | Map to time range input |
| `textbox` | `input.text` | Direct mapping |
| `datasource` | _(omit)_ | Not applicable in Cribl |
| `constant` | _(hardcode in query)_ | |

**Time range translation:**
```python
def translate_grafana_time(time_obj):
    from_val = time_obj.get("from", "now-1h")
    to_val   = time_obj.get("to", "now")
    # Grafana: "now-1h" → Cribl: "-1h"
    earliest = from_val.replace("now-", "-").replace("now", "now")
    return earliest, to_val
```

---

## Parent Search Inference

After parsing all panels, group them by shared base query to create parent searches:

```python
from collections import defaultdict
import hashlib

def infer_parents(panels):
    """
    Groups panels by their base dataset+filter query.
    Panels sharing the same base become children of a parent search.
    """
    def base_query(q):
        lines = [l.strip() for l in q.split("\n") if l.strip()]
        # Base = dataset line + any where filters (not summarize/timestats/top-hitters)
        base = []
        for line in lines:
            if any(line.startswith(op) for op in
                   ["| summarize", "| timestats", "| top-hitters", "| sort", "| limit", "| project"]):
                break
            base.append(line)
        return "\n".join(base)

    groups = defaultdict(list)
    for panel in panels:
        key = hashlib.md5(base_query(panel["query"]).encode()).hexdigest()
        groups[key].append(panel)

    parents = {}
    for key, group in groups.items():
        if len(group) > 1:
            # Worth making a parent — multiple panels share this base
            parent_id = f"parent_{list(groups.keys()).index(key)}"
            parents[parent_id] = {
                "base_query": base_query(group[0]["query"]),
                "panels": group
            }

    return parents
```

---

## Complete Migration Driver

```python
def migrate_dashboard(source_json_or_xml, source_vendor, target_dataset_map=None):
    """
    Full migration pipeline.
    target_dataset_map: dict mapping source index/dataset names to Cribl dataset names
                        e.g. {"firewall": "criblcoffee_pan", "logs-*": "my_logs"}
    """
    # 1. Parse
    if source_vendor == "splunk_xml":
        parsed = parse_splunk_xml(source_json_or_xml)
    elif source_vendor == "splunk_studio":
        parsed = parse_splunk_studio(source_json_or_xml)
    elif source_vendor == "sumo":
        parsed = parse_sumo_dashboard(source_json_or_xml)
    elif source_vendor == "kibana":
        parsed = parse_kibana_export(source_json_or_xml)
    elif source_vendor == "grafana":
        parsed = parse_grafana_dashboard(source_json_or_xml)
    else:
        raise ValueError(f"Unknown vendor: {source_vendor}")

    # 2. Translate queries
    for panel in parsed["panels"]:
        panel["cribl_query"] = translate_query(
            panel.get("query", ""),
            source_vendor,
            target_dataset_map or {}
        )
        panel["cribl_viz"] = translate_viz_type(panel.get("source_viz", ""), source_vendor)

    # 3. Infer parents
    parents = infer_parents(parsed["panels"])

    # 4. Translate inputs
    cribl_inputs = translate_inputs(parsed["inputs"], source_vendor)

    # 5. Emit (use Part A patterns)
    elements = []
    elements.extend(cribl_inputs)

    for parent_id, parent in parents.items():
        elements.append(make_parent_element(parent_id, parent["base_query"]))
        for panel in parent["panels"]:
            child_query = strip_base_query(panel["cribl_query"])
            elements.append(make_child_vis(panel, child_query, parent_id))

    # Standalone panels (no shared base)
    for panel in parsed["panels"]:
        if not any(panel in p["panels"] for p in parents.values()):
            elements.append(make_standalone_vis(panel))

    # Generate id from title: lowercase, replace spaces/hyphens with underscores, strip invalid chars
    import re
    dash_id = re.sub(r'[^a-zA-Z0-9_]', '_', parsed["title"].replace(" ", "_").replace("-", "_")).strip("_")

    return {
        "id": dash_id,
        "schedule": {"enabled": False, "cronSchedule": "0 0 * * *", "tz": "UTC", "keepLastN": 2},
        "groups": {},
        "name": parsed["title"],
        "elements": elements
    }
```

---

## Migration Flags and Reporting

Always generate a migration report alongside the dashboard JSON:

```python
def generate_migration_report(panels):
    flags = []
    for panel in panels:
        q = panel.get("cribl_query", "")
        if "// MANUAL" in q:
            flags.append(f"⚠️  '{panel['title']}': query needs manual translation — verify output")
        if "// NO EQUIVALENT" in q:
            flags.append(f"❌ '{panel['title']}': no Cribl equivalent — panel removed or simplified")
        if "// MIGRATION TODO" in q:
            flags.append(f"🔧 '{panel['title']}': manual translation required")
        if panel.get("cribl_viz") != panel.get("source_viz"):
            flags.append(f"ℹ️  '{panel['title']}': viz type changed {panel['source_viz']} → {panel['cribl_viz']}")

    return "\n".join(flags) if flags else "✅ No migration issues detected"
```

### Common Migration Issues by Vendor

| Issue | Vendors | Resolution |
|---|---|---|
| Single value / stat panels | All | Convert to `chart.column` with single bar; flag for user |
| Regex-based field extraction | Splunk, Sumo | Hand translation or Cribl Code function |
| `transaction` / `sessionize` | Splunk, Sumo | Hand translation; may need Stream pipeline preprocessing |
| Multi-series Prometheus metrics | Grafana | Each `rate()` → `timestats` approximation; flag |
| Saved searches as panel sources | Splunk | Dereference and inline the query |
| Tabs / navigation | Splunk Studio | Flatten into sections with markdown headers |
| Panel drilldown links | All | Not supported in Cribl; strip and flag |
| Alert thresholds on panels | Grafana | Not supported in Cribl; strip and flag |
| Row repeat (variable-driven rows) | Grafana | Flatten to individual panels; flag |
| Transformations (Grafana) | Grafana | Hand translation or absorb into KQL |
| TSVB pipeline aggregations | Kibana | Hand translation; complex pipeline syntax |
| Vega / Vega-Lite | Kibana | No equivalent; remove and flag |
| Timelion expressions | Kibana | Hand translation; often translatable to timestats |
| Multi-value template vars | Grafana, Splunk | Approximate with text input; flag |

---

# CHECKLISTS

## Pre-Deploy Checklist (Building)

- [ ] Every field name confirmed from actual query results — never guessed
- [ ] Every query tested via MCP with non-zero results (or noted as unverifiable)
- [ ] No `||` in any where clause (use `or`)
- [ ] No `kind=left` or `kind=outer` joins (only `kind=inner`)
- [ ] Dashboard JSON valid: `python3 -m json.tool < dashboard.json`
- [ ] All element IDs unique
- [ ] `axis: {}` present on every chart config
- [ ] `variant: "input"` on all input elements
- [ ] `variant: "markdown"` on all markdown elements
- [ ] `colorPalette` set on every chart
- [ ] Standalone panels use `$TIME.earliest$` / `$TIME.latest$` / `$TIME.timezone$`
- [ ] Child panels have `parentSearchId` at **both** top-level AND inside `search` block
- [ ] Child panels use `"earliest": 0, "latest": "now"` (not time tokens)
- [ ] Child queries start with `|` (no `dataset=` prefix)
- [ ] `hidePanel: true` on all parent `list.events` elements
- [ ] `title` present on all `list.events` parents
- [ ] Map panels use `| summarize by country` and `chart.map` config with `mapDetails`
- [ ] `ip-lookup` uses single quotes: `ip-lookup 'GeoLite2-City' on field`
- [ ] `input.dropdown` used (not `input.select`) for dynamic dropdowns
- [ ] Top-level `id` present and matches `^[a-zA-Z0-9_]+$` (required for API create — no hyphens or spaces)
- [ ] Top-level dashboard structure: `id`, `schedule`, `groups`, `name`, `elements` — no `description` or `category`

## Pre-Migration Checklist

- [ ] Source dashboard exported completely (including referenced saved objects for Kibana)
- [ ] All index/dataset names mapped to Cribl dataset names
- [ ] Lookup files referenced in queries uploaded to Cribl Search
- [ ] MMDB file (`GeoLite2-City.mmdb`) uploaded if geo enrichment used
- [ ] Every `// MANUAL` query hand-translated and verified with `cribl_runSearchQuery`
- [ ] Migration report reviewed — all flags addressed or accepted
- [ ] Translated queries tested via MCP before final dashboard build
- [ ] All Pre-Deploy Checklist items above satisfied

---

# PART C — VIZ-LAB DASHBOARDS

Viz-Lab is a Cribl Search App Platform add-on ([Cribl-Community/cc-viz-lab](https://github.com/Cribl-Community/cc-viz-lab) — import into Cribl Search via **App Platform → Add App → Import from Git**) that provides 46+ built-in visualizations — including security-specific views not available in native Cribl Search dashboards (Attack Path Graph, Geo Attack Flows, Auth Anomaly Heatmap, MITRE ATT&CK Matrix, etc.). Viz-Lab dashboards use a **different JSON schema** from native Cribl dashboards and are deployed via the same Cribl Search REST API but to a different endpoint.

## Key Differences vs Native Cribl Dashboards

| | Native Cribl Dashboard | Viz-Lab Dashboard |
|---|---|---|
| Schema | `{ schedule, groups, name, elements }` | `{ id, name, cols, widgets, vizlab: true, ... }` |
| Panels | `elements[]` with `type`, `search`, `config` | `widgets[]` with `vizId`, `query` (flat KQL string) |
| Naming | Any `^[a-zA-Z0-9 _-]+$` | **Must start with `vz_`** to be visible in Viz-Lab |
| API endpoint | `/m/default_search/search/dashboards` | `/m/default_search/search/dashboards` (same) |
| Parent searches | Supported via `parentSearchId` | **Not supported** — every widget has its own `query` |
| Channel mapping | Implicit via chart config | Explicit via field names matching channel `suggest` hints |

## Viz-Lab JSON Schema

```json
{
  "id": "d-unique-id",
  "name": "vz_My Dashboard",
  "createdAt": 1234567890000,
  "updatedAt": 1234567890000,
  "cols": 12,
  "rowHeight": 60,
  "gap": 10,
  "refreshSec": 0,
  "theme": "inherit",
  "accent": "teal",
  "timeRange": {
    "earliest": "-7d",
    "latest": "now",
    "label": "-7d → now"
  },
  "variables": [
    {
      "id": "v-time",
      "name": "TIME",
      "label": "Time Range",
      "type": "time",
      "default": "",
      "current": ""
    }
  ],
  "widgets": [ ... ],
  "version": 1,
  "vizlab": true
}
```

**Required fields:** `id`, `name`, `cols`, `rowHeight`, `widgets`, `version: 1`, `vizlab: true`

## Widget Schema

```json
{
  "id": "w-uniqueid",
  "title": "Panel Title",
  "x": 0, "y": 0, "w": 6, "h": 5,
  "query": "dataset=\"my_dataset\"\n| summarize count() by field",
  "hidePanel": false,
  "options": { "showTitle": true },
  "kind": "viz",
  "vizId": "sankey"
}
```

**Rules:**
- `id` must be unique across all widgets — use `w-` prefix with a short slug
- `query` is a raw KQL string (not a search block object) — newlines as `\n`
- Every widget has its own standalone query — no parent/child relationship
- `kind` is always `"viz"`
- Layout grid: 12 columns, `rowHeight: 60px`, `gap: 10px`

## Channel Mapping — Critical Rule

Viz-Lab auto-maps query result columns to viz channels using `suggest` hints baked into each vizId. **Name your output columns to match these hints** and channels wire up automatically.

| vizId | Required output columns | Optional columns |
|---|---|---|
| `single` | `value` | `label` |
| `arc-gauge` | `value` | `label` |
| `kpi-strip` | `category`, `value` | `spark` |
| `bar` / `column` | x-axis field, y-axis field | — |
| `pie` / `donut` | category field, value field | — |
| `line` / `area` | time/x field, value field | series field |
| `sankey` | `source`, `target`, `value` | — |
| `chord` | `source`, `target`, `value` | — |
| `treemap` | `level1`, `level2` (optional: `level3`, `level4`), `value` | — |
| `sunburst` | `level1`, `level2` (optional: `level3`, `level4`), `value` | — |
| `network2d` | `source`, `target` | `value` |
| `attack-graph` | `source`, `target` | `stage`, `value` |
| `geo-choropleth` | `region`, `value` | — |
| `geo-attack-flows` | `src_country`, `dst_country` | `src_lat`, `src_lng`, `dst_lat`, `dst_lng`, `value`, `severity` |
| `auth-heatmap` | `time`, `outcome` | `user`, `total` |
| `heatmap` | `x`, `y`, `value` | — |
| `alert-correlation` | `alert_id`, `entity` | `severity` |
| `ioc-streamgraph` | `time`, `ioc_type` | `value` |
| `mitre-matrix` | `tactic`, `technique` | `value` |
| `kill-chain-funnel` | `stage` | `value` |
| `detection-radar` | `tactic`, `value` | `total` |

**Pattern:** always end queries with `| extend source=src_field, target=dst_field | project source, target, value` to make channel names explicit.

## Security vizIds — Full Catalog

| vizId | Label | Best for |
|---|---|---|
| `geo-attack-flows` | Geo Attack Flows | Animated arcs between countries — blocked traffic origin/dest |
| `geo-choropleth` | Geo Choropleth | Country heatmap — attack intensity by source nation |
| `auth-heatmap` | Auth Anomaly Heatmap | Time × outcome grid — spot automated attack patterns |
| `attack-graph` | Attack Path Graph | IP-to-IP force graph — blocked connections, edge weight = count |
| `alert-correlation` | Alert Correlation | Bipartite alert × entity graph — campaign clustering |
| `mitre-matrix` | MITRE ATT&CK Matrix | Tactic × technique heatmap — detection coverage |
| `kill-chain-funnel` | Cyber Kill Chain | 7-stage funnel — gap visibility |
| `detection-radar` | Detection Coverage Radar | Radar of MITRE tactic coverage |
| `ioc-streamgraph` | IOC Velocity | IOC type over time — campaign surge detection |
| `sankey` | Sankey | Zone → Application → Action flows |
| `chord` | Chord Diagram | Zone-to-zone bidirectional traffic matrix |
| `treemap` | Treemap | Application × action bandwidth breakdown |
| `network2d` | Network Graph | 2D force graph — service/IP dependencies |

## API Deployment

Viz-Lab dashboards use the **same API endpoint** as native dashboards — the `vizlab: true` flag in the JSON tells Viz-Lab to pick them up.

```bash
BASE="$CRIBL_ORG_URL/api/v1"  # replace with your org URL

# Create
curl -s -X POST "$BASE/m/default_search/search/dashboards" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @/tmp/my_dashboard.viz-lab.json | jq '{id: .items[0].id, name: .items[0].name}'

# Update (PATCH by dashboard name/id)
curl -s -X PATCH "$BASE/m/default_search/search/dashboards/DASHBOARD_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @/tmp/my_dashboard.viz-lab.json

# List to verify
curl -s "$BASE/m/default_search/search/dashboards" \
  -H "Authorization: Bearer $TOKEN" | jq '[.items[] | {id, name}]'
```

**Naming rule:** `name` must start with `vz_` for Viz-Lab to display the dashboard in its launcher. Example: `"name": "vz_CISO Security Overview"`.

## Python Builder Template

```python
import json, time

DS = "my_dataset"
NOW = int(time.time() * 1000)

def widget(id_, title, vizId, x, y, w, h, query):
    return {
        "id": id_, "title": title,
        "x": x, "y": y, "w": w, "h": h,
        "query": query,
        "hidePanel": False,
        "options": {"showTitle": True},
        "kind": "viz",
        "vizId": vizId
    }

widgets = [
    widget("w-kpi-total", "Total Sessions", "single",
           0, 0, 3, 3,
           f'dataset="{DS}"\n| summarize value=count()'),

    widget("w-geo-flows", "Attack Flows", "geo-attack-flows",
           0, 3, 8, 6,
           f'dataset="{DS}"\n'
           f'| where action != "allow"\n'
           f'| summarize value=count() by source_location, destination_location\n'
           f'| extend src_country=source_location, dst_country=destination_location\n'
           f'| project src_country, dst_country, value\n'
           f'| sort by value desc | limit 30'),
]

dashboard = {
    "id": "d-my-dashboard",
    "name": "vz_My Dashboard",
    "createdAt": NOW, "updatedAt": NOW,
    "cols": 12, "rowHeight": 60, "gap": 10,
    "refreshSec": 0, "theme": "inherit", "accent": "teal",
    "timeRange": {"earliest": "-7d", "latest": "now", "label": "-7d → now"},
    "variables": [{"id": "v-time", "name": "TIME", "label": "Time Range",
                   "type": "time", "default": "", "current": ""}],
    "widgets": widgets,
    "version": 1, "vizlab": True
}

with open("/tmp/dashboard.viz-lab.json", "w") as f:
    json.dump(dashboard, f, indent=2)
```

## Viz-Lab Pre-Deploy Checklist

- [ ] Dashboard `name` starts with `vz_`
- [ ] `"version": 1` and `"vizlab": true` present at top level
- [ ] All widget `id` values unique, prefixed with `w-`
- [ ] Output column names match channel `suggest` hints for each `vizId`
- [ ] Every query tested via MCP before including in a widget
- [ ] `| project` used at end of each query to keep only needed columns
- [ ] `source_location` values containing `"0.0.0"` filtered out before geo vizs
- [ ] JSON validated: `python3 -m json.tool < dashboard.viz-lab.json`
- [ ] File saved as `*.viz-lab.json` for easy identification
- [ ] Bearer token obtained before curl deploy commands
