# SPDX-License-Identifier: GPL-3.0-only
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from image_metadata import metadata


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = {"upstream_digest_amd64": "sha256:" + "a" * 64,
                     "upstream_digest_arm64": "sha256:" + "b" * 64,
                     "source_sha256": "d" * 64, "version": "1.2.3", "latest": True,
                     "version__command": "touch /must-not-run"}

    def build(self, **kwargs):
        (self.root / "meta.json").write_text(json.dumps(self.data))
        return metadata(self.root, kwargs.get("repository", "edbfi/zondarr-docker"),
                        kwargs.get("branch", "release"), "c" * 40, "amd64")

    def test_update_commands_are_data_only(self):
        result = self.build()
        self.assertFalse(any("__COMMAND" in v for v in result["build_args"]))
        self.assertIn("release-v1.2.3", result["tags"])
        self.assertIn("latest", result["tags"])

    def test_missing_source_checksum_rejected(self):
        del self.data["source_sha256"]
        with self.assertRaises(ValueError): self.build()

    def test_floating_source_rejected(self):
        self.data["version"] = "main"
        with self.assertRaises(ValueError): self.build()

    def test_missing_digest_rejected(self):
        del self.data["upstream_digest_amd64"]
        with self.assertRaises(ValueError): self.build()

    def test_other_owner_rejected(self):
        with self.assertRaises(ValueError): self.build(repository="upstream/image")

    def test_injected_tag_rejected(self):
        with self.assertRaises(ValueError): self.build(branch="x;false")

    def test_multiline_argument_rejected(self):
        self.data["version"] = "1\nINJECTED=1"
        with self.assertRaises(ValueError): self.build()


if __name__ == "__main__":
    unittest.main()
