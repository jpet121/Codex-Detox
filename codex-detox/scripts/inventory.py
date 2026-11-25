"""Offline project audit. Python 3.11 or later."""
import difflib
import hashlib
import json
import os
import re
import stat
import subprocess
import tomllib
import uuid
from collections import defaultdict
from pathlib import Path

PERSONAL = Path.home() / ".agents/skills"
CONFIG = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
STATE = CONFIG / "detox-runs"
TEMPLATE = Path(__file__).resolve().parents[1] / "assets/report.html"


def checked(path):
    for part in (*reversed(path.parents), path):
        if part.is_symlink() or getattr(part.lstat() if part.exists() else None,
                                        "st_file_attributes", 0) & 1024:
            raise ValueError(f"Linked path requires manual review: {part}")
    return path


def put(path, obj):
    temp = path.with_name(uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def parents(project):
    chain = []
    for directory in (project, *project.parents):
        chain.append(directory)
        if (directory / ".git").exists():
            return list(reversed(chain))
    return [project]


def small(path):
    checked(path)
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError(f"Requires manual inspection: {path}")
    return path.read_bytes()


def inspect_skill(folder):
    data = small(folder / "SKILL.md")
    body = data.decode("utf-8-sig")
    header = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", body, re.S)
    match = header and re.search(r"""^name:[ \t]*(?:'([a-z0-9-]+)'|"([a-z0-9-]+)"|([a-z0-9-]+))[ \t]*\r?$""", header[1], re.M)
    if not match:
        raise ValueError(f"Review frontmatter manually: {folder}")
    name = next(part for part in match.groups() if part)
    entries = {}
    total = 0
    def visit(path):
        nonlocal total
        checked(path)
        info = path.stat()
        mode = stat.S_IMODE(info.st_mode)
        rel = path.relative_to(folder).as_posix()
        if len(entries) >= 4096 or len(path.relative_to(folder).parts) > 64:
            raise ValueError(f"Bundle exceeds inventory limits: {folder}")
        if path.name == ".git":
            raise ValueError(f"Embedded repository requires review: {path}")
        if stat.S_ISDIR(info.st_mode):
            entries[rel] = ["directory", mode]
            for child in sorted(path.iterdir()):
                visit(child)
        elif stat.S_ISREG(info.st_mode):
            total += info.st_size
            if total > 32 * 1024 * 1024:
                raise ValueError(f"Bundle exceeds 32 MiB: {folder}")
            with path.open("rb") as stream:
                entries[rel] = [hashlib.file_digest(stream, "sha256").hexdigest(), mode]
        else:
            raise ValueError(f"Special file requires manual review: {path}")
    visit(folder)
    return name, body, digest(entries), entries


def git_environment():
    # The caller may be checking another worktree or using a temporary index.
    return {k: v for k, v in os.environ.items()
            if k not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                         "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE"}}


def git_check(folder):
    """Return a protection reason and repository metadata directory, if any."""
    base = folder.parent
    marker = next((p for p in (base, *base.parents) if (p / ".git").exists()), None)
    if marker is None:
        return "", None
    def git(*args):
        return subprocess.run(["git", "--no-optional-locks", "--literal-pathspecs", "-C",
                               str(marker), *args], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=10, env=git_environment())
    try:
        path = folder.relative_to(marker).as_posix()
        index = git("ls-files", "--cached", "-z", "--", path)
        if index.returncode:
            return "Git index could not be checked.", None
        if index.stdout:
            return "Git tracks this skill. Teammates and clean checkouts may depend on it.", None
        head = git("rev-parse", "--verify", "-q", "HEAD")
        if head.returncode == 0:
            tree = git("ls-tree", "-z", "HEAD", "--", path)
            if tree.returncode or tree.stdout:
                return "HEAD contains this skill or its status could not be verified.", None
        elif head.returncode != 1:
            return "Git history could not be checked.", None
        meta = git("rev-parse", "--absolute-git-dir")
        if meta.returncode:
            return "Git backup location could not be verified.", None
        return "", checked(Path(os.fsdecode(meta.stdout.rstrip(b"\r\n"))))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return "Git ownership could not be verified.", None


def inventory(project, run):
    rows, groups, actions = [], defaultdict(list), {}
    def row(area, title, detail, key=""):
        rows.append((area, title, detail, key))
    chain = parents(project)
    roots = [PERSONAL] + [p / ".agents/skills" for p in chain]
    for root in dict.fromkeys(roots):
        try:
            checked(root)
            if not root.is_dir():
                continue
            for folder in sorted(root.iterdir()):
                try:
                    checked(folder)
                    if not folder.is_dir() or not (folder / "SKILL.md").exists():
                        continue
                    name, body, fingerprint, manifest = inspect_skill(folder)
                    groups[name].append((folder, body, fingerprint, manifest))
                except (ValueError, OSError) as exc:
                    row("Skills", "Manual review", str(exc))
        except (ValueError, OSError) as exc:
            row("Skills", "Incomplete inventory", str(exc))
    for name, copies in sorted(groups.items()):
        for folder, body, fingerprint, local_manifest in copies:
            others = [c for c in copies if c[0] != folder]
            detail, key = str(folder), ""
            if others:
                for other, otherbody, _, manifest in others:
                    changed = sorted(k for k in local_manifest.keys() | manifest.keys() if local_manifest.get(k) != manifest.get(k))
                    detail += ("\nBundle differences vs " + str(other) + ": " + ", ".join(changed[:40])
                               + (f" (+{len(changed)-40} more)" if len(changed)>40 else "")
                               if changed else f"\nAll scanned bundle contents and mode bits match {other}")
                    diff = list(difflib.unified_diff(otherbody.splitlines(), body.splitlines(),
                                                    fromfile=str(other), tofile=str(folder), n=2))
                    detail += "\n" + ("\n".join(diff[:80]) if diff else f"Matching instruction text: {other}")
                    if len(diff) > 80:
                        detail += "\nDiff excerpt ends here. Review the full files."
                kept = next((c for c in others if c[0].parent == PERSONAL and c[2] == fingerprint), None)
                if folder.parent == project / ".agents/skills" and folder.parent != PERSONAL:
                    reason, git_dir = git_check(folder)
                    if reason:
                        detail += "\nProtected: " + reason
                else:
                    reason, git_dir = "outside selected project", None
                if kept and not reason and name != "codex-detox":
                    key = digest([str(folder), fingerprint, str(kept[0])])
                    backup_base = git_dir / "codex-detox-backups" if git_dir else project / ".codex-detox-backups"
                    backup = backup_base / run / folder.name
                    actions[key] = dict(source=str(folder), backup=str(backup), keep=str(kept[0]), fingerprint=fingerprint)
                    detail += f"\nArchive project copy to {backup}\nKeep personal copy at {kept[0]}"
            row("Skills", name, detail, key)
    rule_lines = defaultdict(list)
    for directory in dict.fromkeys([CONFIG] + chain):
        for filename in ("AGENTS.override.md", "AGENTS.md"):
            path = directory / filename
            try:
                checked(path)
                if path.is_file() and path.stat().st_size:
                    row("Instructions", "Instruction file", str(path))
                    content = small(path).decode("utf-8-sig")
                    for line_number, line in enumerate(content.splitlines(), 1):
                        rule = line.strip().removeprefix("- ").strip()
                        if len(rule) >= 25 and not rule.startswith(("#", "```", "|")):
                            rule_lines[rule].append(f"{path}:{line_number}")
                    break
            except (ValueError, OSError) as exc:
                row("Instructions", "Manual review", str(exc))
                break
    for locations in rule_lines.values():
        if len(locations) > 1:
            row("Instructions", "Repeated instruction text", "\n".join(locations))
    for conf in [CONFIG / "config.toml"] + [d / ".codex/config.toml" for d in chain]:
        try:
            checked(conf)
            if conf.is_file():
                servers = tomllib.loads(small(conf).decode()).get("mcp_servers", {})
                if not isinstance(servers, dict):
                    raise ValueError("Expected [mcp_servers] table")
                for server, settings in sorted(servers.items()):
                    if not isinstance(settings, dict):
                        row("Connectors", "Invalid server settings", f"{server} in {conf}. Expected a table.")
                        continue
                    state = "Disabled in configuration" if settings.get("enabled") is False else "Declared"
                    row("Connectors", server, f"{state} in {conf}. Runtime status and use unknown.")
        except (ValueError, OSError) as exc:
            row("Connectors", "Configuration requires review", f"{conf}. Check TOML syntax and the mcp_servers table.")
    for category, message in [
        ("Chats", "Local scan does not inspect conversations."),
        ("Schedules", "Account schedule inventory requires a session listing tool."),
        ("Connectors", "Account connectors and recent usage require session evidence.")]:
        row(category, "Scope", message)
    return rows, actions


def repo_metadata(project):
    marker = next((p for p in (project, *project.parents) if (p / ".git").exists()), None)
    if marker is None:
        return None
    result = subprocess.run(["git", "-C", str(marker), "rev-parse", "--absolute-git-dir"],
                            capture_output=True, timeout=10, env=git_environment())
    if result.returncode:
        raise ValueError("Could not verify repository metadata directory.")
    return checked(Path(os.fsdecode(result.stdout.rstrip(b"\r\n"))))
