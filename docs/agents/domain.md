# Domain Docs

## Layout and reading rules

This repository uses a single-context layout:

- `GLOSSARY.md` at the repository root defines agreed domain vocabulary.
- `docs/adr/NNNN-short-title.md` records architectural decisions.

Before domain exploration, read the glossary and ADRs relevant to the work. If these files or directories are absent, proceed silently. Create them lazily through `/domain-modeling` when terminology or decisions are actually resolved.

## Vocabulary

Use glossary terms in issue titles, specifications, code, and tests. When a necessary concept is missing, determine whether an existing term fits; capture a real vocabulary gap during domain modeling.

## Decision conflicts

Explicitly identify any proposal that conflicts with an ADR, name the ADR, and explain why reopening the decision is justified. Resolve the conflict before treating the new proposal as an accepted decision.
