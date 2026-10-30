# AGENTS-RULES.md — Central rules and synchronization tooling

Read this supplement together with `AGENTS.md`. This repository contains shared instructions and Python/GitHub Actions tooling, not an installable FHEM module. Module version bumps, commandref, Perl checks and release packaging are inapplicable here.

- Maintain generic instructions only in root `AGENTS.md`. Preserve its existing engineering contracts when changing governance or tooling. Do not collect module-specific configuration or firmware workarounds here.
- A proposed rule needs concrete evidence, a reason it applies beyond its originating project, scope/limits, and a check for duplication or contradictions. Prefer refining an existing rule to appending another prohibition. Automation cannot establish semantic correctness; maintainer review remains necessary.
- Originating project work must link its central proposal. Never discard a local instruction change by blindly synchronizing over it. Use the failed check's patch to retain and review the discovery; a patch is a proposal, not approved policy.
- Consumers use only revisions reachable from central `main`. The check must reject another source, an unmerged revision, a missing supplement, or a byte mismatch. It must not replace local files.
- Synchronization may write only `AGENTS.md` and `.github/agent-rules.json`, only on its dedicated branch. Preserve project supplements, code, workflows and all unrelated files. Reject drift on the default branch or hand-edited synchronization branches. Never force-push or merge.
- Keep checker/tooling pins separate from the adopted rules revision. Ordinary rule updates must not rewrite workflow files or execute scripts from a newly proposed rules revision.
- Use only Python standard-library runtime dependencies. The local and central CI entry point is `bash scripts/ci.sh`. Tests must include real temporary Git histories and a stateful API double for branch/PR synchronization, including negative cases and idempotency. State that doubles do not prove live GitHub App permissions or settings.
- Only trusted central default-branch workflows may receive the GitHub App token. Consumer PR checks are read-only and never execute consumer code. Do not use `pull_request_target` to run a contributor's code with write credentials.
- `consumers.json` is the explicit distribution allowlist. Do not discover and modify other repositories automatically.
- After changes, review all instructions, scripts, tests, workflow files and README together. Report exact tests, branch/PR effects, remaining setup, and any unperformed live distribution test. Do not claim an inactive workflow or an optional status check is enforced.
