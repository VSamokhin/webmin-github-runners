#!/bin/sh
# Syntax-check the Webmin module and render it against sample data.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
mod="$here/../webmin/ghrunners"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

for f in "$mod"/*.cgi "$mod"/*.pl; do
	(cd "$mod" && perl -I"$here/webmin-stub" -c "$f" 2>&1) | grep -q "syntax OK" || fail "syntax: $f"
done

# Every $text{'x'} / &text('x') key used in code exists in lang/en
for key in $(grep -ohE "(\\\$text\{'|&text\(')[a-z_]+" "$mod"/*.cgi "$mod"/*.pl | sed -E "s/.*'//" | grep -v '_$' | sort -u); do
	grep -q "^$key=" "$mod/lang/en" || fail "missing lang key: $key"
done

python3 "$here/make_sample.py" "$tmp/status.json"
"$here/render.sh" "$tmp/status.json" > "$tmp/page.html" 2> "$tmp/err"
[ ! -s "$tmp/err" ] || { cat "$tmp/err"; fail "warnings while rendering"; }
for want in "server-game-android" "android-instrumented" "No online runner has these labels" \
	"2 matching runner(s), all busy" "Disk: ci-store" "devstack-runner-health-android-1" "4712 / 5000"; do
	grep -qF "$want" "$tmp/page.html" || fail "page lacks: $want"
done
grep -q "was last updated" "$tmp/page.html" && fail "fresh status shown as stale"

# Missing file -> setup hint, no crash
"$here/render.sh" "$tmp/nope.json" > "$tmp/missing.html"
grep -q "does not exist" "$tmp/missing.html" || fail "missing-file message"

# Stale file -> warning
python3 - "$tmp/status.json" "$tmp/stale.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["generated_at"] = "2020-01-01T00:00:00Z"
json.dump(d, open(sys.argv[2], "w"))
PY
"$here/render.sh" "$tmp/stale.json" > "$tmp/stale.html"
grep -q "was last updated" "$tmp/stale.html" || fail "stale warning"

# Broken JSON -> error message
echo '{"schema": 1,' > "$tmp/bad.json"
"$here/render.sh" "$tmp/bad.json" > "$tmp/bad.html"
grep -q "not valid JSON" "$tmp/bad.html" || fail "bad JSON message"

# HTML from GitHub data is escaped
python3 - "$tmp/status.json" "$tmp/xss.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["scopes"][0]["runners"][0]["name"] = "<script>alert(1)</script>"
json.dump(d, open(sys.argv[2], "w"))
PY
"$here/render.sh" "$tmp/xss.json" > "$tmp/xss.html"
grep -q "<script>alert(1)" "$tmp/xss.html" && fail "unescaped runner name"

echo "module tests passed"
