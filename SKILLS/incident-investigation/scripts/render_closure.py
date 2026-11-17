#!/usr/bin/env python3
"""Render an incident closure JSON into the Fluency Tier 3 closure report (self-contained HTML).

The look is the Fluency report brand kit (editorial monochrome: white paper, IBM Plex, a brandline
with the lock mark over a black rule, black title, flat mono tables, one blue / red / amber).
The kit is `fluency-report`'s scripts/fluency_brand.py + brand.css; a copy is bundled in scripts/brand/
(refresh it from that skill when the brand changes). FLUENCY_BRAND_DIR or a sibling fluency-report
skill are used if the copy is absent, and the script stops with a clear message if none is found. Branding is fixed and always applied; there is no customer-branded variant.

    python3 scripts/render_closure.py closure.json -o closure.html
    node <fluency-report>/scripts/render_pdf.mjs --input closure.html --output closure.pdf   # optional PDF

Layout (fixed order; optional blocks are skipped when absent):
    brandline · title · lede · meta line
    verdict (own row) · ticket metadata grid (own row)
    §1 recommendation (what to do, before the evidence)
    §2 grounds (AI-assist claims, each tested)
    timeline          (optional — single-event incidents: raw audit times)
    score_table       (optional — multi-day incidents: activity vs riskScore bars)
    base_rate         (optional — peer census table, within this one account)
    negatives         (what did NOT happen, each against a control)
    callouts          (optional — one per red herring the ticket raised)
    evidence · footer (review date)

Inline markup allowed in any text field: **bold**, *italic*, `code`. Everything else
is HTML-escaped, so tenant data can be pasted in safely.
See assets/closure_schema.md for the field reference.
"""
import argparse, glob, html, json, os, re, sys


def _find_brand_kit():
    # The Fluency report brand kit lives only in the `fluency-report` skill (scripts/). Find that skill next to this one.
    here = os.path.dirname(os.path.abspath(__file__)); home = os.path.expanduser("~")
    # scripts/brand/ is a bundled copy of the fluency-report kit: an investigation run is given this skill and a few
    # companions, not fluency-report, so the renderer must not depend on that skill being mounted.
    cands = [os.environ.get("FLUENCY_BRAND_DIR"), os.path.join(here, "brand"), here]
    up = here
    for _ in range(5):
        up = os.path.dirname(up); cands.append(os.path.join(up, "fluency-report", "scripts"))
    cands += [os.path.join(home, ".claude", "skills", "fluency-report", "scripts")]
    cands += glob.glob(os.path.join(home, ".claude", "skills", "**", "fluency-report", "scripts"), recursive=True)
    for c in cands:
        if c and os.path.exists(os.path.join(c, "fluency_brand.py")):
            return c
    raise SystemExit("The Fluency report brand kit was not found. Install the `fluency-report` skill (this report uses its "
                     "scripts/fluency_brand.py and brand.css), or set FLUENCY_BRAND_DIR to that skill's scripts folder.")


sys.path.insert(0, _find_brand_kit())
import fluency_brand as fb  # Fluency report brand kit, from the fluency-report skill

# outcome / disposition -> (label, callout kind). good = blue, watch = amber, act = red.
VERDICTS = {
    "benign":    ("Benign",    "good"),
    "escalate":  ("Escalate",  "watch"),
    "confirmed": ("Confirmed", "act"),
}

# A run that decides with a disposition (the agent portal's fixed set) labels the card
# with it, so a low-severity confirmation closed on an escalate outcome reads
# "Closed: verify · Low", as the portal's opening line does. Without one, the outcome.
DISPOSITIONS = {
    "closed":                  ("Closed",                   "good"),
    "closed_suggested_action": ("Closed, suggested action", "good"),
    "closed_per_note":         ("Closed per account note",  "good"),
    "closed_verify":           ("Closed: verify",           "good"),
    "escalate_confirm":        ("Escalate: verify",         "watch"),
    "escalate_contain":        ("Escalate: contain",        "act"),
    "confirmed":               ("Confirmed",                "act"),
}
SEVERITIES = ("info", "low", "medium", "high", "critical")

BAR_HOT, BAR_COOL = "#b3242e", "#8a8a8a"


def verdict_label(v):
    """The card's label and callout kind: the disposition and severity when given, else the outcome."""
    d = str(v.get("disposition") or "").lower()
    if d in DISPOSITIONS:
        label, kind = DISPOSITIONS[d]
        sev = str(v.get("severity") or "").lower()
        return (f"{label} · {sev.capitalize()}" if sev in SEVERITIES else label), kind
    return VERDICTS[v["outcome"].lower()]


def md(s):
    """Escape, then apply the three inline marks."""
    s = html.escape(str(s if s is not None else ""))
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    return s


def plain(s):
    """Text for fields the kit escapes itself (title, lede, meta line): drop the inline marks."""
    return re.sub(r"[*`]", "", str(s if s is not None else ""))


def paras(v):
    items = v if isinstance(v, list) else [v]
    return "".join(f"<p>{md(p)}</p>" for p in items if p)


class Sections:
    """Numbers the §-sections in the order they are added."""
    def __init__(self):
        self.n, self.out = 0, []

    def add(self, title, body, intro=None):
        self.n += 1
        lead = f'<p class="intro">{md(intro)}</p>' if intro else ""
        self.out.append(fb.section("%02d" % self.n, plain(title), lead + body))


def callout(c, tag_text="Note", kind="good"):
    if isinstance(c, str):  # a bare string is a body without a heading
        c = {"body": c}
    head = f'<h4>{md(c["title"])}</h4>' if c.get("title") else ""
    return (f'<div class="callout {kind}"><p class="tag">{html.escape(tag_text)}</p>{head}'
            f'{paras(c["body"])}</div>')


def render_grounds(g):
    items = "".join(
        f'<li><span class="gn">{i}</span><div><blockquote>&ldquo;{md(x["claim"])}&rdquo;</blockquote>'
        f'{paras(x["finding"])}</div></li>'
        for i, x in enumerate(g["items"], 1))
    return (g.get("title", f"{len(g['items'])} grounds for escalation, tested"),
            f'<ol class="grounds">{items}</ol>', g.get("intro"))


def render_timeline(t):
    """A vertical timeline: time (UTC) at the left, a dot on a line, then who did what. Rows the rule fired on
    (`highlight`) get a filled red dot and a tag, so the moment that raised the incident stands out."""
    items = "".join(
        f'<li class="{"hl" if r.get("highlight") else ""}"><time>{md(r["time"])}</time><span class="dot"></span>'
        f'<div class="tl-body"><p class="tl-actor">{md(r["actor"])}{" " + fb.tag("rule fired", "red") if r.get("highlight") else ""}</p>'
        f'<p>{md(r["event"])}</p></div></li>'
        for r in t["rows"])
    extra = callout(t["callout"], "Read") if t.get("callout") else ""
    return t["title"], f'<ol class="tl">{items}</ol>{extra}', t.get("intro")


def bar(v, vmax, hot):
    pct = 0 if not vmax else max(2, round(100 * v / vmax))
    return f'<div class="bar"><i style="width:{pct}%;background:{BAR_HOT if hot else BAR_COOL}"></i></div>'


def render_score_table(s):
    a_lab, b_lab = s.get("activity_label", "Admin ops"), s.get("score_label", "riskScore")
    amax = max((r["activity"] for r in s["rows"]), default=0)
    bmax = max((r["score"] for r in s["rows"]), default=0)
    rows, hot = [], {}
    for r in s["rows"]:
        is_hot = bool(r.get("incident"))
        rows.append([f"<code>{md(r['day'])}</code>", f"{r['activity']:,}", bar(r["activity"], amax, is_hot),
                     f"{r['score']:,}", bar(r["score"], bmax, is_hot), fb.tag("incident", "red") if is_hot else ""])
        hot[id(rows[-1])] = is_hot
    cap = s.get("caption") or (f"Daily {a_lab.lower()} against the behavior riskScore for the same day. "
                               f"Bars are scaled within each column; column maxima are {amax:,} and {bmax:,}. "
                               f"Red rows were raised as incidents.")
    table = fb.table(["Day", a_lab, "", b_lab, "", ""], rows, widths=["16%", "11%", "25%", "11%", "25%", "12%"],
                     num_cols=(1, 3), raw_cols=(0, 2, 4, 5),
                     row_class=lambda r: "sev-high" if hot[id(r)] else "",
                     foot=md(cap))
    extra = callout(s["callout"], "Read") if s.get("callout") else ""
    return s.get("title", "The score does not follow the activity"), table + extra, s.get("intro")


def render_base_rate(b):
    cols = b["columns"]
    rows = [[f"<code>{md(v)}</code>" if i == 0 else md(v) for i, v in enumerate(r)] for r in b["rows"]]
    table = fb.table(cols, rows, num_cols=tuple(range(1, len(cols))), raw_cols=tuple(range(len(cols))),
                     foot=md(b["caption"]) if b.get("caption") else "")
    return b["title"], table, b.get("intro")


def render_negatives(n):
    items = "".join(f'<li><strong>{md(x["title"])}</strong> {md(x.get("body", ""))}</li>' for x in n["items"])
    extra = "".join(callout(c, "Red herring", "watch") for c in n.get("callouts", []))
    intro = n.get("intro", "Each negative below was run against a control proving the query finds these "
                           "operations elsewhere on the tenant — a zero from a broken query looks identical "
                           "to a real one.")
    return n.get("title", "What did not happen"), f'<ul class="checks">{items}</ul>{extra}', intro


EXTRA_CSS = """
.intro{max-width:none;color:var(--t2)}
ol.grounds{list-style:none;margin:6px 0 0;padding:0}
ol.grounds li{display:grid;grid-template-columns:26px 1fr;gap:10px;padding:12px 0;border-top:1px solid var(--rule)}
ol.grounds li:first-child{border-top:0}
.gn{font:500 10px/1.6 var(--mono);color:var(--blue)}
blockquote{margin:0 0 6px;font-size:13px;font-style:italic;color:var(--ink);font-weight:500}
ol.grounds p{margin:0 0 6px}
ul.checks{list-style:none;margin:6px 0 0;padding:0}
ul.checks li{position:relative;padding:5px 0 5px 20px}
ul.checks li::before{content:"\\2713";position:absolute;left:0;color:var(--blue);font-weight:700}
td code,.sec-body code{font-family:var(--mono)}
@media print{ol.grounds li{break-inside:avoid;page-break-inside:avoid}}
.verdict{display:grid;grid-template-columns:minmax(170px,auto) minmax(0,1fr);grid-template-rows:1fr;align-items:stretch;margin:16px 0 0;background:var(--callout);border:1px solid var(--vc)}
.verdict.v-good{--vc:#1b7f4b}  /* the one green in the report: benign and closed verdicts read as good */.verdict.v-watch{--vc:var(--amber)}.verdict.v-act{--vc:var(--red)}
.v-badge{background:var(--vc);color:#fff;padding:20px 24px;display:flex;flex-direction:column;justify-content:center;gap:10px;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.v-ic{font:700 18px/1 var(--mono);width:30px;height:30px;border:2px solid currentColor;border-radius:50%;display:grid;place-items:center}
.v-label{font:700 22px/1.15 var(--sans);letter-spacing:-.012em}
.v-body{padding:16px 22px;align-self:center}
.v-badge{align-self:stretch}
.v-tag{font:500 8.5px/1.4 var(--mono);letter-spacing:.15em;text-transform:uppercase;color:var(--t3);margin:0 0 6px}
.v-body p{margin:0 0 6px}.v-body p:last-child{margin:0}
.top{display:grid;grid-template-columns:minmax(0,1fr);column-gap:44px;align-items:start}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px 28px;margin:16px 0;padding:16px 0;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule)}
.meta dt{font:500 9px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--t3);margin:0 0 6px}
.meta dd{margin:0;overflow-wrap:anywhere;color:var(--ink)}
/* Full width on screen: the brand kit's 816px (US Letter) column is for print and PDF, which keep it. */
@media screen{
:root{--w:none;--px:40px}
.hero-title,.hero h1{max-width:min(1000px,calc(100% - 90px))}
.hero-sub,.hero p{max-width:min(860px,calc(100% - 90px))}
table,table.data{table-layout:auto}
td,th{overflow-wrap:anywhere}
blockquote,ol.grounds p,ul.checks li{max-width:none}
}
@media screen and (max-width:760px){.verdict{grid-template-columns:1fr;grid-template-rows:auto}}
@media screen and (max-width:640px){:root{--px:20px}.verdict{grid-template-columns:1fr;grid-template-rows:auto}}
/* Timeline */
ol.tl{list-style:none;margin:8px 0 4px;padding:0}
ol.tl li{display:grid;grid-template-columns:130px 14px minmax(0,1fr);column-gap:14px;position:relative;padding:0 0 12px}
ol.tl li::before{content:"";position:absolute;left:calc(130px + 14px + 6px);top:12px;bottom:-2px;width:2px;background:var(--rule)}
ol.tl li:last-child{padding-bottom:2px}ol.tl li:last-child::before{display:none}
ol.tl time{font:500 11px/1.5 var(--mono);color:var(--ink);padding-top:1px;white-space:nowrap}
ol.tl .dot{width:14px;height:14px;border:2px solid var(--ink);border-radius:50%;background:var(--paper);margin-top:2px;position:relative;z-index:1;box-sizing:border-box}
ol.tl li.hl .dot{background:var(--red);border-color:var(--red)}
ol.tl .tl-body p{margin:0 0 2px}
ol.tl .tl-actor{font-weight:600;color:var(--ink)}
ol.tl .tag{margin-left:8px}
@media screen and (max-width:640px){
ol.tl li{grid-template-columns:14px minmax(0,1fr);column-gap:12px}
ol.tl li::before{left:6px}
ol.tl time{grid-column:2;grid-row:1}ol.tl .dot{grid-column:1;grid-row:1}ol.tl .tl-body{grid-column:2;grid-row:2}}
@media print{ol.tl li{break-inside:avoid;page-break-inside:avoid}}

/* Compact: tighter title block, headings, rows and callouts than the brand kit's defaults. */
.brandline{padding-top:18px;padding-bottom:7px}
.hero>.hero-in,.hero>.wrap:not(td){padding-top:16px;padding-bottom:10px;min-height:0}
.hero-mark{width:46px;height:46px;top:20px}
.hero-title,.hero h1{font-size:27px}
.hero-sub,.hero p{font-size:13.5px;margin-top:8px;line-height:1.45}
.hero .hero-meta{margin-top:12px;padding-top:8px}
.verdict{margin-top:10px}
.v-badge{padding:12px 18px;gap:6px}.v-ic{width:24px;height:24px;font-size:14px}.v-label{font-size:18px}
.v-body{padding:10px 16px}
.top .verdict{margin-top:10px}.top .meta{margin-top:10px}
.meta{gap:10px 24px;margin:10px 0;padding:10px 0}
h2{font-size:17px;margin:18px 0 6px}
h2 .n{margin-bottom:3px}
.intro{margin:0 0 6px;font-size:12px}
p{margin:0 0 6px}
td{padding:5px 8px 5px 0}
th{padding-bottom:5px}
div.bar{margin:3px 0}
ol.grounds li{padding:0 0 8px;grid-template-columns:20px 1fr}
ol.grounds p{margin:0 0 3px}
ol.grounds{margin-top:2px}
blockquote{margin-bottom:3px}
ul.checks li{padding:3px 0 3px 18px}
.callout,.note{padding:10px 14px;margin:10px 0}
.method{margin-top:18px}.method h2{margin:0 0 4px}
.footer,.brand-foot{margin-top:18px;padding-bottom:16px}

/* Wide screens: grounds and checks in two columns, so the width carries content. The verdict and the ticket metadata each get their own full-width row. */
@media screen and (min-width:1100px){
ol.grounds,ul.checks{display:block;column-count:2;column-gap:48px}
ol.grounds li,ul.checks li{break-inside:avoid;page-break-inside:avoid}
ol.grounds li{border-top:0;padding:0 0 22px}
}
"""


# Dark mode is closure-only (the shared brand.css is light and also drives print and PDF): it follows the
# viewer's prefers-color-scheme, and <html data-theme="dark|light"> forces either. Screen only: print stays light.
DARK_VARS = ("--ink:#f1f1ef;--text:#d6d6d3;--t2:#b3b3b0;--t3:#8c8c89;--rule:#3b3b3b;--rule2:#2b2b2b;--track:#343434;"
             "--red:#ee6c74;--blue:#5aa8e8;--amber:#e3a83c;--paper:#121212;--callout:#1d1d1d;--bg:#121212;--card:#121212;"
             "--sev-high:#2a1a1b;--sev-med:#2a2417;--sev-low:#1d1d1d;color-scheme:dark")
DARK_RULES = [
    ("html,body", "background:#121212"),
    (".hero-title,.hero h1,h2,h3,.callout h4,.note h4,td.app b", "color:var(--ink)"),
    (".brandline .bl-l img,.hero-mark", "filter:invert(1)"),
    (".tag,.pill", "background:#121212"),
    (".callout .tag", "background:none"),
    (".verdict .v-badge", "color:#121212"),
    (".verdict.v-good", "--vc:#5cc48d"),
    (".tag.red,.tag.p1", "background:var(--red);border-color:var(--red);color:#121212"),
    (".tag.blue", "background:var(--blue);border-color:var(--blue);color:#121212"),
    (".callout,.note", "background:var(--callout)"),
    (".bar", "background:var(--track)"),
]


def _dark(root):
    pre = root + " "
    rules = "".join(",".join(pre + sel for sel in sels.split(",")) + "{" + body + "}" for sels, body in DARK_RULES)
    return root + "{" + DARK_VARS + "}" + rules


DARK_CSS = ("@media screen and (prefers-color-scheme:dark){" + _dark(':root:not([data-theme="light"])') + "}"
            '@media screen{' + _dark(':root[data-theme="dark"]') + "}")


def meta_value(c, label):
    for m in c.get("meta", []):
        if m.get("label", "").lower() == label:
            return plain(m.get("value", ""))
    return ""


def render(c):
    label, kind = verdict_label(c["verdict"])
    v = c["verdict"]
    # Actionable is separate from the outcome: a benign closure can still need the customer to act.
    action = ""
    if v.get("actionable") is True:
        what = v.get("customer_action") or "see the recommendation."
        action = f'<p><strong>Action needed:</strong> {md(what)}</p>'
    elif v.get("actionable") is False:
        action = '<p><em>No action needed.</em></p>'
    icon = {"good": "\u2713", "watch": "!", "act": "\u2715"}[kind]
    verdict = (f'<div class="verdict v-{kind}"><div class="v-badge"><span class="v-ic" aria-hidden="true">{icon}</span>'
               f'<span class="v-label">{html.escape(label)}</span></div>'
               f'<div class="v-body"><p class="v-tag">Verdict</p><p>{md(v["text"])}</p>{action}</div></div>')
    meta = ('<dl class="meta">' + "".join(f'<div><dt>{html.escape(plain(m["label"]))}</dt><dd>{md(m["value"])}</dd></div>'
                                          for m in c["meta"]) + "</dl>")

    secs = Sections()
    secs.add("Recommendation", paras(c["recommendation"]))  # what to do comes first; the evidence follows
    secs.add(*render_grounds(c["grounds"]))
    if c.get("timeline"):    secs.add(*render_timeline(c["timeline"]))
    if c.get("score_table"): secs.add(*render_score_table(c["score_table"]))
    if c.get("base_rate"):   secs.add(*render_base_rate(c["base_rate"]))
    secs.add(*render_negatives(c["negatives"]))
    if c.get("callouts"):
        secs.out.append("".join(callout(x, "Note") for x in c["callouts"]))

    f = c["footer"]
    tenant, subject = meta_value(c, "tenant"), meta_value(c, "subject")
    chrome = " · ".join(x for x in ["Confidential", tenant, "Incident Closure"] if x)
    foot_left = " · ".join(x for x in ["Fluency Incident Closure", subject, tenant] if x)
    return fb.page(
        title=plain(c["title"]),
        eyebrow=plain(c.get("eyebrow") or "Incident closure · Tier 3 review"),
        subtitle=plain(c["lede"]),
        meta=chrome,
        body=f'<div class="top">{verdict}{meta}</div>' + "".join(secs.out),
        method=f'<p>{md(f.get("label", "Tier 3 review"))} · {md(f["date"])}</p><p>Evidence: {md(f["evidence"])}</p>',
        footer_left=foot_left,
        data_date=plain(f["date"]),
        extra_css=EXTRA_CSS + DARK_CSS,
    ).replace("<h2>Methodology</h2>", "<h2>Evidence</h2>", 1)


REQUIRED = ["title", "lede", "verdict", "meta", "grounds", "negatives", "recommendation", "footer"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("closure_json")
    ap.add_argument("-o", "--out", default="-")
    ap.add_argument("--logo", help=argparse.SUPPRESS)  # retired: the monochrome brand has no replaceable logo
    a = ap.parse_args()
    c = json.load(open(a.closure_json))
    if a.logo or c.get("logo"):
        print("note: the Fluency monochrome brand is fixed; --logo / \"logo\" is ignored", file=sys.stderr)
    missing = [k for k in REQUIRED if not c.get(k)]
    if missing:
        sys.exit(f"closure JSON missing required field(s): {', '.join(missing)}")
    if c["verdict"]["outcome"].lower() not in VERDICTS:
        sys.exit("verdict.outcome must be benign, escalate or confirmed")
    d = c["verdict"].get("disposition")
    if d and str(d).lower() not in DISPOSITIONS:
        sys.exit(f"verdict.disposition must be one of {', '.join(DISPOSITIONS)}")
    sev = c["verdict"].get("severity")
    if sev and str(sev).lower() not in SEVERITIES:
        sys.exit(f"verdict.severity must be one of {', '.join(SEVERITIES)}")
    out = render(c)
    (sys.stdout.write(out) if a.out == "-" else open(a.out, "w").write(out))


if __name__ == "__main__":
    main()
