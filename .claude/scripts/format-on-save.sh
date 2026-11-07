#!/bin/bash
input=$(cat)
file_path=$(echo "$input" | python -c "import sys,json; print(json.load(sys.stdin)['tool_input'].get('file_path',''))" 2>/dev/null)
[ -z "$file_path" ] && exit 0
[ ! -f "$file_path" ] && exit 0

# Only this repo's files: a session here can also write in other folders.
repo=$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null)
inside=$(python -c "import os,sys; n=lambda p: os.path.normcase(os.path.abspath(p)); print(n(sys.argv[1]).startswith(n(sys.argv[2]) + os.sep))" "$file_path" "$repo" 2>/dev/null)
[ "$inside" = "True" ] || exit 0

case "$file_path" in
  *.py)
    ruff format --quiet "$file_path" 2>/dev/null
    ruff check --fix --quiet "$file_path" 2>/dev/null
    ;;
esac
exit 0
