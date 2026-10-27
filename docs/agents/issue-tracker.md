# Issue tracker: GitHub

Issues and specs live in GitHub Issues for `fxbillu/Magic-wechat-group-daily-skills`. Use the `gh` CLI and the explicit repository argument when operating outside this checkout.

## Conventions

- Create: `gh issue create --repo fxbillu/Magic-wechat-group-daily-skills --title "..." --body-file /path/to/issue.md`.
- Read: `gh issue view <number> --json number,title,body,labels,comments`.
- List: `gh issue list --state open --json number,title,labels`; add label filters as needed.
- Comment: `gh issue comment <number> --body-file /path/to/comment.md`.
- Apply or remove labels: `gh issue edit <number> --add-label "..."` or `--remove-label "..."`.
- Close: `gh issue close <number> --comment "..."`.

Use real multiline body files. Read `docs/agents/triage-labels.md` before assigning a triage role. Infer the repository from `origin` when running inside this checkout.

When a skill says "publish to the issue tracker," create a GitHub issue within the user's authorized scope. When it says "fetch the relevant ticket," read the GitHub issue and its comments.

## Parent and child issues

Use supported native sub-issue operations when available. Otherwise, put `Part of #<parent>` at the top of each child issue and add a task-list link in the parent. Record unavailable native dependencies as `Blocked by: #<number>` and check blocker states before claiming work.

## Pull requests as a triage surface

**PRs as a request surface: no.**

## Wayfinding operations

For `/wayfinder`, use one map issue labelled `wayfinder:map`, with child tickets labelled `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, or `wayfinder:task`. Create missing wayfinding labels when that workflow is invoked. Claim an unassigned, unblocked ticket with `gh issue edit <number> --add-assignee @me`; comment with findings, close the ticket, and update the map's decisions with a link.
