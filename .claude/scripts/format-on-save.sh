#!/bin/bash
input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')
[ -z "$file_path" ] && exit 0
[ ! -f "$file_path" ] && exit 0

case "$file_path" in
  *.py)
    ruff format --quiet "$file_path" 2>/dev/null
    ruff check --fix --quiet "$file_path" 2>/dev/null
    ;;
esac
exit 0
