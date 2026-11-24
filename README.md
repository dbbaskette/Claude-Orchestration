# Claude Orchestration

Orchestrator mode for Claude Code. A top-tier planner plans and verifies, and cheaper tiers do the hands-on work.

| Tier | Default | Does | Runs as |
|---|---|---|---|
| Planner | `fable`, high | Plans, routes, verifies, re-plans | Main thread |
| Executor | `opus`, high | All real coding | `orch-executor` |
| Reviewer | `opus`, medium | Independent read-only review of risky changes | `orch-reviewer` |
| Worker | `sonnet`, medium | Searches, test runs, mechanical edits. Never real coding | `orch-worker` |

## Use

Per task, from any session (the planner model applies for that turn):

```
/orchestrate add rate limiting to the public API and cover it with tests
```

For long jobs, run the whole session as the planner, so later turns stay on the planner model:

```bash
claude --agent orchestrator
```

On a first run, check `/tasks` to confirm each subagent ran on the model you expect.

## Configure

Edit [.claude/orchestration.json](.claude/orchestration.json), then push it into the skill and agent files:

```bash
python3 .claude/skills/orchestrate/scripts/sync_models.py
```

Add `--check` to report drift without writing; `/orchestrate` runs that check itself. A model is an alias (`fable`, `opus`, `sonnet`, `haiku`, always the latest of that family) or a full ID such as `claude-opus-5-5` to pin a version.

| `routing` setting | Default | Meaning |
|---|---|---|
| `max_parallel_readers` | 4 | Read-only agents sent in one wave |
| `dispatch_budget` | 12 | Dispatches per task. The planner estimates the run up front and asks before starting if it won't fit |
| `review_file_threshold` | 20 | Changes touching more files than this always get reviewed |
| `verification_failures_before_replan` | 2 | Failed checks on one step before re-planning |
| `worker_retry_effort`, `executor_retry_effort` | high, xhigh | Effort for a retried step |

## Stats

With `"stats": { "enabled": true }` in the config (the default), the planner ends each planned run by writing `stats.json` into the run folder: every dispatch with its tier, model, status, tokens and time, the estimate against the budget, review defects, re-plans, and a `strained` list of where the protocol got in the way or a rule was bent. Small jobs that skip planning aren't recorded. The file stays on your machine.

Summarize the runs of one or more projects (default: the current one):

```bash
python3 .claude/skills/orchestrate/scripts/stats.py ~/Projects/app-one ~/Projects/app-two
```

Or type `/orchestrate stats` in a project. The numbers are the planner's own record of each run, so treat them as a guide and not as billing data.

## Install globally

The files work as-is in this project. To use them everywhere, symlink them into `~/.claude` (re-run after adding an `orch*.md` agent file):

```bash
./install.sh
```

## How it works

The full protocol is [SKILL.md](.claude/skills/orchestrate/SKILL.md). In short:

1. **Triage.** Questions are answered directly, and small jobs get one brief. Only larger work is planned, under a dispatch budget.
2. **Plan, read-only.** Workers do the reading. Each step gets a tier, a file scope, a check, and conditions that trigger re-planning. Choices that change existing behavior go to you, not into the plan.
3. **Dispatch.** The model is pinned on every call. Briefs give paths, interfaces, decisions and non-goals, not pasted files. Reads run in parallel and code changes one at a time. Code changes run in parallel only in separate worktrees, on disjoint files, when the task already calls for commits or PRs.
4. **Verify.** The planner reads the real diff from a recorded starting commit. Risky or large changes go to the reviewer, which never sees the executor's report. Failures are fixed by cause: more context, a stronger tier, a smaller step, or a new plan.
5. **Wrap up.** Full test run, whole-diff review, the run's stats, and a report of what each tier did.

Each planned run keeps a ledger, the subagents' full reports and its stats in `.claude/orchestrate/<date>-<task>/` in the project it runs in. In a git repo the planner hides that folder from `git status` by adding it to `.git/info/exclude`, which is local and never committed. The folder is safe to delete.

Without git history there is no diff to check, so the planner verifies by reading the changed files instead.

## Caveats

- On short jobs this usually costs more in total than one strong model. What it saves is planner (Fable) usage. Compare real tasks with `/usage`.
- Every dispatch has a fixed cost. In a test run, each subagent used 65–70k tokens even for a one-command task, which is why small jobs aren't orchestrated.
- The rules are instructions, not hard limits. Nothing technically stops the planner from exceeding the budget or a worker from writing code.
- A skill's `model` is ignored if the session's allowed models exclude it.

## Sources

[Antigravity Orchestrator](https://antigravity.google/docs/models#orchestrator) · [Which Claude model should you build with](https://claude.dev/blog/which-claude-model-should-you-build-with/) · [superpowers subagent-driven-development](https://github.com/obra/superpowers/tree/main/skills/subagent-driven-development) · [Quesma multi-model benchmark](https://quesma.com/blog/multi-model-claude-code-refusal-terminal-bench/) · [Fable orchestrator, Opus executor](https://flaviocopes.com/fable-orchestrator/) · [The Orchestrator's Tax](https://martinfowler.com/articles/orchestrator-tax.html)

## License

[MIT](LICENSE)
