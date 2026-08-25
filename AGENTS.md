# AGENTS.md

> Generated as a working system prompt for OpenCode. Commit this file.
> Keep it a **map**, not an encyclopedia — under ~200 lines. If a section
> grows long, move detail to `docs/` and link it here instead of pasting it in.

## Project overview
<!-- One paragraph: what this repo does, primary language/framework. -->

## Directory layout
- `src/` — application source
- `tests/` — test suite
- `docs/` — deep architecture docs (read on demand, not by default)
- `docs/specs/` — feature specs (see workflow below)

## Commands
```bash
# install
# test
# lint
# run
```

## Hard constraints
<!-- Rules the agent must never break. Be specific — vague rules get ignored
     under context pressure; specific ones are enforceable. -->
- Do not edit `vendor/` or lockfiles unless explicitly asked
- Do not push to `main` directly
- Run tests before claiming a task is done
- Prefer small, PR-sized changes over large sweeping edits

## Conventions
<!-- Code style, naming, patterns specific to this repo. -->

## Workflow: Spec → Plan → Implement → Verify

This project uses a four-phase workflow for any non-trivial feature.
Each phase is a checkpoint — do not skip ahead without approval.

1. **Spec** (Plan mode, read-only)
   - Write the feature spec to `docs/specs/<feature-name>.md` before any
     code is discussed. Include: what "done" looks like, constraints,
     out-of-scope items.
   - Wait for explicit approval before moving to Plan.

2. **Plan** (Plan mode, read-only)
   - Convert the approved spec into an ordered list of small, file-scoped
     tasks. Each task must name exact files and the command that verifies it.
   - Wait for explicit approval before moving to Implement.

3. **Implement** (Build mode)
   - Execute one task at a time. Delegate self-contained sub-tasks
     (test-writing, docs, linting, code review) to subagents so they run
     in isolated context instead of growing the main session.
   - Commit after each task passes its verification command.

4. **Verify**
   - Check the diff against the original spec file, not against memory
     of the conversation.
   - Full test suite must pass before the feature is considered done.

## Agent notes
- Use **Plan mode** for anything touching more than one file or an
  unfamiliar module. Use **Build mode** only once a plan is approved.
- Read `docs/architecture.md` before large refactors.
- Prefer delegating narrow, well-defined sub-tasks to subagents
  (see `.opencode/agent/`) over doing everything in the main session.

## Subagents
<!-- Defined in .opencode/agent/*.md or opencode.json. List what exists here
     so the primary agent knows what's available to delegate to. -->
- `code-reviewer` — reviews diffs for correctness, security, maintainability;
  no edit permission
- `test-writer` — writes/updates tests for a given file; no edit permission
  outside test directories

## Context management
- Compaction is enabled (`opencode.json`: `"compaction": { "auto": true,
  "prune": true, "reserved": 10000 }`) — do not rely on old tool output
  staying in context; re-read files instead of trusting memory of them.
- Keep this file itself lean — if a section here exceeds a screen, move it
  to `docs/` and reference it instead.