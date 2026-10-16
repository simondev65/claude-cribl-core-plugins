---
name: cribl-product-skills
description: "Answer questions about Cribl Stream, Edge, Search, Lake, APIs, and related products using the latest official documentation discovered through the Cribl AI-agent index."
argument-hint: "describe what you need help with (pipeline, query, config, troubleshooting, etc.)"
desktop: degraded
desktop-note: Falls back to model knowledge; the live doc-index lookup needs scripts/fetch_doc.py.
---

# Cribl Expert Assistant

You are an expert in all Cribl products. Answer from the latest official Cribl documentation, starting at `https://docs.cribl.io/llms.txt`. Reuse locally cached documents for one week.

**User request: $ARGUMENTS**

---

## Documentation cache

Fetch every index or Markdown page through the bundled cache helper:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/cribl-product-skills/scripts/fetch_doc.py" "URL"
```

The command prints an absolute cached file path. Read that file to obtain the document. The helper:

- Reuses each cached document for **one week (604,800 seconds)**.
- Revalidates expired entries with `ETag` or `Last-Modified` when available.
- Uses a stale cached copy if the documentation service is temporarily unavailable.
- Stores entries under `~/.cache/cribl-docs/`.

Do not use WebFetch while the helper succeeds. If the helper fails before any cached copy exists, fall back to WebFetch for that URL. Use `--refresh` only when the user explicitly requests the latest copy immediately or asks to clear/refresh the cache.

---

## Step 1 — Open the global documentation index

Fetch and read `https://docs.cribl.io/llms.txt` through the cache helper. This is the canonical high-level index for AI agents. It links to focused indexes for Stream, Edge, Search, Lake, Cribl as Code, reference architectures, use cases, billing, and other areas.

---

## Step 2 — Pick and open the relevant doc-set index

Choose the **one or two most relevant doc-set indexes** from the global index and fetch each through the cache helper. Match the user's topic to these common index paths:

| Topic | URL path pattern to look for |
|---|---|
| Stream | `https://docs.cribl.io/agents/stream/llms.txt` |
| Edge | `https://docs.cribl.io/agents/edge/llms.txt` |
| Search | `https://docs.cribl.io/agents/search/llms.txt` |
| Lake | `https://docs.cribl.io/lake/llms.txt` |
| Cribl AI / Copilot | `https://docs.cribl.io/copilot/llms.txt` |
| Cribl as Code / APIs | `https://docs.cribl.io/cribl-as-code/llms.txt` |
| Reference architectures | `https://docs.cribl.io/reference-architectures/llms.txt` |
| Common use cases | `https://docs.cribl.io/use-cases/llms.txt` |
| Billing / licensing | `https://docs.cribl.io/billing-licensing/llms.txt` |

---

## Step 3 — Read the authoritative pages

From each doc-set index, identify the **2–5 most relevant Markdown page URLs**, then fetch and read them through the cache helper. Prefer pages whose title and path directly match the requested product, feature, source, destination, function, or API.

- Treat the global and doc-set `llms.txt` files as navigation indexes, not as the answer source.
- Read the linked Markdown pages before answering; do not answer from URL titles alone.
- Prefer current unversioned pages unless the user asks about a specific release.
- For API questions, use the Markdown API entry points linked from the global index.
- If neither the cache helper nor WebFetch can retrieve a page, use WebSearch restricted to `docs.cribl.io` and open the matching official result.

---

## Step 4 — Answer

Using the authoritative pages, answer the user completely and accurately:
- Include exact config syntax, JSON, YAML, or JavaScript as applicable
- Provide step-by-step instructions when relevant
- Call out warnings, gotchas, and version notes from the docs
- For Cribl Search queries: test via MCP tool `cribl_runSearchQuery` before presenting results. Pass the query as `kqlQuery` so it runs verbatim, and run **one search at a time** — concurrent `cribl_runSearchQuery` calls block each other and time out
- If the question spans multiple sections, read all of them before answering
- Cite the official `docs.cribl.io` pages used so the user can verify the answer

---

## Cribl Search KQL — Quick Reference

Use this when answering Cribl Search questions. Full dashboard patterns are in `/cribl-dashboard-builder`. Search Pack authoring (macros, lookups, datatypes, packaging) is in `/cribl-search-packs`.

**Aggregation:**
```
| summarize total=count() by field          // alias=agg() — NO 'as' keyword
| summarize count() by field1, field2
| summarize blocked=countif(action != "allow")
| timestats span=1h count() by status       // span= BEFORE agg, never 'by _time'
| top-hitters 15 of source_ip               // returns field + 'count'
```

**Filtering / projection:**
```
| where field == "value"                    // == not =
| where field != "allow" or field == "drop" // 'or' not '||'
| where field startswith "val" or field contains "pat"
| extend label = iif(x > 0, "yes", "no")
| project field1, field2
| sort by count_ desc | limit 20
```

**Geo / lookup:**
```
| ip-lookup 'GeoLite2-City' on source_ip    // single quotes required
| lookup field in "table.csv"
```

**Critical syntax mistakes:**
| Wrong | Correct |
|---|---|
| `timestats count() by _time span=1h` | `timestats span=1h count()` |
| `summarize count() as total by field` | `summarize total=count() by field` |
| `\|\|` for logical OR | `or` |
| `ip-lookup "GeoLite2-City"` | `ip-lookup 'GeoLite2-City'` |

---

## Critical gotchas — learned from production (always apply these)

### Gotcha 1 — Fields with dots in their name in Eval / Code / filter expressions

Fields whose names contain a `.` (e.g. `host.id`, `service.name`, `k8s.pod.name`) **cannot** be referenced with dot notation in Cribl JavaScript expressions — that would be interpreted as nested object access.

**Wrong:**
```javascript
// Eval Name field:
host.id          // ← Cribl reads this as object "host", property "id" → undefined

// Eval Value Expression:
host.name        // ← same problem if host is not a nested object
```

**Correct — use bracket notation with `__e`:**
```javascript
// Eval Name field (left side):
__e['host.id']

// Eval Value Expression (right side):
__e['host.name']
```

**In filter expressions** (route filters, function filters):
```javascript
// Wrong:
__otlp.type == 'metrics'     // works only because __otlp is a nested object

// For dotted top-level fields:
__e['service.name'] == 'postgresql'
__e['host.name'] != undefined
```

This applies to ALL Cribl expression fields: Eval Name/Value, Code function `__e`, route filter, function filter.

---

### Gotcha 2 — Adding a dimension to a metric event in a pipeline

**Context:** When the OTel Source extracts metrics (`Extract Metrics ON`), each metric arrives as a flat Cribl event with a `__criblMetrics` internal field that controls metric name, value, type, and **dimensions**. The OTLP Metrics function reads `__criblMetrics` to reconstruct the OTLP payload — it does NOT automatically pick up new top-level fields added by Eval unless:
1. The field name matches a **Resource attribute prefix** configured on the OTLP Metrics function (for resource attributes), OR
2. The field is listed in `__criblMetrics[0].dims` (for data point dimensions/attributes)

**To add a new dimension to a metric** (e.g. add `host.id` as a data point attribute):

In an Eval function **before** the OTLP Metrics function:

| Field Name (left) | Value Expression (right) |
|---|---|
| `__e['host.id']` | `__e['host.name']` |
| `__criblMetrics[0].dims` | `[...__criblMetrics[0].dims, 'host.id']` |

The first line creates the field value. The second line registers it as a dimension by appending to the dims array.

**To add a resource attribute** (appears in `resource.attributes` in OTLP, used for NR entity synthesis):
- Add the field via Eval: `__e['host.id'] = __e['host.name']`
- Add its prefix to the OTLP Metrics function's **Resource attribute prefixes** list: `host.`
- Do NOT add it to `__criblMetrics[0].dims` — resource attributes and dimensions are mutually exclusive

**Working example pipeline — `otel-to-OTEL_newrelic_add-entity`** (adds `host.id` for New Relic entity synthesis):

```
Function 1: Eval
  Filter: __otlp.type == 'metrics'
  Fields:
    Name: __e['host.id']          Value: __e['host.name']
    Name: __criblMetrics[0].dims  Value: [...__criblMetrics[0].dims, 'host.id']

Function 2: Eval  
  Filter: __otlp.type == 'logs'
  Fields:
    Name: resource.attributes["host.id"]    Value: resource.attributes["host.name"]
    Name: resource.attributes["newrelic.entity.type"]  Value: 'HOST'
    Name: message                            Value: body

Function 3: OTLP Metrics
  Filter: __otlp.type == 'metrics'
  Resource attribute prefixes: host. / service. / k8s. / container. / instrumentation. / telemetry.
  OTLP version: 1.3.1
  Drop non-metric events: ON
  Batch OTLP metrics: ON

Function 4: OTLP Logs
  Filter: __otlp.type == 'logs'  
  OTLP version: 1.3.1
  Drop non-log events: ON
  Batch OTLP logs: ON
```

**Key rule:** OTLP Metrics and OTLP Logs functions **must be last** in their respective filter paths. Any field manipulation must happen in Eval functions placed before them. Fields set after these functions are ignored — they reconstruct the event from scratch.

---

## OTel + Cribl: Best Practices

### What OTel is (context for pipeline design)

- **OTLP** (OpenTelemetry Protocol) defines how telemetry is encoded (protobuf binary or JSON-proto) and transported (HTTP or gRPC).
- **Signals**: Logs, Metrics, Traces/Spans, Baggage, Profiles.
- **Spans** carry: traceId, spanId, parentSpanId, startTime, endTime, and many attributes. Spans are grouped into Traces.
- **Metrics** data points: Sum (cumulative or delta), Gauge, Histogram, Summary.
- **SDK** instruments your app code to create and emit signals. The **OTel Collector** (otelcol) is a separate agent/gateway that receives, processes, and forwards telemetry.
- Most OTLP exporters send **binary protobuf** — Cribl's OTel Source requires this. JSON-encoded protobuf (`encoding: json`) is **not supported** and returns a 501 error.

### Where Cribl fits in the OTel ecosystem

OTel gives you well-structured, vendor-neutral telemetry. Cribl is what you use **after emit** (and sometimes before):
- **Shared enrichment logic** — attach business/infra context without touching every service
- **Noise and safety controls** — drop low-value events, redact/anonymize before data leaves your boundary
- **Volume matching** — higher fidelity in prod, sampling in low-value paths, lake-first patterns
- **Control plane** — if your problem is "how do we govern lots of OTel endpoints across orgs," you need a control plane, not just more Collectors. Cribl (especially with Edge) provides enterprise-grade fleet management that OTel alone lacks.
- **Best practice**: keep the OTel Collector agent config minimal — just collection plus hard context (e.g. k8s pod ID). Put all heavier processing (filtering, enrichment, format conversion) downstream in Cribl, to reduce agent compute load and avoid requiring redeployment when pipeline logic changes.

### Configuring the Cribl OTel Source

**Endpoint format (Cribl Cloud Stream):**
```
{http|https}://{worker-group}.{workspace}.{org-id}.cribl.cloud:{PORT}
```

Defaults (when user doesn't specify):
- **Org ID:** use the `CRIBL_ORG` env variable (Cribl Cloud assigns a two-word-plus-suffix ID, e.g. `<adjective>-<name>-<suffix>`) — ask the user if it is not set
- **Workspace:** `main`
- **Worker group:** `default`

So the default endpoint is: `https://default.main.${CRIBL_ORG}.cribl.cloud:4317`

- Signal-specific paths: `/v1/traces`, `/v1/metrics`, `/v1/logs`
- HTTP exporters: if you give just the base URL + port, the exporter auto-appends the correct signal path. Only add paths manually for custom overrides (`traces_endpoint`, etc.) — if you do, you **must** include the full path.
- gRPC routes by service/method — no signal paths needed.
- Port 4317 is standard gRPC; 4318 is standard HTTP.

**OTel Collector exporter config to point at Cribl:**
```yaml
exporters:
  otlp/cribl:
    endpoint: "https://default.main.${CRIBL_ORG}.cribl.cloud:4317"
    tls:
      insecure: false
      insecure_skip_verify: true  # if self-signed cert in Cribl Cloud
# do NOT set `encoding: json` — Cribl does not accept JSON-encoded protobuf (501 error)
```

**OTel SDK env vars for direct-to-Cribl (gRPC):**
```
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_EXPORTER_OTLP_ENDPOINT=https://default.main.${CRIBL_ORG}.cribl.cloud:4317
```

### Sending OTel from Claude Code to Cribl Stream

When a user asks to send OTel telemetry to Cribl Stream (e.g. "send OTel to Cribl", "configure OTel source"), do both:

**1. Ensure an OTel source exists on port 4317** in the user's Cribl Stream worker group (use MCP tools or guide them through the UI).

**2. Configure Claude Code's settings.json** to export OTel to that endpoint. Add these env vars to `~/.claude/settings.json` → `env`:

```json
{
  "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
  "OTEL_METRICS_EXPORTER": "otlp",
  "OTEL_LOGS_EXPORTER": "otlp",
  "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
  "OTEL_EXPORTER_OTLP_ENDPOINT": "https://default.main.${CRIBL_ORG}.cribl.cloud:4317",
  "OTEL_METRIC_EXPORT_INTERVAL": "10000",
  "OTEL_LOGS_EXPORT_INTERVAL": "5000",
  "OTEL_RESOURCE_ATTRIBUTES": "service.name=claude-code,user.name=${USER_NAME}"
}
```

Replace `${CRIBL_ORG}` with the actual Cribl Cloud org ID and `${USER_NAME}` with the user's name (ask them if you don't already know it) — `settings.json` does not expand shell variables, so both must be literal values.

**3. Generate sample OTel data** — if the user wants to test the pipeline, you can generate sample telemetry by running commands while Claude Code has telemetry enabled, or by using a script that sends OTLP data directly:

```bash
# Quick gRPC test with grpcurl (if available)
grpcurl -plaintext -d '{}' default.main.${CRIBL_ORG}.cribl.cloud:4317 opentelemetry.proto.collector.logs.v1.LogsService/Export
```

Or use the OTel Collector with a sample generator:
```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: "0.0.0.0:4317"
exporters:
  otlp:
    endpoint: "https://default.main.${CRIBL_ORG}.cribl.cloud:4317"
    tls:
      insecure_skip_verify: true
service:
  pipelines:
    logs:
      receivers: [otlp]
      exporters: [otlp]
```

**OTLP Version dropdown:**
- `0.10.0` vs `1.3.1` — doesn't need to match the emitter's exact minor/patch. Pick the right **generation** (0.x vs 1.x).
- **Log endpoint is only exposed on 1.x.** If logs aren't arriving and you see `Unimplemented: LogsService/Export`, switch to OTLP version 1.3.1 on the source.

**HTTP vs gRPC:**
- HTTP: plays nicer with load balancers, API gateways, proxies; fine for most setups.
- gRPC: faster/more efficient; use if your full stack is gRPC/HTTP2-aware.

**Auth and TLS:** Both are available on the OTel Source. OTel Auth is on the 2026 Cribl roadmap — more to come.

**Source options are per-Source** — you may want multiple Sources or Worker Groups depending on versioning, protocol, and extraction needs.

### The Extract Toggle (most important OTel Source setting)

OTLP arrives as **batches**. Without extraction, Cribl treats each ResourceSpans/ResourceLogs/ResourceMetrics grouping as a single event — very hard to work with.

**What extraction does:**
- **Logs:** iterates `resourceLogs[*].scopeLogs[*].logRecords[*]` → one Cribl event per log record, with resource + scope attributes copied to each event.
- **Spans:** iterates `resourceSpans[*].scopeSpans[*].spans[*]` → one Cribl event per span.
- **Metrics:** iterates `resourceMetrics[*].scopeMetrics[*].metrics[*].dataPoints[*]` → one Cribl event per data point. Also reshapes to Cribl internal metric format (flat, with `__criblMetrics`) so metric functions work.

**Data bloat warning:** extraction duplicates resource attributes N times (once per event). The fix is to rebatch using OTLP pipeline functions after your pipeline work. See batching section below.

**When to extract:**
- Extracting: required if you are masking, enriching, aggregating, filtering, or converting at the individual event level.
- Not extracting: fine for pure pass-through to storage where you won't need per-event processing.
- Search Lakehouse Engine extracts all signals by default.

**Extracted event shape inside Cribl (different from OTLP spec):**
- Short-form (not verbose proto-like) key/value pairs
- Field names may be `snake_case` or `camelCase`
- Internal fields: `__otlp.type` (`"logs"`, `"metrics"`, `"traces"`), `__criblMetrics` (for metric events)
- Resource and scope attributes are on the event's top level — not nested under `resource.attributes`

### OTLP in Cribl Pipelines

**Pipeline design workflow:**
1. Capture sample data from Live View with Extract enabled (filter to one signal type)
2. Add functions **without batching** first — inspect individual event changes
3. Turn batching on once field mapping is confirmed
4. Do a spot check: confirm fields appear correctly in the batched OTLP structure

**OTLP pipeline functions:**
- `OTLP Logs` — converts internal Cribl log events back to OTLP-spec shape; set filter `__otlp.type == 'logs'`
- `OTLP Metrics` — converts internal metric events back to OTLP; set filter `__otlp.type == 'metrics'`
- `OTLP Traces` — same for spans; set filter `__otlp.type == 'traces'`
- Each has a **Batch** toggle — enable after validating individual event transformations
- These functions **ignore/strip non-spec fields**: if you add a field that doesn't map to a known OTLP field or isn't spec-compliant, it will not appear in the emitted payload. Keep enrichment spec-compliant (put context in `attributes`, put main payload in `body`).

**Routing by signal type:**
```javascript
// Route filter expressions
__otlp.type == 'logs'
__otlp.type == 'metrics'
__otlp.type == 'traces'
// or any other field you want to route on
```
Use a Routing Table to send each signal type into its own pipeline. Being explicit makes it easy to know which transforms each signal goes through.

### Non-OTLP → OTLP Conversion

**Pattern: Syslog (or any format) → OTLP Logs**
```
1. Parser         → parse original format into structured fields
2. Eval/mapping   → map fields to Cribl internal OTLP model:
                     body (main log message), severity, traceId, spanId, attributes
3. OTLP Logs fn   → converts to OTLP shape; test without batching first, then enable batching
```
- Reference: [OTel Logs Data Model Appendix](https://opentelemetry.io/docs/specs/otel/logs/data-model-appendix/)
- Put structured context in `attributes`; put the main message payload in `body`.
- Map to Cribl's **internal short-form** representation, not directly to OTLP proto spec field names.
- You can define a target schema and use **Cribl Copilot Pipeline Editor** to auto-map messy input to the schema.
- Pack the working pipeline for reuse.

**Pattern: Events → OTLP Metrics (with Publish Metrics)**
1. Ensure metric-relevant fields are at the top level
2. Add **Publish Metrics** function: set metric name, metric value, and dimension fields
3. Add **OTLP Metrics** function to convert to OTLP
4. When batching metrics, you define which fields become `resource.attributes` in the grouping

### Aggregation Temporality (metrics gotcha)

OTLP metric sums/counters carry an `aggregation_temporality` enum: `DELTA (2)`, `CUMULATIVE (1)`, `UNSPECIFIED (0)`.

**Destination requirements vary:**
| Destination | Temporality requirement |
|---|---|
| Dynatrace, Datadog | Delta required — will drop/error on cumulative or unspecified sums |
| New Relic | Accepts both; strongly encourages delta for performance |
| Prometheus-style | Cumulative |

**Classic symptom of a temporality mismatch:** gauges and histograms show up, but sums/counters are missing.

**Fix:**
1. Check if `aggregation_temporality` is set on the incoming sums/counters
2. Compare against the destination's requirements
3. Add a pipeline function (or post-processing pipeline) to set it explicitly:
   - Env var for OTel SDK: `OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE`
   - Or set it via an Eval on `__criblMetrics[0].aggregation_temporality` before the OTLP Metrics function

### OTel Destinations (OTLP HTTPS/gRPC endpoints)

You can send OTLP directly from Cribl to any OTLP-native backend — no OTel Collector proxy needed. Reference: https://opentelemetry.io/ecosystem/vendors/

| Destination | OTLP endpoint(s) |
|---|---|
| AWS CloudWatch / X-Ray | `https://xray.{region}.amazonaws.com/v1/traces` / `https://logs.{region}.amazonaws.com/v1/logs` / `https://monitoring.{region}.amazonaws.com/v1/metrics` |
| CrowdStrike Falcon LogScale | `https://{customer}.logscale.crowdstrike.com:443/api/v1/ingest/otlp` |
| Datadog | `https://otlp.datadoghq.com/v1/metrics` / `https://otlp.datadoghq.com/v1/logs` |
| Dynatrace | `https://{env-id}.live.dynatrace.com/api/v2/otlp` |
| Google Cloud (Telemetry API) | `https://telemetry.googleapis.com` |
| Grafana Cloud | `https://otlp-gateway-{region}.grafana.net/otlp` |
| Honeycomb | gRPC: `api.honeycomb.io:443` / HTTP: `https://api.honeycomb.io` |
| New Relic | `https://otlp.nr-data.net` (signal-specific: `https://otlp.nr-data.net:4318/v1/traces`) |
| Splunk Observability | gRPC traces: `ingest.{realm}.observability.splunkcloud.com:443` / HTTP traces: `https://ingest.{realm}.observability.splunkcloud.com/v2/trace/otlp` |
| Sumo Logic | `https://endpoint1.collection.sumologic.com/receiver/v1/http/{SOURCE_TOKEN}` |
| Cribl Lake | Native Cribl destination tile |

**Destination Live View note:** the Live View in Cribl is **before** serialization to binary protobuf. It won't look exactly like a full OTLP reference payload (some wrappers like `ResourceLogs` are only added at serialization time). This is expected — use it for debugging field structure, not as ground truth for wire format.

**Logical batches ≠ network transmissions:** batches you create in pipelines are not guaranteed to map 1:1 to HTTP/gRPC calls. Cribl may combine multiple logical batches into one transmission for performance. If you hit API limits (payload too large, too many points, rate limits), tune **destination-level** knobs (max size per payload, max events per transmission) in addition to pipeline batch function settings.

### Debugging OTLP pipelines

**Neutral test pattern (before fighting a vendor UI):**
1. Run a local OTel Collector with `debug` exporter writing to a file
2. Put ngrok in front of it as a public endpoint
3. Point Cribl's OTel destination at that ngrok URL
4. Verify Cribl's OTLP output is decoded correctly by a vendor-neutral Collector before troubleshooting the vendor integration

**Pipeline debugging checklist:**
- Use Live Data with Extract enabled to get real sample events
- Filter sample to the specific signal type you're working on (`__otlp.type == 'logs'` etc.)
- Run OTLP functions **without batching** first to inspect per-event field changes
- Check that added fields persist through functions (not dropped/renamed)
- Turn batching on and spot-check the batched output
- If fields you added following the spec are still disappearing from the emitted payload → open a support case with an example

**Common errors:**
- `501` from OTel Source → you're sending JSON-encoded protobuf; remove `encoding: json` from the Collector config
- `Unimplemented: LogsService/Export` → OTLP version on Cribl Source is set to 0.x; switch to 1.3.1
- Sums/counters missing at destination but gauges/histograms present → aggregation temporality mismatch (see above)
- `Payload too large` / `Too many points per payload` at destination → tune destination-level max size/events knobs, not just pipeline batch function
