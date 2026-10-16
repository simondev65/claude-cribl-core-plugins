# Splunk SimpleXML Advanced Feature Handling

Reference for the Splunk SimpleXML features that don't map cleanly through the base SPL→KQL table in `SKILL.md`. Load this when the source XML contains any of: `<change>`, `<condition>`, `<set token>`, `<unset token>`, `<drilldown>`, `<selection>`, `<finalized>`, `<done>`, `depends="…"`, `rejects="…"`, `script="…"`, `stylesheet="…"`, inline `<html>`, `<viz type="leaflet_maps_app…">`, `printgeocode`, `loadjob`, `from datamodel:`, or `<input type="multiselect">`.

**Ground truth (verified 2026):** Cribl Search dashboards support four input types (`timerange`, `text`, `number`, `dropdown`), three interaction actions (run search, open link, add value to input), parent-search sharing (`parentSearchId`), and two map modes (Choropleth, Geo/marker). No multiselect, no checkbox, no reactive-token engine, no chart brush, no forward/reverse geocoder, no custom JS/CSS/HTML, no datamodel operator, no arbitrary job-SID references. Design conversions around those constraints; do not fabricate schema fields.

---

## 1. Reactive tokens (`<change>`, `<condition>`, `<set/unset token>`)

Splunk fires token side-effects on input change and search completion. Cribl has no equivalent event bus. Handle each Splunk pattern as follows:

| Splunk pattern | Cribl handling |
|---|---|
| `<input><change><condition value="1"><set token="X">y</set></condition></change></input>` (checkbox flips a control token) | Merge the derived state into the query directly with `iif`/`case` off the input, or drop the derivation and expose the raw input. |
| `<search><done><set token="earliestTime">$result.earliestTime$</set></done></search>` (a helper search computes tokens for downstream panels) | Fold the computation into every downstream query as a leading `\| extend` block, or precompute in the parent search. Do not emit an invisible helper panel. |
| `<search><finalized><condition match="'job.resultCount' = 1"><set token="d_name">$result.d_name$</set></condition></finalized></search>` (auto-select when one row returns) | Not achievable. Require the user to click the row (see §3 Drilldown → Interactions), or filter downstream panels with a `\| where` that assumes user selection. |
| `<progress><unset token="X"></unset></progress>` (clear tokens during load) | No equivalent — omit. Downstream panels will simply re-run when their input tokens change. |

**Panel gating (`depends="$token$"`, `rejects="$token$"`)** — no dashboard-level visibility gate exists. Two acceptable substitutes:
- Emit the panel unconditionally; its query returns zero rows when the gating input is empty (`\| where "$token$" != ""`). Users see an empty state instead of a hidden panel.
- Move the gated content to a second dashboard and link via an Interaction ("Add value to dashboard input" on a target dashboard).

Never invent a `depends` / `hidePanel` / `visibleWhen` field on Cribl elements — the API silently accepts unknown properties and the panel will still render.

---

## 2. Query-populated multiselect and checkbox

Splunk `<input type="multiselect">` with a `<search>` for choices, and `<input type="checkbox">`, both have **no native Cribl equivalent** — Cribl supports only single-value Dropdown, Text, Number, and Time Range.

Fallback matrix:

| Source input | Cribl substitute | Query pattern |
|---|---|---|
| Multiselect with a small enumerated `<choice>` set | `input.dropdown` with an added `"All"` option; user picks one at a time. | `\| where "$token$" == "All" or field == "$token$"` |
| Multiselect populated by a search | `input.dropdown` sourced from the same query, `\| summarize by field \| project field`. Multi-value is lost. | Same as above; note the loss in the migration report. |
| Multiselect where the user genuinely needs to pick N values | `input.text` with an instruction ("comma-separated"); parse in the query. | `\| extend __sel = split("$token$", ",") \| where array_length(__sel) == 0 or field in (__sel)` — verify `in` on a dynamic array works against the target dataset engine; fall back to `\| where "$token$" == "" or _raw contains "$token$"` for text-body scans. |
| Checkbox (bool token) | `input.dropdown` with two static-looking options (`Yes` / `No`), or a Text input defaulting to `"1"`/`""`. | `\| where "$flag$" == "1"` |

Always flag every downgrade in the migration report so the user knows they lost the multi-value UX.

---

## 3. Table drilldown → Cribl Interactions

Splunk's `<drilldown><set token="X">$row.field$</set></drilldown>` translates cleanly to Cribl's Interactions on `list.table` and most chart panels (**not** `chart.map` or gauges — Interactions are unsupported there).

Available Interaction tokens in Cribl (verified from `/search/dashboard-interactions/`):
- `$value$` — the clicked cell value
- `$field.name$` — the clicked column name
- `$field.value$` — the clicked value (same as `$value$` for tables)
- `$rowData.<fieldname>$` — any other column in the same row
- `$earliest$`, `$latest$` — from the panel's current time range
- `$environment.*$` — workspace metadata

Three action types:

```json
"interactions": [
  {
    "type": "runSearch",
    "trigger": "click",
    "query": "dataset=\"netmotion\" \n| where d_name == $rowData.d_name$ \n| sort by _time",
    "openIn": "sameTab"
  },
  {
    "type": "openLink",
    "trigger": "click",
    "url": "https://internal.example.com/user/$rowData.user$",
    "openIn": "newTab"
  },
  {
    "type": "addValueToInput",
    "trigger": "click",
    "targetDashboardId": "this_dashboard",
    "targetInputId": "d_name_filter",
    "value": "$rowData.d_name$"
  }
]
```

Rules:
- Include the `interactions` array at the **element level**, alongside `search` and `config` — not inside `search`.
- The `addValueToInput` type is the direct analog to Splunk `<drilldown><set token>`; use it for the "click a user → filter every downstream panel" pattern.
- If the source panel that hosts the drilldown has its own time picker, either wire the interaction to a Time Range Input directly, or omit time propagation — mismatched time state breaks the interaction.

For the ERT dashboard's `<drilldown><set token="d_name">$result.d_name$</set></drilldown>` on the user search table, this becomes a single `addValueToInput` interaction pointing to a `d_name_filter` Dropdown that all downstream panels reference.

---

## 4. Chart brush / range selection (`<selection>`)

Splunk `<chart><selection><set token="earliestTimeF">$start$</set></selection></chart>` lets the user drag on a chart to set a time window. **Cribl has no equivalent** — Interactions fire on single-point click only, not drag-select.

Options:
- **Remove the selector chart** and let the user narrow with the top-level Time Range Input.
- **Replace with a second Time Range Input** labeled "Narrower window" and require the user to type or pick a range from the input, referenced by downstream panels as `$TIME_NARROW.earliest$` etc.

Flag the loss of drag-brush UX in the report.

---

## 5. `loadjob $sid$` and cross-panel result reuse

Splunk `| loadjob $search_base_sid$` reuses another panel's job results by SID. Cribl has no arbitrary-SID reference — the equivalent is a **parent search** (`parentSearchId`), which is intra-dashboard only.

Conversion:
1. Take the Splunk panel that produces the shared SID (typically hidden with `depends="$show_advanced$"` or invisible on the layout) and re-emit it as a Cribl `list.events` parent with `hidePanel: true`.
2. Rewrite every `| loadjob $that_sid$` panel to a child that starts with `|` (no `dataset=`) and carries `parentSearchId` at both the top level and inside its `search` block.
3. If the Splunk dashboard used TWO SIDs joined via `append` (e.g., a base-events job + a locations job like the ERT dashboard's `parent_traffic` + `parent_locations` pattern), emit **two Cribl parents** and let the map panel reference the primary one — Cribl children cannot `append` from a second parent.

If the map genuinely needs a merged event set from two independent sources, materialize the merge in a single parent query using `union` (if both sources are api_http or in the same lake) or drop the secondary layer and note the omission.

---

## 6. `from datamodel:"Name"`

Splunk data models have no Cribl equivalent. Substitute the underlying dataset:

```
| from datamodel:"Emergency_Tracking_Device_Location"
```
becomes
```
dataset="netmotion"
| where sourcetype == "nm_device_survey" or sourcetype == "nm_adapter_survey"
| where isnotnull(lat)
```

Ask the user (or read the datamodel's XML definition in Splunk) for the underlying `constraints` — that's the search string the datamodel expands to. If the user cannot supply it, flag every affected panel as "TODO: datamodel constraint unknown."

---

## 7. Geocoding (`printgeocode`)

Splunk `printgeocode type=geocode address=addr` (forward) and `type=reverse latfield=lat lonfield=lon` (reverse) have **no KQL equivalent**. The only built-in geo enrichment is `ip-lookup 'GeoLite2-City' on <ip_field>`, which does IP-to-location, not address-to-lat/lon.

Three workarounds, ranked by fidelity:

1. **api_http dataset + join** (works only if the panel doing the lookup uses another api_http dataset — S3/Lake sides can't join).
   - Configure a `api_http` dataset in Cribl pointing at Bing Maps `/REST/v1/Locations` or Google Geocoding.
   - Panel: `dataset="my_events" | join kind=inner (dataset="geocoder_api" | project address, lat, lon) on $left.address == $right.address`.
2. **Precompute at ingest** in a Stream pipeline: enrich each event with `lat`/`lon` before it lands in the lake, then dashboards just read the pre-enriched fields. This is the recommended path — flag it as a Stream config task, not a dashboard task.
3. **Drop the geocoding step** and require the user to enter lat/lon directly, or replace the address multiselect with a lat/lon Text input.

The `printgeocode type=reverse` "Resolve Addresses" toggle in Splunk map popups has no dashboard-only path in Cribl — recommend option 2.

---

## 8. Leaflet maps → Cribl map options

The `leaflet_maps_app.maps-plus` visualization is a third-party Splunk app with clustering, heatmap layers, path splitting, custom icons, HTML popups, Bing/OSM tiles, and 60+ options. Cribl Search has **one** built-in map (`chart.map`) with **two modes** — Choropleth and Geo (point markers with a numeric scale).

Feature-by-feature parity:

| Leaflet feature | Cribl native equivalent | Notes |
|---|---|---|
| Choropleth by country | `chart.map` with `mapDetails.mapType: "Choropleth"` and `mapSourceID: "World"` | Query must emit `country`. |
| Point markers with lat/lon | `chart.map` with `mapDetails.mapType: "Geo"` | Query emits `Name`, `Latitude`, `Longitude`, and a numeric value field. This is not documented in the base SKILL.md; use this mode when converting marker maps. |
| HTML popups (`description=<dl>...<dl>`) | Not supported. | The Splunk-style HTML tooltip is lost. Consider a companion `list.table` below the map for the same info. |
| Path lines between markers (`pathIdentifier`, `pathSplits`) | Not supported natively. | For attack/flow paths, use Viz-Lab `geo-attack-flows`. For simple ordered tracks like GPS breadcrumbs, emit a marker map and add a `chart.line` of `_time` vs a computed distance-from-origin — the line is the temporal proxy. |
| Clustering / heatmap | Not supported. | Downgrade to plain markers; flag. |
| Marker color/size by field | Marker size scales with the numeric channel automatically. | Custom color-by-field is not exposed. |
| Icon SVGs, per-marker priority | Not supported. | Drop. |
| Bing tiles, custom tile URL | Not configurable. | Cribl uses its own tile source. |
| Fullscreen, measure tool, right-click menu | Not supported. | Drop. |
| Auto fit-and-zoom | Automatic. | Cribl always fits to data. |

**Geo (marker) mode config skeleton:**

```json
{
  "id": "map_route",
  "title": "Truck Route",
  "type": "chart.map",
  "layout": { "x": 0, "y": 20, "w": 12, "h": 6 },
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

For anything requiring path lines, HTML popups, or per-marker styling → **Viz-Lab dashboard**, not native Cribl Search dashboard. If the user needs both dashboards to share filters, deploy two files: the native dashboard for tables/inputs, the Viz-Lab dashboard for the map, and wire them together with an `addValueToInput` Interaction whose `targetDashboardId` is the Viz-Lab dashboard's id.

---

## 9. Custom `script=`, `stylesheet=`, inline `<html>`

Not supported anywhere in Cribl Search dashboards. Strip all three.

- `script="foo.js"` — remove; document any token-manipulation logic it contained so it can be replaced with Interactions or precomputed query fields.
- `stylesheet="foo.css"` — remove.
- Inline `<html>...<input type="date"...></html>` — replace with a Cribl `input.text` (user types `YYYY-MM-DD`) that feeds a query using `todatetime("$tokenSelectedDate$")` to compute earliest/latest. Or better: replace with a Time Range Input and let the user pick the day natively.

Any interactivity beyond the four inputs and three interactions requires a Viz-Lab dashboard.

---

## 10. Missing SPL → KQL command mappings

Append these to the base translation table in `SKILL.md`:

| SPL | Cribl KQL | Notes |
|---|---|---|
| `\| spath input=field path=a.b output=new` | `\| extend new = extract_json("$.a.b", field)` | Never `project-rename new = field.a.b` — dotted names silently fail. |
| `\| spath input=raw path=resourceSets{}.resources{} output=x` | `\| extend x = parse_json(raw).resourceSets \| mv-expand x = x.resources` | KQL uses `mv-expand`, not `mvexpand`. Test — some engines expect `mvexpand`. |
| `\| mvexpand field` | `\| mv-expand field` | Splits a multi-value field into rows. Verify hyphen vs no-hyphen on the target engine — Lakehouse accepts `mv-expand`. |
| `\| mvindex(field, 0)` | `extend x = field[0]` (if array) or `extend x = tostring(split(field, ",")[0])` (if delimited string) | 0-indexed. |
| `MVZIP(a, b, "\|")` | `strcat(a, "\|", b)` when scalars; if a/b are arrays, `mv-apply` pairs — flag for manual review. | |
| `\| replace "OLD" with "NEW" in field` | `\| extend field = replace_string(field, "OLD", "NEW")` | |
| `\| replace "OLD\\*" with "*" in field` (regex-ish) | `\| extend field = replace_regex(field, @"OLD.*", "*")` | Splunk's `\*` in `replace` is a literal, not a regex — inspect before translating. |
| `\| eval f = coalesce(a, b, c)` | `\| extend f = coalesce(a, b, c)` | Same name. |
| `\| eval f = if(x=="a", 1, if(x=="b", 2, 3))` | `\| extend f = case(x == "a", 1, x == "b", 2, 3)` | Prefer `case` over nested `iif`. |
| `\| rangemap field=n green=0-4 yellow=5-15 red=15-100` | `\| extend range = case(n <= 4, "green", n <= 15, "yellow", n <= 100, "red", "none")` | Splunk's `rangemap` output field is named `range`; preserve that name so downstream panels still reference it. |
| `\| streamstats count as pos` | `\| extend pos = row_number()` | Only works if the parent search already sorted; add `\| sort by _time asc` first. |
| `\| streamstats current=f window=1 values(coord) as prev` | `\| extend prev = prev(coord, 1)` | Requires KQL engine with `prev()` — verify on target dataset. |
| `\| eventstats count as total` | `\| extend total = toscalar(count())` (rough) | Splunk's `eventstats` broadcasts an aggregate back to every row. In KQL, compute once and cross-join: `\| extend __k=1 \| join kind=inner (T \| summarize total=count() \| extend __k=1) on __k \| project-away __k*`. Flag as complex. |
| `\| accum transID` | `\| serialize \| extend accum = row_cumsum(transID)` | Cumulative sum along the current sort order. |
| `\| eval t = strftime(_time, "%Y-%m-%d %H:%M")` | `\| extend t = format_datetime(_time, "yyyy-MM-dd HH:mm")` | Splunk uses strftime tokens; KQL uses .NET-style format specifiers. Translate the format string: `%Y`→`yyyy`, `%m`→`MM`, `%d`→`dd`, `%H`→`HH`, `%M`→`mm`, `%S`→`ss`, `%l`→`h` (12-hour, no leading zero), `%p`→`tt`. |
| `\| eval ts = strptime(str, "%Y-%m-%d")` | `\| extend ts = todatetime(str)` | Cribl's `todatetime` auto-parses ISO-ish strings; for non-standard formats, split with `substring` and rebuild. |
| `\| eval f = substr(s, 1, 3)` | `\| extend f = substring(s, 0, 3)` | Splunk is 1-indexed; KQL is 0-indexed. Subtract 1 from the offset. |
| `\| eval f = len(s)` | `\| extend f = strlen(s)` | Already in base table — noted here for completeness. |
| `\| eval f = round(x, 2)` | `\| extend f = round(x, 2)` | Same. |
| `\| eval f = tostring(x, "hex")` | `\| extend f = tostring(tolong(x), 16)` — verify. | KQL's `tostring` doesn't take a base; use format specifiers or bitops. Flag. |
| `\| eval hex = "#" . rH . gH . bH` (concat) | `\| extend hex = strcat("#", rH, gH, bH)` | `.` string concat → `strcat`. |
| `\| fillnull value=0` | `\| extend field = coalesce(field, 0)` | Per-field; there's no bulk fillnull. |
| `\| nullifzero(field)` | `\| extend field = iif(field == 0, dynamic(null), field)` | Manual. |
| `\| convert num(field)` | `\| extend field = toint(field)` or `todouble(field)` | Same as `tonumber` mapping. |
| `\| sort 0 field` (Splunk's "unlimited") | `\| sort by field` | KQL sort has no row cap by default. |

Where an SPL command doesn't appear in this table or the base table, the correct behavior is to emit `// COPILOT: <original>` in the query text and add the panel to the migration flag list — not to guess.

---

## 11. Conversion decision tree for a Splunk XML dashboard

Run this before writing any Cribl JSON:

1. **Scan for showstoppers.** Any of: `printgeocode type=geocode` on a live user input (not precomputable), `<selection>` chart brush that gates downstream data, a Leaflet map with path lines AND popups AND clustering that's the primary UX, a `script=` file that computes tokens the rest of the dashboard reads. If any is load-bearing, tell the user the dashboard cannot be a like-for-like port and propose splitting into (a) a native Cribl dashboard for the tabular/filter parts and (b) a Viz-Lab dashboard for the visualization-heavy parts. Get their sign-off before continuing.
2. **Enumerate every token** by walking the XML: `<input token=…>`, `<set token=…>`, `<eval>` token substitutions. Classify each as user-input (→ Cribl Input), search-derived (→ absorb into query), or drilldown-target (→ Interaction addValueToInput).
3. **Enumerate every panel dependency**: which panel produces which token, which panel consumes which token. This is the graph you must preserve. If it has cycles, break the cycle by picking one edge to make user-driven (a Dropdown they choose from).
4. **Map viz types** — remember `chart.map` supports both Choropleth and Geo (marker) modes.
5. **Collapse redundant base searches** into `list.events` parents; every child gets `parentSearchId` at both levels.
6. **Emit** the JSON with `id` matching `^[a-zA-Z0-9_]+$`, `axis: {}` on every chart, `variant` on inputs/markdown, all the base-skill rules.
7. **Write a migration report** listing every downgrade (multiselect→dropdown, brush→removed, path lines→removed, geocoding→precompute-required, custom JS→removed) so the user can decide whether the trade is acceptable before deployment.

---

## 12. Worked example: the ERT (Emergency Response Tracking) dashboard

The Splunk dashboard has: 1 checkbox, 1 text input, 1 multiselect populated by `printgeocode`, 1 HTML date picker, 1 time-range chart with brush, 1 leaflet map with paths+HTML popups, 3 "token diagnostic" tables, 1 user-search table with drilldown, 3 hidden helper searches producing SIDs, 1 dropdown for grouping accuracy that swaps in different SPL fragments via token substitution, 2 dropdowns whose values are giant SPL snippets (color-shading logic), and multiple `depends="$show_advanced$"` panels.

Recommended split:

**Native Cribl Search dashboard** (retains ~65% of functionality):
- Time Range Input (replaces the HTML date picker; a full day picker is a special case of a time range)
- Text Input `userFilter`
- Text Input `addr` (raw address; drop the multiselect — user pastes lat,lon or a place name string)
- Dropdown `grouping` with four static-labeled options; the SPL fragments become branching `case()` in the parent query
- Dropdown `gps_source` (three static values)
- Hidden parent `parent_gps` on the `netmotion` dataset, applying the base filters and the color-shading `case()`s
- Table "User Search Results" with an `addValueToInput` Interaction that sets `d_name_filter` when a row is clicked
- Line chart "Time Range Selector" — but without brush; users narrow via the time input
- Native `chart.map` in **Geo mode** for the marker route (color-by-time; no path lines, no HTML popups, no clustering)
- Companion `list.table` below the map showing arrive/depart/totalMins per stop, replacing the HTML popup content

**Viz-Lab dashboard** (optional, if the user wants path lines back):
- `geo-attack-flows` widget repurposed for GPS routes: `src_lat/src_lng` = previous point, `dst_lat/dst_lng` = current point, one row per hop.

**Explicit drops** (report to user):
- `printgeocode` address→lat/lon multiselect. Replacement: the user enters lat/lon directly, or a Stream pipeline enriches the events with `formattedAddress`/`lat`/`lon` at ingest.
- Reverse geocoding "Resolve Addresses" checkbox. Same replacement path.
- Chart brush selection on the time-range chart.
- All Leaflet-specific options (clustering, heatmap, path splits, custom tile server, Bing key, measure tool).
- Custom JS date picker (replaced by native Time Range).
- Custom CSS `dateContainer` layout.
- `depends="$show_advanced$"` diagnostic tables — either remove or convert to a separate "diagnostics" dashboard linked via Interaction.

This split preserves the analytical value (find a user, filter by time, see their GPS trail) while acknowledging the four hard blockers (geocoding, path lines, brush, custom code).
