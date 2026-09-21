#!/usr/bin/env python3
"""Get real JSON out of the ingext CLI.

Most `ingext` subcommands print a human summary and throw the response away.
The full JSON body is only ever visible in the debug log (`-l debug`), where the
client pretty-prints it into a Go slog `msg="..."` field. This module runs the
command and digs that body back out.

    # run a command and capture its response body
    python3 ingext_json.py run summary.json -- \
        eventwatch search_summary --query user@corp.com --from 1787246734000 --to 1789838734000

    # run a KQL file, and PROVE which tenant answered
    python3 ingext_json.py kql out.json query.kql --expect contoso

    # or extract from a debug log you already have
    python3 ingext_json.py extract debug.log summary.json

Every mode prints the resolved siteURL to stderr, and `--expect <substring>`
turns that into an assertion that exits non-zero on a mismatch.

Why that matters: ~/.ingext/config.yaml is SHARED GLOBAL STATE. `ingext config
use` mutates it for every session on the machine, so a concurrent session can
move your target out from under you mid-run. Reading `config view` before and
after is weaker than this, because a flip and flip-back inside the call would
pass both reads. The siteURL in the call's own debug log is what actually
answered.
"""

import json
import re
import subprocess
import sys


def extract(log_path):
    """Return the last JSON response body found in an `ingext -l debug` log.

    The client logs the body twice: once raw inside the chunked HTTP dump, once
    pretty-printed on its own line. Only the pretty-printed line parses cleanly,
    so that is the one we take. Both are Go-quoted, which is JSON-compatible.
    """
    raw = open(log_path, "rb").read().decode("utf-8", "replace")
    best = None
    for line in raw.split("\n"):
        i = line.find('msg="{')
        if i < 0:
            continue
        quoted = line[i + 4:]
        if not quoted.endswith('"'):
            continue
        try:
            body = json.loads(json.loads(quoted))
        except Exception:
            continue
        if isinstance(body, dict) and "response" in body:
            best = body
    return best


AUTH_RE = re.compile(rb"(Authorization:\s*Bearer\s+)[^\\\r\n\"]+")


def _redact(blob):
    """`-l debug` dumps the request headers, including the bearer token.

    The log is written to disk and read back, so the credential must never
    reach the file. Only `run` needs debug at all -- `kql` uses `-l info`.
    """
    return AUTH_RE.sub(rb"\1[REDACTED]", blob)


def run(args, log_path):
    """Run `ingext -l debug <args>`, tee a REDACTED log, return the parsed body."""
    proc = subprocess.run(
        ["ingext", "-l", "debug"] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    with open(log_path, "wb") as fh:
        fh.write(_redact(proc.stdout))
    return extract(log_path)


def run_kql(query_path, out_path, log_path):
    """`ingext kql` writes its own clean JSON; we only want the log for siteURL."""
    proc = subprocess.run(
        ["ingext", "-l", "info", "kql", "@" + query_path, "--output", out_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    with open(log_path, "wb") as fh:
        fh.write(proc.stdout)
    return proc.returncode


def site_url(log_path):
    """The tenant the command actually reached. Check this before trusting a result."""
    for line in open(log_path, "r", errors="replace"):
        if "initialized ingext client" in line and "siteURL=" in line:
            return line.split("siteURL=")[1].strip()
    return None


def check_site(log_path, expect):
    """Print what actually answered; assert it if an expectation was given."""
    url = site_url(log_path)
    sys.stderr.write("site: {}\n".format(url or "UNKNOWN"))
    if expect is None:
        return
    if url is None:
        sys.exit("could not determine the site from {} -- refusing to trust the "
                 "result".format(log_path))
    if expect not in url:
        sys.exit("WRONG TENANT: expected {!r} in the site, got {}. The shared "
                 "~/.ingext/config.yaml may have been changed by another "
                 "session mid-run.".format(expect, url))


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    mode = argv[1]
    expect = None
    if "--expect" in argv:
        i = argv.index("--expect")
        expect = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]

    if mode == "kql":
        out_path, query_path = argv[2], argv[3]
        log_path = out_path + ".log"
        rc = run_kql(query_path, out_path, log_path)
        check_site(log_path, expect)
        if rc != 0:
            sys.exit("ingext kql exited {} -- see {}".format(rc, log_path))
        sys.stderr.write("wrote {}\n".format(out_path))
        return

    if mode == "extract":
        log_path, out_path = argv[2], argv[3]
        body = extract(log_path)
    elif mode == "run":
        out_path = argv[2]
        if "--" not in argv:
            sys.exit("run: put the ingext arguments after `--`")
        args = argv[argv.index("--") + 1:]
        log_path = out_path + ".log"
        body = run(args, log_path)
    else:
        sys.exit(__doc__)

    check_site(log_path, expect)
    if body is None:
        sys.exit("no JSON response body in {} -- check the log for an auth or "
                 "targeting error".format(log_path))

    with open(out_path, "w") as fh:
        json.dump(body, fh, indent=2)
    hits = body.get("response", {}).get("hits", {})
    total = hits.get("total", {})
    sys.stderr.write("wrote {} ({} hits)\n".format(
        out_path, total.get("value") if isinstance(total, dict) else "?"))


if __name__ == "__main__":
    main(sys.argv)
