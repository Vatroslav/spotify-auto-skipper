#!/bin/bash
# PreToolUse hook: block DELETE statements that aren't wrapped in a transaction

CMD=$(python -c "import sys,json; print(json.load(sys.stdin)['tool_input']['command'])" 2>/dev/null)

# Only care about commands containing DELETE FROM
echo "$CMD" | grep -qi 'DELETE FROM' || exit 0

# Must also contain BEGIN (transaction)
if ! echo "$CMD" | grep -qi 'BEGIN'; then
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"DELETE blocked! All DELETE operations must be wrapped in a transaction (BEGIN, DELETE, verify row count, COMMIT/ROLLBACK)."}}'
    exit 0
fi
