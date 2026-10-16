#!/usr/bin/env bash
#
# Build an installable .crbl from a Pack repo, with the pre-flight checks that
# stop you shipping an archive Cribl silently refuses.
#
#   bash pack-build.sh [pack-repo-dir]     # default: cwd
#
# A .crbl is just a gzipped tar - but it MUST be built with GNU tar. macOS/BSD
# tar writes extended pax headers and AppleDouble entries that Cribl's importer
# rejects, and the failure looks like a corrupt archive rather than a tar dialect
# problem: install dies with `ENOENT: .../default/pack.yml` even though
# `tar -tzf` happily lists the file.
set -euo pipefail

ROOT="$(cd "${1:-.}" && pwd)"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

[[ -f package.json && -f default/pack.yml ]] || {
  echo "error: $ROOT is not a pack repo (need package.json and default/pack.yml)" >&2
  exit 1
}

# Homebrew installs GNU tar as `gtar`; on Linux `tar` already IS GNU tar. Probe
# both and verify by --version rather than trusting the name, so this works
# unchanged on a Mac and in CI.
TAR=""
for candidate in gtar tar; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" --version 2>/dev/null | head -1 | grep -q 'GNU tar'; then
    TAR="$candidate"
    break
  fi
done
if [[ -z "$TAR" ]]; then
  echo "error: GNU tar not found (looked for 'gtar' and 'tar')." >&2
  echo "       macOS: brew install gnu-tar" >&2
  echo "       Do NOT substitute macOS/BSD tar - Cribl cannot install those archives." >&2
  exit 1
fi

NAME="$(python3 -c 'import json;print(json.load(open("package.json"))["name"])')"
VERSION="$(python3 -c 'import json;print(json.load(open("package.json"))["version"])')"
PACK_ID="$(python3 -c 'import yaml;print(yaml.safe_load(open("default/pack.yml"))["id"])')"
PACK_VERSION="$(python3 -c 'import yaml;print(yaml.safe_load(open("default/pack.yml"))["version"])')"

# Cribl decides whether an installed pack needs upgrading from package.json, but
# the UI displays pack.yml. Skew between them is invisible until it confuses
# someone six months from now.
[[ "$VERSION" == "$PACK_VERSION" ]] || {
  echo "error: version mismatch - package.json=$VERSION default/pack.yml=$PACK_VERSION" >&2
  exit 1
}
[[ "$NAME" == "$PACK_ID" ]] || {
  echo "error: id mismatch - package.json name=$NAME default/pack.yml id=$PACK_ID" >&2
  exit 1
}

# Every YAML file must parse before we ship it.
python3 - <<'PY'
import glob, sys, yaml
bad = 0
for path in sorted(glob.glob('default/**/*.yml', recursive=True)):
    try:
        yaml.safe_load(open(path))
    except Exception as exc:
        bad += 1
        print(f'error: {path}: {exc}', file=sys.stderr)
if bad:
    sys.exit(1)
print('  yaml ok')
PY

# Cross-reference + JSON Schema validation. The schema half skips itself when
# there is no Cribl install; the cross-reference half always runs.
python3 "$HERE/pack-validate.py" --pack "$ROOT"

OUT="${NAME}_${VERSION}.crbl"
rm -f "$OUT"

# Directories must appear as their own tar entries or import fails on older
# Cribl versions - that is why we pass the top-level names, not a file list.
EXTRA=()
for opt in logo.png logo.jpg; do
  [[ -f "$opt" ]] && EXTRA+=("$opt")
done
[[ -d data ]] && EXTRA+=(data)

"$TAR" -czf "$OUT" \
  --exclude '.DS_Store' \
  --exclude '._*' \
  --exclude '__pycache__' \
  --exclude '.git' \
  --exclude '*.crbl' \
  package.json README.md default "${EXTRA[@]}"

echo
echo "built $OUT ($(du -h "$OUT" | cut -f1)) with $TAR"
echo "install: Cribl Stream > Processing > Packs > Add Pack > Import from File"
echo "         re-importing the SAME version is refused ('Version $VERSION is up to date')"
echo "         - use a -dev.N suffix while iterating, and Import mode Replace so the"
echo "           local/ overlay does not shadow your new default/"
"$TAR" -tzf "$OUT" | head -20
