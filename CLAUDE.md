# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow

- **Questions are not instructions.** When the user asks how something works or asks a question, answer the question. Do NOT start editing code unless explicitly told to make a change.
- **DELETE safety.** Always wrap DELETE operations in a transaction: BEGIN, DELETE, check affected row count matches expected, COMMIT only if correct, ROLLBACK otherwise.
- **Pydantic model ordering.** Never insert a new BaseModel class between an existing model's fields and its `@field_validator` decorators — the validators rebind to the new class and crash startup with PydanticUserError (bit us in v3.15.0).

## Permissions

- Main branch has force-push protection enabled on GitHub — do not attempt `git push --force` to main

## Build & Deploy

```bash
# Build and start locally
cd cloud
docker compose up -d --build

# View logs
docker compose logs -f
```

No tests or linting are configured. For deployment, use the `/deploy` skill which reads connection details from the user's private config.

## Versioning

Intent-based model (migrated 2026-07-11 from the old `-N` snapshot model) - full rules: `~/.claude/knowledge/versioning-intent.md` (in Croatian).
- Version file: `cloud/app/__init__.py` (`APP_VERSION`, format `vX.Y.Z`, no suffix).
- The guard activates on `cloud/`.
- Hooks: `.claude/hooks/check-version-bump.sh` + `.claude/hooks/check-version-decrease.sh` (blocks any edit that lowers `APP_VERSION`).
- Tag only on prod deploy.

## Health monitoring

Design (worker self-healing: crash vs clean stop, conscious no-autoheal decision) is documented in [README.md](README.md) under "Health monitoring" — read it before touching `worker.py` lifecycle or the Docker HEALTHCHECK.
