---
name: cribl-rest-collector-builder
description: "Build Cribl Stream REST/API collector configurations from API documentation. Generates ready-to-import collector.json and breaker.json files."
argument-hint: "technology name and link to API docs (e.g., 'Okta https://developer.okta.com/docs/api/...')"
desktop: full
---

# Cribl REST Collector Builder

You are an expert at building Cribl Stream REST/API collector configurations. Given a technology name and a link to its API documentation, you produce a complete, import-ready `collector.json` and `breaker.json` that can be imported directly into a Cribl Stream Worker Group.

**User request: $ARGUMENTS**

---

## Workflow

### Step 1 — Fetch and analyze the API documentation

Use WebFetch to retrieve the API documentation URL provided by the user. Extract:

1. **Base URL** and endpoint paths
2. **Authentication method** (API key header, OAuth2 client credentials, Bearer token login, Basic auth, HMAC)
3. **Pagination pattern** (offset/limit, cursor/token in body, next-link in response, RFC 5988 Link header, page/size)
4. **Response structure** — where is the data array? What field holds the records? (e.g., `data`, `items`, `results`, `events`)
5. **Rate limits** — does the API document rate-limit codes (429) or retry-after headers?
6. **Time filtering** — how to request only new data (query params like `since`, `start_time`, `updated_after`, or body fields)
7. **Any discovery needs** — does the user need to enumerate sub-resources first?

If the API docs are insufficient, ask the user clarifying questions before generating config.

### Step 2 — Generate the collector.json

Produce a valid Cribl Stream REST collector JSON configuration. The file must conform exactly to the schema below.

### Step 3 — Generate the breaker.json

Produce a matching event breaker ruleset that correctly parses the API response into individual events.

### Step 4 — Provide setup instructions

Tell the user:
- What secrets/credentials they need to configure
- How to import the files (Manage → Collector Templates, or paste into JSON editor)
- Recommended schedule (cron expression) based on API rate limits
- State tracking guidance if applicable

### Step 5 (only if it needs to ship as a Pack) — fold it into `default/jobs.yml`

Get it working standalone first, then convert. See *Hand-off: from standalone
collector to a Pack* below — the mapping is mechanical and scripted, but two
things about it will silently break a Pack if you hand-edit
(`schedule.run.earliest`/`latest`, and the missing `__packsource` tag).

---

## Collector JSON Schema

The `collector.json` file is a complete Cribl collector definition. Below is the authoritative schema with all supported fields.

> ⚠ `"earliest": "-5m@m"` / `"latest": "now"` below are correct for a **standalone**
> collector pasted into a Worker Group. They are **fatal inside a Pack** — drop both
> keys when this object moves into `default/jobs.yml`. See *Hand-off: from standalone
> collector to a Pack* at the end of this skill.

```json
{
  "id": "<unique-collector-id>",
  "type": "collection",
  "description": "<what this collector does>",
  "ttl": "4h",
  "removeFields": [],
  "resumeOnBoot": false,
  "streamtags": [],
  "workerAffinity": false,
  "schedule": {
    "cronSchedule": "*/5 * * * *",
    "maxConcurrentRuns": 1,
    "skippable": true,
    "enabled": false,
    "run": {
      "rescheduleDroppedTasks": true,
      "maxTaskReschedule": 1,
      "logLevel": "info",
      "jobTimeout": "60m",
      "mode": "run",
      "timeRangeType": "relative",
      "earliest": "-5m@m",
      "latest": "now",
      "expression": "true",
      "minTaskSize": "1MB",
      "maxTaskSize": "10MB",
      "stateTracking": {
        "enabled": false,
        "stateUpdateExpression": "__timestampExtracted !== false && {latestTime: (state.latestTime || 0) > _time ? state.latestTime : _time}",
        "stateMergeExpression": "(prevState.latestTime || 0) > newState.latestTime ? prevState : newState"
      }
    }
  },
  "collector": {
    "type": "rest",
    "destructive": false,
    "encoding": "utf8",
    "conf": {
      "discovery": { ... },
      "collectUrl": "<JS expression — single-quoted string or template literal>",
      "collectMethod": "get|post|post_with_body|other",
      "collectBody": "<JS template literal for POST body>",
      "collectRequestParams": [ {"name": "...", "value": "..."} ],
      "collectRequestHeaders": [ {"name": "...", "value": "..."} ],
      "pagination": { ... },
      "authentication": "none|basic|basicSecret|login|loginSecret|oauth|oauthSecret|google_oauth|google_oauthSecret|hmac",
      "timeout": 0,
      "useRoundRobinDns": false,
      "disableTimeFilter": false,
      "decodeUrl": true,
      "rejectUnauthorized": true,
      "captureHeaders": false,
      "safeHeaders": [],
      "retryRules": { ... },
      "loginUrl": "<JS expression>",
      "loginBody": "<JS template literal>",
      "tokenRespAttribute": "<dot-path to token in response>",
      "authHeaderKey": "Authorization",
      "authHeaderExpr": "`Bearer ${token}`",
      "credentialsSecret": "<secret-id>",
      "clientSecretParamName": "client_secret",
      "clientSecretParamValue": "<secret>",
      "authRequestParams": [ {"name": "...", "value": "..."} ],
      "authRequestHeaders": [ {"name": "...", "value": "..."} ]
    }
  },
  "input": {
    "type": "collection",
    "staleChannelFlushMs": 10000,
    "sendToRoutes": true,
    "preprocess": { "disabled": true },
    "throttleRatePerSec": "0",
    "breakerRulesets": ["<breaker-ruleset-id>"],
    "metadata": [ {"name": "...", "value": "..."} ]
  },
  "savedState": {}
}
```

---

## Discovery Configuration

```json
// No discovery (single endpoint)
"discovery": { "discoverType": "none" }

// HTTP Request discovery
"discovery": {
  "discoverType": "http",
  "discoverUrl": "'https://api.example.com/resources'",
  "discoverMethod": "get",
  "discoverRequestParams": [ {"name": "...", "value": "..."} ],
  "discoverRequestHeaders": [ {"name": "...", "value": "..."} ],
  "discoverDataField": "items",
  "pagination": { "type": "none", "maxPages": 50 }
}

// Item List discovery
"discovery": {
  "discoverType": "list",
  "itemList": ["item1", "item2", "item3"]
}

// JSON Response discovery
// The field is manualDiscoverResult, NOT discoverResult, and it is required.
"discovery": {
  "discoverType": "json",
  "manualDiscoverResult": { "items": [{"id": "a"}, {"id": "b"}] },
  "discoverDataField": "items"
}
```

`discoverType` is an enum: `none | http | json | list`. Required companions per
branch — `http`: `discoverUrl` + `discoverMethod`; `list`: `itemList`; `json`:
`manualDiscoverResult`. Discovery has its own nested `pagination` object using
the same six `type` values as Collect (see below).

---

## Pagination Configuration

> **The `type` value is an enum with exactly six members.** Anything else fails
> validation. In a Pack the failure surfaces on install as the useless
> `failed to install: should be equal to one of the allowed values`; in the
> Collector UI it is a red Save. Note that the stored value often does **not**
> match the UI label — "RFC 5988" is `response_header_link`, "Offset/Limit" is
> `request_offset`, "Page/Size" is `request_page`.
>
> | UI label | `type` value |
> |---|---|
> | None | `none` |
> | Response Body Attribute | `response_body` |
> | Response Header Attribute | `response_header` |
> | RFC 5988 – Web Linking | `response_header_link` |
> | Offset/Limit | `request_offset` |
> | Page/Size | `request_page` |
>
> Verify against the schema shipped in any Cribl install rather than guessing:
> `jq '.properties.pagination' $CRIBL_HOME/default/cribl/collectors/rest/conf.schema.json`

```json
// No pagination
"pagination": { "type": "none" }

// Response Body Attribute (next URL or cursor token)
// required: attribute, maxPages
"pagination": {
  "type": "response_body",
  "attribute": ["next"],
  "maxPages": 0,
  "lastPageExpr": ""
}

// Response Header Attribute
// required: attribute, maxPages
"pagination": {
  "type": "response_header",
  "attribute": ["Link"],
  "maxPages": 50
}

// RFC 5988 Web Linking
// required: nextRelationAttribute, maxPages
"pagination": {
  "type": "response_header_link",
  "nextRelationAttribute": "next",
  "curRelationAttribute": "",
  "maxPages": 50
}

// Offset/Limit
// required: offsetField, limitField, limit, maxPages, zeroIndexed
"pagination": {
  "type": "request_offset",
  "offsetField": "offset",
  "offset": 0,
  "limitField": "limit",
  "limit": 100,
  "totalRecordField": "total",
  "maxPages": 0,
  "zeroIndexed": true
}

// Page/Size
// required: pageField, sizeField, size, maxPages, zeroIndexed
"pagination": {
  "type": "request_page",
  "pageField": "page",
  "page": 1,
  "sizeField": "size",
  "size": 100,
  "totalPageField": "totalPages",
  "totalRecordField": "totalRecords",
  "maxPages": 0,
  "zeroIndexed": false
}
```

**`request_offset` / `request_page` record limits are static numbers, not
expressions.** `limit` and `size` have no `jsExpression` flag in the schema, so
`C.vars[...]` will not be evaluated there — bake the literal in, and expose the
tunable only on collectors that pass the limit as a request parameter instead.

---

## Authentication Configuration

### None (API key in headers)
```json
"authentication": "none",
"collectRequestHeaders": [
  {"name": "Authorization", "value": "'Bearer <API_KEY>'"},
  {"name": "Content-Type", "value": "'application/json'"}
]
```

### Basic Auth
```json
"authentication": "basic",
"username": "<username>",
"password": "<password>"
```

### Basic Auth with Credentials Secret
```json
"authentication": "basicSecret",
"credentialsSecret": "<secret-id>"
```

### Login (POST for token)
```json
"authentication": "login",
"loginUrl": "'https://api.example.com/auth/token'",
"loginBody": "`client_id=${username}&client_secret=${password}`",
"tokenRespAttribute": "access_token",
"authHeaderKey": "Authorization",
"authHeaderExpr": "`Bearer ${token}`",
"authRequestHeaders": [
  {"name": "Content-Type", "value": "'application/x-www-form-urlencoded'"}
]
```

### Login with Credentials Secret
```json
"authentication": "loginSecret",
"loginUrl": "'https://api.example.com/auth/token'",
"loginBody": "`client_id=${username}&client_secret=${password}`",
"credentialsSecret": "<secret-id>",
"tokenRespAttribute": "access_token",
"authHeaderKey": "Authorization",
"authHeaderExpr": "`Bearer ${token}`",
"authRequestHeaders": [
  {"name": "Content-Type", "value": "'application/x-www-form-urlencoded'"}
]
```

### OAuth (Client Credentials)
```json
"authentication": "oauth",
"loginUrl": "'https://api.example.com/oauth/token'",
"clientSecretParamName": "client_secret",
"clientSecretParamValue": "<secret>",
"authRequestParams": [
  {"name": "client_id", "value": "'<client-id>'"},
  {"name": "grant_type", "value": "'client_credentials'"}
],
"tokenRespAttribute": "access_token",
"authHeaderKey": "Authorization",
"authHeaderExpr": "`Bearer ${token}`"
```

### OAuth with Text Secret
```json
"authentication": "oauthSecret",
"loginUrl": "'https://api.example.com/oauth/token'",
"clientSecretParamName": "client_secret",
"clientSecretParamValue": "<secret-id>",
"authRequestParams": [
  {"name": "client_id", "value": "'<client-id>'"},
  {"name": "grant_type", "value": "'client_credentials'"}
],
"tokenRespAttribute": "access_token",
"authHeaderKey": "Authorization",
"authHeaderExpr": "`Bearer ${token}`"
```

---

## Retry Configuration

```json
"retryRules": {
  "type": "backoff",
  "interval": 1000,
  "limit": 5,
  "multiplier": 2,
  "maxIntervalMs": 20000,
  "codes": [429, 503],
  "enableHeader": true,
  "retryConnectTimeout": false,
  "retryConnectReset": false,
  "retryHeaderName": "retry-after"
}
```

---

## Event Breaker JSON Schema

The `breaker.json` defines how raw API responses are broken into individual events:

```json
{
  "id": "<breaker-ruleset-id>",
  "lib": "custom",
  "rules": [
    {
      "condition": "<JS expression — when to apply this rule>",
      "type": "json_array|json|ndjson|regex|csv|timestamp",
      "name": "<rule-name>",
      "timestampAnchorRegex": "/<regex>/",
      "timestamp": {
        "type": "auto|format|current",
        "length": 150,
        "format": "<strptime format>"
      },
      "timestampTimezone": "utc|local",
      "timestampEarliest": "-420weeks",
      "timestampLatest": "+1week",
      "maxEventBytes": 51200,
      "disabled": false,
      "jsonExtractAll": true,
      "jsonArrayField": "<dot.path.to.array>",
      "jsonTimeField": "<field-containing-timestamp>",
      "cleanFields": true,
      "eventBreakerRegex": "/[\\n\\r]+(?!\\s)/"
    }
  ]
}
```

### Common Event Breaker Patterns

**JSON Array** (most REST APIs return `{"data": [...]}` or `{"items": [...]}`):
```json
{
  "condition": "true",
  "type": "json_array",
  "jsonArrayField": "data",
  "jsonExtractAll": true,
  "jsonTimeField": "timestamp",
  "timestamp": { "type": "auto", "length": 150 },
  "timestampTimezone": "utc",
  "maxEventBytes": 51200,
  "name": "api_events"
}
```

**NDJSON** (one JSON object per line):
```json
{
  "condition": "true",
  "type": "ndjson",
  "jsonExtractAll": true,
  "timestamp": { "type": "auto", "length": 150 },
  "maxEventBytes": 51200,
  "name": "ndjson_events"
}
```

**Whole response as single event** (no array, response IS the event):
```json
{
  "condition": "true",
  "type": "json",
  "jsonExtractAll": true,
  "timestamp": { "type": "current" },
  "maxEventBytes": 512000,
  "name": "single_event"
}
```

---

## JavaScript Expression Rules

All URL, parameter, header, and body `value` fields follow these rules:

1. **Static strings** use single quotes: `'https://api.example.com/v1/events'`
2. **Dynamic values** use backtick template literals: `` `${variable}` ``
3. **Available variables in Collect fields:**
   - `${earliest}` / `${latest}` — job time range (epoch seconds)
   - `${authToken}` — token from Login/OAuth auth
   - `${id}` — current item from Item List / HTTP discovery
   - `${<field>}` — any field from the discovery result object
   - `state.<key>` — saved state from previous runs
4. **Available variables in Login body:**
   - `${username}` / `${password}` — credentials
5. **Available in pagination context:**
   - Any attribute name from the response (e.g., `${cursor}`, `${next_stream_position}`)
6. **Encode unsafe URL characters:** `C.Encode.uri(\`\${variable}\`)`
7. **Time formatting:** `C.Time.strftime(earliest, '%Y-%m-%dT%H:%M:%SZ')`
8. **Secrets:** `C.Secret('secret-name')`

---

## State Tracking Patterns

### Track latest timestamp (most common)
```json
"stateTracking": {
  "enabled": true,
  "stateUpdateExpression": "__timestampExtracted !== false && {latestTime: (state.latestTime || 0) > _time ? state.latestTime : _time}",
  "stateMergeExpression": "(prevState.latestTime || 0) > newState.latestTime ? prevState : newState"
}
```
Reference in Collect params: `` `${state.latestTime * 1000}` `` or `` `${C.Time.strftime(state.latestTime || earliest, '%Y-%m-%dT%H:%M:%SZ')}` ``

### Track cursor/offset per discovered item
```json
"stateTracking": {
  "enabled": true,
  "stateUpdateExpression": "__timestampExtracted !== false && { id: __collectible.id, latestTime: (state[__collectible.id]?.latestTime || 0) > _time ? state[__collectible.id].latestTime : _time }",
  "stateMergeExpression": "Object.assign({}, prevState, { [newState.id]: (prevState[newState.id]?.latestTime || 0) > newState.latestTime ? prevState[newState.id] : newState })"
}
```

---

## Scheduling Recommendations

| API Rate Limit | Recommended Cron | Notes |
|---|---|---|
| No documented limit | `*/5 * * * *` (every 5 min) | Start conservative, increase frequency after testing |
| 60 req/min | `*/5 * * * *` | Safe for paginated collection |
| 10 req/min | `*/15 * * * *` | Account for pagination requests |
| 100 req/day | `0 */4 * * *` (every 4 hours) | 6 runs/day leaves room for retries |
| Near real-time needed | `* * * * *` (every minute) | Only if API supports it and state tracking is enabled |

---

## Output Rules

1. **Always use `loginSecret` or `oauthSecret`** over plain `login`/`oauth` when building production configs — remind the user to create a Cribl text secret
2. **Always include retry rules** — most APIs return 429s under load
3. **Set `rejectUnauthorized: true`** unless the user explicitly needs self-signed cert support
4. **Set `disableTimeFilter: false`** unless the API has no time-based filtering
5. **Default `maxPages: 0`** (unlimited) unless the API has known issues with deep pagination
6. **Include `description`** explaining what the collector does and which API endpoint it targets
7. **Name the breaker ruleset** after the technology: `<Technology>_Events_Breaker`
8. **Use placeholder markers** for secrets: `<INSERT_API_KEY>`, `<INSERT_CLIENT_ID>`, `<INSERT_CLIENT_SECRET>`
9. **Include sensible streamtags** that identify the technology: `["vendor:<name>", "type:api"]`
10. **Validate the `conf` against Cribl's own schema before handing it over** — see below. Never guess an enum value.

---

## Validate Before Handing It Over

Every Cribl install ships the collector and Function JSON Schemas on disk. Use
them instead of trusting this document or your memory:

```bash
CRIBL_HOME=${CRIBL_HOME:-/opt/cribl}          # or ~/cribl on a tarball install

# All enums in the REST collector conf, with their JSON pointers:
python3 - "$CRIBL_HOME" <<'PY'
import json, sys
s = json.load(open(f'{sys.argv[1]}/default/cribl/collectors/rest/conf.schema.json'))
def walk(n, p=''):
    if not isinstance(n, dict): return
    if 'enum' in n: print(f'{p}: {n["enum"]}')
    for k, v in n.items():
        if k in ('properties', 'definitions', 'dependencies'):
            for kk, vv in v.items(): walk(vv, f'{p}.{kk}')
        elif k == 'items': walk(v, p + '[]')
        elif k in ('allOf', 'anyOf', 'oneOf'):
            for i, vv in enumerate(v): walk(vv, f'{p}|{i}')
        elif k in ('then', 'else', 'not'): walk(v, p)
walk(s)
PY
```

And validate the finished config:

```bash
python3 -m pip install --user jsonschema
python3 - collector.json <<'PY'
import json, sys, os
from jsonschema import Draft7Validator
home = os.environ.get('CRIBL_HOME', '/opt/cribl')
conf = json.load(open(sys.argv[1]))['collector']['conf']
v = Draft7Validator(json.load(open(f'{home}/default/cribl/collectors/rest/conf.schema.json')))
bad = 0
for e in sorted(v.iter_errors(conf), key=lambda e: list(e.absolute_path)):
    bad += 1
    print('/'.join(map(str, e.absolute_path)) or '<root>', '|', e.validator, '|', e.message)
    for sub in e.context or []:   # oneOf failures are useless without these
        print('   ->', '/'.join(map(str, sub.absolute_path)), '|', sub.validator, '|', sub.message)
print('clean' if not bad else f'{bad} violation(s)')
PY
```

Same trick for pipeline Functions:
`$CRIBL_HOME/default/cribl/functions/<function-id>/conf.schema.json`. A missing
directory means the Function id does not exist.

### The job wrapper, breakers and vars are on disk too — in the OpenAPI spec

`collectors/<type>/conf.schema.json` only covers `collector.conf`. Everything
*around* it — the `schedule` / `run` / `input` wrapper, Event Breaker rulesets,
Variables, Routes, samples — lives in the gzipped OpenAPI spec that ships with
the UI:

```bash
python3 - <<'PY'
import gzip, json, os
home = os.environ.get('CRIBL_HOME', '/opt/cribl')
spec = json.load(gzip.open(f'{home}/default/ui/static/swagger/openapi.json.gz'))
s = spec['components']['schemas']
for name in ('SavedJobCollection', 'EventBreakerRuleset', 'GlobalVar', 'Routes', 'DataSample'):
    print(name, '-> required:', s[name].get('required'))

# Most of the interesting fields sit behind $ref + allOf, so flatten as you go.
def props(node, depth=0):
    if depth > 8 or not isinstance(node, dict):
        return {}
    if '$ref' in node:
        return props(s[node['$ref'].split('/')[-1]], depth + 1)
    out = dict(node.get('properties') or {})
    for sub in node.get('allOf', []):
        out.update(props(sub, depth + 1))
    return out

run = props(s['RunSettingsTypeSavedJobCollectionSchedule'])
for k in ('mode', 'timeRangeType', 'earliest', 'latest'):
    print(k, '->', run[k].get('type'))
PY
```

On Cribl 4.15 that last loop prints:

```
mode -> string
timeRangeType -> string
earliest -> number      # <- not string
latest -> number        # <- not string
```

This is where you learn things that are otherwise invisible until a pack breaks:

> ⚠ **`schedule.run.earliest` / `latest` are typed as NUMBERS (epoch seconds)** in
> `SavedJobCollection`. The Collector UI happily saves the relative-time strings
> from the *Collector JSON Schema* section (`"-5m@m"`, `"now"`) on a **standalone**
> collector, and that works. Move the same object into a **Pack**'s
> `default/jobs.yml` and the strings fail AJV validation *on load* — the pack
> stays registered but unloaded and every Pack API call then throws
> `Cannot read properties of undefined (reading 'handleClusterCall')`, taking out
> the whole Packs UI. Inside a pack: omit both keys, keep
> `timeRangeType: relative`, and build the window in `collectRequestParams`
> instead (see the Pack hand-off section below).

---

## Hand-off: from standalone collector to a Pack

A single collector is a paste into one Worker Group. To ship a **set** of
collectors plus their breaker, pipelines and variables as one installable unit,
they go into a Pack — and Collectors in a Pack live in `default/jobs.yml`, not
`inputs.yml`.

The conversion is mechanical: the map key IS the `id`, and the `id` key is
dropped.

```yaml
# default/jobs.yml  — the same object you just built, minus "id"
in_vendor_events:
  type: collection
  ttl: 4h
  schedule:
    enabled: false          # ALWAYS ship disabled
    cronSchedule: "*/5 * * * *"
    run:
      mode: run
      timeRangeType: relative
      # no earliest/latest — see the warning above
      stateTracking: { enabled: true, ... }
  collector:
    type: rest
    conf: { ... }           # verbatim
  input:
    type: collection
    sendToRoutes: true
    breakerRulesets: ['Vendor Ruleset']     # matched BY NAME
    pipeline: vendor_parse                  # a pack-internal pipeline
    output: default
    metadata:
      - name: __packsource
        value: "'<pack-id>.<logical-source>'"   # what route.yml filters on
```

Do not do this by hand — the `cribl-stream-packs` skill ships the converter and
the validator:

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/cribl-stream-packs/scripts"
python3 "$S/pack-json-to-yaml.py" --pack ~/my-pack --write collector.json breaker.json
python3 "$S/pack-validate.py"     --pack ~/my-pack
python3 "$S/pack-yaml-to-json.py" --pack ~/my-pack      # render back out to debug
```

**Build and debug the collector standalone first, always.** A Collector inside a
Pack cannot be run from the Pack UI — it needs a Worker Group **Commit & Deploy**
before it will fire even once, so iterating there costs an upload, install,
commit and deploy per change. At group level you get **Run → Preview**: one
request, broken-out events, nothing written downstream.

See the `cribl-stream-packs` skill §6.7 for the full JSON ⇄ pack-YAML mapping
(pipelines are the one artifact that changes nesting) and §6.1b for the
`jobs.yml` conventions.

---

## Import Instructions Template

After generating the files, provide these import instructions:

### Method 1: JSON Import (recommended)
1. In Cribl Stream, go to **Data → Sources → Collectors → REST/API**
2. Click **Add Collector**
3. Switch to the **Configure as JSON** tab
4. Paste the `collector.json` content
5. Click **Save**

### Method 2: Event Breaker Import
1. Go to **Processing → Knowledge → Event Breaker Rules**
2. Click **Add Ruleset**
3. Switch to **Configure as JSON**
4. Paste the `breaker.json` content
5. Click **Save**

### Method 3: File Import
1. Save both files to a directory
2. Go to **Manage → Collector Templates**
3. Import from file

---

## Reference: Cribl Collector Templates Repository

Official collector templates for reference: https://github.com/criblio/collector-templates/tree/main/collectors/rest

Known templates (64+ technologies): 1Password, Abnormal Security, Akamai SIEM, AlienVault, AlphaSOC, Atlassian (Confluence/Jira audit), Boomi, Box, Carbon Black, Code42, CrowdStrike (alerts, detections, devices, vulnerabilities), Cribl internal metrics/logs, and many more.

When building a collector for a technology that has an existing template, fetch it from the repository as a starting point:
```
gh api repos/criblio/collector-templates/contents/collectors/rest/<template>/collector.json --jq '.content' | base64 -d
```

---

## Cribl REST Collector Documentation

Full docs reference: https://docs.cribl.io/stream/usecase-rest/
Use-case walkthrough: https://docs.cribl.io/stream/usecase-rest/#using-restapi-collectors
Collector templates repo: https://github.com/criblio/collector-templates
