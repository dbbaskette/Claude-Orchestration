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
RETURNED = ("DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED", "NO_DEFECTS", "DEFECTS")
STATUSES = RETURNED + ("FAILED", "INTERRUPTED")
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
    "reviews_skipped": 0,
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
  estimate    your plan-time estimate of dispatches; null if you made none
  used        the ledger's DISPATCHES count
  user_asks   questions you put to the user during the run; null if not recorded
  reviews_skipped   steps that met a Step 4 review condition and got no review;
              null if not recorded
  dispatches  one entry per Agent call or SendMessage continuation, in order.
              Parallel readers get an entry each, though they count once in used
    kind      {' | '.join(KINDS)}
    tier      {' | '.join(TIERS)}
    status    as returned ({', '.join(RETURNED)}),
              FAILED when your own verification rejected the result, or
              INTERRUPTED when it was stopped before it reported
    tokens, seconds   from the Agent result's usage; null if not shown. Never estimate.
              A SendMessage continuation's tokens are unreliable: record null
    defects   review entries only: the count at each severity (low includes
              the reviewer's LOW NOT LISTED)
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

    def count(obj, key, where="", optional=False):
        if optional and obj.get(key) is None:
            return
        if type(obj.get(key)) is not int or obj[key] < 0:
            out.append(f"{where}{key} must be a whole number of 0 or more" + (" or null" if optional else ""))

    def one_of(obj, key, allowed, where=""):
        if obj.get(key) not in allowed:
            out.append(f"{where}{key} must be one of: {', '.join(allowed)}")

    text(d, "run")
    text(d, "task")
    one_of(d, "outcome", OUTCOMES)
    for key in ("budget", "used", "replans"):
        count(d, key)
    for key in ("estimate", "user_asks", "reviews_skipped"):
        count(d, key, optional=True)

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
        used = sum(d["used"] for _, d in runs)
        est = [d for _, d in runs if d.get("estimate") is not None]
        asks = [d["user_asks"] for _, d in runs if d.get("user_asks") is not None]
        at_limit = sum(d["used"] >= d["budget"] for _, d in runs)
        print(f"Dispatches: {used} used, {used / n:.1f} per run; runs that reached the budget: {at_limit}")
        if est:
            over = sum(d["used"] > d["estimate"] for d in est)
            print(f"Estimates ({len(est)} of {n} runs): {avg(d['estimate'] for d in est):.1f} estimated against "
                  f"{avg(d['used'] for d in est):.1f} used; over their estimate: {over}")
        print(f"Re-plans: {sum(d['replans'] for _, d in runs)}; questions to the user: "
              f"{sum(asks) if asks else '-'} ({len(asks)} of {n} runs recorded)")

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
        rework = kinds["fix"] + kinds["retry"] + kinds["review"]
        print(f"Reviews, fixes and retries: {rework} of {len(calls)} calls ({rework / len(calls):.0%})")
        first = Counter(x["status"] for x in calls if x["kind"] == "step")
        if first:
            print(f"First attempts at a step: {sum(first.values())} "
                  f"({', '.join(f'{s} {first[s]}' for s in STATUSES if first[s])})")
        reviews = [x for x in calls if x["kind"] == "review" and "defects" in x]
        if reviews:
            sev = {s: sum(x["defects"][s] for x in reviews) for s in SEVERITIES}
            total = sum(sev.values())
            print(f"Reviews: {len(reviews)}; defects {', '.join(f'{s} {sev[s]}' for s in SEVERITIES)} "
                  f"({total / len(reviews):.1f} per review)")
        skipped_reviews = [d["reviews_skipped"] for _, d in runs if d.get("reviews_skipped") is not None]
        if skipped_reviews:
            print(f"Required reviews skipped: {sum(skipped_reviews)} ({len(skipped_reviews)} of {n} runs recorded)")

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
