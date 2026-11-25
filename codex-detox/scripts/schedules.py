"""Record a reversible pause plan. The host performs the authorized provider call."""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
from inventory import STATE, checked, digest, put, small
from journal import project_lock


def read_observation(path):
    item = json.loads(small(path.absolute()))
    required = {"id", "title", "enabled"}
    if (not isinstance(item, dict) or item.keys() != required or type(item["enabled"]) is not bool
            or any(not isinstance(item[k], str) or not item[k].strip() for k in ("id", "title"))):
        raise ValueError("Expected a task ID, title, and observed enabled boolean")
    return item


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("preview", "prepare", "verify", "prepare-undo", "verify-undo"))
    parser.add_argument("--run", required=True)
    parser.add_argument("--observed", required=True, type=Path)
    parser.add_argument("--confirm")
    args = parser.parse_args()
    if not re.fullmatch("[a-f0-9]{32}", args.run):
        raise ValueError("Invalid run")
    folder = checked(STATE / args.run)
    if not (folder / "audit.json").is_file():
        raise ValueError("Unknown audit run")
    observed = read_observation(args.observed)
    plan = {"run":args.run, "id":observed["id"], "title":observed["title"], "before":True, "after":False}
    token = digest(plan)
    receipt = folder / ("schedule-" + digest(observed["id"]) + ".json")
    if args.operation == "preview":
        if not observed["enabled"]:
            raise ValueError("Task is already paused")
        print(json.dumps(plan, indent=2), "\nConfirmation:", token)
        return
    if args.confirm != token:
        raise ValueError("Task identity or title differs from the approved preview")
    with project_lock(folder / "schedule-locks"):
        record = json.loads(checked(receipt).read_text(encoding="utf-8")) if receipt.exists() else {
            "plan":plan, "confirmation":token, "status":"new", "observations":[]}
        if record["plan"] != plan:
            raise ValueError("Receipt belongs to a different task plan")
        state = record["status"]
        allowed, expected, status = {
            "prepare": (("new","pause-pending"),True,"pause-pending"),
            "verify": (("pause-pending","paused"),False,"paused"),
            "prepare-undo": (("paused","resume-pending"),False,"resume-pending"),
            "verify-undo": (("resume-pending","resumed"),True,"resumed"),
        }[args.operation]
        matches = state in allowed and observed["enabled"] is expected
        record["observations"].append({"timestamp":datetime.now(timezone.utc).isoformat(),
                                       "step":args.operation, "enabled":observed["enabled"], "matched":matches})
        if matches:
            record["status"] = status
        put(receipt,record)
        print(receipt)
        if not matches:
            raise ValueError(f"Unexpected provider state or receipt phase ({state}). Review before continuing.")
        print(status, file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        sys.exit(f"Schedule operation stopped: {exc}")
