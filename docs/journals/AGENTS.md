# Development Journal Writing Standards

After completing each coding task, you MUST create a separate Markdown journal file documenting the completed work.

Each journal represents exactly one task. Never combine multiple unrelated tasks into a single journal file.

The purpose is to maintain a clean, searchable, and reliable engineering history that allows developers and AI coding agents to quickly understand past implementations, technical decisions, and remaining work.

## 1. File Organization

Store all journal files under:

`docs/journals/`

Use the following filename convention:

`YYYY-MM-DD-HHMM-short-task-description.md`

Examples:
- `2026-11-06-0930-implement-jwt-authentication.md`
- `2026-11-06-1045-fix-user-login-validation.md`
- `2026-11-06-1430-refactor-database-queries.md`

Rules:
- Create exactly one new journal file per task.
- Use the actual task completion date and local time.
- Use lowercase kebab-case for the task description.
- Keep filenames short, descriptive, and meaningful.
- Ensure filenames are unique. If a collision occurs, add a numeric suffix.
- Never append new tasks to existing journal files.
- Never overwrite or modify historical journals unless explicitly requested.
- Create the journal directory if it does not exist.

## 2. Writing Principles

Every journal MUST be:

- **Clear:** Use simple, professional Vietnamese.
- **Concise:** Avoid unnecessary details and repetition.
- **Specific:** Describe actual changes, not vague activities.
- **Accurate:** Never invent implementations or verification results.
- **Scannable:** Use consistent Markdown headings and bullet points.
- **Self-contained:** Readers should understand the task without the original conversation.
- **Actionable:** Clearly identify limitations and follow-up work.

Write about engineering outcomes, not the step-by-step coding process.

## 3. Required Journal Structure

Use this template for every journal:

# [Short Task Title]

**Date:** YYYY-MM-DD HH:MM  
**Status:** Completed | Partially Completed | Blocked

## Summary

Describe the outcome in 1–3 sentences.

Explain what was accomplished and why it matters.

## Changes Made

- Describe the key implementation changes.
- Highlight important changes in behavior, logic, architecture, APIs, database, or configuration.
- Group related changes logically.
- Avoid describing trivial edits.

## Files Affected

- `path/to/file.ts` — Explain its role in the implementation.
- `path/to/another-file.ts` — Explain the relevant change.

Only list files that are important for understanding the task.

## Technical Decisions

- Explain significant implementation decisions.
- Describe why a particular approach was chosen.
- Mention relevant architectural trade-offs when applicable.

If there were no significant decisions, write "None."

## Verification

- **Tests:** Tests executed and their actual results.
- **Build/Lint/Typecheck:** Checks performed and outcomes.
- **Manual Verification:** Behaviors manually verified.

Clearly distinguish passed, failed, and unexecuted checks.

Never claim verification was successful unless it was actually performed.

## Known Issues / Limitations

- Document unresolved bugs, limitations, or technical debt.
- Write "None known" if there are no known issues.

## Next Steps

- List specific follow-up actions, if needed.
- Write "None" if no follow-up is necessary.

## 4. Length Guidelines

Adjust the journal length according to task complexity:

- **Small task:** 100–150 words.
- **Medium task:** 150–250 words.
- **Complex task:** 250–400 words.

These are guidelines, not strict requirements.

Avoid padding entries just to reach a target length.

Prefer short paragraphs and meaningful bullet points.

## 5. Content Quality Rules

1. Explain WHAT changed, WHY it changed, and HOW it was verified.
2. Use precise technical terminology.
3. Avoid generic statements such as "Fixed bugs" or "Updated code."
4. Never paste full source files, large diffs, or raw terminal logs.
5. Never include secrets, credentials, tokens, or sensitive information.
6. Do not repeat the original task instructions.
7. Avoid unnecessary implementation details that are obvious from the code.
8. Include exact file paths, functions, or endpoints when they provide useful context.
9. Record only confirmed facts.
10. Keep the journal readable in under two minutes.

## 6. Journal Creation Workflow

After completing the implementation:

1. Review the final code changes.
2. Identify the actual task outcome.
3. Collect verification results.
4. Identify important technical decisions and remaining limitations.
5. Generate a descriptive, unique journal filename.
6. Create a new Markdown file under `docs/journals/`.
7. Write the journal using the required structure.
8. Check the journal for accuracy, clarity, and formatting.
9. Include the journal file path in the final task response.

## 7. Important Restrictions

- NEVER use a single shared journal file for multiple tasks.
- NEVER append unrelated work to an existing journal.
- NEVER create multiple journal files for one task.
- NEVER invent verification results.
- NEVER document intended changes as completed changes.
- NEVER modify old journals without explicit authorization.
- NEVER create a journal for a task that involved no actual repository changes unless explicitly requested.
- Do not create a new journal solely for the act of writing or updating journal files.

## 8. Final Response Requirement

After completing a task, include:

- A concise summary of the implementation.
- Verification results.
- Remaining issues, if any.
- The path to the newly created journal file.

The journal must be written before the task is considered finished.

**Golden Rule:** One task = one journal file. Every journal should be concise, accurate, independently understandable, and useful for future engineering work.