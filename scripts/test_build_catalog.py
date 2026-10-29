import hashlib
import io
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from build_catalog import build_catalog


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "dist"
        self.revision = "a" * 40

    def skill(self, name="example", root="SKILLS", aliases=""):
        folder = self.root / root / name
        folder.mkdir(parents=True)
        metadata = f'\nmetadata:\n  aliases: "{aliases}"' if aliases else ""
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\nversion: 1.2.3\ndescription: >-\n  Example skill\n  with folded YAML.{metadata}\n---\n\nInstructions.\n"
        )
        return folder

    def build(self, output=None):
        return build_catalog(self.root, output or self.output, "SecurityDo/ingext_skills",
                             self.revision, "2026-10-29T12:00:00-04:00")

    def test_catalog_and_downloads_cover_both_roots(self):
        folder = self.skill()
        script = folder / "scripts" / "run.py"
        script.parent.mkdir()
        script.write_text("print('hello')\n")
        script.chmod(0o755)
        asset = folder / "assets" / "image.bin"
        asset.parent.mkdir()
        asset.write_bytes(bytes(range(256)))
        self.skill("report-example", "reports", "Legacy_Report")
        catalog = self.build()
        self.assertEqual(catalog, json.loads((self.output / "catalog.json").read_text()))
        self.assertEqual([s["id"] for s in catalog["skills"]], ["example", "report-example"])
        self.assertEqual(catalog["skills"][1]["category"], "report")
        self.assertEqual(catalog["skills"][1]["aliases"], ["Legacy_Report"])
        for entry in catalog["skills"]:
            download = entry["download"]
            content = (self.output / download["filename"]).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), download["sha256"])
            self.assertEqual(len(content), download["sizeBytes"])
            self.assertEqual(download["url"], f"https://github.com/SecurityDo/ingext_skills/releases/download/catalog-{self.revision}/{entry['id']}.skill")
            self.assertIn(self.revision, entry["sourceUrl"])
            source = self.root / entry["sourcePath"]
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                expected = {f"{entry['id']}/{p.relative_to(source).as_posix()}": p.read_bytes()
                            for p in source.rglob("*") if p.is_file()}
                self.assertEqual({n: archive.read(n) for n in archive.namelist()}, expected)
                self.assertEqual(entry["fileCount"], len(expected))
                if entry["id"] == "example":
                    mode = archive.getinfo("example/scripts/run.py").external_attr >> 16
                    self.assertTrue(mode & stat.S_IXUSR)

    def test_output_is_reproducible_despite_source_mtime(self):
        folder = self.skill()
        self.build()
        first = {p.name: p.read_bytes() for p in self.output.iterdir()}
        import os
        os.utime(folder / "SKILL.md", (1234567890, 1234567890))
        second_output = self.root / "dist2"
        self.build(second_output)
        self.assertEqual(first, {p.name: p.read_bytes() for p in second_output.iterdir()})

    def test_source_content_changes_package_hash(self):
        folder = self.skill()
        first = self.build()["skills"][0]["download"]["sha256"]
        with (folder / "SKILL.md").open("a") as stream:
            stream.write("Changed instructions.\n")
        second = self.build(self.root / "dist2")["skills"][0]["download"]["sha256"]
        self.assertNotEqual(first, second)

    def test_stale_checked_in_package_is_not_release_input(self):
        self.skill()
        (self.root / "cowork").mkdir()
        (self.root / "cowork/example.skill").write_bytes(b"stale package")
        self.build()
        with zipfile.ZipFile(self.output / "example.skill") as archive:
            self.assertIn(b"version: 1.2.3", archive.read("example/SKILL.md"))

    def test_duplicate_ids_fail_before_writing(self):
        self.skill()
        self.skill(root="reports")
        with self.assertRaisesRegex(ValueError, "duplicate skill ID"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_alias_collision_fails(self):
        self.skill("first", aliases="second")
        self.skill("second")
        with self.assertRaisesRegex(ValueError, "duplicate skill ID or alias"):
            self.build()

    def test_invalid_name_and_metadata_fail(self):
        folder = self.skill("Invalid_Name")
        with self.assertRaisesRegex(ValueError, "name must match"):
            self.build()
        (folder / "SKILL.md").write_text("---\nname: example\nversion: 1.0.0\ndescription: [not, a, string]\n---\n")
        with self.assertRaisesRegex(ValueError, "description must be"):
            self.build()

    def test_symlinks_are_rejected(self):
        folder = self.skill()
        outside = self.root / "outside.txt"
        outside.write_text("not a skill resource")
        (folder / "reference.txt").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            self.build()

    def test_local_cache_files_are_excluded(self):
        folder = self.skill()
        (folder / "__pycache__").mkdir()
        (folder / "__pycache__/run.cpython.pyc").write_bytes(b"cache")
        (folder / ".DS_Store").write_bytes(b"cache")
        self.assertEqual(self.build()["skills"][0]["fileCount"], 1)

    def test_existing_output_is_not_overwritten(self):
        self.skill()
        self.build()
        with self.assertRaisesRegex(ValueError, "empty directory"):
            self.build()

    def test_invalid_revision_and_empty_sources_fail(self):
        with self.assertRaisesRegex(ValueError, "no source skills"):
            self.build()
        self.skill()
        self.revision = "master"
        with self.assertRaisesRegex(ValueError, "full lowercase Git commit SHA"):
            self.build()


if __name__ == "__main__":
    unittest.main()
