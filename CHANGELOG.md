# Changelog

All notable changes to this marketplace and its plugins are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
plugin versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-10-16

First public release of the `cribl-core` plugin.

### Added

- `cribl-product-skills` — answers Cribl product questions from the live official
  documentation index (`docs.cribl.io/llms.txt`), with a one-week local cache
  (`fetch_doc.py`), a Cribl Search KQL quick reference, and production gotchas.
- `cribl-dashboard-builder` — builds, tests, and deploys Cribl Search dashboards
  (native and Viz-Lab schemas), and migrates dashboards in from Splunk,
  Sumo Logic, Elastic/Kibana, and Grafana — including Splunk SimpleXML
  tokens, drilldowns, `depends` gating and geo maps
  (`references/splunk-xml-advanced.md`).
- `cribl-stream-packs` — authors and modifies Cribl Stream Packs, with helper
  scripts for offline validation (`pack-validate.py`), `.crbl` packaging
  (`pack-build.sh`), and JSON⇄YAML conversion.
- `cribl-search-packs` — authors and modifies Cribl Search Packs, including
  Dispensary publication standards.
- `cribl-rest-collector-builder` — generates Cribl Stream REST collector and
  event-breaker configs from vendor API documentation.

### Notes

This plugin's skills were developed and used internally before being packaged
for public release; `1.0.0` marks the start of this repository's version
lineage rather than the skills' first version.
