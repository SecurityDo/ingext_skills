#!/usr/bin/env python3
"""Turn Proofpoint event rows into a structured email verdict.

Reads one or more kql_search results over the Proofpoint table (every column prefixed
"@proofpoint."), de-duplicates re-emitted rows, and works out sender, recipients, direction,
delivery, clicks, threats, attachments, blast radius, timeline and routing from the event fields
alone. Direction comes from the participants, never from the Proofpoint cluster label.

  proofpoint_verdict.py --events EVENTS.json [--events MORE.json ...] [--related RELATED.json]
                        [--internal-domain example.com ...] [--case-key user@example.com]
                        [--out verdict.json]

--events   kql_search result(s) for the message under investigation (one GUID, QID or messageID)
--related  kql_search result(s) for other messages that share a threat id, threat URL, sender or
           subject; used only for the blast-radius section
Prints a plain-language summary; --out also writes the full structure.
"""
import argparse, datetime, json, re, sys

PREFIX = "@proofpoint."
FREE_MAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com",
             "icloud.com", "aol.com", "proton.me", "protonmail.com"}
EMAIL_RE = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}")


def load_rows(path):
    """kql_search result -> list of {"@timestamp": ..., "pp": {field: value}}."""
    try:
        with open(path) as f:
            raw = json.load(f)
        tables = raw["data"]["Tables"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        sys.exit("%s is not a kql_search result: %s" % (path, e))
    table = tables[0]
    cols = [c["ColumnName"] for c in table["Columns"]]
    out = []
    for row in table["Rows"]:
        rec = dict(zip(cols, row))
        pp = {}
        for k, v in rec.items():
            if k.startswith(PREFIX):
                if isinstance(v, str) and v[:1] in "[{":
                    try:
                        v = json.loads(v)
                    except ValueError:
                        pass
                pp[k[len(PREFIX):]] = v
        if pp:
            out.append({"@timestamp": rec.get("timestamp"), "pp": pp})
    return out


def dedupe_rows(rows):
    seen, keep = set(), []
    for r in rows:
        k = json.dumps(r, sort_keys=True, default=str)
        if k not in seen:
            seen.add(k)
            keep.append(r)
    return keep, len(rows) - len(keep)


def as_list(v):
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [x for x in v if x not in (None, "")]
    return [v]


def dedupe(vals):
    out = []
    for v in vals:
        if v not in out:
            out.append(v)
    return out


def emails(vals):
    found = []
    for v in vals:
        for m in EMAIL_RE.findall(str(v)):
            m = m.strip().lower()
            if m not in found:
                found.append(m)
    return found


def domain(addr):
    return addr.rsplit("@", 1)[1].strip().lower() if "@" in addr else None


def classify(addr, internal):
    d = domain(addr)
    inside = bool(d and d in internal)
    return {"address": addr, "domain": d, "internal": inside, "external": not inside, "free_mail": bool(d and d in FREE_MAIL)}


def threats_of(pp):
    t = pp.get("threatsInfoMap")
    if isinstance(t, dict):
        return [t]
    return [x for x in t if isinstance(x, dict)] if isinstance(t, list) else []


def parts_of(pp):
    return [{"filename": p.get("filename"), "content_type": p.get("contentType") or p.get("oContentType"),
             "disposition": p.get("disposition"), "md5": p.get("md5"), "sha256": p.get("sha256"),
             "sandbox_status": p.get("sandboxStatus")}
            for p in (pp.get("messageParts") or []) if isinstance(p, dict)]


def click_hits(value, prefix=""):
    hits = []
    if isinstance(value, dict):
        for k, child in value.items():
            path = "%s.%s" % (prefix, k) if prefix else str(k)
            if re.search(r"click", str(k), re.I) and child not in (None, "", [], False):
                hits.append({"path": path, "value": child})
            hits.extend(click_hits(child, path))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            hits.extend(click_hits(child, "%s[%d]" % (prefix, i)))
    return hits


def delivery(pps):
    ev, contra, delivered, quarantined = [], [], False, False
    for pp in pps:
        t = str(pp.get("type") or "")
        if "deliver" in t.lower():
            delivered = True
            ev.append("type=" + t)
        if "block" in t.lower() or "quarantin" in t.lower():
            quarantined = True
            contra.append("type=" + t)
        for f in ("quarantineFolder", "quarantineRule"):
            if pp.get(f):
                quarantined = True
                contra.append("%s=%s" % (f, pp[f]))
        for f in ("disposition", "finalAction", "deliveryStatus"):
            a = str(pp.get(f) or "").lower()
            if any(w in a for w in ("quarantine", "block", "drop")):
                quarantined = True
                contra.append("%s=%s" % (f, pp[f]))
            elif any(w in a for w in ("deliver", "allow", "relay")):
                delivered = True
                ev.append("%s=%s" % (f, pp[f]))
        for route in as_list(pp.get("policyRoutes")):
            if "allow_relay" in str(route):
                ev.append("policyRoutes contains " + str(route))
    if delivered and quarantined:
        # one message can be blocked for some recipients and delivered to others
        return {"verdict": "mixed", "confidence": "medium", "delivered_evidence": dedupe(ev), "blocked_evidence": dedupe(contra)}
    if quarantined:
        return {"verdict": False, "confidence": "high", "evidence": dedupe(contra)}
    if delivered:
        return {"verdict": True, "confidence": "high", "evidence": dedupe(ev)}
    return {"verdict": "unknown", "confidence": "none", "evidence": []}


def direction(senders, recips, internal, source, routing):
    if not internal:
        return {"verdict": "unknown", "confidence": "none", "evidence": ["No internal domain source was available."], "routing_evidence": routing}
    s_in = any((domain(e) or "") in internal for e in senders)
    r_in = any((domain(e) or "") in internal for e in recips)
    r_out = any((domain(e) or "") not in internal for e in recips)
    conf = "high" if source == "provided" else "medium"
    if s_in and r_out and not r_in:
        v = "outbound"
    elif not s_in and r_in:
        v = "inbound"
    elif s_in and r_in and not r_out:
        v = "internal"
    elif s_in and r_in and r_out:
        v = "mixed_internal_and_external"
    else:
        v, conf = "external_or_unknown", "low"
    return {"verdict": v, "confidence": conf, "routing_evidence": routing,
            "evidence": ["internal_domains_source=%s" % source, "sender_internal=%s" % s_in, "recipient_internal=%s" % r_in, "recipient_external=%s" % r_out]}


def contradictions(d, routing):
    text = " ".join(str(x).lower() for x in routing)
    out = []
    if d["verdict"] in ("outbound", "mixed_internal_and_external") and "inbound" in text:
        out.append("Participants show an internal sender and external recipients, but the routing label says inbound.")
    if d["verdict"] == "inbound" and "outbound" in text:
        out.append("Participants show an external sender and internal recipients, but the routing label says outbound.")
    return out


def local_user(case_key, senders, rcpt_detail, internal, d):
    in_senders = [e for e in senders if (domain(e) or "") in internal]
    entries = [x for k in ("to", "cc", "bcc", "recipient") for x in rcpt_detail.get(k, [])]
    in_recips = dedupe([x["address"] for x in entries if x["internal"]])
    key_emails = emails([case_key]) if case_key else []
    key_external = any((domain(e) or "") not in internal for e in key_emails) if internal and key_emails else None
    if in_senders:
        primary, role = in_senders[0], "sender"
    elif in_recips:
        primary, role = in_recips[0], "recipient"
    else:
        primary, role = None, "unknown"
    return {"primary_local_user": primary, "primary_role": role, "internal_senders": in_senders, "internal_recipients": in_recips,
            "case_key": case_key, "case_key_is_external": key_external, "pivot_recommended": bool(key_external and in_senders)}


def summarize(rows, internal_arg, case_key, related_rows):
    pps = [r["pp"] for r in rows]
    senders_raw = [v for pp in pps for f in ("sender", "fromAddress", "headerFrom") for v in as_list(pp.get(f))]
    rcpt_raw = {f: [v for pp in pps for v in as_list(pp.get(f))] for f in ("recipient", "toAddresses", "ccAddresses", "bccAddresses", "replyToAddress", "headerReplyTo")}
    sender_emails = emails(senders_raw)
    all_rcpt = emails(rcpt_raw["recipient"] + rcpt_raw["toAddresses"] + rcpt_raw["ccAddresses"] + rcpt_raw["bccAddresses"])
    if internal_arg:
        internal, source = {x.strip().lower() for x in internal_arg if x.strip()}, "provided"
    else:
        internal = {d for e in sender_emails for d in [domain(e)] if d and d not in FREE_MAIL}
        source = "derived_from_sender_domains"
    rcpt = {"to": [classify(e, internal) for e in emails(rcpt_raw["toAddresses"])],
            "cc": [classify(e, internal) for e in emails(rcpt_raw["ccAddresses"])],
            "bcc": [classify(e, internal) for e in emails(rcpt_raw["bccAddresses"])],
            "recipient": [classify(e, internal) for e in emails(rcpt_raw["recipient"])],
            "reply_to": [classify(e, internal) for e in emails(rcpt_raw["replyToAddress"] + rcpt_raw["headerReplyTo"])]}
    routing = []
    for pp in pps:
        for f in ("cluster", "policyRoutes", "modulesRun"):
            if pp.get(f):
                routing.append("%s=%s" % (f, pp[f]))
    routing = dedupe(routing)
    dirn = direction(sender_emails, all_rcpt, internal, source, routing)

    ids = {}
    for pp in pps:
        ident = {"GUID": pp.get("GUID"), "QID": pp.get("QID"), "messageID": pp.get("messageID"),
                 "threatIDs": dedupe([t.get("threatID") for t in threats_of(pp) if t.get("threatID")]),
                 "threatUrls": dedupe([t.get("threatUrl") for t in threats_of(pp) if t.get("threatUrl")])}
        ids.setdefault(json.dumps(ident, sort_keys=True), dict(ident, record_count=0))["record_count"] += 1

    threats = dedupe([{"classification": t.get("classification"), "detection_type": t.get("detectionType"), "threat_type": t.get("threatType"),
                       "threat": t.get("threat"), "threat_id": t.get("threatID"), "threat_status": t.get("threatStatus"),
                       "threat_time": t.get("threatTime"), "threat_url": t.get("threatUrl"), "campaign_id": t.get("campaignID") or t.get("campaignId")}
                      for pp in pps for t in threats_of(pp)])
    clicks = [h for r in rows for h in click_hits(r["pp"], "@proofpoint")]
    click_types = dedupe([str(pp.get("type")) for pp in pps if str(pp.get("type") or "").lower().startswith("click")])
    atts = dedupe([a for pp in pps for a in parts_of(pp)])
    scores = {k: dedupe([pp[k + "Score"] for pp in pps if pp.get(k + "Score") is not None]) for k in ("impostor", "phish", "spam", "malware")}

    blast = None
    if related_rows is not None:
        rp = [r["pp"] for r in related_rows]
        blast = {"records": len(rp), "messages": len(dedupe([(p.get("GUID"), p.get("QID")) for p in rp])),
                 "senders": dedupe(emails([v for p in rp for f in ("sender", "fromAddress", "headerFrom") for v in as_list(p.get(f))])),
                 "recipients": dedupe(emails([v for p in rp for f in ("recipient", "toAddresses") for v in as_list(p.get(f))])),
                 "types": {t: sum(1 for p in rp if p.get("type") == t) for t in dedupe([p.get("type") for p in rp])}}

    return {
        "record_count": len(rows),
        "message_identities": list(ids.values()),
        "sender_authentication": {"sender_emails": sender_emails, "sender_ips": dedupe([pp["senderIP"] for pp in pps if pp.get("senderIP")]),
                                  "header_from": dedupe([pp["headerFrom"] for pp in pps if pp.get("headerFrom")]),
                                  "auth_fields": {k: dedupe([pp[k] for pp in pps if pp.get(k)]) for k in ("spf", "dkim", "dmarc")},
                                  "scores": scores},
        "recipients": rcpt,
        "local_user_context": local_user(case_key, sender_emails, rcpt, internal, dirn),
        "direction": dirn,
        "delivery": delivery(pps),
        "clicks": {"verdict": True if clicks or click_types else "unknown", "evidence": clicks, "click_event_types": click_types,
                   "note": None if (clicks or click_types) else "No click-related fields were present in the captured records."},
        "threats": threats,
        "attachments": atts,
        "blast_radius": blast,
        "timeline": [{"event_timestamp": r["@timestamp"], "message_time": r["pp"].get("messageTime"),
                      "threat_times": [t.get("threatTime") for t in threats_of(r["pp"]) if t.get("threatTime")]} for r in rows],
        "subject": dedupe([pp["subject"] for pp in pps if pp.get("subject")]),
        "routing": {"clusters": dedupe([pp["cluster"] for pp in pps if pp.get("cluster")]),
                    "policy_routes": dedupe([r for pp in pps for r in as_list(pp.get("policyRoutes"))]),
                    "modules_run": dedupe([m for pp in pps for m in as_list(pp.get("modulesRun"))]),
                    "contradictions": contradictions(dirn, routing),
                    "note": "Routing labels are not used as direction authority."},
        "internal_domains": {"domains": sorted(internal), "source": source},
    }


def parse_time(t):
    try:
        return datetime.datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except ValueError:
        return None


def threat_age_days(v):
    """Days between each threat's threatTime and the first event; a threat far older than the message is an indicator that was reused, not a new one."""
    ev = [parse_time(x["event_timestamp"]) for x in v["timeline"] if x.get("event_timestamp")]
    first = min((e for e in ev if e), default=None)
    out = {}
    for t in v["threats"]:
        tt = parse_time(t.get("threat_time"))
        if first and tt:
            out[t["threat_id"]] = (first - tt).days
    return out


def words(v):
    if v is True:
        return "delivered"
    if v is False:
        return "blocked or quarantined"
    return str(v)


def render(v, dups):
    L = []
    d, dl, lu = v["direction"], v["delivery"], v["local_user_context"]
    L.append("Records: %d (%d exact duplicate row(s) removed). Subject: %s" % (v["record_count"], dups, "; ".join(v["subject"]) or "n/a"))
    L.append("Sender: %s | sender IP: %s" % (", ".join(v["sender_authentication"]["sender_emails"]) or "n/a", ", ".join(v["sender_authentication"]["sender_ips"]) or "n/a"))
    rc = v["recipients"]
    L.append("To: %s | CC: %s | BCC: %s" % tuple(", ".join("%s (%s)" % (x["address"], "internal" if x["internal"] else "external") for x in rc[k]) or "empty" for k in ("to", "cc", "bcc")))
    L.append("Direction: %s (%s confidence; internal domains %s, %s)" % (d["verdict"], d["confidence"], ", ".join(v["internal_domains"]["domains"]) or "none", v["internal_domains"]["source"]))
    for c in v["routing"]["contradictions"]:
        L.append("  Routing contradiction: " + c)
    if dl["verdict"] == "mixed":
        L.append("Delivery: mixed. Delivered: %s. Blocked: %s" % ("; ".join(dl["delivered_evidence"]), "; ".join(dl["blocked_evidence"])))
    else:
        L.append("Delivery: %s (%s confidence) %s" % (words(dl["verdict"]), dl["confidence"], "; ".join(dl["evidence"])))
    L.append("Local user: %s (%s)%s" % (lu["primary_local_user"], lu["primary_role"], "; case key is external, pivot to this user" if lu["pivot_recommended"] else ""))
    ages = threat_age_days(v)
    for t in v["threats"]:
        age = ages.get(t["threat_id"])
        L.append("Threat: %s %s %s status=%s threatTime=%s%s" % (t["classification"], t["threat_type"], t["threat"], t["threat_status"], t["threat_time"],
                 " (%d days before the message)" % age if age is not None and age > 30 else ""))
    if not v["threats"]:
        L.append("Threats: none attached to these records")
    L.append("Clicks: %s" % (v["clicks"]["note"] or "click fields present: %d" % len(v["clicks"]["evidence"])))
    L.append("Attachments/parts: %d" % len(v["attachments"]))
    sc = {k: x for k, x in v["sender_authentication"]["scores"].items() if x}
    L.append("Scores: %s" % (sc or "none reported"))
    b = v["blast_radius"]
    L.append("Blast radius: %s" % ("not collected" if b is None else "%d record(s), %d message(s), %d sender(s), %d recipient(s), %s" % (b["records"], b["messages"], len(b["senders"]), len(b["recipients"]), b["types"])))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", action="append", required=True)
    ap.add_argument("--related", action="append")
    ap.add_argument("--internal-domain", action="append")
    ap.add_argument("--case-key")
    ap.add_argument("--out")
    a = ap.parse_args()
    rows = [r for p in a.events for r in load_rows(p)]
    if not rows:
        print("insufficient_event_evidence: no Proofpoint event rows in the --events results. Do not state sender, recipient, direction, delivery, click or verdict facts.")
        sys.exit(2)
    rows, dups = dedupe_rows(rows)
    rel = None
    if a.related:
        rel, _ = dedupe_rows([r for p in a.related for r in load_rows(p)])
    v = summarize(rows, a.internal_domain, a.case_key, rel)
    v["duplicate_rows_removed"] = dups
    print(render(v, dups))
    if a.out:
        with open(a.out, "w") as f:
            json.dump(v, f, indent=1, default=str)


if __name__ == "__main__":
    main()
