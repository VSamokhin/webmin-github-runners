# Notes for coding agents

- Run before pushing: `python3 -m unittest discover -s tests`, `tests/test_module.sh`, `ruff check .`,
  `perlcritic webmin/ghrunners/*.cgi webmin/ghrunners/*.pl`, `shellcheck build.sh tests/*.sh`, `actionlint`.
- GitHub Actions: always use the latest release of an action, pinned by its full commit SHA with the version as a
  comment (`uses: owner/action@<sha> # vX.Y.Z`). Use the tag's commit SHA (`^{}`), not an annotated tag object.
- Don't bump versions in the repository: the release tag decides (see README, Releases).
- Under the Authentic theme, ui_print_header's right-hand slot becomes an icon button bar; don't put text there.

## Branches, pull requests and shipping (Viktor, 2026-11-22)

- One work package = one work branch = one pull request; never reuse a branch for a second package.
- Iterate on the work branch: commit and push as often as useful, with the local checks before each push.
- Open the pull request into `main` only when Viktor asks to ship the package: never earlier, never as a draft and
  never "for review". Opening it is the ship request, and CI then runs every check.
- Before opening it, bring `origin/main` into the branch. Merge only when every CI check is green on a head that
  contains `origin/main`; Viktor's ship request is the approval, so merge it without asking again. Never merge red or
  pending; a fix pushed to the branch runs the checks again.
- Never write the skip-CI marker in a commit message, not even in its body.
