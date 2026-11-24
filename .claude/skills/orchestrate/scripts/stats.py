#!/usr/bin/env python3
"""Per-run stats for /orchestrate, kept so the protocol can be tuned from real use.

  stats.py --template      print a blank stats.json and what each field means
  stats.py --check FILE    validate one stats.json (exit 1 if invalid)
  stats.py [PATH ...]      summarize runs. PATH is a project, a run folder or a
                           stats.json; default is the current project

A run's file is <project>/.claude/orchestrate/<run>/stats.json. Nothing leaves the machine.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

OUTCOMES = ("done", "partial", "stopped")
KINDS = ("read", "step", "fix", "retry", "review", "verify")
TIERS = ("executor", "reviewer", "worker")
STATUSES = ("DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED", "NO_DEFECTS", "DEFECTS", "FAILED")
SEVERITIES = ("high", "medium", "low")

TEMPLATE = {
    "run": "<run folder name>",
    "task": "<one line>",
    "outcome": "done",
    "budget": 12,
    "estimate": 0,
    "used": 0,
    "replans": 0,
    "user_asks": 0,
    "dispatches": [
        {"step": "1", "kind": "step", "tier": "executor", "model": "opus", "effort": "high",
         "status": "DONE", "tokens": None, "seconds": None},
        {"step": "1", "kind": "review", "tier": "reviewer", "model": "opus", "effort": "medium",
         "status": "DEFECTS", "tokens": None, "seconds": None,
         "defects": {"high": 0, "medium": 0, "low": 0}},
    ],
    "strained": ["<one line each>"],
}

GUIDE = f"""
Fields:
  outcome     {' | '.join(OUTCOMES)} (stopped = ended before the work was finished)
  budget      routing.dispatch_budget, or the raised limit the user agreed to
  estimate    your plan-time estimate of dispatches
  used        the ledger's DISPATCHES count
  user_asks   questions you put to the user during the run
  dispatches  one entry per Agent call or SendMessage continuation, in order
    kind      {' | '.join(KINDS)}
    tier      {' | '.join(TIERS)}
    status    as returned ({', '.join(STATUSES[:-1])}),
              or FAILED when your own verification rejected the result
    tokens, seconds   from the Agent result's usage; null if not shown. Never estimate.
    defects   review entries only: the count at each severity
  strained    where the protocol got in the way, cost more than it should have, or
              you bent a rule, and why. [] if nothing did.
Record what happened, not what should have.
"""


def problems(d):
    """List of schema problems in one stats object."""
    if not isinstance(d, dict):
        return ["top level must be an object"]
    out = []

    def text(obj, key, where=""):
        v = obj.get(key)
        if not isinstance(v, str) or not v.strip() or v.startswith("<"):
            out.append(f"{where}{key} must be filled-in text")

    def count(obj, key, where=""):
        if type(obj.get(key)) is not int or obj[key] < 0:
            out.append(f"{where}{key} must be a whole number of 0 or more")

    def one_of(obj, key, allowed, where=""):
        if obj.get(key) not in allowed:
            out.append(f"{where}{key} must be one of: {', '.join(allowed)}")

    text(d, "run")
    text(d, "task")
    one_of(d, "outcome", OUTCOMES)
    for key in ("budget", "estimate", "used", "replans", "user_asks"):
        count(d, key)

    dispatches = d.get("dispatches")
    if not isinstance(dispatches, list):
        out.append("dispatches must be a list")
        dispatches = []
    for i, x in enumerate(dispatches, 1):
        where = f"dispatches[{i}]."
        if not isinstance(x, dict):
            out.append(f"dispatches[{i}] must be an object")
            continue
        for key in ("step", "model", "effort"):
            text(x, key, where)
        one_of(x, "kind", KINDS, where)
        one_of(x, "tier", TIERS, where)
        one_of(x, "status", STATUSES, where)
        for key in ("tokens", "seconds"):
            v = x.get(key)
            if v is not None and (type(v) not in (int, float) or v < 0):
                out.append(f"{where}{key} must be a number or null")
        if "defects" in x:
            if not isinstance(x["defects"], dict):
                out.append(f"{where}defects must be an object")
            else:
                for sev in SEVERITIES:
                    count(x["defects"], sev, where + "defects.")

    strained = d.get("strained")
    if not isinstance(strained, list) or any(not isinstance(s, str) or s.startswith("<") for s in strained):
        out.append("strained must be a list of filled-in lines ([] if none)")
    return out


def find(paths):
    """stats.json files under the given projects, run folders or files."""
    files = []
    for p in map(Path, paths or ["."]):
        if p.is_file():
            files.append(p)
        elif (p / "stats.json").is_file():
            files.append(p / "stats.json")
        else:
            files += sorted((p / ".claude" / "orchestrate").glob("*/stats.json"))
    return files


def load(path):
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return None, [str(e)]
    return d, problems(d)


def avg(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def fmt(n, digits=0):
    return "-" if n is None else f"{n:,.{digits}f}"


def report(files):
    runs, skipped = [], []
    for f in files:
        d, errs = load(f)
        if errs:
            skipped.append(f"{f}: {errs[0]}")
        else:
            runs.append((f, d))
    if not runs:
        print("No valid stats.json found.")
    else:
        n = len(runs)
        projects = {f.resolve().parents[3] for f, _ in runs if len(f.resolve().parents) > 3}
        outcomes = Counter(d["outcome"] for _, d in runs)
        calls = [x for _, d in runs for x in d["dispatches"]]
        print(f"Runs: {n} ({', '.join(f'{o} {outcomes[o]}' for o in OUTCOMES)}) in {len(projects) or 1} project(s)")
        used, est = sum(d["used"] for _, d in runs), sum(d["estimate"] for _, d in runs)
        at_limit = sum(d["used"] >= d["budget"] for _, d in runs)
        over_est = sum(d["used"] > d["estimate"] for _, d in runs)
        print(f"Dispatches: {used} used, {used / n:.1f} per run; estimated {est / n:.1f} per run")
        print(f"  runs over their estimate: {over_est}; runs that reached the budget: {at_limit}")
        print(f"Re-plans: {sum(d['replans'] for _, d in runs)}; questions to the user: {sum(d['user_asks'] for _, d in runs)}")

        by_tier = defaultdict(list)
        for x in calls:
            by_tier[x["tier"]].append(x)
        print(f"\n{'tier':9} {'calls':>5} {'tokens/call':>12} {'sec/call':>9}  statuses")
        for tier in TIERS:
            xs = by_tier.get(tier, [])
            if not xs:
                continue
            statuses = Counter(x["status"] for x in xs)
            shown = ", ".join(f"{s} {statuses[s]}" for s in STATUSES if statuses[s])
            print(f"{tier:9} {len(xs):5} {fmt(avg(x['tokens'] for x in xs)):>12} "
                  f"{fmt(avg(x['seconds'] for x in xs)):>9}  {shown}")
        tokens = [x["tokens"] for x in calls if x["tokens"] is not None]
        print(f"Subagent tokens recorded: {fmt(sum(tokens))} over {len(tokens)} of {len(calls)} calls")

        kinds = Counter(x["kind"] for x in calls)
        print("\nBy kind: " + ", ".join(f"{k} {kinds[k]}" for k in KINDS if kinds[k]))
        reviews = [x for x in calls if x["kind"] == "review" and "defects" in x]
        if reviews:
            sev = {s: sum(x["defects"][s] for x in reviews) for s in SEVERITIES}
            total = sum(sev.values())
            print(f"Reviews: {len(reviews)}; defects {', '.join(f'{s} {sev[s]}' for s in SEVERITIES)} "
                  f"({total / len(reviews):.1f} per review)")

        notes = [(d["run"], s) for _, d in sorted(runs, key=lambda r: r[1]["run"], reverse=True)
                 for s in d["strained"]]
        if notes:
            print("\nStrained (newest first):")
            for run, s in notes:
                print(f"  - [{run}] {s}")
    if skipped:
        print("\nSkipped (invalid):", *skipped, sep="\n  - ")
    return 0


def main():
    args = sys.argv[1:]
    if "--template" in args:
        print(json.dumps(TEMPLATE, indent=2))
        print(GUIDE)
        return 0
    if "--check" in args:
        rest = [a for a in args if a != "--check"]
        if len(rest) != 1:
            print("usage: stats.py --check FILE")
            return 1
        _, errs = load(Path(rest[0]))
        if errs:
            print(f"STATS ERROR in {rest[0]}:", *errs, sep="\n  - ")
            return 1
        print("Stats OK.")
        return 0
    if any(a.startswith("-") for a in args):
        print(__doc__)
        return 0 if args[0] in ("-h", "--help") else 1
    return report(find(args))


if __name__ == "__main__":
    sys.exit(main())
