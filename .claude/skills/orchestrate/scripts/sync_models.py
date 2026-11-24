#!/usr/bin/env python3
"""Sync model/effort from .claude/orchestration.json into skill and agent frontmatter.

  sync_models.py            rewrite frontmatter to match the config
  sync_models.py --check    print the config and report drift (always exits 0)

The .claude root comes from this script's real path, so it works the same
in-project or symlinked into ~/.claude.
"""
import json
import re
import sys
from pathlib import Path

ALIASES = {"fable", "opus", "sonnet", "haiku"}
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
ROUTING_COUNTS = ("max_parallel_readers", "dispatch_budget", "review_file_threshold",
                  "verification_failures_before_replan")
ROUTING_EFFORTS = ("worker_retry_effort", "executor_retry_effort")
AGENT_TIERS = ("executor", "reviewer", "worker")  # one subagent file each
TIERS = ("planner",) + AGENT_TIERS

ROOT = Path(__file__).resolve().parents[3]  # the .claude directory
CONFIG = ROOT / "orchestration.json"
FRONTMATTER = re.compile(r"\A---\n(.*?\n)---\n", re.S)


def validate(cfg):
    errors = []
    for tier in TIERS:
        t = cfg.get(tier)
        if not isinstance(t, dict):
            errors.append(f"missing '{tier}' section")
            continue
        model, effort = str(t.get("model", "")), str(t.get("effort", ""))
        if model not in ALIASES and not re.fullmatch(r"\S*claude-\S+", model):
            errors.append(f"{tier}.model '{model}' must be one of {sorted(ALIASES)} or a full claude-* model ID")
        if effort not in EFFORTS:
            errors.append(f"{tier}.effort '{effort}' must be one of {sorted(EFFORTS)}")
        if tier in AGENT_TIERS and not re.fullmatch(r"[A-Za-z0-9_-]+", str(t.get("agent", ""))):
            errors.append(f"{tier}.agent must be an agent file name (letters, digits, - and _)")
    routing = cfg.get("routing") if isinstance(cfg.get("routing"), dict) else {}
    for key in ROUTING_COUNTS:
        if type(routing.get(key)) is not int or routing[key] < 1:
            errors.append(f"routing.{key} must be a whole number of 1 or more")
    for key in ROUTING_EFFORTS:
        if routing.get(key) not in EFFORTS:
            errors.append(f"routing.{key} must be one of {sorted(EFFORTS)}")
    return errors


def targets(cfg):
    """(tier, file) pairs whose frontmatter carries that tier's model/effort."""
    yield "planner", ROOT / "skills" / "orchestrate" / "SKILL.md"
    yield "planner", ROOT / "agents" / "orchestrator.md"
    for tier in AGENT_TIERS:
        yield tier, ROOT / "agents" / f"{cfg[tier]['agent']}.md"


def get_field(fm, key):
    m = re.search(rf"^{key}:[ \t]*(.*)$", fm, re.M)
    return m.group(1).strip().strip("\"'") if m else None


def set_field(fm, key, value):
    line = f"{key}: {value}"
    if re.search(rf"^{key}:", fm, re.M):
        return re.sub(rf"^{key}:.*$", line, fm, count=1, flags=re.M)
    return fm + line + "\n"


def main():
    check = "--check" in sys.argv[1:]
    fail = 0 if check else 1  # --check never fails, so it can't abort the skill

    try:
        cfg = json.loads(CONFIG.read_text())
        errors = validate(cfg) if isinstance(cfg, dict) else ["top level must be an object"]
    except (OSError, ValueError) as e:
        errors = [str(e)]
    if errors:
        print(f"CONFIG ERROR in {CONFIG}:", *errors, sep="\n  - ")
        return fail

    if check:
        print(f"Config: {CONFIG}")
        for tier in TIERS:
            t = cfg[tier]
            print(f"  {tier:9} model={t['model']:8} effort={t['effort']:7} agent={t.get('agent', '(main thread)')}")
        routing = {k: v for k, v in cfg.get("routing", {}).items() if not k.startswith("_")}
        print("  routing:", json.dumps(routing))

    problems, drift = [], []
    for tier, path in targets(cfg):
        want = (cfg[tier]["model"], cfg[tier]["effort"])
        name = path.relative_to(ROOT)
        m = FRONTMATTER.match(path.read_text()) if path.exists() else None
        if not m:
            problems.append(f"{name}: file or frontmatter missing")
            continue
        fm = m.group(1)
        have = (get_field(fm, "model"), get_field(fm, "effort"))
        if have == want:
            continue
        if check:
            drift.append(f"{name}: has {have[0]}/{have[1]}, config says {want[0]}/{want[1]}")
        else:
            fm = set_field(set_field(fm, "model", want[0]), "effort", want[1])
            text = path.read_text()
            path.write_text(text[: m.start(1)] + fm + text[m.end(1):])
            print(f"updated {name} -> {want[0]}/{want[1]}")

    if problems:
        print("PROBLEM:", *problems, sep="\n  - ")
    if drift:
        print("DRIFT:", *drift, sep="\n  - ")
        print(f"Fix with: python3 {Path(__file__).resolve()}")
    if not problems and not drift:
        print("In sync." if check else "Done.")
    return fail if problems else 0


if __name__ == "__main__":
    sys.exit(main())
