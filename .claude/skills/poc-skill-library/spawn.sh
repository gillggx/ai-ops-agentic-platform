#!/usr/bin/env bash
# spawn.sh — recreate the Skill Library POC branch off the current main.
#
# Usage: bash .claude/skills/poc-skill-library/spawn.sh [branch-name]
#   default branch-name: poc/skill-library-YYYYMMDD
#
# What it does:
#   1. Sanity check working tree + git state
#   2. git worktree backup of current main into a sibling directory
#   3. Fetch origin/poc/skill-library (source of the canonical commits)
#   4. Create new branch off main, cherry-pick the two POC commits
#   5. Push, print DevOps pull instructions
#
# Aborts loudly on the first failure — never leaves the repo in a
# half-merged state. Re-run after you've fixed whatever it complained
# about.

set -euo pipefail

# ── Canonical POC commits (SHAs on origin/poc/skill-library) ─────────────
SOURCE_REMOTE_BRANCH="origin/poc/skill-library"
COMMIT_STRIP="1d443ab"     # chore(poc): strip ontology_simulator
COMMIT_MCP_HEADERS="965f74b"  # feat(poc-mcp): headers form + ${ENV} interpolation

# ── Args ─────────────────────────────────────────────────────────────────
DEFAULT_BRANCH="poc/skill-library-$(date +%Y%m%d)"
NEW_BRANCH="${1:-$DEFAULT_BRANCH}"

# ── Helpers ──────────────────────────────────────────────────────────────
err()  { printf '\033[31m[err]\033[0m  %s\n' "$*" >&2; exit 1; }
warn() { printf '\033[33m[warn]\033[0m %s\n' "$*" >&2; }
info() { printf '\033[36m[info]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m[ ok ]\033[0m %s\n' "$*"; }

# ── 1. Sanity ────────────────────────────────────────────────────────────
[ -d .git ] || err "run from repo root (current: $PWD)"
git diff --quiet || err "working tree has unstaged changes — stash or commit first"
git diff --cached --quiet || err "working tree has staged changes — stash or commit first"

if git rev-parse --verify "refs/heads/$NEW_BRANCH" >/dev/null 2>&1; then
  err "branch $NEW_BRANCH already exists locally — delete it or pick another name"
fi
if git ls-remote --exit-code --heads origin "$NEW_BRANCH" >/dev/null 2>&1; then
  err "branch $NEW_BRANCH already exists on origin — pick another name"
fi

info "fetching origin..."
git fetch origin --quiet

if ! git rev-parse --verify "$SOURCE_REMOTE_BRANCH" >/dev/null 2>&1; then
  err "$SOURCE_REMOTE_BRANCH not found — fetch failed or branch was deleted upstream"
fi
for sha in "$COMMIT_STRIP" "$COMMIT_MCP_HEADERS"; do
  if ! git cat-file -e "$sha" 2>/dev/null; then
    err "commit $sha not in the local repo even after fetch — POC source moved?"
  fi
done

# ── 2. Backup main ───────────────────────────────────────────────────────
# Prefer a git worktree (gives a physical read-only copy in a sibling dir).
# Fall back to a git tag when main is already checked out somewhere — git
# refuses two worktrees on the same branch. A tag is zero-cost and can be
# `git checkout`ed at any time to recover main exactly as it was.
REPO_NAME=$(basename "$PWD")
PARENT=$(dirname "$PWD")
TS=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="$PARENT/${REPO_NAME}_main_backup_${TS}"
BACKUP_DESC=""

main_checked_out_elsewhere=false
if git worktree list --porcelain | awk '/^branch /{print $2}' | grep -q "^refs/heads/main$"; then
  main_checked_out_elsewhere=true
fi

if [ -e "$BACKUP_PATH" ]; then
  warn "backup path already exists, reusing: $BACKUP_PATH"
  BACKUP_DESC="worktree $BACKUP_PATH"
elif $main_checked_out_elsewhere; then
  BACKUP_TAG="backup-main-${TS}"
  git tag "$BACKUP_TAG" main
  ok "main already checked out — created git tag '$BACKUP_TAG' as backup"
  info "recover with: git checkout $BACKUP_TAG  (or: git branch <name> $BACKUP_TAG)"
  BACKUP_DESC="git tag $BACKUP_TAG"
else
  info "creating main backup worktree at $BACKUP_PATH"
  git worktree add "$BACKUP_PATH" main >/dev/null
  ok "backup worktree ready"
  BACKUP_DESC="worktree $BACKUP_PATH"
fi

# ── 3. Create new branch off latest main ─────────────────────────────────
info "updating local main from origin/main..."
git checkout main --quiet
git pull --ff-only --quiet origin main

MAIN_HEAD=$(git rev-parse --short HEAD)
info "main is at $MAIN_HEAD — branching $NEW_BRANCH"
git checkout -b "$NEW_BRANCH" --quiet

# ── 4. Cherry-pick the canonical POC commits ─────────────────────────────
for sha in "$COMMIT_STRIP" "$COMMIT_MCP_HEADERS"; do
  short=$(git rev-parse --short "$sha")
  info "cherry-pick $short..."
  if ! git cherry-pick "$sha"; then
    git status --short
    cat <<EOF >&2

[!] cherry-pick of $short failed. The repo is in cherry-pick state.
    Resolve conflicts, then either:

      git cherry-pick --continue   # accept your resolution
      git cherry-pick --abort      # bail and let me re-run spawn.sh

    If conflicts are large enough that resolving by hand is risky,
    abort + branch delete + follow the Manual recipe in SKILL.md
    instead.
EOF
    exit 2
  fi
  ok "applied $short"
done

# ── 5. Push + summarize ─────────────────────────────────────────────────-
info "pushing $NEW_BRANCH to origin..."
git push --quiet -u origin "$NEW_BRANCH"
ok "pushed origin/$NEW_BRANCH"

NEW_HEAD=$(git rev-parse --short HEAD)
COUNT=$(git rev-list --count main..HEAD)

cat <<EOF

────────────────────────────────────────────────────
  POC branch ready
────────────────────────────────────────────────────
  branch:        $NEW_BRANCH
  base (main):   $MAIN_HEAD
  HEAD:          $NEW_HEAD
  commits ahead: $COUNT (expected: 2)
  main backup:   $BACKUP_DESC

  Pull on DevOps box:
      cd /opt/aiops
      git fetch
      git checkout $NEW_BRANCH
      git pull

  Then on EC2:
      sudo systemctl stop ontology-simulator 2>/dev/null
      sudo systemctl disable ontology-simulator 2>/dev/null
      sudo vi python_ai_sidecar/.env   # add external API tokens
      sudo bash deploy/java-update.sh
      sudo bash deploy/update.sh
────────────────────────────────────────────────────
EOF
