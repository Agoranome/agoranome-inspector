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

# Each market in turn, into the same book. A market joins this list once its trial runs have been checked.
# A sheet the check before signing holds is not published, and a market whose run fails (its catalog unreadable,
# say) publishes nothing: the other markets still run and are published, then the job fails so that GitHub tells
# the repository's owner. After looking at a held sheet, start the workflow by hand with "publish anyway".
held=""
failed=""
for market in ${RUN_MARKETS:-x402 mpp}; do
  set +e
  "$INSPECTOR" run "$SITE" --market "$market" --private "$PRIVATE" ${PUBLISH_ANYWAY:+--publish-anyway} ${RUN_ARGS:-}
  code=$?
  set -e
  if [ "$code" -eq 3 ]; then
    held="$held $market"
  elif [ "$code" -ne 0 ]; then
    failed="$failed $market"
    echo "::error::The $market run failed (exit $code) and published nothing; the other markets go on."
  fi
done

if [ -f "$SITE/book.jsonl" ]; then
  # Delivery signs from the chain: payers and repeat payers of each x402 seller (signs.py), once the BASE_RPC secret
  # names a Base RPC that answers eth_getLogs. Counts only in this log.
  if [ -n "${BASE_RPC:-}" ]; then
    if ! "$INSPECTOR" signs "$SITE" --rpc "$BASE_RPC" --private "$PRIVATE" ${SIGNS_ARGS:-}; then
      echo "::warning::The delivery signs were not read from the chain this week; see the log above."
    fi
  fi
  # The shelf report card, graded again from the newest sheets (a new book entry only when something changed).
  "$INSPECTOR" shelf "$SITE"
  # The lab's receipt roots and the 15% pledge's figures, read from its public ledger. A ledger that can't be read,
  # or whose figures don't add up, is left out this week with a warning: the sheets still publish.
  if ! "$INSPECTOR" anchor-lab "$SITE" ${LAB_LEDGER:+--ledger "$LAB_LEDGER"}; then
    echo "::warning::The lab's pledge ledger was not put in the book this week; see the log above."
  fi
  # Close each finished month in the accounts, as a back-stop to the month-close workflow: what each source earned
  # and what the pledge owes (accounts.py). A month closes once; a late statement is closed again by hand.
  "$INSPECTOR" close "$SITE"
  # Buyers' reports, each tied to a payment on Base, from the lab's public listing (counts only in this log).
  if ! "$INSPECTOR" reports "$SITE" ${LAB_REPORTS:+--source "$LAB_REPORTS"}; then
    echo "::warning::The lab's buyers' reports were not put in the book this week; see the log above."
  fi
  # Sellers' disputes, each signed by the row's pay-to address, from the lab's public listing (counts only).
  if ! "$INSPECTOR" disputes "$SITE" ${LAB_DISPUTES:+--source "$LAB_DISPUTES"}; then
    echo "::warning::The lab's disputes were not put in the book this week; see the log above."
  fi
  # Best-buy sheets from what the book now holds (a new entry only when a row changed).
  "$INSPECTOR" best-buy "$SITE"
  # The plan's gates from the lab, the money gate completed from the accounts (a new entry only on a change).
  if ! "$INSPECTOR" gates "$SITE" ${LAB_GATES:+--source "$LAB_GATES"}; then
    echo "::warning::The lab's gates were not put in the book this week; see the log above."
  fi
  touch "$SITE/.nojekyll"
  # A pinned first key, once Shariar has published it as the repository variable INSPECTOR_FIRST_KID.
  "$INSPECTOR" verify "$SITE" --all ${INSPECTOR_FIRST_KID:+"--key=$INSPECTOR_FIRST_KID"}
  (
    cd "$SITE"
    git add -A
    if git diff --cached --quiet; then
      echo "Nothing new to publish."
    else
      git commit -q -m "Sheet $(date -u +%Y-%m-%d)"
      git push origin "$BRANCH"
      echo "Published: $(tr -d '\n ' < head.json)"
    fi
  )
fi

if [ -n "$held" ]; then
  echo "::error::Held by the check before signing, not published:$held. See the log above for why."
fi
if [ -n "$held$failed" ]; then
  exit 1
fi
