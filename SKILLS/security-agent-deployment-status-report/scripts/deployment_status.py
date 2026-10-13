#!/usr/bin/env python3
"""Security agent deployment status from Fluency resource dumps.

  deployment_status.py fields --dumps DUMPS --resource RESOURCE
      Field paths in a downloaded dump, how often each is filled, and common values. Use it to
      choose the host / os / lastSeen / filter fields when adding a source.

  deployment_status.py check --dumps DUMPS [--sources FILE]
      Per-source health: records, records in scope, records active, snapshot hour.

  deployment_status.py render --dumps DUMPS --work WORK --account ACCOUNT [...]
      Matches devices across sources and writes WORK/facts.json, WORK/devices.csv and the HTML report.

Dumps are the gzipped JSONL files issued by get_resource_dump_url, saved as
DUMPS/<resource>/<customer>.jsonl.gz. Every decision comes from the sources file.
Python standard library only.
"""
import argparse
import csv
import gzip
import html
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
FIELDS_REQUIRED = ("name", "resource", "host", "os", "lastSeen")
STATES = ("missing", "stale", "active")  # index is the state code
SNAPSHOT_MAX_AGE = timedelta(hours=48)

# Device class from the OS string (case-insensitive substring match, first class wins).
CLASS_KEYWORDS = [
    ("Server", ["server"]),
    ("Linux", ["linux", "ubuntu", "centos", "red hat", "rhel", "debian", "suse", "rocky", "alma"]),
]
DEFAULT_CLASS = "Workstation"


# ---- sources ---------------------------------------------------------------

def load_config(path):
    cfg = json.load(open(path))
    sources = cfg["sources"]
    errors = []
    names = set()
    for i, s in enumerate(sources):
        for f in FIELDS_REQUIRED:
            if not s.get(f):
                errors.append(f"source #{i + 1}: missing '{f}'")
        name = s.get("name", "")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            errors.append(f"source #{i + 1}: name '{name}' must be a plain identifier")
        if name in names:
            errors.append(f"duplicate source name '{name}'")
        names.add(name)
        if not isinstance(s.get("filter", {}), dict):
            errors.append(f"source '{name}': filter must be an object of field: value")
        s.setdefault("label", name)
        s.setdefault("scope", s.get("resource", ""))
        s["required"] = bool(s.get("required"))
    authorities = [s for s in sources if s.get("idAuthority")]
    if len(authorities) > 1:
        errors.append("at most one source can set idAuthority")
    if authorities and not authorities[0].get("deviceId"):
        errors.append(f"idAuthority source '{authorities[0]['name']}' needs a deviceId field")
    if not any(s["required"] for s in sources):
        errors.append("at least one source must be required")
    if errors:
        sys.exit("sources file is invalid:\n  " + "\n  ".join(errors))
    cfg["staleDays"] = int(cfg.get("staleDays", 30))
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
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return datetime.fromtimestamp(v / 1000, timezone.utc)
    m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$", str(v).strip())
    if not m:
        return None
    frac = "." + ((m.group(3) or ".")[1:] + "000000")[:6]
    tz = m.group(4) or "Z"
    tz = "+00:00" if tz == "Z" else (tz if ":" in tz else tz[:3] + ":" + tz[3:])
    return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}{frac}{tz}").astimezone(timezone.utc)


def norm_host(v):
    # Lowercase, drop the DNS suffix, drop the trailing "$" of AD computer accounts.
    return ("" if v is None else str(v)).split(".")[0].strip().lower().rstrip("$")


def norm_id(v):
    return ("" if v is None else str(v)).strip().lower()


# ---- dumps -----------------------------------------------------------------

def dump_files(dumps, resource):
    return sorted((Path(dumps) / resource).glob("*.jsonl.gz"))


def iter_dump(files, resource):
    """Yields (envelope, record). The vendor fields sit under "@<resource>" in each line."""
    for f in files:
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    doc = json.loads(line)
                    rec = doc.get("@" + resource)
                    if not isinstance(rec, dict):
                        rec = {k: v for k, v in doc.items() if not k.startswith("@")}
                    yield doc, rec


def snapshot_time(day_index):
    try:
        return datetime.strptime(day_index, "%Y%m%d-%H").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def load_sources(cfg, dumps):
    """Reads each source's dump once: all records, the in-scope ones, and the snapshot hour."""
    data = {}
    for s in cfg["sources"]:
        files = dump_files(dumps, s["resource"])
        total, scoped, snaps = 0, [], set()
        for doc, rec in iter_dump(files, s["resource"]):
            total += 1
            snaps.add(doc.get("@dayIndex"))
            if in_scope(rec, s.get("filter")):
                scoped.append(rec)
        times = [t for t in map(snapshot_time, snaps) if t]
        data[s["name"]] = {"files": files, "records": total, "scoped": scoped,
                           "snapshot": min(times) if times else None}
    return data


def source_health(cfg, data, now):
    cutoff = now - timedelta(days=cfg["staleDays"])
    rows = []
    for s in cfg["sources"]:
        d = data[s["name"]]
        seen = [to_dt(get_path(r, s["lastSeen"])) for r in d["scoped"]]
        active = sum(1 for t in seen if t and t > cutoff)
        hosts = {norm_host(get_path(r, s["host"])) for r in d["scoped"]} - {""}
        problems = []
        if not d["files"]:
            problems.append("no dump downloaded")
        elif not d["records"]:
            problems.append("dump is empty")
        elif not d["scoped"]:
            problems.append("no records match the filter")
        elif not active:
            problems.append(f"no record seen in the last {cfg['staleDays']} days")
        elif not hosts:
            problems.append(f"'{s['host']}' is empty on every record")
        if d["snapshot"] and now - d["snapshot"] > SNAPSHOT_MAX_AGE:
            problems.append(f"snapshot is {int((now - d['snapshot']).total_seconds() // 3600)} hours old")
        rows.append({
            "source": s["name"], "resource": s["resource"], "required": s["required"],
            "dumps": [f.name[:-len(".jsonl.gz")] for f in d["files"]],
            "records": d["records"], "inScope": len(d["scoped"]), "active": active, "hosts": len(hosts),
            "snapshot": d["snapshot"].strftime("%Y-%m-%dT%H:%MZ") if d["snapshot"] else None,
            "problems": problems,
        })
    return rows


def print_health(rows, out=sys.stdout):
    print(f"{'source':<14}{'records':>9}{'in scope':>10}{'active':>8}{'hosts':>7}  snapshot           dumps", file=out)
    for r in rows:
        print(f"{r['source']:<14}{r['records']:>9}{r['inScope']:>10}{r['active']:>8}{r['hosts']:>7}  "
              f"{r['snapshot'] or '-':<18} {', '.join(r['dumps']) or '-'}", file=out)
    for r in rows:
        for p in r["problems"]:
            print(f"{'PROBLEM' if r['required'] else 'warning'}: {r['source']} ({r['resource']}): {p}", file=out)


def cmd_check(args):
    cfg = load_config(args.sources)
    rows = source_health(cfg, load_sources(cfg, args.dumps), datetime.now(timezone.utc))
    print_health(rows)
    if any(r["problems"] and r["required"] for r in rows):
        sys.exit(1)


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
        sys.exit(f"no dump files in {Path(args.dumps) / args.resource}")
    stats = defaultdict(lambda: {"filled": 0, "types": Counter(), "values": Counter()})
    n = 0
    for _, rec in iter_dump(files, args.resource):
        n += 1
        for path, v in flatten(rec).items():
            st = stats[path]
            if v not in (None, "", [], {}):
                st["filled"] += 1
                st["values"][json.dumps(v)[:48] if isinstance(v, (list, dict, bool)) else str(v)[:48]] += 1
            st["types"][type(v).__name__] += 1
        if n >= args.sample:
            break
    print(f"{args.resource}: {n} records read from {len(files)} file(s)")
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

def device_class(os_name):
    o = (os_name or "").lower()
    for cls, words in CLASS_KEYWORDS:
        if any(w in o for w in words):
            return cls
    return DEFAULT_CLASS


def classify(cfg, codes):
    """codes: {source name: 0 missing / 1 stale / 2 active} -> (status, issue key or None)."""
    sources = cfg["sources"]
    if not any(codes[s["name"]] == 2 for s in sources):
        return "Inactive", None
    missing = tuple(s["name"] for s in sources if s["required"] and codes[s["name"]] == 0)
    if missing:
        return "Missing agent", ("missing", missing)
    stale = tuple(s["name"] for s in sources if s["required"] and codes[s["name"]] == 1)
    if stale:
        return "Agent not reporting", ("stale", stale)
    return "Compliant", None


def build_devices(cfg, data, now):
    """One record per device. Records carrying a device ID the idAuthority source knows are filed
    under the authority's hostname (renamed machines line up); everything else matches on the
    normalized hostname. A source is active for a device if any of its records was seen within
    staleDays, stale if it only holds older records, missing if it holds none."""
    sources = cfg["sources"]
    cutoff = now - timedelta(days=cfg["staleDays"])
    authority = next((s for s in sources if s.get("idAuthority")), None)
    name_by_id = {}
    if authority:
        for r in data[authority["name"]]["scoped"]:
            host, did = norm_host(get_path(r, authority["host"])), norm_id(get_path(r, authority["deviceId"]))
            if host and did:
                name_by_id.setdefault(did, host)

    by_host = {}
    for s in sources:
        n = s["name"]
        for r in data[n]["scoped"]:
            host = norm_host(get_path(r, s["host"]))
            if not host:
                continue
            if s.get("deviceId"):
                host = name_by_id.get(norm_id(get_path(r, s["deviceId"])), host)
            d = by_host.setdefault(host, {"host": host, "codes": {}, "seen": {}, "osBy": {}})
            seen = to_dt(get_path(r, s["lastSeen"]))
            d["codes"][n] = max(d["codes"].get(n, 0), 2 if seen and seen > cutoff else 1)
            if seen and (n not in d["seen"] or seen > d["seen"][n]):
                d["seen"][n] = seen
            os_value = get_path(r, s["os"])
            if os_value not in (None, "") and n not in d["osBy"]:
                d["osBy"][n] = str(os_value)

    devices = []
    for d in by_host.values():
        codes = {s["name"]: d["codes"].get(s["name"], 0) for s in sources}
        os_name = next((d["osBy"][s["name"]] for s in sources if s["name"] in d["osBy"]), "")
        status, issue = classify(cfg, codes)
        devices.append({"host": d["host"], "os": os_name, "deviceClass": device_class(os_name),
                        "codes": codes, "seen": d["seen"], "status": status, "issue": issue})
    return devices


def join_and(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def pct(n, d):
    return 0 if d == 0 else round(100.0 * n / d, 1)


def issue_label(cfg, issue):
    kind, names = issue
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
    return (0 if kind == "missing" else 1, len(names), [order[n] for n in names])


def active_in(cfg, d):
    return [s["name"] for s in cfg["sources"] if d["codes"][s["name"]] == 2]


def compute_facts(cfg, devices, health, account, generated):
    sources = cfg["sources"]
    names = [s["name"] for s in sources]
    references = [s["name"] for s in sources if not s["required"]]
    totals = Counter()
    coverage = {n: Counter() for n in names}
    issues = defaultdict(lambda: {"devices": 0, "byClass": Counter(), "notInReference": Counter()})
    patterns = Counter()
    inactive = Counter()
    by_class = defaultdict(Counter)
    listed = []
    for d in devices:
        totals[d["status"]] += 1
        if d["status"] == "Inactive":
            inactive[tuple(n for n in names if d["codes"][n])] += 1
            continue
        by_class[d["deviceClass"]][d["status"]] += 1
        patterns[tuple(active_in(cfg, d))] += 1
        for n in names:
            coverage[n][STATES[d["codes"][n]]] += 1
        if d["issue"]:
            i = issues[d["issue"]]
            i["devices"] += 1
            i["byClass"][d["deviceClass"]] += 1
            for n in references:
                if d["codes"][n] == 0:
                    i["notInReference"][n] += 1
            listed.append({
                "host": d["host"], "os": d["os"], "deviceClass": d["deviceClass"], "status": d["status"],
                "issue": issue_label(cfg, d["issue"]),
                "states": {n: STATES[d["codes"][n]] for n in names},
                "lastSeen": {n: d["seen"][n].strftime("%Y-%m-%d") if n in d["seen"] else "" for n in names},
            })

    active = sum(totals[k] for k in ("Compliant", "Missing agent", "Agent not reporting"))
    snapshots = [h["snapshot"] for h in health if h["snapshot"]]
    ordered = sorted(issues, key=lambda k: issue_sort_key(cfg, k))
    return {
        "account": account,
        "generatedAt": generated.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataAsOf": min(snapshots) if snapshots else None,
        "staleDays": cfg["staleDays"],
        "sources": [{"name": s["name"], "label": s["label"], "required": s["required"]} for s in sources],
        "sourceHealth": health,
        "totals": {
            "activeDevices": active,
            "compliant": totals["Compliant"],
            "missingAgent": totals["Missing agent"],
            "agentNotReporting": totals["Agent not reporting"],
            "inactive": totals["Inactive"],
            "compliancePct": pct(totals["Compliant"], active),
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
        } for k in ordered],
        "presencePatterns": [{"activeIn": list(k), "devices": v} for k, v in patterns.most_common()],
        "inactiveByPresence": [{"presentIn": list(k), "devices": v} for k, v in inactive.most_common()],
        "byDeviceClass": {c: dict(v) for c, v in by_class.items()},
        "deviceList": {"total": len(listed)},
        "_devices": listed,
    }


def write_devices_csv(cfg, devices, path):
    """Every device, one row each: the full inventory behind the report."""
    order = {"Missing agent": 0, "Agent not reporting": 1, "Compliant": 2, "Inactive": 3}
    names = [s["name"] for s in cfg["sources"]]
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["host", "os", "deviceClass", "status", "detail", "activeIn"]
                   + [c for n in names for c in (n, f"{n}_lastSeen")])
        for d in sorted(devices, key=lambda d: (order[d["status"]], d["host"])):
            w.writerow([d["host"], d["os"], d["deviceClass"], d["status"],
                        issue_label(cfg, d["issue"]) if d["issue"] else "", "+".join(active_in(cfg, d))]
                       + [c for n in names for c in (STATES[d["codes"][n]],
                                                      d["seen"][n].strftime("%Y-%m-%d %H:%M") if n in d["seen"] else "")])


# ---- HTML ------------------------------------------------------------------

GREEN, AMBER, RED, BLUE, NAVY = "var(--green)", "var(--amber)", "var(--red)", "var(--blue)", "var(--navy)"
NEUTRAL = "#c9ced8"
TONE_COLOUR = {"urgent": RED, "normal": BLUE, "routine": NAVY}
CLASS_LABELS = [("Workstation", "Workstations"), ("Server", "Servers"), ("Linux", "Linux hosts")]
CLASS_NOUNS = {"Server": ("server", "servers"), "Linux": ("Linux host", "Linux hosts")}


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


def default_narrative(cfg, f):
    t = f["totals"]
    label = {s["name"]: s["label"] for s in cfg["sources"]}
    required = [s for s in cfg["sources"] if s["required"]]
    req_labels = [s["label"] for s in required]
    if len(required) == 1:
        have = req_labels[0]
    elif len(required) == 2:
        have = f"both {join_and(req_labels)}"
    else:
        have = f"all of {join_and(req_labels)}"
    days = f["staleDays"]
    p1 = (f"Of <strong>{t['activeDevices']:,} devices</strong> active in the last {days} days, "
          f"<strong>{t['compliant']:,} ({t['compliancePct']}%)</strong> have {esc(have)} installed and reporting. "
          f"<strong>{t['missingAgent']}</strong> devices are missing at least one required agent, and "
          f"<strong>{t['agentNotReporting']}</strong> have an agent that has stopped reporting.")
    cov = {c["source"]: c for c in f["coverage"]}
    rates = [f"{esc(s['label'])} is active on {cov[s['name']]['active']:,} devices ({cov[s['name']]['coveragePct']}%)"
             for s in required]
    p2 = join_and(rates) + "."
    missing = [i for i in f["issues"] if i["kind"] == "missing"]
    if missing:
        p2 += " By gap: " + join_and(f"{i['devices']} {esc(i['label'][0].lower() + i['label'][1:])}" for i in missing) + "."
    servers = sum(i["byClass"].get("Server", 0) for i in f["issues"])
    if servers:
        p2 += f" {servers} of the {f['deviceList']['total']} devices needing attention are servers."

    steps = []
    for rank, i in enumerate(sorted(f["issues"], key=lambda i: -i["devices"])):
        names = [label[n] for n in i["sources"]]
        note = class_note(i["byClass"])
        note = f" ({note})" if note else ""
        refs = "".join(f"; {n} of them are not in {esc(label[r])}" for r, n in i["listedNotInReference"].items() if n)
        if i["kind"] == "missing" and len(names) == 1:
            urgent = len(steps) < 2
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
    return {"summary": [p1, p2], "nextSteps": steps}


def render_html(cfg, f, narrative, title, customer):
    sources = cfg["sources"]
    t = f["totals"]
    days = f["staleDays"]
    active = t["activeDevices"]
    cov = {c["source"]: c for c in f["coverage"]}
    refs = [s for s in sources if not s["required"]]
    n_req = sum(1 for s in sources if s["required"])
    generated = datetime.strptime(f["generatedAt"], "%Y-%m-%dT%H:%M:%SZ")
    as_of = datetime.strptime(f["dataAsOf"], "%Y-%m-%dT%H:%MZ") if f.get("dataAsOf") else generated

    kpis = f"""
<div class="kpi"><div class="kpi-label">Active devices</div><div class="kpi-value navy">{active:,}</div><div class="kpi-note">last {days} days</div></div>
<div class="kpi"><div class="kpi-label">Fully covered</div><div class="kpi-value green">{t['compliant']:,}</div><div class="kpi-note">{t['compliancePct']}% of active</div></div>
<div class="kpi"><div class="kpi-label">Missing an agent</div><div class="kpi-value red">{t['missingAgent']}</div><div class="kpi-note">{'one or both agents' if n_req == 2 else 'one or more agents'}</div></div>
<div class="kpi"><div class="kpi-label">Not reporting</div><div class="kpi-value amber">{t['agentNotReporting']}</div><div class="kpi-note">silent &gt; {days} days</div></div>
<div class="kpi"><div class="kpi-label">Inactive records</div><div class="kpi-value">{t['inactive']}</div><div class="kpi-note">excluded from totals</div></div>
"""

    # Coverage by source
    ref_legend = f"Not in {refs[0]['label']}" if len(refs) == 1 else "Not in inventory"
    rows = []
    for s in sources:
        c = cov[s["name"]]
        total = c["active"] + c["stale"] + c["missing"]
        miss_note = "missing" if s["required"] else f"not in {s['label']}"
        bar = stacked_bar([(c["active"], GREEN, "active"), (c["stale"], AMBER, "stale"),
                           (c["missing"], RED if s["required"] else NEUTRAL, miss_note)], total)
        rows.append(f"""
      <div class="src-row">
        <div class="src-head"><span class="src-name">{esc(s['label'])}</span><span class="tag">{'required' if s['required'] else 'reference only'}</span><span class="src-pct">{c['coveragePct']}%</span></div>
        {bar}
        <div class="src-note">{c['active']:,} active · {c['stale']} stale · {c['missing']} {esc(miss_note)}</div>
      </div>""")
    legend_items = [(GREEN, "Active"), (AMBER, "Stale"), (RED, "Missing")] + ([(NEUTRAL, ref_legend)] if refs else [])
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
        <div class="bar-track"><div class="bar-fill" style="width:{100.0 * i['devices'] / max_issue:.1f}%;background:{RED if i['kind'] == 'missing' else AMBER}"></div></div>
        <div class="ibar-val">{i['devices']}</div>
      </div>""")
    if not bars:
        bars.append('<div class="src-note">Every active device has all required agents reporting.</div>')
    panel_issues = f"""
<div class="panel col-6">
  <div class="panel-header"><h2 class="panel-title">Devices requiring attention</h2><span class="panel-subtitle">{f['deviceList']['total']} devices{' · listed on page 2' if f['deviceList']['total'] else ''}</span></div>
  <div class="ibars">{''.join(bars)}</div>
</div>"""

    # Presence matrix
    required = [s for s in sources if s["required"]]
    max_pat = max([p["devices"] for p in f["presencePatterns"]] or [1])
    prow = []
    for p in f["presencePatterns"]:
        present = set(p["activeIn"])
        dots = "".join(f'<td class="dotc"><span class="dot{" on" if s["name"] in present else ""}"></span></td>' for s in sources)
        absent = [s["label"] for s in required if s["name"] not in present]
        if not absent:
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
    panel_patterns = f"""
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
        <div class="src-head"><span class="src-name">{cls_label}</span><span class="src-pct">{pct(ok, total)}%</span></div>
        {bar}
        <div class="src-note">{ok:,} of {total:,} covered · {miss} missing{f" · {silent} silent" if silent else ''}</div>
      </div>""")
    panel_types = f"""
<div class="panel {'col-12 types-wide' if wide else 'col-4'}">
  <div class="panel-header"><h2 class="panel-title">By device type</h2><span class="panel-subtitle">% fully covered</span></div>
  {legend([(GREEN, 'Covered'), (AMBER, 'Silent'), (RED, 'Missing')])}
  <div class="type-rows">{''.join(crow)}</div>
</div>"""

    summary_html = "".join(f"<p>{p}</p>" for p in narrative["summary"])
    steps_html = "".join(
        f'<div class="ns-item"><div class="ns-num" style="background:{TONE_COLOUR.get(s.get("tone"), BLUE)}">{n}</div><div>'
        f'<div class="ns-when">{esc(s.get("when", ""))}</div><div class="ns-act">{s["text"]}</div></div></div>'
        for n, s in enumerate(narrative["nextSteps"][:6], 1))

    # Method
    authority = next((s for s in sources if s.get("idAuthority")), None)
    host_rule = 'the hostname, compared case-insensitively with the domain suffix and any trailing "$" removed'
    if authority:
        id_sources = [s["label"] for s in sources if s.get("deviceId")]
        matching = (f"{esc(join_and(id_sources))} records are matched on the {esc(authority['label'])} device ID, so renamed "
                    f"machines line up. All other matching uses {esc(host_rule)}.")
    else:
        matching = f"Devices are matched on {esc(host_rule)}."
    req_labels = [s["label"] for s in required]
    req_text = f"{esc(join_and(req_labels))} {'is' if len(req_labels) == 1 else 'are'} required on every active device."
    if refs:
        ref_labels = [s["label"] for s in refs]
        one = len(ref_labels) == 1
        req_text += (f" {esc(join_and(ref_labels))} {'is a reference inventory' if one else 'are reference inventories'} only, "
                     f"so a device that is absent from {'it' if one else 'them'} is not counted as a gap for that reason.")
    method = f"""
<div class="panel col-12 page-break">
  <div class="panel-header"><h2 class="panel-title">How this report is built</h2><span class="panel-subtitle">Inventory snapshot {as_of.strftime('%d %b %Y %H:00 UTC')} · account {esc(f['account'])}</span></div>
  <div class="method">
    <div><b>Sources.</b> {esc('; '.join(s['scope'] for s in sources))}.</div>
    <div><b>Matching.</b> {matching}</div>
    <div><b>Active / stale.</b> A source counts a device as <i>active</i> if it has seen it within the last {days} days, and <i>stale</i> if it
    holds a record that is older. Devices that are not active in any source are <i>inactive</i> and excluded from all totals.</div>
    <div><b>Required.</b> {req_text}</div>
  </div>
</div>"""

    # Device list
    state_colour = {"active": GREEN, "stale": AMBER, "missing": RED}
    body = []
    for i in f["issues"]:
        group = [d for d in f["_devices"] if d["issue"] == i["label"]]
        if not group:
            continue
        body.append(f'<tr class="grp"><td colspan="{2 + len(sources)}">{esc(i["label"])} <span>({len(group)})</span></td></tr>')
        for d in group:
            badge = f'<span class="cls">{d["deviceClass"]}</span>' if d["deviceClass"] != DEFAULT_CLASS else ""
            cells = []
            for s in sources:
                state, seen = d["states"][s["name"]], d["lastSeen"][s["name"]]
                colour = state_colour[state] if (s["required"] or state != "missing") else NEUTRAL
                text = {"active": "Active", "stale": "Stale", "missing": missing_label(s)}[state]
                when = f' <span class="when">{short_date(seen)}</span>' if state == "stale" and seen else ""
                cells.append(f'<td><span class="st"><i style="background:{colour}"></i>{esc(text)}{when}</span></td>')
            body.append(f'<tr><td class="host">{esc(d["host"])}</td><td>{esc(pretty_os(d["os"]))}{badge}</td>{"".join(cells)}</tr>')
    dl = f["deviceList"]
    listed_note = f"{dl['listed']} of {dl['total']} devices listed" if dl["listed"] < dl["total"] else f"{dl['total']} devices"
    src_w = min(96, (700 - 150 - 140) // max(1, len(sources)))
    device_list = "" if not body else f"""
<div class="panel col-12">
  <div class="panel-header"><h2 class="panel-title">Devices requiring attention</h2><span class="panel-subtitle">{listed_note} · dates show when a stale agent last reported</span></div>
  <table class="data devlist">
    <colgroup><col style="width:150px"><col>{''.join(f'<col style="width:{src_w}px">' for _ in sources)}</colgroup>
    <thead><tr><th>Device</th><th>Operating system</th>{''.join(f'<th>{esc(s["label"])}</th>' for s in sources)}</tr></thead>
    <tbody>{''.join(body)}</tbody>
  </table>
</div>"""

    subtitle = f"{join_and(s['label'] for s in sources)} device coverage"
    fills = {
        "{{report_title}}": esc(title),
        "{{report_subtitle}}": esc(f"{customer} · {subtitle}" if customer else subtitle),
        "{{report_date}}": generated.strftime("%d %b %Y, %H:%M UTC"),
        "{{report_meta}}": f" · Account {esc(f['account'])} · Activity window: last {days} days",
        "{{kpi_strip}}": kpis,
        "{{summary_html}}": summary_html,
        "{{main_grid}}": panel_sources + panel_issues + panel_patterns + panel_types,
        "{{next_steps_items}}": steps_html,
        "{{appendix}}": method + device_list,
        "{{footer_page_info}}": f"Fluency Report · {esc(title)}",
        "{{footer_data_date}}": as_of.strftime("%d %b %Y, %H:00 UTC"),
    }
    tpl = (SKILL_DIR / "assets" / "report_template.html").read_text()
    for k, v in fills.items():
        tpl = tpl.replace(k, v)
    return tpl


def cmd_render(args):
    cfg = load_config(args.sources)
    now = (datetime.strptime(args.as_of, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if args.as_of
           else datetime.now(timezone.utc).replace(microsecond=0))
    data = load_sources(cfg, args.dumps)
    health = source_health(cfg, data, now)
    print_health(health)
    if any(h["problems"] and h["required"] for h in health) and not args.allow_unhealthy:
        sys.exit("A required source is unhealthy (see above), so the report would blame devices for a data "
                 "problem. Fix the dumps, or pass --allow-unhealthy to render anyway.")

    devices = build_devices(cfg, data, now)
    f = compute_facts(cfg, devices, health, args.account, now)
    rank = {i["label"]: n for n, i in enumerate(f["issues"])}
    class_rank = {"Server": 0, "Linux": 1, DEFAULT_CLASS: 2}
    f["_devices"].sort(key=lambda d: (rank[d["issue"]], class_rank.get(d["deviceClass"], 3), d["host"]))
    if args.max_listed and len(f["_devices"]) > args.max_listed:
        f["_devices"] = f["_devices"][:args.max_listed]
    f["deviceList"]["listed"] = len(f["_devices"])

    narrative = default_narrative(cfg, f)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    narrative_path = Path(args.narrative) if args.narrative else work / "narrative.json"
    if narrative_path.exists():
        custom = json.loads(narrative_path.read_text())
        narrative.update({k: v for k, v in custom.items() if k in ("summary", "nextSteps") and v})
        print(f"narrative: {narrative_path}")
    else:
        print("narrative: default (write narrative.json in the work dir to replace it)")

    facts = {k: v for k, v in f.items() if not k.startswith("_")}
    facts["defaultNarrative"] = default_narrative(cfg, f)
    (work / "facts.json").write_text(json.dumps(facts, indent=2) + "\n")
    write_devices_csv(cfg, devices, work / "devices.csv")

    out = Path(args.out) if args.out else work
    (out / "assets").mkdir(parents=True, exist_ok=True)
    logo = out / "assets" / "logo2.png"
    if not logo.exists():
        shutil.copyfile(SKILL_DIR / "assets" / "logo2.png", logo)
    html_path = out / f"{args.stem}.html"
    html_path.write_text(render_html(cfg, f, narrative, args.title, args.customer))

    t = f["totals"]
    print(f"wrote {html_path}, {work / 'facts.json'} and {work / 'devices.csv'} ({len(devices)} devices)")
    print(f"active {t['activeDevices']} · compliant {t['compliant']} ({t['compliancePct']}%) · missing {t['missingAgent']}"
          f" · not reporting {t['agentNotReporting']} · inactive {t['inactive']}")
    for i in f["issues"]:
        print(f"  {i['label']}: {i['devices']}")
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
    r.add_argument("--allow-unhealthy", action="store_true", help="render even if a required source looks broken")
    r.set_defaults(func=cmd_render)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
