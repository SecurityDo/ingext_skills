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
    verdict: icon + headline, text, action, impact and respond (own row) · ticket metadata grid (own row)
    §1 recommendation: icon bullets, the main text of each highlighted (what to do, before the evidence)
    §2 grounds (AI-assist claims, each tested)
    timeline          (optional — single-event incidents: raw audit times)
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

def verdict_parts(v):
    """(label, severity word, kind) for the verdict headline: the disposition and severity when given, else the outcome."""
    d = str(v.get("disposition") or "").lower()
    if d in DISPOSITIONS:
        label, kind = DISPOSITIONS[d]
        sev = str(v.get("severity") or "").lower()
        return label, (sev.capitalize() if sev in SEVERITIES else ""), kind
    label, kind = VERDICTS[v["outcome"].lower()]
    return label, "", kind


# One monochrome stroke icon set (24px grid). Colour comes from the state class on the wrapper.
ICONS = {
    "check":   '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9.5"/>',
    "alert":   '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.4v.1"/>',
    "x":       '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
    "lock":    '<rect x="5" y="10.5" width="14" height="9.5" rx="2"/><path d="M8 10.5V8a4 4 0 018 0v2.5"/>',
    "mail":    '<rect x="3" y="5.5" width="18" height="13" rx="2"/><path d="M3.5 7l8.5 6 8.5-6"/>',
    "sliders": '<path d="M4 8h9M17 8h3M4 16h3M11 16h9"/><circle cx="15" cy="8" r="2"/><circle cx="9" cy="16" r="2"/>',
    "sun":     '<circle cx="12" cy="12" r="3.5"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8"/>',
    "info":    '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.8v.1"/>',
    "search":  '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.2-4.2"/>',
    "eye":     '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.7"/>',
    "arrow":   '<path d="M5 12h14M13 6l6 6-6 6"/>',
}


def icon(name, cls=""):
    return f'<span class="ic {cls}" aria-hidden="true"><svg viewBox="0 0 24 24">{ICONS[name]}</svg></span>'


# A recommendation bullet's kind picks its icon and colour. Authors can set it; otherwise it is read from the wording.
REC_KINDS = {  # kind -> (icon, label shown when the author gave none: "" = no label)
    "close": ("check", ""), "contain": ("lock", ""), "confirm": ("mail", ""), "change": ("sun", ""),
    "tune": ("sliders", ""), "monitor": ("eye", ""), "info": ("info", ""),
}
REC_GUESS = [("contain", r"\b(contain|disable|isolate|revoke|kill the|reset the (password|credential))"),
             ("confirm", r"\b(confirm|ask |verify with|check with)"),
             ("tune", r"\b(tun(e|ing)|mask|suppress|the rule fires)"),
             ("change", r"\b(block|enforce|enable|require|restrict|conditional access)"),
             ("close", r"\b(close|no action|nothing to)")]


def rec_kind(item_kind, text):
    k = str(item_kind or "").lower()
    if k in REC_KINDS:
        return k
    for name, pat in REC_GUESS:
        if re.search(pat, text, re.I):
            return name
    return "info"


def highlight_main(text, main=None):
    """The bullet's main point in bold: `main` when given, else the first sentence (or its first clause when the
    sentence runs long). Text the author already marked with ** is left as written; a text with no short
    opening point is left plain rather than bolded whole."""
    t = str(text or "")
    if main:
        return f'<span class="main">{md(main)}</span> {md(t)}'.rstrip()
    if "**" in t:
        return md(t)
    m = re.match(r"(.+?[.!?])(\s+|$)", t, re.S)
    lead = m.group(1) if m else t
    if len(lead) > 180:  # long opening sentence: take a first clause of a useful length, or highlight nothing
        for c in re.finditer(r"\s(?:\u2014|\u2013|-)\s|[;:]\s", lead[:170]):
            end = c.start() + (1 if lead[c.start()] in ";:" else 0)
            if end >= 45:
                lead = lead[:end]
                break
        else:
            return md(t)
    rest = t[len(lead):].lstrip()
    return f'<span class="main">{md(lead)}</span>' + (f" {md(rest)}" if rest else "")


def render_recommendations(rec):
    """Bullets, each with an icon and its main text highlighted. `recommendation` is a string, a list of strings,
    or a list of {text, label?, kind?, main?}; a paragraph per line becomes a bullet."""
    items = rec if isinstance(rec, list) else str(rec).split("\n")
    out = []
    for it in items:
        if isinstance(it, dict):
            text, label, kind, main = it.get("text", ""), it.get("label", ""), it.get("kind"), it.get("main")
        else:
            text, label, kind, main = it, "", None, None
        if not str(text).strip() and not main:
            continue
        k = rec_kind(kind, f"{label} {main or ''} {text}")
        lab = f'<p class="rl">{md(label)}</p>' if label else ""
        out.append(f'<li>{icon(REC_KINDS[k][0], "r-" + k)}<div>{lab}<p class="rt">{highlight_main(text, main)}</p></div></li>')
    return f'<ul class="recs">{"".join(out)}</ul>'


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
    return (f'<div class="callout {kind}"><p class="tag">{icon("alert" if kind in ("watch", "act") else "info")}{html.escape(tag_text)}</p>{head}'
            f'{paras(c["body"])}</div>')


ENTRY_STATE = {"established": ("Established from the rows", "red"), "likely": ("Likely, not proven", "amber"),
               "not_established": ("Not established", "gray")}


def render_entry(e):
    """How the attacker got in: the entry steps from the raw rows, the control that did not
    stop it, and what would settle an entry the rows do not show."""
    state = ENTRY_STATE.get(str(e.get("state", "")).lower())
    head = f'<p>{fb.tag(state[0], state[1])}</p>' if state else ""
    body = paras(e["body"]) if e.get("body") else ""
    steps = ""
    if e.get("steps"):
        items = "".join(f'<li><time>{md(r.get("time", ""))}</time><span class="dot"></span>'
                        f'<div class="tl-body"><p>{md(r["event"])}</p></div></li>' for r in e["steps"])
        steps = f'<ol class="tl">{items}</ol>'
    why = callout({"title": "Why it worked", "body": e["why_it_worked"]}, "Control gap", "watch") if e.get("why_it_worked") else ""
    missing = callout({"title": "What would settle it", "body": e["missing"]}, "Gap", "watch") if e.get("missing") else ""
    return e.get("title") or "How the attacker got in", head + body + steps + why + missing


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


def render_base_rate(b):
    cols = b["columns"]
    rows = [[f"<code>{md(v)}</code>" if i == 0 else md(v) for i, v in enumerate(r)] for r in b["rows"]]
    table = fb.table(cols, rows, num_cols=tuple(range(1, len(cols))), raw_cols=tuple(range(len(cols))),
                     foot=md(b["caption"]) if b.get("caption") else "")
    return b["title"], table, b.get("intro")


def render_negatives(n):
    items = "".join(f'<li>{icon("check")}<strong>{md(x["title"])}</strong> {md(x.get("body", ""))}</li>' for x in n["items"])
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
ul.checks li{position:relative;padding:5px 0 5px 22px}
td code,.sec-body code{font-family:var(--mono)}
@media print{ol.grounds li{break-inside:avoid;page-break-inside:avoid}}
.top{display:grid;grid-template-columns:minmax(0,1fr);column-gap:44px;align-items:start}
.top .meta{margin-top:10px}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px 28px;margin:16px 0;padding:16px 0;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule)}
.meta dt{font:500 9px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--t3);margin:0 0 6px}
.meta dd{margin:0;overflow-wrap:anywhere;color:var(--ink)}
.meta .sub{display:block;margin-top:2px;font-size:11.5px;color:var(--t2)}
/* Full width on screen: the brand kit's 816px (US Letter) column is for print and PDF, which keep it. */
@media screen{
:root{--w:none;--px:40px}
.hero-title,.hero h1{max-width:min(1000px,calc(100% - 90px))}
.hero-sub,.hero p{max-width:min(860px,calc(100% - 90px))}
table,table.data{table-layout:auto}
td,th{overflow-wrap:anywhere}
blockquote,ol.grounds p,ul.checks li{max-width:none}
}
@media screen and (max-width:640px){:root{--px:20px}}
/* Icons: one monochrome stroke set (see ICONS); colour comes from the state. */
.ic{display:inline-grid;place-items:center;flex:none;color:var(--t2)}
.ic svg{width:100%;height:100%;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
ul.checks .ic{color:#1b7f4b}.ic.s-good,.ic.r-close{color:#1b7f4b}.ic.s-watch,.ic.r-change,.ic.r-tune{color:var(--amber)}.ic.s-act,.ic.r-contain{color:var(--red)}.ic.r-confirm,.ic.r-info{color:var(--blue)}
/* Verdict: tinted box, state icon and headline, the severity word in the state colour, then impact and respond */
.verdict{--vt:#e8f3ec;margin:10px 0 0;padding:14px 20px 14px;background:var(--vt);border-left:4px solid var(--vc);-webkit-print-color-adjust:exact;print-color-adjust:exact}
.verdict.v-good{--vc:#1b7f4b;--vt:#e8f3ec}.verdict.v-watch{--vc:var(--amber);--vt:#faefd6}.verdict.v-act{--vc:var(--red);--vt:#fbe9ea}
.v-tag{font:500 8.5px/1.4 var(--mono);letter-spacing:.15em;text-transform:uppercase;color:var(--t3);margin:0 0 4px}
.v-head{display:flex;align-items:center;gap:10px;margin:0 0 6px;font-size:20px;line-height:1.2;font-weight:700;letter-spacing:-.01em;color:var(--ink)}
.v-head .ic{width:26px;height:26px;color:var(--vc)}
.v-sev{color:var(--vc)}
.verdict p{margin:0 0 6px}.verdict p:last-child{margin:0}
.v-split{display:grid;grid-template-columns:minmax(0,1fr) minmax(200px,300px);gap:6px 36px;margin-top:10px;padding-top:10px;border-top:1px solid color-mix(in srgb,var(--vc) 28%,transparent)}
.v-split p{margin:0}
.v-rh{font-size:15px;font-weight:700;color:var(--vc);line-height:1.25;margin:2px 0 3px!important}
.v-rn{font-size:11.5px;color:var(--t2)}
@media screen and (max-width:760px){.v-split{grid-template-columns:1fr}}
/* Recommendations: icon bullets, the main text highlighted */
ul.recs{list-style:none;margin:4px 0 0;padding:0}
ul.recs li{display:grid;grid-template-columns:26px minmax(0,1fr);gap:0 12px;padding:9px 0;border-top:1px solid var(--rule)}
ul.recs li:first-child{border-top:0;padding-top:2px}
ul.recs .ic{width:22px;height:22px;margin-top:1px}
ul.recs .rl{font:500 9px/1.4 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--t2);margin:0 0 2px}
ul.recs .rt{margin:0}
ul.recs .main{font-weight:700;color:var(--ink);background:linear-gradient(transparent 62%,color-mix(in srgb,var(--blue) 18%,transparent) 62%)}
ul.checks li .ic{position:absolute;left:0;top:4px;width:15px;height:15px}
.callout .tag{display:flex;align-items:center;gap:6px}.callout .tag .ic{width:13px;height:13px}
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
ul.checks li{padding:3px 0 3px 22px}
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
    (".verdict.v-good", "--vc:#5cc48d;--vt:#16271e"),
    (".verdict.v-watch", "--vt:#2a2417"),
    (".verdict.v-act", "--vt:#2b1a1c"),
    (".ic.s-good,.ic.r-close,ul.checks .ic", "color:#5cc48d"),
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


RISK_LABEL = re.compile(r"risk\s*-?score", re.I)


def render_verdict(v):
    """The verdict box: state icon and headline (the severity word in the state colour), the verdict text, what the
    customer must do, then an optional row with the impact on the left and the response on the right."""
    label, sev, kind = verdict_parts(v)
    icon_name = {"good": "check", "watch": "alert", "act": "x"}[kind]
    head = f'{html.escape(label)}' + (f' <span class="v-sev">{html.escape(sev)}</span>' if sev else "")
    # Actionable is separate from the outcome: a benign closure can still need the customer to act.
    action = ""
    if v.get("actionable") is True:
        what = v.get("customer_action") or "see the recommendation."
        action = f'<p><strong>Action needed:</strong> {md(what)}</p>'
    elif v.get("actionable") is False:
        action = '<p><em>No action needed.</em></p>'
    split = ""
    imp, resp = v.get("impact"), v.get("respond")
    if imp or resp:
        left = right = ""
        if imp:
            ilabel, itext = (imp.get("label", "Impact"), imp.get("text", "")) if isinstance(imp, dict) else ("Impact", imp)
            left = f'<div><p class="v-tag">{md(ilabel)}</p><p>{md(itext)}</p></div>'
        if resp:
            rh, rn = (resp.get("headline", ""), resp.get("note", "")) if isinstance(resp, dict) else (resp, "")
            right = (f'<div><p class="v-tag">Respond</p><p class="v-rh">{md(rh)}</p>'
                     + (f'<p class="v-rn">{md(rn)}</p>' if rn else "") + "</div>")
        split = f'<div class="v-split">{left}{right}</div>'
    return (f'<div class="verdict v-{kind}"><p class="v-tag">Verdict</p>'
            f'<h4 class="v-head">{icon(icon_name, "s-" + kind)}<span>{head}</span></h4>'
            f'<p>{md(v["text"])}</p>{action}{split}</div>'), kind


def render_meta(items):
    """The ticket metadata grid. A `sub` line sits under the value in muted type. Risk scores are not shown."""
    cells = "".join(
        f'<div><dt>{html.escape(plain(m["label"]))}</dt><dd>{md(m["value"])}'
        + (f'<span class="sub">{md(m["sub"])}</span>' if m.get("sub") else "") + "</dd></div>"
        for m in items if not RISK_LABEL.search(str(m.get("label", ""))))
    return f'<dl class="meta">{cells}</dl>'


def render(c):
    verdict, kind = render_verdict(c["verdict"])
    meta = render_meta(c["meta"])
    closed = kind == "good"  # closed and benign verdicts end the ticket; anything else is still open
    doc = "Incident Closure" if closed else "Incident Analysis"

    secs = Sections()
    secs.add("Recommendation", render_recommendations(c["recommendation"]))  # what to do comes first
    if c.get("entry"):       secs.add(*render_entry(c["entry"]))
    secs.add(*render_grounds(c["grounds"]))
    if c.get("timeline"):    secs.add(*render_timeline(c["timeline"]))
    if c.get("base_rate"):   secs.add(*render_base_rate(c["base_rate"]))
    secs.add(*render_negatives(c["negatives"]))
    if c.get("callouts"):
        secs.out.append("".join(callout(x, "Note") for x in c["callouts"]))

    f = c["footer"]
    tenant, subject = meta_value(c, "tenant"), meta_value(c, "subject")
    chrome = " · ".join(x for x in ["Confidential", tenant, doc] + ([] if closed else ["Open"]) if x)
    foot_left = " · ".join(x for x in [f"Fluency {doc}", subject, tenant] if x)
    return fb.page(
        title=plain(c["title"]),
        eyebrow=plain(c.get("eyebrow") or f"{doc.replace('Incident ', 'Incident ').lower().capitalize()} · Tier 3 review"),
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
    if c.get("score_table"):
        print("note: risk scores are not shown in the report; score_table is ignored", file=sys.stderr)
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
