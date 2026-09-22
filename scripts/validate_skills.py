#!/usr/bin/env python3
"""Validate skill frontmatter before it reaches a provider.

Checks every SKILLS/*/SKILL.md and the SKILL.md embedded in every cowork/*.skill
package, because the packages carry their own copy of the frontmatter and a fix to
the source alone leaves them failing at install time.

By default it reads the staged (index) content, so a pre-commit hook checks what is
actually about to be committed. --worktree reads the files on disk instead.
"""
import argparse, io, re, subprocess, sys, zipfile

MAX_DESC = 1024
XML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)


def load_description(fm_text):
    """Return the folded description value. Falls back if pyyaml is absent."""
    try:
        import yaml
        return (yaml.safe_load(fm_text) or {}).get("description")
    except ImportError:
        # Three scalar styles appear in this repo: "description: >", "description: >-"
        # and a plain one-line scalar. Fold all three the way YAML would.
        # The frontmatter capture has no trailing newline, so add one or the
        # last line of the block is dropped.
        m = re.search(r"^description:[ \t]*(.*)\n((?:[ \t]+.*\n|\n)*)", fm_text + "\n", re.M)
        if not m:
            return None
        first = m.group(1).strip()
        rest = " ".join(l.strip() for l in m.group(2).splitlines() if l.strip())
        if first in (">", ">-", ">+", "|", "|-", "|+"):
            return rest
        return (first + " " + rest).strip()


def check(label, text, errors):
    m = FRONTMATTER.match(text)
    if not m:
        errors.append("%s: no YAML frontmatter" % label)
        return
    try:
        desc = load_description(m.group(1))
    except Exception as exc:
        errors.append("%s: frontmatter does not parse (%s)" % (label, exc))
        return
    if not desc:
        errors.append("%s: frontmatter has no 'description'" % label)
        return
    desc = desc.strip()
    if len(desc) > MAX_DESC:
        errors.append("%s: field 'description' in SKILL.md must be at most %d characters "
                      "(is %d, over by %d)" % (label, MAX_DESC, len(desc), len(desc) - MAX_DESC))
    tags = sorted(set(XML_TAG.findall(desc)))
    if tags:
        errors.append("%s: SKILL.md description cannot contain XML tags (found %s)"
                      % (label, ", ".join(tags)))


def tracked_files():
    out = subprocess.check_output(["git", "ls-files", "-z"]).decode("utf-8")
    return [p for p in out.split("\0") if p]


def read(path, from_index):
    if from_index:
        return subprocess.check_output(["git", "show", ":%s" % path])
    with open(path, "rb") as fh:
        return fh.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worktree", action="store_true",
                    help="validate files on disk instead of the staged content")
    args = ap.parse_args()
    from_index = not args.worktree

    errors, n = [], 0
    for path in tracked_files():
        if path.endswith("/SKILL.md") and path.startswith("SKILLS/"):
            try:
                blob = read(path, from_index)
            except subprocess.CalledProcessError:
                continue  # staged for deletion
            check(path, blob.decode("utf-8"), errors)
            n += 1
        elif path.endswith(".skill"):
            try:
                blob = read(path, from_index)
            except subprocess.CalledProcessError:
                continue
            try:
                z = zipfile.ZipFile(io.BytesIO(blob))
            except zipfile.BadZipFile:
                errors.append("%s: not a readable zip archive" % path)
                continue
            members = [m for m in z.namelist() if m.endswith("SKILL.md")]
            if not members:
                errors.append("%s: package contains no SKILL.md" % path)
            for m in members:
                check("%s (%s)" % (path, m), z.read(m).decode("utf-8"), errors)
                n += 1

    if errors:
        sys.stderr.write("skill validation failed:\n\n")
        for e in errors:
            sys.stderr.write("  %s\n" % e)
        sys.stderr.write("\n%d error(s) across %d SKILL.md file(s).\n" % (len(errors), n))
        sys.stderr.write("Remember: cowork/*.skill packages embed their own frontmatter -- "
                         "rebuild the package after editing the source.\n")
        return 1
    print("skill validation passed: %d SKILL.md file(s) checked" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
