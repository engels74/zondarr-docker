# SPDX-License-Identifier: GPL-3.0-only
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from publish import validate, validate_publication


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for arch in ("amd64", "arm64"):
            folder = self.root / ("alpinevpn-" + arch)
            folder.mkdir()
            record = {"repository": "edbfi/base-image", "branch": "alpinevpn", "arch": arch,
                      "revision": "a" * 40, "tags": ["alpinevpn"]}
            (folder / "metadata.json").write_text(json.dumps(record))
            for name in ("image.tar", "result.txt", "packages.txt"):
                (folder / name).write_text("PASS: fixture" if name == "result.txt" else "fixture")
            (folder / "runtime-result.json").write_text(json.dumps({"passed": True, "architecture": arch}))

    def validate(self):
        return validate(self.root, "edbfi/base-image", "alpinevpn")

    def test_complete_pair(self):
        self.assertEqual(self.validate()["revision"], "a" * 40)

    def test_failed_runtime_rejected(self):
        (self.root / "alpinevpn-amd64/runtime-result.json").write_text(json.dumps({"passed": False, "architecture": "amd64"}))
        with self.assertRaises(ValueError): self.validate()

    def test_failed_smoke_rejected(self):
        (self.root / "alpinevpn-amd64/result.txt").write_text("FAIL")
        with self.assertRaises(ValueError): self.validate()

    def test_missing_smoke_evidence(self):
        (self.root / "alpinevpn-amd64/result.txt").unlink()
        with self.assertRaises(ValueError): self.validate()

    def test_mixed_revisions(self):
        path = self.root / "alpinevpn-arm64/metadata.json"
        record = json.loads(path.read_text()); record["revision"] = "b" * 40
        path.write_text(json.dumps(record))
        with self.assertRaises(ValueError): self.validate()

    def test_other_repository(self):
        path = self.root / "alpinevpn-arm64/metadata.json"
        record = json.loads(path.read_text()); record["repository"] = "other/image"
        path.write_text(json.dumps(record))
        with self.assertRaises(ValueError): self.validate()


class PublicationGateTests(unittest.TestCase):
    def setUp(self):
        self.sha = "a" * 40
        self.live = {"commit": {"sha": self.sha}, "protected": False}
        self.runs = [{"head_sha": self.sha, "head_branch": "nightly", "status": "completed", "conclusion": "success"}]

    def check(self, ref="refs/heads/nightly", sha=None):
        validate_publication({"revision": self.sha}, "nightly", self.live, self.runs, ref, sha or self.sha)

    def test_unprotected_reviewed_channel_allowed(self):
        self.check()

    def test_other_workflow_branch_rejected(self):
        with self.assertRaises(ValueError): self.check(ref="refs/heads/arbitrary")

    def test_changed_live_head_rejected(self):
        self.live["commit"]["sha"] = "b" * 40
        with self.assertRaises(ValueError): self.check()

    def test_stale_workflow_rejected(self):
        with self.assertRaises(ValueError): self.check(sha="b" * 40)

    def test_missing_final_ci_rejected(self):
        self.runs = []
        with self.assertRaises(ValueError): self.check()

    def test_failed_final_ci_rejected(self):
        self.runs[0]["conclusion"] = "failure"
        with self.assertRaises(ValueError): self.check()
