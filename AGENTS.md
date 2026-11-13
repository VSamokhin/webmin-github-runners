# Notes for coding agents

- Run before pushing: `python3 -m unittest discover -s tests`, `tests/test_module.sh`, `ruff check .`,
  `perlcritic webmin/ghrunners/*.cgi webmin/ghrunners/*.pl`, `shellcheck build.sh tests/*.sh`, `actionlint`.
- GitHub Actions: always use the latest release of an action, pinned by its full commit SHA with the version as a
  comment (`uses: owner/action@<sha> # vX.Y.Z`). Use the tag's commit SHA (`^{}`), not an annotated tag object.
- Don't bump versions in the repository: the release tag decides (see README, Releases).
- Under the Authentic theme, ui_print_header's right-hand slot becomes an icon button bar; don't put text there.
