#!/bin/bash
# PreToolUse hook: block git commit AND VPS deploy if version not bumped

# Parse command from stdin JSON
CMD=$(python -c "import sys,json; print(json.load(sys.stdin)['tool_input']['command'])" 2>/dev/null)

# ── Check 1: Block VPS deploys without version bump ──────────────
# Catch ANY ssh/tar command targeting the VPS that rebuilds docker
if echo "$CMD" | grep -qE 'docker compose up.*--build|tar.*ssh.*docker'; then
    # Check if cloud/ files have been modified (staged or unstaged) since last commit
    CLOUD_CHANGES=$(git diff --name-only HEAD -- cloud/ 2>/dev/null; git diff --cached --name-only -- cloud/ 2>/dev/null)
    # Also check untracked cloud files
    CLOUD_CHANGES="$CLOUD_CHANGES
$(git ls-files --others --exclude-standard -- cloud/ 2>/dev/null)"

    # Remove cloud/app/__init__.py from the list to see if there are OTHER changes
    OTHER_CHANGES=$(echo "$CLOUD_CHANGES" | grep -v '^$' | grep -v '^cloud/app/__init__.py$' | head -1)

    if [ -n "$OTHER_CHANGES" ]; then
        # There are cloud changes — verify __init__.py was also bumped
        VERSION_CHANGED=$(git diff HEAD -- cloud/app/__init__.py 2>/dev/null; git diff --cached -- cloud/app/__init__.py 2>/dev/null)
        if [ -z "$VERSION_CHANGED" ]; then
            printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Deploy blocked! cloud/ files changed but cloud/app/__init__.py version not bumped. Increment the version first."}}'
            exit 0
        fi
    fi

    # ── Check 1b: If version has a test suffix, ensure it was incremented ──
    LAST_DEPLOY_FILE=".claude/hooks/.last-deployed-version"
    CURRENT_VERSION=$(sed -n 's/.*APP_VERSION.*"\(v\?\)\([^"]*\)".*/\2/p' cloud/app/__init__.py 2>/dev/null)

    if echo "$CURRENT_VERSION" | grep -qE '\-[0-9]+$'; then
        # Has test suffix — check against last deploy
        if [ -f "$LAST_DEPLOY_FILE" ]; then
            LAST_VERSION=$(cat "$LAST_DEPLOY_FILE")
            if [ "$CURRENT_VERSION" = "$LAST_VERSION" ]; then
                # Calculate next suffix
                CUR_SUFFIX=$(echo "$CURRENT_VERSION" | sed -E 's/.*-([0-9]+)$/\1/')
                NEXT_SUFFIX=$((CUR_SUFFIX + 1))
                BASE=$(echo "$CURRENT_VERSION" | sed -E 's/-[0-9]+$//')
                NEXT_VERSION="${BASE}-${NEXT_SUFFIX}"
                printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Deploy blocked! Test version %s was already deployed. Increment the suffix (e.g. %s → %s) before deploying again."}}' \
                    "$CURRENT_VERSION" "$CURRENT_VERSION" "$NEXT_VERSION"
                exit 0
            fi
        fi
        # Save current version as last deployed (will be written by post-deploy hook)
    fi
fi

# ── Check 2: Block git commit without version bump ───────────────
echo "$CMD" | grep -qE 'git commit' || exit 0

# Get staged files + any files mentioned in a git add in the same command
STAGED=$(git diff --cached --name-only)
# For chained commands like "git add file1 file2 && git commit", extract added paths
ADD_PART=$(echo "$CMD" | sed -n 's/.*git add \([^&]*\).*/\1/p')
if [ -n "$ADD_PART" ]; then
    # Convert space-separated paths to newline-separated
    STAGED="$STAGED
$(echo "$ADD_PART" | tr ' ' '\n')"
fi

# Only care if cloud/ or spotify_auto_skipper/ files are staged
echo "$STAGED" | grep -qE '^cloud/|^spotify_auto_skipper/' || exit 0

MISSING=""

# Check cloud version
if echo "$STAGED" | grep -q '^cloud/'; then
    if ! echo "$STAGED" | grep -q '^cloud/app/__init__.py$'; then
        MISSING="${MISSING} cloud/app/__init__.py"
    fi
fi

# Check desktop version
if echo "$STAGED" | grep -q '^spotify_auto_skipper/'; then
    if ! echo "$STAGED" | grep -q '^spotify_auto_skipper/__init__.py$'; then
        MISSING="${MISSING} spotify_auto_skipper/__init__.py"
    fi
fi

# All good
[ -z "$MISSING" ] && exit 0

# Block the commit
printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Version not bumped! Update:%s"}}' "$MISSING"
