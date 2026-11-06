#!/usr/bin/env python3
"""Simulate the FAIR scenarios and render the Cyber Risk in Dollars board report (HTML + PDF), Fluency editorial style.

  render_report.py scenarios.json [OUT_DIR] [--date DDMonYY] [--no-pdf] [--iterations N]

scenarios.json is the output of calibrate_scenarios.py (schema: assets/sample_scenarios.json). Per scenario the
loss event frequency (events a year) and each loss component are min / most likely / max ranges; the simulation samples
PERT distributions, draws a Poisson event count per simulated year and sums the losses. It runs the current state and the
state after the recommended actions. Text fields may use the tokens {TENANT} {ALE} {P90} {P95} {TALE} {SAVED} {TOP_NAME}
{TOP_SHARE} {FREQ_NAME} {APPETITE}, filled from the simulation so the words always match the numbers. Text is HTML.
"""
import argparse, bisect, datetime, html, json, math, os, random, re
import os as _os, sys as _sys, glob as _glob


def _find_brand_kit():
    # The Fluency report brand kit lives only in the `fluency-report` skill (scripts/). Find that skill next to this one.
    here = _os.path.dirname(_os.path.abspath(__file__)); home = _os.path.expanduser("~")
    cands = [_os.environ.get("FLUENCY_BRAND_DIR"), here]
    up = here
    for _ in range(5):
        up = _os.path.dirname(up); cands.append(_os.path.join(up, "fluency-report", "scripts"))
    cands += [_os.path.join(home, ".claude", "skills", "fluency-report", "scripts")]
    cands += _glob.glob(_os.path.join(home, ".claude", "skills", "**", "fluency-report", "scripts"), recursive=True)
    for c in cands:
        if c and _os.path.exists(_os.path.join(c, "fluency_brand.py")):
            return c
    raise SystemExit("The Fluency report brand kit was not found. Install the `fluency-report` skill (this report uses its "
                     "scripts/fluency_brand.py and brand.css), or set FLUENCY_BRAND_DIR to that skill's scripts folder.")


_sys.path.insert(0, _find_brand_kit())
import fluency_brand as fb  # Fluency report brand kit, from the fluency-report skill

ITER = 20000


def pert(lo, ml, hi, rng):
    if hi <= lo:
        return lo
    a = 1 + 4 * (ml - lo) / (hi - lo)
    b = 1 + 4 * (hi - ml) / (hi - lo)
    return lo + rng.betavariate(a, b) * (hi - lo)


def poisson(lam, rng):
    if lam <= 0:
        return 0
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def simulate(sc, lef_mult=1.0, lm_mult=1.0, seed=7, iters=ITER):
    rng = random.Random(seed)
    lf, out = sc["lef"], []
    for _ in range(iters):
        n = poisson(pert(lf["min"], lf["ml"], lf["max"], rng) * lef_mult, rng)
        out.append(sum(sum(pert(c["min"], c["ml"], c["max"], rng) for c in sc["loss"]) * lm_mult for _e in range(n)))
    return out


def pct(xs, p):
    s = sorted(xs)
    return s[min(len(s) - 1, int(p / 100 * len(s)))]


def money(v):
    v = float(v)
    if v >= 1e6:
        return "$%.1fM" % (v / 1e6)
    if v >= 1e3:
        return "$%.0fK" % (v / 1e3)
    return "$%.0f" % v


def plain(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or ""))


def effects_for(treat, sid):
    lf = lm = 1.0
    for t in treat:
        e = t.get("effects", {}).get(sid, {})
        lf *= e.get("lef", 1.0)
        lm *= e.get("lm", 1.0)
    return lf, lm


def build(d, out_dir, date_override=None, pdf=True, iters=ITER):
    when = datetime.datetime.strptime(d["assessment_date"], "%Y-%m-%d")
    stamp = date_override or when.strftime("%d%b%y")
    tenant = d["tenant"]
    treat = d.get("treatments", [])
    sims, cur_tot, trt_tot = [], [0.0] * iters, [0.0] * iters
    for i, sc in enumerate(d["scenarios"]):
        lf, lm = effects_for(treat, sc["id"])
        c, t = simulate(sc, seed=11 + i, iters=iters), simulate(sc, lf, lm, seed=11 + i, iters=iters)
        cur_tot = [a + b for a, b in zip(cur_tot, c)]
        trt_tot = [a + b for a, b in zip(trt_tot, t)]
        sims.append(dict(sc=sc, mean=sum(c) / iters, p90=pct(c, 90), tmean=sum(t) / iters,
                         prob=sum(1 for v in c if v > 0) / iters, ev=sum(x["ml"] for x in sc["loss"])))
    sims.sort(key=lambda r: -r["mean"])
    ale, p90, p95 = sum(cur_tot) / iters, pct(cur_tot, 90), pct(cur_tot, 95)
    tale, tp90 = sum(trt_tot) / iters, pct(trt_tot, 90)
    appetite, limit = d.get("risk_appetite"), d.get("insurance_limit")
    top = sims[0]
    freq = max(sims, key=lambda r: r["prob"])
    tok = {"TENANT": tenant, "ALE": money(ale), "P90": money(p90), "P95": money(p95), "TALE": money(tale), "SAVED": money(ale - tale),
           "TOP_NAME": top["sc"]["name"], "TOP_SHARE": "%d%%" % round(100 * top["mean"] / ale) if ale else "0%",
           "FREQ_NAME": freq["sc"]["name"], "APPETITE": money(appetite) if appetite else ""}
    fill = lambda s: re.sub(r"\{([A-Z_0-9]+)\}", lambda m: tok.get(m.group(1), m.group(0)), s or "")

    kpis = [fb.kpi("Expected annual loss", money(ale), color="red"), fb.kpi("1-in-10 year loss", money(p90), color="amber"),
            fb.kpi("1-in-20 year loss", money(p95)), fb.kpi("Expected loss after actions", money(tale), color="blue")]

    body = fb.section(1, fill(d["headline"]).replace("&amp;", "&"), "<p>%s</p>" % fill(d["summary"]))
    body += '<div class="callout act"><h4>Board ask</h4><p>%s</p></div>' % (lambda s: s[:1].upper() + s[1:])(fill(d["board_ask"]))
    if appetite:
        inside = p90 <= appetite
        body += '<div class="callout %s"><h4>Risk appetite</h4><p>A 1-in-10-year loss of %s is %s the stated tolerance of %s. After the recommended actions it would be %s%s.</p></div>' % (
            "" if inside else "act", money(p90), "within" if inside else "above", money(appetite), money(tp90),
            "" if tp90 > appetite else ", back inside tolerance")
    if limit:
        over = sum(1 for v in cur_tot if v > limit) / iters
        body += '<div class="callout"><h4>Insurance limit</h4><p>About %.1f%% of simulated years lose more than the %s cyber insurance limit supplied (losses shown gross, before recoveries).</p></div>' % (100 * over, money(limit))

    # 2. Loss exceedance curve and scenario bars
    mx = max(pct(cur_tot, 99.5), 1)
    xs = [mx * i / 60 for i in range(61)]
    s_cur, s_trt = sorted(cur_tot), sorted(trt_tot)
    curve = lambda s: [100.0 * (1 - bisect.bisect_right(s, x) / len(s)) for x in xs]
    chart = fb.line_chart([money(x) for x in xs], [("Current", curve(s_cur)), ("After recommended actions", curve(s_trt))],
                          colors=["#b3242e", "#175d9a"], y_label="Chance a year's loss exceeds this amount (%)", height=230)
    chart += '<p class="fn">Each point is the chance (vertical axis, percent) that one year of cyber losses exceeds the amount on the horizontal axis. %s simulated years.</p>' % format(iters, ",")
    short = lambda n: re.split(r" &amp;| \(", n)[0]
    bars = fb.bar_rows([(short(r["sc"]["name"]), r["mean"], "#b3242e" if i == 0 else "#8a8a8a", money(r["mean"])) for i, r in enumerate(sims)], fmt=money)
    body += fb.section(2, "How large the loss could be", chart + '<h3>Expected annual loss by scenario</h3>' + bars)

    # 3. Risk register
    reg = [["<b>%s</b><br><span class=\"fn\">%s</span>" % (r["sc"]["name"], r["sc"]["description"]), "%d%%" % round(100 * r["prob"]), money(r["ev"]),
            "<b>%s</b>" % money(r["mean"]), money(r["p90"]), money(r["tmean"])] for r in sims]
    reg.append(["<b>Total</b>", "", "", "<b>%s</b>" % money(ale), money(p90), money(tale)])
    body += fb.section(3, "Quantified risk register", fb.table(
        ["Scenario", "Chance", "Per event", "Per year", "1-in-10", "After actions"], reg,
        widths=["31%", "12%", "13%", "16%", "14%", "14%"], num_cols=(1, 2, 3, 4, 5), raw_cols=(0, 1, 2, 3, 4, 5), total_last=True,
        foot="Chance is the share of simulated years with at least one event. Per event is the typical cost of one event, per year the expected annual loss, 1-in-10 the loss in a bad year. Ranges are modelled, not forecasts."))

    # 4. Drivers
    drv = []
    for r in sims:
        sc = r["sc"]
        ev = "<ul>%s</ul>" % "".join("<li>%s</li>" % e for e in sc["evidence"])
        rng_ = ("<p class=\"fn\"><b>Frequency (events a year):</b> %s &ndash; %s &ndash; %s (min, likely, max)<br><b>Loss per event:</b> %s</p>" % (
            sc["lef"]["min"], sc["lef"]["ml"], sc["lef"]["max"],
            ", ".join("%s %s&ndash;%s" % (c["name"], money(c["min"]), money(c["max"])) for c in sc["loss"])))
        drv.append('<div style="break-inside:avoid"><h3>%s</h3>%s</div>' % (sc["name"], fb.table(
            ["What the telemetry shows", "How it shapes the estimate"], [[ev, "<p>%s</p>%s" % (sc["calibration"], rng_)]],
            widths=["52%", "48%"], raw_cols=(0, 1))))
    body += fb.section(4, "What drives each scenario", "".join(drv))

    # 5. Treatments
    base_sum = sum(r["mean"] for r in sims)
    trows = []
    for k, t in enumerate(treat):
        after = 0.0
        for i, sc in enumerate(d["scenarios"]):
            e = t.get("effects", {}).get(sc["id"], {})
            after += sum(simulate(sc, e.get("lef", 1), e.get("lm", 1), seed=11 + i, iters=iters)) / iters if e else next(r["mean"] for r in sims if r["sc"]["id"] == sc["id"])
        cut = base_sum - after
        cost = t.get("annual_cost")
        ret = ("%.1f&times;" % (cut / cost)) if cost else "&ndash;"
        trows.append((cut, ["<b>%s</b><br><span class=\"fn\">%s</span>" % (t["name"], t["detail"]), "%s<br><span class=\"fn\">%s</span>" % (t["owner"], t["timeframe"]),
                            "<b>%s</b>" % money(cut), money(cost) if cost else "to be supplied", ret]))
    trows.sort(key=lambda x: -x[0])
    body += fb.section(5, "What each recommended action is worth", fb.table(
        ["Action", "Owner, timeframe", "Avoided", "Cost", "Return"], [r for _, r in trows],
        widths=["44%", "16%", "14%", "13%", "13%"], num_cols=(2, 3, 4), raw_cols=(0, 1, 2, 3, 4),
        foot="Avoided is the drop in expected annual loss a year if that action alone is done. Actions overlap, so the figures do not add up to the total."))

    # 6. Assumptions
    body += fb.section(6, "Assumptions to confirm", "<ul>%s</ul>" % "".join("<li>%s</li>" % a for a in d["assumptions"]))

    method = ("<p>Risk is loss event frequency times loss magnitude. Each input is a calibrated range; the model samples PERT distributions, draws a Poisson number of events for each of %s simulated years and sums the losses. "
              "Frequencies come from a baseline raised by the evidence in the readiness assessment and widened where telemetry cannot measure a control. Results are modelled ranges, not forecasts. No individual users or hosts are named. Sources:</p><ul>%s</ul>" % (
                  format(iters, ","), "".join("<li>%s</li>" % s for s in d["sources"])))
    title = "Cyber Risk in Dollars"
    doc = fb.page(title, "Cyber risk quantification · board confidential", body=body,
                  subtitle="What a cyber incident could cost %s a year, and what each recommended action is worth, from live security telemetry." % plain(tenant),
                  meta="Prepared by Fluency Security · Connector: %s · Assessment date: %s · Evidence window: %s" % (plain(tenant), when.strftime("%d %B %Y"), plain(d.get("evidence_window", ""))),
                  kpis=kpis, method=method, footer_left="Fluency Security · Cyber Risk in Dollars · %s" % plain(tenant), data_date=when.strftime("%d %b %Y"))
    os.makedirs(out_dir, exist_ok=True)
    base = "Cyber_Risk_in_Dollars_%s_%s" % (re.sub(r"[^A-Za-z0-9]+", "", plain(tenant)), stamp)
    hp = os.path.join(out_dir, base + ".html")
    open(hp, "w", encoding="utf-8").write(doc)
    out = [hp]
    if pdf:
        try:
            pp = os.path.join(out_dir, base + ".pdf")
            fb.to_pdf(hp, pp, title=title)
            out.append(pp)
        except Exception as e:
            print("PDF step skipped (%s)" % e)
    print("ALE %s  P90 %s  P95 %s  treated ALE %s  largest: %s (%s)" % (money(ale), money(p90), money(p95), money(tale), plain(top["sc"]["name"]), tok["TOP_SHARE"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios")
    ap.add_argument("out_dir", nargs="?", default=".")
    ap.add_argument("--date", help="run date stamp DDMonYY (default: the assessment date)")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--iterations", type=int, default=ITER)
    a = ap.parse_args()
    for p in build(json.load(open(a.scenarios, encoding="utf-8")), a.out_dir, a.date, not a.no_pdf, a.iterations):
        print(p)


if __name__ == "__main__":
    main()
