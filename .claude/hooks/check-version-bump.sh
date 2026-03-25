#!/bin/bash
# PreToolUse hook: block git commit if version not bumped

# Parse command from stdin JSON
CMD=$(python -c "import sys,json; print(json.load(sys.stdin)['tool_input']['command'])" 2>/dev/null)

# Only care about git commit commands
echo "$CMD" | grep -qE 'git commit' || exit 0

# Get staged files + any files mentioned in a git add in the same command
STAGED=$(git diff --cached --name-only)
# For chained commands like "git add file1 file2 && git commit", extract added paths
ADD_PART=$(echo "$CMD" | sed -n 's/.*git add \([^&]*\).*/\1/p')
if [ -n "$ADD_PART" ]; then
    STAGED="$STAGED
$(echo "$ADD_PART" | tr ' ' '\n')"
fi

# Only care if cloud/ files are staged
echo "$STAGED" | grep -q '^cloud/' || exit 0

MISSING=""

# Check cloud version
if echo "$STAGED" | grep -q '^cloud/'; then
    if ! echo "$STAGED" | grep -q '^cloud/app/__init__.py$'; then
        MISSING="${MISSING} cloud/app/__init__.py"
    fi
fi

# All good
[ -z "$MISSING" ] && exit 0

# Block the commit
printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Version not bumped! Update:%s"}}' "$MISSING"
