# Agent notes

Skills live in `.agents/skills/<name>/SKILL.md`. Load a matching skill **before** writing code or proposing a design.

## Agent skills

### Issue tracker

Local markdown files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default role labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` and `docs/adr/`. See `docs/agents/domain.md`.

## Skill triggers

Read `.agents/skills/<name>/SKILL.md` immediately when the situation matches, then follow it:

| Situation | Skill |
| --- | --- |
| New behaviour, a bug fix with tests, red-green-refactor, or a vertical slice | `tdd` |
| Something is broken, throwing, failing, slow, or the user says debug/diagnose | `diagnosing-bugs` |
| Designing a module interface, placing a seam, or making code more testable | `codebase-design` |
| Reviewing a branch, PR, or the diff since a commit/merge-base | `code-review` |
| Fuzzy domain terms, glossary work, `CONTEXT.md`, or an ADR | `domain-modeling` |
| A design question that needs throwaway UI or state-model code | `prototype` |
| Facts from docs/APIs that need cited primary-source research | `research` |
| An in-progress git merge or rebase with conflicts | `resolving-merge-conflicts` |
| Steps only a human can do: credentials, dashboards, one-off cutovers | `wizard` |
| Writing or editing skills, `AGENTS.md`, or other agent-facing docs | `writing-for-agents` |
| Stress-testing a plan in-chat (and no `/grill-*` skill is already running) | `grilling` |

User-invoked orchestrators stay slash-command only. Do not start them unless the user names them: `/grill-with-docs`, `/grill-me`, `/to-spec`, `/to-tickets`, `/implement`, `/triage`, `/wayfinder`, `/ask-matt`, `/improve-codebase-architecture`, `/handoff`, `/wait-what`.
