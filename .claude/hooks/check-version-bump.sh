#!/bin/bash
# PreToolUse hook: intent-based bump guard.
# Veze se na DEKLARIRANU NAMJERU (tip commita), ne na putanju fajla.
# Zamijenio stari path-based/-N snapshot model (migracija 2026-07-11).

CMD=$(python -c "import sys,json; print(json.load(sys.stdin)['tool_input'].get('command',''))" 2>/dev/null)

# Samo git commit komande
echo "$CMD" | grep -qE 'git commit' || exit 0

# The hook runs from the session's current folder, not the repo root. Another repo
# (an added working directory) is not this guard's business; in a subfolder or worktree
# of this repo, go to its root because the version-file paths below are root-relative.
common_dir() { git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null; }
[ "$(common_dir .)" -ef "$(common_dir "$(dirname "$0")")" ] || exit 0
cd "$(git rev-parse --show-toplevel)" || exit 0

# Staged fileovi (+ fileovi dodani inline preko git add u istoj komandi)
STAGED=$(git diff --cached --name-only)
ADD_PART=$(echo "$CMD" | sed -n 's/.*git add \([^&;|]*\).*/\1/p')
if [ -n "$ADD_PART" ]; then
    STAGED="$STAGED
$(echo "$ADD_PART" | tr ' ' '\n')"
fi

# Guard se aktivira samo ako su app source fileovi (cloud/) dirani
echo "$STAGED" | grep -qE '^cloud/' || exit 0

deny() {
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}' "$1"
    exit 0
}

# Commit poruka iz -m / --message (robusno preko shlex)
# A PowerShell here-string (@'...'@ or @"..."@) goes first: shlex cannot read it.
MSG=$(printf '%s' "$CMD" | python -c "
import re, sys, shlex
cmd = sys.stdin.read()
here = re.search(r'(?:-m|--message)[ =]*@([\x27\x22])\r?\n(.*?)\r?\n\1@', cmd, re.S)
if here:
    print(here.group(2).strip())
    sys.exit()
try:
    toks = shlex.split(cmd)
except Exception:
    toks = []
msg = ''
for i, t in enumerate(toks):
    if t in ('-m', '--message') and i + 1 < len(toks):
        msg = toks[i + 1]; break
    if t.startswith('-m') and len(t) > 2:
        msg = t[2:]; break
    if t.startswith('--message='):
        msg = t[len('--message='):]; break
print(msg)
" 2>/dev/null)

# Tip je u PRVOM retku (conventional header). MSG je cesto viseredan (tijelo +
# Co-Authored-By), pa tip vadimo samo iz headera - inace sed hvata i rijeci iz
# tijela i TYPE postane viseredan (ne matcha case -> lazni blok).
HEADER=$(printf '%s' "$MSG" | head -1)
TYPE=$(printf '%s' "$HEADER" | sed -n 's/^\([a-zA-Z]\+\).*/\1/p' | tr 'A-Z' 'a-z')

# Breaking: "tip!:" / "tip(scope)!:" u headeru ili "BREAKING CHANGE" bilo gdje
BREAKING=0
printf '%s' "$HEADER" | grep -qE '^[a-zA-Z]+(\([^)]*\))?!:' && BREAKING=1
printf '%s' "$MSG" | grep -q 'BREAKING CHANGE' && BREAKING=1

# Je li version linija stvarno promijenjena u version fileu (ne samo staged)
BUMPED=0
git diff --cached -U0 -- cloud/app/__init__.py 2>/dev/null | grep -qE '^\+[[:space:]]*APP_VERSION' && BUMPED=1

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
