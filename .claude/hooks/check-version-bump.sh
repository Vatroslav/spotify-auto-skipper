#!/bin/bash
# PreToolUse hook: intent-based bump guard.
# Veze se na DEKLARIRANU NAMJERU (tip commita), ne na putanju fajla.
# Zamijenio stari path-based/-N snapshot model (migracija 2026-07-11).

# What this command commits, read by read-commit.py next to this script: the repo it goes
# to (git -C, cd), the files, the message. No output means no commit in this repo.
PARSED=$(python "$(dirname "$0")/read-commit.py" 2>/dev/null)
[ -n "$PARSED" ] || exit 0
FACTS=$(printf '%s\n' "$PARSED" | sed '/^msg$/,$d')
MSG=$(printf '%s\n' "$PARSED" | sed '1,/^msg$/d')
SKIP=$(printf '%s\n' "$FACTS" | sed -n 's/^skip //p')
if [ -n "$SKIP" ]; then
    printf '{"systemMessage":"check-version-bump: %s"}' "$SKIP"
    exit 0
fi

# Version-file paths below are root-relative, and a worktree has its own root.
cd "$(printf '%s\n' "$FACTS" | sed -n 's/^root //p')" || exit 0
STAGED=$(printf '%s\n' "$FACTS" | sed -n 's/^file //p')

# Guard se aktivira samo ako su app source fileovi (cloud/) dirani
echo "$STAGED" | grep -qE '^cloud/' || exit 0

deny() {
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}' "$1"
    exit 0
}

# Tip je u PRVOM retku (conventional header). MSG je cesto viseredan (tijelo +
# Co-Authored-By), pa tip vadimo samo iz headera - inace sed hvata i rijeci iz
# tijela i TYPE postane viseredan (ne matcha case -> lazni blok).
HEADER=$(printf '%s' "$MSG" | head -1)
TYPE=$(printf '%s' "$HEADER" | sed -n 's/^\([a-zA-Z]\+\).*/\1/p' | tr 'A-Z' 'a-z')

# Breaking: "tip!:" / "tip(scope)!:" u headeru ili "BREAKING CHANGE" bilo gdje
BREAKING=0
printf '%s' "$HEADER" | grep -qE '^[a-zA-Z]+(\([^)]*\))?!:' && BREAKING=1
printf '%s' "$MSG" | grep -q 'BREAKING CHANGE' && BREAKING=1

# A version line changed by this commit, or earlier on this branch: a branch lands as one release.
bumped_in() {
    if printf '%s\n' "$STAGED" | grep -qxF "$1" && git diff HEAD -U0 -- "$1" 2>/dev/null | grep -qE "$2"; then
        return 0
    fi
    [ "$(git symbolic-ref --short -q HEAD)" != "main" ] || return 1
    BRANCH_BASE=$(git merge-base HEAD origin/main 2>/dev/null) || return 1
    git diff "$BRANCH_BASE" HEAD -U0 -- "$1" 2>/dev/null | grep -qE "$2"
}

BUMPED=0
bumped_in cloud/app/__init__.py '^\+[[:space:]]*APP_VERSION' && BUMPED=1

# Breaking uvijek trazi bump (major)
if [ "$BREAKING" = "1" ] && [ "$BUMPED" != "1" ]; then
    deny "Breaking promjena (!: / BREAKING CHANGE) a verzija nije podignuta. Bumpaj major u cloud/app/__init__.py."
fi

case "$TYPE" in
    feat|fix|perf)
        [ "$BUMPED" = "1" ] || deny "Tip '$TYPE' mijenja ponasanje a verzija nije podignuta. Bumpaj cloud/app/__init__.py (feat -> minor, fix/perf -> patch)."
        ;;
    docs|chore|style|refactor|test|ci|build|revert)
        : # bez bumpa OK
        ;;
    *)
        deny "Diras app source (cloud/) ali namjera nije deklarirana. Dodaj conventional prefiks u commit poruku (feat/fix/docs/chore/refactor...) da guard moze odluciti treba li bump."
        ;;
esac

exit 0
