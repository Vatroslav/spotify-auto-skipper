---
name: release
description: Finalize and release a tested change - land it on main, create git tag + GitHub release, update todo. Use when the user says "release", "release it", "merge it", "ship the release", "završi", or when a change has been verified healthy on production and is ready for main. NOT for deploying during iteration - that is the /deploy skill.
---

# Release a finished change

This is the choreography from "the change is tested" to "the release is published". Every release in this repo follows it (see PRs #62-#72). Follow the order exactly — the two historical failures both came from skipping a step (PR #48 merge lost code; v3.9.0 needed a fixup commit to bump main after merge).

Versioning model — full rules: `~/.claude/knowledge/versioning-intent.md`. The repo-specific delta: the version was already bumped in the feature commit that changed behavior. Releasing does NOT touch the version — it lands, tags, and deploys the number that is already on the branch.

## Preconditions

- You are on a feature branch (never release directly from main).
- The change was verified: deployed to production and healthy (via `/deploy` on the branch), or explicitly approved by the user.
- The version in `cloud/app/__init__.py` is already the final target number, bumped in the behavior-changing commit. If a source change on the branch has no bump yet, fix that before releasing.

## Steps

### 1. Sync with main if it diverged

```bash
git fetch origin
git log HEAD..origin/main --oneline
```

If main has commits the branch doesn't: merge `origin/main` INTO the branch first and resolve conflicts here, not in the PR. **After resolving, verify no branch changes were lost** — diff the branch against main and confirm every intended change is still present:

```bash
git diff origin/main...HEAD --stat
```

This is the PR #48 lesson: a merge resolution silently dropped the Like/Unlike pieces and they had to be restored in a follow-up commit (`8304569`).

### 2. Update docs/todo.md on the branch

If the change resolves a `docs/todo.md` item, mark it `[x]` and append the version + PR number to the entry — in this same branch, before the merge (precedent: `a0ae497`, `1411476`). This is a docs-only commit → **no bump**; prefix it `docs:`.

### 3. PR and merge

```bash
gh pr create --base main --title "..." --body "..."
gh pr merge <N> --merge
```

Use a merge commit (`--merge`), not squash — the repo history keeps individual commits.

### 4. Tag + GitHub release (always together)

After the merge, tag the merge commit on main. The tag is the version already live on the branch:

```bash
git checkout main && git pull
git tag vX.Y.Z
git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z — <short description>" --notes "<what changed and why>"
```

Never create the tag without the GitHub release or vice versa.

### 5. Deploy the release

Run the `/deploy` skill from main. The health check must report the target version, `worker_running: true`, `worker_alive: true`.

### 6. Record it

Update the project memory: last known version, one-paragraph summary of what shipped and any watch-outs learned during the work.

## Rules

- Versioning rules (which commit types bump, hook enforcement): `~/.claude/knowledge/versioning-intent.md`.
- Do **not** make a source-touching "Release ..." commit: a bare `Release` subject is not a conventional type and the hook will block it. The version already lives in the feature commit, so the release step touches only `docs/todo.md` and the main merge.
- Never `git push --force` to main (branch protection is on).
- Do not delete the feature branch without asking.
