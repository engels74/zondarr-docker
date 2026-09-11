#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Validate build metadata without executing its update commands."""
import argparse
import base64
import json
import re
from pathlib import Path


def metadata(root, repository, branch, revision, arch):
    if not re.fullmatch(r"edbfi/[a-z0-9][a-z0-9._-]*", repository):
        raise ValueError("Only edbfi image repositories are supported")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", branch):
        raise ValueError("Invalid image tag")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected a full Git revision")
    if arch not in {"amd64", "arm64"}:
        raise ValueError("Unsupported architecture")
    raw = json.loads((root / "meta.json").read_text())
    if not isinstance(raw, dict):
        raise ValueError("meta.json must be an object")
    if branch not in {"release", "nightly"}:
        raise ValueError("Unsupported channel")
    if not re.fullmatch(r"[0-9a-f]{64}", raw.get("source_sha256", "")):
        raise ValueError("Missing pinned source checksum")
    if not re.fullmatch(r"[0-9a-f]{40}|v?\d+\.\d+\.\d+", str(raw.get("version", ""))):
        raise ValueError("Source must be a full revision or release tag")
    args = []
    for key, value in raw.items():
        if key.endswith("__command"):
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or not isinstance(value, (str, bool, int, float)):
            raise ValueError("Invalid metadata key/value")
        value = str(value).lower() if isinstance(value, bool) else str(value)
        if "\n" in value or "\r" in value:
            raise ValueError("Multiline build argument")
        args.append(f"{key.upper()}={value}")
    digest = raw.get("upstream_digest_" + arch, "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Missing pinned upstream architecture digest")
    version = str(raw.get("version", "---"))
    stats = {"app": repository.split("/")[1], "image": repository + ":" + branch,
             "revision": revision[:7], "version": version}
    args.extend(["PACKAGE_VERSION=" + branch + "-" + revision[:7],
                 "IMAGE_STATS=" + base64.b64encode(json.dumps(stats).encode()).decode()])
    tags = [branch, branch + "-" + revision[:7]]
    if raw.get("version"):
        tags.append(branch + "-" + re.sub(r"[^A-Za-z0-9_.-]", "-", version))
        match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version)
        if match:
            parts = match.groups()
            tags.extend(branch + "-v" + ".".join(parts[:n]) for n in (1, 2, 3))
    if raw.get("latest") is True:
        tags.append("latest")
    if any(len(tag) > 128 for tag in tags):
        raise ValueError("Image tag too long")
    return {"repository": repository, "branch": branch, "revision": revision,
            "arch": arch, "tags": list(dict.fromkeys(tags)), "build_args": args}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("root", "repository", "branch", "revision", "arch", "output"):
        parser.add_argument("--" + name, required=True)
    opts = parser.parse_args()
    result = metadata(Path(opts.root), opts.repository, opts.branch, opts.revision, opts.arch)
    out = Path(opts.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "metadata.json").write_text(json.dumps(result, indent=2) + "\n")
    (out / "build-args.txt").write_text("\n".join(result["build_args"]) + "\n")
