---
name: cribl-stream-packs
description: "Build and modify Cribl Stream Packs — file layout, pipeline YAML schemas, function allowlists, routes, sources/destinations, OCSF/CIM/CSL normalization, samples, packaging (gtar), API deploy (upload→install|upgrade→commit→deploy), vars.yml schema (no wrapping vars: key, lib:custom), expression vs static fields, JSON⇄YAML conversion for collector packs, offline validation against a real Cribl install, and battle-tested quirks. (v7 — JSON⇄pack-YAML conversion + scripts/pack-validate.py)"
argument-hint: "describe the pack you want to build or modify"
desktop: degraded
desktop-note: "The reference material works as-is; the scripts/ helpers (pack-validate.py, JSON⇄YAML conversion, gtar packaging) need a shell, so run those in Claude Code."
---

# Building & Modifying Cribl Stream Packs

> **Pack vs App — intent check:** If the user is building a **Cribl Stream Pack** (portable config bundle: pipelines, routes, functions, knowledge objects for cribl stream), use this skill. If they're building a **Cribl App** (run custom applications embedded directly in Cribl), use the app skills from the `app-creation` plugin (`app-creation:app-questions`, `app-creation:app-brief`, `app-creation:app-implement`) instead. When the user says "pack" early in the conversation, go straight to this skill — do not invoke the app-definition workflow.

Authoritative working agreement for operating inside a Cribl Stream Pack repository. Follow this document before touching any file. It encodes file layout, schemas, conventions, validation rules, and the end‑to‑end workflow used to ship a Pack from a local repo back into a Cribl Stream Worker Group.

> Always reason in small steps, ground every change in real Cribl YAML/JSON, and never invent function names, fields, or destination types — only use those listed in the references at the bottom.

---

## 1. What a Cribl Stream Pack Is

A Pack is a self‑contained, portable bundle of Cribl Stream configuration: Routes, Pipelines (with Functions), Sources, Destinations, Event Breakers, knowledge objects (lookups, parsers, regexes, schemas, grok, vars), sample data, README, and metadata. It is distributed as a `.crbl` file, which is just a `gzip`‑compressed `tar` archive (`tar.gz`). Packs created in Cribl Stream 4.0+ are forward‑compatible only with 4.0+.

You may both **create** new Packs and **modify** existing ones (typically downloaded from the Cribl Packs Dispensary at https://packs.cribl.io or the GitHub mirror https://github.com/criblpacks).

---

## 2. Pack File Structure (canonical)

After `tar -xvf <pack>.crbl`, the working tree looks like this. Every directory listed must exist as an explicit tar entry (otherwise import on older Cribl versions fails).

```
<pack-id>/
├── package.json                         # REQUIRED — pack manifest (npm-style)
├── README.md                            # REQUIRED — user-facing docs
├── logo.png | logo.jpg                  # OPTIONAL — ≤2 MB, 280×50 px recommended
├── default/                             # REQUIRED — original/baked configs
│   ├── pack.yml                         # Pack identity + display info
│   ├── inputs.yml                       # Sources defined in the pack (optional)
│   ├── jobs.yml                         # Collectors (REST, S3, …) in the pack (optional)
│   ├── outputs.yml                      # Destinations defined in the pack (optional)
│   ├── breakers.yml                     # Custom Event Breakers (optional)
│   ├── samples.yml                      # Index of sample files
│   ├── vars.yml                         # Pack-scoped Global Variables
│   ├── regexes.yml                      # Regex Library entries
│   ├── parsers.yml                      # Parser Library entries
│   ├── schemas.yml                      # JSON/Parquet schema refs
│   ├── grok-patterns/                   # one file per pattern set (optional)
│   ├── lookups/                         # *.yml descriptors for lookup files
│   └── pipelines/
│       ├── route.yml                    # Pack-internal Routes table
│       └── <pipeline-id>/
│           └── conf.yml                 # Pipeline definition (functions array)
├── data/
│   ├── samples/                         # *.json / *.ndjson / *.log sample files
│   └── lookups/                         # *.csv / *.mmdb lookup data
└── local/                               # OPTIONAL — user overlays (created by UI)
```

Rules the agent MUST respect:

- **Never delete `default/`**. It is the “factory” layer. User edits live in `local/` (managed by the Cribl UI). When editing locally, modify `default/` only — that is the source of truth committed to Git.
- **Every Pipeline is its own subdirectory** under `default/pipelines/<pipeline-id>/conf.yml`. The directory name IS the pipeline ID.
- **Pack-level Routes** live in `default/pipelines/route.yml` (note: file is named `route.yml`, not `routes.yml`).
- **Sample files** are referenced by entries in `default/samples.yml` and stored under `data/samples/`. If you add a sample you MUST add an entry to `samples.yml` AND set `isPackOnly: true` so it ships with the pack.
- **Lookup CSVs** live in `data/lookups/<name>.csv` and need a matching `default/lookups/<name>.csv.yml` descriptor. Avoid huge lookups (Git size limits) — use env vars or absolute paths for very large files.
- **TLS cert and secret material is stripped on export.** Never check secrets, private keys, or certificate bodies into the repo. Reference them by name only.

---

## 3. Manifest Files

### 3.1 `package.json`
Cribl uses npm‑style metadata. Minimum required keys:

```json
{
  "name": "<pack-id>",
  "version": "1.0.0",
  "description": "Short one-line description shown in the dispensary",
  "author": "Your Name <you@company.com>",
  "license": "Apache-2.0",
  "keywords": ["fortinet", "firewall", "cim", "reduction"],
  "engines": { "cribl": ">=4.0.0" }
}
```

- `name` MUST equal the top-level pack directory and the `id` in `pack.yml`. Allowed: `[a-z0-9_-]+`. Lowercase, no spaces.
- Bump `version` (semver) on EVERY change. Cribl decides whether to upgrade based on this field when pulling from Git.

### 3.2 `default/pack.yml`

```yaml
id: <pack-id>                   # MUST match package.json "name"
displayName: Human Readable Name
version: 1.0.0                  # mirror package.json; both must agree
author: Your Name
description: |
  Multi-line description. Markdown is OK.
minStreamVersion: 4.0.0         # optional; lowest compatible Cribl Stream
dataTypes:   [logs, metrics]    # optional taxonomy used by the Dispensary
useCases:    [reduction, normalization, routing]
technologies:[fortinet, syslog]
tags:        [internal, prod]
```

### 3.3 `README.md`
Required for any Pack you intend to share. Follow the Packs Publication Standard. Sections to include:

1. **Overview** — what the pack does and why.
2. **Prerequisites** — Cribl Stream version, upstream/downstream systems, lookups required.
3. **What’s included** — Routes, Pipelines, Sources, Destinations, knowledge objects.
4. **Configuration** — Variables (`vars.yml`) the user must set, sample-data assumptions (e.g., expected `sourcetype`, `__inputId`, etc.).
5. **Usage** — how to wire it into a Route or attach to a Source/Destination as a pre/post‑processing pipeline.
6. **Validation** — sample input → expected output (paste short JSON snippets).
7. **Limitations & Known Issues**.
8. **Changelog** keyed by version.

---

## 4. Pipeline Schema (`default/pipelines/<id>/conf.yml`)

Pipelines are an ordered array of Functions executed top‑to‑bottom on every event that matches the Pipeline’s upstream filter.

```yaml
output: default                 # Default downstream output (rare in packs)
streamtags: []
groups: {}                      # Function group UI metadata (optional)
asyncFuncTimeout: 1000
description: One-line pipeline description
functions:
  - id: comment
    filter: 'true'
    disabled: false
    conf:
      comment: |
        Purpose, author, ticket. Always start a pipeline with a Comment block.
  - id: eval
    filter: "sourcetype=='fortigate'"
    description: Normalize Fortinet field names to Splunk CIM
    conf:
      add:
        - name: vendor
          value: "'Fortinet'"
        - name: product
          value: "'FortiGate'"
        - name: src_ip
          value: srcip
        - name: dest_ip
          value: dstip
      remove: ['srcip','dstip']
  - id: regex_extract
    filter: "_raw && _raw.startsWith('date=')"
    conf:
      regex: '/(?<key>\w+)=("(?<qval>[^"]*)"|(?<val>\S+))/g'
      source: _raw
  - id: drop
    filter: "action=='deny' && severity=='informational'"
    final: true
```

### Mandatory function record fields
| Key | Purpose |
|---|---|
| `id` | The Function’s built‑in identifier (see allowlist below). |
| `filter` | JS expression returning truthy to apply this Function. Default `'true'`. |
| `disabled` | `true` to keep config but skip execution. |
| `final` | When `true`, events that pass this Function are not handed to subsequent Functions. |
| `description` | Free‑form, human‑readable. STRONGLY encouraged on every Function. |
| `conf` | Function‑specific configuration object — schema differs per Function. |

### Allowlisted Function `id` values (Cribl Stream 4.17)
`aggregations`, `aggregate_metrics`, `auto_timestamp`, `cef_serializer`, `chain`, `clone`, `code`, `comment`, `dns_lookup`, `drop`, `drop_dimensions`, `dynamic_sampling`, `eval`, `event_breaker`, `flatten`, `fold_keys`, `geoip`, `grok`, `guard`, `json_unroll`, `lookup`, `mask`, `numerify`, `otlp_logs`, `otlp_metrics`, `otlp_traces`, `parser`, `publish_metrics`, `redis`, `regex_extract`, `regex_filter`, `rename`, `rollup_metrics`, `sampling`, `serde`, `serialize`, `snmp_trap_serialize`, `suppress`, `tee`, `unroll`, `xml_unroll`, `windows_sid_lookup`.

> Two Functions handle structured parsing and they have **different YAML schemas** — do not mix them up (we hit this bug in §15):
> - `parser` — the **Parser** Function. Uses a Parser Library entry (`lib`, `type`, `srcField`, `destField`, `fields`). Best when you want to declare reusable parsing logic at Library level.
> - `serde` — the **Serialize/Deserialize** Function. KVP / JSON / CSV / ELFF in/out via `mode: extract|serialize`, `type`, `srcField`, `cleanFields`, `allowedKeyChars`, `allowedValueChars`. Best for inline KVP extraction (e.g., FortiGate, Cisco ASA).

**Do not invent IDs.** If the desired transform isn’t in this list, use `code` (JavaScript) or `eval` with a Cribl Expression (`C.*`).

### Expression fields vs static config fields

Not every `conf` key accepts `C.vars.*` or JS. Mixing them up fails silently or errors at save time.

| Kind | What it accepts | Examples |
|---|---|---|
| **Expression fields** | JS expressions, `C.vars.*`, template literals, field refs | `filter`, Eval `add[].value` / `remove`, Rename/Mask field expressions, Aggregations `aggregations[].expression` / `groupBy` |
| **Static config fields** | Literals only (number / boolean / string) set at pipeline save time — **no** runtime evaluation | Aggregations: `timeWindow`, `passthrough`, `metricsMode`, `cumulative`, `flushOnInputClose`, `sufficientStatsOnly` |

> **Gotcha:** `C.vars.TZ_METRIC_WINDOW_SECONDS` in Aggregations `timeWindow` does **not** work — `timeWindow` is a static numeric config field. Bake the literal (e.g. `timeWindow: 60`) into the pipeline YAML; expose tunables only via expression-capable fields.

### Aggregations (`id: aggregations`) — static vs expression

```yaml
- id: aggregations
  filter: "true"
  conf:
    timeWindow: 60              # STATIC number — not an expression; no C.vars.*
    aggregations:
      - aggOp: count
        expression: "true"      # expression-capable
    groupBy: ["host"]           # expression-capable field list
    passthrough: false          # STATIC boolean
    metricsMode: false          # STATIC boolean
    cumulative: false           # STATIC boolean
    flushOnInputClose: true     # STATIC boolean
    sufficientStatsOnly: false  # STATIC boolean
```

Use pack variables for thresholds/filters that live in Eval/`filter` expressions; keep window size and Aggregations toggles as literals (or document them as install-time pipeline edits).

### Event field access
- The current event is the special variable `__e`.
- Use bracket notation for non‑alphanumeric or nested fields: `__e['kubernetes.namespace_name']`, `__e['user-agent']`.
- Internal fields start with `__` (e.g., `__inputId`, `__srcIpPort`, `__channel`). Do not remove them with wildcards; specify by name if removal is required.
- Cribl supports ECMAScript 2015. Regex flavor is JavaScript (test on https://regex101.com with the ECMAScript flavor).

---

## 5. Routes (`default/pipelines/route.yml`)

Routes are evaluated in order. Each row binds a JS filter expression to a Pipeline and an output, with an optional `final` flag (defaults to `true` — only one matching Route fires unless toggled off to clone).

```yaml
id: default                       # the Routes DOC has an id; keep it `default`
groups: {}
comments:
  # STRUCTURED objects, not strings. `index` is REQUIRED by Cribl's
  # RouteComment schema — the 0-based position of the Route it is pinned above.
  - id: routing_note
    index: 0
    comment: |
      Why these Routes are ordered this way.
routes:
  - id: route-fortigate-traffic
    name: Fortigate Traffic
    final: true
    disabled: false
    pipeline: fortigate_traffic_cim
    description: Normalize traffic logs to Splunk CIM Network_Traffic
    enableOutputExpression: false
    outputExpression: null
    filter: "sourcetype=='fortigate' && subtype=='traffic'"
    clones: []
    targetContext: group          # hand the event back to the Worker Group
    output: __group
  - id: default
    name: default
    final: true
    disabled: false
    pipeline: passthru            # REQUIRED — see the no-op note below
    description: Pass-through for everything this pack does not shape.
    enableOutputExpression: false
    outputExpression: null
    filter: "true"
    clones: []
    targetContext: group
    output: __group
```

Notes:
- `pipeline` MUST match an existing directory under `default/pipelines/`, or be a Cribl built-in (`passthru`, `devnull`, `main`).
- **`pipeline` is REQUIRED by the `RouteConf` schema — you cannot omit it.** For a no-op catch-all use the built-in **`passthru`**. Do NOT use `devnull` (it discards the events) and do not leave the field empty or absent (AJV rejects the Route, which fails the whole pack load — see §15.T).
- **`output: __group` + `targetContext: group` is the portable Pack idiom**: it means "hand the event back to the Worker Group's own Routes and Destinations", so the installer chooses Splunk / S3 / Cribl Lake / HTTP without editing the pack. Use a Destination id from `default/outputs.yml` only when the pack genuinely owns its egress. `output: default` refers to the *Worker Group's* default Destination and is the less portable choice.
- Give every Route the **full field set** — `id, name, final, disabled, pipeline, description, enableOutputExpression, outputExpression, filter, clones, targetContext, output`. Partially-specified Routes are a common source of silent load failures.
- Disable a Route during dev with `disabled: true`, never by deleting it. Shipping a shaping Route **disabled** and gating it on a variable as well makes "turn on OCSF output" a deliberate two-step, which is the right default for a pack someone else installs.
- Routes are the one artifact that does **not** round-trip to a standalone Worker Group config — `__group` / `targetContext` only mean something inside a Pack. See §6.7.

---

## 6. Sources, Destinations, Breakers, Samples, Vars

### 6.1 `default/inputs.yml` (Sources in Pack)
One source per port. Multiple instances of the same Source type require unique ports. Example syslog source:

```yaml
inputs:
  in_syslog_fortigate:
    type: syslog
    disabled: false
    port: 9514
    protocol: udp
    host: 0.0.0.0
    pqEnabled: false
    streamtags: ['fortigate']
    description: Fortinet FortiGate syslog ingest
    connections:
      - pipeline: 'pack:fortigate_pre'   # optional pre-processing pipeline
        output: default
```

Naming convention enforced by Cribl at runtime: `source.<pack_name>.<source_name>`.

Unsupported in Packs (do NOT add to `inputs.yml`): System Metrics, System State, Cribl Internal.

### 6.1b `default/jobs.yml` (Collectors in Pack)

**Collector-based Sources DO ship in Packs — they just do not live in `inputs.yml`.** They go in `default/jobs.yml`, keyed by collector id. Cribl's own `cribl-akamai-rest-io` pack is built this way, and packs whose id ends in `-io` are usually Collector + Destination bundles.

Each entry is the standalone collector JSON **minus the `id` key** (the YAML key IS the id), converted to YAML. `scripts/pack-json-to-yaml.py` does that conversion for you — see §6.7.

```yaml
in_vendor_events:
  type: collection
  ttl: 4h
  description: What this collects and from which endpoint
  streamtags: [vendor]
  workerAffinity: false
  schedule:
    enabled: false                 # ship DISABLED; the installer opts in
    cronSchedule: "*/5 * * * *"
    maxConcurrentRuns: 1
    skippable: true
    resumeMissed: false
    run:
      mode: run
      timeRangeType: relative
      # NO earliest/latest here — see the box below. Build the window in
      # collectRequestParams instead.
      timestampTimezone: UTC
      stateTracking:
        enabled: true
        stateUpdateExpression: "..."
        stateMergeExpression: "..."
  collector:
    type: rest                     # see the cribl-rest-collector-builder skill
    destructive: false
    encoding: utf8
    conf: { ... }                   # validate this against Cribl's JSON Schema
  input:
    type: collection
    sendToRoutes: true
    breakerRulesets: ['<Ruleset name from default/breakers.yml>']
    pipeline: <pack-internal pre-processing pipeline id>
    output: default
    metadata:
      - name: __packsource
        value: "'<pack-id>.<logical-source-name>'"   # route on this in route.yml
  savedState: {}
  notifications: []
```

> ### ⚠ `schedule.run.earliest` / `latest` are NUMBERS in a Pack, not relative-time strings
>
> The Collector UI happily saves `earliest: "-15m"` / `latest: "now"` on a
> standalone collector. Cribl's **`SavedJobCollection`** schema — the one a Pack
> is validated against — types both as **numbers (epoch seconds)**. Ship the
> strings inside `jobs.yml` and the whole Pack fails AJV validation *on load*:
> it stays **registered but unloaded**, and every subsequent Pack API call throws
>
> ```
> Cannot read properties of undefined (reading 'handleClusterCall')
> ```
>
> which takes out the **entire Packs UI**, not just your pack. There is no error
> message that points at the field.
>
> **Fix:** omit both keys, leave `timeRangeType: relative`, and have each
> collector build its own window in `collectRequestParams` — first run looks back
> a fixed interval, every run after that resumes from `state.latestTime`:
>
> ```yaml
> collectRequestParams:
>   - name: start
>     value: "`${state && state.latestTime ? state.latestTime : Math.round(Date.now() / 1000) - 900}`"
>   - name: end
>     value: "`${Math.round(Date.now() / 1000)}`"
> ```
>
> This is how Cribl's own `cribl-akamai-rest-io` pack does it. `scripts/pack-validate.py`
> flags the string form; `scripts/pack-json-to-yaml.py` strips it on conversion.

Conventions that matter:

- **Ship `schedule.enabled: false`.** Installing a pack must never start collecting against someone's API budget.
- **Stamp `__packsource`** in `input.metadata` so `route.yml` can filter on `__packsource == '<pack-id>.<name>'`. This is the standard pack idiom.
- **Reference secrets, never embed them:** `` "`Token ${C.Secret('vendor_api_token').value}`" ``. Cribl strips secret material on export, so a committed literal is both a leak and a lie. Note the auth *scheme* word is vendor-specific — Juniper Mist wants `Token `, not `Bearer `; a wrong scheme renders fine and fails as a bare `401`.
- **Secrets are Worker Group scoped, not pack scoped.** The pack can only reference a secret by name; the installer must create it in the group the pack is deployed to. Say so in the README, with the exact name.
- **`input.pipeline`** names a pack-internal pipeline and runs before the pack Routes — the right place for `_time`, `sourcetype` and identity fields.
- **`input.pipeline` and `input.breakerRulesets` resolve BY NAME.** They are strings, not references — a typo is silently a no-op, not an error. `scripts/pack-validate.py` cross-checks both against what the pack actually contains.
- **You cannot test-run a Collector from the Pack UI.** Collector-based Sources in a Pack need a **Commit & Deploy** on the Worker Group before they will run at all, which makes the edit→test loop brutally slow. Render the collector to standalone JSON and iterate at group level instead — that is what §6.7 is for.
- **Validate `collector.conf`** against `$CRIBL_HOME/default/cribl/collectors/<type>/conf.schema.json` before building the `.crbl`. On install Cribl reports only the failing AJV keyword with no field path (e.g. `failed to install: should be equal to one of the allowed values`), which tells you nothing. `scripts/pack-validate.py` does this and prints the JSON pointer. See also the `cribl-rest-collector-builder` skill.

### 6.2 `default/outputs.yml` (Destinations in Pack)

```yaml
outputs:
  out_splunk_hec:
    type: splunk_hec
    disabled: false
    url: ${HEC_URL}
    token: ${HEC_TOKEN}
    streamtags: []
    description: Splunk HEC for normalized events
```

Naming convention at runtime: `destination.<pack_name>.<dest_name>`. Custom Parquet schemas and Amazon Security Lake destinations are NOT supported inside Packs.

### 6.3 `default/breakers.yml` (Event Breakers)

**No wrapping `breakers:` key.** The top-level key IS the ruleset *name* — the same string that `input.breakerRulesets` and the Event Breaker UI show — and it carries `lib: custom` like any other pack-authored library object. Ruleset names may contain spaces.

```yaml
# CORRECT — top-level ruleset name, lib: custom, rules[] inside it
Fortinet FortiGate Syslog Ruleset:
  lib: custom
  minRawLength: 256
  description: Fortinet FortiGate syslog breaker
  rules:
    - name: FortiGate KVP
      condition: "true"
      type: regex
      disabled: false
      eventBreakerRegex: '/[\n\r]+(?!\s)/'
      timestampAnchorRegex: '/date=/'
      timestamp:
        type: auto
        length: 150
      timestampTimezone: utc
      timestampEarliest: -420weeks
      timestampLatest: +1week
      maxEventBytes: 51200
```

> **Which files take a wrapping key is NOT consistent — memorize the table.** Getting it wrong is a *silent* failure in both directions: the object simply never appears in the UI, and the pack still installs "successfully".
>
> | File | Wrapping key? | Top-level keys are |
> |---|---|---|
> | `default/inputs.yml` | **yes** — `inputs:` | Source ids |
> | `default/outputs.yml` | **yes** — `outputs:` | Destination ids |
> | `default/jobs.yml` | **no** | Collector ids |
> | `default/breakers.yml` | **no** | Ruleset names |
> | `default/vars.yml` | **no** | Variable ids (see §6.5) |
> | `default/samples.yml` | **no** | Sample ids (= file basenames) |
> | `default/pipelines/route.yml` | n/a — single document with `id`, `groups`, `comments`, `routes` | |
>
> `scripts/pack-validate.py` detects a stray `breakers:` / `vars:` wrapper and fails on it.

### 6.4 `default/samples.yml` and `data/samples/`

**`samples.yml` is a MAP keyed by the sample id** (NOT a list). Each on‑disk sample file is named after that id with a `.json` extension: `data/samples/<id>.json`.

```yaml
# default/samples.yml — top-level key IS the sample id
fortigate_traffic:                      # id; file on disk = data/samples/fortigate_traffic.json
  sampleName: fortigate_traffic.log     # display label only (extension is cosmetic)
  description: 50 fortigate traffic events for CIM mapping tests
  tags: [fortigate, traffic]
  isPackOnly: true                      # ships with the pack
  packId: <pack-id>
  size: 14233                           # BYTE size of the .json file on disk
  numEvents: 50                         # number of elements in the JSON array
  created: 0
```

**CRITICAL — sample file CONTENT must be a JSON array of event objects, not raw log text.** Cribl parses every file under `data/samples/` as JSON. A raw `*.log` / newline‑delimited text file makes the UI fail with **`Error parsing sample file content`** when you open the sample. Store one object per event, each carrying at least `_raw` (the full original line, including any syslog header your pipeline strips):

```json
[
  {"_raw": "<14>Jun 11 13:03:58 PA-VM 1,2026/06/11 13:03:58,...,allow,..."},
  {"_raw": "<14>Jun 11 13:04:05 PA-VM 1,2026/06/11 13:04:05,...,deny,..."}
]
```

You may add other fields per event (`_time`, `source`, `host`, etc.), but `_raw` alone is enough — the pipeline’s first `eval` reads `(message || _raw)`.

When you add a sample:
1. Write the events as a JSON array to `data/samples/<id>.json` (see content rule above). Do NOT ship raw `.log` text.
2. Add a `samples.yml` entry whose **top-level key equals `<id>`** (the file basename) and set `isPackOnly: true`. `sampleName` is just a label; Cribl resolves the file by the id/basename, so the on-disk name `<id>.json` is what matters — there is no separate `fileName` field in the working format.
3. Set `size` to the byte size of the `.json` file and `numEvents` to the array length (cosmetic, but keep them honest).
4. Make sure your test pipeline filter references a field present in the sample (e.g., `sourcetype`). If your pipeline filters on `sourcetype=='fortigate'` but the sample event has no `sourcetype` field, Data Preview will show 0 matches.
5. **Key/basename must agree.** If `samples.yml` is keyed `smpFortigateCapture` but the file is `fortigate_capture.json`, Data Preview fails with `Unable to find sample with id=smpFortigateCapture`. Name the file after the key. See §15.K.

### 6.5 `default/vars.yml` (Variables / Templatization)

**`vars.yml` is a MAP keyed by variable ID at the TOP LEVEL of the file** — same shape as Worker Group Knowledge → Variables (`docs.cribl.io/stream/varsyml/`). It is **NOT** a list of `{name, type, value}` objects, and it must **NOT** wrap entries under a `vars:` key.

Each `value` is ALWAYS a **string** in YAML, even for `type: number`. String-type variables are evaluated as JavaScript expressions at runtime, so literal string values need **inner quotes**.

| Field | Required | Purpose |
|---|---|---|
| `type` | yes | `string` \| `number` \| `boolean` \| `expression` \| `array` \| `object` \| `any` \| … |
| `lib` | yes | Always `custom` for pack-authored variables (`cribl` / `cribl-custom` are reserved for built-ins) |
| `value` | yes | Always a **string** in YAML (see rules below) |
| `label` | strongly recommended | **Primary display name** in Knowledge → Variables / Pack Settings. Without it the raw ID (e.g. `TZ_DRIFT_THRESHOLD_SECONDS`) is shown. |
| `description` | recommended | Hover / tooltip text in the UI — not the main display name |
| `tags` | optional | Filter/group tags (string) |

```yaml
# CORRECT — top-level IDs, required lib: custom (NO wrapping `vars:` key)
HEC_URL:
  type: string
  lib: custom
  label: "HEC URL"
  value: "'https://splunk.example.com:8088/services/collector'"
  description: "Splunk HEC endpoint"
  tags: pack
HEC_TOKEN:
  type: string
  lib: custom
  label: "HEC Token"
  value: "'change-me'"
  description: "HEC token (override at install time)"
  tags: pack
TZ_DRIFT_THRESHOLD_SECONDS:
  type: number
  lib: custom
  label: "Drift Threshold (seconds)"
  value: "900"
  description: "Seconds of drift before flagging as suspect"
  tags: timezone
INDEX_NAME:
  type: string
  lib: custom
  label: "Index Name"
  value: "'cribl_monitoring'"
  description: "Target index for output events"
ENABLE_REDUCTION:
  type: boolean
  lib: custom
  label: "Enable Reduction"
  value: "true"
  description: "Toggle noise reduction pipeline"
```

```yaml
# WRONG — wrapping `vars:` key. Cribl silently ignores your custom IDs.
# Knowledge → Variables stays empty (or only shows leftover sample vars like
# cribl.sourceA). C.vars.TZ_* resolves to undefined at runtime.
vars:
  TZ_DRIFT_THRESHOLD_SECONDS:
    type: number
    value: "900"
```

**Rules:**

| Rule | Example |
|---|---|
| Top-level map keyed by variable ID — **no** wrapping `vars:` | `HEC_URL:` at column 0 of the file |
| Every pack-authored var needs `lib: custom` | `lib: custom` |
| Format is a **map**, not a list | `HEC_URL:` not `- name: HEC_URL` / `- id: HEC_URL` |
| `value` is **always a string** (even numbers and booleans) | `value: "900"` not `value: 900` |
| String literals need **inner JS quotes** (evaluated as expressions) | `value: "'my_index'"` not `value: "my_index"` |
| Numbers and booleans are bare JS expressions (no inner quotes) | `value: "900"`, `value: "true"` |
| Always set `label` for UI display; use `description` for tooltip/help text | `label: "Drift Threshold (seconds)"` |

> **WARNING — Silent failure mode:** If `vars.yml` uses the wrong format (wrapping `vars:` key, list instead of map, missing `lib: custom`, bare numbers instead of strings, missing inner quotes), Cribl may load the pack without error but custom variables never appear under Knowledge → Variables and ALL `C.vars.*` references silently return `undefined`. Pipeline functions will appear to "do nothing". If you see this, check `vars.yml` format FIRST. Verify via `GET /api/v1/m/<group>/p/<packId>/lib/vars` — your IDs must be in `items[].id`. See also §15.S.

Reference variables in expressions as `C.vars.<name>` (JS-enabled fields) or bind them via the Variable icon / `__template_<field>` on supported Source/Destination fields. Use `C.systemVars` for Worker Group–scoped values. Replace every environment‑specific literal with a variable so the pack is portable.

### 6.6 Lookups
- CSV: `data/lookups/asset_owners.csv` + descriptor `default/lookups/asset_owners.csv.yml` containing only `id`, `fileName`, `description`, `tags`.
- For very large lookup files, ship a small placeholder and document the absolute path or env var the customer must set.

---

## 6.7 Standalone JSON ⇄ Pack YAML (REQUIRED for any Collector pack)

Cribl has **two representations of the same objects** and you will move between them constantly:

| | Standalone JSON | Pack YAML |
|---|---|---|
| Where it lives | Worker Group: "Configure as JSON" tab, `GET /api/v1/…`, `criblio/collector-templates` | `default/**.yml` inside the pack |
| Shape | **one object with an `id` key** | **a map keyed BY that id, with `id` removed** |
| Can you run a Collector? | **Yes — Run → Preview, instantly** | **No — needs Commit & Deploy first** |
| Portable? | one paste per object, dependencies by hand | one `.crbl`, one install |

That last row is the whole reason this section exists. **A REST Collector inside a Pack cannot be test-run from the Pack UI.** So the only sane loop for a collector pack is: build and debug as standalone JSON against the live API, then fold the working object into the pack — and render it back out whenever you need to debug again.

### 6.7.1 The mapping, artifact by artifact

Memorize the pipeline row; it is the only one with a nesting change.

| Artifact | Standalone JSON | Pack YAML path | Transform |
|---|---|---|---|
| REST/S3/… Collector | `{"id": "in_vendor_events", "type": "collection", "schedule": {…}, "collector": {…}, "input": {…}}` | `default/jobs.yml` | key = `id`; **drop `id`**; body verbatim |
| Pipeline | `{"id": "vendor_parse", "conf": {"functions": [...], …}}` | `default/pipelines/vendor_parse/conf.yml` | **directory name = `id`**; file holds the **inside of `conf`** — one level shallower |
| Event Breaker ruleset | `{"id": "Vendor Ruleset", "lib": "custom", "rules": [...]}` | `default/breakers.yml` | key = `id` (the *name*, spaces allowed); **drop `id`**; keep `lib: custom` |
| Variables | `{"VAR_A": {…}, "VAR_B": {…}}` (already a map) | `default/vars.yml` | verbatim, merged key by key |
| Routes | `{"id": "default", "comments": [...], "routes": [...]}` | `default/pipelines/route.yml` | verbatim — **but see the warning below** |
| Sample data | `[{"_raw": "…"}, …]` | `data/samples/<id>.json` + `default/samples.yml` entry | key = file basename; add `isPackOnly: true` |

> **Routes do not survive the trip to a Worker Group.** A pack's Routes use `output: __group` / `targetContext: group`, which only mean something inside a Pack. Pasting them at group level will not do what you want. When you publish standalone configs, omit the Routes and instead document a Worker Group Route filtered on `__packsource == '<pack-id>.<source>'` (which every collector stamps) or on your own dataset field.

### 6.7.2 Scripts — do not hand-convert

Three helpers ship with this skill. `${CLAUDE_PLUGIN_ROOT}` resolves to the plugin root at runtime; `--pack` defaults to the current directory.

```bash
SCRIPTS="${CLAUDE_PLUGIN_ROOT}/skills/cribl-stream-packs/scripts"

# ── Pack YAML  →  paste-ready standalone JSON ────────────────────────────────
python3 "$SCRIPTS/pack-yaml-to-json.py" --pack ~/my-pack
#   -> conf/collectors/*.json  conf/pipelines/*.json  conf/breakers/*.json
#      conf/routes.json  conf/vars.json  conf/README.md  (gitignore conf/)

# same objects under the criblio/collector-templates naming convention
python3 "$SCRIPTS/pack-yaml-to-json.py" --pack ~/my-pack \
    --templates ~/collector-templates/collectors/rest/<vendor>
#   -> rest_*.json  eb_*.json  pipe_*.json  vars_*.json  sample_*.json

# ── standalone JSON  →  Pack YAML ────────────────────────────────────────────
python3 "$SCRIPTS/pack-json-to-yaml.py" collector.json          # dry run: prints the fragment
python3 "$SCRIPTS/pack-json-to-yaml.py" --pack ~/my-pack --write conf/collectors/*.json

# ── validate before you ever build a .crbl ───────────────────────────────────
python3 "$SCRIPTS/pack-validate.py" --pack ~/my-pack
bash    "$SCRIPTS/pack-build.sh" ~/my-pack     # validate + gtar + version cross-check
```

`pack-json-to-yaml.py` detects the artifact kind from the object's shape, applies the mapping above, and enforces the pack conventions as it goes: forces `schedule.enabled: false`, strips string `earliest`/`latest` (§6.1b), warns on a missing `__packsource`, warns on literal credentials that should be `C.Secret(...)`, fixes `lib: custom` and missing inner quotes on variables, and adds the required `index` to Route comments.

> **It defaults to a dry run, deliberately.** Rewriting a YAML file through a YAML library **drops every comment in it**, and pack YAML is where the "why" of a collector lives — which endpoint, which quirk, why this pagination type. Read the printed fragment and paste it in by hand to keep your comments; use `--write` only on a clean git tree.

### 6.7.3 The loop for a collector pack

1. **Build one collector as standalone JSON** (`cribl-rest-collector-builder` skill), paste it into **Data → Sources → Collectors → REST/API → Configure as JSON**.
2. **Run → Preview.** One request, broken-out events, nothing written downstream. Iterate here — this is the only fast feedback you get.
3. **Fold it into the pack** with `pack-json-to-yaml.py`. Add the pre-processing pipeline, the breaker ruleset, the `__packsource` metadata and a Route.
4. **`pack-validate.py`**, then `pack-build.sh`. Never skip straight to `Add Pack`.
5. **Install with Import mode `Replace`** so the `local/` overlay cannot shadow your new `default/` (§15.L), then **Commit & Deploy** — collectors do not run until you do.
6. When something misbehaves in the pack, **render back out** with `pack-yaml-to-json.py` and debug at group level again. The generated JSON is derived from `default/`, so the two can never drift.

Keep `default/` as the single source of truth and `conf/` gitignored. Generated-from-YAML in one direction and folded-back-in in the other means there is exactly one copy of the truth.

---

## 7. Cribl Expression Library (`C.*`)
You may use these inside any `eval`/filter/value expression. Do NOT invent helpers outside this set.

- `C.Crypto.*` — `encrypt(value, keyId)`, `decrypt(value)`, hashes (`md5`, `sha1`, `sha256`, `xxh3`).
- `C.Decode.*` / `C.Encode.*` — base64, hex, url, gzip, zlib.
- `C.Lookup` — inline lookup against a Lookup file: `C.Lookup('asset_owners.csv','host').match(host)`.
- `C.Mask.*` — `random()`, `repeat()`, `md5()`, `sha256()`, etc., for redaction.
- `C.Net.*` — `cidrMatch`, `isPrivate`, `ipVersion`, `expandIPv6`, `intToIp`, `ipToInt`.
- `C.Text.*` — `parseXml`, `parseWinEvent` (compact Windows XML reduction), `parseDsv`, `substr`, `replace`, `trim`.
- `C.Time.*` — `strftime`, `strptime`, `now`, `dateAdd`, `dateDiff`.
- `C.vars.<name>` — read a Pack/Group variable.
- `C.expr.*` — guarded helpers for math/strings.

Use `C.Text.parseWinEvent(_raw, ['0','0x0','-'])` for 30–70% reduction on Windows XML events; that idiom is canonical and must be preferred over hand‑rolled XML parsing.

---

## 8. Reduction & Normalization Cookbook (use these patterns)

When the user asks for “reduce”, “drop noise”, “convert to CIM”, etc., reach first for these proven recipes:

| Goal | Functions to chain |
|---|---|
| Drop noisy events | `regex_filter` or `drop` with a tight filter, set `final: true` |
| Time‑based dedup | `suppress` (keyExpr + timeWindowSec + maxNumberOfMatches) |
| Sample low‑value high‑volume traffic | `sampling` (static rate) or `dynamic_sampling` (rate based on group volume) |
| Roll up to metrics | `aggregations` (count/sum/avg by group) with `passthrough: false` to drop originals |
| Field add/remove/rename | `eval` (add) + `rename` for bulk renames |
| Parse k=v / CSV / JSON | `serde` with `mode: extract` and `type: kvp\|json\|csv\|elff` for inline parsing; `parser` (+ Library entry) when the parser should be reusable; for KV regex use `regex_extract` with global flag |
| Mask PII | `mask` with rules — prefer `C.Mask.sha256` for reversible joins, `C.Mask.random` for pure redaction |
| Enrich with internal data | `lookup` (CSV/MMDB), `redis` for high‑cardinality dynamic lookups, `dns_lookup`/`geoip` |
| Splunk CIM mapping | `eval` — alias raw Fortinet/Cisco/PAN field names to CIM names (`src_ip`, `dest_ip`, `action`, `bytes_in`, `bytes_out`, `app`, `user`, `vendor`, `product`) |
| Windows EVT XML compaction | `eval` with `__e._raw = C.Text.parseWinEvent(_raw, ['0','0x0','-'])` then `flatten` then `rename` |

Always end the pipeline with a `serialize` Function only when the destination expects a specific format (e.g., CSV, KVP, CEF). For JSON destinations, leave the event as a JS object.

---

## 9. Schema Quick References (used by most security packs)

When the user asks to normalize vendor data, target one of these three canonical schemas. Always set `vendor` and `product` (or the schema's equivalent) early so downstream Routes can filter on them cheaply, regardless of which target schema you're producing.

### 9.1 Splunk CIM 6.0
Full reference: https://docs.splunk.com/Documentation/CIM/latest/User/Overview

- **Network_Traffic**: `action`, `app`, `bytes`, `bytes_in`, `bytes_out`, `dest`, `dest_ip`, `dest_port`, `direction`, `duration`, `protocol`, `src`, `src_ip`, `src_port`, `transport`, `user`, `vendor_product`.
- **Authentication**: `action`, `app`, `dest`, `signature`, `src`, `user`, `vendor_account`, `authentication_method`.
- **Web**: `action`, `bytes_in`, `bytes_out`, `dest`, `http_method`, `http_user_agent`, `http_referrer`, `status`, `uri_path`, `url`, `user`.
- **Performance** (interface metrics, CPU, memory): `cpu_load_percent`, `mem_used`, `mem_total`, `interface_name`, `throughput_in`, `throughput_out`.

Output shape: typically a JSON document in `_raw` (see §15.M).

### 9.2 OCSF 1.4 (Open Cybersecurity Schema Framework)
Schema browser: https://schema.ocsf.io/1.4.0/ · Spec & JSON Schemas: https://github.com/ocsf/ocsf-schema (1.4.0 branch) · Server docs: https://schema.ocsf.io/

**Required root fields on every OCSF event** (any class):

| Field | Meaning |
|---|---|
| `class_uid`, `class_name` | Event Class (e.g., `4001` / `Network Activity`). |
| `category_uid`, `category_name` | Parent Category (e.g., `4` / `Network Activity`). |
| `activity_id`, `activity_name` | Class‑specific activity enum (`1` Open, `2` Close, `6` Traffic, …). |
| `type_uid`, `type_name` | `class_uid * 100 + activity_id`. Convention, but emit it. |
| `severity_id`, `severity` | `0` Unknown, `1` Informational, `2` Low, `3` Medium, `4` High, `5` Critical, `6` Fatal, `99` Other. |
| `time` | Event time in **milliseconds** since epoch (NOT seconds). |
| `metadata` | Object with `version` (`"1.4.0"`), `product` `{ vendor_name, name, version }`, optional `profiles`. |

**Category UIDs** (root buckets):

| UID | Category | Notable Classes |
|---|---|---|
| 1 | System Activity | 1001 File System Activity, 1003 Kernel Activity, 1004 Memory Activity, 1005 Module Activity, 1007 Process Activity |
| 2 | Findings | 2001 Security Finding, 2002 Vulnerability Finding, 2003 Compliance Finding, 2004 Detection Finding |
| 3 | Identity & Access Management | 3001 Account Change, 3002 Authentication, 3003 Authorize Session, 3005 User Access Management, 3006 Group Management |
| 4 | Network Activity | 4001 Network Activity, 4002 HTTP Activity, 4003 DNS Activity, 4004 DHCP Activity, 4005 RDP, 4006 SMB, 4007 SSH, 4008 FTP, 4009 Email, 4010 Network File Activity, 4013 Tunnel Activity |
| 5 | Discovery | 5001 Device Inventory Info, 5002 Device Config State |
| 6 | Application Activity | 6001 Web Resources Activity, 6003 API Activity, 6004 Web Resource Access, 6005 Datastore, 6007 Scan Activity |
| 7 | Remediation | 7001 Remediation Activity |

**Common nested objects** (use the ones your Class declares):

- `src_endpoint`, `dst_endpoint` — `{ ip, port, hostname, mac, svc_name, location, vlan_uid, interface_name }`
- `device` — `{ ip, hostname, type_id, type, os, hw_info, ... }`
- `actor` — `{ user: {name, uid, type, domain}, process: {...}, session: {...} }`
- `connection_info` — `{ direction_id, direction, protocol_name, protocol_num, protocol_ver_id, boundary_id, session: {} }`
- `traffic` — `{ bytes, bytes_in, bytes_out, packets, packets_in, packets_out }`
- `http_request` — `{ url: {full_url, hostname, path, port, scheme, query_string}, http_method, version, user_agent, referrer }`
- `http_response` — `{ status, status_code, length, content_type, message }`
- `tls` — `{ version, cipher, ja3, ja3s, sni, certificate: {...} }`
- `unmapped` — free‑form bag for vendor fields that have no canonical home. **Always allowed** — use generously instead of dropping data.

**Status / outcome enums**:
- `status_id`: `0` Unknown, `1` Success, `2` Failure, `99` Other (+ `status` and `status_detail` strings).
- `disposition_id` (Findings only): `0` Unknown, `1` Allowed, `2` Blocked, `3` Quarantined, `4` Isolated, `5` Deleted, …

Output shape: typically a JSON document in `_raw` produced via `eval` + `JSON.stringify(__ocsf)` (NOT `serialize` with `srcField`; see §15.H).

### 9.3 Azure CommonSecurityLog (Schema 2026‑03)
Microsoft Sentinel's CEF‑equivalent table. Target for the Log Ingestion API DCR/DCE flow as well as the legacy HTTP Data Collector. Reference: https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/commonsecuritylog · Sentinel CEF/Syslog overview: https://learn.microsoft.com/en-us/azure/sentinel/connect-cef-syslog-ama

**Identity columns** (always populate these):

| Column | Type | Notes |
|---|---|---|
| `TimeGenerated` | datetime | ISO‑8601 UTC. Sentinel indexes on this. |
| `DeviceVendor` | string | e.g., `"Fortinet"`. |
| `DeviceProduct` | string | e.g., `"FortiGate"`. |
| `DeviceVersion` | string | Firmware / app version. |
| `DeviceEventClassID` | **Number** | Vendor‑specific signature/event id. Emit as a number (`13`), not a zero‑padded string (`"0000000013"`). |
| `Activity` | string | Free‑form. Convention: `${type}:${subtype} ${action}` (e.g., `"traffic:forward accept"`). |
| `DeviceAction` | string | The action taken (`accept`, `deny`, `drop`, `block`). |
| `LogSeverity` | string | `Low` / `Medium` / `High` / `Very-High` / `Unknown`. |
| `OriginalLogSeverity` | string | Raw vendor severity verbatim (e.g., `notice`, `warning`). |
| `DeviceFacility` | string | Syslog facility name (`local0`, `daemon`, …). |
| `DeviceEventCategory` | string | Typically `${type}:${subtype}` for filtering. |
| `Computer` | string | Device hostname (your `host`/`devname` field). |
| `Type` | string | Always `"CommonSecurityLog"`. |
| `SourceSystem` | string | Free‑form (`"Cribl"` is fine). |
| `DeviceName` | string | Same as `Computer` for most vendors. |
| `DeviceExternalID` | string | Device serial / unique identifier (`devid`). |

**Network columns**:

`Protocol`, `ApplicationProtocol`, `SourceIP`, `SourcePort`, `SourceUserName`, `SourceUserID`, `SourceHostName`, `SourceMACAddress`, `DestinationIP`, `DestinationPort`, `DestinationUserName`, `DestinationUserID`, `DestinationHostName`, `DestinationMACAddress`, `SentBytes`, `ReceivedBytes`, `DeviceInboundInterface`, `DeviceOutboundInterface`.

**Web columns**:

`RequestURL`, `RequestMethod`, `RequestClientApplication` (user‑agent), `RequestContext`.

**Custom columns** (vendor‑specific scratch — use Labels to document them):

`DeviceCustomString1..6` + `DeviceCustomString1..6Label`
`DeviceCustomNumber1..3` + `DeviceCustomNumber1..3Label`
`DeviceCustomFloatingPoint1..4` + Labels
`DeviceCustomIPv6Address1..4` + Labels
`DeviceCustomDate1..2` + Labels

**Catch‑all**:

`AdditionalExtensions` — a **single string** of `key=value;key=value;...` pairs, no JSON. Use guarded concatenation to build it: `(field ? 'k=' + field + ';' : '') + ...` then trim the trailing `;`. This is where any FortiGate / Cisco / PAN field with no canonical column belongs.

**Trailing summary columns**: `Message` (human‑readable summary), `EventOutcome` (`Success` / `Failure` / `Unknown`).

Output shape: **top‑level fields on the event, no `_raw`**. The Sentinel destination JSON‑serializes the whole event itself; see §15.M.

---

## 10. Workflow

This is the loop the agent must follow when asked to build or modify a pack.

1. **Bootstrap**
   - If editing an existing pack: in Cribl, Manage Packs → row menu → Export → mode `Merge` → download `<pack>_<version>.crbl`.
   - `mkdir <pack>-repo && cd <pack>-repo && tar -xvf ~/Downloads/<pack>_<version>.crbl`.
   - Open the folder in Claude Code and ask for the change you want; this skill is already loaded.
2. **Plan before editing**
   - Always read `package.json`, `default/pack.yml`, `default/pipelines/route.yml`, every `default/pipelines/*/conf.yml`, and the README first.
   - Restate the user’s ask and list the files you will change. Do not modify Sources/Destinations unless explicitly asked.
3. **Edit safely**
   - Make minimal, surgical YAML diffs. Preserve key order where reasonable.
   - For every new Function, add a `description`. For every new Pipeline, add a leading `comment` Function with purpose, author, date, ticket.
   - Add or update sample data and `samples.yml` BEFORE writing the transform — verify the pipeline against the sample.
   - Bump `version` in BOTH `package.json` and `default/pack.yml`. Add a Changelog entry to `README.md`.
4. **Validate locally — against a real Cribl install, not by eye**

   Cribl validates a Pack with AJV on install and tells you only the keyword that failed (`failed to install: should be equal to one of the allowed values`) with **no field path**. Do not debug that. Every install already carries the schemas on disk:

   | What | Where |
   |---|---|
   | Collector confs | `$CRIBL_HOME/default/cribl/collectors/<type>/conf.schema.json` |
   | Pipeline Function confs | `$CRIBL_HOME/default/cribl/functions/<id>/conf.schema.json` |
   | **Routes, job wrapper, breakers, vars, samples** | `$CRIBL_HOME/default/ui/static/swagger/openapi.json.gz` → `components.schemas.{Routes, SavedJobCollection, EventBreakerRuleset, GlobalVar, DataSample}` |

   That second row is where the required-property lists actually live, and it is not obvious it exists — it is the gzipped OpenAPI spec bundled with the UI. It is how you learn that `RouteConf` requires `pipeline`, `RouteComment` requires `index`, and `schedule.run.earliest`/`latest` are numbers.

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/cribl-stream-packs/scripts/pack-validate.py" --pack .
   #   pass 1  cross-references — always runs, no Cribl install needed:
   #           dangling route→pipeline and collector→breaker refs, samples.yml
   #           keys with no file, C.vars reads of undefined variables, dead
   #           variables, package.json/pack.yml version+id skew, stray
   #           `breakers:`/`vars:` wrapper keys
   #   pass 2  JSON Schema — skips itself if there is no install:
   #           real JSON pointers instead of AJV's mystery keyword
   ```

   Then build. `pack-build.sh` wraps the YAML lint, the version cross-check, the validator and **GNU tar** (never macOS/BSD `tar` — see §12.2):

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/skills/cribl-stream-packs/scripts/pack-build.sh" .
   ```

   Or by hand:
   ```bash
   gtar -cvz --exclude .DS_Store --exclude .git --exclude '*.crbl' \
     -f <pack>_<new-version>.crbl \
     package.json README.md default data
   ```
   Sanity‑check archive contents with `tar tvf <pack>_<new-version>.crbl | awk '{print $9}'` — every directory must appear as its own entry.

   Add an offline pipeline dry-run too if the pack does real normalization (§15.P) — a simulator pass catches ~95% of expression bugs before the `.crbl` exists.
5. **Round‑trip in Cribl**
   - Cribl UI → Manage Packs → Add Pack → Import from File → upload the `.crbl`.
   - Use Data Preview against the `In Pack` samples to confirm the transformation. Fix and re‑export until green.
   - Commit & Deploy on the Worker Group.

   > **Version collision:** Cribl refuses to install a pack at the same version it already has (`"failed to upgrade: Version X.Y.Z is up to date"`). During development iteration, use a `-dev.N` prerelease suffix (e.g., `1.0.0-dev.1`, `1.0.0-dev.2`) — Cribl treats each distinct version string as upgradeable. Only use clean semver for the final working version. Alternatively, use Manage Packs → row menu → Delete before re-importing the same version.

   > **Programmatic preview (API-based testing):** Pack samples require the full scoped reference:
   > ```
   > POST /api/v1/preview
   > { "pipeline": "<packId>:<pipelineId>", "sampleId": "<packId>:<sampleId>" }
   > ```
   > The exact format may vary by Cribl version. When in doubt, use the UI's Data Preview (which handles scoping internally) and reserve API testing for CI/CD automation after the format is confirmed manually.

6. **Promote via Git (recommended)**
   - Push the extracted folder to a Git repo. Cribl can `Import from Git` (Personal Access Token required for private repos) and later `Publish to Git` directly from the Pack’s row menu. Use branches per environment (`dev` → `test` → `main`). Cribl decides upgrade eligibility from `package.json.version`.

---

## 11. Hard Rules for the Agent

1. **Never fabricate** Function `id`s, Source/Destination `type`s, `C.*` helpers, or YAML keys. If unsure, stop and ask, or use `code` with explicit JavaScript.
2. **Never strip the `default/` baseline.** All edits go into `default/`. Do not author files into `local/`.
3. **Never embed secrets** (HEC tokens, AWS keys, TLS PEM bodies). Use `vars.yml` placeholders or environment variables (`${VAR}`).
4. **Always bump `version`** in `package.json` and `default/pack.yml` together when shipping a change. Add a README Changelog entry.
5. **Always include a leading `comment` Function** in every new Pipeline summarizing intent.
6. **Always provide at least one sample event** under `data/samples/<id>.json` (a JSON array of `{"_raw": …}` objects — NOT raw `.log` text; see §6.4/§15.K) plus a `samples.yml` entry keyed by `<id>` with `isPackOnly: true`. The pipeline filter MUST match a field present in the sample.
7. **Always prefer existing Functions** (`eval`, `rename`, `serde`, `parser`, `regex_extract`, `mask`, `lookup`, `aggregations`, `suppress`, `sampling`, `drop`) over `code`. Reach for `code` only when no built‑in fits — and even then, prefer a chain of single‑expression `eval`s (see §15.A).
8. **Never write JS that depends on global state across events.** Cribl is shared‑nothing per Worker Process; aggregation across workers requires `redis`.
9. **JavaScript regex only.** No PCRE‑specific constructs (`\K`, named conditional groups, etc.).
10. **Always build `.crbl` archives with GNU tar (`gtar`), never macOS/BSD `tar`.** macOS `tar`/`bsdtar` (even with `--format=ustar`) silently produces archives Cribl cannot install (`ENOENT: …/default/pack.yml` even though `tar -tzf` lists the file). Install once with `brew install gnu-tar`. Exclude `.DS_Store`, `.git`, and `*.crbl`. Do not pass `--no-recursion` without `--force-local`.
11. **Each Pack within a Worker Group must have a unique Pack ID.** When forking a Pack, change `id` in `pack.yml`, `name` in `package.json`, and the top‑level directory together.
12. **Do not use unsupported Sources/Destinations in Packs** (see §6.1 and §6.2 lists).
13. **Lookups under ~5 MB** belong in the repo; bigger ones must be referenced via env var or absolute path documented in the README.
14. **When in doubt about a function’s schema**, read its docs page (links in §13) before guessing — these are the only authoritative source.
15. **Every variable in `vars.yml` must be referenced** via `C.vars.<name>` in at least one pipeline, route filter, or source/destination config. Unreferenced variables are dead config that confuses users and suggests broken wiring. Always set a human-readable `label` (UI display name); put longer help text in `description`. **Schema:** top-level IDs (never wrap under `vars:`), required `lib: custom`, string `value`s — see §6.5.
16. **Do not put `C.vars.*` (or any JS) in static Aggregations config fields** (`timeWindow`, `passthrough`, `metricsMode`, `cumulative`, `flushOnInputClose`, `sufficientStatsOnly`). Those are literals only — see §4.
17. **Run `scripts/pack-validate.py` before every `.crbl` build.** Cribl's install-time AJV error has no field path; the validator does. Both its passes are cheap and the cross-reference pass needs no Cribl install.
18. **Never hand-convert between standalone JSON and pack YAML.** Use `scripts/pack-json-to-yaml.py` / `scripts/pack-yaml-to-json.py` (§6.7). The pipeline nesting change (`conf` unwraps into `conf.yml`) and the id→map-key move are exactly the kind of thing that is silently wrong when done by eye.
19. **Get the wrapping-key question right per file** — `inputs:`/`outputs:` are wrapped; `jobs.yml`, `breakers.yml`, `vars.yml`, `samples.yml` are **not** (§6.3). A wrong wrapper installs cleanly and the objects simply never appear.
20. **Omit `schedule.run.earliest`/`latest` in `jobs.yml`** and build the collection window in `collectRequestParams`. The relative-time strings the UI writes are numbers in the Pack schema and take out the whole Packs UI (§6.1b).

---

## 12. Helpful Snippets

### 12.1 Skeleton for a brand‑new Pack
```bash
PACK=cribl-fortinet-fortigate
mkdir -p $PACK/{default/pipelines,default/lookups,data/samples,data/lookups}
cat > $PACK/package.json <<'JSON'
{ "name":"cribl-fortinet-fortigate","version":"0.1.0",
  "description":"FortiGate syslog → Splunk CIM with reduction",
  "author":"Your Name <you@example.com>",
  "license":"Apache-2.0","keywords":["fortinet","cim","reduction"],
  "engines":{"cribl":">=4.0.0"} }
JSON
cat > $PACK/default/pack.yml <<'YML'
id: cribl-fortinet-fortigate
displayName: FortiGate → Splunk CIM
version: 0.1.0
author: Your Name
description: Normalize Fortinet FortiGate syslog to Splunk CIM and reduce noise.
minStreamVersion: 4.0.0
dataTypes: [logs]
useCases: [normalization, reduction]
technologies: [fortinet, syslog]
tags: [security, firewall]
YML
echo "# FortiGate → Splunk CIM Pack" > $PACK/README.md
```

### 12.2 Pack a folder back into a `.crbl`

> **macOS `tar`/bsdtar silently corrupts `.crbl` archives** — always build with GNU tar (`gtar`), never the OS-default `tar`. Even `tar --format=ustar -czvf` fails at install with misleading `ENOENT: …/default/pack.yml` while `tar -tzf` still lists the file. The same gotcha applies to Search Packs.

```bash
brew install gnu-tar   # provides `gtar` — once per machine
cd $PACK
gtar -cvz --exclude .DS_Store --exclude .git --exclude '*.crbl' \
  -f ../${PACK}_$(jq -r .version package.json).crbl \
  package.json README.md default data
```

### 12.3 Diff‑friendly Function comment template
```yaml
- id: comment
  filter: 'true'
  conf:
    comment: |
      Pipeline : fortigate_traffic_cim
      Purpose  : Map FortiGate "type=traffic" syslog to Splunk CIM Network_Traffic.
      Author   : @your-handle
      Updated  : 2026-05-01
      Refs     : TICKET-123, https://docs.splunk.com/Documentation/CIM/.../NetworkTraffic
```

---

## 13. References (load on demand)

### The most authoritative reference is the Cribl install itself

Before reaching for docs or priors, read the schemas on disk. They are the exact
ones the product validates against, versioned with the install:

```bash
CRIBL_HOME=${CRIBL_HOME:-/opt/cribl}        # or ~/cribl on a tarball install

ls  $CRIBL_HOME/default/cribl/collectors/           # every collector type
ls  $CRIBL_HOME/default/cribl/functions/            # every Function id (no dir = no such Function)
jq . $CRIBL_HOME/default/cribl/collectors/rest/conf.schema.json
cat $CRIBL_HOME/default/cribl/breakers.yml          # canonical breakers.yml shape
cat $CRIBL_HOME/default/cribl/inputs.yml            # canonical inputs.yml shape (wrapped)

# Routes / job wrapper / breakers / vars / samples — the required-property lists
python3 -c "import gzip,json;s=json.load(gzip.open('$CRIBL_HOME/default/ui/static/swagger/openapi.json.gz'));\
print(json.dumps(s['components']['schemas']['SavedJobCollection'],indent=2))"
```

`scripts/pack-validate.py` automates all of this — see §10 step 4.

Authoritative Cribl docs — always prefer these over the agent’s priors.

- Packs overview: https://docs.cribl.io/stream/packs/
- Create a Pack: https://docs.cribl.io/stream/packs/#create-a-pack
- Pack‑Based Config Management: https://docs.cribl.io/stream/pack-management/
- Version Control Packs in External Git Repos: https://docs.cribl.io/stream/version-control-packs/
- Packs Publication Standards: https://docs.cribl.io/stream/packs-standards/
- Configuration Files (full YAML index): https://docs.cribl.io/stream/configuration-files/
- Pipelines: https://docs.cribl.io/stream/pipelines/
- Functions index: https://docs.cribl.io/stream/functions/
- Eval: https://docs.cribl.io/stream/eval-function/ · Mask: https://docs.cribl.io/stream/mask-function/ · Parser: https://docs.cribl.io/stream/parser-function/ · Aggregations: https://docs.cribl.io/stream/aggregations-function/ · Suppress: https://docs.cribl.io/stream/suppress-function/ · Sampling: https://docs.cribl.io/stream/sampling-function/ · Lookup: https://docs.cribl.io/stream/lookup-function/ · Code: https://docs.cribl.io/stream/code-function/
- Cribl Expressions (`C.*`): https://docs.cribl.io/stream/expressions/
- Reducing Windows XML: https://docs.cribl.io/stream/usecase-win-xml/
- Routes: https://docs.cribl.io/stream/routes/
- Event Breakers: https://docs.cribl.io/stream/event-breakers/
- API reference (for programmatic export/install): https://docs.cribl.io/cribl-as-code/api-reference/
- Copy / export / install Packs via API: https://docs.cribl.io/cribl-as-code/copy-export-install-packs/
- Commit & deploy via API: https://docs.cribl.io/cribl-as-code/commit-deploy/
- Cribl AI chatbot (use for runtime questions only, not as a YAML source of truth): https://ai.cribl.cloud/chatbot

### Deploy a Pack via API (full recipe — upload is not enough)

Canonical flow: [Copy, Export, and Install Packs](https://docs.cribl.io/cribl-as-code/copy-export-install-packs/) + [Commit and Deploy](https://docs.cribl.io/cribl-as-code/commit-deploy/). Upload alone only stages a temp file; it does **not** install or activate anything.

**URL patterns**
- Cribl Cloud org: `https://<workspace>-<org-id>.cribl.cloud` (e.g. `https://main-acme.cribl.cloud`)
- Worker-group–scoped pack ops: `/api/v1/m/<group>/…`
- Cluster-scoped commit/deploy: `/api/v1/version/…` and `/api/v1/master/groups/<group>/…` — **no** `/m/<group>` prefix on those two

Set once:
```bash
BASE="https://<workspace>-<org-id>.cribl.cloud"   # or https://<leader>:9000 on-prem
GROUP="default"
PACK_ID="<pack-id>"
CRBL="<pack-id>_<version>.crbl"                  # built with gtar — see §12.2
AUTH="Authorization: Bearer $TOKEN"
```

**1. Upload** (PUT) — requires the `filename` query parameter. Response is `{"source":"<pack>_<version>.<randomsuffix>.crbl"}`. **Capture `source` exactly** — step 2 needs it.
```bash
SOURCE=$(curl -sS -X PUT "$BASE/api/v1/m/$GROUP/packs?filename=$CRBL" \
  -H "$AUTH" -H "Content-Type: application/octet-stream" \
  --data-binary @"$CRBL" | jq -r .source)
echo "source=$SOURCE"
```

**2. Install or upgrade** — choose by whether the pack already exists on the worker group:

| Situation | Method | Endpoint |
|---|---|---|
| Pack **does not** exist | **POST** (install) | `/api/v1/m/<group>/packs` |
| Pack **already** exists | **PATCH** (upgrade in place) | `/api/v1/m/<group>/packs/<pack-id>` |

Prefer **PATCH** for upgrades — it replaces pack contents without a destructive DELETE and preserves runtime state better than DELETE + re-POST. Reserve POST for first-time installs only.

**2a. First-time install** (POST) — body must include that exact `source` (and usually `id`):
```bash
curl -sS -X POST "$BASE/api/v1/m/$GROUP/packs" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"source\":\"$SOURCE\",\"id\":\"$PACK_ID\"}"
```

**2b. Upgrade existing pack** (PATCH) — preferred when the pack is already installed:
```bash
curl -sS -X PATCH "$BASE/api/v1/m/$GROUP/packs/$PACK_ID" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"source\":\"$SOURCE\"}"
```

| Error string | Meaning / fix |
|---|---|
| `Missing required parameter: source` | Body omitted `source`, or you POSTed/PATCHed the raw filename instead of the upload response's `source` |
| `Pack name cannot be empty` | Missing/empty `id` on POST |
| `Pack Id conflicts with existing Pack` | Pack already installed — do **not** DELETE by default; use **PATCH** (2b) with the same `source`. DELETE + re-POST only if you intentionally want a clean wipe |

**3. Commit** (POST) — required on Cribl Cloud / distributed before deploy picks up the change:
```bash
COMMIT=$(curl -sS -X POST "$BASE/api/v1/version/commit" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"group\":\"$GROUP\",\"message\":\"Install/upgrade $PACK_ID\"}" \
  | jq -r '.items[0].commit')
echo "commit=$COMMIT"
```
Response includes `items[0].commit` — a git-style SHA. **Save it**; step 4 needs it (not the pack semver).

**4. Deploy** (PATCH) — activates the committed config on running workers:
```bash
curl -sS -X PATCH "$BASE/api/v1/master/groups/$GROUP/deploy" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"version\":\"$COMMIT\"}"
```
| Error string | Meaning / fix |
|---|---|
| `missing required parameter: version` | Body omitted `version` — it is **not** optional |
| (deploy with pack semver) | Wrong value — `version` must be the **commit SHA** from step 3, never `package.json` version |

Community / examples
- Cribl Packs Dispensary: https://packs.cribl.io
- Cribl Packs GitHub org: https://github.com/criblpacks
- HelloPacks reference repo: https://github.com/criblpacks/HelloPacks
- Blog — “How To: Roll Your Own Cribl Pack”: https://cribl.io/blog/how-to-roll-your-own-cribl-pack/
- Blog — “Add an existing Cribl Pack to Git”: https://cribl.io/blog/no-more-kidding-around-add-an-existing-cribl-pack-to-git/
- Blog — “Time to GIT Serious” (CI/CD for Packs): https://cribl.io/blog/time-to-git-serious-automate-your-cribl-pack-deployments/
- Blog — “Source/Destinations in Packs”: https://cribl.io/blog/introducing-sources-and-destinations-in-cribl-packs/

Domain references the agent may need
- Splunk CIM 6.0: https://docs.splunk.com/Documentation/CIM/latest/User/Overview · per‑dataset field reference: https://docs.splunk.com/Documentation/CIM/latest/User/NetworkTraffic
- OCSF 1.4 schema browser: https://schema.ocsf.io/1.4.0/ · JSON Schema repo (branch `1.4.0`): https://github.com/ocsf/ocsf-schema · spec PDF / docs: https://schema.ocsf.io/
- Azure CommonSecurityLog table (2026‑03): https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/commonsecuritylog · CEF/Syslog → Sentinel via AMA: https://learn.microsoft.com/en-us/azure/sentinel/connect-cef-syslog-ama · ASIM (Sentinel Advanced Security Information Model) parsers: https://learn.microsoft.com/en-us/azure/sentinel/normalization
- Regex101 (set flavor to ECMAScript): https://regex101.com

---

## 14. Quickstart Prompts (run with the pack folder open)

- **New Pack from scratch**: “Scaffold a new Cribl Stream pack named `cribl-<vendor>-<tech>` that ingests `<source>`, normalizes to Splunk CIM `<dataset>`, and reduces volume by dropping `<noise>` and aggregating `<metric>`. Add a sample event and a Data Preview test plan.”
- **Modify an existing Pack**: “Open the pack in this folder. Add a reduction pipeline for `<event subtype>` that targets ≥20% reduction without dropping any allow/deny actions. Bump version, update README changelog, and tell me which routes need wiring.”
- **CIM mapping**: “Read `data/samples/fortigate_traffic.log`, propose CIM Network_Traffic field mappings, then implement them as a new pipeline `fortigate_traffic_cim` and add a Route entry in `default/pipelines/route.yml`.”

---

## 15. Battle-tested Patterns & Cribl Quirks (REQUIRED READING before editing pipelines)

This section captures real bugs we hit while building this pack. **Read this whole section before authoring or modifying any pipeline YAML.** Every entry below is sourced from a specific failure observed in Cribl Stream, not from speculation.

### 15.A. `eval` Function `value` expressions: NO nested scopes, NO statements, single expression only

Cribl evaluates each `eval.add[].value` as a **single JavaScript expression** inside a `with(event)` block. The expression parser rejects anything that smells like a nested lexical scope.

**DO NOT use any of these in a `value:`**
- IIFEs: `(function(){ ... return x; })()`
- Arrow function bodies with braces: `() => { ... return x; }`
- `var`, `let`, `const` declarations
- `return` statements at the top level
- Multiple statements separated by `;`

You will see `Expression cannot have nested scopes` (or a near‑miss `ReferenceError` for the field you tried to read, because the parser silently turned your IIFE into junk and `with` no longer binds your field name).

**DO use:** object‑literal lookups, chained ternaries, `Array.indexOf(...) >= 0 ? a : b`, string concatenation, `JSON.stringify(...)`, plain method calls.

<good-example>Map a numeric protocol id to a name without any scope:

```yaml
- id: eval
  filter: "true"
  conf:
    add:
      - name: proto_name
        value: |-
          proto === 6 ? 'TCP'
          : proto === 17 ? 'UDP'
          : proto === 1 ? 'ICMP'
          : proto === 50 ? 'ESP'
          : 'OTHER'
```</good-example>

<good-example>Lookup via inline object literal (no IIFE needed):

```yaml
- id: eval
  filter: "true"
  conf:
    add:
      - name: fgt_proto_name
        value: "({'6':'TCP','17':'UDP','1':'ICMP','50':'ESP','58':'IPv6-ICMP'})[String(proto)] || 'OTHER'"
```</good-example>

<bad-example>This **looks** like idiomatic JS but Cribl rejects it (and the field disappears at runtime):

```yaml
- id: eval
  filter: "true"
  conf:
    add:
      - name: proto_name
        value: |
          (function(p){
            var m = {6:'TCP', 17:'UDP', 1:'ICMP'};
            return m[p] || 'OTHER';
          })(proto)
```</bad-example>

If your logic genuinely needs branches, split it into **multiple chained `eval` Functions** with intermediate scratch fields (prefix with `__`, e.g., `__ocsf`, `__csl_extras`). That's what the OCSF/CSL/CIM pipelines in this pack do.

### 15.B. Strict‑mode reserved words: cannot be bare identifiers

`eval` runs in JS strict mode. Bare references to strict‑mode reserved words throw `SyntaxError: Unexpected strict mode reserved word`.

The ones we've hit in FortiGate fields: `interface`. Likely to hit eventually: `package`, `public`, `private`, `protected`, `implements`, `let`, `static`, `yield`, `enum`, `arguments`, `eval` (yes, the word).

**Fix:** access via `__e['<field>']` instead.

<good-example>

```yaml
- name: src_interface
  value: "__e['interface']"
```</good-example>

<bad-example>

```yaml
- name: src_interface
  value: "interface"   # SyntaxError: Unexpected strict mode reserved word
```</bad-example>

### 15.C. YAML `value: null` evaporates — use the string `"null"` instead

A bare YAML `null` (or empty `value:` line) deserializes to JS `undefined` inside Cribl, and the UI then complains "This field is required". You'll see the value disappear in Data Preview as well.

When you genuinely want the JavaScript literal `null` (e.g., to leave a CIM field unset), quote it as a JS expression:

<good-example>

```yaml
- name: http_content_type
  value: "null"        # JS expression: the literal null
- name: status
  value: "null"
```</good-example>

<bad-example>

```yaml
- name: http_content_type
  value: null          # YAML null → undefined → "field is required"
- name: status
  value:               # same problem
```</bad-example>

### 15.D. YAML ternaries (and anything with `:`) must be quoted

YAML treats unquoted `:` as a key separator. Any ternary in a `value:` MUST be a quoted string or a block scalar.

<good-example>

```yaml
- name: severity_id
  value: "level === 'critical' ? 5 : level === 'high' ? 4 : 3"
- name: longer_expr
  value: |-
    level === 'critical' ? 5
    : level === 'high' ? 4
    : level === 'medium' ? 3
    : 2
```</good-example>

<bad-example>

```yaml
- name: severity_id
  value: level === 'critical' ? 5 : level === 'high' ? 4 : 3
# → "mapping values are not allowed here"
```</bad-example>

Descriptions containing `:` or `[…]` need the same treatment.

### 15.E. `keep` is an EXEMPTION list, not a whitelist — pair it with `remove: ["*"]`

`eval.conf.keep` does **not** "keep only these fields and drop everything else". It only protects listed fields from being matched by patterns in `remove`. To actually whitelist a small set of fields you must combine them:

<good-example>

```yaml
- id: eval
  filter: "true"
  description: Final cleanup — drop everything except CIM canonical fields
  conf:
    add: []
    remove:
      - "*"
      - "__*"
      - "_*"
      - "cribl_*"
    keep:
      - _raw
      - _time
      - index
      - host
      - source
      - sourcetype
      - vendor
      - product
      - src_ip
      - dest_ip
      # ... etc
```</good-example>

<bad-example>

```yaml
# This DOES NOT strict-whitelist. It leaves every other field intact.
conf:
  remove: []
  keep:
    - _raw
    - _time
```</bad-example>

### 15.F. `*` in `remove` does NOT match underscore‑prefixed fields — list them explicitly

Cribl's wildcard matcher treats `__*`, `_*`, and the pipeline‑metadata prefix `cribl_*` (e.g., `cribl_breaker`, `cribl_pipe`) as **not matched by `*` alone**. If you only put `*` in `remove`, internal/scratch fields will leak into your serialized output.

**Always include all four patterns** in any final cleanup that aims for a strict whitelist:

```yaml
remove:
  - "*"
  - "__*"     # Cribl internals: __inputId, __channel, __ctrlFields, etc.
  - "_*"      # _raw, _time, _metric — only the ones you explicitly want should be in keep
  - "cribl_*" # cribl_breaker, cribl_pipe, cribl_pack, etc.
```

The same applies to a `serialize` Function's `fields:` list — see §15.G.

### 15.G. `serialize` Function `fields:` list — put excludes FIRST, `*` LAST

We observed cases where the UI surface and/or runtime order‑sensitivity caused `__*` fields to slip through into serialized output when the list was `["*", "!__*", ...]`. Reorder so the excludes come first, then `*` at the end:

<good-example>

```yaml
- id: serialize
  filter: "true"
  conf:
    type: json
    dstField: _raw
    fields:
      - "!__*"
      - "!_*"
      - "!cribl_*"
      - "!_raw"
      - "*"
```</good-example>

<bad-example>

```yaml
fields:
  - "*"
  - "!__*"
  - "!_*"
# UI/runtime ordering caused __* fields to remain in the output
```</bad-example>

### 15.H. `serialize` with `srcField: <object>` is unreliable — use `eval` + `JSON.stringify` for nested objects

When building a normalized output as a nested scratch object (e.g., `__ocsf = { activity_id: …, src_endpoint: { ip: …}, … }`), the obvious next step seems to be `serialize` with `srcField: __ocsf, type: json, dstField: _raw`. In practice we observed `_raw` staying as the **original FortiGate KVP**, not the OCSF JSON — the `serialize` Function did not consistently pull from the scratch field.

**The reliable pattern is a single `eval`:**

<good-example>

```yaml
- id: eval
  filter: "true"
  description: Emit OCSF JSON to _raw deterministically (sidesteps serialize+srcField bug)
  conf:
    add:
      - name: _raw
        value: "__ocsf ? JSON.stringify(__ocsf) : (_raw || '')"
      - name: sourcetype
        value: "'ocsf:1.4'"
    remove: []
    keep: []
```</good-example>

Use the `serialize` Function only when serializing the **event itself** (i.e., the union of top‑level fields), not a scratch sub‑object.

### 15.I. `parser` vs `serde` — different Functions, different schemas

We initially used `id: parser` with a `mode: extract`, `type: kvp` config — which is the **`serde` Function's schema**. Cribl silently accepted the YAML but the UI reported "Function parser is missing" and Data Preview produced no extracted fields.

For inline KVP / JSON / CSV extraction inside a pipeline, the correct Function is **`serde`**:

```yaml
- id: serde
  filter: "true"
  description: Extract KVP fields from _raw (FortiGate syslog)
  conf:
    mode: extract
    type: kvp
    srcField: _raw
    cleanFields: false
    allowedKeyChars: []
    allowedValueChars: []
```

Use `id: parser` only when you want to bind to a **Parser Library** entry (`lib: <parserId>`) for reusability across multiple pipelines.

### 15.J. Avoid the `code` Function for normalization work — use chained `eval`s

The `code` Function shines for true side‑effectful logic (async lookups, stateful aggregation buffers, complex multi‑pass transforms). For per‑event field mapping/normalization we found it:

- harder to read in YAML (the JS body is a folded scalar with awkward whitespace)
- harder to debug — errors surface as `code(…)` with no field‑level context
- easy to leave half‑written (empty function bodies still ship)

**Prefer:** a series of `eval` Functions, each with one or two single‑expression `add:` entries. This is exactly what `fortigate_to_ocsf_1_4`, `fortigate_to_azure_csl`, and `fortigate_to_splunk_cim` do. It diffs cleanly in Git, each step is testable in Data Preview, and the constraints from §15.A–C apply uniformly.

### 15.K. Sample files: JSON-array CONTENT + id/basename alignment

Two distinct failure modes bite here. Both are real; we hit each.

**(a) Content format — `Error parsing sample file content`.** Cribl parses every file under `data/samples/` as JSON, so the file MUST be a JSON array of event objects, e.g. `[{"_raw":"...line1..."},{"_raw":"...line2..."}]`. If you ship raw `*.log` text (one syslog line per row), opening the sample in the UI throws **`Error parsing sample file content`** and Data Preview can’t load it. Convert raw lines to a JSON array (minimum `{"_raw": <line>}` per event) and save as `data/samples/<id>.json`. Note this contradicts the old "place the raw file in `data/samples/<name>.log`" advice — the dispensary packs all store `.json` arrays, and that is the format that actually works.

A quick converter:

```bash
node -e 'const fs=require("fs");for(const f of fs.readdirSync("data/samples").filter(x=>x.endsWith(".log"))){const b=f.replace(/\.log$/,"");const a=fs.readFileSync("data/samples/"+f,"utf8").split("\n").filter(l=>l.trim()).map(l=>({_raw:l}));fs.writeFileSync("data/samples/"+b+".json",JSON.stringify(a));fs.unlinkSync("data/samples/"+f);}'
```

**(b) Resolution — `Unable to find sample with id=...`.** `samples.yml` is a MAP keyed by id, and Cribl resolves the file as `data/samples/<id>.json`. The working format has **no `fileName` field** — the top-level key must equal the on‑disk basename. We once had:

```yaml
# WRONG: key/basename mismatch + raw .log on disk
smpFortigateCapture:
  sampleName: smpFortigateCapture
  fileName: fortigate_capture.log
```

which failed with `Unable to find sample with id=smpFortigateCapture`. Fix: name the file `smpFortigateCapture.json`, key the `samples.yml` entry `smpFortigateCapture`, and drop `fileName`. `sampleName` is a cosmetic label only.

We renamed `fortigate_capture.log` → `smpFortigateCapture.json` and updated `samples.yml`'s `fileName` accordingly. After that, Data Preview resolved cleanly.

### 15.L. Cribl `local/` overlay shadows your `default/` edits — clear it after every import

Cribl stores every UI edit (or fork from an imported Pack) under `local/<pack-id>/...` and **overlays it on top of `default/`** at runtime. When you re‑import a `.crbl` with new `default/` content, Cribl's default Import mode is **Merge**, which preserves the existing `local/` overlay. So your fresh `default/pipelines/foo/conf.yml` may still appear unchanged in the UI.

Symptoms we hit:
- "I fixed the IIFE in `default/`, version‑bumped, re‑imported — but Data Preview still shows the old IIFE."
- "I added `__*` to `remove:` but the UI's Function shows `remove: []`."

**Fixes (any one works):**
1. **Manage Packs → row menu → Import** → choose mode **`Replace`** instead of `Merge`. This discards `local/` and re‑applies `default/`.
2. **Manage Packs → row menu → `Reset Pack`** → "Discard local edits". Same effect, scoped to one Pack.
3. Open each affected Function in the UI and re‑save it (this collapses `local/` ↔ `default/` for just that Function).

If you suspect this whenever changes "don't take effect", reach for option 1 first.

### 15.M. Output strategy varies per destination — pick the right one

Different downstream systems expect normalized data in different shapes. Pick **one** of these patterns per pipeline and don't mix:

| Destination | Recommended shape | How to produce it |
|---|---|---|
| Splunk HEC (CIM dataset) | `_raw` contains the CIM JSON document. Top‑level event fields are minimal (`_time`, `index`, `host`, `source`, `sourcetype`). | Build CIM fields as top‑level → final `eval` with `remove:["*","__*","_*","cribl_*"]` + `keep:[...CIM fields...]` → `serialize` with `type: json`, `dstField: _raw`, `fields: ["!__*","!_*","!cribl_*","!_raw","*"]` → second cleanup `eval` to drop the CIM fields and keep only `_raw` + routing. |
| Microsoft Sentinel (CommonSecurityLog) | **No `_raw`.** Each CSL column is a **top‑level event field**. The Sentinel destination JSON‑serializes the whole event. | Set every CSL column with `eval`. **Do not** add a `serialize` step. Final cleanup `eval` removes non‑CSL fields with `remove:["*","__*","_*","cribl_*"]` + `keep:[...CSL fields..., _time, index, host, source, sourcetype]`. |
| OCSF lake (S3/ADLS/GCS) | `_raw` is the OCSF JSON. | Build the OCSF object as a scratch field `__ocsf` via chained `eval`s → set `_raw = JSON.stringify(__ocsf)` via `eval` (NOT `serialize` with `srcField`, see §15.H) → final cleanup `eval` with `remove:["*","__*","_*","cribl_*"]` + `keep:[_raw,_time,index,host,source,sourcetype]`. |
| KVP passthrough (reduction only) | `_raw` is the reduced KVP. | After field drops, run `serialize` with `type: kvp`, `dstField: _raw`, `fields: ["!__*","!_*","!cribl_*","*"]`. |

### 15.N. The OCSF / CSL / CIM "anatomy" pattern

Every normalization pipeline in this pack follows the same 6‑step anatomy. Use it as a template:

1. **`comment`** Function — purpose, author, refs.
2. **`eval`** — set routing/identity scratch fields (e.g., `__class_uid`, severity, activity).
3. **One or more `eval` Functions, filtered by `type==…` / `subtype==…`** — populate per‑subtype scratch fields (e.g., `__src_endpoint`, `__dst_endpoint`, `__http_request`).
4. **`eval`** — assemble the final normalized object (`__ocsf`) or set the destination's top‑level fields (CSL).
5. **`eval`** (NOT `serialize` for sub‑objects) — write to `_raw` via `JSON.stringify(__scratch)`, set `sourcetype`. Skip this step for CSL (Sentinel) since fields stay top‑level.
6. **`eval`** — final cleanup with strict whitelist: `remove:["*","__*","_*","cribl_*"]` + `keep:[<the small set you want to emit>]`.

### 15.O. Per‑subtype filter discipline

Use the Function `filter:` (not nested JS branches) to scope work to a specific FortiGate `type`/`subtype`. Cribl skips the Function entirely if the filter is false, which is cheaper than evaluating a no‑op `eval` body and far easier to read in Data Preview's per‑Function inspector.

<good-example>

```yaml
- id: eval
  filter: "type=='traffic'"
  description: OCSF Network Activity (class_uid=4001) — populate src/dst endpoints
  conf:
    add:
      - name: __ocsf
        value: "Object.assign({}, __ocsf, { src_endpoint: {ip: srcip, port: srcport}, dst_endpoint: {ip: dstip, port: dstport} })"
```</good-example>

### 15.P. Local validation: the JS pipeline simulator

To avoid the import → test → re‑export loop, we built a small Node.js simulator that parses `default/pipelines/*/conf.yml`, walks the Function list, and evaluates each `eval.value` against a sample event. Key implementation notes if you (re)build it:

1. **Use a `Proxy` with a `has` trap** that returns `true` so missing field reads inside `with(event)` evaluate to `undefined` instead of throwing `ReferenceError`. Cribl does the same.
2. **Whitelist JS globals** (`Math`, `String`, `Number`, `Date`, `JSON`, `Array`, `Object`, `parseInt`, `parseFloat`, `isFinite`, `isNaN`) so they don't get shadowed by event fields of the same name.
3. **Enforce strict mode** by wrapping each value in `"use strict"; (function(){ with(event) { return (<expr>); } })()` and watch for `SyntaxError` — this catches §15.A and §15.B issues exactly the way Cribl does.
4. **Apply `keep`/`remove` semantics correctly**: `remove` patterns drop fields; `keep` exempts. `remove:["*"]` without a `keep` list nukes the whole event.
5. **Emulate `serialize`**: filter the event by `fields:` (with the same exclude‑first semantics from §15.G), then `JSON.stringify` or KVP‑serialize.

A simulator pass + diff against expected OCSF / CSL / CIM JSON catches ~95% of bugs before the `.crbl` ever reaches Cribl.

### 15.Q. Version bumping discipline (don't forget any of these)

Each shipped change requires updating **all four** of these — Cribl's upgrade detector reads `package.json.version`, the UI displays `default/pack.yml.version`, the README is what users actually read, and the archive filename is what gets uploaded:

1. `package.json` → `version`
2. `default/pack.yml` → `version`
3. `README.md` → new `## Changelog` entry under `### Version X.Y.Z — YYYY-MM-DD`
4. Rebuild the archive with **GNU tar**: `gtar -cvz --exclude .DS_Store --exclude .git --exclude '*.crbl' -f <pack>_<X.Y.Z>.crbl package.json README.md default data` (never macOS `tar` — see §12.2)

### 15.R. Things we tried that did NOT work (don't waste time)

- **`(function(){…})()` IIFE in `eval.value`** — rejected; see §15.A.
- **`code` Function with a return expression** — runs, but rapidly becomes unreadable and we hit silent empty‑body bugs.
- **`serialize` with `srcField: __ocsf`** — `_raw` was not updated reliably; see §15.H.
- **`keep:[...]` without `remove:["*"]`** — does NOT whitelist; see §15.E.
- **`remove:["*"]` without explicit `__*`, `_*`, `cribl_*`** — internal fields leak; see §15.F.
- **Bare `value: null`** — UI rejects with "field required"; see §15.C.
- **Re‑importing with `Merge` mode expecting the new `default/` to apply** — `local/` overlay wins; see §15.L.
- **Shipping raw `*.log` text as sample files** — Cribl parses `data/samples/*` as JSON, so opening the sample throws `Error parsing sample file content`. Ship a JSON array of `{"_raw": …}` objects as `<id>.json`; see §6.4/§15.K.
- **Free‑form `comments` in `route.yml`** — the Routes `comments` field is a structured array; a list of plain strings makes the whole Routes config fail to load and the UI shows a single empty Route. Use `comments: []` (and give each Route the full field set: `id, name, final, disabled, pipeline, description, enableOutputExpression, outputExpression, filter, clones, output`).
- **Building `.crbl` with macOS/BSD `tar` (`tar -czf` / even `tar --format=ustar -czvf`)** — install fails with `ENOENT: …/default/pack.yml` despite the file appearing in `tar -tzf`. Always use `gtar`; see §12.2.
- **API upload alone (`PUT …/packs?filename=`)** — only stages a temp file (`{"source":"….<random>.crbl"}`). Without Install/Upgrade → Commit → Deploy the pack never activates; guessing POSTs without that `source` yields `Missing required parameter: source` / `Pack name cannot be empty`. Full recipe in §13.
- **Re-install via POST when the pack already exists** — fails with `Pack Id conflicts with existing Pack`. Prefer `PATCH …/packs/<pack-id>` with `{"source":"…"}` to upgrade in place; DELETE + re-POST only for intentional wipe.
- **`C.vars.*` in Aggregations `timeWindow` (or other static toggles)** — silently fails / errors; `timeWindow`, `passthrough`, `metricsMode`, `cumulative`, `flushOnInputClose`, `sufficientStatsOnly` are literal config only. See §4.
- **Wrapping pack variables under a top-level `vars:` key in `default/vars.yml`** — Cribl ignores the custom IDs. Knowledge → Variables shows only sample leftovers (`cribl.sourceA`, `unixtime`, …); `C.vars.MY_VAR` is `undefined`. Use top-level IDs + `lib: custom` (see §6.5). Observed 2026-08-17 on `cribl-timezone-anomaly-detector`.
- **Wrapping Event Breakers under a `breakers:` key** — same silent-nothing failure as `vars:`. Unlike `inputs.yml`/`outputs.yml`, `breakers.yml` is keyed by ruleset *name* at the top level. Cribl's own `$CRIBL_HOME/default/cribl/breakers.yml` is the reference (`AWS Ruleset:` at column 0, with `lib: cribl`). See the table in §6.3.
- **Copying `schedule.run.earliest: "-15m"` / `latest: "now"` out of a working standalone collector into `jobs.yml`** — valid in the Collector UI, fatal in a Pack: they are numbers in `SavedJobCollection`, and the pack then fails AJV *on load*, breaking the whole Packs UI with `handleClusterCall`. Omit them; build the window in `collectRequestParams`. See §6.1b and §15.T.
- **Omitting `pipeline` on a catch-all Route** — earlier guidance said to leave it empty for a no-op. `RouteConf` **requires** it; an empty/absent value fails validation on load. Use the built-in `passthru` (not `devnull`, which discards the events).
- **Hand-converting a collector's JSON into `jobs.yml`, or a pipeline's JSON into `conf.yml`** — the pipeline case drops a nesting level (`{id, conf:{…}}` → the *inside* of `conf`) and the id becomes the map key or directory name. Easy to get subtly wrong, and the failure is a pack that installs but does nothing. Use `scripts/pack-json-to-yaml.py` (§6.7).
- **Iterating on a pack-hosted REST Collector by rebuilding the `.crbl`** — collectors in a Pack need a Commit & Deploy before they run at all, and there is no Run → Preview in the Pack UI. Debug as standalone JSON at group level first; see §15.U.

### 15.S. Silent expression failures — `C.vars.*` and undefined references

Cribl does NOT throw on expression evaluation errors in `eval` Functions. If an expression references `C.vars.MISSING_VAR` or any undefined value, the field assignment is **silently skipped**. The event passes through unchanged. There is no error in the UI, no error in the logs, and Data Preview shows the event without the expected field.

This is the most insidious failure mode in pack development — the pipeline appears "installed" and "healthy" but produces no output fields. Events flow through completely unmodified.

**Debugging checklist when eval "does nothing":**

1. **Verify `vars.yml` loads correctly** — API: `GET /api/v1/m/<group>/p/<packId>/lib/vars`. Confirm your custom IDs appear in `items[].id`. If they are missing (and you only see `unixtime` / `cribl.sourceA` / similar), the vars file format is wrong (see §6.5 — usually a wrapping `vars:` key or missing `lib: custom`).
2. **Check that variable values are strings** — even numbers must be `"900"` not `900` in `vars.yml`.
3. **Check that string literals have inner quotes** — `"'my_string'"` not `"my_string"`. Without inner quotes, Cribl evaluates the bare word as a JS identifier (which is undefined).
4. **Test each expression in isolation** — use Data Preview with hardcoded values before referencing `C.vars.*`. If the hardcoded version works but the `C.vars` version doesn't, the problem is in vars resolution.
5. **Check for silent `undefined` propagation** — if `C.vars.X` is undefined and you use it in arithmetic (`C.vars.X * 1000`), the result is `NaN`, which Cribl may assign to the field or skip entirely depending on context.

**Common root causes (ordered by frequency):**
- `vars.yml` wraps entries under a `vars:` key instead of top-level IDs (see §6.5)
- Missing `lib: custom` on pack-authored variables
- `vars.yml` uses list format instead of map format (see §6.5)
- `value` field contains a bare number instead of a string
- String value missing inner quotes (evaluates as undefined identifier)
- Variable name typo (`C.vars.THRESHHOLD` vs `C.vars.THRESHOLD`)
- Pack was imported but vars weren't saved (re-import with Replace mode)

### 15.T. A Pack that fails AJV **on load** takes out the whole Packs UI

There are two different validation moments and they fail very differently.

| Moment | Symptom |
|---|---|
| **Install** (`Add Pack`) | `failed to install: <AJV keyword>` — no field path, but the pack is simply not installed. Annoying, recoverable. |
| **Load** (after install, on every leader restart) | The pack stays **registered but unloaded**, and every Pack API call then throws `Cannot read properties of undefined (reading 'handleClusterCall')` — which breaks the **entire Packs UI for every pack in the group**, not just yours. |

The second one is the dangerous one, because nothing points at your pack. Causes we have actually hit:

- `schedule.run.earliest` / `latest` as relative-time strings in `jobs.yml` (§6.1b)
- a Route with no `pipeline` (RouteConf requires it — use `passthru`)
- a Route comment with no `index` (RouteComment requires it)
- free-form strings in `route.yml`'s `comments` instead of `{id, index, comment}` objects

All four are caught by `scripts/pack-validate.py`. If you are already in this state: delete the pack via the API (`DELETE /api/v1/m/<group>/packs/<pack-id>`) to get the UI back, then fix and re-install.

### 15.U. Collector packs cannot be tested from the Pack UI

A collector-based Source inside a Pack does not run until the Worker Group has had a **Commit & Deploy** — there is no Run → Preview from inside the Pack. If you try to iterate on a REST Collector by rebuilding the `.crbl` each time, every single change costs an upload, install, commit and deploy.

Build and debug the collector as **standalone JSON at Worker Group level**, where Run → Preview is instant, and only fold it into the pack once it works. §6.7 has the conversion and the loop.
