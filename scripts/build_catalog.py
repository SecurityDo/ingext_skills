#!/usr/bin/env python3
"""Build a versioned catalog and reproducible Cowork archives from source skills."""
import argparse
import hashlib
import io
import json
import re
import stat
import subprocess
import zipfile
from pathlib import Path

import yaml

SOURCE_ROOTS = ("SKILLS", "reports")
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
REVISION = re.compile(r"[0-9a-f]{40}")
REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*")


def source_files(folder):
    """Ignore local build debris; never follow symlinks into another directory."""
    files = []
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if "__pycache__" in relative.parts or path.name == ".DS_Store" or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise ValueError(f"{path}: symlinks are not supported in skill packages")
        if path.is_file():
            files.append(path)
    return files


def read_metadata(manifest):
    if manifest.is_symlink() or manifest.parent.is_symlink() or manifest.parent.parent.is_symlink():
        raise ValueError(f"{manifest}: symlinks are not supported in skill packages")
    text = manifest.read_text(encoding="utf-8")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, re.S)
    if not match:
        raise ValueError(f"{manifest}: missing YAML frontmatter")
    data = yaml.safe_load(match[1])
    if not isinstance(data, dict):
        raise ValueError(f"{manifest}: frontmatter must be a mapping")
    for field in ("name", "description", "version"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"{manifest}: {field} must be a non-empty string")
    name = data["name"]
    if not NAME.fullmatch(name) or len(name) > 64 or name != manifest.parent.name:
        raise ValueError(f"{manifest}: name must match its folder and use lowercase letters, digits and hyphens")
    if not VERSION.fullmatch(data["version"]):
        raise ValueError(f"{manifest}: version must be a semantic version string")
    description = data["description"].strip()
    if len(description) > 1024 or re.search(r"</?[A-Za-z][^>]*>", description):
        raise ValueError(f"{manifest}: description exceeds 1024 characters or contains XML tags")
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError(f"{manifest}: metadata must be a mapping")
    aliases = metadata.get("aliases", "")
    if not isinstance(aliases, str):
        raise ValueError(f"{manifest}: metadata.aliases must be a comma-separated string")
    aliases = [alias.strip() for alias in aliases.split(",") if alias.strip()]
    if len(set(aliases)) != len(aliases):
        raise ValueError(f"{manifest}: duplicate aliases")
    return {"id": name, "name": name, "version": data["version"],
            "description": description, "aliases": sorted(aliases)}


def package_skill(folder):
    """Normalize ZIP order, timestamp and permissions; retain executable scripts."""
    stream = io.BytesIO()
    files = source_files(folder)
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            info = zipfile.ZipInfo(f"{folder.name}/{path.relative_to(folder).as_posix()}", (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return stream.getvalue(), len(files)


def build_catalog(root, output, repository, revision, committed_at):
    root, output = Path(root).resolve(), Path(output).resolve()
    if not REPOSITORY.fullmatch(repository) or repository.split("/")[-1] in (".", ".."):
        raise ValueError("repository must be owner/repo")
    if not REVISION.fullmatch(revision):
        raise ValueError("revision must be a full lowercase Git commit SHA")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"{output}: output must be absent or an empty directory")
    for source_root in SOURCE_ROOTS:
        source = root / source_root
        if output == source or source in output.parents:
            raise ValueError("output must be outside source skill directories")
    tag = f"catalog-{revision}"
    base = f"https://github.com/{repository}"
    manifests = sorted(p for name in SOURCE_ROOTS for p in (root / name).glob("*/SKILL.md"))
    if not manifests:
        raise ValueError("no source skills found")
    entries, packages, identifiers = [], {}, set()
    for manifest in manifests:
        entry = read_metadata(manifest)
        for identifier in (entry["id"], *entry["aliases"]):
            if identifier in identifiers:
                raise ValueError(f"{manifest}: duplicate skill ID or alias {identifier!r}")
            identifiers.add(identifier)
        content, count = package_skill(manifest.parent)
        filename = f"{entry['id']}.skill"
        source_path = manifest.parent.relative_to(root).as_posix()
        entry.update({
            "category": "report" if source_path.startswith("reports/") else "skill",
            "sourcePath": source_path,
            "sourceUrl": f"{base}/blob/{revision}/{source_path}/SKILL.md",
            "fileCount": count,
            "download": {
                "filename": filename,
                "url": f"{base}/releases/download/{tag}/{filename}",
                "format": "zip",
                "sha256": hashlib.sha256(content).hexdigest(),
                "sizeBytes": len(content),
            },
        })
        entries.append(entry)
        packages[filename] = content
    entries.sort(key=lambda entry: entry["id"])
    catalog = {"schemaVersion": 1, "repositoryUrl": base, "sourceRevision": revision,
               "sourceCommittedAt": committed_at, "releaseTag": tag,
               "skills": entries}
    # Validate every skill before writing artifacts, so invalid input cannot yield a partial catalog.
    output.mkdir(parents=True, exist_ok=True)
    for filename, content in packages.items():
        (output / filename).write_bytes(content)
    (output / "catalog.json").write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--repository", default="SecurityDo/ingext_skills")
    args = parser.parse_args()
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.root, text=True).strip()
        committed_at = subprocess.check_output(["git", "show", "-s", "--format=%cI", "HEAD"], cwd=args.root, text=True).strip()
        # The revision in public URLs must identify the actual input, not uncommitted edits.
        dirty = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all", "--", *SOURCE_ROOTS], cwd=args.root, text=True)
        if dirty:
            raise ValueError("commit source skill changes before generating a release catalog")
        catalog = build_catalog(args.root, args.output, args.repository, revision, committed_at)
    except (ValueError, OSError, subprocess.CalledProcessError, yaml.YAMLError) as exc:
        parser.exit(1, f"catalog build failed: {exc}\n")
    print(f"Built {len(catalog['skills'])} packages and catalog.json in {args.output} ({catalog['releaseTag']})")


if __name__ == "__main__":
    main()
