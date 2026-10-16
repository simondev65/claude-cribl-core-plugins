#!/usr/bin/env python3
"""Validate a Cribl Stream Pack before `Add Pack` ever sees it.

    python3 pack-validate.py --pack ~/my-pack
    CRIBL_HOME=~/cribl python3 pack-validate.py --pack ~/my-pack

Two passes:

**Pass 1 - cross-reference checks. Always runs, needs no Cribl install.**
Catches the dangling references and dead config that schema validation cannot
see: routes pointing at pipelines that do not exist, collectors naming a breaker
ruleset that is not in breakers.yml, samples.yml keys with no file on disk,
`C.vars[...]` reads of variables nobody defined, version/id skew between
package.json and pack.yml.

**Pass 2 - JSON Schema checks. Needs a Cribl install (skips itself otherwise).**
Cribl validates a Pack with AJV on install and reports only the keyword that
failed - `failed to install: should be equal to one of the allowed values` - with
no field path. Unusable. The same schemas are already on disk in any install:

    $CRIBL_HOME/default/cribl/collectors/<type>/conf.schema.json
    $CRIBL_HOME/default/cribl/functions/<id>/conf.schema.json

so validate against those and get a real JSON pointer instead.

The job wrapper (schedule/run), Routes, Event Breakers, Variables and samples are
NOT in those files, but they ARE in the OpenAPI spec bundled with the UI:

    $CRIBL_HOME/default/ui/static/swagger/openapi.json.gz

which is where the required-property lists live - `RouteConf` requires
`pipeline`, `RouteComment` requires `index`, and `schedule.run.earliest`/`latest`
are **numbers**, not relative-time strings. Getting any of those wrong makes the
Pack fail AJV validation on load: it stays registered but unloaded, and every
Pack API call then throws `Cannot read properties of undefined (reading
'handleClusterCall')`, which takes out the whole Packs UI - not just your pack.

Exit codes: 0 = clean, 1 = at least one error. Warnings alone do not fail.
"""

import argparse
import glob
import gzip
import json
import os
import re
import sys

try:
    import yaml
except ImportError:
    sys.exit("pyyaml is required: python3 -m pip install --user pyyaml")

BUILTIN_PIPELINES = {"passthru", "devnull", "main"}

errors = []
warnings = []
checked = 0


def err(where, msg):
    errors.append(f"error: {where}: {msg}")


def warn(where, msg):
    warnings.append(f"warning: {where}: {msg}")


def walk_strings(node):
    """Yield every string scalar in a parsed YAML/JSON structure."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str):
                yield k
            yield from walk_strings(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from walk_strings(v)


def load(root, rel):
    path = os.path.join(root, rel)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            return yaml.safe_load(fh)
    except Exception as exc:
        err(rel, f"does not parse: {exc}")
        return None


# ══════════════════════════════════════════════ pass 1 - cross-reference checks
def cross_reference(root):
    global checked

    pkg_path = os.path.join(root, "package.json")
    pkg = {}
    if os.path.exists(pkg_path):
        try:
            pkg = json.load(open(pkg_path))
        except Exception as exc:
            err("package.json", f"does not parse: {exc}")
    else:
        err("package.json", "missing - required at the pack root")

    pack = load(root, os.path.join("default", "pack.yml")) or {}
    if not pack:
        err("default/pack.yml", "missing - required")
    if pkg and pack:
        if pkg.get("version") != pack.get("version"):
            err("version", f"package.json={pkg.get('version')} != "
                           f"default/pack.yml={pack.get('version')} - Cribl "
                           "decides upgrade eligibility from package.json")
        if pkg.get("name") != pack.get("id"):
            err("id", f"package.json name={pkg.get('name')} != "
                      f"default/pack.yml id={pack.get('id')}")
    checked += 1

    # --- what exists -------------------------------------------------------
    pipe_root = os.path.join(root, "default", "pipelines")
    pipelines = set()
    if os.path.isdir(pipe_root):
        pipelines = {e for e in os.listdir(pipe_root)
                     if os.path.isfile(os.path.join(pipe_root, e, "conf.yml"))}
    breakers = set((load(root, os.path.join("default", "breakers.yml")) or {}).keys())
    jobs = load(root, os.path.join("default", "jobs.yml")) or {}
    vars_ = load(root, os.path.join("default", "vars.yml")) or {}
    routes_doc = load(root, os.path.join("default", "pipelines", "route.yml")) or {}
    samples = load(root, os.path.join("default", "samples.yml")) or {}

    if isinstance(breakers, dict) and "breakers" in breakers and len(breakers) == 1:
        err("default/breakers.yml", "wrapped under a `breakers:` key - unlike "
            "inputs.yml/outputs.yml, breakers.yml is keyed by ruleset name at "
            "the TOP level. The wrapper makes the rulesets invisible.")
    if isinstance(vars_, dict) and "vars" in vars_ and len(vars_) == 1:
        err("default/vars.yml", "wrapped under a `vars:` key - vars.yml is keyed "
            "by variable ID at the TOP level. With the wrapper Cribl loads the "
            "pack silently and every C.vars.* read returns undefined.")

    # --- routes ------------------------------------------------------------
    for i, r in enumerate(routes_doc.get("routes") or []):
        where = f"default/pipelines/route.yml:routes[{i}] ({r.get('id')})"
        p = r.get("pipeline")
        if not p:
            err(where, "RouteConf requires `pipeline` - use the built-in "
                       "`passthru` for a no-op (never `devnull`, which discards)")
        elif p not in pipelines and p not in BUILTIN_PIPELINES:
            err(where, f"pipeline '{p}' is neither default/pipelines/{p}/ nor a "
                       f"built-in {sorted(BUILTIN_PIPELINES)}")
        if r.get("output") not in (None, "__group") and "targetContext" not in r:
            warn(where, f"output '{r['output']}' with no targetContext - inside a "
                        "Pack use output: __group + targetContext: group unless "
                        "it names a Destination in default/outputs.yml")
        checked += 1
    for i, c in enumerate(routes_doc.get("comments") or []):
        where = f"default/pipelines/route.yml:comments[{i}]"
        if isinstance(c, str):
            err(where, "the Routes `comments` field is a structured array, not a "
                       "list of strings - a string list makes the whole Routes "
                       "config fail to load and the UI shows one empty Route")
        elif isinstance(c, dict) and "index" not in c:
            err(where, "RouteComment requires `index` (0-based position of the "
                       "Route the comment is pinned above)")

    # --- collectors --------------------------------------------------------
    for cid, job in jobs.items():
        job = job or {}
        where = f"default/jobs.yml:{cid}"
        inp = job.get("input") or {}
        p = inp.get("pipeline")
        if p and p not in pipelines and p not in BUILTIN_PIPELINES:
            err(where, f"input.pipeline '{p}' does not exist under default/pipelines/")
        for rs in inp.get("breakerRulesets") or []:
            if rs not in breakers:
                err(where, f"input.breakerRulesets references '{rs}', which is not "
                           "a key in default/breakers.yml (it is matched by NAME)")
        if (job.get("schedule") or {}).get("enabled"):
            warn(where, "schedule.enabled is true - ship Collectors DISABLED so "
                        "installing the pack cannot start burning someone's API budget")
        run = ((job.get("schedule") or {}).get("run") or {})
        for key in ("earliest", "latest"):
            if isinstance(run.get(key), str):
                err(where, f"schedule.run.{key} is the string {run[key]!r}; "
                           "SavedJobCollection types it as a NUMBER (epoch "
                           "seconds). This fails AJV on load and leaves the pack "
                           "registered-but-unloaded ('handleClusterCall'). Omit "
                           "the key and build the window in collectRequestParams.")
        meta = inp.get("metadata") or []
        if not any(isinstance(m, dict) and m.get("name") == "__packsource" for m in meta):
            warn(where, "no __packsource in input.metadata - route.yml has "
                        "nothing stable to filter this collector's events on")
        checked += 1

    # --- samples -----------------------------------------------------------
    for sid, s in (samples or {}).items():
        path = os.path.join(root, "data", "samples", f"{sid}.json")
        if not os.path.exists(path):
            err(f"default/samples.yml:{sid}", f"no data/samples/{sid}.json - Cribl "
                "resolves samples by id/basename, so a mismatch fails with "
                f"'Unable to find sample with id={sid}'")
            continue
        try:
            body = json.load(open(path))
        except Exception as exc:
            err(f"data/samples/{sid}.json", f"not valid JSON ({exc}) - Cribl parses "
                "everything under data/samples/ as JSON and the UI throws 'Error "
                "parsing sample file content'. Ship a JSON array, not raw log text.")
            continue
        if not isinstance(body, list):
            err(f"data/samples/{sid}.json", "must be a JSON ARRAY of event objects")
        if isinstance(s, dict) and not s.get("isPackOnly"):
            warn(f"default/samples.yml:{sid}", "isPackOnly is not true - the sample "
                 "will not ship with the pack")
        checked += 1

    # --- variables: defined vs referenced ----------------------------------
    # Scan the PARSED YAML, not the file text: a folded/quoted scalar can carry a
    # line-continuation backslash mid-identifier ("C.vars['mis\<newline>t_org_id']"),
    # which a text regex reads as two broken names.
    referenced = set()
    for path in glob.glob(os.path.join(root, "default", "**", "*.yml"), recursive=True):
        try:
            doc = yaml.safe_load(open(path))
        except Exception:
            continue  # already reported by the yaml parse pass
        for s in walk_strings(doc):
            referenced |= set(re.findall(r"C\.vars\[\s*['\"]([^'\"]+)['\"]\s*\]", s))
            referenced |= set(re.findall(r"C\.vars\.([A-Za-z_$][\w$]*)", s))
    for name in sorted(referenced - set(vars_)):
        err("C.vars", f"'{name}' is read in default/ but not defined in "
                      "default/vars.yml - Cribl does NOT throw on this, the field "
                      "assignment is silently skipped and the event passes through "
                      "unchanged")
    for name in sorted(set(vars_) - referenced):
        warn("default/vars.yml", f"'{name}' is defined but never read via C.vars - "
                                 "dead config that suggests broken wiring")
    for name, v in (vars_ or {}).items():
        if not isinstance(v, dict):
            continue
        where = f"default/vars.yml:{name}"
        if v.get("lib") != "custom":
            err(where, "pack-authored variables need lib: custom "
                       "(cribl / cribl-custom are reserved for built-ins)")
        if not isinstance(v.get("value"), str):
            err(where, f"value must be a STRING even for type: {v.get('type')} - "
                       f"got {type(v.get('value')).__name__}")
        elif v.get("type") == "string" and not re.match(r"^\s*['\"`]", v["value"]):
            err(where, f"type: string values are evaluated as JS, so a literal "
                       f"needs inner quotes: \"'{v['value']}'\" not \"{v['value']}\" "
                       "(without them Cribl reads a bare identifier -> undefined)")
        if not v.get("label"):
            warn(where, "no label - the UI falls back to showing the raw ID")
        checked += 1


# ═══════════════════════════════════════════════════ pass 2 - JSON Schema checks
def report(where, errs):
    for e in errs:
        pointer = "/".join(str(p) for p in e.absolute_path) or "<root>"
        err(where, f"{pointer}: {e.validator}: {e.message}")
        # oneOf/anyOf failures are useless without the branch errors.
        for sub in e.context or []:
            sub_ptr = "/".join(str(p) for p in sub.absolute_path) or "<root>"
            errors.append(f"       -> {sub_ptr}: {sub.validator}: {sub.message}")


def openapi_to_draft7(node):
    """OpenAPI 3.0 dialect -> something Draft7Validator understands."""
    if isinstance(node, dict):
        node = {k: openapi_to_draft7(v) for k, v in node.items() if k != "example"}
        if node.pop("nullable", False) and "type" in node:
            t = node["type"]
            node["type"] = [t, "null"] if isinstance(t, str) else list(t) + ["null"]
        return node
    if isinstance(node, list):
        return [openapi_to_draft7(v) for v in node]
    return node


def is_spec_artifact(schema_name, error):
    """True for errors the bundled spec raises against Packs that install fine.

    Each of these is reproduced by a Cribl-published pack known to install
    cleanly, so treating them as failures would just train people to ignore this
    script. Re-check against cribl-akamai-rest-io before extending the list.
    """
    path = list(error.absolute_path)
    # RouteConf types outputExpression as a string, but the UI writes null and
    # cribl-akamai-rest-io ships it that way on every Route.
    if path[-1:] == ["outputExpression"] and error.validator == "type":
        return True
    # DataSample types 'tags' as a string; real packs use a list.
    if schema_name == "DataSample" and path == ["tags"]:
        return True
    # The collector conf is validated properly against the authoritative on-disk
    # collectors/<type>/conf.schema.json. The spec's copy has a degenerate oneOf:
    # with 'enableDiscoverCode' absent, both branches of
    # RestDiscoveryDiscoverTypeHttp match, so oneOf can never be satisfied.
    if schema_name == "SavedJobCollection" and path[:1] == ["collector"]:
        return True
    return False


OPENAPI_MAP = [
    (os.path.join("default", "pipelines", "route.yml"), "Routes", False),
    (os.path.join("default", "jobs.yml"), "SavedJobCollection", True),
    (os.path.join("default", "breakers.yml"), "EventBreakerRuleset", True),
    (os.path.join("default", "vars.yml"), "GlobalVar", True),
    (os.path.join("default", "samples.yml"), "DataSample", True),
]


def schema_checks(root, cribl_home):
    global checked
    schema_root = os.path.join(cribl_home, "default", "cribl")
    if not os.path.isdir(schema_root):
        print(f"  schema checks skipped: no Cribl install at {cribl_home} "
              "(set CRIBL_HOME to one)")
        return
    try:
        from jsonschema import Draft7Validator
    except ImportError:
        print("  schema checks skipped: jsonschema not installed "
              "(python3 -m pip install --user jsonschema)")
        return

    cache = {}

    def validator_for(kind, name):
        """kind is 'collectors' or 'functions'."""
        key = (kind, name)
        if key not in cache:
            path = os.path.join(schema_root, kind, name, "conf.schema.json")
            cache[key] = Draft7Validator(json.load(open(path))) \
                if os.path.exists(path) else None
        return cache[key]

    # --- collector confs ---------------------------------------------------
    for cid, job in (load(root, os.path.join("default", "jobs.yml")) or {}).items():
        collector = (job or {}).get("collector") or {}
        ctype = collector.get("type")
        if not ctype:
            continue
        v = validator_for("collectors", ctype)
        if v is None:
            err(f"default/jobs.yml:{cid}", f"unknown collector type '{ctype}'")
            continue
        checked += 1
        report(f"default/jobs.yml:{cid}",
               sorted(v.iter_errors(collector.get("conf") or {}),
                      key=lambda e: list(e.absolute_path)))

    # --- pipeline functions ------------------------------------------------
    for path in sorted(glob.glob(os.path.join(root, "default", "pipelines", "*", "conf.yml"))):
        rel = os.path.relpath(path, root)
        for i, fn in enumerate((yaml.safe_load(open(path)) or {}).get("functions") or []):
            fid = fn.get("id")
            v = validator_for("functions", fid)
            if v is None:
                err(f"{rel}:functions[{i}]", f"no such Function id '{fid}' - there "
                    f"is no {schema_root}/functions/{fid}/")
                continue
            checked += 1
            report(f"{rel}:functions[{i}] ({fid})",
                   sorted(v.iter_errors(fn.get("conf") or {}),
                          key=lambda e: list(e.absolute_path)))

    # --- routes / job wrapper / breakers / vars / samples ------------------
    openapi = os.path.join(cribl_home, "default", "ui", "static", "swagger",
                           "openapi.json.gz")
    if not os.path.exists(openapi):
        print(f"  note: no OpenAPI spec at {openapi} - skipped the "
              "Routes/jobs/breakers/vars/samples schemas")
        return
    spec = openapi_to_draft7(json.load(gzip.open(openapi)))
    components = spec["components"]
    for rel, schema_name, keyed in OPENAPI_MAP:
        doc = load(root, rel)
        if not doc:
            continue
        # Inline the schema with components as a sibling so internal
        # "#/components/schemas/..." refs resolve within this same document.
        v = Draft7Validator(dict(components["schemas"][schema_name],
                                 components=components))
        items = doc.items() if keyed else [(doc.get("id", "<doc>"), doc)]
        for key, obj in items:
            # Keyed configs carry their map key as the object's id.
            probe = dict(obj, id=obj.get("id", key)) if isinstance(obj, dict) else obj
            checked += 1
            report(f"{rel}:{key} (vs {schema_name})",
                   [e for e in sorted(v.iter_errors(probe),
                                      key=lambda e: list(e.absolute_path))
                    if not is_spec_artifact(schema_name, e)])


def main():
    ap = argparse.ArgumentParser(description="Validate a Cribl Stream Pack.")
    ap.add_argument("--pack", default=".", help="pack repo root (default: cwd)")
    ap.add_argument("--cribl-home", default=os.environ.get("CRIBL_HOME", "/opt/cribl"),
                    help="Cribl install to read schemas from (default: $CRIBL_HOME or /opt/cribl)")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = ap.parse_args()

    root = os.path.abspath(os.path.expanduser(args.pack))
    if not os.path.isdir(os.path.join(root, "default")):
        sys.exit(f"error: {root} has no default/ - not a pack repo")

    cross_reference(root)
    schema_checks(root, os.path.abspath(os.path.expanduser(args.cribl_home)))

    for w in warnings:
        print("  " + w, file=sys.stderr)
    for e in errors:
        print(e, file=sys.stderr)

    if errors:
        print(f"\n{len(errors)} error(s) - Cribl would reject or misload this pack",
              file=sys.stderr)
        return 1
    if warnings and args.strict:
        print(f"\n{len(warnings)} warning(s), --strict", file=sys.stderr)
        return 1
    try:
        version = json.load(open(os.path.join(args.cribl_home, "package.json")))["version"]
    except Exception:
        version = "schemas unavailable"
    print(f"  pack ok ({checked} checks, Cribl {version})"
          + (f", {len(warnings)} warning(s)" if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
