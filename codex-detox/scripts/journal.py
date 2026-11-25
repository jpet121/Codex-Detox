"""Verify actual paths before reporting or performing a reversible move."""
import ctypes
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path

from inventory import PERSONAL, checked, digest, git_check, inspect_skill, put, small


def signature(path, legacy):
    if legacy:
        if set(path.iterdir()) != {path / "SKILL.md"}:
            raise ValueError("Legacy backup contains additional entries")
        file = path / "SKILL.md"
        return digest([small(file).hex(), stat.S_IMODE(file.stat().st_mode)])
    return inspect_skill(path)[2]


def observe(action, legacy):
    def state(key):
        try:
            path = checked(Path(action[key]))
            if not path.exists():
                return "absent"
            return "match" if signature(path, legacy) == action["fingerprint"] else "changed"
        except (ValueError, OSError) as exc:
            return f"unverified ({exc})"
    return {key: state(key) for key in ("source", "backup", "keep")}


def expected(state, archived):
    a, b = ("absent", "match") if archived else ("match", "absent")
    return state["source"] == a and state["backup"] == b


def safe_rename(source, target):
    """Refuse an occupied destination even if it appeared after the last check."""
    if os.name == "nt":
        source.rename(target)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        result = libc.renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1)
    elif sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        result = libc.renamex_np(os.fsencode(source), os.fsencode(target), 4)
    else:
        raise ValueError("Exclusive rename unavailable on this platform")
    if result:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


@contextmanager
def project_lock(directory):
    # OS releases the lock on process exit. Keep the lock file to avoid inode races.
    checked(directory).mkdir(mode=0o700, parents=True, exist_ok=True)
    with checked(directory / "operation.lock").open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def verify_paths(action, project, run, legacy, applying):
    source, backup, keep = (checked(Path(action[k])) for k in ("source", "backup", "keep"))
    if source.parent != project / ".agents/skills" or keep.parent != PERSONAL or keep == source:
        raise ValueError("Unexpected skill source or retained personal path")
    reason, meta = git_check(source)
    if applying and reason:
        raise ValueError(f"{source}: {reason}")
    local = project / ".codex-detox-backups" / run / source.name
    if backup != local:
        # For restoration the file may now be tracked. Verify the metadata directory independently.
        if not applying and meta is None:
            from inventory import repo_metadata
            meta = repo_metadata(project)
        if legacy or not meta or backup != meta / "codex-detox-backups" / run / source.name:
            raise ValueError(f"Unexpected backup location: {backup}")
    elif applying and meta:
        raise ValueError("Project repository changed. Run a fresh audit.")


def execute(project, run, audit, ids, token, journal, receipt, reverse):
    legacy = audit.get("version", 1) == 1
    if legacy and not reverse:
        raise ValueError("Use a fresh scan for apply. Existing receipts still support undo.")
    if receipt and (receipt["ids"] != ids or receipt["confirmation"] != token):
        raise ValueError("Selection differs from this run's existing receipt")
    if receipt and not reverse and (receipt.get("direction") == "undo" or receipt["status"] in ("restoring", "restored")):
        raise ValueError("Undo has started. Run a new scan for further cleanup.")
    if not receipt:
        receipt = dict(ids=ids, confirmation=token, plan=[audit["actions"][k] for k in ids],
                       completed=[], restored=[])
    actions = audit["actions"]
    direction = "undo" if reverse else "apply"
    def validate(key):
        action = actions[key]
        verify_paths(action, project, run, legacy, not reverse)
        state = observe(action, legacy)
        # Resolve an interrupted rename only if intent was durably recorded.
        intent = receipt.get("pending")
        if intent and intent["id"] == key:
            was_apply = intent["direction"] == "apply"
            if expected(state, was_apply):
                done = receipt["completed" if was_apply else "restored"]
                if key not in done:
                    done.append(key)
                receipt.pop("pending")
            elif expected(state, not was_apply):
                receipt.pop("pending")
            else:
                raise ValueError(f"Interrupted move needs review at {action['source']}: {state}")
        if legacy and reverse and key not in receipt["completed"] and expected(state, True):
            receipt["completed"].append(key)
        was_moved = key in receipt["completed"] and key not in receipt["restored"]
        if reverse and was_moved and expected(state, False):
            receipt.setdefault("already_restored", []).append(key)
            receipt["restored"].append(key)
            return False
        if reverse and key not in receipt["completed"]:
            return False
        if not expected(state, was_moved) or (not reverse and state["keep"] != "match"):
            raise ValueError(f"Observed path state differs at {action['source']}: {state}")
        return was_moved if reverse else not was_moved
    try:
        receipt["direction"] = direction
        receipt["status"] = "restoring" if reverse else "applying"
        receipt.pop("error", None)
        # Preflight every item before moving the first one.
        ordered = list(reversed(ids)) if reverse else ids
        for key in ordered:
            validate(key)
        put(journal, receipt)
        for key in ordered:
            if not validate(key):
                continue
            action = actions[key]
            source, backup = (Path(action[k]) for k in ("source", "backup"))
            src, dst = (backup, source) if reverse else (source, backup)
            checked(dst.parent).mkdir(mode=0o700, parents=True, exist_ok=True)
            receipt["pending"] = {"id": key, "direction": direction}
            put(journal, receipt)
            safe_rename(src, dst)
            validate(key)
            put(journal, receipt)
        for key in ordered:
            if validate(key):
                raise ValueError("Requested state was not reached")
        receipt["status"] = "restored" if reverse else "applied"
    except (OSError, ValueError) as exc:
        receipt.update(status="blocked", error=str(exc))
        raise
    finally:
        receipt["observed"] = {k: observe(actions[k], legacy) for k in ids}
        put(journal, receipt)
        print(journal)
        print(f"Status: {receipt['status']}", file=sys.stderr)
        for key in ids:
            s = receipt["observed"][key]
            print(f"{actions[key]['source']} | project: {s['source']} | backup: {s['backup']} | personal: {s['keep']}", file=sys.stderr)
        if receipt["status"] == "blocked":
            print("Review the paths and error. Retry the same plan after resolving the conflict, or undo the completed moves.", file=sys.stderr)
