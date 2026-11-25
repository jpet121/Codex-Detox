"""Run with python -m unittest discover -s tests -v. Uses disposable homes and projects."""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/detox.py"


class DetoxTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.project = self.root / "Project A"
        self.home = self.root / "Personal setup"
        self.project.mkdir()
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home),
                        CODEX_HOME=str(self.home / ".codex"), PYTHONDONTWRITEBYTECODE="1")
        for key in list(self.env):
            if key.startswith("GIT_"):
                del self.env[key]

    def cli(self, *args, ok=True, inject=None):
        command = [sys.executable, "-B", str(SCRIPT)]
        if inject:
            command = [sys.executable, "-B", "-c",
                       "import sys,os;sys.path.insert(0,sys.argv.pop(1));import detox,journal\n"
                       + inject + "\ndetox.main()", str(SCRIPT.parent)]
        result = subprocess.run(command + list(map(str,args)), env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, ok, (result.stdout, result.stderr))
        return result

    def git(self, *args):
        subprocess.run(["git","-C",str(self.project),"-c","user.name=Tester","-c",
                        "user.email=test@example.invalid",*args], env=self.env, check=True, capture_output=True)

    def pair(self, name, bundled=False):
        for base in (self.home, self.project):
            path = base / ".agents/skills" / name
            path.mkdir(parents=True)
            (path / "SKILL.md").write_text(f"---\nname: {name}\n---\nReview new code.\n", encoding="utf-8")
            if bundled:
                (path / "assets").mkdir()
                (path / "assets/sample").write_bytes(bytes(range(256)))
        return path

    def scan(self):
        self.page = Path(self.cli("scan","--project",self.project).stdout.strip())
        self.run = self.page.parent.name
        audit = json.loads((self.page.parent/"audit.json").read_text())
        self.actions = audit["actions"]
        return self.page.read_text(encoding="utf-8")

    def preview(self, *numbers):
        self.selection = self.cli("select","--run",self.run,*sum((["--item", n] for n in numbers),[])).stdout.strip()
        self.args = ["--run",self.run,"--selection",self.selection]
        self.token = self.cli("preview",*self.args).stdout.split()[-1]

    def apply(self, **kwargs):
        return self.cli("apply",*self.args,"--confirm",self.token,**kwargs)

    def undo(self, **kwargs):
        return self.cli("undo","--run",self.run,"--confirm",self.token,**kwargs)

    def receipt(self):
        return json.loads((self.page.parent/"receipt.json").read_text())

    def test_chat_round_trip_identical_bundle(self):
        folder = self.pair("review", True)
        self.scan()
        self.assertIn("1. Archive",self.cli("list","--run",self.run).stdout)
        self.preview(1)
        self.apply()
        self.assertFalse(folder.exists())
        self.apply()
        self.undo(); self.undo()
        self.assertEqual((folder/"assets/sample").read_bytes(),bytes(range(256)))
        self.assertEqual(self.receipt()["status"],"restored")

    def test_different_helper_and_missing_empty_directory(self):
        folder = self.pair("audit", True)
        (folder/"assets/sample").write_bytes(b"changed")
        (folder/"empty").mkdir()
        page = self.scan()
        self.assertIn("Bundle differences",page)
        self.assertIn("assets/sample",page)
        self.assertIn("empty",page)
        self.assertFalse(self.actions)

    @unittest.skipUnless(shutil.which("git"),"requires Git")
    def test_tracked_staged_and_head_only(self):
        f=self.pair("review")
        self.git("init","-q"); self.git("add",".")
        self.assertIn("Git tracks this skill",self.scan()); self.assertFalse(self.actions)
        self.git("commit","-qm","fixture"); self.git("rm","--cached",str(f/"SKILL.md"))
        self.assertIn("HEAD contains",self.scan()); self.assertFalse(self.actions)

    @unittest.skipUnless(shutil.which("git"),"requires Git")
    def test_becomes_tracked_after_preview(self):
        f=self.pair("review")
        self.git("init","-q");self.scan();self.preview(1);self.git("add",".")
        self.apply(ok=False)
        self.assertTrue(f.exists())
        self.assertEqual(self.receipt()["completed"],[])

    @unittest.skipUnless(shutil.which("git"),"requires Git")
    def test_backup_outside_worktree(self):
        self.pair("review"); self.git("init","-q"); self.scan(); self.preview(1);self.apply()
        a=next(iter(self.actions.values()))
        self.assertTrue(Path(a["backup"]).is_relative_to(self.project/".git"))
        self.undo()

    def test_bad_config_preserves_other_findings(self):
        self.pair("review")
        config=self.project/".codex/config.toml";config.parent.mkdir()
        for content in ("mcp_servers = 5","[oops", 'mcp_servers = "opaque"'):
            config.write_text(content)
            self.assertIn("Configuration requires review",self.scan());self.assertTrue(self.actions)
        config.write_text('[mcp_servers]\ninvalid = 42\n[mcp_servers.good]\nenabled = false\ncommand="secret-sentinel"')
        page=self.scan()
        self.assertIn("Invalid server settings",page);self.assertIn("Disabled in configuration",page)
        self.assertNotIn("secret-sentinel",page)

    def test_stale_second_item_does_not_move_first(self):
        first=self.pair("alpha"); second=self.pair("beta");self.scan();self.preview(1,2)
        (second/"SKILL.md").write_text("changed")
        result=self.apply(ok=False)
        self.assertTrue(first.exists());self.assertIn("receipt.json",result.stdout)
        self.assertEqual(self.receipt()["completed"],[]);self.assertEqual(self.receipt()["status"],"blocked")

    def test_mid_batch_failure_has_partial_receipt_and_undo(self):
        first=self.pair("alpha");second=self.pair("beta");self.scan();self.preview(1,2)
        result=self.apply(ok=False,inject="""rename=journal.safe_rename
def fail_second(src,dst):
    if src.name == 'beta': raise OSError("simulated unavailable destination")
    rename(src,dst)
journal.safe_rename=fail_second""")
        self.assertIn("receipt.json",result.stdout)
        self.assertIn("backup: match",result.stderr)
        self.assertEqual(len(self.receipt()["completed"]),1)
        self.assertFalse(first.exists());self.assertTrue(second.exists());self.undo()
        self.assertTrue(first.exists());self.assertEqual(self.receipt()["status"],"restored")

    def test_hard_exit_after_rename_resumes(self):
        folder=self.pair("alpha");self.scan();self.preview(1)
        self.apply(ok=False, inject="""rename=journal.safe_rename
def stop_after_move(src,dst):
    rename(src,dst)
    os._exit(75)
journal.safe_rename=stop_after_move""")
        self.assertFalse(folder.exists());self.assertIn("pending",self.receipt())
        self.apply(); self.undo();self.assertTrue(folder.exists())

    def test_retry_flags_manual_restore(self):
        folder=self.pair("alpha");self.scan();self.preview(1);self.apply()
        Path(next(iter(self.actions.values()))["backup"]).rename(folder)
        self.apply(ok=False)
        self.assertEqual(self.receipt()["status"],"blocked")
        self.undo()
        self.assertEqual(len(self.receipt()["already_restored"]),1)

    def test_restore_refuses_collision_and_rechecks_repeat(self):
        folder=self.pair("alpha");self.scan();self.preview(1);self.apply()
        folder.mkdir()
        self.undo(ok=False);self.assertEqual(self.receipt()["status"],"blocked")
        folder.rmdir();self.undo()
        (folder/"SKILL.md").write_text("later edit")
        self.undo(ok=False)
        self.assertEqual((folder/"SKILL.md").read_text(),"later edit")

    def test_invalid_selection_and_confirmation(self):
        folder=self.pair("alpha");self.scan();self.preview(1)
        self.cli("apply",*self.args,"--confirm","wrong",ok=False)
        for selection in ([],dict(run="wrong",ids=list(self.actions)),dict(run=self.run,ids=["../outside"])):
            Path(self.selection).write_text(json.dumps(selection))
            self.cli("preview",*self.args,ok=False)
        self.assertTrue(folder.exists())

    def test_legacy_undo(self):
        source=self.pair("old");self.scan()
        auditfile=self.page.parent/"audit.json"; audit=json.loads(auditfile.read_text())
        key=next(iter(audit["actions"])); action=audit["actions"][key]
        def digest(obj):return hashlib.sha256(json.dumps(obj,sort_keys=True).encode()).hexdigest()
        file=source/"SKILL.md"
        action["fingerprint"]=digest([file.read_bytes().hex(),stat.S_IMODE(file.stat().st_mode)])
        audit.pop("version"); auditfile.write_text(json.dumps(audit))
        backup=Path(action["backup"]); backup.parent.mkdir(parents=True); source.rename(backup)
        self.token=digest([self.run,[key],[action]])
        receipt=dict(status="applied",ids=[key],plan=[action],completed=[key],restored=[],confirmation=self.token)
        (self.page.parent/"receipt.json").write_text(json.dumps(receipt))
        self.undo();self.assertTrue(source.exists())

    def test_repeated_instruction_locations(self):
        text = "All release builds require independent review."
        (self.project/"AGENTS.md").write_text(text)
        global_dir=self.home/".codex";global_dir.mkdir()
        (global_dir/"AGENTS.md").write_text("Heading\n" + text)
        page=self.scan()
        self.assertIn("Repeated instruction text",page)
        self.assertIn("AGENTS.md:2",page)
        self.assertIn("AGENTS.md:1",page)

    @unittest.skipUnless(shutil.which("git"),"requires Git")
    def test_alternate_index_does_not_hide_tracked_path(self):
        self.pair("private"); self.git("init","-q");self.git("add",".")
        self.env["GIT_INDEX_FILE"]=str(self.root/"different-index")
        self.assertIn("Git tracks",self.scan())
        self.assertFalse(self.actions)

    def test_schedule_verified_pause_and_resume(self):
        self.scan()
        helper=SCRIPT.with_name("schedules.py")
        observation=self.root/"observed.json"
        def write(enabled,title="Weekly review"):
            observation.write_text(json.dumps(dict(id="fixture-id",title=title,enabled=enabled)))
        def cmd(op,token=None,ok=True):
            args=[sys.executable,"-B",str(helper),op,"--run",self.run,"--observed",str(observation)]
            if token:
                args+=["--confirm",token]
            result=subprocess.run(args,env=self.env,text=True,capture_output=True)
            self.assertEqual(result.returncode==0,ok,result.stderr)
            return result.stdout.strip()
        write(True)
        token=cmd("preview").split()[-1]
        cmd("prepare","wrong",False)
        receipt=Path(cmd("prepare",token))
        cmd("verify",token,False)
        self.assertEqual(json.loads(receipt.read_text())["status"],"pause-pending")
        write(False,"Renamed");cmd("verify",token,False)
        write(False);cmd("verify",token)
        cmd("prepare-undo",token);write(True);cmd("verify-undo",token)
        self.assertEqual(json.loads(receipt.read_text())["status"],"resumed")

    def test_symlinked_bundle_requires_manual_review(self):
        folder=self.pair("alpha")
        try:
            (folder/"linked").symlink_to(folder/"SKILL.md")
        except OSError as exc:
            self.skipTest(f"Host cannot create test link: {exc}")
        self.assertIn("Linked path requires manual review",self.scan());self.assertFalse(self.actions)


if __name__ == "__main__":
    unittest.main()
