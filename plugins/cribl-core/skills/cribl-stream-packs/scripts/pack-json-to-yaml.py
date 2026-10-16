#!/usr/bin/env python3
"""Fold standalone Cribl JSON (UI "Configure as JSON" / collector-templates) into
a Pack's `default/` YAML layout.

    # print the YAML fragment and where it goes (default - safe, no clobber)
    python3 pack-json-to-yaml.py collector.json

    # merge it into the pack for real
    python3 pack-json-to-yaml.py --pack ~/my-pack --write collector.json

    # a whole directory of exports at once
    python3 pack-json-to-yaml.py --pack ~/my-pack --write conf/**/*.json

This is the direction you need when you build a REST Collector in the Worker
Group UI, get it working against the live API, and then want it to ship inside a
Pack. The UI speaks ONE JSON object with an `id` key; a Pack speaks a YAML map
keyed BY that id with the `id` key removed. Pipelines get an extra twist: the
UI's `{id, conf:{functions:[...]}}` becomes `default/pipelines/<id>/conf.yml`
holding just the *inside* of `conf`.

Kind is detected from the object's shape - see DETECTORS below. Nothing is
written unless you pass --write.

DEFAULT IS --dry-run ON PURPOSE: rewriting a YAML file through PyYAML drops
every comment in it. Pack YAML is usually heavily commented (that is where the
"why" of a collector lives), so the safe move is to read the fragment and paste
it in by hand. Use --write on a clean git tree only.
"""

import argparse
import json
import os
import re
import sys

try:
    import yaml
except ImportError:
    sys.exit("pyyaml is required: python3 -m pip install --user pyyaml")

BUILTIN_PIPELINES = {"passthru", "devnull", "main"}


# --------------------------------------------------------------------- helpers
def die(msg):
    sys.exit(f"error: {msg}")


def warn(msg):
    print(f"  warning: {msg}", file=sys.stderr)


def dump_yaml(obj):
    """Block-style YAML that reads like hand-written pack config."""
    return yaml.safe_dump(obj, sort_keys=False, default_flow_style=False,
                          width=100, allow_unicode=True)


# ------------------------------------------------------------------- detectors
def detect(obj):
    """Return one of: collector | pipeline | breaker | routes | vars | unknown."""
    if not isinstance(obj, dict):
        return "unknown"
    if isinstance(obj.get("collector"), dict) and "type" in obj["collector"]:
        return "collector"
    if isinstance(obj.get("conf"), dict) and "functions" in obj["conf"]:
        return "pipeline"
    if "functions" in obj and isinstance(obj["functions"], list):
        return "pipeline"
    if isinstance(obj.get("rules"), list) and obj.get("rules"):
        return "breaker"
    if isinstance(obj.get("routes"), list):
        return "routes"
    # vars.yml is a flat map of id -> {type, lib, value}
    if obj and all(isinstance(v, dict) and "value" in v and "type" in v
                   for v in obj.values()):
        return "vars"
    return "unknown"


# ----------------------------------------------------------------- transformers
def as_collector(obj, path):
    """Standalone collector JSON -> (jobs.yml key, body)."""
    cid = obj.get("id") or os.path.splitext(os.path.basename(path))[0]
    body = {k: v for k, v in obj.items() if k != "id"}

    sched = body.setdefault("schedule", {})
    if sched.get("enabled"):
        sched["enabled"] = False
        warn(f"{cid}: forced schedule.enabled: false - installing a Pack must "
             "never start collecting against someone's API budget")

    run = sched.get("run") or {}
    # The AJV trap: SavedJobCollection types earliest/latest as NUMBERS (epoch
    # seconds). The UI happily saves "-15m" / "now" on a standalone collector,
    # but inside a Pack those strings fail validation on load, which leaves the
    # Pack registered-but-unloaded and takes out the whole Packs UI.
    for key in ("earliest", "latest"):
        if isinstance(run.get(key), str):
            run.pop(key)
            warn(f"{cid}: dropped schedule.run.{key} (a relative-time STRING - "
                 "the Pack schema wants epoch seconds). Build the window in "
                 "collectRequestParams instead; see the skill's §6.1b.")
    if run:
        run.setdefault("timeRangeType", "relative")

    inp = body.setdefault("input", {})
    inp.setdefault("type", "collection")
    inp.setdefault("sendToRoutes", True)
    meta = inp.setdefault("metadata", [])
    if not any(m.get("name") == "__packsource" for m in meta if isinstance(m, dict)):
        warn(f"{cid}: no __packsource in input.metadata - add "
             "{name: __packsource, value: \"'<pack-id>.<source>'\"} so "
             "route.yml can filter on it")

    conf = (body.get("collector") or {}).get("conf") or {}
    text = json.dumps(conf)
    for hdr in re.findall(r'"value"\s*:\s*"([^"]*(?:Bearer|Token|Basic|api[_-]?key)[^"]*)"',
                          text, re.I):
        if "C.Secret(" not in hdr and "C.vars" not in hdr:
            warn(f"{cid}: possible literal credential in the collector conf "
                 f"({hdr[:48]}...) - reference a Secret instead: "
                 "`Token ${C.Secret('<name>').value}`")
    return cid, body


def as_pipeline(obj, path):
    """Pipeline JSON -> (pipeline id, conf.yml body).

    The UI/`GET /api/v1/pipelines` shape is {id, conf:{output, functions, ...}}.
    In a Pack the directory name IS the id and conf.yml holds the INSIDE of
    `conf` - one nesting level less than the JSON.
    """
    pid = obj.get("id") or os.path.splitext(os.path.basename(path))[0]
    body = obj["conf"] if isinstance(obj.get("conf"), dict) else \
        {k: v for k, v in obj.items() if k != "id"}
    body = dict(body)
    body.setdefault("asyncFuncTimeout", 1000)
    fns = body.get("functions") or []
    if fns and fns[0].get("id") != "comment":
        warn(f"{pid}: pipeline does not open with a `comment` Function - add "
             "one with purpose/author/refs (skill rule #5)")
    return pid, body


def as_breaker(obj, path):
    """Event Breaker ruleset JSON -> (breakers.yml key, body)."""
    bid = obj.get("id") or os.path.splitext(os.path.basename(path))[0]
    body = {k: v for k, v in obj.items() if k != "id"}
    body.setdefault("lib", "custom")
    return bid, body


def as_routes(obj, path):
    """Routes JSON -> the whole default/pipelines/route.yml document."""
    body = dict(obj)
    body.setdefault("id", "default")
    body.setdefault("groups", {})
    body.setdefault("comments", [])
    for i, c in enumerate(body["comments"]):
        if isinstance(c, str):
            die("route.yml `comments` is a structured array, not a list of "
                "strings. A plain string list makes the whole Routes config "
                "fail to load and the UI shows one empty Route. Use "
                "{id, index, comment}.")
        if isinstance(c, dict) and "index" not in c:
            c["index"] = 0
            warn(f"comments[{i}]: added the required `index` (0-based position "
                 "of the Route the comment is pinned above)")
    for r in body.get("routes") or []:
        if not r.get("pipeline"):
            r["pipeline"] = "passthru"
            warn(f"route {r.get('id')}: RouteConf requires `pipeline`; set it to "
                 "the built-in `passthru` (never `devnull`, which discards)")
        if r.get("output") not in ("__group", None) or "targetContext" not in r:
            warn(f"route {r.get('id')}: inside a Pack use "
                 "`output: __group` + `targetContext: group` to hand events "
                 "back to the Worker Group's own Routes/Destinations")
        r.setdefault("clones", [])
        r.setdefault("enableOutputExpression", False)
        r.setdefault("outputExpression", None)
    return None, body


def as_vars(obj, path):
    """vars.json -> the whole default/vars.yml map (merged key by key)."""
    for name, v in obj.items():
        if not isinstance(v, dict):
            continue
        if v.get("lib") != "custom":
            v["lib"] = "custom"
            warn(f"{name}: set lib: custom (required on pack-authored variables)")
        if not isinstance(v.get("value"), str):
            v["value"] = json.dumps(v.get("value"))
            warn(f"{name}: value must be a STRING even for type "
                 f"{v.get('type')} - quoted it as {v['value']!r}")
        elif v.get("type") == "string" and not re.match(r"^\s*['\"`]", v["value"]):
            v["value"] = "'" + v["value"] + "'"
            warn(f"{name}: type: string values are evaluated as JS, so a literal "
                 f"needs inner quotes - rewrote as {v['value']!r}")
        if not v.get("label"):
            warn(f"{name}: no label - the UI will show the raw ID")
    return None, obj


# kind -> (transform, target path, mode)
#   mode "key" = one entry in a map keyed by id
#   mode "map" = merge top-level keys into the existing map
#   mode "doc" = the whole document / its own file
TRANSFORM = {
    "collector": (as_collector, os.path.join("default", "jobs.yml"), "key"),
    "breaker":   (as_breaker,   os.path.join("default", "breakers.yml"), "key"),
    "vars":      (as_vars,      os.path.join("default", "vars.yml"), "map"),
    "routes":    (as_routes,    os.path.join("default", "pipelines", "route.yml"), "doc"),
    "pipeline":  (as_pipeline,  None, "doc"),
}


# ------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(
        description="Fold standalone Cribl JSON into a Pack's default/ YAML.")
    ap.add_argument("files", nargs="+", help="JSON files exported from Cribl")
    ap.add_argument("--pack", default=".", help="pack repo root (default: cwd)")
    ap.add_argument("--write", action="store_true",
                    help="actually merge into the pack (DROPS YAML COMMENTS in "
                         "any file it rewrites - use on a clean git tree)")
    args = ap.parse_args()

    root = os.path.abspath(os.path.expanduser(args.pack))
    if args.write and not os.path.isdir(os.path.join(root, "default")):
        die(f"{root} has no default/ - is that a pack repo? "
            "(omit --write to just print the fragments)")

    # kind -> {key: body} accumulated across every input file
    staged = {}
    for path in args.files:
        try:
            obj = json.load(open(path))
        except Exception as exc:
            die(f"{path}: {exc}")
        kind = detect(obj)
        if kind == "unknown":
            warn(f"{path}: cannot tell what this is (no collector/functions/"
                 "rules/routes/vars shape) - skipped")
            continue
        fn, target, mode = TRANSFORM[kind]
        key, body = fn(obj, path)
        staged.setdefault(kind, []).append((key, body, path))

    if not staged:
        die("nothing recognized")

    for kind, items in staged.items():
        _, target, mode = TRANSFORM[kind]
        for key, body, path in items:
            if kind == "pipeline":
                # The directory name IS the pipeline id, and conf.yml holds the
                # INSIDE of the JSON's `conf` - one nesting level less.
                target = os.path.join("default", "pipelines", key, "conf.yml")
            frag = dump_yaml({key: body} if mode == "key" else body)

            print(f"\n# ==> {target}"
                  f"{'  (key: ' + key + ')' if mode == 'key' else ''}"
                  f"   [from {os.path.basename(path)}]")
            if not args.write:
                print(frag, end="")
                continue

            dest = os.path.join(root, target)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if mode == "doc":
                if os.path.exists(dest):
                    warn(f"overwriting {target} (comments in it are lost)")
                open(dest, "w").write(frag)
            else:
                existing = {}
                if os.path.exists(dest):
                    existing = yaml.safe_load(open(dest)) or {}
                    warn(f"rewriting {target} - YAML comments in it are lost")
                incoming = {key: body} if mode == "key" else body
                for k in incoming:
                    if k in existing:
                        warn(f"replacing existing key '{k}' in {target}")
                existing.update(incoming)
                open(dest, "w").write(dump_yaml(existing))
            print("  written")

    if not args.write:
        print("\n# dry run - nothing written. Paste the fragments above into "
              "the listed files\n# (keeps your YAML comments), or re-run with "
              "--write on a clean git tree.")
    print("\nnext: python3 pack-validate.py --pack " + args.pack, file=sys.stderr)


if __name__ == "__main__":
    main()
