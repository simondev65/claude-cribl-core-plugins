# Contributing

Thanks for helping improve these plugins. This repo is a Claude Code **plugin marketplace**, so the layout and manifests matter as much as the content.

## Repository layout

```
claude-cribl-core-plugins/
├── .claude-plugin/
│   └── marketplace.json          # marketplace manifest — lists every plugin
├── plugins/
│   └── cribl-core/
│       ├── .claude-plugin/
│       │   └── plugin.json       # plugin manifest — version is authoritative
│       ├── README.md
│       └── skills/
│           └── <skill-name>/
│               ├── SKILL.md      # required
│               ├── scripts/      # optional helpers the skill invokes
│               └── references/   # optional load-on-demand material
├── CHANGELOG.md
├── LICENSE
└── README.md
```

Two rules that are easy to get wrong:

- A plugin's version appears in **two** places — `plugins/<name>/.claude-plugin/plugin.json` and the matching `plugins[]` entry in `.claude-plugin/marketplace.json`. Keep them identical; `claude plugin tag` will refuse to tag a release if they disagree.
- Skills are discovered by directory. The directory name and the `name:` field in `SKILL.md` frontmatter must match.

## Validating your change

Run both before you open a PR:

```bash
python3 tools/validate-manifests.py                     # enforced in CI
claude plugin validate . --strict                       # marketplace manifest
claude plugin validate ./plugins/cribl-core --strict     # plugin manifest + skills
```

**`tools/validate-manifests.py`** is the gate CI enforces. It needs no dependencies, no network, and no Claude Code install, and it checks what the CLI cannot: that `plugin.json` and the marketplace entry agree on name and version, that every skill's frontmatter carries `name`/`description`/`desktop`, that skills shipping `scripts/` reference `${CLAUDE_PLUGIN_ROOT}`, and that no internal-only content (internal wiki links, private env vars, absolute home paths) has leaked into this public repo.

**`claude plugin validate --strict`** checks the manifest schemas themselves. `--strict` treats warnings as errors, catching unrecognized fields and missing metadata the runtime would otherwise tolerate. CI runs it advisory-only, since it depends on the published CLI.

Also install your branch locally and exercise the skill for real:

```bash
claude plugin marketplace add /path/to/your/clone
claude plugin install cribl-core@claude-cribl-core-plugins
```

## Writing skills

**`SKILL.md` frontmatter:**

```yaml
---
name: my-skill                 # must match the directory name
description: "..."             # what Claude matches the user's request against
argument-hint: "..."           # optional — shown when invoked as a slash command
desktop: full | degraded       # does this work in Claude Desktop?
desktop-note: "..."            # required when desktop is not `full`
---
```

The `description` is the single most important line you write. It is what Claude matches a user's request against, so state **when** to use the skill and include the phrasings people actually type. "Build and modify Cribl Stream Packs — pipeline YAML, routes, packaging…" gets found; "Stream Pack helper" does not.

`desktop`/`desktop-note` are a convention of this repo: Claude Desktop has no shell, so a skill whose steps depend on `scripts/` or `curl` is `degraded` there. Say so in one line rather than leaving users to discover it.

**Content guidelines:**

- **Ground it in reality.** Every schema, field name, and function must be real. If a gotcha is in here, it should be one someone actually hit — say what the symptom was, since Cribl's own error messages are often misleading.
- **Reference the plugin root, not absolute paths.** Use `${CLAUDE_PLUGIN_ROOT}` so scripts resolve wherever the plugin is installed:
  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/skills/my-skill/scripts/helper.py"
  ```
- **Keep large reference material out of `SKILL.md`.** Put it in `references/` and link to it, so it loads only when needed.
- **No internal or private content.** No links to internal wikis, no customer names, no credentials, no company-internal env vars or paths. This repo is public.
- **Prefer official docs** (`docs.cribl.io`) as the cited source.

## Releasing

1. Update the version in `plugin.json` **and** in the marketplace `plugins[]` entry.
2. Add a `CHANGELOG.md` entry describing what changed.
3. Bump the marketplace `metadata.version` only when the catalog itself changes (a plugin added, removed, or renamed).
4. Tag the release:
   ```bash
   claude plugin tag ./plugins/cribl-core     # creates cribl-core--v<version>
   ```

Use patch versions for fixes and clarifications, minor for new skills or capabilities, major for changes that break how an existing skill is invoked.

## Reporting problems

Open an issue with the Cribl product and version, what you asked, what the skill produced, and what you expected. For a Pack or dashboard that Cribl rejected, include the exact error — those messages are frequently misleading, and capturing them is how the gotcha sections get written.
