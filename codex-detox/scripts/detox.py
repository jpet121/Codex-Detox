"""Codex Detox command line. Python 3.11 or later."""
import argparse
import html
import json
import re
import sys
import uuid
from pathlib import Path

sys.dont_write_bytecode = True
from inventory import STATE, TEMPLATE, checked, digest, inventory, put, repo_metadata, small
from journal import execute, project_lock

def report(runpath, rows):
    sections = []
    numbers = {key: i for i, key in enumerate((r[3] for r in rows if r[3]), 1)}
    for area in ("Skills", "Instructions", "Connectors", "Chats", "Schedules"):
        items = []
        for group, title, detail, key in rows:
            if group == area:
                choice = (f'<label><input type="checkbox" value="{key}"> Item {numbers[key]} · Archive project copy</label>' if key else "")
                items.append(f"<article><strong>{html.escape(title)}</strong><pre>{html.escape(detail)}</pre>{choice}</article>")
        sections.append(f"<section><h2>{area}</h2>" + ("".join(items) or "<p>No entries found in the scanned locations.</p>") + "</section>")
    page = TEMPLATE.read_text(encoding="utf-8").replace("RUN_ID", runpath.name).replace("REPORT_ROWS", "".join(sections))
    (runpath / "report.html").write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["scan", "list", "select", "annotate", "preview", "apply", "undo"])
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--run")
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--item", action="append", type=int)
    parser.add_argument("--confirm")
    parser.add_argument("--notes", type=Path)
    args = parser.parse_args()
    if args.command == "scan":
        project = args.project.resolve(strict=True)
        if not project.is_dir():
            raise ValueError("Select a project directory")
        run = uuid.uuid4().hex
        location = checked(STATE / run)
        location.mkdir(mode=0o700, parents=True)
        rows, actions = inventory(project, run)
        put(location / "audit.json", dict(version=2, project=str(project), actions=actions))
        put(location / "rows.json", rows)
        report(location, rows)
        print(location / "report.html")
        return
    if not re.fullmatch("[a-f0-9]{32}", args.run or ""):
        raise ValueError("Supply the scan run ID")
    location = checked(STATE / args.run)
    audit = json.loads(checked(location / "audit.json").read_text(encoding="utf-8"))
    project = Path(audit["project"])
    if args.command in ("list", "select"):
        choices = list(audit["actions"])
        if args.command == "list":
            if not choices:
                print("No eligible local archives.")
            for idx, key in enumerate(choices, 1):
                print(f"{idx}. Archive {audit['actions'][key]['source']}")
            return
        if not args.item or any(n < 1 or n > len(choices) for n in args.item) or len(set(args.item)) != len(args.item):
            raise ValueError("Use distinct item numbers from the list")
        selection = location / ("selection-" + uuid.uuid4().hex + ".json")
        put(selection, dict(run=args.run, ids=[choices[n-1] for n in args.item]))
        print(selection)
        return
    if args.command == "annotate":
        if not args.notes:
            raise ValueError("Supply a notes file")
        notes = json.loads(small(args.notes.absolute()))
        if not isinstance(notes, list):
            raise ValueError("Expected a list of observations")
        rows = json.loads((location / "rows.json").read_text(encoding="utf-8"))
        for note in notes:
            if (not isinstance(note, dict) or set(note) != {"area", "title", "detail"}
                    or any(not isinstance(v, str) for v in note.values())
                    or note["area"] not in {"Skills", "Instructions", "Chats", "Schedules", "Connectors"}):
                raise ValueError("Invalid observation")
            rows.append((note["area"], note["title"], note["detail"], ""))
        report(location, rows)
        print(location / "report.html")
        return
    journal = location / "receipt.json"
    if checked(project / ".codex-detox.lock").exists():
        raise ValueError("Earlier Detox operation lock exists. Check its owner before retrying.")
    if args.command == "undo":
        receipt = json.loads(checked(journal).read_text(encoding="utf-8"))
        selected = receipt["ids"]
    else:
        if not args.selection:
            raise ValueError("Supply the exported selection")
        selection = json.loads(small(args.selection.absolute()))
        if not isinstance(selection, dict):
            raise ValueError("Expected a selection object")
        selected = selection.get("ids")
        if selection.get("run") != args.run or not isinstance(selected, list) or not selected:
            raise ValueError("Empty selection or wrong run")
    if any(not isinstance(k, str) or k not in audit["actions"] for k in selected) or len(set(selected)) != len(selected):
        raise ValueError("Unknown or repeated action")
    plan = [audit["actions"][k] for k in selected]
    token = digest([args.run, selected, plan])
    if args.command == "preview":
        if audit.get("version") != 2:
            raise ValueError("Use a fresh scan for preview and apply. Previous receipts support undo.")
        current = inventory(project, args.run)[1]
        if any(current.get(k) != a for k, a in zip(selected, plan)):
            raise ValueError("The project changed. Scan again.")
        print(json.dumps(plan, indent=2), "\nConfirmation:", token)
        return
    if args.confirm != token:
        raise ValueError("Preview the exact plan and confirm it first")
    meta = repo_metadata(project)
    directory = meta / "codex-detox-backups" if meta else project / ".codex-detox-backups"
    with project_lock(directory):
        receipt = json.loads(checked(journal).read_text(encoding="utf-8")) if journal.exists() else None
        execute(project, args.run, audit, selected, token, journal, receipt, args.command == "undo")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        sys.exit(f"Detox stopped: {error}")
