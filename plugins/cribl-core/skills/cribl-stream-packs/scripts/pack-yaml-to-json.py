#!/usr/bin/env python3
"""Render a Pack's `default/` YAML into paste-ready standalone JSON.

    python3 pack-yaml-to-json.py --pack ~/my-pack                # -> <pack>/conf/
    python3 pack-yaml-to-json.py --pack ~/my-pack --out /tmp/x   # somewhere else
    python3 pack-yaml-to-json.py --pack ~/my-pack \
        --templates ~/collector-templates/collectors/rest/<vendor>

The Pack's `default/*.yml` stays the source of truth and the thing that ships;
everything this writes is generated from it, so neither copy can drift.

Two reasons to run it:

1. **Smoke-test without installing the Pack.** Paste one object into the Worker
   Group UI's "Configure as JSON" tab and hit a live API. A Collector inside a
   Pack cannot be run from the Pack UI at all - collector-based Sources in Packs
   need a Commit & Deploy before they will run - so this is how you iterate on a
   REST Collector at any speed.

       conf/collectors/<id>.json    Data > Sources > Collectors > REST/API
       conf/breakers/<slug>.json    Processing > Knowledge > Event Breaker Rules
       conf/pipelines/<id>.json     Processing > Pipelines
       conf/routes.json             Routing > Data Routes  (pack-only, see below)
       conf/vars.json               Processing > Knowledge > Variables

2. **Publish to criblio/collector-templates.** `--templates` writes the same
   objects under that repo's file-naming convention (`rest_` / `eb_` / `pipe_` /
   `sample_` prefixes) so the manual-import configs sit alongside the other
   vendors.

Routes are deliberately omitted from --templates output: a Pack's Routes use
`output: __group` / `targetContext: group`, which only means anything inside a
Pack. Pasting them at Worker Group level will not do what you want.

Add `conf/` to .gitignore - `default/` is the pack.
"""

import argparse
import json
import os
import re
import shutil
import sys

try:
    import yaml
except ImportError:
    sys.exit("pyyaml is required: python3 -m pip install --user pyyaml")


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class Pack:
    def __init__(self, root):
        self.root = os.path.abspath(os.path.expanduser(root))
        self.default = os.path.join(self.root, "default")
        if not os.path.isdir(self.default):
            sys.exit(f"error: {self.root} has no default/ - not a pack repo")

    def load(self, rel):
        path = os.path.join(self.default, rel)
        if not os.path.exists(path):
            return None
        with open(path) as fh:
            return yaml.safe_load(fh)

    def collectors(self):
        """jobs.yml: map key IS the collector id, which the JSON needs back."""
        for cid, body in (self.load("jobs.yml") or {}).items():
            yield cid, dict({"id": cid}, **(body or {}))

    def breakers(self):
        """breakers.yml: top-level key is the ruleset name (no `breakers:` wrapper)."""
        for name, body in (self.load("breakers.yml") or {}).items():
            body = body or {}
            obj = {"id": name, "lib": body.get("lib", "custom")}
            obj.update({k: v for k, v in body.items() if k != "lib"})
            yield name, obj

    def pipelines(self):
        """conf.yml holds the INSIDE of the JSON's `conf` - re-wrap it."""
        pipe_root = os.path.join(self.default, "pipelines")
        if not os.path.isdir(pipe_root):
            return
        for entry in sorted(os.listdir(pipe_root)):
            conf = os.path.join(pipe_root, entry, "conf.yml")
            if not os.path.isfile(conf):
                continue
            with open(conf) as fh:
                yield entry, {"id": entry, "conf": yaml.safe_load(fh)}

    def samples(self):
        sample_dir = os.path.join(self.root, "data", "samples")
        if not os.path.isdir(sample_dir):
            return
        for entry in sorted(os.listdir(sample_dir)):
            if entry.endswith(".json"):
                yield entry, os.path.join(sample_dir, entry)

    @property
    def pack_id(self):
        return (self.load("pack.yml") or {}).get("id", os.path.basename(self.root))


CONF_README = """# conf/ - paste-ready JSON (generated)

Generated from `default/` by `pack-yaml-to-json.py`. **Do not edit these files** -
edit the YAML under `default/` and re-run the script. `default/` is the pack.

Use this to smoke-test against a live API without installing the Pack. A
Collector inside a Pack cannot be run from the Pack UI; it needs a Commit &
Deploy first, so this is the fast iteration loop.

## Order matters - build dependencies first, or objects save with dangling refs

1. **Secrets** - Worker Group scoped. Distributed/Cloud: **Worker Group > Group
   Settings > Security > Secrets**. Single instance: **Settings > Security >
   Secrets**. Create every secret your collectors reference by
   `C.Secret('<name>')`, with the exact same name. A missing secret renders as
   the literal `undefined` in the header and the API replies 401.
2. **Variables** - `vars.json`, under **Processing > Knowledge > Variables**. Add
   each one by hand; the Variables UI has no bulk JSON import. Skipping this
   makes every `C.vars[...]` in a `collectUrl` resolve to `undefined`.
3. **Event Breakers** - `breakers/*.json`, under **Processing > Knowledge > Event
   Breaker Rules > Add Ruleset > Configure as JSON**.
4. **Pipelines** - `pipelines/*.json`, under **Processing > Pipelines > Add
   Pipeline > Configure as JSON**. Create the collector's pre-processing pipeline
   first - the collectors reference it by name.
5. **Collectors** - `collectors/*.json`, under **Data > Sources > Collectors >
   REST/API > Add Collector > Configure as JSON**.

Every collector ships `schedule.enabled: false`. Use **Run > Preview** on one
first: it fires a single request and shows the broken-out events without writing
anything downstream. Only then enable the schedule.

## Caveats when testing outside the Pack

- `routes.json` uses `output: __group` / `targetContext: group`, which only means
  something inside a Pack. Test the pipelines directly against `data/samples/`
  instead.
- `input.pipeline` and `input.breakerRulesets` reference the Pack's pipeline and
  ruleset **by name**. Steps 3 and 4 create objects with those exact names at
  group level, so the references resolve.
"""


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(json.dumps(obj, indent=2) + "\n")
    return path


def render_conf(pack, out):
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    written = []
    for cid, obj in pack.collectors():
        written.append(write_json(os.path.join(out, "collectors", cid + ".json"), obj))
    for name, obj in pack.breakers():
        written.append(write_json(os.path.join(out, "breakers", slugify(name) + ".json"), obj))
    for pid, obj in pack.pipelines():
        written.append(write_json(os.path.join(out, "pipelines", pid + ".json"), obj))
    routes = pack.load(os.path.join("pipelines", "route.yml"))
    if routes:
        written.append(write_json(os.path.join(out, "routes.json"), routes))
    vars_ = pack.load("vars.yml")
    if vars_:
        written.append(write_json(os.path.join(out, "vars.json"), vars_))
    readme = os.path.join(out, "README.md")
    with open(readme, "w") as fh:
        fh.write(CONF_README)
    written.append(readme)
    return written


def render_templates(pack, dest):
    """criblio/collector-templates naming: rest_ / eb_ / pipe_ / sample_."""
    os.makedirs(dest, exist_ok=True)
    written = []
    for cid, obj in pack.collectors():
        # in_vendor_events -> rest_vendor_events.json
        written.append(write_json(
            os.path.join(dest, "rest_" + re.sub(r"^in_", "", cid) + ".json"), obj))
    for name, obj in pack.breakers():
        written.append(write_json(os.path.join(dest, "eb_" + slugify(name) + ".json"), obj))
    for pid, obj in pack.pipelines():
        written.append(write_json(os.path.join(dest, "pipe_" + pid + ".json"), obj))
    vars_ = pack.load("vars.yml")
    if vars_:
        written.append(write_json(os.path.join(dest, "vars_" + slugify(pack.pack_id) + ".json"),
                                  vars_))
    for name, src in pack.samples():
        target = os.path.join(dest, "sample_" + name)
        shutil.copyfile(src, target)
        written.append(target)
    print("  note: Routes omitted - output: __group / targetContext: group is "
          "Pack-only. Document a Worker Group Route filtered on __packsource "
          "in the template README instead.", file=sys.stderr)
    return written


def main():
    ap = argparse.ArgumentParser(
        description="Render a Pack's default/ YAML into paste-ready JSON.")
    ap.add_argument("--pack", default=".", help="pack repo root (default: cwd)")
    ap.add_argument("--out", help="output dir for the conf/ layout (default: <pack>/conf)")
    ap.add_argument("--templates", metavar="DIR",
                    help="write the criblio/collector-templates layout to DIR instead")
    args = ap.parse_args()

    pack = Pack(args.pack)
    if args.templates:
        dest = os.path.abspath(os.path.expanduser(args.templates))
        written = render_templates(pack, dest)
        base = dest
    else:
        base = os.path.abspath(os.path.expanduser(args.out or os.path.join(pack.root, "conf")))
        written = render_conf(pack, base)

    for p in written:
        print("  " + os.path.relpath(p, base))
    print(f"\n{len(written)} files written to {base}")


if __name__ == "__main__":
    main()
