---
name: deploy
description: Deploy the Spotify Auto-Skipper app to the VPS. Use this skill whenever the user asks to deploy, push to production, update the server, or says something like "deploy this", "push to server", "update VPS", "ship it". Also trigger when the user says "deploy" as a standalone command. This skill handles the full deploy pipeline including version verification, git push, SSH build, and health check.
---

# Deploy to VPS

This skill deploys the Spotify Auto-Skipper to the VPS. Follow these steps exactly — do not improvise or try alternative paths.

## Environment Variables

Before deploying, read these from the user's global CLAUDE.md or memory. The skill uses these placeholders:
- `$DEPLOY_USER` — SSH user
- `$DEPLOY_HOST` — VPS hostname
- `$DEPLOY_REPO` — git repo path on VPS
- `$DEPLOY_APP` — app/Docker context path on VPS

## Server Layout

- **Git repo on VPS:** `$DEPLOY_REPO` (full repo clone)
- **Symlink:** `$DEPLOY_APP` → `$DEPLOY_REPO/cloud`
- **Docker context:** `$DEPLOY_APP` (which is `cloud/`)
- **Environment:** `$DEPLOY_APP/.env`
- **Database:** Docker volume `skipper_skipper_data` (not a filesystem folder)
- **Container:** `skipper` (fixed via `container_name` in docker-compose.yml)
- **Compose project:** pinned to `skipper` via the top-level `name:` field in docker-compose.yml. This keeps the project name (and thus the data volume `skipper_skipper_data`) stable no matter which directory `docker compose` runs from. Do NOT pass `-p` or rely on the directory basename.

## Deploy Steps

### 1. Read the current version

```bash
cat cloud/app/__init__.py
```

Extract the version string (e.g., `v3.3.4`). This is the version that will be deployed.

### 2. Verify the version is pushed to remote

The VPS pulls from GitHub, so the version commit must be on the remote already.

```bash
git log origin/$(git branch --show-current) --oneline -1
```

If the local commit is ahead of the remote, push first:

```bash
git push origin $(git branch --show-current)
```

### 3. Deploy via SSH

Run this single SSH command (do NOT cd into subdirectories separately or try other paths):

```bash
ssh $DEPLOY_USER@$DEPLOY_HOST "cd $DEPLOY_REPO && git fetch --all && git checkout <BRANCH> && git pull && cd cloud && docker compose up -d --build"
```

Replace `<BRANCH>` with the current branch name. Use a 120-second timeout for this command since Docker builds can take a while.

### 4. Health check

Wait 5 seconds for the container to start, then:

```bash
ssh $DEPLOY_USER@$DEPLOY_HOST "curl -s http://localhost:8000/health"
```

Verify the response contains:
- `"version": "<expected version>"` — must match what's in `cloud/app/__init__.py`
- `"worker_running": true`
- `"worker_alive": true`

### 5. Report result

Tell the user:
- Which version was deployed
- Whether the health check passed
- If anything went wrong, show the exact error

## Troubleshooting

If the SSH command fails with "not a git repository", the symlink or repo may be broken. Check:
```bash
ssh $DEPLOY_USER@$DEPLOY_HOST "ls -la $DEPLOY_APP && ls -la $DEPLOY_REPO/.git"
```

If the deploy hook blocks the build with "already deployed", the version suffix needs to be incremented in `cloud/app/__init__.py` before retrying.

If `docker compose up` fails with a container-name conflict (`The container name "/skipper" is already in use`), the Compose project name resolved to something other than `skipper` (e.g. `cloud`, from the directory basename). Confirm `name: skipper` is present at the top of `cloud/docker-compose.yml`. As a one-off recovery, deploy with the explicit project: `docker compose -p skipper up -d --build`. Never let it create a `cloud_skipper_data` volume — that is an empty/stale DB, not the live one.
