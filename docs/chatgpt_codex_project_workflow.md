# ChatGPT Project <-> Codex Workflow

Date: July 18, 2026

## Purpose

Use ChatGPT Projects for long-lived planning context and Codex for local repository execution.

This workflow is designed to move context back and forth reliably even if product surfaces change.

## Current product boundary

As of July 18, 2026:
- ChatGPT Projects are shared workspaces for chats, files, and project instructions.
- Codex works in the ChatGPT desktop app on local folders, repositories, terminals, and developer tools.
- There is not a repo-native automatic sync layer that guarantees your live local workspace state appears inside a ChatGPT Project by itself.
- The safe model is artifact-based handoff: keep the important state in repo docs, then use those docs in ChatGPT Projects and Codex threads.

## Source of truth split

Use this split consistently:

- Repo docs:
  - architecture
  - plans
  - verification criteria
  - achievement notes
  - next prompt seeds
- ChatGPT Project:
  - planning discussions
  - prompt refinement
  - roadmap thinking
  - product or UX exploration
  - draft task briefs for the next Codex run
- Codex:
  - code changes
  - tests
  - Docker
  - migrations
  - debugging
  - implementation verification

## Required handoff artifacts

Before leaving a completed phase or feature, keep these current:

- `README.md`
- `verification.md`
- `docs/phase_1a_achievement.md` or the current phase equivalent
- this workflow doc when the process changes

Minimum content for each achievement note:
- what now works
- how it was verified
- known gaps
- startup command
- recommended next prompt seed

## Recommended back-and-forth loop

### 1. Before implementation in Codex

Start in ChatGPT Project and prepare:
- the goal
- constraints
- acceptance criteria
- out-of-scope items
- requested deliverable

Then save the result into repo docs if it becomes authoritative:
- `planning.md`
- `designing.md`
- `docs/plans/...`

### 2. Execute in Codex

In Codex:
- implement
- test
- verify manually
- update docs
- create or refresh the achievement note

### 3. Send results back to ChatGPT Project

After Codex finishes, send back:
- the achievement note
- relevant screenshots
- exact verification output
- open issues or gaps

Best artifact to paste first:
- `docs/phase_1a_achievement.md`

### 4. Use ChatGPT Project to prepare the next prompt

Ask ChatGPT Project to:
- summarize the current state
- identify remaining Phase N gaps
- draft the next phase prompt using the achievement note plus current docs

Then bring that prompt back into Codex for execution.

## Standard prompt package for ChatGPT Project

When preparing the next prompt, include:

1. Current achievement note
2. Current `planning.md`
3. Current `designing.md`
4. Current `verification.md`
5. Any screenshots or API output that prove the current state

## Standard prompt package for Codex

When starting the next Codex task, include:

1. the phase objective
2. the authoritative docs to read
3. the exact working baseline
4. the startup command
5. the acceptance criteria
6. the constraints and non-goals

## Practical workflow for CineSense

### After each successful implementation

1. Run:

```sh
./scripts/start-phase-1a.sh
```

2. Verify the core API/UI path.

3. Update:
- `README.md`
- `verification.md`
- `docs/phase_1a_achievement.md`

4. In ChatGPT Project, paste:
- the latest achievement note
- any screenshots
- any API response proving success

5. Ask ChatGPT Project:

```text
Using the attached achievement note and current phase docs, draft the next implementation prompt for Codex. Keep scope tight, preserve current constraints, and list explicit acceptance criteria and non-goals.
```

6. Bring that refined prompt back into Codex.

## What is possible vs not

Possible:
- use the same overall project in ChatGPT and Codex
- keep shared understanding through project instructions and repo docs
- move context reliably by pasting or attaching repo-backed artifacts

Not guaranteed:
- automatic live sync of local repo state into a ChatGPT Project
- automatic conversation continuity between every ChatGPT surface and every Codex local execution context
- assuming a ChatGPT Project can inspect your local filesystem unless you explicitly provide the files or use a supported connected workflow

## Recommended operating rule

Do not rely on memory alone across surfaces.

Always move state through repo artifacts:
- docs
- achievement notes
- screenshots
- exact command output when needed

That keeps the workflow stable even when tools or product surfaces change.

