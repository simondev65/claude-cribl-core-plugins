# cribl-core

Cribl product expertise for Claude, plus the authoring workflows that go with it. Ask a product question and get an answer grounded in the **current** docs; ask for a dashboard, a Pack, or a collector config and get working artifacts.

---

## Quick Start

### What this plugin does

Five skills, two kinds of work:

**Answering** — `cribl-product-skills` navigates the official Cribl AI-agent documentation index (`docs.cribl.io/llms.txt`), reads the pages that actually matter to your question, and cites them. Because it reads live docs rather than relying on model memory, it stays current with the product.

**Authoring** — the other four skills produce real artifacts: Cribl Search dashboard JSON, Stream and Search Pack repositories, and Stream REST collector configs. Each encodes the schemas, the validation steps, and the failure modes that bite in practice.

### Before you start

- **For answering questions:** nothing. Just ask.
- **For deploying dashboards:** set `CRIBL_ORG_URL`, `CRIBL_CLIENT_ID`, and `CRIBL_CLIENT_SECRET` (Cribl Cloud OAuth client credentials). Authoring works without them; only the deploy and live-test steps need them.
- **For dataset and query discovery:** connect the [Cribl MCP server](https://docs.cribl.io/copilot/cribl-mcp-server/). Without it, Claude asks you for dataset and field names instead of discovering them.
- **For packaging Packs on macOS:** `brew install gnu-tar`. BSD `tar` writes pax headers that Cribl's importer rejects, and the error it reports (`ENOENT: .../default/pack.yml`) points nowhere near the real cause.

### Walk-through: ask a product question

```
> How do I configure an OTel source in Cribl Stream and route metrics to two destinations?
```

The skill opens the global doc index, picks the Stream index, reads the relevant pages, and answers with real config plus citations. No slash command needed — it triggers on the topic.

### Walk-through: build a dashboard

```
> /cribl-dashboard-builder a security overview for my firewall data

  1. Discovers datasets and samples fields          (Cribl MCP)
  2. Writes each panel query and tests it for real  (Cribl MCP)
  3. Assembles the dashboard JSON
  4. Deploys via the Search REST API
  5. Verifies the deployment
```

Queries are tested before they land in a panel, so you don't deploy a dashboard full of syntax errors.

### Walk-through: migrate dashboards in from another vendor

```
> /cribl-dashboard-builder            # then paste your Splunk XML / Grafana JSON
```

Splunk, Sumo Logic, Elastic/Kibana, and Grafana are supported. The skill parses the source format, translates the queries to KQL, infers parent searches where panels share a base query, and reports what it could not translate rather than silently guessing.

### Walk-through: build a Stream Pack

```
> /cribl-stream-packs a pack that ingests FortiGate traffic logs,
  normalizes to Splunk CIM, and cuts volume 20%

  # Then, before you ever try to install it:
  python3 scripts/pack-validate.py --pack ~/my-pack
  bash    scripts/pack-build.sh    ~/my-pack
```

`pack-validate.py` catches the errors Cribl reports uselessly at install time — routes pointing at pipelines that don't exist, `C.vars[…]` reads of undefined variables, `samples.yml` keys with no file behind them, version skew between `package.json` and `pack.yml`. With `CRIBL_HOME` set it also validates against the real AJV schemas shipped in your Cribl install, which is the only way to resolve `should be equal to one of the allowed values` — an error Cribl gives you with no field path.

---

## Skills

| Skill | Use it to | Desktop |
|-------|-----------|---------|
| `cribl-product-skills` | Answer questions on Stream, Edge, Search, Lake, and the APIs from live official docs, with a one-week local cache. Includes a KQL quick reference and production gotchas (dotted field names, metric dimensions, OTel endpoints). | degraded |
| `cribl-dashboard-builder` | Build, test, and deploy Cribl Search dashboards (native and Viz-Lab schemas); migrate dashboards from Splunk, Sumo Logic, Kibana, and Grafana. | degraded |
| `cribl-stream-packs` | Author and modify Stream Packs: pipeline YAML, routes, sources/destinations, `vars.yml`, OCSF/CIM/CSL normalization, JSON⇄YAML conversion, offline validation, `.crbl` packaging, API deploy. | degraded |
| `cribl-search-packs` | Author and modify Search Packs: dashboards, saved searches, Datatypes, macros, lookups, `pack(…)` references, global access, `.crbl` packaging, Dispensary standards. | full |
| `cribl-rest-collector-builder` | Turn vendor API docs into ready-to-import `collector.json` and `breaker.json` for a Stream REST collector — pagination, auth, and event breaking included. | full |

The **Desktop** column is the `desktop:` field in each skill's frontmatter: `full` means it works as-is in Claude Desktop; `degraded` means the reference material works in chat but the bundled scripts or deploy steps need a shell, so run those in Claude Code.

## Bundled scripts

Helpers the skills call, which you can also run directly:

| Script | What it does |
|--------|--------------|
| `cribl-product-skills/scripts/fetch_doc.py` | Fetches `docs.cribl.io` pages through a one-week cache in `~/.cache/cribl-docs/`, revalidating with `ETag`/`Last-Modified` and falling back to a stale copy if docs are unreachable. HTTPS-and-`docs.cribl.io`-only by design. |
| `cribl-stream-packs/scripts/pack-validate.py` | Two-pass Pack validation: cross-reference checks that need no Cribl install, plus AJV schema validation against a real one when `CRIBL_HOME` is set. |
| `cribl-stream-packs/scripts/pack-build.sh` | Builds an installable `.crbl` with the pre-flight checks that stop you shipping an archive Cribl silently refuses. Requires GNU tar. |
| `cribl-stream-packs/scripts/pack-yaml-to-json.py` | Renders a Pack's `default/` YAML into paste-ready standalone JSON, so you can smoke-test one object in the Worker UI without installing the Pack. |
| `cribl-stream-packs/scripts/pack-json-to-yaml.py` | Folds standalone Cribl JSON (UI "Configure as JSON" exports, `collector-templates`) back into a Pack's `default/` YAML layout. |

## FAQ / Gotchas

**"Do I need to type a slash command?"**
No. Skills activate when your request matches their description — asking "why is my Cribl route not matching?" pulls in `cribl-product-skills` on its own. Slash commands are for when you want a specific skill regardless.

**"Why does it read the docs every time instead of just answering?"**
Because Cribl ships fast and model memory goes stale. The one-week cache in `~/.cache/cribl-docs/` keeps this cheap — repeat questions on a topic hit the cache. Ask to "refresh" if you need the newest copy immediately.

**"Can these skills deploy to my Cribl org?"**
Only where you've given them credentials, and only when you ask. `cribl-dashboard-builder` deploys dashboards via the Search REST API using `CRIBL_CLIENT_ID`/`CRIBL_CLIENT_SECRET`; `cribl-stream-packs` can deploy a Pack through the Stream API. Nothing deploys implicitly as part of authoring.

**"Does anything here store my credentials?"**
No. Credentials are read from your environment or `~/.claude/settings.json` at the moment they're used. Nothing in this repo writes them anywhere.

**"My `.crbl` won't install and the error makes no sense."**
Two likely causes, both documented in the skill. If it's `ENOENT: .../default/pack.yml`, you built with BSD `tar` — rebuild with `gtar` via `pack-build.sh`. If it's `should be equal to one of the allowed values` with no field path, run `pack-validate.py` with `CRIBL_HOME` set to validate against the real schemas.

**"Can the skills commit or open a PR?"**
Not on their own. They produce local files; git is yours to drive.

**"What's the difference between a Pack and an App?"**
A **Pack** is a portable bundle of Cribl configuration (pipelines, routes, dashboards, knowledge objects) — use the skills here. An **App** is a custom application embedded in Cribl — use the companion [`claude-cribl-app-plugins`](https://github.com/Cribl-Community/claude-cribl-app-plugins) marketplace instead. The Pack skills check this intent up front so you don't end up in the wrong workflow.

**"Viz-Lab dashboards vs native — which do I want?"**
Native for standard panels. [Viz-Lab](https://github.com/Cribl-Community/cc-viz-lab) for its 46+ visualizations, including security views (MITRE ATT&CK matrix, attack path graphs, geo attack flows) that native dashboards don't have. Different JSON schema, same REST endpoint; names must start with `vz_`. Part C of `cribl-dashboard-builder` covers it.

---

## Resources

- **Cribl Docs:** https://docs.cribl.io
- **Cribl MCP Server:** https://docs.cribl.io/copilot/cribl-mcp-server/
- **Packs Dispensary:** https://packs.cribl.io/
- **Packs publication standards:** https://docs.cribl.io/stream/packs-standards/
- **Pack examples:** https://github.com/criblpacks
- **REST collector templates:** https://github.com/criblio/collector-templates
