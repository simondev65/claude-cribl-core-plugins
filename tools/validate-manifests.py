#!/usr/bin/env python3
"""Structural validation for this plugin marketplace.

    python3 tools/validate-manifests.py

Checks what `claude plugin validate --strict` cannot: that the marketplace and
plugin manifests agree with each other and with what is actually on disk, that
every skill's frontmatter carries the fields this repo requires, and that no
internal-only content has leaked into a public repo.

Needs no dependencies, no network, and no Claude Code install, so it can gate
CI on its own. Run `claude plugin validate --strict` as well when you have the
CLI to hand — it checks the manifest schemas themselves.

Exit code 0 = clean, 1 = at least one error.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VALID_DESKTOP = {"full", "degraded", "unsupported"}

# Substrings that must never appear in a public repo. Kept generic and narrow:
# anything organisation-specific belongs in the publisher's own private checks,
# not in a public file that would itself list it.
FORBIDDEN = [
    ("/Users/", "absolute path from a contributor's machine"),
    ("/home/", "absolute path from a contributor's machine"),
    ("atlassian.net", "link to an Atlassian Cloud site — wikis and tickets are not public docs"),
]

# Patterns that must never appear. Kept alongside FORBIDDEN so a leak fails the
# build rather than relying on a reviewer to spot it.
FORBIDDEN_PATTERNS = [
    (
        re.compile(r"\bmain-[a-z]+-[a-z]+-[a-z0-9]{6,}\b"),
        "looks like a real Cribl Cloud workspace URL — use WORKSPACE-ORG",
    ),
    (
        re.compile(r"\b(?:eyJ[A-Za-z0-9_-]{20,}|(?:gh[ops]|sk|xox[bp])[_-][A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16})\b"),
        "looks like a credential or token",
    ),
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        "private key material",
    ),
    (
        re.compile(r"\b[\w.+-]+@(?!example\.(?:com|org|net)\b|company\.com\b)[\w-]+\.[a-z]{2,}\b", re.I),
        "looks like a real email address — use you@example.com",
    ),
]
# Files exempt from the path check: this validator names the patterns it hunts.
FORBIDDEN_EXEMPT = {Path(__file__).resolve()}

errors: list[str] = []
warnings: list[str] = []


def error(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        error(f"{rel(path)}: missing")
    except json.JSONDecodeError as exc:
        error(f"{rel(path)}: invalid JSON — {exc}")
    return None


def parse_frontmatter(path: Path) -> dict[str, str] | None:
    """Pull top-level `key: value` pairs out of YAML frontmatter.

    Deliberately minimal — the fields this repo requires are all flat scalars,
    so this avoids a PyYAML dependency. Nested structures are ignored, not
    misparsed: any line that is not `key: value` at column 0 is skipped.
    """
    text = path.read_text()
    if not text.startswith("---\n"):
        error(f"{rel(path)}: no YAML frontmatter (must start with `---`)")
        return None
    end = text.find("\n---", 3)
    if end == -1:
        error(f"{rel(path)}: frontmatter is not closed with `---`")
        return None

    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key] = value
    return fields


def check_skill(skill_dir: Path) -> None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        error(f"{rel(skill_dir)}: no SKILL.md")
        return

    fields = parse_frontmatter(skill_md)
    if fields is None:
        return

    name = fields.get("name")
    if not name:
        error(f"{rel(skill_md)}: frontmatter is missing `name`")
    elif name != skill_dir.name:
        error(
            f"{rel(skill_md)}: frontmatter name `{name}` does not match "
            f"directory `{skill_dir.name}`"
        )

    if not fields.get("description"):
        error(f"{rel(skill_md)}: frontmatter is missing `description`")

    desktop = fields.get("desktop")
    if not desktop:
        error(
            f"{rel(skill_md)}: frontmatter is missing `desktop` "
            f"(one of {', '.join(sorted(VALID_DESKTOP))})"
        )
    elif desktop not in VALID_DESKTOP:
        error(
            f"{rel(skill_md)}: desktop `{desktop}` is not one of "
            f"{', '.join(sorted(VALID_DESKTOP))}"
        )
    elif desktop != "full" and not fields.get("desktop-note"):
        error(
            f"{rel(skill_md)}: desktop is `{desktop}` so a one-line "
            f"`desktop-note` is required"
        )

    # Scripts a skill ships should be referenced through ${CLAUDE_PLUGIN_ROOT},
    # otherwise they will not resolve once the plugin is installed elsewhere.
    scripts = skill_dir / "scripts"
    if scripts.is_dir() and any(scripts.iterdir()):
        body = skill_md.read_text()
        if "CLAUDE_PLUGIN_ROOT" not in body:
            warn(
                f"{rel(skill_md)}: ships scripts/ but never mentions "
                f"${{CLAUDE_PLUGIN_ROOT}} — paths may not resolve once installed"
            )
        for script in sorted(scripts.iterdir()):
            if script.is_file() and script.suffix in {".py", ".sh"}:
                mode = script.stat().st_mode
                if not mode & 0o111:
                    warn(f"{rel(script)}: not executable (chmod +x)")


def check_forbidden(plugin_dir: Path) -> None:
    for path in sorted(plugin_dir.rglob("*")):
        if not path.is_file() or path.resolve() in FORBIDDEN_EXEMPT:
            continue
        if path.suffix not in {".md", ".py", ".sh", ".json", ".yml", ".yaml"}:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for needle, why in FORBIDDEN:
                if needle in line:
                    error(f"{rel(path)}:{lineno}: contains `{needle}` — {why}")
            for pattern, why in FORBIDDEN_PATTERNS:
                match = pattern.search(line)
                if match:
                    error(f"{rel(path)}:{lineno}: `{match.group(0)}` {why}")


def main() -> int:
    marketplace_path = ROOT / ".claude-plugin" / "marketplace.json"
    marketplace = load_json(marketplace_path)
    if marketplace is None:
        print_report()
        return 1

    for field in ("name", "owner", "plugins"):
        if field not in marketplace:
            error(f"{rel(marketplace_path)}: missing required field `{field}`")

    entries = marketplace.get("plugins") or []
    if not entries:
        error(f"{rel(marketplace_path)}: `plugins` is empty")

    seen: set[str] = set()
    for entry in entries:
        name = entry.get("name")
        if not name:
            error(f"{rel(marketplace_path)}: a plugins[] entry has no `name`")
            continue
        if name in seen:
            error(f"{rel(marketplace_path)}: duplicate plugin `{name}`")
        seen.add(name)

        source = entry.get("source")
        if not isinstance(source, str):
            # Remote sources are legal but there is nothing local to check.
            continue

        plugin_dir = (ROOT / source).resolve()
        if not plugin_dir.is_dir():
            error(f"{rel(marketplace_path)}: source `{source}` does not exist")
            continue

        plugin_path = plugin_dir / ".claude-plugin" / "plugin.json"
        plugin = load_json(plugin_path)
        if plugin is None:
            continue

        if plugin.get("name") != name:
            error(
                f"{rel(plugin_path)}: name `{plugin.get('name')}` does not match "
                f"marketplace entry `{name}`"
            )

        mp_version, pl_version = entry.get("version"), plugin.get("version")
        if pl_version is None:
            error(f"{rel(plugin_path)}: missing `version`")
        elif mp_version is None:
            error(f"{rel(marketplace_path)}: plugin `{name}` has no `version`")
        elif mp_version != pl_version:
            error(
                f"version mismatch for `{name}`: marketplace.json says "
                f"{mp_version}, plugin.json says {pl_version}"
            )

        if not plugin.get("description"):
            error(f"{rel(plugin_path)}: missing `description`")

        skills_dir = plugin_dir / "skills"
        if not skills_dir.is_dir():
            error(f"{rel(plugin_dir)}: no skills/ directory")
        else:
            skill_dirs = sorted(d for d in skills_dir.iterdir() if d.is_dir())
            if not skill_dirs:
                error(f"{rel(skills_dir)}: contains no skills")
            for skill_dir in skill_dirs:
                check_skill(skill_dir)

        if not (plugin_dir / "README.md").is_file():
            warn(f"{rel(plugin_dir)}: no README.md")

        check_forbidden(plugin_dir)

    print_report()
    return 1 if errors else 0


def print_report() -> None:
    for msg in warnings:
        print(f"warning: {msg}")
    for msg in errors:
        print(f"error: {msg}")
    if errors:
        print(f"\n✗ {len(errors)} error(s), {len(warnings)} warning(s)")
    else:
        print(f"✔ validation passed ({len(warnings)} warning(s))")


if __name__ == "__main__":
    sys.exit(main())
