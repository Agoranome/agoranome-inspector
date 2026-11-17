#!/usr/bin/env bash
# Restate published sheets under a newer rule, as the "Restate a sheet" workflow runs it: take the site from the
# gh-pages branch, sign one restatement per sheet into its book, verify the whole site, and only then push.
set -euo pipefail

BRANCH="${PAGES_BRANCH:-gh-pages}"
SITE="${SITE_DIR:-site}"
INSPECTOR="${INSPECTOR:-agoranome-inspector}"

if [ -z "${INSPECTOR_SIGNING_KEY:-}" ]; then
  echo "::notice::The INSPECTOR_SIGNING_KEY secret is not set, so nothing was restated."
  exit 0
fi
if ! [[ "${RESTATE_RULE:-}" =~ ^[a-z0-9-]{1,32}$ ]]; then
  echo "::error::The rule must be a rule's name, such as sheet-2."
  exit 2
fi

git config user.name "agoranome-inspector"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git fetch --depth=1 origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
git worktree add -B "$BRANCH" "$SITE" "origin/$BRANCH"

for sheet in ${RESTATE_SHEETS:-}; do
  if ! [[ "$sheet" =~ ^[a-z0-9-]{1,64}$ ]]; then
    echo "::error::$sheet is not a sheet id."
    exit 2
  fi
  "$INSPECTOR" restate "$SITE" "$sheet" --rule "$RESTATE_RULE"
done
# A restated pick table changes the best-buy file built from it: build it again (it says "unchanged" otherwise).
"$INSPECTOR" best-buy "$SITE"

"$INSPECTOR" verify "$SITE" --all ${INSPECTOR_FIRST_KID:+"--key=$INSPECTOR_FIRST_KID"}
(
  cd "$SITE"
  git add -A
  if git diff --cached --quiet; then
    echo "Nothing new to publish."
  else
    git commit -q -m "Restated under $RESTATE_RULE: ${RESTATE_SHEETS}"
    git push origin "$BRANCH"
    echo "Published: $(tr -d '\n ' < head.json)"
  fi
)
