"""PreToolUse hook: block running the cloud app code locally.

On 2026-09-13 a local script that imported `app.*` from cloud/ froze the PC three times
until a forced restart (memory: feedback_no_local_app_execution). Cloud code is verified
only with `ruff check .`, `ast.parse` (parse, no import) and a deploy to the VPS.

Blocks (deny, so Claude rewrites the step instead of Vatra getting a prompt):
- Bash/PowerShell that runs python/pytest/uvicorn and imports the app (`import app`,
  `from app`, `app.main:app`) or runs code under cloud/ (cwd in cloud/, `cd cloud`,
  `python cloud/x.py`). Allowed: ruff, and `ast.parse` without importing app.
- preview_start of the `cloud-dev` server (uvicorn locally, needs production secrets).
"""
import json
import re
import sys

RUNNER = re.compile(r"(?:^|[\s;&|(\"'])(?:python3?|py|pytest|uvicorn)(?:\.exe)?(?=[\s\"';&|)]|$)", re.I)
IMPORTS_APP = re.compile(r"\b(?:import\s+app\b|from\s+app\b|app\.main:app)")
IN_CLOUD = re.compile(
    r"(?:^|[\s;&|(])(?:cd|pushd|Set-Location)\s+[\"']?(?:\./)?cloud\b"
    r"|(?:^|[\s\"'/])cloud/\S*\.py\b",
    re.I,
)
SAFE = re.compile(r"\bruff\b|\bast\.parse\b")

REASON = ("Running the cloud app locally is blocked: on 2026-09-13 a local script that imported "
          "app.* froze Vatra's PC three times. Verify with `ruff check .`, `python -c \"import ast; "
          "ast.parse(...)\"` (no import), or deploy the feature branch to the VPS and read the logs.")


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    tool = data.get("tool_name") or ""
    inp = data.get("tool_input") or {}
    if tool.endswith("__preview_start"):
        if inp.get("name") == "cloud-dev":
            deny("The cloud-dev server needs production secrets (SECRET_KEY, Spotify OAuth) and "
                 "must not run locally. " + REASON)
        return
    cmd = inp.get("command") or ""
    if not RUNNER.search(cmd):
        return
    cwd = (data.get("cwd") or "").replace("\\", "/").rstrip("/") + "/"
    in_cloud = "/cloud/" in cwd
    if IMPORTS_APP.search(cmd):
        deny(REASON)
    if (in_cloud or IN_CLOUD.search(cmd)) and not SAFE.search(cmd):
        deny(REASON)


if __name__ == "__main__":
    main()
