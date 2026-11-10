#!/usr/bin/env python3
"""Measure incident handling from behavior_summary_search replies (the case register).

  case_evidence.py --facets facets.json --open open1.json [open2.json ...] [--closed closed1.json ...]
                   --asof YYYY-MM-DD [--rules ../assets/rating_rules.json] -o case_evidence.json

  --facets  a reply for the whole 90-day register (riskScore 3000+) asked with facets status, classification,
            scoreLevel, keyType; its `total` and `facets` give exact counts even if few documents came back.
  --open    replies for the OPEN cases (status:new); the first reply's facets cover every open case.
  --closed  replies for a sample of recently closed cases (timing of human closure).
Replies are the saved tool output (a JSON object with documents[].source). Several files of one kind are merged and
de-duplicated by case id. No user, host or address is copied into the output: counts and durations only.
"""
import argparse, datetime, json, os, re, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if isinstance(d, dict) and "documents" not in d and "result" in d:
        d = d["result"]
    return d


def docs_of(paths):
    seen, out = set(), []
    for p in paths:
        for x in load(p).get("documents", []):
            s = x.get("source", x)
            i = s.get("id") or s.get("uuid")
            if i in seen:
                continue
            seen.add(i); out.append(s)
    return out


def facet(d, name):
    return {f["value"]: f["count"] for f in (d.get("facets") or {}).get(name, [])}


def iso_ms(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?Z?", str(v))
    if not m:
        return None
    t = datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc).timestamp() * 1000
    return t + (float((m.group(2) or ".0")[:7]) * 1000)


def case_times(s, ai_actor):
    """Per-case timing facts from the comment thread."""
    detect = iso_ms(s.get("incidentDetectionTime")) or float(s.get("from") or 0) or None
    cs = sorted((s.get("comments") or []), key=lambda c: c.get("createdOn") or 0)
    ai = [c for c in cs if (c.get("username") or "") == ai_actor]
    hu = [c for c in cs if (c.get("username") or "") not in ("", ai_actor)]
    first_ai = ai[0]["createdOn"] if ai else None
    esc = None
    for c in ai:
        txt = c.get("content") or ""
        try:
            j = json.loads(txt)
        except Exception:
            j = {}
        blob = json.dumps(j) if j else txt
        flag = (isinstance(j, dict) and (j.get("actionable") is True or str(j.get("decision", "")).upper().startswith("ESCALATE"))) \
            or "ESCALATE" in blob.upper() or re.search(r'"actionable"\s*:\s*true', blob) is not None
        if flag:
            esc = c["createdOn"]; break
    human_act = [c for c in hu if c.get("actions")]
    first_human = human_act[0]["createdOn"] if human_act else None
    ai_closed = any((c.get("username") == ai_actor) and any("to 'closed'" in a for a in (c.get("actions") or [])) for c in cs)
    return detect, first_ai, esc, first_human, ai_closed


def med(v):
    return round(statistics.median(v), 1) if v else None


def pct(v, q):
    if not v:
        return None
    v = sorted(v); k = min(len(v) - 1, int(round(q * (len(v) - 1))))
    return round(v[k], 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--facets", required=True); ap.add_argument("--open", nargs="*", default=[]); ap.add_argument("--closed", nargs="*", default=[])
    ap.add_argument("--asof", required=True); ap.add_argument("--rules", default=os.path.join(HERE, "..", "assets", "rating_rules.json"))
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    rules = json.load(open(a.rules)); ai_actor = rules["ai_actor"]
    asof = datetime.datetime.strptime(a.asof, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc).timestamp() * 1000 + 86399000
    H = 3600000.0; D = 86400000.0
    reg = load(a.facets)
    total = int(reg.get("total") or 0)
    status = facet(reg, "status"); klass = facet(reg, "classification"); level = facet(reg, "scoreLevel")
    open_n = status.get("new", 0)
    classified = sum(klass.values()); unclassified = max(0, total - classified)
    true_pos = sum(v for k, v in klass.items() if k.lower().startswith("true positive"))
    opened = docs_of(a.open) if a.open else []
    ofac = load(a.open[0]) if a.open else {}
    open_levels = facet(ofac, "scoreLevel")
    open_gt8000 = open_levels.get(">8000")
    # open cases
    ages, esc_wait, esc_no_human, esc_total, personal, open_unclassified = [], [], 0, 0, 0, 0
    pd_re = re.compile(rules["personal_data_rule_pattern"], re.I)
    ai_first, ai_n, no_ai = [], 0, 0
    for s in opened:
        detect, first_ai, esc, first_human, _ = case_times(s, ai_actor)
        if detect:
            ages.append((asof - detect) / D)
        if first_ai:
            ai_n += 1
            if detect and first_ai >= detect:
                ai_first.append((first_ai - detect) / 60000.0)
        else:
            no_ai += 1
        if esc:
            esc_total += 1
            if not first_human:
                esc_no_human += 1; esc_wait.append((asof - esc) / D)
        if any(pd_re.search(r or "") for r in (s.get("behaviorRules") or [])):
            personal += 1
        if not s.get("classification"):
            open_unclassified += 1
    old_n = sum(1 for x in ages if x > rules["ownership"]["open_age_days_flag"])
    over_deadline = sum(1 for w in esc_wait if w * 24 > rules["tightest_deadline_hours"])
    # closed sample
    closed = docs_of(a.closed) if a.closed else []
    to_close_h, closed_by_ai, closed_by_human = [], 0, 0
    for s in closed:
        detect, first_ai, esc, first_human, ai_closed = case_times(s, ai_actor)
        if first_ai:
            ai_n += 1
            if detect and first_ai >= detect:
                ai_first.append((first_ai - detect) / 60000.0)
        else:
            no_ai += 1
        done = None
        for c in sorted((s.get("comments") or []), key=lambda c: c.get("createdOn") or 0):
            if any("to 'closed'" in x for x in (c.get("actions") or [])):
                done = c; break
        if done:
            if done.get("username") == ai_actor:
                closed_by_ai += 1
            else:
                closed_by_human += 1
            if detect and done["createdOn"] >= detect:
                to_close_h.append((done["createdOn"] - detect) / H)
    # is there any reportability / materiality determination in the data?
    rp = re.compile(rules["reportability_pattern"], re.I)
    texts = list(klass.keys())
    for s in opened + closed:
        texts.append(s.get("classification") or "")
        for c in (s.get("comments") or []):
            texts.extend(c.get("actions") or [])
    has_reportability = any(rp.search(t or "") for t in texts)
    examined = len(opened) + len(closed)
    out = {
        "asof": a.asof, "window_days": rules["window_days"], "ai_actor": ai_actor,
        "register": {"total": total, "status": status, "open": open_n, "closed": status.get("closed", 0), "classification": klass, "score_level": level,
                     "unclassified": unclassified, "true_positive": true_pos},
        "open": {"fetched": len(opened), "total": open_n, "complete": len(opened) >= open_n if open_n else True,
                 "risk_gt_8000": open_gt8000, "older_than_flag": old_n, "flag_days": rules["ownership"]["open_age_days_flag"],
                 "oldest_days": round(max(ages), 1) if ages else None, "median_age_days": med(ages),
                 "escalated": esc_total, "escalated_no_human": esc_no_human, "escalated_over_deadline": over_deadline,
                 "oldest_escalation_wait_days": round(max(esc_wait), 1) if esc_wait else None,
                 "personal_data": personal, "unclassified": open_unclassified},
        "closed_sample": {"fetched": len(closed), "closed_by_ai": closed_by_ai, "closed_by_human": closed_by_human,
                          "median_hours_to_close": med(to_close_h), "p90_hours_to_close": pct(to_close_h, 0.9)},
        "triage": {"cases_examined": examined, "with_ai_verdict": ai_n, "without_ai_verdict": no_ai,
                   "median_minutes": med(ai_first), "p90_minutes": pct(ai_first, 0.9),
                   "coverage_pct": round(100.0 * ai_n / examined, 1) if examined else None},
        "reportability": {"field_found": has_reportability},
    }
    json.dump(out, open(a.out, "w"), indent=1)
    print("cases %d (open %d, fetched %d) | triage coverage %s%% | escalated open %d (no human %d) | wrote %s" % (
        total, open_n, len(opened), out["triage"]["coverage_pct"], esc_total, esc_no_human, a.out))


if __name__ == "__main__":
    main()
