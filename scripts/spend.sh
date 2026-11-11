#!/usr/bin/env bash
# The model spend ledger: one append-only file (spend.jsonl) on its own branch, model-spend, so that every job that
# may call a model reads the month's spend before it does (see src/agoranome_inspector/models.py).
#
#   bash scripts/spend.sh pull   put the branch in $SPEND_DIR (default: spend), or start it
#   bash scripts/spend.sh push   commit what was added and push it, merging with any push made meanwhile
#
# The jobs that use it run one at a time (concurrency group model-spend); the file merges line by line
# (merge=union) all the same.
set -euo pipefail

BRANCH="${SPEND_BRANCH:-model-spend}"
DIR="${SPEND_DIR:-spend}"

git config user.name >/dev/null || git config user.name "agoranome-inspector"
git config user.email >/dev/null || git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

case "${1:-}" in
  pull)
    if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null; then
      git fetch --depth=50 origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
      git worktree add -B "$BRANCH" "$DIR" "origin/$BRANCH"
    else
      echo "No $BRANCH branch yet: starting the spend ledger."
      git worktree add --orphan -b "$BRANCH" "$DIR"
      printf 'spend.jsonl merge=union\n' > "$DIR/.gitattributes"
    fi
    touch "$DIR/spend.jsonl"
    ;;
  push)
    cd "$DIR"
    git add -A
    if git diff --cached --quiet; then
      echo "No model spend to record."
      exit 0
    fi
    git commit -q -m "Model spend, $(date -u +%Y-%m-%dT%H:%MZ)"
    for wait in 2 4 8 16; do
      if git push origin "$BRANCH"; then
        exit 0
      fi
      sleep "$wait"
      git fetch --depth=50 origin "$BRANCH"
      git merge -q --no-edit "origin/$BRANCH"
    done
    echo "::error::The spend ledger could not be pushed."
    exit 1
    ;;
  *)
    echo "usage: spend.sh pull|push" >&2
    exit 2
    ;;
esac
