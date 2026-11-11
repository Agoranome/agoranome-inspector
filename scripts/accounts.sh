#!/usr/bin/env bash
# The accounts, as the "Accounts" workflow runs them: on the first days of each month, close the month before; by
# hand, post one statement (a payout, licence, prize, grant or credit) and close again. The "Answer a dispute"
# workflow runs it too, with ANSWER_* set: the operator's answer to one seller's dispute goes in the book.
#
# 1. Take the published site from the gh-pages branch.
# 2. Read the lab's ledger again (its receipt roots and pledge figures), so the close sees the month's final figures.
# 3. Post the statement, if one was given (STATEMENT_* variables), then close every finished month not yet closed,
#    or close CLOSE_PERIOD again.
# 4. Verify the whole site, and only then commit it to gh-pages.
#
# Nothing happens while the INSPECTOR_SIGNING_KEY secret is unset. The statement's own document never comes here:
# only its SHA-256 goes in the book.
set -euo pipefail

BRANCH="${PAGES_BRANCH:-gh-pages}"
SITE="${SITE_DIR:-site}"
INSPECTOR="${INSPECTOR:-agoranome-inspector}"

if [ -z "${INSPECTOR_SIGNING_KEY:-}" ]; then
  echo "::notice::The INSPECTOR_SIGNING_KEY secret is not set, so nothing was posted."
  exit 0
fi
if ! git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null; then
  echo "::notice::No $BRANCH branch yet: the accounts start once the weekly run has published a sheet."
  exit 0
fi

git config user.name "agoranome-inspector"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git fetch --depth=1 origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
git worktree add -B "$BRANCH" "$SITE" "origin/$BRANCH"

if ! "$INSPECTOR" anchor-lab "$SITE" ${LAB_LEDGER:+--ledger "$LAB_LEDGER"}; then
  echo "::warning::The lab's ledger could not be read again; the close uses the figures the book already holds."
fi

if [ -n "${STATEMENT_TYPE:-}" ]; then
  args=(statement "$SITE" --type "$STATEMENT_TYPE" --from "${STATEMENT_FROM:?name who paid}"
        --period "${STATEMENT_PERIOD:?the month it arrived, YYYY-MM}" --amount-usd "${STATEMENT_AMOUNT_USD:?}"
        --document-sha256 "${STATEMENT_DOCUMENT_SHA256:?the document hash}")
  [ -n "${STATEMENT_DOCUMENT_URL:-}" ] && args+=(--document-url "$STATEMENT_DOCUMENT_URL")
  [ "${STATEMENT_GRANT_TESTS:-}" = "true" ] && args+=(--passes-grant-tests)
  [ -n "${STATEMENT_NOTE:-}" ] && args+=(--note "$STATEMENT_NOTE")
  # More flags, one word each, with no shell in between (e.g. "--currency EUR --amount 5000").
  if [ -n "${STATEMENT_MORE:-}" ]; then
    read -r -a more <<< "$STATEMENT_MORE"
    args+=("${more[@]}")
  fi
  "$INSPECTOR" "${args[@]}"
fi

if [ -n "${ANSWER_ID:-}" ]; then
  args=(answer "$SITE" "$ANSWER_ID" --outcome "${ANSWER_OUTCOME:?upheld or not_upheld}" --reason "${ANSWER_REASON:?}")
  [ -n "${ANSWER_CORRECTION:-}" ] && args+=(--correction "$ANSWER_CORRECTION")
  "$INSPECTOR" "${args[@]}"
fi

"$INSPECTOR" close "$SITE" ${CLOSE_PERIOD:+--period "$CLOSE_PERIOD"}
"$INSPECTOR" verify "$SITE" --all ${INSPECTOR_FIRST_KID:+"--key=$INSPECTOR_FIRST_KID"}
(
  cd "$SITE"
  git add -A
  if git diff --cached --quiet; then
    echo "Nothing new to publish."
  else
    git commit -q -m "Accounts $(date -u +%Y-%m-%d)"
    git push origin "$BRANCH"
    echo "Published: $(tr -d '\n ' < head.json)"
  fi
)
