#!/usr/bin/env bash
# The weekly run, as the "Weekly sheet" workflow runs it.
#
# 1. Take the published site from the gh-pages branch (or start it, the first time).
# 2. Read the index, ask every listing with real demand without paying, judge, and sign the sheet and its change
#    log into the site's open book.
# 3. Verify the whole site with the one command anyone would use.
# 4. Only then commit it to gh-pages, which GitHub Pages serves.
#
# Nothing is measured or published while the INSPECTOR_SIGNING_KEY secret is unset. The private run file (the
# index's payer and call counts) is written outside the site and thrown away with the runner.
set -euo pipefail

BRANCH="${PAGES_BRANCH:-gh-pages}"
SITE="${SITE_DIR:-site}"
PRIVATE="${PRIVATE_DIR:-${RUNNER_TEMP:-/tmp}/inspector-private}"
INSPECTOR="${INSPECTOR:-agoranome-inspector}"

if [ -z "${INSPECTOR_SIGNING_KEY:-}" ]; then
  echo "::notice::The INSPECTOR_SIGNING_KEY secret is not set, so nothing was measured or published."
  exit 0
fi

git config user.name "agoranome-inspector"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null; then
  git fetch --depth=1 origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
  git worktree add -B "$BRANCH" "$SITE" "origin/$BRANCH"
else
  echo "No $BRANCH branch yet: starting the site and its book."
  git worktree add --orphan -b "$BRANCH" "$SITE"
fi

"$INSPECTOR" run "$SITE" --private "$PRIVATE" ${RUN_ARGS:-}
touch "$SITE/.nojekyll"

# A pinned first key, once Shariar has published it as the repository variable INSPECTOR_FIRST_KID.
"$INSPECTOR" verify "$SITE" --all ${INSPECTOR_FIRST_KID:+"--key=$INSPECTOR_FIRST_KID"}

cd "$SITE"
git add -A
git commit -q -m "Sheet $(date -u +%Y-%m-%d)"
git push origin "$BRANCH"
echo "Published: $(cat head.json | tr -d '\n ')"
