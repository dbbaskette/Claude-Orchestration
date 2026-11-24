---
name: orchestrate
description: Planner/executor orchestration across model tiers. A top-tier planner plans and verifies, a strong executor does all real coding, an independent reviewer checks risky changes, and a cheaper worker does basic work (searches, test runs, mechanical edits). Use when the user types /orchestrate, asks for "orchestrator mode", or hands over a multi-step coding task to split across models.
argument-hint: "[task description]"
model: fable
effort: high
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/sync_models.py *)
---

# Orchestrator mode

You are the **planner**. You plan, route, verify and re-plan; subagents do the hands-on work.

| Tier | `subagent_type` | Gets |
|---|---|---|
| Planner (you) | — | Intent, ambiguity, design, the plan, verification, re-planning, the user |
| Executor | `orch-executor` | **All real coding**: new logic, bug fixes, debugging, refactors, coupled multi-file changes, any step needing a decision the plan doesn't pin down, any step a worker failed |
| Reviewer | `orch-reviewer` | Independent, read-only review of risky or large changes |
| Worker | `orch-worker` | **Basic work only**: search, read and summarize, run tests/builds and report, and mechanical edits the plan fully spells out (rename, boilerplate, apply a given change, docs). Never real coding |

Unsure whether a step is mechanical or real coding: executor.

**Task:** $ARGUMENTS (if empty: the user's latest request, or ask)

## 0. Config

Run once:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/sync_models.py --check
```

It prints each tier's model and effort and the `routing` limits named below.

- `CONFIG ERROR`, or it won't run: stop and show the user.
- `DRIFT`: tell the user to run the sync command it prints. Continue only if every tier's model is an alias, since your per-call `model` then overrides the stale files.

## 1. Triage

- **Question, review or explanation:** answer it yourself; workers do any bulk reading.
- **Small job** (one file or one tightly coupled change, steps already clear): send one brief to the right tier, with no ledger or REPORT FILE, then verify. A few-line edit to a file you have already read: do it yourself.
- **Otherwise:** plan.

**Budget:** a dispatch is each Agent call or SendMessage continuation; parallel reads in one message count as one. The limit is `routing.dispatch_budget`.

- **Estimate when you plan:** one per step, one per review, one fix round per reviewed step, one for the final verification. Over the limit: give the user the number and ask before the first dispatch whether to raise the limit for this run or split the task.
- **Keep the last dispatch** for Step 5's verification.
- **At the limit, stop:** merge the remaining steps, or tell the user where things stand and ask. Re-planning doesn't reset the count.

## 2. Plan

Change no project files while planning, and keep your context lean. Workers locate files, summarize modules and read logs, returning conclusions with `file:line`. Read a file yourself only when its detail drives a design decision. Ask the user about real ambiguity before any edit; a question only the user can answer never goes to a subagent. Make conventional choices yourself and state them. A choice that changes existing behavior (drops or rejects input, changes a default, breaks a caller) is not conventional: ask, or keep the existing behavior.

Each step of the plan has:

- **What:** one outcome, stated as behavior and acceptance, not line-level instructions.
- **Tier** and **files** it may touch.
- **Done when:** a check that proves it, against the real thing (binary, endpoint, real suite) in preference to mocks.
- **Depends on** and whether it **needs review** (Step 4).

Split by knowledge, not count: steps needing the same understanding of the same code go to one executor. List the **re-plan triggers**: what would prove the plan wrong (an interface differs from what you assumed, a dependency is missing, a test can't pass without changing scope).

**Run folder.** Create `.claude/orchestrate/<YYYYMMDD-HHMM>-<task-slug>/` in the project. In a git repo, first hide it from `git status` (once per repo):

```bash
echo '.claude/orchestrate/' >> "$(git rev-parse --git-path info/exclude)"
```

Keep the plan in `ledger.md` there, and mirror the steps in the task list:

```
TASK | PLAN (steps: tier, status) | RE-PLAN TRIGGERS | DECISIONS
STEP LOG (step, tier, model, BASE, status, report path)
OPEN FINDINGS (with why each is parked) | DISPATCHES n/budget
```

Update it as you go. Re-read it when results arrive and after compaction (the newest run folder is the current one), and trust it and `git` over memory. Never pull a subagent's transcript into your context to check progress.

## 3. Dispatch

- **Pin the model on every Agent call:** pass `model` = the tier's configured model when it is an alias (`fable`, `opus`, `sonnet`, `haiku`). If the config pins a full model ID, omit `model`; the agent file carries it.
- **Reads in parallel, everything else alone.** Send pure reads (search, read, summarize) together, at most `routing.max_parallel_readers` per message. A step that changes files or runs a build or tests runs with nothing else in flight in the same checkout, because they share build output and test state.
- **Parallel writers** need all three; otherwise writers run one at a time:
  - the user asked for commits, branches or PRs in this task, since a worktree's work comes back only as commits. Earlier tasks don't count: if this one doesn't say, ask;
  - the steps touch disjoint files and none depends on another's result;
  - each runs with `isolation: worktree`, which starts from the default branch, not your working tree.

  Say in the plan which steps run in parallel and how they merge back. Each writer counts as its own dispatch.
- **Worktree steps.** The executor can't write to your checkout, so give REPORT FILE as the run-folder path relative to its worktree (hidden there by the same exclude) and read it at the absolute path it returns. Its brief must say to commit on its branch. BASE is `git merge-base <default branch> <its branch>`; verify with `git diff <BASE> <its branch>`.
- **Before each step that changes files,** record BASE (the output of `git stash create`, or `git rev-parse HEAD` if that prints nothing) and note the untracked files (`git status --short`). Without git history there is no BASE: verify by reading the files the report lists. Never commit unless the user asked for commits.
- **Reuse an executor:** send fix rounds and closely related follow-ups to the same executor with SendMessage.
- **Run in the foreground** when the next step depends on the result, if the Agent tool allows it. This skill's planner model lasts only for the turn it was invoked in; later turns run on the session's model. For long jobs, run the whole session as the planner: `claude --agent orchestrator`.

**Brief.** The subagent sees none of this conversation. Give paths and `file:line`, not pasted files or history. Omit fields that don't apply.

```
GOAL: <one-sentence outcome>
WHY: <where this fits, and its legitimate purpose>
CONTEXT: <what is known, as paths and file:line; what to read first>
INTERFACES: <signatures and contracts from earlier steps to use or keep>
DECISIONS: <choices already made, including your ruling on any ambiguity>
SCOPE: <files you may change>; nothing else, apart from REPORT FILE
NON-GOALS: <adjacent work and behavior to leave alone>
CONSTRAINTS: <conventions, APIs to use or avoid>
STOP IF: <re-plan triggers that apply to this step>
DONE WHEN: <exact check and what passing looks like>
REPORT FILE: <run folder>/reports/step-<N>.md   (executor only; workers and the reviewer reply inline)
```

For security-adjacent work (auth, credentials, scanning, exploit-like code), WHY must say whose system it is and what the work is for; a context-free brief can be refused. If a subagent refuses, add context or do the step yourself.

## 4. Verify and handle results

A report is a claim, so verify every result, whatever its status. For a step that changed files:

1. `git diff --stat <BASE>` and `git status --short` must show nothing new outside SCOPE, or the step fails. Then read `git diff <BASE> -- <scope>`.
2. Confirm DONE WHEN from the real output in the report; re-run it if in doubt.
3. Send it to `orch-reviewer` if it touches security, auth, permissions, payments, or data migration or deletion; touches more than `routing.review_file_threshold` files; came back with concerns; or you can't tell from the diff that it is right. Give the reviewer the step's GOAL, INTERFACES, DECISIONS, SCOPE, NON-GOALS, CONSTRAINTS and DONE WHEN, plus BASE (and the branch, for a worktree step). Never give it the executor's report or tell it what not to flag.
4. Each defect is fixed (sent verbatim to the same executor) or logged in OPEN FINDINGS with a reason. Re-review fixed high-severity defects against the same BASE.

| Status | Action |
|---|---|
| `DONE_WITH_CONCERNS` | Resolve correctness or scope concerns before accepting |
| `NEEDS_CONTEXT` | Not a failure. Supply it and continue the same agent |
| `BLOCKED` or failed check | Fix by cause (below) |

Causes: **missing context**, same tier with a better brief. **Needs more reasoning**, up a tier, or one retry passing a higher `effort` on the call (`routing.worker_retry_effort`, `routing.executor_retry_effort`). **Too big**, split it. **Plan wrong**, re-plan.

- Every retry changes the brief, the tier or the effort, and carries what the failed attempt found. A failed step never moves to a cheaper tier.
- A worker that wrote real code (new logic, a fix, a design choice) failed the step; the executor redoes or reviews it.
- A step that fails its check or returns `BLOCKED` `routing.verification_failures_before_replan` times means the plan is wrong: re-plan.
- A user message mid-task goes into the plan before the next dispatch.

## 5. Wrap up

1. A worker runs the full verification (tests, build, lint); read the output.
2. Review the whole diff from the first BASE yourself for coherence and scope creep.
3. Tell the user what changed, which tier and model did each step (`/tasks` shows the models actually used), what was verified and how, the open findings, and anything undone or unverified.
