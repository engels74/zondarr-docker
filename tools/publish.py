#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Publish only the two tested archives for the unchanged reviewed channel."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def validate(evidence, repository, branch):
    if not re.fullmatch(r"edbfi/[a-z0-9][a-z0-9._-]*", repository):
        raise ValueError("Unexpected repository")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", branch):
        raise ValueError("Invalid image branch")
    records = []
    for arch in ("amd64", "arm64"):
        folder = evidence / (branch + "-" + arch)
        data = json.loads((folder / "metadata.json").read_text())
        if (data["repository"], data["branch"], data["arch"]) != (repository, branch, arch):
            raise ValueError("Artifact identity mismatch")
        if not re.fullmatch(r"[0-9a-f]{40}", data["revision"]):
            raise ValueError("Invalid revision")
        if not data["tags"] or any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", t) for t in data["tags"]):
            raise ValueError("Invalid image tags")
        for name in ("image.tar", "result.txt", "packages.txt"):
            if not (folder / name).is_file() or (folder / name).stat().st_size == 0:
                raise ValueError("Missing tested artifact: " + name)
        result = json.loads((folder / "runtime-result.json").read_text())
        if result.get("passed") is not True or result.get("architecture") != arch:
            raise ValueError("Runtime acceptance did not pass for this architecture")
        if not (folder / "result.txt").read_text().startswith("PASS:"):
            raise ValueError("Smoke result is not successful")
        records.append(data)
    if any(records[0][k] != records[1][k] for k in ("revision", "tags")):
        raise ValueError("Architecture revisions or tags differ")
    return records[0]


def validate_publication(data, branch, live, runs, workflow_ref, workflow_sha):
    if branch not in {"release", "nightly"} or workflow_ref != "refs/heads/" + branch:
        raise ValueError("Publish from the matching channel workflow only")
    if live["commit"]["sha"] != data["revision"] or workflow_sha != data["revision"]:
        raise ValueError("Workflow, live branch and tested revision must match")
    if not any(run["head_sha"] == data["revision"] and run["head_branch"] == branch and run["status"] == "completed" and run["conclusion"] == "success" for run in runs):
        raise ValueError("Successful final-channel CI is required before publication")


def run(args):
    subprocess.run(args, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("evidence", "repository", "branch"):
        parser.add_argument("--" + name, required=True)
    opts = parser.parse_args()
    evidence = Path(opts.evidence)
    data = validate(evidence, opts.repository, opts.branch)
    live = json.loads(subprocess.check_output(["gh", "api", f"repos/{opts.repository}/branches/{opts.branch}"], text=True))
    runs = json.loads(subprocess.check_output(["gh", "api", f"repos/{opts.repository}/actions/workflows/ci.yml/runs?head_sha={data['revision']}&event=push&per_page=100"], text=True))["workflow_runs"]
    validate_publication(data, opts.branch, live, runs, os.environ.get("GITHUB_REF"), os.environ.get("GITHUB_SHA"))
    registry = "ghcr.io/" + opts.repository
    temporary = []
    for arch in ("amd64", "arm64"):
        run(["docker", "load", "-i", str(evidence / (opts.branch + "-" + arch) / "image.tar")])
        tag = registry + ":" + opts.branch + "-" + data["revision"][:7] + "-" + os.environ["GITHUB_RUN_ID"] + "-" + arch
        run(["docker", "tag", "local-validation:" + opts.branch + "-" + arch, tag])
        run(["docker", "push", tag])
        temporary.append(tag)
    live = json.loads(subprocess.check_output(["gh", "api", f"repos/{opts.repository}/branches/{opts.branch}"], text=True))
    validate_publication(data, opts.branch, live, runs, os.environ.get("GITHUB_REF"), os.environ.get("GITHUB_SHA"))
    command = ["docker", "buildx", "imagetools", "create"]
    for tag in data["tags"]:
        command.extend(["--tag", registry + ":" + tag])
    run(command + temporary)
    run(["docker", "buildx", "imagetools", "inspect", registry + ":" + opts.branch])
