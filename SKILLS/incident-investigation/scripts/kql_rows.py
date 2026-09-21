#!/usr/bin/env python3
"""Read an `ingext kql --output` file as rows, deduplicated.

    ingext kql @q.kql --output signin.json
    python3 kql_rows.py signin.json                    # TSV to stdout
    python3 kql_rows.py signin.json --count IPAddress  # value counts for one column
    python3 kql_rows.py signin.json --json             # list of dicts

The datalake returns the same event more than once on these indexes -- the same
sign-in appears two or three times with identical field values. Any hand count
of "failed logins" off the raw rows is inflated. This dedupes on the whole row
before printing, and reports how many duplicates it dropped.
"""

import json
import sys
from collections import Counter


def load(path, dedupe=True):
    body = json.load(open(path))
    table = body["data"]["Tables"][0]
    cols = [c["ColumnName"] for c in table["Columns"]]
    rows = [dict(zip(cols, r)) for r in table["Rows"]]
    raw = len(rows)
    if dedupe:
        seen, out = set(), []
        for r in rows:
            k = json.dumps(r, sort_keys=True, default=str)
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        rows = out
    return cols, rows, raw


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    path = argv[1]
    rest = argv[2:]
    cols, rows, raw = load(path, dedupe="--raw" not in rest)

    if raw != len(rows):
        sys.stderr.write("{} rows -> {} after dedupe ({} duplicates dropped)\n"
                         .format(raw, len(rows), raw - len(rows)))
    else:
        sys.stderr.write("{} rows\n".format(len(rows)))

    if "--count" in rest:
        col = rest[rest.index("--count") + 1]
        for val, n in Counter(r.get(col) for r in rows).most_common():
            print("{:>7}  {}".format(n, val))
        return

    if "--json" in rest:
        json.dump(rows, sys.stdout, indent=2, default=str)
        return

    print("\t".join(cols))
    for r in rows:
        print("\t".join(str(r.get(c, "")).replace("\t", " ") for c in cols))


if __name__ == "__main__":
    main(sys.argv)
