import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "agent_rules", Path(__file__).resolve().parents[1] / "scripts/agent_rules.py")
rules = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rules)
CONFIG = {"repository": "Flachzange/FHEM_Modul_Wiffi", "branch": "main",
          "supplement": "AGENTS-WIFFI.md"}


class FakeGitHub:
    """Stateful REST contract double; it does not exercise real GitHub permissions."""

    def __init__(self, revision, text):
        self.calls = []
        self.sequence = 100
        self.refs = {"main": "a" * 40}
        self.commits = {self.refs["main"]: {"tree": {"sha": "original"}}}
        self.trees = {"original": {
            "AGENTS.md": text,
            rules.MANIFEST: json.dumps(rules.manifest(revision, CONFIG["supplement"])),
            CONFIG["supplement"]: "Project-specific contract\n",
            "FHEM/unchanged.pm": "unchanged module\n"}}
        self.prs = []

    @property
    def writes(self):
        return [call for call in self.calls if call[0] != "GET"]

    def next_sha(self):
        self.sequence += 1
        return f"{self.sequence:040x}"

    def files(self, revision):
        return self.trees[self.commits[revision]["tree"]["sha"]]

    def file(self, repo, path, revision):
        return self.files(revision)[path].encode()

    def call(self, method, path, data=None, missing=False):
        self.calls.append((method, path, copy.deepcopy(data)))
        path = path.removeprefix("/repos/" + CONFIG["repository"])
        if method == "GET" and path.startswith("/git/ref/heads/"):
            sha = self.refs.get(path.removeprefix("/git/ref/heads/"))
            return {"object": {"sha": sha}} if sha else None
        if method == "GET" and path.startswith("/pulls?"):
            return copy.deepcopy(self.prs)
        if method == "GET" and path.startswith("/compare/"):
            base, head = path.removeprefix("/compare/").split("...")
            left, right = self.files(base), self.files(head)
            return {"total_commits": 1, "files": [
                {"filename": p, "status": "modified" if p in left else "added"}
                for p in set(left) | set(right) if left.get(p) != right.get(p)]}
        if method == "GET" and path.startswith("/git/commits/"):
            return self.commits[path.removeprefix("/git/commits/")]
        if method == "POST" and path == "/git/trees":
            sha = self.next_sha()
            self.trees[sha] = dict(self.trees[data["base_tree"]])
            self.trees[sha].update({f["path"]: f["content"] for f in data["tree"]})
            return {"sha": sha}
        if method == "POST" and path == "/git/commits":
            sha = self.next_sha()
            self.commits[sha] = {"tree": {"sha": data["tree"]}, "parents": data["parents"]}
            return {"sha": sha}
        if method == "POST" and path == "/git/refs":
            branch = data["ref"].removeprefix("refs/heads/")
            assert branch not in self.refs
            self.refs[branch] = data["sha"]
            return {}
        if method == "PATCH" and path.startswith("/git/refs/heads/"):
            branch = path.removeprefix("/git/refs/heads/")
            assert data["force"] is False
            assert self.commits[data["sha"]]["parents"] == [self.refs[branch]]
            self.refs[branch] = data["sha"]
            return {}
        if method == "POST" and path == "/pulls":
            self.prs.append(dict(data, number=1))
            return self.prs[-1]
        if method == "PATCH" and path == "/pulls/1":
            self.prs[0].update(data)
            return self.prs[0]
        raise AssertionError((method, path, data))


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.central = self.root / "central"
        self.project = self.root / "project"
        self.central.mkdir()
        (self.project / ".github").mkdir(parents=True)
        self.run_git("init", "-q", "-b", "main")
        self.run_git("config", "user.name", "Rules test")
        self.run_git("config", "user.email", "rules@example.invalid")
        (self.central / "consumers.json").write_text(json.dumps(
            {"schema": 1, "consumers": [CONFIG]}))
        (self.central / "AGENTS.md").write_text("Original rules\n")
        self.old = self.commit()
        (self.central / "AGENTS.md").write_text("Reviewed new rules\n")
        self.new = self.commit()
        self.run_git("update-ref", "refs/remotes/origin/main", self.new)
        self.write_project(self.old, "Original rules\n")
        self.api = FakeGitHub(self.old, "Original rules\n")

    def run_git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.central), *args], text=True).strip()

    def commit(self):
        self.run_git("add", ".")
        self.run_git("commit", "-qm", "Test revision")
        return self.run_git("rev-parse", "HEAD")

    def write_project(self, revision, text):
        (self.project / "AGENTS.md").write_text(text)
        (self.project / CONFIG["supplement"]).write_text("Project-only rules\n")
        (self.project / rules.MANIFEST).write_text(json.dumps(
            rules.manifest(revision, CONFIG["supplement"])))

    def check(self, **kwargs):
        return rules.check(self.project, self.central, CONFIG["repository"], **kwargs)

    def sync(self, target=None, apply=True):
        return rules.sync_consumer(self.api, self.central, CONFIG, target or self.new, apply)

    def test_valid_adopted_revision(self):
        self.assertEqual(self.check(), self.old)

    def test_changed_copy_fails_and_preserves_patch_without_rewriting(self):
        (self.project / "AGENTS.md").write_text("Local discovery\n")
        patch = self.root / "proposal.patch"
        with self.assertRaisesRegex(rules.RulesError, "differs"):
            self.check(diff_output=patch)
        self.assertIn("+Local discovery", patch.read_text())
        self.assertIn("-Original rules", patch.read_text())
        self.assertEqual((self.project / "AGENTS.md").read_text(), "Local discovery\n")

    def test_unmerged_revision_rejected_even_when_bytes_match(self):
        self.run_git("checkout", "-qb", "proposal")
        (self.central / "AGENTS.md").write_text("Not approved\n")
        proposed = self.commit()
        self.write_project(proposed, "Not approved\n")
        with self.assertRaisesRegex(rules.RulesError, "not merged"):
            self.check()

    def test_unknown_revision_rejected(self):
        self.write_project("f" * 40, "Original rules\n")
        with self.assertRaises(rules.RulesError):
            self.check()

    def test_wrong_source_and_short_revision_rejected(self):
        for change in ({"repository": "Flachzange/Other"}, {"revision": "main"}, {"path": "other.md"}):
            data = rules.manifest(self.old, CONFIG["supplement"])
            data["source"].update(change)
            (self.project / rules.MANIFEST).write_text(json.dumps(data))
            with self.assertRaises(rules.RulesError):
                self.check()

    def test_missing_or_symlinked_supplement_rejected(self):
        supplement = self.project / CONFIG["supplement"]
        supplement.unlink()
        with self.assertRaisesRegex(rules.RulesError, "missing"):
            self.check()
        supplement.symlink_to(self.project / "AGENTS.md")
        with self.assertRaisesRegex(rules.RulesError, "Symlinks"):
            self.check()

    def test_unregistered_repository_rejected(self):
        with self.assertRaisesRegex(rules.RulesError, "not registered"):
            rules.check(self.project, self.central, "Flachzange/Other")

    def test_registry_duplicate_and_traversal_rejected(self):
        for items in ([CONFIG, CONFIG], [dict(CONFIG, supplement="../other.md")]):
            (self.central / "consumers.json").write_text(json.dumps({"schema": 1, "consumers": items}))
            with self.assertRaises(rules.RulesError):
                rules.consumers(self.central)

    def test_sync_dry_run_has_no_writes(self):
        self.assertEqual(self.sync(apply=False), "would create draft PR")
        self.assertEqual(self.api.writes, [])

    def test_sync_creates_only_allowed_files_on_draft_branch(self):
        before = copy.deepcopy(self.api.files(self.api.refs["main"]))
        self.assertEqual(self.sync(), "created draft PR")
        self.assertEqual(self.api.files(self.api.refs["main"]), before)
        branch = self.api.files(self.api.refs[rules.SYNC_BRANCH])
        changed = {p for p in branch if branch[p] != before[p]}
        self.assertEqual(changed, {"AGENTS.md", rules.MANIFEST})
        self.assertTrue(self.api.prs[0]["draft"])
        self.assertEqual(json.loads(branch[rules.MANIFEST])["source"]["revision"], self.new)

    def test_second_sync_does_not_write_or_duplicate_pr(self):
        self.sync()
        self.api.calls.clear()
        self.assertEqual(self.sync(), "existing PR is current")
        self.assertEqual(self.api.writes, [])
        self.assertEqual(len(self.api.prs), 1)

    def test_interrupted_run_reuses_branch_and_creates_only_missing_pr(self):
        self.sync()
        self.api.prs.clear()
        previous = self.api.refs[rules.SYNC_BRANCH]
        self.api.calls.clear()
        self.assertEqual(self.sync(), "created draft PR")
        self.assertEqual(self.api.refs[rules.SYNC_BRANCH], previous)
        self.assertEqual([call[1] for call in self.api.writes],
                         ["/repos/" + CONFIG["repository"] + "/pulls"])

    def test_default_branch_progress_aborts_before_writes(self):
        original_call = self.api.call
        reads = 0

        def changing_main(method, path, *args, **kwargs):
            nonlocal reads
            result = original_call(method, path, *args, **kwargs)
            if method == "GET" and path.endswith("/git/ref/heads/main"):
                reads += 1
                if reads == 2:
                    return {"object": {"sha": "f" * 40}}
            return result

        self.api.call = changing_main
        with self.assertRaisesRegex(rules.RulesError, "main changed"):
            self.sync()
        self.assertEqual(self.api.writes, [])

    def test_next_revision_updates_existing_branch_without_force(self):
        self.sync()
        previous = self.api.refs[rules.SYNC_BRANCH]
        (self.central / "AGENTS.md").write_text("Another reviewed rule\n")
        later = self.commit()
        self.run_git("update-ref", "refs/remotes/origin/main", later)
        self.assertEqual(self.sync(later), "updated existing PR")
        self.assertEqual(len(self.api.prs), 1)
        self.assertEqual(self.api.commits[self.api.refs[rules.SYNC_BRANCH]]["parents"], [previous])

    def test_default_branch_drift_is_not_overwritten(self):
        self.api.files(self.api.refs["main"])["AGENTS.md"] = "Local discovery\n"
        with self.assertRaisesRegex(rules.RulesError, "default-branch drift"):
            self.sync()
        self.assertEqual(self.api.writes, [])

    def test_sync_branch_manual_changes_are_not_overwritten(self):
        self.sync()
        self.api.files(self.api.refs[rules.SYNC_BRANCH])["AGENTS.md"] = "Local proposal\n"
        self.api.calls.clear()
        with self.assertRaisesRegex(rules.RulesError, "hand-edited"):
            self.sync()
        self.assertEqual(self.api.writes, [])

    def test_sync_branch_unrelated_changes_are_not_overwritten(self):
        self.sync()
        self.api.files(self.api.refs[rules.SYNC_BRANCH])["FHEM/unchanged.pm"] = "Unrelated change\n"
        self.api.calls.clear()
        with self.assertRaisesRegex(rules.RulesError, "unrelated"):
            self.sync()
        self.assertEqual(self.api.writes, [])

    def test_downgrade_rejected_before_writes(self):
        self.api = FakeGitHub(self.new, "Reviewed new rules\n")
        with self.assertRaisesRegex(rules.RulesError, "downgrade"):
            self.sync(self.old)
        self.assertEqual(self.api.writes, [])

    def test_current_copy_does_not_create_an_empty_pr(self):
        self.api = FakeGitHub(self.new, "Reviewed new rules\n")
        self.assertEqual(self.sync(), "current")
        self.assertEqual(self.api.writes, [])


if __name__ == "__main__":
    unittest.main()
