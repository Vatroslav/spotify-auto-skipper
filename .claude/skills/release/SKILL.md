---
name: release
description: Finalize and release a tested change - set the final version, land it on main, create git tag + GitHub release, update todo. Use when the user says "release", "release it", "merge it", "ship the release", "završi", or when a test snapshot has been verified healthy on production and the change is ready for main. NOT for deploying test snapshots during iteration - that is the /deploy skill.
---

# Release a finished change

This is the choreography from "the fix is tested" to "the release is published". Every release in this repo follows it (see PRs #62-#72). Follow the order exactly — the two historical failures both came from skipping a step (PR #48 merge lost code; v3.9.0 needed a fixup commit to bump main after merge).

## Preconditions

- You are on a feature branch (never release directly from main).
- The change was verified: test snapshot (`vX.Y.Z-N`) deployed to production and healthy, or explicitly approved by the user without a snapshot.
- You know the final version. Semantic rules: MAJOR = breaking, MINOR = new feature, PATCH = bug fix/tweak. If unsure which, ask.

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

### 2. Set the final version

Edit `cloud/app/__init__.py`: remove the `-N` test suffix (e.g. `v3.16.8-3` → `v3.16.8`). Test suffixes must NEVER land on main.

### 3. Update docs/todo.md on the branch

If the change resolves a `docs/todo.md` item, mark it `[x]` and append the version + PR number to the entry — in this same branch, before the merge (precedent: `a0ae497`, `1411476`).

### 4. Release commit

Commit message format (see git log for examples):

```
Release vX.Y.Z — <short description of the change>
```

Push the branch.

### 5. PR and merge

```bash
gh pr create --base main --title "..." --body "..."
gh pr merge <N> --merge
```

Use a merge commit (`--merge`), not squash — the repo history keeps individual snapshot commits.

### 6. Tag + GitHub release (always together)

After the merge, tag the merge commit on main:

```bash
git checkout main && git pull
git tag vX.Y.Z
git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z — <short description>" --notes "<what changed and why>"
```

Never create the tag without the GitHub release or vice versa.

### 7. Deploy the release

Run the `/deploy` skill from main. The health check must report the final version (no suffix), `worker_running: true`, `worker_alive: true`.

### 8. Record it

Update the project memory: last known version, one-paragraph summary of what shipped and any watch-outs learned during the work.

## Rules

- Every commit on main bumps the patch version — including docs/tooling-only commits (user feedback, no exceptions). Docs-only bumps don't get a tag/release, just the version bump in the commit.
- A pre-commit hook blocks commits that stage `cloud/` files without bumping `cloud/app/__init__.py` — that's a signal you forgot step 2, not something to work around.
- Never `git push --force` to main (branch protection is on).
- Do not delete the feature branch without asking.
