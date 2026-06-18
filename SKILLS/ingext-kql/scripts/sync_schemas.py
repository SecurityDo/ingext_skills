#!/usr/bin/env python3
"""
Sync the embedded schema knowledge base for the ingext-kql skill.

Source of truth: the `ingext_schema` repo. This script walks
`<repo>/datatypes/*/` and copies, for every data type:

  - info_*.yaml   -> references/schemas/<TableName>/info.yaml
  - queries/*.yaml -> references/schemas/<TableName>/queries/<name>.yaml

The <TableName> is the KQL identifier returned by the `list_data_tables`
MCP tool. It is taken from the `schema:` field of each info_*.yaml and the
`datatype:` field of each query yaml -- those are the join keys, NOT the
folder name (one datatype folder, e.g. AzureAudit, can back several tables).

It then writes references/schemas/manifest.json mapping every table name to
its schema doc, description, and example queries, so the skill can resolve a
table discovered at runtime to its embedded schema + examples.

Usage:
    python3 scripts/sync_schemas.py --repo /path/to/ingext_schema
    python3 scripts/sync_schemas.py --repo ../ingext_schema --check

--check exits non-zero if the embedded KB is out of date (for CI), without
writing anything.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import sys
import tempfile

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "PyYAML is required. Install with: pip install pyyaml --break-system-packages\n"
    )
    sys.exit(2)


SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_yaml(path):
    """Parse a YAML file, tolerating odd formatting by returning {} on failure."""
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return {}


def scalar(value):
    return value.strip() if isinstance(value, str) else value


def field_via_regex(path, field):
    """Fallback extraction of a top-level scalar field if YAML parse fails."""
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^%s:\s*(.+)$" % re.escape(field), line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    return None


def discover(repo):
    """Return {tableName: {datatype, description, info_src, queries:[...] }}."""
    datatypes_dir = os.path.join(repo, "datatypes")
    if not os.path.isdir(datatypes_dir):
        sys.stderr.write("No datatypes/ folder under %s\n" % repo)
        sys.exit(2)

    tables = {}

    # First pass: info_*.yaml -> table schema docs.
    for folder in sorted(os.listdir(datatypes_dir)):
        dpath = os.path.join(datatypes_dir, folder)
        if not os.path.isdir(dpath):
            continue
        for fname in sorted(os.listdir(dpath)):
            if not (fname.startswith("info_") and fname.endswith(".yaml")):
                continue
            ipath = os.path.join(dpath, fname)
            data = load_yaml(ipath)
            table = scalar(data.get("schema")) or field_via_regex(ipath, "schema")
            if not table:
                sys.stderr.write("WARN: no schema: in %s, skipping\n" % ipath)
                continue
            desc = scalar(data.get("description")) or ""
            nfields = len(data.get("fields") or [])
            tables.setdefault(table, _blank(table))
            entry = tables[table]
            entry["datatype"] = folder
            entry["description"] = desc
            entry["field_count"] = nfields
            entry["_info_src"] = ipath

    # Second pass: queries/*.yaml -> example queries keyed by datatype.
    for folder in sorted(os.listdir(datatypes_dir)):
        qdir = os.path.join(datatypes_dir, folder, "queries")
        if not os.path.isdir(qdir):
            continue
        for fname in sorted(os.listdir(qdir)):
            if not fname.endswith(".yaml"):
                continue
            qpath = os.path.join(qdir, fname)
            data = load_yaml(qpath)
            table = scalar(data.get("datatype")) or field_via_regex(qpath, "datatype")
            if not table:
                sys.stderr.write("WARN: no datatype: in %s, skipping\n" % qpath)
                continue
            qdesc = scalar(data.get("description")) or ""
            # collapse multi-line descriptions to a one-line summary
            qdesc = " ".join(qdesc.split())
            if len(qdesc) > 200:
                qdesc = qdesc[:197] + "..."
            tags = data.get("tags") or []
            tables.setdefault(table, _blank(table))
            tables[table]["queries"].append(
                {
                    "file": "queries/%s" % fname,
                    "description": qdesc,
                    "tags": tags,
                    "_src": qpath,
                }
            )

    return tables


def _blank(table):
    return {
        "table": table,
        "datatype": None,
        "description": "",
        "field_count": 0,
        "_info_src": None,
        "queries": [],
    }


def build_tree(tables, dest_root):
    """Write schema folders + manifest into dest_root. Returns manifest dict."""
    os.makedirs(dest_root, exist_ok=True)
    manifest_tables = {}

    for table in sorted(tables):
        entry = tables[table]
        tdir = os.path.join(dest_root, table)
        os.makedirs(tdir, exist_ok=True)

        info_rel = None
        if entry["_info_src"]:
            shutil.copyfile(entry["_info_src"], os.path.join(tdir, "info.yaml"))
            info_rel = "schemas/%s/info.yaml" % table

        query_records = []
        if entry["queries"]:
            os.makedirs(os.path.join(tdir, "queries"), exist_ok=True)
            for q in sorted(entry["queries"], key=lambda x: x["file"]):
                fname = os.path.basename(q["file"])
                shutil.copyfile(q["_src"], os.path.join(tdir, "queries", fname))
                query_records.append(
                    {
                        "file": "schemas/%s/queries/%s" % (table, fname),
                        "description": q["description"],
                        "tags": q["tags"],
                    }
                )

        manifest_tables[table] = {
            "datatype": entry["datatype"],
            "description": entry["description"],
            "field_count": entry["field_count"],
            "info": info_rel,
            "queries": query_records,
        }

    manifest = {
        "_comment": (
            "Auto-generated by scripts/sync_schemas.py from the ingext_schema repo. "
            "Do not edit by hand. Keys are KQL table names as returned by list_data_tables."
        ),
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "table_count": len(manifest_tables),
        "tables": manifest_tables,
    }
    with open(os.path.join(dest_root, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return manifest


def snapshot(root):
    """Map of relpath -> bytes for every file under root (manifest minus its timestamp)."""
    out = {}
    if not os.path.isdir(root):
        return out
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, root)
            with open(full, "rb") as fh:
                data = fh.read()
            if rel == "manifest.json":
                obj = json.loads(data.decode("utf-8"))
                obj.pop("generated_at", None)
                data = json.dumps(obj, indent=2, sort_keys=True).encode("utf-8")
            out[rel] = data
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, help="Path to the ingext_schema repo")
    ap.add_argument(
        "--skill", default=SKILL_DIR, help="Path to the ingext-kql skill dir"
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Verify the embedded KB is up to date; do not write. Exit 1 if stale.",
    )
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    dest = os.path.join(os.path.abspath(args.skill), "references", "schemas")

    tables = discover(repo)

    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dest = os.path.join(tmp, "schemas")
            build_tree(tables, tmp_dest)
            if snapshot(tmp_dest) != snapshot(dest):
                sys.stderr.write(
                    "Embedded schema KB is OUT OF DATE. Run: "
                    "python3 scripts/sync_schemas.py --repo %s\n" % args.repo
                )
                sys.exit(1)
        print("Embedded schema KB is up to date (%d tables)." % len(tables))
        return

    if os.path.isdir(dest):
        shutil.rmtree(dest)
    manifest = build_tree(tables, dest)
    print(
        "Synced %d tables into %s"
        % (manifest["table_count"], os.path.relpath(dest, args.skill))
    )
    for t in sorted(manifest["tables"]):
        info = manifest["tables"][t]
        print(
            "  %-28s fields=%-4s queries=%-2d (%s)"
            % (t, info["field_count"], len(info["queries"]), info["datatype"])
        )


if __name__ == "__main__":
    main()
