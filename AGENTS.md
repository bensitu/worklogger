# AGENTS.md

Universal instructions for AI coding agents.

## Core principles

- Think first. State assumptions, clarify ambiguity, and surface tradeoffs before editing.
- Keep it simple. Implement the smallest solution that solves the requested problem.
- Change surgically. Touch only files and lines directly related to the task.
- Verify by goals. Define success criteria, run relevant checks, and fix failures before finishing.

## Before coding

- Understand the current behavior before changing it.
- If requirements conflict, stop and explain the conflict.
- For larger tasks, write a short plan and define verification steps.
- Do not guess from filenames alone; inspect the actual implementation.

## Python and PySide6 rules

- Preserve the separation between UI, business logic, storage, constants, i18n, and packaging code.
- Do not rewrite large GUI sections, QSS, or layout structure unless explicitly requested.
- Do not block the UI thread with long-running work.
- Keep signal/slot behavior, theme switching, language switching, and calendar rendering compatible.
- Follow the existing error-handling and state-update patterns.

## Data, i18n, and packaging

- Preserve existing SQLite data and CSV compatibility.
- Do not change database schema or stored settings without an explicit migration plan.
- All user-visible strings must use the existing gettext/i18n mechanism.
- When adding resources, ensure they are included in PyInstaller/spec/build scripts.
- Pay attention to translations, templates, icons, holidays, tzlocal, and other runtime assets.

## Testing and verification

- Run the smallest relevant check first.
- Add or update tests when behavior changes, if the project has suitable tests.
- Prefer durable behavior and integration coverage; avoid duplicate checks of implementation details.
- Do not retain temporary diagnostic tests that only reproduce a single incident.
- Keep visual, screenshot, and native GUI checks opt-in. Run them only when changes affect the interface or platform rendering.
- Do not repeat the complete suite for every small change; match verification to the affected behavior and risk.
- If a check cannot be run, explain why and state what was verified instead.

## Safety

- Never expose secrets, tokens, credentials, or private data.
- Do not weaken validation, storage safety, logging, or platform compatibility.
- Do not run destructive commands or rewrite history unless explicitly requested.

## Final response

- Summarize what changed and why.
- List checks run and their results.
- Mention remaining risks, skipped checks, or follow-up work.
