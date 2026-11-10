#!/usr/bin/env python3
"""Security agent deployment status from Fluency resource dumps.

  deployment_status.py fields --dumps DUMPS --resource RESOURCE
      Field paths in a downloaded dump, how often each is filled, and common values. Use it to
      choose the host / os / lastSeen / filter fields when adding a source.

  deployment_status.py check --dumps DUMPS [--sources FILE]
      Per-source health: records, records in scope, records active, snapshot hour, and which
      sources the report will leave out.

  deployment_status.py render --dumps DUMPS --work WORK --account ACCOUNT [...]
      Matches devices across sources and writes WORK/facts.json, WORK/devices.csv and the HTML report.

Dumps are the gzipped JSONL files issued by get_resource_dump_url, saved as
DUMPS/<resource>/<customer>.jsonl.gz. Every decision comes from the sources file.

A source whose dump is missing, unreadable, empty or unusable is left out of the run and the
report says so; the report is still produced from the sources that remain. Only an invalid sources
file stops the script. Python standard library only.
"""
import argparse
import csv
import gzip
import html
import ipaddress
import json
import re
import shutil
import sys
import zlib
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
FIELDS_REQUIRED = ("name", "resource", "host", "os", "lastSeen")
STATES = ("missing", "stale", "active")  # index is the state code
SNAPSHOT_MAX_AGE = timedelta(hours=48)
READ_ERRORS = (OSError, EOFError, zlib.error, UnicodeDecodeError, ValueError)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Device class from the OS string (and a source's device-type field). Network devices are matched as
# whole words; the other classes as case-insensitive substrings, first class wins.
NETWORK_CLASS, UNKNOWN_CLASS, DEFAULT_CLASS = "Network device", "Unknown", "Workstation"
NETWORK_WORDS = ["firewall", "router", "switch", "ups", "pdu", "power device", "printer", "camera", "voip",
                 "access point", "fortios", "fortigate", "fortinet", "apc", "aos", "cisco", "ios-xe", "nx-os",
                 "junos", "pan-os", "panos", "routeros", "mikrotik", "edgeos", "sonicos", "idrac", "ilo", "ipmi",
                 "netscaler", "big-ip", "meraki", "aruba", "ubiquiti", "unifi", "synology", "qnap"]
NETWORK_RE = re.compile(r"(?<![a-z0-9])(?:" + "|".join(map(re.escape, NETWORK_WORDS)) + r")(?![a-z0-9])")
COMPUTER_TYPE_RE = re.compile(r"server|workstation|desktop|laptop|computer|general purpose|virtual machine")
CLASS_KEYWORDS = [
    ("Server", ["server"]),
    ("Linux", ["linux", "ubuntu", "centos", "red hat", "rhel", "debian", "suse", "rocky", "alma"]),
]

# Device statuses. The first four are the agent-assessment scope that every total and percentage uses.
SCOPE_STATUSES = ("Compliant", "Missing agent", "Agent not reporting", "Not assessed")
STATUS_ORDER = {"Missing agent": 0, "Agent not reporting": 1, "Unidentified": 2, "Compliant": 3,
                "Not assessed": 4, "No agent expected": 5, "Inactive": 6}


def warn(msg):
    print(f"warning: {msg}", file=sys.stderr)


# ---- sources ---------------------------------------------------------------

def as_paths(v):
    if isinstance(v, str):
        return [v] if v else []
    if isinstance(v, list) and all(isinstance(x, str) and x for x in v):
        return list(v)
    return []


def load_config(path):
    try:
        cfg = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        sys.exit(f"cannot read the sources file {path}: {e}")
    sources = cfg.get("sources") if isinstance(cfg, dict) else None
    if not isinstance(sources, list) or not sources:
        sys.exit(f"sources file {path} needs a non-empty \"sources\" list")
    try:
        cfg["staleDays"] = int(cfg.get("staleDays", 30))
    except (TypeError, ValueError):
        sys.exit("sources file is invalid: staleDays must be a number of days")
    errors = []
    names = set()
    for i, s in enumerate(sources):
        if not isinstance(s, dict):
            errors.append(f"source #{i + 1}: must be an object")
            continue
        for f in FIELDS_REQUIRED:
            if not s.get(f):
                errors.append(f"source #{i + 1}: missing '{f}'")
        name = s.get("name", "")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", str(name)):
            errors.append(f"source #{i + 1}: name '{name}' must be a plain identifier")
        if name in names:
            errors.append(f"duplicate source name '{name}'")
        names.add(name)
        if not isinstance(s.get("filter", {}), dict):
            errors.append(f"source '{name}': filter must be an object of field: value")
        s["hostPaths"] = as_paths(s.get("host"))
        if s.get("host") and not s["hostPaths"]:
            errors.append(f"source '{name}': host must be a field path or a list of field paths")
        for f in ("key", "ip", "deviceId", "deviceType", "weaknesses", "confirmedWeaknesses"):
            if f in s and not (isinstance(s[f], str) and s[f]):
                errors.append(f"source '{name}': {f} must be a field path")
        try:
            s["staleDays"] = int(s.get("staleDays", cfg["staleDays"]))
        except (TypeError, ValueError):
            errors.append(f"source '{name}': staleDays must be a number of days")
        s.setdefault("label", name)
        s.setdefault("scope", s.get("resource", ""))
        s["required"] = bool(s.get("required"))
        s["discovery"] = bool(s.get("discovery"))
        s["matchIp"] = bool(s.get("matchIp"))
    authorities = [s for s in sources if isinstance(s, dict) and s.get("idAuthority")]
    if len(authorities) > 1:
        errors.append("at most one source can set idAuthority")
    if authorities and not authorities[0].get("deviceId"):
        errors.append(f"idAuthority source '{authorities[0]['name']}' needs a deviceId field")
    if not any(isinstance(s, dict) and s.get("required") for s in sources):
        errors.append("at least one source must be required")
    if errors:
        sys.exit("sources file is invalid:\n  " + "\n  ".join(errors))
    return cfg


def get_path(rec, path):
    """Dotted path into a record: "activeDirectory.computerDistinguishedName"."""
    cur = rec
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def matches(value, expected):
    """Filter semantics: a scalar must be equal, a list means any of, {"not": x} negates."""
    if isinstance(expected, list):
        return any(matches(value, e) for e in expected)
    if isinstance(expected, dict) and set(expected) == {"not"}:
        return not matches(value, expected["not"])
    if isinstance(expected, bool) and isinstance(value, str):
        return value.lower() == str(expected).lower()
    return value == expected


def in_scope(rec, flt):
    return all(matches(get_path(rec, k), v) for k, v in (flt or {}).items())


def to_dt(v):
    """Vendor timestamp (ISO string, any fraction length, or epoch milliseconds) -> aware UTC datetime."""
    if v in (None, "") or isinstance(v, bool):
        return None
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000, timezone.utc)
        m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$", str(v).strip())
        if not m:
            return None
        frac = "." + ((m.group(3) or ".")[1:] + "000000")[:6]
        tz = m.group(4) or "Z"
        tz = "+00:00" if tz == "Z" else (tz if ":" in tz else tz[:3] + ":" + tz[3:])
        return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}{frac}{tz}").astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def first_value(v):
    """A field value as one string. Lists, and lists serialized into a string ("['a', 'b']"), give
    their first non-empty element."""
    if isinstance(v, str):
        t = v.strip()
        if not (t.startswith("[") and t.endswith("]")):
            return t
        try:
            v = json.loads(t)
        except ValueError:
            v = re.findall(r"['\"]([^'\"]+)['\"]", t)
    if isinstance(v, (list, tuple)):
        return next((str(x).strip() for x in v if x not in (None, "") and str(x).strip()), "")
    return "" if v is None or isinstance(v, dict) else str(v).strip()


def is_ip(v):
    try:
        ipaddress.ip_address(v)
        return True
    except ValueError:
        return False


def norm_host(v):
    """Lowercase, drop the DNS suffix, drop the trailing "$" of AD computer accounts. An IP address
    is kept whole."""
    h = first_value(v).lower()
    if is_ip(h):
        return h
    return h.split(".")[0].strip().rstrip("$")


def norm_id(v):
    return first_value(v).lower()


def norm_ip(v):
    """A usable device IP, or "": loopback, link-local and unspecified addresses never identify a device."""
    try:
        a = ipaddress.ip_address(first_value(v))
    except ValueError:
        return ""
    return "" if a.is_loopback or a.is_link_local or a.is_unspecified or a.is_multicast else str(a)


# ---- dumps -----------------------------------------------------------------

def dump_files(dumps, resource):
    d = Path(dumps) / resource
    return sorted(set(d.glob("*.jsonl.gz")) | set(d.glob("*.jsonl")))


def dump_name(path):
    n = Path(path).name
    for suffix in (".jsonl.gz", ".jsonl"):
        if n.endswith(suffix):
            return n[:-len(suffix)]
    return n


def open_dump(path):
    return gzip.open(path, "rt", encoding="utf-8") if str(path).endswith(".gz") else open(path, encoding="utf-8")


def iter_lines(fh, resource, counter):
    """Yields (envelope, record) and counts unreadable lines in counter["bad"]. The vendor fields sit
    under "@<resource>" in each line."""
    for line in fh:
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            counter["bad"] += 1
            continue
        if not isinstance(doc, dict):
            counter["bad"] += 1
            continue
        rec = doc.get("@" + resource)
        if not isinstance(rec, dict):
            rec = {k: v for k, v in doc.items() if not k.startswith("@")}
        yield doc, rec


def scan_dump(path, resource, flt):
    """One dump file -> (records, in-scope records, snapshot hours, bad lines). Raises READ_ERRORS
    when the file can't be read through (a truncated or corrupt download)."""
    counter = Counter()
    total, scoped, snaps = 0, [], set()
    with open_dump(path) as fh:
        for doc, rec in iter_lines(fh, resource, counter):
            total += 1
            snaps.add(doc.get("@dayIndex"))
            if in_scope(rec, flt):
                scoped.append(rec)
    return total, scoped, snaps, counter["bad"]


def snapshot_time(day_index):
    try:
        return datetime.strptime(day_index, "%Y%m%d-%H").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def load_sources(cfg, dumps):
    """Reads each source's dumps: all records, the in-scope ones, and the snapshot hour. A dump whose
    snapshot is more than SNAPSHOT_MAX_AGE older than the newest dump of the same resource comes from
    a replaced or removed integration and is left out; so is a file that can't be read."""
    data = {}
    for s in cfg["sources"]:
        files, unreadable = [], []
        for f in dump_files(dumps, s["resource"]):
            try:
                total, scoped, snaps, bad = scan_dump(f, s["resource"], s.get("filter"))
            except READ_ERRORS as e:
                unreadable.append((f, f"{type(e).__name__}: {e}"[:160]))
                continue
            times = [t for t in map(snapshot_time, snaps) if t]
            files.append({"file": f, "records": total, "scoped": scoped, "bad": bad,
                          "snapshot": min(times) if times else None})
        newest = max((p["snapshot"] for p in files if p["snapshot"]), default=None)
        kept = [p for p in files if not (newest and p["snapshot"] and newest - p["snapshot"] > SNAPSHOT_MAX_AGE)]
        superseded = [p for p in files if p not in kept]
        times = [p["snapshot"] for p in kept if p["snapshot"]]
        data[s["name"]] = {
            "found": bool(files or unreadable),
            "files": [p["file"] for p in kept],
            "records": sum(p["records"] for p in kept),
            "scoped": [r for p in kept for r in p["scoped"]],
            "badLines": sum(p["bad"] for p in kept),
            "snapshot": min(times) if times else None,
            "superseded": [(p["file"], p["snapshot"]) for p in superseded],
            "unreadable": unreadable,
        }
    return data


def fmt_age(delta):
    hours = int(delta.total_seconds() // 3600)
    return f"{hours} hours" if hours < 72 else f"{hours // 24} days"


def source_health(cfg, data, now):
    """Per-source health. A problem means the source is left out of the run (usable: false); a warning
    keeps it."""
    rows = []
    for s in cfg["sources"]:
        d = data[s["name"]]
        cutoff = now - timedelta(days=s["staleDays"])
        seen = [to_dt(get_path(r, s["lastSeen"])) for r in d["scoped"]]
        active = sum(1 for t in seen if t and t > cutoff)
        if s.get("key"):
            hosts = {first_value(get_path(r, s["key"])).lower() for r in d["scoped"]} - {""}
        else:
            hosts = {next((h for h in (norm_host(get_path(r, p)) for p in s["hostPaths"]) if h), "")
                     for r in d["scoped"]} - {""}
        problems, warnings = [], []
        if not d["found"]:
            problems.append("no dump downloaded")
        elif not d["files"]:
            problems.append("no dump could be read: " + "; ".join(f"{dump_name(f)} ({e})" for f, e in d["unreadable"]))
        elif not d["records"]:
            problems.append("dump is empty")
        elif not d["scoped"]:
            problems.append("no records match the filter")
        elif not active:
            problems.append(f"no record seen in the last {s['staleDays']} days")
        elif not hosts:
            problems.append(f"'{s.get('key') or ', '.join(s['hostPaths'])}' is empty on every record")
        if d["files"]:
            for f, err in d["unreadable"]:
                warnings.append(f"left out {dump_name(f)}, which could not be read ({err})")
        for f, snap in d["superseded"]:
            warnings.append(f"left out {dump_name(f)} (snapshot {snap:%Y-%m-%d %H:00Z}): more than "
                            f"{int(SNAPSHOT_MAX_AGE.total_seconds() // 3600)} hours older than the newest "
                            f"{s['resource']} dump, so it is from a replaced or removed integration")
        if d["badLines"]:
            warnings.append(f"skipped {d['badLines']} unreadable lines")
        if d["snapshot"] and now - d["snapshot"] > SNAPSHOT_MAX_AGE:
            warnings.append(f"snapshot is {fmt_age(now - d['snapshot'])} old ({d['snapshot']:%Y-%m-%d %H:00Z})")
        rows.append({
            "source": s["name"], "label": s["label"], "resource": s["resource"], "required": s["required"],
            "usable": not problems,
            "dumps": [dump_name(f) for f in d["files"]],
            "records": d["records"], "inScope": len(d["scoped"]), "active": active, "hosts": len(hosts),
            "snapshot": d["snapshot"].strftime("%Y-%m-%dT%H:%MZ") if d["snapshot"] else None,
            "problems": problems, "warnings": warnings,
        })
    return rows


def print_health(rows, out=sys.stdout):
    print(f"{'source':<14}{'status':<10}{'records':>9}{'in scope':>10}{'active':>8}{'hosts':>7}  snapshot           dumps",
          file=out)
    for r in rows:
        status = "left out" if not r["usable"] else ("warning" if r["warnings"] else "ok")
        print(f"{r['source']:<14}{status:<10}{r['records']:>9}{r['inScope']:>10}{r['active']:>8}{r['hosts']:>7}  "
              f"{r['snapshot'] or '-':<18} {', '.join(r['dumps']) or '-'}", file=out)
    for r in rows:
        for p in r["problems"]:
            print(f"LEFT OUT{' (required source)' if r['required'] else ''}: {r['source']} ({r['resource']}): {p}", file=out)
        for w in r["warnings"]:
            print(f"warning: {r['source']} ({r['resource']}): {w}", file=out)
    used = [r for r in rows if r["usable"]]
    print("report covers: " + (", ".join(f"{r['source']}{' (required)' if r['required'] else ''}" for r in used) or "nothing")
          + (" · left out: " + ", ".join(r["source"] for r in rows if not r["usable"]) if len(used) < len(rows) else ""),
          file=out)
    if not any(r["required"] for r in used):
        print("note: no required agent source is usable, so the report lists the inventories without assessing "
              "agent coverage", file=out)


def cmd_check(args):
    cfg = load_config(args.sources)
    print_health(source_health(cfg, load_sources(cfg, args.dumps), datetime.now(timezone.utc)))


def flatten(rec, prefix="", depth=0, out=None):
    out = {} if out is None else out
    for k, v in rec.items():
        if isinstance(v, dict) and v and depth < 2:
            flatten(v, f"{prefix}{k}.", depth + 1, out)
        else:
            out[f"{prefix}{k}"] = v
    return out


def cmd_fields(args):
    files = dump_files(args.dumps, args.resource)
    if not files:
        print(f"no dump files in {Path(args.dumps) / args.resource}")
        return
    stats = defaultdict(lambda: {"filled": 0, "types": Counter(), "values": Counter()})
    n = 0
    counter = Counter()
    for f in files:
        try:
            with open_dump(f) as fh:
                for _, rec in iter_lines(fh, args.resource, counter):
                    n += 1
                    for path, v in flatten(rec).items():
                        st = stats[path]
                        if v not in (None, "", [], {}):
                            st["filled"] += 1
                            st["values"][json.dumps(v)[:48] if isinstance(v, (list, dict, bool)) else str(v)[:48]] += 1
                        st["types"][type(v).__name__] += 1
                    if n >= args.sample:
                        break
        except READ_ERRORS as e:
            print(f"warning: {f.name} could not be read through ({type(e).__name__}: {e})")
        if n >= args.sample:
            break
    print(f"{args.resource}: {n} records read from {len(files)} file(s)"
          + (f", {counter['bad']} unreadable lines skipped" if counter["bad"] else ""))
    for path in sorted(stats):
        st = stats[path]
        kinds = "/".join(t for t, _ in st["types"].most_common(2))
        distinct = len(st["values"])
        if 0 < distinct <= 8:
            shown = ", ".join(f"{v} ({c})" for v, c in st["values"].most_common(8))
        else:
            shown = f"e.g. {next(iter(st['values']), '')}" if distinct else ""
        print(f"  {path:<42} {100 * st['filled'] // max(n, 1):>3}%  {kinds:<12} {distinct:>5}  {shown}")


# ---- devices ---------------------------------------------------------------

def device_class(os_name, device_type=""):
    o, t = (os_name or "").lower(), (device_type or "").lower()
    if NETWORK_RE.search(o) or NETWORK_RE.search(t) or (t and not COMPUTER_TYPE_RE.search(t)):
        return NETWORK_CLASS
    for cls, words in CLASS_KEYWORDS:
        if any(w in o for w in words):
            return cls
    return DEFAULT_CLASS if o.strip() else UNKNOWN_CLASS


def classify(cfg, codes, cls):
    """codes: {source name: 0 missing / 1 stale / 2 active} -> (status, issue key or None)."""
    sources = cfg["sources"]
    if not any(codes[s["name"]] == 2 for s in sources):
        return "Inactive", None
    required = [s["name"] for s in sources if s["required"]]
    if all(codes[n] == 0 for n in required):
        if cls == NETWORK_CLASS:
            return "No agent expected", None
        if cls == UNKNOWN_CLASS:
            return "Unidentified", ("unidentified", ())
    if not required:
        return "Not assessed", None
    missing = tuple(n for n in required if codes[n] == 0)
    if missing:
        return "Missing agent", ("missing", missing)
    stale = tuple(n for n in required if codes[n] == 1)
    if stale:
        return "Agent not reporting", ("stale", stale)
    return "Compliant", None


def build_units(s, records, name_by_id, now):
    """Collapses one source's records into units, one per device as the source sees it: the `key`
    field when the source has one (e.g. the IP across several pentests), else the device-ID-mapped or
    normalized hostname. A unit keeps every candidate name, the IPs, the latest last-seen time, and
    the OS, device type and weakness counts of its most recent record."""
    cutoff = now - timedelta(days=s["staleDays"])
    units = {}
    for r in records:
        names = [norm_host(get_path(r, p)) for p in s["hostPaths"]]
        name = next((n for n in names if n), "")
        did = norm_id(get_path(r, s["deviceId"])) if s.get("deviceId") else ""
        ip = norm_ip(get_path(r, s["ip"])) if s.get("ip") else ""
        if s.get("key"):
            k = first_value(get_path(r, s["key"])).lower()
        else:
            k = name_by_id.get(did) or name or (ip if s["matchIp"] else "")
        if not k:
            continue
        u = units.setdefault(k, {"key": k, "named": False, "names": [[] for _ in s["hostPaths"]], "ids": set(),
                                 "ips": set(), "seen": None, "code": 0, "os": "", "deviceType": "",
                                 "metrics": {}, "latest": None})
        u["named"] = u["named"] or bool(name_by_id.get(did) or name)
        for i, n in enumerate(names):
            if n:
                u["names"][i].append(n)
        if did:
            u["ids"].add(did)
        if ip:
            u["ips"].add(ip)
        seen = to_dt(get_path(r, s["lastSeen"]))
        u["code"] = max(u["code"], 2 if seen and seen > cutoff else 1)
        if seen and (u["seen"] is None or seen > u["seen"]):
            u["seen"] = seen
        at = seen or EPOCH
        os_value = first_value(get_path(r, s["os"]))
        dtype = first_value(get_path(r, s["deviceType"])) if s.get("deviceType") else ""
        if (os_value or dtype) and (u["latest"] is None or at >= u["latest"] or not (u["os"] or u["deviceType"])):
            u["os"], u["deviceType"] = os_value or u["os"], dtype or u["deviceType"]
        metrics = {}
        for m in ("weaknesses", "confirmedWeaknesses"):
            if s.get(m):
                try:
                    metrics[m] = int(float(first_value(get_path(r, s[m])) or 0))
                except (TypeError, ValueError):
                    pass
        if u["latest"] is None or at > u["latest"]:
            u["latest"], u["metrics"] = at, metrics
        elif at == u["latest"]:
            for m, v in metrics.items():
                u["metrics"][m] = max(u["metrics"].get(m, 0), v)
    return units


def consistent_name(u):
    """The first host path whose names agree across every record of the unit. A name that changes
    between records (one IP reported under several names over several pentests) is not trusted."""
    for vals in u["names"]:
        if vals and len(set(vals)) == 1:
            return vals[0]
    return ""


def build_devices(cfg, data, now):
    """One record per device. Records carrying a device ID the idAuthority source knows are filed
    under the authority's hostname (renamed machines line up); everything else matches on the
    normalized hostname. Units of a matchIp source (e.g. hosts found by a network scan) are filed
    under: the authority hostname for a known device ID; else their name if another source knows it;
    else the one host that another source lists at the same IP; else their own name; else the IP.
    A source is active for a device if any of its records was seen within the source's staleDays,
    stale if it only holds older records, missing if it holds none."""
    sources = cfg["sources"]
    authority = next((s for s in sources if s.get("idAuthority")), None)
    name_by_id = {}
    if authority:
        for r in data[authority["name"]]["scoped"]:
            host = next((h for h in (norm_host(get_path(r, p)) for p in authority["hostPaths"]) if h), "")
            did = norm_id(get_path(r, authority["deviceId"]))
            if host and did:
                name_by_id.setdefault(did, host)

    units = {s["name"]: build_units(s, data[s["name"]]["scoped"], name_by_id, now) for s in sources}
    known, ip_index, match_stats = set(), defaultdict(set), {s["name"]: Counter() for s in sources}

    def mapped_name(u):
        return next((name_by_id[i] for i in sorted(u["ids"]) if i in name_by_id), "")

    def address(u):
        return sorted(u["ips"])[0] if u["ips"] else u["key"]

    for s in [s for s in sources if not s["matchIp"]]:
        for u in units[s["name"]].values():
            if s.get("key"):
                mapped = mapped_name(u)
                name = mapped or consistent_name(u)
                u["host"], how = (name, "device ID" if mapped else "name") if name else (address(u), "address")
            else:
                u["host"], how = u["key"], "device ID" if mapped_name(u) else "name"
            match_stats[s["name"]][how] += 1
            known.add(u["host"])
            for ip in u["ips"]:
                ip_index[ip].add(u["host"])
    for s in [s for s in sources if s["matchIp"]]:
        for u in units[s["name"]].values():
            mapped = mapped_name(u)
            name = consistent_name(u) if s.get("key") else (u["key"] if u["named"] else "")
            by_ip = {h for ip in u["ips"] for h in ip_index.get(ip, ())}
            if mapped:
                u["host"], how = mapped, "device ID"
            elif name and name in known:
                u["host"], how = name, "name"
            elif len(by_ip) == 1:
                u["host"], how = next(iter(by_ip)), "IP address"
            elif name:
                u["host"], how = name, "own name only"
            else:
                u["host"], how = address(u), "address only"
            match_stats[s["name"]][how] += 1
            known.add(u["host"])

    by_host = {}
    for s in sources:
        n = s["name"]
        for u in units[n].values():
            d = by_host.setdefault(u["host"], {"host": u["host"], "codes": {}, "seen": {}, "os": {}, "deviceType": {},
                                               "ips": set(), "names": set(), "metrics": {}})
            d["codes"][n] = max(d["codes"].get(n, 0), u["code"])
            if u["seen"] and (n not in d["seen"] or u["seen"] > d["seen"][n]):
                d["seen"][n] = u["seen"]
            if u["os"] and n not in d["os"]:
                d["os"][n] = u["os"]
            if u["deviceType"] and n not in d["deviceType"]:
                d["deviceType"][n] = u["deviceType"]
            d["ips"] |= u["ips"]
            d["names"] |= {x for vals in u["names"] for x in vals}
            for m, v in u["metrics"].items():
                d["metrics"][m] = max(d["metrics"].get(m, 0), v)

    devices = []
    for d in by_host.values():
        codes = {s["name"]: d["codes"].get(s["name"], 0) for s in sources}
        first = next((s["name"] for s in sources if s["name"] in d["os"] or s["name"] in d["deviceType"]), None)
        os_name = d["os"].get(first, "") if first else ""
        dtype = d["deviceType"].get(first, "") if first else ""
        cls = device_class(os_name, dtype)
        status, issue = classify(cfg, codes, cls)
        devices.append({"host": d["host"], "os": os_name, "deviceType": dtype, "deviceClass": cls,
                        "codes": codes, "seen": d["seen"], "status": status, "issue": issue,
                        "ips": sorted(d["ips"]), "aliases": sorted(d["names"] - {d["host"]}),
                        "metrics": d["metrics"]})
    return devices, {n: dict(c) for n, c in match_stats.items() if c}


def join_and(items):
    items = [str(i) for i in items]
    if not items:
        return ""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def pct(n, d):
    return 0 if d == 0 else round(100.0 * n / d, 1)


def issue_label(cfg, issue):
    kind, names = issue
    if kind == "unidentified":
        return "Unidentified hosts"
    label = {s["name"]: s["label"] for s in cfg["sources"]}
    required = [s["name"] for s in cfg["sources"] if s["required"]]
    if kind == "missing":
        if len(names) == len(required) > 1:
            return "Missing both agents" if len(required) == 2 else "Missing all required agents"
        return "Missing " + join_and(label[n] for n in names)
    return join_and(label[n] for n in names) + " not reporting"


def issue_sort_key(cfg, issue):
    order = {s["name"]: i for i, s in enumerate(cfg["sources"])}
    kind, names = issue
    return ({"missing": 0, "stale": 1}.get(kind, 2), len(names), [order[n] for n in names])


def active_in(cfg, d):
    return [s["name"] for s in cfg["sources"] if d["codes"][s["name"]] == 2]


def compute_facts(cfg, all_sources, devices, health, match_stats, account, generated):
    """cfg holds the sources used in this run; all_sources is every configured source, so the facts
    also say which were left out and why."""
    sources = cfg["sources"]
    names = [s["name"] for s in sources]
    references = [s["name"] for s in sources if not s["required"]]
    discovery = [s for s in sources if s["discovery"]]
    inventories = [s["name"] for s in sources if not s["discovery"]]
    totals = Counter()
    coverage = {n: Counter() for n in names}
    issues = defaultdict(lambda: {"devices": 0, "byClass": Counter(), "notInReference": Counter(), "withWeaknesses": 0})
    patterns = Counter()
    inactive = Counter()
    by_class = defaultdict(Counter)
    disc = {s["name"]: {"devices": 0, "byStatus": Counter(), "notInInventories": 0, "notInInventoriesByStatus": Counter(),
                        "withWeaknesses": 0, "attentionWithWeaknesses": 0, "attentionWithConfirmed": 0, "latest": None}
            for s in discovery}
    listed = []
    for d in devices:
        totals[d["status"]] += 1
        if d["status"] == "Inactive":
            inactive[tuple(n for n in names if d["codes"][n])] += 1
            continue
        weak, confirmed = d["metrics"].get("weaknesses", 0), d["metrics"].get("confirmedWeaknesses", 0)
        for s in discovery:
            n = s["name"]
            if d["codes"][n] == 2:
                x = disc[n]
                x["devices"] += 1
                x["byStatus"][d["status"]] += 1
                if inventories and all(d["codes"][i] == 0 for i in inventories):
                    x["notInInventories"] += 1
                    x["notInInventoriesByStatus"][d["status"]] += 1
                x["withWeaknesses"] += weak > 0
                x["attentionWithWeaknesses"] += bool(d["issue"]) and weak > 0
                x["attentionWithConfirmed"] += bool(d["issue"]) and confirmed > 0
        if d["status"] in SCOPE_STATUSES:
            by_class[d["deviceClass"]][d["status"]] += 1
            patterns[tuple(active_in(cfg, d))] += 1
            for n in names:
                coverage[n][STATES[d["codes"][n]]] += 1
        if d["issue"]:
            i = issues[d["issue"]]
            i["devices"] += 1
            i["byClass"][d["deviceClass"]] += 1
            i["withWeaknesses"] += weak > 0
            for n in references:
                if d["codes"][n] == 0:
                    i["notInReference"][n] += 1
            listed.append({
                "host": d["host"], "os": d["os"], "deviceClass": d["deviceClass"], "status": d["status"],
                "issue": issue_label(cfg, d["issue"]),
                "states": {n: STATES[d["codes"][n]] for n in names},
                "lastSeen": {n: d["seen"][n].strftime("%Y-%m-%d") if n in d["seen"] else "" for n in names},
                "ips": d["ips"], "aliases": d["aliases"], "weaknesses": weak, "confirmedWeaknesses": confirmed,
            })
    for s in discovery:
        seen = [d["seen"][s["name"]] for d in devices if s["name"] in d["seen"]]
        disc[s["name"]]["latest"] = max(seen).strftime("%Y-%m-%d") if seen else None

    assessed = any(s["required"] for s in sources)
    active = sum(totals[k] for k in SCOPE_STATUSES)
    by_name = {h["source"]: h for h in health}
    used = {s["name"] for s in sources}
    required_snaps = [by_name[s["name"]]["snapshot"] for s in sources if s["required"] and by_name[s["name"]]["snapshot"]]
    snaps = required_snaps or [by_name[n]["snapshot"] for n in used if by_name[n]["snapshot"]]
    ordered = sorted(issues, key=lambda k: issue_sort_key(cfg, k))
    return {
        "account": account,
        "generatedAt": generated.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataAsOf": min(snaps) if snaps else None,
        "staleDays": cfg["staleDays"],
        "assessed": assessed,
        "sources": [{"name": s["name"], "label": s["label"], "required": s["required"], "discovery": s["discovery"],
                     "staleDays": s["staleDays"], "snapshot": by_name[s["name"]]["snapshot"]} for s in sources],
        "unavailableSources": [{"name": s["name"], "label": s["label"], "required": s["required"],
                                "reason": "; ".join(by_name[s["name"]]["problems"])}
                               for s in all_sources if s["name"] not in used],
        "sourceHealth": health,
        "totals": {
            "activeDevices": active,
            "compliant": totals["Compliant"],
            "missingAgent": totals["Missing agent"],
            "agentNotReporting": totals["Agent not reporting"],
            "notAssessed": totals["Not assessed"],
            "unidentified": totals["Unidentified"],
            "noAgentExpected": totals["No agent expected"],
            "inactive": totals["Inactive"],
            "compliancePct": pct(totals["Compliant"], active) if assessed else None,
        },
        "coverage": [{
            "source": s["name"], "label": s["label"], "required": s["required"],
            "active": coverage[s["name"]]["active"], "stale": coverage[s["name"]]["stale"],
            "missing": coverage[s["name"]]["missing"], "coveragePct": pct(coverage[s["name"]]["active"], active),
        } for s in sources],
        "issues": [{
            "key": f"{k[0]}: {'+'.join(k[1])}", "label": issue_label(cfg, k), "kind": k[0], "sources": list(k[1]),
            "devices": issues[k]["devices"], "byClass": dict(issues[k]["byClass"]),
            "listedNotInReference": dict(issues[k]["notInReference"]),
            "withWeaknesses": issues[k]["withWeaknesses"],
        } for k in ordered],
        "presencePatterns": [{"activeIn": list(k), "devices": v} for k, v in patterns.most_common()],
        "inactiveByPresence": [{"presentIn": list(k), "devices": v} for k, v in inactive.most_common()],
        "byDeviceClass": {c: dict(v) for c, v in by_class.items()},
        "discovery": [{
            "source": s["name"], "label": s["label"], "devices": disc[s["name"]]["devices"],
            "byStatus": dict(disc[s["name"]]["byStatus"]),
            "notInInventories": disc[s["name"]]["notInInventories"],
            "notInInventoriesByStatus": dict(disc[s["name"]]["notInInventoriesByStatus"]),
            "withWeaknesses": disc[s["name"]]["withWeaknesses"],
            "attentionWithWeaknesses": disc[s["name"]]["attentionWithWeaknesses"],
            "attentionWithConfirmed": disc[s["name"]]["attentionWithConfirmed"],
            "latestSeen": disc[s["name"]]["latest"],
            "matchedBy": match_stats.get(s["name"], {}),
        } for s in discovery],
        "matching": match_stats,
        "deviceList": {"total": len(listed)},
        "_devices": listed,
    }


def write_devices_csv(cfg, devices, path):
    """Every device, one row each: the full inventory behind the report."""
    names = [s["name"] for s in cfg["sources"]]
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["host", "os", "deviceClass", "status", "detail", "activeIn"]
                   + [c for n in names for c in (n, f"{n}_lastSeen")]
                   + ["ips", "otherNames", "weaknesses", "confirmedWeaknesses"])
        for d in sorted(devices, key=lambda d: (STATUS_ORDER.get(d["status"], 9), d["host"])):
            w.writerow([d["host"], d["os"], d["deviceClass"], d["status"],
                        issue_label(cfg, d["issue"]) if d["issue"] else "", "+".join(active_in(cfg, d))]
                       + [c for n in names for c in (STATES[d["codes"][n]],
                                                      d["seen"][n].strftime("%Y-%m-%d %H:%M") if n in d["seen"] else "")]
                       + [" ".join(d["ips"]), " ".join(d["aliases"]),
                          d["metrics"].get("weaknesses", ""), d["metrics"].get("confirmedWeaknesses", "")])


# ---- HTML ------------------------------------------------------------------

GREEN, AMBER, RED, BLUE, NAVY = "var(--green)", "var(--amber)", "var(--red)", "var(--blue)", "var(--navy)"
NEUTRAL, GREY = "#c9ced8", "#8a8a8a"
TONE_COLOUR = {"urgent": RED, "normal": BLUE, "routine": NAVY}
CLASS_LABELS = [("Workstation", "Workstations"), ("Server", "Servers"), ("Linux", "Linux hosts"),
                (NETWORK_CLASS, "Network devices"), (UNKNOWN_CLASS, "Unknown OS")]
CLASS_NOUNS = {"Server": ("server", "servers"), "Linux": ("Linux host", "Linux hosts")}
ISSUE_COLOUR = {"missing": RED, "stale": AMBER, "unidentified": GREY}


def esc(s):
    return html.escape(str(s))


def pretty_os(os_name):
    o = os_name or ""
    for raw, nice in (("WindowsServer", "Windows Server "), ("Windows11", "Windows 11"), ("Windows10", "Windows 10")):
        if o.startswith(raw):
            return nice + o[len(raw):]
    return o


def short_date(iso):
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d %b")
    except (TypeError, ValueError):
        return iso or ""


def long_date(iso):
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d %b %Y")
    except (TypeError, ValueError):
        return iso or ""


def snapshot_text(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%MZ").strftime("%d %b %Y %H:00 UTC")
    except (TypeError, ValueError):
        return "date unknown"


def plural(n, one, many=None):
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def stacked_bar(segments, total):
    parts = []
    for count, colour, label in segments:
        if count > 0 and total > 0:
            parts.append(f'<div class="seg" style="flex:{100.0 * count / total:.3f} 0 0;background:{colour}" '
                         f'title="{esc(label)}: {count}"></div>')
    return f'<div class="stack">{"".join(parts)}</div>'


def legend(items):
    return '<div class="legend">' + "".join(
        f'<span class="lg"><i style="background:{c}"></i>{esc(t)}</span>' for c, t in items) + "</div>"


def class_note(by_class):
    parts = []
    for cls in ("Server", "Linux"):
        n = by_class.get(cls, 0)
        if n:
            parts.append(f"{n} {CLASS_NOUNS[cls][0 if n == 1 else 1]}")
    return ", ".join(parts)


def missing_label(s):
    return "Missing" if s["required"] else s.get("missingLabel", "Not listed")


def discovery_sentence(cfg, f):
    """One sentence per discovery source: what the network scan found and how much of it is covered."""
    out = []
    req = [s["label"] for s in cfg["sources"] if s["required"]]
    for x in f["discovery"]:
        b = x["byStatus"]
        parts = []
        if f["assessed"]:
            parts.append(f"{b.get('Compliant', 0)} run {esc(join_and(req))}")
            miss = b.get("Missing agent", 0)
            if miss:
                only = x["notInInventoriesByStatus"].get("Missing agent", 0)
                parts.append(f"{miss} could run an agent but have none"
                             + (f" ({only} of them appear in no other inventory)" if only else ""))
            if b.get("Agent not reporting"):
                parts.append(f"{b['Agent not reporting']} have an agent that stopped reporting")
        if b.get("No agent expected"):
            parts.append(f"{plural(b['No agent expected'], 'is a network device', 'are network devices')} such as firewalls "
                         f"or power units")
        if b.get("Unidentified"):
            parts.append(f"{b['Unidentified']} could not be identified")
        if parts:
            out.append(f"{esc(x['label'])} found <strong>{x['devices']} hosts</strong> on the network: {join_and(parts)}.")
    return " ".join(out)


def default_narrative(cfg, f):
    t = f["totals"]
    label = {s["name"]: s["label"] for s in cfg["sources"]}
    required = [s for s in cfg["sources"] if s["required"]]
    discovery_refs = {s["name"] for s in cfg["sources"] if s["discovery"]}
    days = f["staleDays"]
    missing_required = [u["label"] for u in f["unavailableSources"] if u["required"]]
    steps = []
    if not required:
        p1 = (f"No security agent inventory was available for this report, so agent coverage could not be measured. "
              f"The connected inventories list <strong>{t['activeDevices']:,} devices</strong> active in the last {days} days.")
        p2 = discovery_sentence(cfg, f) or "Once an agent inventory is connected, this report shows which devices lack an agent."
        if missing_required:
            steps.append({"when": "This week", "tone": "urgent",
                          "text": f"Connect the {esc(join_and(missing_required))} device inventory so that agent coverage "
                                  f"can be measured."})
    else:
        req_labels = [s["label"] for s in required]
        if len(required) == 1:
            have = req_labels[0]
        elif len(required) == 2:
            have = f"both {join_and(req_labels)}"
        else:
            have = f"all of {join_and(req_labels)}"
        p1 = (f"Of <strong>{t['activeDevices']:,} devices</strong> active in the last {days} days, "
              f"<strong>{t['compliant']:,} ({t['compliancePct']}%)</strong> have {esc(have)} installed and reporting. "
              f"<strong>{t['missingAgent']}</strong> devices are missing {'the agent' if len(required) == 1 else 'at least one required agent'}, and "
              f"<strong>{t['agentNotReporting']}</strong> have an agent that has stopped reporting.")
        cov = {c["source"]: c for c in f["coverage"]}
        rates = [f"{esc(s['label'])} is active on {cov[s['name']]['active']:,} devices ({cov[s['name']]['coveragePct']}%)"
                 for s in required]
        p2 = join_and(rates) + "."
        missing = [i for i in f["issues"] if i["kind"] == "missing"]
        if missing and (len(missing) > 1 or len(required) > 1):
            p2 += " By gap: " + join_and(f"{i['devices']} {esc(i['label'][0].lower() + i['label'][1:])}" for i in missing) + "."
        servers = sum(i["byClass"].get("Server", 0) for i in f["issues"])
        if servers:
            p2 += f" {servers} of the {f['deviceList']['total']} devices needing attention are servers."
        sentence = discovery_sentence(cfg, f)
        if sentence:
            p2 += " " + sentence

    disc_label = join_and(label[n] for n in discovery_refs)
    for i in sorted(f["issues"], key=lambda i: -i["devices"]):
        names = [label[n] for n in i["sources"]]
        note = class_note(i["byClass"])
        note = f" ({note})" if note else ""
        refs = "".join(f"; {n} of them are not in {esc(label[r])}" for r, n in i["listedNotInReference"].items()
                       if n and r not in discovery_refs)
        if i["withWeaknesses"] and discovery_refs:
            refs += f"; {i['withWeaknesses']} of them have weaknesses found by {esc(disc_label)}"
        if i["kind"] == "unidentified":
            weak = f"; {i['withWeaknesses']} of them have weaknesses" if i["withWeaknesses"] else ""
            steps.append({"when": "Within 30 days", "tone": "normal",
                          "text": f"Identify the {i['devices']} hosts {esc(disc_label)} found without a detectable "
                                  f"operating system{weak}; install an agent on any that are computers."})
        elif i["kind"] == "missing" and len(names) == 1:
            urgent = sum(1 for s in steps if s["tone"] == "urgent") < 2
            steps.append({"when": "This week" if urgent else "Within 14 days", "tone": "urgent" if urgent else "normal",
                          "text": f"Deploy {esc(names[0])} to the {i['devices']} active devices that lack it{note}{refs}."})
        elif i["kind"] == "missing":
            lacking = f"neither {names[0]} nor {names[1]}" if len(names) == 2 else f"none of {join_and(names)}"
            steps.append({"when": "Within 30 days", "tone": "normal",
                          "text": f"Review the {i['devices']} devices with {esc(lacking)}{note}: confirm they "
                                  f"are in use, then onboard or retire them."})
        else:
            steps.append({"when": "Within 14 days", "tone": "normal",
                          "text": f"Investigate the {i['devices']} devices where {esc(join_and(names))} stopped reporting "
                                  f"(last-seen dates are in the device list)."})
    steps = steps[:5]
    urgency = ["This week", "Within 14 days", "Within 30 days"]
    steps.sort(key=lambda s: urgency.index(s["when"]))
    if t["inactive"]:
        top = [p for p in f["inactiveByPresence"][:2] if len(p["presentIn"]) == 1]
        detail = ", ".join(f"{p['devices']} {esc(label[p['presentIn'][0]])}-only" for p in top)
        steps.append({"when": "Quarterly", "tone": "routine",
                      "text": f"Retire the {t['inactive']} inactive records{f' ({detail})' if detail else ''} so the "
                              f"inventories match the active estate."})
    if not steps:
        steps.append({"when": "Quarterly", "tone": "routine",
                      "text": "Re-run this report to confirm coverage stays complete as devices are added."})
    return {"summary": [p1, p2], "nextSteps": steps}


def render_discovery(cfg, f):
    """One panel per discovery source: the hosts it found, by what the rest of the report says about them."""
    req = [s["label"] for s in cfg["sources"] if s["required"]]
    panels = []
    for x in f["discovery"]:
        b, total = x["byStatus"], x["devices"]
        only = x["notInInventoriesByStatus"]
        rows = []
        if f["assessed"]:
            rows += [
                (f"Running {join_and(req)}", b.get("Compliant", 0), BLUE, ""),
                ("Could run an agent, none found", b.get("Missing agent", 0), RED,
                 f"{only.get('Missing agent', 0)} in no other inventory" if only.get("Missing agent") else ""),
                ("Agent not reporting", b.get("Agent not reporting", 0), AMBER, ""),
            ]
        else:
            rows.append(("Agent coverage not assessed", b.get("Not assessed", 0), GREY, ""))
        rows += [
            ("Unidentified (no OS detected)", b.get("Unidentified", 0), GREY, ""),
            ("Network devices, no agent expected", b.get("No agent expected", 0), NEUTRAL, ""),
        ]
        bars = []
        for i, (text, n, colour, sub) in enumerate(rows):
            if not n and i > 1:
                continue
            bars.append(f"""
      <div class="ibar">
        <div class="ibar-label">{esc(text)}{f'<span class="ibar-sub">{esc(sub)}</span>' if sub else ''}</div>
        <div class="bar-track"><div class="bar-fill" style="width:{100.0 * n / max(total, 1):.1f}%;background:{colour}"></div></div>
        <div class="ibar-val">{n}</div>
      </div>""")
        note = ""
        if x["attentionWithWeaknesses"]:
            note = (f'<div class="src-note">{x["attentionWithWeaknesses"]} of the devices needing attention '
                    f'{"has" if x["attentionWithWeaknesses"] == 1 else "have"} weaknesses found by {esc(x["label"])}'
                    + (f'; on {x["attentionWithConfirmed"]} of them {esc(x["label"])} confirmed at least one'
                       if x["attentionWithConfirmed"] else "")
                    + ".</div>")
        latest = f" · latest results {long_date(x['latestSeen'])}" if x["latestSeen"] else ""
        panels.append(f"""
<div class="panel col-12">
  <div class="panel-header"><h2 class="panel-title">Hosts found on the network by {esc(x['label'])}</h2><span class="panel-subtitle">{total} hosts{latest}</span></div>
  <div class="ibars">{''.join(bars)}</div>
  {note}
</div>""")
    return "".join(panels)


def render_html(cfg, f, narrative, title, customer):
    sources = cfg["sources"]
    t = f["totals"]
    days = f["staleDays"]
    active = t["activeDevices"]
    cov = {c["source"]: c for c in f["coverage"]}
    refs = [s for s in sources if not s["required"]]
    required = [s for s in sources if s["required"]]
    n_req = len(required)
    assessed = f["assessed"]
    generated = datetime.strptime(f["generatedAt"], "%Y-%m-%dT%H:%M:%SZ")
    as_of = datetime.strptime(f["dataAsOf"], "%Y-%m-%dT%H:%MZ") if f.get("dataAsOf") else generated
    weak_sources = [s for s in sources if s.get("weaknesses")]

    dash = "&#8212;"
    miss_note = {0: "no agent data", 1: f"no {esc(required[0]['label'])}" if required else "", 2: "one or both agents"}.get(n_req, "one or more agents")
    kpis = f"""
<div class="kpi"><div class="kpi-label">Active devices</div><div class="kpi-value navy">{active:,}</div><div class="kpi-note">last {days} days</div></div>
<div class="kpi"><div class="kpi-label">Fully covered</div><div class="kpi-value green">{f"{t['compliant']:,}" if assessed else dash}</div><div class="kpi-note">{f"{t['compliancePct']}% of active" if assessed else 'not assessed'}</div></div>
<div class="kpi"><div class="kpi-label">Missing an agent</div><div class="kpi-value red">{t['missingAgent'] if assessed else dash}</div><div class="kpi-note">{miss_note}</div></div>
<div class="kpi"><div class="kpi-label">Not reporting</div><div class="kpi-value amber">{t['agentNotReporting'] if assessed else dash}</div><div class="kpi-note">silent &gt; {days} days</div></div>
"""
    if t["unidentified"]:
        kpis += f"""<div class="kpi"><div class="kpi-label">Unidentified hosts</div><div class="kpi-value">{t['unidentified']}</div><div class="kpi-note">found on the network, no OS</div></div>\n"""
    kpis += f"""<div class="kpi"><div class="kpi-label">Inactive records</div><div class="kpi-value">{t['inactive']}</div><div class="kpi-note">excluded from totals</div></div>\n"""

    # Data-coverage notice: a required inventory that is configured but not in this run
    notice = ""
    missing_required = [u["label"] for u in f["unavailableSources"] if u["required"]]
    if missing_required:
        if assessed:
            text = (f"No {esc(join_and(missing_required))} device inventory was available, so this report measures "
                    f"{esc(join_and(s['label'] for s in required))} coverage only.")
        else:
            text = (f"No security agent inventory ({esc(join_and(missing_required))}) was available, so agent coverage "
                    f"is not assessed. The figures below describe the device inventories only.")
        notice = f'<div class="callout watch"><p><b>Data coverage.</b> {text}</p></div>'

    # Coverage by source
    ref_legend = f"Not in {refs[0]['label']}" if len(refs) == 1 else "Not in inventory"
    rows = []
    for s in sources:
        c = cov[s["name"]]
        total = c["active"] + c["stale"] + c["missing"]
        miss_text = "missing" if s["required"] else f"not in {s['label']}"
        bar = stacked_bar([(c["active"], GREEN, "active"), (c["stale"], AMBER, "stale"),
                           (c["missing"], RED if s["required"] else NEUTRAL, miss_text)], total)
        rows.append(f"""
      <div class="src-row">
        <div class="src-head"><span class="src-name">{esc(s['label'])}</span><span class="tag">{'required' if s['required'] else 'reference only'}</span><span class="src-pct">{c['coveragePct']}%</span></div>
        {bar}
        <div class="src-note">{c['active']:,} active · {c['stale']} stale · {c['missing']} {esc(miss_text)}</div>
      </div>""")
    if not rows:
        rows.append('<div class="src-note">No device inventory was available for this account.</div>')
    legend_items = ([(GREEN, "Active"), (AMBER, "Stale")] + ([(RED, "Missing")] if required else [])
                    + ([(NEUTRAL, ref_legend)] if refs else []))
    panel_sources = f"""
<div class="panel col-6">
  <div class="panel-header"><h2 class="panel-title">Agent coverage by source</h2><span class="panel-subtitle">{active:,} active devices</span></div>
  {legend(legend_items)}
  {''.join(rows)}
</div>"""

    # Devices requiring attention
    max_issue = max([i["devices"] for i in f["issues"]] or [1])
    bars = []
    for i in f["issues"]:
        note = class_note(i["byClass"])
        bars.append(f"""
      <div class="ibar">
        <div class="ibar-label">{esc(i['label'])}{f'<span class="ibar-sub">incl. {note}</span>' if note else ''}</div>
        <div class="bar-track"><div class="bar-fill" style="width:{100.0 * i['devices'] / max_issue:.1f}%;background:{ISSUE_COLOUR.get(i['kind'], GREY)}"></div></div>
        <div class="ibar-val">{i['devices']}</div>
      </div>""")
    if not bars:
        bars.append('<div class="src-note">'
                    + ("Every active device has all required agents reporting." if assessed and active else
                       "Agent coverage was not assessed: no security agent inventory was available." if not assessed else
                       "No active devices were found.") + "</div>")
    panel_issues = f"""
<div class="panel col-6">
  <div class="panel-header"><h2 class="panel-title">Devices requiring attention</h2><span class="panel-subtitle">{f['deviceList']['total']} devices{' · listed in the device list' if f['deviceList']['total'] else ''}</span></div>
  <div class="ibars">{''.join(bars)}</div>
</div>"""

    # Presence matrix
    max_pat = max([p["devices"] for p in f["presencePatterns"]] or [1])
    prow = []
    for p in f["presencePatterns"]:
        present = set(p["activeIn"])
        dots = "".join(f'<td class="dotc"><span class="dot{" on" if s["name"] in present else ""}"></span></td>' for s in sources)
        absent = [s["label"] for s in required if s["name"] not in present]
        if not required:
            note = ""
        elif not absent:
            note = "Fully covered"
        elif len(absent) == len(required) and len(required) > 1:
            note = "No active agent"
        else:
            note = "No active " + join_and(absent)
        prow.append(f"""<tr>{dots}
      <td><div class="pbar"><div class="pbar-fill" style="width:{100.0 * p['devices'] / max_pat:.1f}%"></div></div></td>
      <td class="num">{p['devices']}</td>
      <td class="note{'' if not absent else ' gap'}">{esc(note)}</td></tr>""")
    dot_cols = "".join(f'<col style="width:{max(48, round(6.0 * len(s["label"])) + 8)}px">' for s in sources)
    wide = len(sources) > 3
    panel_patterns = "" if not prow else f"""
<div class="panel {'col-12' if wide else 'col-8'}">
  <div class="panel-header"><h2 class="panel-title">Where each active device is seen</h2><span class="panel-subtitle">active within {days} days</span></div>
  <table class="data matrix">
    <colgroup>{dot_cols}<col><col style="width:36px"><col style="width:156px"></colgroup>
    <thead><tr>{''.join(f'<th class="dotc">{esc(s["label"])}</th>' for s in sources)}<th colspan="2" style="text-align:right">Devices</th><th>Coverage</th></tr></thead>
    <tbody>{''.join(prow)}</tbody>
  </table>
</div>"""

    # By device type
    crow = []
    for cls, cls_label in CLASS_LABELS:
        st = f["byDeviceClass"].get(cls, {})
        total = sum(st.values())
        if not total:
            continue
        ok, miss, silent = st.get("Compliant", 0), st.get("Missing agent", 0), st.get("Agent not reporting", 0)
        bar = stacked_bar([(ok, GREEN, "fully covered"), (silent, AMBER, "not reporting"), (miss, RED, "missing an agent")], total)
        crow.append(f"""
      <div class="src-row">
        <div class="src-head"><span class="src-name">{cls_label}</span><span class="src-pct">{pct(ok, total) if assessed else dash}{'%' if assessed else ''}</span></div>
        {bar}
        <div class="src-note">{f"{ok:,} of {total:,} covered · {miss} missing" + (f" · {silent} silent" if silent else '') if assessed else f"{total:,} devices"}</div>
      </div>""")
    panel_types = "" if not crow else f"""
<div class="panel {'col-12 types-wide' if wide else 'col-4'}">
  <div class="panel-header"><h2 class="panel-title">By device type</h2><span class="panel-subtitle">% fully covered</span></div>
  {legend([(GREEN, 'Covered'), (AMBER, 'Silent'), (RED, 'Missing')])}
  <div class="type-rows">{''.join(crow)}</div>
</div>"""

    summary_html = "".join(f"<p>{p}</p>" for p in narrative["summary"])
    steps_html = "".join(
        f'<div class="ns-item"><div class="ns-num" style="background:{TONE_COLOUR.get(s.get("tone"), BLUE)}">{n}</div><div>'
        f'<div class="ns-when">{esc(s.get("when", ""))}</div><div class="ns-act">{s.get("text", "")}</div></div></div>'
        for n, s in enumerate(narrative["nextSteps"][:6], 1))

    # Method
    authority = next((s for s in sources if s.get("idAuthority")), None)
    host_rule = 'the hostname, compared case-insensitively with the domain suffix and any trailing "$" removed'
    id_sources = [s["label"] for s in sources if s.get("deviceId") and s is not authority]
    if authority and id_sources:
        matching = (f"{esc(join_and(id_sources))} records are matched on the {esc(authority['label'])} device ID, so renamed "
                    f"machines line up. All other matching uses {esc(host_rule)}.")
    else:
        matching = f"Devices are matched on {esc(host_rule)}."
    ip_sources = [s for s in sources if s["matchIp"]]
    ip_providers = [s["label"] for s in sources if s.get("ip") and not s["matchIp"]]
    for s in ip_sources:
        matching += (f" {esc(s['label'])} hosts are matched on their network name when it is consistent across scans"
                     + (f", otherwise on the IP address {esc(join_and(ip_providers))} last reported" if ip_providers else "")
                     + "; a host that matches neither is listed by its IP address.")
    windows = [f"{esc(s['label'])} counts a device as seen if it found it within the last {s['staleDays']} days"
               for s in sources if s["staleDays"] != days]
    req_text = (f"{esc(join_and(s['label'] for s in required))} {'is' if n_req == 1 else 'are'} required on every active device."
                if required else "No security agent inventory was available, so no device is assessed for agent coverage.")
    if refs:
        ref_labels = [s["label"] for s in refs]
        one = len(ref_labels) == 1
        req_text += (f" {esc(join_and(ref_labels))} {'is a reference inventory' if one else 'are reference inventories'} only, "
                     f"so a device that is absent from {'it' if one else 'them'} is not counted as a gap for that reason.")
    if any(s["discovery"] for s in sources):
        req_text += (" Network devices such as firewalls, switches and power units cannot run an endpoint agent and are "
                     "counted separately; hosts whose operating system could not be detected are listed as unidentified "
                     "and are not part of the percentages.")
    snapshots = " · ".join(f"{esc(s['label'])} {snapshot_text(next((h['snapshot'] for h in f['sourceHealth'] if h['source'] == s['name']), None))}"
                           for s in sources)
    left_out = ""
    if f["unavailableSources"]:
        left_out = (f"<div><b>Not included.</b> {esc(join_and(u['label'] for u in f['unavailableSources']))}: no usable device "
                    f"inventory was available for this report.</div>")
    method = f"""
<div class="panel col-12 page-break">
  <div class="panel-header"><h2 class="panel-title">How this report is built</h2><span class="panel-subtitle">Data as at {as_of.strftime('%d %b %Y %H:00 UTC')} · account {esc(f['account'])}</span></div>
  <div class="method">
    <div><b>Sources.</b> {esc('; '.join(s['scope'] for s in sources)) or 'none'}.{f' Inventory snapshots: {snapshots}.' if sources else ''}</div>
    {left_out}
    <div><b>Matching.</b> {matching}</div>
    <div><b>Active / stale.</b> A source counts a device as <i>active</i> if it has seen it within the last {days} days, and <i>stale</i> if it
    holds a record that is older{('. ' + '; '.join(windows)) if windows else ''}. Devices that are not active in any source are <i>inactive</i> and excluded from all totals.</div>
    <div><b>Required.</b> {req_text}</div>
  </div>
</div>"""

    # Device list
    state_colour = {"active": GREEN, "stale": AMBER, "missing": RED}
    body = []
    n_cols = 2 + len(sources) + (1 if weak_sources else 0)
    for i in f["issues"]:
        group = [d for d in f["_devices"] if d["issue"] == i["label"]]
        if not group:
            continue
        body.append(f'<tr class="grp"><td colspan="{n_cols}">{esc(i["label"])} <span>({len(group)})</span></td></tr>')
        for d in group:
            badge = f'<span class="cls">{d["deviceClass"]}</span>' if d["deviceClass"] not in (DEFAULT_CLASS, UNKNOWN_CLASS) else ""
            cells = []
            for s in sources:
                state, seen = d["states"][s["name"]], d["lastSeen"][s["name"]]
                colour = state_colour[state] if (s["required"] or state != "missing") else NEUTRAL
                text = {"active": s.get("activeLabel", "Active"), "stale": "Stale", "missing": missing_label(s)}[state]
                if d["status"] == "Unidentified" and state == "missing":
                    colour, text = NEUTRAL, "None"  # an unidentified host may not be able to run an agent at all
                when = f' <span class="when">{short_date(seen)}</span>' if state == "stale" and seen else ""
                cells.append(f'<td class="stc"><span class="st"><i style="background:{colour}"></i>{esc(text)}{when}</span></td>')
            if weak_sources:
                w, c = d["weaknesses"], d["confirmedWeaknesses"]
                cells.append(f'<td class="num">{w}{f" <span class=when>({c})</span>" if c else ""}</td>' if w else
                             '<td class="num"><span class="when">&#8211;</span></td>')
            host = d["host"]
            extra = []
            if d["aliases"]:
                extra.append("names seen: " + ", ".join(d["aliases"][:2]) + (" …" if len(d["aliases"]) > 2 else ""))
            if d["ips"] and d["ips"] != [host]:
                extra.append(", ".join(d["ips"][:2]))
            sub = f'<div class="when" style="font-weight:400;font-family:var(--sans)">{esc(" · ".join(extra))}</div>' if extra else ""
            os_text = esc(pretty_os(d["os"])) if d["os"] else '<span class="when">Not detected</span>'
            body.append(f'<tr><td class="host">{esc(host)}{sub}</td><td>{os_text}{badge}</td>{"".join(cells)}</tr>')
    dl = f["deviceList"]
    listed_note = f"{dl['listed']} of {dl['total']} devices listed" if dl["listed"] < dl["total"] else f"{dl['total']} devices"
    weak_w = 76 if weak_sources else 0
    src_w = min(100, (716 - 140 - 130 - weak_w) // max(1, len(sources)))
    weak_head = f'<th style="text-align:right">{esc(weak_sources[0]["label"])} weak&shy;nesses</th>' if weak_sources else ""
    device_list = "" if not body else f"""
<div class="panel col-12">
  <div class="panel-header"><h2 class="panel-title">Devices requiring attention</h2><span class="panel-subtitle">{listed_note} · dates show when a stale agent last reported{f" · (n) = weaknesses {esc(weak_sources[0]['label'])} confirmed" if weak_sources else ""}</span></div>
  <table class="data devlist">
    <colgroup><col style="width:140px"><col>{''.join(f'<col style="width:{src_w}px">' for _ in sources)}{f'<col style="width:{weak_w}px">' if weak_sources else ''}</colgroup>
    <thead><tr><th>Device</th><th>Operating system</th>{''.join(f'<th>{esc(s["label"])}</th>' for s in sources)}{weak_head}</tr></thead>
    <tbody>{''.join(body)}</tbody>
  </table>
</div>"""

    subtitle = f"{join_and(s['label'] for s in sources)} device coverage" if sources else "Device coverage"
    fills = {
        "{{report_title}}": esc(title),
        "{{report_subtitle}}": esc(f"{customer} · {subtitle}" if customer else subtitle),
        "{{report_date}}": generated.strftime("%d %b %Y, %H:%M UTC"),
        "{{report_meta}}": f" · Account {esc(f['account'])} · Activity window: last {days} days",
        "{{kpi_strip}}": kpis,
        "{{summary_html}}": summary_html,
        "{{main_grid}}": notice + panel_sources + panel_issues + panel_patterns + panel_types,
        "{{next_steps_items}}": steps_html,
        "{{appendix}}": render_discovery(cfg, f) + method + device_list,
        "{{footer_page_info}}": f"Fluency Report · {esc(title)}",
        "{{footer_data_date}}": as_of.strftime("%d %b %Y, %H:00 UTC"),
    }
    tpl = (SKILL_DIR / "assets" / "report_template.html").read_text()
    for k, v in fills.items():
        tpl = tpl.replace(k, v)
    return tpl


def load_narrative(path, narrative):
    """Overlays narrative.json on the default narrative. A file that can't be used is reported and
    the default is kept, so a bad narrative never stops the render."""
    try:
        custom = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        warn(f"{path} could not be read ({e}); using the default narrative")
        return False
    if not isinstance(custom, dict):
        warn(f"{path} is not a JSON object; using the default narrative")
        return False
    summary, steps = custom.get("summary"), custom.get("nextSteps")
    used = False
    if isinstance(summary, str):
        summary = [summary]
    if isinstance(summary, list) and summary and all(isinstance(p, str) for p in summary):
        narrative["summary"], used = summary, True
    elif summary:
        warn(f"{path}: summary must be a list of HTML paragraphs; keeping the default summary")
    if isinstance(steps, list) and steps and all(isinstance(s, dict) and s.get("text") for s in steps):
        narrative["nextSteps"], used = steps, True
    elif steps:
        warn(f"{path}: nextSteps must be a list of {{when, tone, text}}; keeping the default next steps")
    return used


def cmd_render(args):
    cfg = load_config(args.sources)
    now = (datetime.strptime(args.as_of, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if args.as_of
           else datetime.now(timezone.utc).replace(microsecond=0))
    data = load_sources(cfg, args.dumps)
    health = source_health(cfg, data, now)
    print_health(health)
    usable = {h["source"] for h in health if h["usable"]}
    run_cfg = dict(cfg, sources=[s for s in cfg["sources"] if s["name"] in usable])

    devices, match_stats = build_devices(run_cfg, data, now)
    f = compute_facts(run_cfg, cfg["sources"], devices, health, match_stats, args.account, now)
    rank = {i["label"]: n for n, i in enumerate(f["issues"])}
    class_rank = {"Server": 0, "Linux": 1, DEFAULT_CLASS: 2}
    f["_devices"].sort(key=lambda d: (rank[d["issue"]], class_rank.get(d["deviceClass"], 3),
                                      -d["confirmedWeaknesses"], -d["weaknesses"], d["host"]))
    if args.max_listed and len(f["_devices"]) > args.max_listed:
        f["_devices"] = f["_devices"][:args.max_listed]
    f["deviceList"]["listed"] = len(f["_devices"])

    narrative = default_narrative(run_cfg, f)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    narrative_path = Path(args.narrative) if args.narrative else work / "narrative.json"
    if narrative_path.exists() and load_narrative(narrative_path, narrative):
        print(f"narrative: {narrative_path}")
    else:
        print("narrative: default (write narrative.json in the work dir to replace it)")

    facts = {k: v for k, v in f.items() if not k.startswith("_")}
    facts["defaultNarrative"] = default_narrative(run_cfg, f)
    (work / "facts.json").write_text(json.dumps(facts, indent=2) + "\n")
    write_devices_csv(run_cfg, devices, work / "devices.csv")

    out = Path(args.out) if args.out else work
    (out / "assets").mkdir(parents=True, exist_ok=True)
    logo = out / "assets" / "logo2.png"
    if not logo.exists() and (SKILL_DIR / "assets" / "logo2.png").exists():
        shutil.copyfile(SKILL_DIR / "assets" / "logo2.png", logo)
    html_path = out / f"{args.stem}.html"
    html_path.write_text(render_html(run_cfg, f, narrative, args.title, args.customer))

    t = f["totals"]
    print(f"wrote {html_path}, {work / 'facts.json'} and {work / 'devices.csv'} ({len(devices)} devices)")
    if f["assessed"]:
        print(f"active {t['activeDevices']} · compliant {t['compliant']} ({t['compliancePct']}%) · missing {t['missingAgent']}"
              f" · not reporting {t['agentNotReporting']} · inactive {t['inactive']}")
    else:
        print(f"agent coverage NOT assessed (no required source usable) · active {t['activeDevices']} · inactive {t['inactive']}")
    if t["unidentified"] or t["noAgentExpected"]:
        print(f"outside the percentages: unidentified {t['unidentified']} · network devices (no agent expected) {t['noAgentExpected']}")
    for i in f["issues"]:
        print(f"  {i['label']}: {i['devices']}")
    for x in f["discovery"]:
        print(f"  {x['label']}: {x['devices']} hosts, matched by {', '.join(f'{k} {v}' for k, v in x['matchedBy'].items()) or '-'}")
    for u in f["unavailableSources"]:
        print(f"left out of the report: {u['label']}{' (required)' if u['required'] else ''}: {u['reason']}")
    dl = f["deviceList"]
    if dl["listed"] < dl["total"]:
        print(f"note: the device list shows {dl['listed']} of {dl['total']} devices (--max-listed); devices.csv has all")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    fl = sub.add_parser("fields", help="list the fields of a downloaded dump")
    fl.add_argument("--dumps", required=True, help="directory holding <resource>/<customer>.jsonl.gz")
    fl.add_argument("--resource", required=True)
    fl.add_argument("--sample", type=int, default=5000, help="records to read (default 5000)")
    fl.set_defaults(func=cmd_fields)
    c = sub.add_parser("check", help="per-source health of the downloaded dumps")
    c.add_argument("--dumps", required=True)
    c.add_argument("--sources", default=str(SKILL_DIR / "sources.json"))
    c.set_defaults(func=cmd_check)
    r = sub.add_parser("render", help="build facts.json, devices.csv and the HTML report")
    r.add_argument("--dumps", required=True)
    r.add_argument("--work", required=True, help="directory for facts.json, devices.csv and narrative.json")
    r.add_argument("--account", required=True, help="Fluency account the dumps came from")
    r.add_argument("--sources", default=str(SKILL_DIR / "sources.json"))
    r.add_argument("--customer", default="", help="customer name for the subtitle")
    r.add_argument("--title", default="Security Agent Deployment Status")
    r.add_argument("--narrative", help="narrative JSON (default: WORK/narrative.json if present)")
    r.add_argument("--out", help="output directory for the HTML (default: WORK)")
    r.add_argument("--stem", default="security_deployment_status")
    r.add_argument("--as-of", help="evaluate activity as of YYYY-MM-DDTHH:MM:SSZ (default: now)")
    r.add_argument("--max-listed", type=int, default=0, help="cap the device list in the report (default: all)")
    r.set_defaults(func=cmd_render)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
