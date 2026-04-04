#!/bin/bash
# PreToolUse hook (Edit): block edits that decrease APP_VERSION in __init__.py

INPUT=$(cat)

# Extract file_path and new_string from Edit tool input
FILE_PATH=$(echo "$INPUT" | python -c "import sys,json; print(json.load(sys.stdin)['tool_input'].get('file_path',''))" 2>/dev/null)
NEW_STRING=$(echo "$INPUT" | python -c "import sys,json; print(json.load(sys.stdin)['tool_input'].get('new_string',''))" 2>/dev/null)

# Only check __init__.py files with APP_VERSION changes
echo "$FILE_PATH" | grep -q '__init__.py$' || exit 0
echo "$NEW_STRING" | grep -q 'APP_VERSION' || exit 0

[ -f "$FILE_PATH" ] || exit 0

# Use a single Python script for all logic to avoid shell quoting issues
python -c "
import re, sys, json

# Read current version from file
with open(sys.argv[1]) as f:
    cur_match = re.search(r'APP_VERSION\s*=\s*[\"\\x27]v?([^\"\\x27]+)[\"\\x27]', f.read())
if not cur_match:
    sys.exit(0)
cur = cur_match.group(1)

# Extract new version from the edit string
new_match = re.search(r'APP_VERSION\s*=\s*[\"\\x27]v?([^\"\\x27]+)[\"\\x27]', sys.argv[2])
if not new_match:
    sys.exit(0)
new = new_match.group(1)

def parse_ver(v):
    parts = v.split('-', 1)
    base = [int(x) for x in re.findall(r'\d+', parts[0])]
    suffix = [int(x) for x in re.findall(r'\d+', parts[1])] if len(parts) > 1 else []
    return base, suffix

cur_base, cur_suf = parse_ver(cur)
new_base, new_suf = parse_ver(new)

decreased = False
if new_base < cur_base:
    decreased = True
elif new_base == cur_base:
    if not cur_suf and new_suf:
        decreased = True
    elif cur_suf and new_suf and new_suf < cur_suf:
        decreased = True

if decreased:
    out = {
        'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': f'Version decrease blocked! Current: v{cur}, attempted: v{new}. Version can only go up.'
        }
    }
    print(json.dumps(out))
" "$FILE_PATH" "$NEW_STRING"
