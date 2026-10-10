# AGENTS

Project-local notes:
- Keep adapters simple and runnable.
- Prefer clear stdout status lines.
- For AI Agents: see `docs/AI_USAGE_RULES.md` for CLI rules.
- After creating or formalizing a new test pack and completing meaningful live validation, do not stop at code/commit. Required closeout is: validation closeout + reusable skill capture. Treat this as mandatory, not optional.
- Commit discipline: each completed independent small intent must be committed immediately as its own atomic commit. Do not batch unrelated intents into one commit.

## SpectraSynq Git publication — 10 October 2026

Captain's publication target is `https://github.com/synqing/ai-embedded-lab.git`
on the existing `master` branch. The original author repository
`https://github.com/EZ32Inc/ai-embedded-lab.git` is retained as `upstream`.
Before returning an authentication/access blocker, inspect the actual remote,
authenticated identity and target repository permissions. A broad token scope
does not establish write access to another owner's repository. Preserve upstream
history and use normal fast-forward publication; never force push or overwrite
the separate SpectraSynq-EdgeAI-Lab project because its name appears similar.

Titan continuations: before treating a measurement gap as a hardware-wide blocker,
read /Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan/docs/migration/TITAN-FIRST-ISOLATED-SESSION-2026-10-08.txt
and the shared spectrasynq-workflow progress/blocker rule. Preserve the connected-strip
HOLD. Isolated diagnostic readiness is checked after boot and before stimulus;
physical exclusion and actual scoped authority still precede programming.

## Titan absent-USB incident prevention — 10 October 2026
Before asking Captain to reconnect cables or debug a serial monitor, read the
mandatory absent-USB recovery order in
`/Users/spectrasynq/Workspace_Management/Software/SpectraSynq-PRISM/Kx-Titan/docs/migration/NATIVE-FIRST-BOOT-2026-10-08.md`.
Inventory USB and serial separately; consume prior recovery evidence. Where
already authorised and applicable, root performs one bounded E2 Lite signature/
read-and-run with probe power OFF, then verifies application identity and restores
ownership. Do not bypass a denial or substitute unverified flashing. Ask for one
physical action only after the remaining physical dependency is identified.
