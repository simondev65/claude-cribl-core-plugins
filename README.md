# Claude Cribl Core Plugins

Claude Code plugins that give Claude working expertise in the [Cribl](https://cribl.io) product suite — Stream, Edge, Search, Lake — plus the authoring workflows that go with it: dashboards, Stream and Search Packs, and REST collector configs.

Answers come from the **live official docs** (`docs.cribl.io`), not from model memory, so guidance tracks the current product rather than a training cutoff.

## Installation

Inside Claude Code, run:

```
/plugin marketplace add simondev65/claude-cribl-core-plugins
/plugin install cribl-core@claude-cribl-core-plugins
```

Then `/reload-plugins` (or restart Claude Code). That's it — the five skills below are available.

Or from a terminal:

```bash
claude plugin marketplace add simondev65/claude-cribl-core-plugins
claude plugin install cribl-core@claude-cribl-core-plugins
```

Prefer the menus? Run `/plugin` → **Marketplaces** → **Add Marketplace**, paste `https://github.com/simondev65/claude-cribl-core-plugins`, then install `cribl-core`.

### Updating

```bash
claude plugin marketplace update claude-cribl-core-plugins
claude plugin update cribl-core@claude-cribl-core-plugins
```

Releases are listed in [CHANGELOG.md](./CHANGELOG.md). For more on plugin management, see the [Claude Code documentation](https://docs.claude.com/en/docs/claude-code/plugins).

## Plugins

| Plugin | Description |
|--------|-------------|
| **[cribl-core](./plugins/cribl-core/README.md)** | Cribl product expertise and authoring workflows. Answers product questions from live Cribl docs, builds and migrates Cribl Search dashboards, authors Stream and Search Packs, and generates REST collector configs from API documentation. |

## Skills

Installing `cribl-core` gives you five skills:

| Skill | Use it to |
|-------|-----------|
| `cribl-product-skills` | Ask anything about Stream, Edge, Search, Lake, or the APIs. Reads the current docs via the Cribl AI-agent index (`llms.txt`) with a one-week local cache. |
| `cribl-dashboard-builder` | Build, test, and deploy Cribl Search dashboards — including native and Viz-Lab schemas — and migrate dashboards in from Splunk, Sumo Logic, Kibana, or Grafana. |
| `cribl-stream-packs` | Author and modify Cribl Stream Packs: pipeline YAML, routes, sources/destinations, OCSF/CIM/CSL normalization, `vars.yml`, packaging, and API deploy. |
| `cribl-search-packs` | Author and modify Cribl Search Packs: dashboards, saved searches, Datatypes, macros, lookups, `pack(…)` references, and `.crbl` packaging. |
| `cribl-rest-collector-builder` | Turn a vendor's API docs into ready-to-import `collector.json` and `breaker.json` for a Cribl Stream REST collector. |

Skills activate automatically when your request matches, or you can invoke one directly — `/cribl-stream-packs`, `/cribl-dashboard-builder`, and so on.

## Requirements

- **Claude Code** (any recent version with plugin support)
- **Python 3** — for the docs cache helper and the Pack validation/conversion scripts
- **GNU tar** (`gtar`) — only if you package Packs on macOS: `brew install gnu-tar`. The OS-default BSD `tar` silently produces `.crbl` archives that Cribl refuses to install.
- **A Cribl deployment** — needed only for the steps that deploy or test against a live org. Authoring works offline.

Nothing here requires credentials to be stored. Deploy steps prompt for, or read, your own Cribl Cloud OAuth client credentials at the time you run them.

## Quick Links

- **[Cribl Docs](https://docs.cribl.io)** — official product documentation
- **[Cribl Packs Dispensary](https://packs.cribl.io/)** — published Packs
- **[criblpacks](https://github.com/criblpacks)** — Pack source examples
- **[Cribl Community](https://github.com/Cribl-Community)** — community-maintained tooling
- **[claude-cribl-app-plugins](https://github.com/Cribl-Community/claude-cribl-app-plugins)** — companion plugins for authoring Cribl **Apps**

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md). Pull requests should keep `claude plugin validate . --strict` green.

## License

[Apache 2.0](./LICENSE)

---

For more detail on a plugin, see its own README.
