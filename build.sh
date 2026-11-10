#!/bin/sh
# Build the Webmin module package: dist/ghrunners.wbm.gz
set -eu
cd "$(dirname "$0")"
version=$(sed -n 's/^version=//p' webmin/ghrunners/module.info)
mkdir -p dist
chmod 0755 webmin/ghrunners/*.cgi webmin/ghrunners/*.pl
tar -C webmin --owner=0 --group=0 --numeric-owner --sort=name \
	--mtime="@${SOURCE_DATE_EPOCH:-0}" -cf - ghrunners | gzip -9n > dist/ghrunners.wbm.gz
echo "dist/ghrunners.wbm.gz (module version $version)"
