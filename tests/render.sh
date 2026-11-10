#!/bin/sh
# Render the module's index page outside Webmin, using the stub WebminCore.
#   python3 tests/make_sample.py /tmp/s.json && tests/render.sh /tmp/s.json > /tmp/page.html
set -eu
here=$(cd "$(dirname "$0")" && pwd)
mod="$here/../webmin/ghrunners"
status=$(realpath "$1")
cfg=$(mktemp)
trap 'rm -f "$cfg"' EXIT
sed "s|^status_file=.*|status_file=$status|" "$mod/config" > "$cfg"
if [ -n "${GHR_EXTRA_CONFIG:-}" ]; then printf '%s\n' "$GHR_EXTRA_CONFIG" >> "$cfg"; fi
cd "$mod"
GHR_MODULE_DIR="$mod" GHR_CONFIG="$cfg" GHR_NO_HTTP_HEADER=1 \
	perl -I"$here/webmin-stub" -w index.cgi
