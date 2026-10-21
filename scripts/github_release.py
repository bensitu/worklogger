"""Create or resume a commit-bound draft release without modifying published releases."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.release_assets import RELEASE_PYTHON, checksum, validate_assets, validate_identity


class GitHubClient:
    def __init__(self, repository):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("GitHub repository must be in owner/name format")
        self.repository = repository

    def request(self, path, *, body=None, missing_ok=False, paginate=False):
        command = ["gh", "api", f"repos/{self.repository}/{path}", "--method", "POST" if body is not None else "GET",
                   "--header", "Accept: application/vnd.github+json", "--header", "X-GitHub-Api-Version: 2022-11-28"]
        if body is not None:
            command.extend(["--input", "-"])
        if paginate:
            command.extend(["--paginate", "--slurp"])
        if missing_ok:
            command.append("--include")
        response = subprocess.run(command, input=json.dumps(body) if body is not None else None,
                                  capture_output=True, text=True, timeout=120)
        payload = response.stdout
        if missing_ok:
            header, separator, payload = payload.partition("\n\n")
            status = re.search(r"^HTTP/\S+\s+(\d{3})\b", header, re.MULTILINE)
            if status is None or not separator:
                raise RuntimeError(f"GitHub API response has no HTTP status: {path}")
            if status[1] == "404":
                return None
        if response.returncode:
            raise RuntimeError(f"GitHub API request failed: {path}")
        return json.loads(payload)

    def upload(self, tag, path):
        response = subprocess.run(["gh", "release", "upload", tag, str(path), "--repo", self.repository, "--clobber"],
                                  capture_output=True, text=True, timeout=300)
        if response.returncode:
            raise RuntimeError(f"Release asset upload failed: {path.name}")


def tag_commit(client, tag):
    reference = client.request(f"git/ref/tags/{quote(tag, safe='')}", missing_ok=True)
    if reference is None:
        return None
    value = reference["object"]
    for _depth in range(10):
        if value["type"] == "commit":
            return value["sha"]
        if value["type"] != "tag":
            break
        value = client.request(f"git/tags/{value['sha']}")["object"]
    raise ValueError("Release tag does not resolve to a commit")


def validate_remote(client, tag, commit):
    validate_identity(tag, commit)
    existing_commit = tag_commit(client, tag)
    if existing_commit is not None and existing_commit != commit:
        raise ValueError("Release tag already points to a different commit")
    pages = client.request("releases?per_page=100", paginate=True)
    releases = [release for page in pages for release in page if release["tag_name"] == tag]
    if len(releases) > 1:
        raise ValueError("Multiple releases use the requested tag")
    release = releases[0] if releases else None
    if release is not None:
        if not release["draft"] or release.get("immutable"):
            raise ValueError("Published or immutable releases cannot be modified")
        if existing_commit is None and release["target_commitish"] != commit:
            raise ValueError("Existing release draft belongs to a different commit")
    return existing_commit, release


def select_artifacts(client, run_id, attempt, commit, kind):
    if run_id < 1 or attempt < 1 or client.request(f"actions/runs/{run_id}")["head_sha"] != commit:
        raise ValueError("Artifacts must belong to the requested workflow run and commit")
    prefixes = ({"release": "WorkLogger-Release-Files"} if kind == "release" else {
        "windows": f"WorkLogger-Windows-x64-Python-{RELEASE_PYTHON}",
        "linux": f"WorkLogger-Linux-x64-Python-{RELEASE_PYTHON}",
        "macos": f"WorkLogger-macOS-arm64-Python-{RELEASE_PYTHON}",
    })
    pages = client.request(f"actions/runs/{run_id}/artifacts?per_page=100", paginate=True)
    artifacts = [artifact for page in pages for artifact in page["artifacts"] if not artifact["expired"]]
    selected = {}
    for key, prefix in prefixes.items():
        candidates = []
        for artifact in artifacts:
            match = re.fullmatch(re.escape(prefix) + r"-Attempt-([1-9][0-9]*)", artifact["name"])
            if match and int(match[1]) <= attempt and artifact["workflow_run"]["head_sha"] == commit:
                candidates.append((int(match[1]), artifact["id"]))
        if not candidates:
            raise ValueError(f"Verified workflow artifact is missing: {prefix}")
        latest = max(number for number, _identifier in candidates)
        identifiers = [identifier for number, identifier in candidates if number == latest]
        if len(identifiers) != 1:
            raise ValueError(f"Workflow artifact is ambiguous: {prefix}")
        selected[key] = identifiers[0]
    return selected


def verify_release_signature(assets, commit, repository):
    workflow = os.environ.get("GITHUB_WORKFLOW_REF", "")
    expected_prefix = repository + "/.github/workflows/release-build.yml@refs/"
    if not workflow.startswith(expected_prefix) or not workflow[len(expected_prefix):].startswith(("heads/", "tags/")):
        raise ValueError("Release signing workflow identity is unavailable")
    subprocess.run(["cosign", "verify-blob", str(assets / "SHA256SUMS"),
        "--bundle", str(assets / "SHA256SUMS.sigstore.json"),
        "--certificate-identity", "https://github.com/" + workflow,
        "--certificate-oidc-issuer", "https://token.actions.githubusercontent.com",
        "--certificate-github-workflow-sha", commit], check=True, timeout=120)


def publish_draft(client, assets, tag, commit):
    paths = validate_assets(assets, tag, commit, require_signatures=True)
    verify_release_signature(assets, commit, client.repository)
    expected = {path.name: path for path in paths}
    existing_commit, release = validate_remote(client, tag, commit)
    if release is not None and any(asset["name"] not in expected for asset in release["assets"]):
        raise ValueError("Existing draft contains assets outside the verified release file set")
    if existing_commit is None:
        client.request("git/refs", body={"ref": f"refs/tags/{tag}", "sha": commit})
    if tag_commit(client, tag) != commit:
        raise ValueError("Release tag changed during publication")
    if release is None:
        release = client.request("releases", body={"tag_name": tag, "target_commitish": commit,
            "name": f"WorkLogger {tag}", "draft": True, "prerelease": "-" in tag,
            "generate_release_notes": True, "make_latest": "false"})
    path = f"releases/{release['id']}"
    for asset in paths:
        current = client.request(path)
        if not current["draft"] or current.get("immutable") or current["tag_name"] != tag or tag_commit(client, tag) != commit:
            raise ValueError("Release is no longer an editable draft for the requested commit")
        client.upload(tag, asset)
    current = client.request(path)
    if not current["draft"] or current.get("immutable") or current["tag_name"] != tag or tag_commit(client, tag) != commit:
        raise ValueError("Release changed during publication")
    uploaded = current["assets"]
    if len(uploaded) != len(expected) or {asset["name"] for asset in uploaded} != set(expected):
        raise ValueError("Uploaded release asset set is incomplete")
    for asset in uploaded:
        source = expected[asset["name"]]
        if (asset["state"] != "uploaded" or asset["size"] != source.stat().st_size
                or asset.get("digest") != f"sha256:{checksum(source)}"):
            raise ValueError(f"Uploaded release asset checksum differs: {source.name}")
    return current["html_url"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("validate", "select", "publish"))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--kind", choices=("builds", "release"))
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--attempt", type=int)
    args = parser.parse_args()
    client = GitHubClient(args.repository)
    validate_identity(args.tag, args.commit)
    if args.operation == "select":
        if args.kind is None or args.run_id is None or args.attempt is None:
            parser.error("--kind, --run-id and --attempt are required for artifact selection")
        selected = select_artifacts(client, args.run_id, args.attempt, args.commit, args.kind)
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            for key, identifier in selected.items():
                stream.write(f"{key}={identifier}\n")
        print(f"Selected {len(selected)} verified workflow artifacts")
    elif args.operation == "validate":
        validate_remote(client, args.tag, args.commit)
        print(f"Release version and remote state validated for {args.tag}")
    else:
        if args.assets is None:
            parser.error("--assets is required for publication")
        url = publish_draft(client, args.assets, args.tag, args.commit)
        print(f"Draft release verified: {url}")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as stream:
                stream.write(f"### Draft Release\n\n[{args.tag}]({url})\n\nCommit: `{args.commit}`\n")


if __name__ == "__main__":
    main()
