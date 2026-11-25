"""Use the public CLI to audit, archive, and restore a fictional project."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "codex-detox/scripts/detox.py"


def run_demo(root):
    home, project = root / "personal", root / "project"
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home),
               CODEX_HOME=str(home / ".codex"), PYTHONDONTWRITEBYTECODE="1")
    # No account, real user configuration, or real repository is needed.
    for name in ("code-review", "release-review"):
        for scope in (home, project):
            folder = scope / ".agents/skills" / name
            folder.mkdir(parents=True)
            (folder / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Review a sample change.\n---\nCheck the test result.\n",
                encoding="utf-8")
            helper = folder / "rules.txt"
            rule = "Require independent review.\n"
            if scope == project and name == "release-review":
                rule += "Keep the release receipt.\n"
            helper.write_text(rule, encoding="utf-8")

    def cli(*args):
        result = subprocess.run([sys.executable, "-B", str(CLI), *map(str, args)],
                                env=env, cwd=project, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout.strip()

    report = Path(cli("scan", "--project", project))
    run = report.parent.name
    findings = json.loads((report.parent / "rows.json").read_text(encoding="utf-8"))
    choices = [row for row in findings if row[3]]
    if len(choices) != 1 or choices[0][1] != "code-review":
        raise ValueError("Expected one eligible duplicate")
    if not any(row[1] == "release-review" and "rules.txt" in row[2] and not row[3] for row in findings):
        raise ValueError("Expected the changed helper to require review")
    print("code-review      Identical bundle. Eligible for archive.")
    print("release-review   rules.txt differs. Keep for review.")
    selection = cli("select", "--run", run, "--item", 1)
    params = ["--run", run, "--selection", selection]
    preview = cli("preview", *params)
    token = preview.split()[-1]
    print("Preview          1 project copy selected.")
    receipt = Path(cli("apply", *params, "--confirm", token))
    def state():
        return json.loads(receipt.read_text(encoding="utf-8"))
    applied = state()
    source = Path(applied["plan"][0]["source"])
    backup = Path(applied["plan"][0]["backup"])
    if applied["status"] != "applied" or source.exists() or not backup.is_dir():
        raise ValueError("Archive verification failed")
    print("Archive          Project copy moved. Backup verified.")
    cli("undo", "--run", run, "--confirm", token)
    if state()["status"] != "restored" or not source.is_dir() or backup.exists():
        raise ValueError("Restore verification failed")
    print("Undo             Project copy restored. Receipt verified.")
    return report, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", type=Path, metavar="NEW_FOLDER",
                        help="Save the fictional project, report, and receipt to a new folder")
    args = parser.parse_args()
    if args.keep:
        root = args.keep.resolve()
        root.mkdir(parents=True, exist_ok=False)
        report, receipt = run_demo(root)
        print(f"Report: {report}\nReceipt: {receipt}")
    else:
        with tempfile.TemporaryDirectory(prefix="codex-detox-demo-") as root:
            run_demo(Path(root).resolve())


if __name__ == "__main__":
    main()
