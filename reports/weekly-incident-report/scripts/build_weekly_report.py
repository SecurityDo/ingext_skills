#!/usr/bin/env python3
"""Weekly Incident Report for ONE Agent Portal account (one interactive HTML file) in the Fluency editorial style.

  build_weekly_report.py --lists page1.json [page2.json ...] --account <account> --display "<Tenant name>" \
        --start YYYY-MM-DD --end YYYY-MM-DD [--details DIR] [--notes notes.json] [--site-url https://<connector>.app.ingext.io] [--mcp provider|tenant] [--out OUT_DIR]

--lists    saved replies of agentportal_list_incidents (each {"incidents":[...]}), newest first, enough pages to cover
           the week and the week before it (the comparison).
--details  folder of saved agentportal_get_incident replies (one JSON file each). Read for every incident that is not
           closed: the list reply carries a latest_investigation that is not always the latest run, and the incident
           status here is the live one. Only a few fields are read, so a trimmed file works as well as the raw reply.
--notes    optional analyst commentary (see SKILL.md): {"tuning":[{"title","text","tickets":[...]}], "extra_gaps":[...]}.

The layout is fixed and every text field is escaped here. Brand kit: the `fluency-report` skill (fluency_brand.py).
"""
import argparse, csv, datetime as dt, glob, json, os, re, sys


def _find_brand_kit():
    here = os.path.dirname(os.path.abspath(__file__)); home = os.path.expanduser("~")
    cands = [os.environ.get("FLUENCY_BRAND_DIR"), here]
    up = here
    for _ in range(5):
        up = os.path.dirname(up)
        cands += [os.path.join(up, "fluency-report", "scripts"), os.path.join(up, "SKILLS", "fluency-report", "scripts")]
    cands += [os.path.join(home, ".claude", "skills", "fluency-report", "scripts")]
    cands += glob.glob(os.path.join(home, ".claude", "skills", "**", "fluency-report", "scripts"), recursive=True)
    for c in cands:
        if c and os.path.exists(os.path.join(c, "fluency_brand.py")):
            return c
    raise SystemExit("The Fluency report brand kit was not found. Install the `fluency-report` skill (this report uses its "
                     "scripts/fluency_brand.py and brand.css), or set FLUENCY_BRAND_DIR to that skill's scripts folder.")


sys.path.insert(0, _find_brand_kit())
import fluency_brand as fb  # from the fluency-report skill

e = fb.esc
RANK = {"": -1, "info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
SEV_TAG = {"critical": "red", "high": "red", "medium": "amber", "low": "gray", "info": "gray", "": "gray"}
SEV_ROW = {"critical": "sev-high", "high": "sev-high", "medium": "sev-med", "low": "sev-low", "info": "sev-low", "": "sev-low"}

# What kind of confirmation a closed incident asks for. First match wins; order matters.
CATEGORIES = [
    ("Endpoints and infrastructure", re.compile(r"Defender|isolate|reimage|scheduled task|\bSSD\b|Kerberos|\b10\.0\.\d+\.\d+|full scan", re.I)),
    ("Administrator and mailbox-permission changes", re.compile(r"FullAccess|SendAs|Send on Behalf|conditional access|\bCA\d\d\b|enterprise app|service principal|ServiceTeam|PnP|Persona|Power Automate|PIM|admin account|eligible roles|re-enable", re.I)),
    ("External guests and shared files", re.compile(r"\bguests?\b|\bshar(e|ed|ing)\b|\binvit", re.I)),
    ("New accounts, enrolment and password resets", re.compile(r"contractor|non-employee|onboarding|rehired|started on|new (iPad|Windows device)|enrol|set up (their|a new)|phone (registration|setup|method|number)|mobile number|security-info|password reset|SSPR|passkey|Authenticator|registered the|iPad", re.I)),
    ("Unusual location or network", re.compile(r"VPN|\bUK\b|Starlink|Leaseweb|Wi-Fi|Canada|Australia|India|relay|proxy|travel|network", re.I)),
]
OTHER = "Other confirmations"
SPLIT = re.compile(r"[;.]?\s+(?=(?:If|if) (?:not|no|they|it|anything|the scan|someone)\b)")


# ---------------------------------------------------------------- reading
def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def day(s):
    return (s or "")[:10]


def pick_latest(invs):
    ok = [i for i in invs if i.get("status") == "succeeded" and i.get("verdict")]
    return sorted(ok, key=lambda i: i.get("created_at", ""))[-1] if ok else None


def impact_text(inv):
    v = ((inv.get("closure") or {}).get("verdict") or {})
    imp = v.get("impact")
    if isinstance(imp, dict):
        imp = imp.get("text")
    resp = v.get("respond") or {}
    return (imp or "").strip(), (resp.get("headline") or "").strip()


def effective(inc, detail):
    """One record per incident: the live status and the latest finished investigation (by time, not by list order)."""
    li = inc.get("latest_investigation") or {}
    invs = (detail or {}).get("investigations") or [li]
    status = (((detail or {}).get("incident") or {}).get("status")) or inc.get("status") or ""
    last = pick_latest(invs)
    peak = max((RANK.get((i.get("severity") or ""), -1) for i in invs if i.get("status") == "succeeded"), default=-1)
    confirmed = any(i.get("verdict") == "confirmed" for i in invs if i.get("status") == "succeeded")
    skips = [i for i in invs if i.get("status") == "skipped" and "budget" in (i.get("error") or "").lower()]
    failed = [i for i in invs if i.get("status") == "failed"]
    src = last or {}
    imp, resp = impact_text(src) if last else ("", "")
    run_state = "ok" if last else (invs[-1].get("status") if invs else "none") or "none"
    err = ""
    if not last:
        err = next((i.get("error") for i in reversed(invs) if i.get("error")), "")
    return {
        "ticket": inc.get("ticket_key", ""), "id": inc.get("id", ""), "entity": inc.get("entity", ""), "status": status,
        "risk": inc.get("risk_score") or 0, "first_seen": day(inc.get("first_seen_at")),
        "severity": (src.get("severity") or "") if last else "", "actionable": bool(src.get("actionable")) if last else False,
        "disposition": src.get("disposition") or "", "verdict": src.get("verdict") or "",
        "action": clean((src.get("customer_action") or "").strip()),
        "summary": (src.get("summary") or li.get("summary") or "").strip() if last else "",
        "impact": imp, "respond": resp, "has_run": bool(last), "run_state": run_state, "err": err,
        "peak": peak, "flipped": bool(last) and (confirmed and src.get("verdict") != "confirmed" or peak > RANK.get(src.get("severity") or "", -1)),
        "budget_skips": len(skips), "failed_runs": len(failed), "detail": bool(detail),
        "budget_text": next((i.get("error") for i in skips), ""),
        "run_date": day(src.get("created_at")) if last else "", "carried": False,
        "incident_id": inc.get("incident_id", ""), "account": inc.get("account_name", ""),
    }


def categorise(r):
    text = "%s %s" % (r["action"], r["summary"])
    if "@" not in r["entity"] or r["entity"].endswith(".int"):
        return CATEGORIES[0][0]
    if r["entity"].startswith(("entra.", "svc.")):
        return CATEGORIES[1][0]
    for name, rx in CATEGORIES:
        if rx.search(r["action"]):
            return name
    return OTHER


def split_action(a):
    parts = SPLIT.split(a, maxsplit=1)
    if len(parts) == 2:
        rem = re.sub(r"^(?:if not|if no|if they did not|if they do not|if they were not|if it was not)[,:]?\s*", "", parts[1].strip(), flags=re.I)
        if rem and rem != parts[1].strip():
            rem = rem[0].upper() + rem[1:]
        elif rem:
            rem = rem[0].upper() + rem[1:]
        return parts[0].strip().rstrip(";."), rem
    return a, ""


_INC = re.compile(r"^(?P<kt>[^_]+)_(?P<key>.+)_(?P<day>\d{8})$")


def link_for(tpl, r):
    """Direct link to the incident's page in Fluency. tpl placeholders: {key} {key_type} {day} {incident_id} {id} {account} (all URL-encoded)."""
    if not tpl:
        return ""
    from urllib.parse import quote
    mm = _INC.match(r.get("incident_id", "") or "")
    vals = {"key": mm.group("key") if mm else r["entity"], "key_type": mm.group("kt") if mm else "", "day": mm.group("day") if mm else r["first_seen"].replace("-", ""),
            "incident_id": r.get("incident_id", ""), "id": r["id"], "account": r.get("account", "")}
    return tpl.format(**{k: quote(v, safe="") for k, v in vals.items()})


def trim(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def who(r):
    ent = r["entity"]
    return ent.split("#ext#")[0].replace("_", "@", 1) + " (guest)" if "#ext#" in ent.lower() else ent


# ---------------------------------------------------------------- build
def build(a):
    start = dt.date.fromisoformat(a.start); end = dt.date.fromisoformat(a.end)
    prev_start = start - dt.timedelta(days=(end - start).days + 1)
    incs = {}
    for p in a.lists:
        page = load(p)
        for i in (page if isinstance(page, list) else page.get("incidents", [])):
            incs[i["id"]] = i
    details = {}
    if a.details:
        for p in glob.glob(os.path.join(a.details, "*.json")):
            d = load(p); did = (d.get("incident") or {}).get("id") or d.get("id")
            if did:
                details[did] = d
    rows = [effective(i, details.get(i["id"])) for i in incs.values()]
    pending = [r for r in rows if not r["has_run"] and start.isoformat() <= r["first_seen"] <= end.isoformat()]
    done = [r for r in rows if r["has_run"]]          # an incident with no finished investigation is not reported (yet)
    s0, e0, p0 = start.isoformat(), end.isoformat(), prev_start.isoformat()
    win, carried = [], []
    for r in done:
        if s0 <= r["first_seen"] <= e0:
            win.append(r)
        elif p0 <= r["first_seen"] < s0 and r["run_date"] >= s0:
            r["carried"] = True; carried.append(r); win.append(r)   # triggered last week, investigated this week
    prev = [r for r in done if p0 <= r["first_seen"] < s0 and not (r["run_date"] >= s0)]
    if not win:
        raise SystemExit("No investigated incident was first seen between %s and %s in the files given." % (a.start, a.end))
    covered_prev = min(r["first_seen"] for r in rows) <= p0

    act_now, verify, suggest, house, settled = [], [], [], [], []
    for r in win:
        open_ = r["status"] != "closed"
        if open_ and r["actionable"]:
            act_now.append(r)
        elif r["action"] and r["actionable"]:
            verify.append(r)
        elif r["action"]:
            suggest.append(r); settled.append(r)
        elif open_:
            house.append(r); settled.append(r)
        else:
            settled.append(r)
    act_now.sort(key=lambda r: (-max(r["peak"], RANK.get(r["severity"], -1)), -r["risk"]))
    verify.sort(key=lambda r: (-RANK.get(r["severity"], -1), -r["risk"]))
    suggest.sort(key=lambda r: (-RANK.get(r["severity"], -1), -r["risk"]))
    asof = max((day((incs[r["id"]].get("last_seen_at"))) for r in win), default=a.end)
    return dict(win=win, prev=prev, carried=carried, pending=pending, act_now=act_now, verify=verify, suggest=suggest, house=house,
                settled=settled, link_tpl=a.link_template, rdate=(dt.date.fromisoformat(a.report_date) if a.report_date else end), start=start, end=end, prev_start=prev_start, asof=asof, covered_prev=covered_prev)


def fmt_day(d):
    return d.strftime("%d %b").lstrip("0")


def group_verify(ver):
    groups = {}
    for r in ver:
        groups.setdefault(categorise(r), []).append(r)
    return [(c, groups[c]) for c in [c for c, _ in CATEGORIES] + [OTHER] if c in groups]


DUE_DAYS = {"P1": 0, "P2": 7, "P3": 14}      # the due date is the report date plus this many days


def fmt_due(d):
    return d.strftime("%a %d %b").replace(" 0", " ")


def names(rs, limit=2):
    seen = []
    for r in rs:
        w = who(r)
        if w not in seen:
            seen.append(w)
    return ", ".join(seen[:limit]) + (" +%d more" % (len(seen) - limit) if len(seen) > limit else "")


def short(text, n):
    """First sentence, cut at a word boundary: the checklist shows the ask, the CSV holds the full text."""
    t = re.sub(r"\s+", " ", text or "").strip()
    first = re.split(r"(?<=[.?])\s", t, maxsplit=1)[0]
    t = first if len(first) <= n else t
    if len(t) > n:
        t = t[:n].rsplit(" ", 1)[0].rstrip(",;:(") + "…"
    return t


def clean(t):
    """The investigation writes for the day it ran ("ask X today"); the report is read later, so drop or replace the relative day."""
    t = t or ""
    t = re.sub(r"\btoday's\b", "that day's", t, flags=re.I)
    t = re.sub(r"\s+(today|tonight)(?=\s*(?:[.,;:)]|$))", " that day", t, flags=re.I)      # "invited today." -> "invited that day."
    t = re.sub(r"\s+(today|this week|tonight)\b", "", t, flags=re.I)                       # "Ask X today whether" -> "Ask X whether"
    return re.sub(r"\s{2,}", " ", t).strip()


def sentence(t):
    t = clean(t)
    return t if not t or t.endswith((".", "?")) else t + "."


def todo_items(m, capped, notes):
    """The analyst's checklist as data. A top-level action is either one item (one incident or process step) or a group that
    expands into one sub-item per entity. Each leaf has a stable id so ticks survive a reload."""
    rd = m["rdate"]
    due = lambda pri: fmt_due(rd + dt.timedelta(days=DUE_DAYS[pri]))
    items = []
    for r in m["act_now"]:
        urgent = max(r["peak"], RANK.get(r["severity"], -1)) >= RANK["medium"] or r["flipped"]
        pri = "P1" if urgent else "P2"
        ask, ifno = split_action(clean(r["action"]))
        main = "<b>%s</b>" % e(short(ask, 170))
        if ifno:
            main += '<span class="fn">If no: %s</span>' % e(short(ifno[0].lower() + ifno[1:], 90))
        det = []
        if r["flipped"]:
            peak = next(k for k, v in RANK.items() if v == r["peak"])
            det.append("<b>Rating moved</b>: %s earlier in the week, %s on the latest run. Confirm the final call." % (e(peak), e(r["severity"] or "unrated")))
        if r["summary"]:
            det.append("<b>Found</b>: %s" % e(trim(r["summary"], 420)))
        if r["impact"]:
            det.append("<b>Impact if wrong</b>: %s" % e(r["impact"]))
        det.append("<b>Ask</b>: %s" % e(sentence(ask)))
        if ifno:
            det.append("<b>If the answer is no</b>: %s" % e(sentence(ifno)))
        copy = "%s %s%s" % (who(r), sentence(ask), (" If the answer is no: %s" % ifno) if ifno else "")
        items.append(dict(id=r["id"], pri=pri, due=due(pri), main=main, ent=who(r), detail=det, copy=copy, first=r["first_seen"], url=link_for(m.get("link_tpl"), r)))
    for cat, rs in group_verify(m["verify"]):
        subs = []
        for r in rs:
            c1, c2 = split_action(clean(r["action"]))
            subs.append(dict(id=r["id"], url=link_for(m.get("link_tpl"), r), ent=who(r), text=sentence(c1), ifno=sentence(c2) if c2 else "", copy="%s: %s%s" % (who(r), sentence(c1), (" If the answer is no: %s" % c2) if c2 else "")))
        items.append(dict(id="g-" + cat, pri="P2", due=due("P2"), main="<b>%d confirmations · %s</b>" % (len(rs), e(cat.lower())), ent=names(rs), subs=subs, rs=rs))
    if m["house"]:
        subs = [dict(id=r["id"], url=link_for(m.get("link_tpl"), r), ent=who(r), text=trim(r["summary"], 160), ifno="", copy="Close %s in the portal." % who(r)) for r in m["house"]]
        items.append(dict(id="g-close", pri="P3", due=due("P3"), main="<b>Close %d benign incident%s</b> still in Escalate" % (len(m["house"]), "" if len(m["house"]) == 1 else "s"), ent="", subs=subs))
    if m["suggest"]:
        subs = [dict(id=r["id"], url=link_for(m.get("link_tpl"), r), ent=who(r), text=sentence(r["action"]), ifno="", copy="%s: %s" % (who(r), sentence(r["action"]))) for r in m["suggest"]]
        items.append(dict(id="g-opt", pri="P3", due=due("P3"), main="<b>Review %d optional suggestion%s</b>" % (len(m["suggest"]), "" if len(m["suggest"]) == 1 else "s"), ent="", subs=subs))
    if capped:
        items.append(dict(id="p-budget", pri="P3", due=due("P3"), main="<b>Check the daily investigation budget</b>", ent="", detail=["Automatic investigation was skipped on %d incident%s after the daily budget was reached." % (capped, "" if capped == 1 else "s")], copy="Check the daily investigation budget."))
    tun = notes.get("tuning", [])
    if tun:
        subs = [dict(id="p-tune-%d" % i, ent=t["title"], text=sentence(t["text"]), ifno="", copy="Tune: %s. %s" % (t["title"], t["text"])) for i, t in enumerate(tun)]
        items.append(dict(id="g-tune", pri="P3", due=due("P3"), main="<b>Tune %d noisy detection%s</b>" % (len(tun), "" if len(tun) == 1 else "s"), ent="", subs=subs))
    return items


CK_CSS = """
.print-only{display:none}
.ck-bar{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;margin:14px 0 6px}
.ck-prog{display:flex;align-items:center;gap:10px;font:500 11px var(--mono);letter-spacing:.06em;color:var(--t2);text-transform:uppercase}
.ck-track{width:160px;height:6px;background:var(--track);position:relative}.ck-track i{position:absolute;left:0;top:0;bottom:0;width:0;background:var(--blue);transition:width .2s}
.ck-btns{display:flex;gap:6px;flex-wrap:wrap;margin-left:auto}
.ck button{font:500 9px var(--mono);letter-spacing:.12em;text-transform:uppercase;border:1px solid var(--rule);background:#fff;color:var(--t2);padding:6px 9px;cursor:pointer;border-radius:0}
.ck button:hover{border-color:var(--ink);color:var(--ink)}.ck button.on{background:var(--ink);border-color:var(--ink);color:#fff}
.ck-item{border-bottom:1px solid var(--rule2);border-left:3px solid transparent}.ck-item[data-pri=P1]{border-left-color:var(--red);background:#fdf7f7}
.ck-item.done{opacity:.55}.ck-item.done .ck-main b{text-decoration:line-through}
.ck-head{display:grid;grid-template-columns:22px 46px minmax(0,1fr) 26% 92px;gap:10px;align-items:start;padding:11px 8px 10px 10px}
.ck-head input,.ck-sub input{width:15px;height:15px;margin:2px 0 0;accent-color:#111}
.ck a{color:var(--blue);text-decoration:none;border-bottom:1px solid transparent}.ck a:hover{border-bottom-color:var(--blue)}
.ck-main b{display:block;font-weight:600;color:#000;line-height:1.4}.ck-main .fn{display:block;margin:3px 0 0}.ck-ent,.ck-due{font-size:11.5px;color:var(--t2);overflow-wrap:anywhere}
.ck-cnt{font:500 9.5px var(--mono);color:var(--t3);margin-left:6px;letter-spacing:.06em}
.ck details{padding:0 10px 10px 90px}.ck summary{cursor:pointer;font:500 9px var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--blue);list-style:none;width:max-content}
.ck summary::-webkit-details-marker{display:none}.ck summary::after{content:" +"}.ck details[open] summary::after{content:" \\2212"}
.ck-d{margin-top:8px;border-left:2px solid var(--rule);padding-left:12px;font-size:11.5px;color:var(--text)}.ck-d p{margin:0 0 6px}
.ck-sub{display:grid;grid-template-columns:22px minmax(0,34%) minmax(0,1fr) 54px;gap:10px;align-items:start;padding:7px 0;border-top:1px solid var(--rule2);font-size:11.5px}
.ck-sub:first-child{border-top:0}.ck-sub.done{opacity:.5}.ck-sub .fn{display:block;margin:2px 0 0}.ck-sub b{font-weight:600;overflow-wrap:anywhere}
@media (max-width:700px){.ck-head{grid-template-columns:22px 46px 1fr}.ck-ent,.ck-due{grid-column:3}.ck details{padding-left:10px}.ck-sub{grid-template-columns:22px 1fr}.ck-sub>:nth-child(n+3){grid-column:2}}
@media print{.ck-bar,.ck summary,.ck-copy{display:none!important}.ck details{display:none}.print-only{display:block}.ck-item{break-inside:avoid}.ck-head{padding:7px 4px}.ck-item[data-pri=P1]{background:none}}
"""

CK_JS = """
(function(){var root=document.querySelector('.ck');if(!root)return;var key=root.getAttribute('data-key'),st={};
try{st=JSON.parse(localStorage.getItem(key)||'{}')}catch(e){}
function save(){try{localStorage.setItem(key,JSON.stringify(st))}catch(e){}}
var f='all',items=[].slice.call(root.querySelectorAll('.ck-item'));
function leaves(it){return [].slice.call(it.querySelectorAll('input.ck-leaf'))}
function refresh(){var done=0;
 items.forEach(function(it){var ls=leaves(it),n=0;ls.forEach(function(l){l.checked=!!st[l.getAttribute('data-id')];if(l.checked)n++;var r=l.closest('.ck-sub');if(r)r.classList.toggle('done',l.checked)});
  var top=it.querySelector('input.ck-top'),all=ls.length&&n===ls.length;
  if(top){top.checked=all;top.indeterminate=n>0&&n<ls.length;var c=it.querySelector('.ck-cnt');if(c)c.textContent=n+'/'+ls.length}
  it.classList.toggle('done',!!all);if(all)done++;
  var show=f==='all'||(f==='open'?!all:it.getAttribute('data-pri')===f);it.style.display=show?'':'none'});
 root.querySelector('.ck-done').textContent=done;root.querySelector('.ck-fill').style.width=(100*done/items.length)+'%'}
root.addEventListener('change',function(ev){var t=ev.target;if(t.classList.contains('ck-leaf')){st[t.getAttribute('data-id')]=t.checked}
 else if(t.classList.contains('ck-top')){leaves(t.closest('.ck-item')).forEach(function(l){st[l.getAttribute('data-id')]=t.checked})}
 save();refresh()});
function copy(text,btn){var done=function(){var o=btn.textContent;btn.textContent='Copied';setTimeout(function(){btn.textContent=o},1200)};
 if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(done,function(){fb(text);done()})}else{fb(text);done()}}
function fb(text){var a=document.createElement('textarea');a.value=text;document.body.appendChild(a);a.select();try{document.execCommand('copy')}catch(e){}document.body.removeChild(a)}
root.addEventListener('click',function(ev){var b=ev.target.closest('button');if(!b)return;
 if(b.hasAttribute('data-copy')){copy(b.getAttribute('data-copy'),b)}
 else if(b.hasAttribute('data-f')){f=b.getAttribute('data-f');[].forEach.call(root.querySelectorAll('[data-f]'),function(x){x.classList.toggle('on',x===b)});refresh()}
 else if(b.classList.contains('ck-all')){var open=b.getAttribute('data-open')!=='1';[].forEach.call(root.querySelectorAll('details'),function(d){d.open=open});b.setAttribute('data-open',open?'1':'0');b.textContent=open?'Collapse all':'Expand all'}
 else if(b.classList.contains('ck-list')){var out=[];items.forEach(function(it){var ls=leaves(it);ls.forEach(function(l){if(!l.checked){var r=l.closest('.ck-sub')||l.closest('.ck-head');var c=r.querySelector('[data-copy]');if(c)out.push('- '+c.getAttribute('data-copy'))}})});copy(out.join('\\n'),b)}
 else if(b.classList.contains('ck-reset')){if(confirm('Clear all ticks?')){st={};save();refresh()}}});
refresh()})();
"""


def ck_html(items, key, d1):
    """The interactive checklist (screen) built from todo_items()."""
    out = ['<div class="ck" data-key="%s">' % e(key)]
    out.append('<div class="ck-bar"><div class="ck-prog"><span><b class="ck-done">0</b> of %d done</span><span class="ck-track"><i class="ck-fill"></i></span></div>'
               '<div class="ck-btns"><button data-f="all" class="on">All</button><button data-f="P1">P1</button><button data-f="P2">P2</button><button data-f="P3">P3</button><button data-f="open">Not done</button>'
               '<button class="ck-all">Expand all</button><button class="ck-list">Copy open list</button><button class="ck-reset">Reset</button></div></div>' % len(items))
    for it in items:
        subs = it.get("subs")
        box = '<input type="checkbox" class="ck-top" aria-label="Done">' if subs else '<input type="checkbox" class="ck-leaf" data-id="%s" aria-label="Done">' % e(it["id"])
        ent = (('<a href="%s" target="_blank" rel="noopener" title="Open in Fluency">%s ↗</a>' % (e(it["url"]), e(it["ent"]))) if it.get("url") else e(it["ent"])) + (('<br><span class="fn">first seen %s</span>' % e(fmt_day(dt.date.fromisoformat(it["first"])))) if it.get("first") else "")
        cnt = '<span class="ck-cnt"></span>' if subs else ""
        copy_btn = "" if subs else ''
        head = '<div class="ck-head ck-row">%s%s<div class="ck-main">%s%s</div><div class="ck-ent">%s</div><div class="ck-due">%s</div></div>' % (
            box, fb.tag(it["pri"], "p%s" % it["pri"][1]), it["main"] + cnt if subs else it["main"], "", ent, e(it["due"]))
        if subs:
            rows = "".join('<div class="ck-sub"><input type="checkbox" class="ck-leaf" data-id="%s" aria-label="Done"><b>%s</b><div>%s%s</div><button class="ck-copy" data-copy="%s">Copy</button></div>' % (
                e(s_["id"]), (('<a href="%s" target="_blank" rel="noopener" title="Open in Fluency">%s ↗</a>' % (e(s_["url"]), e(s_["ent"]))) if s_.get("url") else e(s_["ent"])), e(s_["text"]), ('<span class="fn">%s%s</span>' % ("" if s_["ifno"].lower().startswith("if ") else "If no: ", e(s_["ifno"]))) if s_["ifno"] else "", e(s_["copy"])) for s_ in subs)
            det = '<details><summary>%d items</summary><div class="ck-d">%s</div></details>' % (len(subs), rows)
        else:
            body = "".join("<p>%s</p>" % d for d in it.get("detail", []))
            body += '<p><button class="ck-copy" data-copy="%s">Copy message</button></p>' % e(it["copy"])
            det = '<details><summary>Details</summary><div class="ck-d">%s</div></details>' % body
        # the copy payload for "Copy open list" lives on the head row of single items
        if not subs:
            head = head.replace('<div class="ck-due">', '<span hidden data-copy="%s"></span><div class="ck-due">' % e(it["copy"]), 1)
        out.append('<div class="ck-item" data-pri="%s">%s%s</div>' % (it["pri"], head, det))
    out.append("</div>")
    return "".join(out)


def render(a, m, notes):
    win, act, ver, hou = m["win"], m["act_now"], m["verify"], m["house"]
    n = len(win); np_ = len(m["prev"]); k = len(m["carried"])
    label = "%s – %s %d" % (fmt_day(m["start"]), fmt_day(m["end"]), m["end"].year)
    delta = ("%+d on the week before" % (n - np_)) if m["covered_prev"] else "week before not covered"
    skips = [r for r in win if r["budget_skips"]]
    capped = len(skips)
    confirmed = [r for r in win if r["verdict"] == "confirmed"]
    todo = todo_items(m, capped, notes)
    p1 = [t for t in todo if t["pri"] == "P1"]
    rd = m["rdate"]
    d1, d2, d3 = (fmt_due(rd + dt.timedelta(days=DUE_DAYS[x])) for x in ("P1", "P2", "P3"))

    kp = [fb.kpi("Actions to do", len(todo), note=("%d due %s" % (len(p1), d1)) if p1 else "none due %s" % d1, color="red" if p1 else ""),
          fb.kpi("Open incidents", len(act), note="still in Escalate", color="red" if act else ""),
          fb.kpi("Closed, to confirm", len(ver), note="%d groups" % len(group_verify(ver)), color="amber" if ver else ""),
          fb.kpi("Incidents investigated", n, note=delta + (" · %d from last week" % k if k else ""))]
    lede = "%d incidents investigated for %s, %s. %s" % (n, a.display, label, "None rated confirmed." if not confirmed else "%d rated confirmed." % len(confirmed))

    head = ("%d actions, %d due %s" % (len(todo), len(p1), d1)) if p1 else "%d actions, none urgent" % len(todo)
    sub = "P1 due %s · P2 by %s · P3 by %s" % (d1, d2, d3)
    key = "weekly-incident-report:%s:%s:%s" % (a.account, m["start"].isoformat(), m["end"].isoformat())
    body = fb.section(1, "What the analyst needs to do", fb.netread(head, "<p>%s</p>" % e(sub)) + ck_html(todo, key, d1) + "<script>%s</script>" % CK_JS)

    # print version of the detail (the PDF has no clicks): confirmations, suggestions, close-in-portal
    pr = ""
    if ver:
        for cat, rs in group_verify(ver):
            rws = [["<b>%s</b>" % e(who(r)), e(short(split_action(r["action"])[0], 140))] for r in rs]
            pr += '<h3>%s <span class="fn">· %d</span></h3>' % (e(cat), len(rs)) + fb.table(["Entity", "Confirm"], rws, widths=["30%", "70%"], raw_cols=(0, 1))
        pr = fb.section(2, "Closed incidents to confirm", pr)
    if m["suggest"]:
        rws = [["<b>%s</b>" % e(who(r)), e(short(r["action"], 130))] for r in m["suggest"]]
        pr += fb.section(3, "Optional suggestions", fb.table(["Entity", "Suggestion"], rws, widths=["30%", "70%"], raw_cols=(0, 1)))
    if hou:
        pr += fb.section(4, "Close in the portal", '<p class="fn">Investigated as benign, still in Escalate.</p><p>%s</p>' % e(", ".join(dict.fromkeys(who(r) for r in hou))))
    body += '<div class="print-only">%s</div>' % pr

    items = ""
    by_ticket = {r["ticket"]: r for r in win}
    for t in notes.get("tuning", []):
        ents = list(dict.fromkeys(who(by_ticket[tk]) if tk in by_ticket else tk for tk in t.get("tickets", [])))
        items += "<li><b>%s.</b> %s <span class=\"fn\">(%s)</span></li>" % (e(t["title"]), e(t["text"]), e(", ".join(ents[:3]) + (" +%d" % (len(ents) - 3) if len(ents) > 3 else "")))
    if capped:
        spend = re.search(r"\(([^)]*spent today[^)]*)\)", " ".join(r["budget_text"] for r in skips) or "")
        items += "<li><b>Investigation budget.</b> Automatic investigation was skipped on %d incident%s after the daily budget was reached%s.</li>" % (capped, "" if capped == 1 else "s", (" (%s)" % e(spend.group(1).replace("spent today", "spent that day"))) if spend else "")
    if items:
        body += fb.section(5, "Process findings", "<ul>%s</ul>" % items)

    det_n = sum(1 for r in win if r["detail"])
    method = ("<ul><li>Source: Agent Portal, account <b>%s</b> (%s), read-only. Week = first-seen date, %s to %s UTC. Data as at %s.</li>" % (e(a.account), e(a.display), e(m["start"].isoformat()), e(m["end"].isoformat()), e(m["asof"])) +
              "<li>Only investigated incidents are included; one still waiting for its first investigation appears in the week it is investigated.</li>" +
              "<li>%d open incident%s read in full; closed incidents use the list reply.</li>" % (det_n, " was" if det_n == 1 else "s were") +
              "<li>An entity repeats if it triggered more than one incident. Due dates run from %s: P1 same day, P2 +7 days, P3 +14 days.</li>" % e(fmt_due(rd)) +
              "<li>Ticks are kept in this browser only; printing shows the checklist unticked.</li>" +
              "".join("<li>%s</li>" % e(g) for g in notes.get("extra_gaps", [])) + "</ul>")
    return fb.page("Weekly Incident Report", "Incident report · Confidential", body=body, subtitle=lede,
                   meta="Prepared by Fluency Security · Tenant: %s · Week: %s" % (a.display, label),
                   kpis=kp, method=method, extra_css=CK_CSS,
                   footer_left="Fluency Security · Weekly Incident Report · %s" % a.display, data_date=dt.date.fromisoformat(m["asof"]).strftime("%d %b %Y"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lists", nargs="+", required=True); ap.add_argument("--details"); ap.add_argument("--notes")
    ap.add_argument("--account", required=True); ap.add_argument("--display"); ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--report-date", help="YYYY-MM-DD the report is issued; due dates run from it (default: --end)")
    ap.add_argument("--site-url", help="the Fluency site of the MCP connector, https://<connector>.app.ingext.io; each entity links to its behavior-summary page there")
    ap.add_argument("--mcp", choices=["provider", "tenant"], default="provider", help="the MCP server type: a provider server hosts many accounts and its links carry gridaccount; a tenant server is one account and its links do not")
    ap.add_argument("--link-template", help="override: full URL template with {key} {day} {account} placeholders")
    ap.add_argument("--out", default=".")
    a = ap.parse_args(); a.display = a.display or a.account
    if a.site_url and not a.link_template:
        a.link_template = a.site_url.rstrip("/") + "/v2/behavior-summary?dayIndex={day}&id=%22{key}%22" + ("&gridaccount={account}" if a.mcp == "provider" else "")
    notes = load(a.notes) if a.notes else {}
    m = build(a)
    doc = render(a, m, notes)
    os.makedirs(a.out, exist_ok=True)
    hp = os.path.join(a.out, "Weekly_Incident_Report_%s_%s.html" % (re.sub(r"[^A-Za-z0-9]+", "", a.account), m["end"].strftime("%d%b%y")))
    open(hp, "w", encoding="utf-8").write(doc)
    print("reported=%d (open=%d confirm=%d settled=%d; optional=%d close_in_portal=%d inside settled) carried_from_last_week=%d; left out (no finished investigation)=%d" %
          (len(m["win"]), len(m["act_now"]), len(m["verify"]), len(m["settled"]), len(m["suggest"]), len(m["house"]), len(m["carried"]), len(m["pending"])))
    print(hp)


if __name__ == "__main__":
    main()
