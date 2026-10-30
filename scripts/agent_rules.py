#!/usr/bin/env python3
"""Verify adopted rules and distribute reviewed revisions through draft PRs."""

import argparse
import base64
import difflib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

SOURCE = "Flachzange/FHEM_Agent_Rules"
MANIFEST = ".github/agent-rules.json"
SYNC_BRANCH = "codex/sync-agent-rules"
SHA = re.compile(r"[0-9a-f]{40}\Z")
SUPPLEMENT = re.compile(r"AGENTS-[A-Za-z0-9_-]+\.md\Z")
REPOSITORY = re.compile(r"Flachzange/[A-Za-z0-9_.-]+\Z")
MAX_FILE = 256 * 1024


class RulesError(Exception):
    """An actionable validation or synchronization failure."""


def git(root, *args, ok=(0,)):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False
    )
    if result.returncode not in ok:
        raise RulesError(f"git {args[0]} failed (exit {result.returncode})")
    return result


def read_json(content):
    try:
        return json.loads(content)
    except (UnicodeError, ValueError) as exc:
        raise RulesError("Invalid UTF-8 JSON") from exc


def consumers(root, revision=None):
    raw = (Path(root) / "consumers.json").read_bytes() if revision is None else \
        git(root, "show", f"{revision}:consumers.json").stdout
    data = read_json(raw)
    if not isinstance(data, dict) or set(data) != {"schema", "consumers"} or data["schema"] != 1:
        raise RulesError("Invalid consumer registry schema")
    if not isinstance(data["consumers"], list) or not data["consumers"]:
        raise RulesError("Consumer registry must be a nonempty list")
    seen = set()
    for item in data["consumers"]:
        if not isinstance(item, dict) or set(item) != {"repository", "branch", "supplement"}:
            raise RulesError("Invalid consumer entry")
        if not isinstance(item["repository"], str) or not REPOSITORY.fullmatch(item["repository"]):
            raise RulesError("Invalid consumer repository")
        if item["repository"] == SOURCE or item["repository"] in seen:
            raise RulesError("Duplicate or self-referencing consumer")
        seen.add(item["repository"])
        if item["branch"] != "main" or not isinstance(item["supplement"], str) or \
                not SUPPLEMENT.fullmatch(item["supplement"]):
            raise RulesError("Invalid consumer branch or supplement")
    return data["consumers"]


def manifest(revision, supplement):
    return {"schema": 1, "source": {"repository": SOURCE, "path": "AGENTS.md",
            "revision": revision}, "supplement": supplement}


def validate_manifest(raw, config):
    data = read_json(raw)
    if not isinstance(data, dict) or set(data) != {"schema", "source", "supplement"}:
        raise RulesError("Invalid adoption manifest")
    source = data.get("source")
    if data["schema"] != 1 or not isinstance(source, dict) or \
            set(source) != {"repository", "path", "revision"} or \
            source["repository"] != SOURCE or source["path"] != "AGENTS.md":
        raise RulesError("Unexpected canonical source or manifest schema")
    revision = source["revision"]
    if not isinstance(revision, str) or not SHA.fullmatch(revision):
        raise RulesError("Rules revision must be a full lowercase commit SHA")
    if data["supplement"] != config["supplement"]:
        raise RulesError("Project supplement differs from the central registry")
    return data


def canonical(root, revision):
    if not SHA.fullmatch(revision):
        raise RulesError("Invalid source revision")
    accepted = git(root, "merge-base", "--is-ancestor", revision,
                   "refs/remotes/origin/main", ok=(0, 1))
    if accepted.returncode:
        raise RulesError("Rules revision is not merged into central main")
    return git(root, "show", f"{revision}:AGENTS.md").stdout


def regular_file(root, relative):
    path = Path(root) / relative
    # Do not follow a .github symlink or a symlink to another project's rules.
    for part in [path, *list(path.parents)[:len(Path(relative).parts) - 1]]:
        if part.is_symlink():
            raise RulesError(f"Symlinks are not allowed for {relative}")
    if not path.is_file():
        raise RulesError(f"Required file missing: {relative}")
    if path.stat().st_size > MAX_FILE:
        raise RulesError(f"File too large: {relative}")
    return path.read_bytes()


def check(project, central, repository, diff_output=None):
    registry = consumers(central)
    configs = [c for c in registry if c["repository"] == repository]
    if len(configs) != 1:
        raise RulesError("Repository is not registered as a consumer")
    config = configs[0]
    data = validate_manifest(regular_file(project, MANIFEST), config)
    regular_file(project, config["supplement"])
    expected = canonical(central, data["source"]["revision"])
    actual = regular_file(project, "AGENTS.md")
    if actual != expected:
        if diff_output:
            patch = "".join(difflib.unified_diff(
                expected.decode("utf-8").splitlines(keepends=True),
                actual.decode("utf-8").splitlines(keepends=True),
                fromfile="a/AGENTS.md", tofile="b/AGENTS.md"))
            Path(diff_output).write_text(patch, encoding="utf-8")
        raise RulesError("Local AGENTS.md differs: preserve the patch and propose generic changes centrally")
    return data["source"]["revision"]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, token):
        if not token:
            raise RulesError("GH_TOKEN is required for live synchronization")
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect)

    def call(self, method, path, data=None, missing=False):
        payload = None if data is None else json.dumps(data).encode("utf-8")
        request = urllib.request.Request(
            "https://api.github.com" + path, data=payload, method=method,
            headers={"Accept": "application/vnd.github+json",
                     "Authorization": "Bearer " + self.token,
                     "X-GitHub-Api-Version": "2022-11-28",
                     "Content-Type": "application/json", "User-Agent": "FHEM-Agent-Rules"})
        try:
            with self.opener.open(request, timeout=30) as response:
                return read_json(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and missing:
                return None
            raise RulesError(f"GitHub {method} {path.split('?')[0]} returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise RulesError("GitHub request failed; no automatic write retry") from exc

    def file(self, repo, path, revision):
        data = self.call("GET", f"/repos/{repo}/contents/{path}?" +
                         urllib.parse.urlencode({"ref": revision}))
        if data.get("type") != "file" or data.get("encoding") != "base64" or \
                data.get("size", MAX_FILE + 1) > MAX_FILE:
            raise RulesError("Unexpected GitHub file response")
        try:
            result = base64.b64decode(data["content"].replace("\n", ""), validate=True)
        except (KeyError, ValueError) as exc:
            raise RulesError("Invalid GitHub file content") from exc
        if len(result) > MAX_FILE:
            raise RulesError("GitHub file exceeds size limit")
        return result


def sync_consumer(api, central, config, target, apply=False):
    repo = config["repository"]
    prefix = f"/repos/{repo}"
    default = api.call("GET", prefix + "/git/ref/heads/main")["object"]["sha"]
    current = validate_manifest(api.file(repo, MANIFEST, default), config)
    old_rules = canonical(central, current["source"]["revision"])
    new_rules = canonical(central, target)
    if git(central, "merge-base", "--is-ancestor", current["source"]["revision"],
           target, ok=(0, 1)).returncode:
        raise RulesError(f"{repo}: refusing to downgrade the adopted revision")
    if api.file(repo, "AGENTS.md", default) != old_rules:
        raise RulesError(f"{repo}: default-branch drift; refusing to overwrite local discoveries")
    api.file(repo, config["supplement"], default)
    if old_rules == new_rules:
        return "current"
    desired = {"AGENTS.md": new_rules.decode("utf-8"),
               MANIFEST: json.dumps(manifest(target, config["supplement"]), indent=2) + "\n"}
    branch = api.call("GET", prefix + "/git/ref/heads/" + SYNC_BRANCH, missing=True)
    parent = default
    owner = repo.split("/")[0]
    prs = api.call("GET", prefix + "/pulls?" + urllib.parse.urlencode(
        {"state": "open", "head": owner + ":" + SYNC_BRANCH, "base": "main", "per_page": 100}))
    if len(prs) > 1:
        raise RulesError(f"{repo}: multiple open synchronization PRs")
    unchanged = False
    if branch:
        parent = branch["object"]["sha"]
        comparison = api.call("GET", prefix + f"/compare/{default}...{parent}")
        files = comparison.get("files", [])
        if comparison.get("total_commits", 0) > 100 or \
                any(f["filename"] not in desired or f.get("status") not in {"modified", "added"}
                    for f in files):
            raise RulesError(f"{repo}: synchronization branch contains unrelated changes")
        branch_manifest = validate_manifest(api.file(repo, MANIFEST, parent), config)
        branch_rules = api.file(repo, "AGENTS.md", parent)
        if branch_rules != canonical(central, branch_manifest["source"]["revision"]):
            raise RulesError(f"{repo}: synchronization branch was hand-edited")
        # Do not downgrade a branch already carrying a later reviewed source revision.
        if git(central, "merge-base", "--is-ancestor", branch_manifest["source"]["revision"],
               target, ok=(0, 1)).returncode:
            raise RulesError(f"{repo}: synchronization branch is newer than this distribution run")
        unchanged = all(api.file(repo, path, parent).decode("utf-8") == content
                        for path, content in desired.items())
    elif prs:
        raise RulesError(f"{repo}: PR exists without the expected branch")
    if not apply:
        return "would update draft PR" if prs else "would create draft PR"
    if api.call("GET", prefix + "/git/ref/heads/main")["object"]["sha"] != default:
        raise RulesError(f"{repo}: main changed during planning; rerun without overwriting")
    if not unchanged:
        commit = api.call("GET", prefix + "/git/commits/" + parent)
        tree = api.call("POST", prefix + "/git/trees", {
            "base_tree": commit["tree"]["sha"],
            "tree": [{"path": p, "mode": "100644", "type": "blob", "content": c}
                     for p, c in desired.items()]})
        created = api.call("POST", prefix + "/git/commits", {
            "message": "docs: synchronize central agent rules", "tree": tree["sha"], "parents": [parent]})
        if branch:
            # A concurrently advanced branch rejects this non-fast-forward update.
            api.call("PATCH", prefix + "/git/refs/heads/" + SYNC_BRANCH,
                     {"sha": created["sha"], "force": False})
        else:
            api.call("POST", prefix + "/git/refs",
                     {"ref": "refs/heads/" + SYNC_BRANCH, "sha": created["sha"]})
    title = "Synchronize shared FHEM agent rules"
    body = (f"Adopt {SOURCE}@{target}.\n\n"
            "Only AGENTS.md and its adoption manifest are updated. Project supplements, "
            "module code, versions and workflows remain unchanged.\n\n"
            "The distributor verified the old copy against its recorded central revision "
            "and refused local drift. Review the central rule changes and consumer CI "
            "before merging; this PR does not approve or merge itself.\n\n"
            f"Source: https://github.com/{SOURCE}/blob/{target}/AGENTS.md")
    if prs:
        if prs[0].get("title") != title or prs[0].get("body") != body:
            api.call("PATCH", prefix + "/pulls/" + str(prs[0]["number"]),
                     {"title": title, "body": body})
        return "updated existing PR" if not unchanged else "existing PR is current"
    api.call("POST", prefix + "/pulls", {"title": title, "body": body,
             "head": SYNC_BRANCH, "base": "main", "draft": True})
    return "created draft PR"


def validate(root):
    consumers(root)
    for name in ("AGENTS.md", "AGENTS-RULES.md", "README.md"):
        text = regular_file(root, name).decode("utf-8")
        if "\r" in text or not text.endswith("\n"):
            raise RulesError(f"{name}: use UTF-8 with LF and a final newline")
    text = (Path(root) / "AGENTS.md").read_text(encoding="utf-8")
    for required in (SOURCE, "Shared rules maintenance", "AGENTS-*.md"):
        if required not in text:
            raise RulesError("Shared maintenance contract is missing")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("check", "sync", "validate"):
        sub = commands.add_parser(command)
        sub.add_argument("--central-root", type=Path, default=Path("."))
        if command == "check":
            sub.add_argument("--project-root", type=Path, required=True)
            sub.add_argument("--repository", required=True)
            sub.add_argument("--diff-output", type=Path)
        if command == "sync":
            sub.add_argument("--apply", action="store_true", help="Write branches and draft PRs; default is dry-run")
    args = parser.parse_args()
    try:
        if args.command == "validate":
            validate(args.central_root)
            print("Central registry and rule documents: PASS")
        elif args.command == "check":
            revision = check(args.project_root, args.central_root, args.repository, args.diff_output)
            print(f"Shared rules match accepted revision {revision}: PASS")
        else:
            target = git(args.central_root, "rev-parse", "HEAD").stdout.decode().strip()
            canonical(args.central_root, target)
            api = GitHub(os.environ.get("GH_TOKEN"))
            failed = False
            for config in consumers(args.central_root):
                try:
                    print(config["repository"] + ": " + sync_consumer(
                        api, args.central_root, config, target, args.apply))
                except (RulesError, OSError, ValueError) as exc:
                    print(f"{config['repository']}: {exc}", file=sys.stderr)
                    failed = True
            return int(failed)
    except (RulesError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
