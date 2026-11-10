#!/usr/bin/env python3
"""Rate disclosure readiness from the measured evidence and draft the findings JSON.

  rate_evidence.py --cases case_evidence.json --platform platform_evidence.json --tenant "Name" --date YYYY-MM-DD
                   [--applicability applicability.json] [--rules ../assets/rating_rules.json] --out draft_findings.json

Everything rated comes from assets/rating_rules.json. Text is plain (the renderer escapes it). No individual is named.

applicability.json (optional; counsel's answers):
  {"sec": "yes|no|unknown", "nis2": "...", "dora": "...", "customer": "...", "customer_notice_hours": 72,
   "reportability_register": false, "notes": "free text"}
Unknown SEC / NIS2 applicability is shown as "Confirm"; DORA defaults to "no" (not applicable) unless the tenant is a financial entity.
"""
import argparse, datetime, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
RANK = {"ready": 0, "partial": 1, "not ready": 2}


def worst(statuses):
    s = [x for x in statuses if x in RANK]
    return max(s, key=lambda x: RANK[x]) if s else "confirm"


def n(x):
    return "{:,}".format(int(x))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", required=True); ap.add_argument("--platform", required=True); ap.add_argument("--tenant", required=True)
    ap.add_argument("--date", required=True); ap.add_argument("--applicability"); ap.add_argument("--rules", default=os.path.join(HERE, "..", "assets", "rating_rules.json"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    R = json.load(open(a.rules)); C = json.load(open(a.cases)); P = json.load(open(a.platform))
    app = json.load(open(a.applicability)) if a.applicability else {}
    asof = datetime.datetime.strptime(a.date, "%Y-%m-%d")
    reg, op, cl, tr = C["register"], C["open"], C["closed_sample"], C["triage"]
    total, opn = reg["total"], reg["open"]
    dl = R["tightest_deadline_hours"]
    complete = op["complete"]
    ge = "" if complete else "at least "
    plus = "" if complete else "+"

    # ---- capabilities -------------------------------------------------------------------------------------------
    cap = {}
    cov, med = tr["coverage_pct"], tr["median_minutes"]
    if not total:
        cap["triage"] = ("partial", "No cases at risk %s+ in %d days, so triage speed was not exercised." % (n(R["case_risk_floor"]), R["window_days"]))
    elif not tr["with_ai_verdict"]:
        cap["triage"] = ("partial", "%s cases at risk %s+ in %d days. None carries an AI-analyst verdict, so time to first triage cannot be measured." % (n(total), n(R["case_risk_floor"]), R["window_days"]))
    else:
        ok = cov >= R["triage"]["ready_coverage_pct"] and med is not None and med <= R["triage"]["ready_median_minutes"]
        cap["triage"] = ("ready" if ok else "partial", "%s cases at risk %s+ in %d days; %d%% of those examined carry an AI-analyst verdict, median %s min to the first one%s." % (
            n(total), n(R["case_risk_floor"]), R["window_days"], round(cov), "%g" % med if med is not None else "n/a",
            ", slowest tenth over %g min" % tr["p90_minutes"] if tr["p90_minutes"] else ""))
    old_share = (100.0 * op["older_than_flag"] / op["fetched"]) if op["fetched"] else 0.0
    esc_over = op["escalated_over_deadline"]
    own_bad = esc_over > 0 or old_share >= R["ownership"]["not_ready_open_old_share_pct"]
    pct_open = (100.0 * opn / total) if total else 0
    ev = "%s cases (%d%%) still open" % (n(opn), round(pct_open))
    if tr["with_ai_verdict"]:
        ev += "; %s%d escalated by the AI analyst %s" % (ge if op["escalated"] else "", op["escalated"], "with no recorded human decision" if op["escalated_no_human"] == op["escalated"] and op["escalated"] else "(%d without a human decision)" % op["escalated_no_human"])
    else:
        ev += "; no AI escalation is recorded, so a human decision is the only clock stop"
    if op["oldest_days"] is not None:
        ev += "; oldest open case %s days old, %s older than %d days" % (n(round(op["oldest_days"])), ge + n(op["older_than_flag"]), op["flag_days"])
    cap["ownership"] = ("not ready" if own_bad else ("partial" if opn else "ready"), ev + ".")
    rf = C["reportability"]["field_found"]; reg_asserted = bool(app.get("reportability_register"))
    unc = reg["unclassified"]
    rev = "Cases carry SOC labels only (benign, false positive, true positive); %s (%d%%) are unclassified; no significant, material or notifiable flag." % (n(unc), round(100.0 * unc / total)) if total else "No cases to assess."
    if rf:
        cap["reportability"] = ("ready", "A reportability or materiality marker was found on case classifications or actions; %s (%d%%) cases are unclassified." % (n(unc), round(100.0 * unc / max(total, 1))))
    elif reg_asserted:
        cap["reportability"] = ("partial", "Counsel states determinations are recorded outside the SIEM; the case itself carries no marker. " + rev)
    else:
        cap["reportability"] = ("not ready", rev)
    rt = P["retention"]; md = rt["min_days"]
    if md is None:
        cap["timeline"] = ("confirm", "History was not measured.")
    else:
        st = "ready" if md >= R["retention"]["ready_days"] else ("partial" if md >= R["retention"]["partial_days"] else "not ready")
        names = ", ".join("%s %d days" % (t, v["days"]) for t, v in sorted(rt["tables"].items(), key=lambda kv: kv[1]["days"]))
        cap["timeline"] = (st, "Earliest event held: %s. Attackers are often present longer than this." % names if st != "ready" else "Earliest event held: %s." % names)
    sc = P["scope"]; present = [k for k, v in sc.items() if v["present"]]
    need = R["scope_ready_categories"]; missing = [k for k in need if not sc[k]["present"]]
    sst = "ready" if not missing else ("partial" if len([k for k in need if sc[k]["present"]]) >= 2 else "not ready")
    cap["scope"] = (sst, "Visible: %s. %s" % ("; ".join(sc[k]["label"] for k in present) or "nothing measured",
                                              ("Not visible in this tenant's data: %s." % "; ".join(sc[k]["label"] for k in missing)) if missing else "All four scoping sources are present."))
    cr = P.get("clearing")
    if cr is None:
        cap["integrity"] = ("confirm", "Log clearing and directory-change auditing were not checked in this run.")
    elif cr["count"] > 0:
        cap["integrity"] = ("not ready", "Security logs were cleared %s times in %d days; cleared evidence weakens any report." % (n(cr["count"]), cr["days"]))
    else:
        cap["integrity"] = ("ready", "No log-clearing events in %d days." % cr["days"])
    cap["vendors"] = ("confirm", "Vendor incident notices are not visible in the SIEM; documents and contacts to be provided.")
    cap["workflow"] = ("confirm", "Board, legal and customer-notification approvers and templates are not visible in the SIEM; documents to be provided.")

    CAPS = [("triage", "Detection and automated triage", "Starts every disclosure clock.", "All regimes"),
            ("ownership", "Human escalation and ownership", "Someone must own the decision and the clock.", "%d h" % dl),
            ("reportability", "Reportability classification", "Regulators test the timing of the determination.", "SEC / NIS2"),
            ("timeline", "Timeline reconstruction", "Required for 72-hour and final reports.", "72 h / 1 month"),
            ("scope", "Scope of data and systems affected", "Drives materiality and customer impact.", "72 h"),
            ("integrity", "Evidence integrity", "Reports must be defensible.", "Final report"),
            ("vendors", "Third-party incident awareness", "Supplier incidents can trigger reporting.", "NIS2 Art. 21"),
            ("workflow", "Board, legal and customer notification workflow", "Decisions need named approvers and templates.", "All regimes")]
    capabilities = [{"id": k, "capability": nm, "why": why, "evidence": cap[k][1], "target": tgt, "status": cap[k][0]} for k, nm, why, tgt in CAPS]

    # ---- regimes ------------------------------------------------------------------------------------------------
    deps = {k: v["depends"] for k, v in R["regimes"].items()}
    cust_h = app.get("customer_notice_hours", 72)
    RT = {
        "sec": {"scope": "US public companies: disclose a material cybersecurity incident within 4 business days of determining it is material; determine materiality without unreasonable delay. Annual 10-K Item 1C describes risk management and governance.",
                "app": "Only if %s or a parent is an SEC registrant (to confirm). Public customers must assess incidents at suppliers, so they will ask for fast, factual information either way." % a.tenant,
                "clock": [("Discovery", "assess materiality without unreasonable delay"), ("+4 business days", "file Form 8-K Item 1.05 after the determination"), ("Later", "amend the 8-K as facts become known")]},
        "nis2": {"scope": "Essential and important entities in the EU: report significant incidents to the national CSIRT or authority.",
                 "app": "Applies only if %s is established in, or provides services into, an EU member state (to confirm). EU customers may flow obligations down by contract." % a.tenant,
                 "clock": [("24 hours", "early warning after becoming aware of a significant incident"), ("72 hours", "incident notification with initial assessment and indicators"), ("1 month", "final report with root cause and mitigations")]},
        "dora": {"scope": "EU financial entities and critical ICT third-party providers: report major ICT-related incidents.",
                 "app": "Not expected to apply unless %s is an EU financial entity or critical ICT provider. Its 4-hour initial-notification standard is used here only as a stretch benchmark." % a.tenant,
                 "clock": [("4 hours", "initial notification after classifying as major (no later than 24 hours from awareness)"), ("72 hours", "intermediate report"), ("1 month", "final report")]},
        "customer": {"scope": "Customer agreements and privacy law typically require notice of security incidents within 24 to 72 hours; US state breach laws and GDPR apply to personal data.",
                     "app": "Assumed to apply: contractual notice clauses are common. Counsel to confirm the notice periods in force (%d hours assumed here)." % cust_h,
                     "clock": [("%d hours" % cust_h, "typical contractual notification clause"), ("72 hours", "GDPR personal-data breach notification (if EU data)"), ("State law", "US breach notification without unreasonable delay")]},
    }
    GAP = {"sec": "No materiality-assessment step or decision record is visible in the incident workflow.",
           "nis2": "A significance decision within 24 hours is not achievable while open cases wait for a human." if own_bad else "The 24-hour early warning depends on a recorded significance decision, which is not visible.",
           "dora": "Not applicable; see NIS2 for the operative EU requirement.",
           "customer": "No register of customer notification obligations is linked to the incident workflow."}
    regimes = []
    for k, rv in R["regimes"].items():
        computed = worst([cap[d][0] for d in deps[k]])
        av = app.get(k, rv["default_applicability"])
        if av == "no":
            rd, gap = "n/a", GAP[k] if k == "dora" else "Counsel states this regime does not apply."
        elif av == "unknown":
            rd = "confirm"; gap = "If it applies the readiness is %s. %s" % (computed.title(), GAP[k])
        else:
            rd, gap = computed, GAP[k]
        if k == "dora" and av == "no":
            rd, gap = "n/a", GAP[k]
        regimes.append({"id": k, "regime": rv["name"], "readiness": rd, "computed": computed, "scope": RT[k]["scope"], "applicability": RT[k]["app"],
                        "clock": [{"when": w, "what": t} for w, t in RT[k]["clock"]], "gap": gap})

    # ---- clock test ---------------------------------------------------------------------------------------------
    BLUE, RED, AMB, GRY = "#175d9a", "#b3242e", "#a06c00", "#8a857c"
    clock = []
    if med is not None:
        clock.append({"step": "Detect and auto-triage", "pct": max(2, round(100.0 * med / (dl * 60))), "label": "~%g min" % med, "color": BLUE})
    else:
        clock.append({"step": "Detect and auto-triage", "pct": 0, "label": "Not evidenced", "color": GRY})
    if op["oldest_escalation_wait_days"] is not None:
        w = op["oldest_escalation_wait_days"]
        clock.append({"step": "Human acknowledges escalation", "pct": min(100, round(100.0 * w * 24 / dl)), "label": "%s+ days" % n(round(w)) if w * 24 > dl else "%.0f h" % (w * 24), "color": RED if w * 24 > dl else BLUE})
    elif op["oldest_days"] is not None:
        w = op["oldest_days"]
        clock.append({"step": "Human takes first action", "pct": min(100, round(100.0 * w * 24 / dl)), "label": "%s+ days" % n(round(w)) if w * 24 > dl else "%.0f h" % (w * 24), "color": RED if w * 24 > dl else BLUE})
    else:
        clock.append({"step": "Human takes first action", "pct": 0, "label": "No open cases", "color": BLUE})
    clock.append({"step": "Decide significance", "pct": 100 if cap["reportability"][0] != "ready" else 15, "label": "Not evidenced" if cap["reportability"][0] != "ready" else "Recorded", "color": RED if cap["reportability"][0] != "ready" else BLUE})
    clock.append({"step": "Scope data and systems", "pct": {"ready": 15, "partial": 60, "not ready": 100}.get(cap["scope"][0], 60), "label": {"ready": "Visible", "partial": "Partial", "not ready": "Blind"}[cap["scope"][0]], "color": {"ready": BLUE, "partial": AMB, "not ready": RED}[cap["scope"][0]]})
    if md is not None:
        held = min(md, R["retention"]["ready_days"])
        clock.append({"step": "Preserve evidence for reports", "pct": round(100.0 * (1 - held / R["retention"]["ready_days"])) or 5, "label": "%d days held" % md,
                      "color": BLUE if cap["timeline"][0] == "ready" else (AMB if cap["timeline"][0] == "partial" else RED)})
    else:
        clock.append({"step": "Preserve evidence for reports", "pct": 0, "label": "Not measured", "color": GRY})

    # ---- rating --------------------------------------------------------------------------------------------------
    not_ready = esc_over > 0 or old_share >= R["ownership"]["not_ready_open_old_share_pct"] or cap["reportability"][0] == "not ready"
    gaps_left = any(cap[k][0] in ("partial", "not ready") for k in ("triage", "timeline", "scope", "integrity", "reportability", "ownership"))
    rating = "Not ready" if not_ready else ("Partially ready" if gaps_left else "Ready")

    # ---- KPIs, summary -------------------------------------------------------------------------------------------
    kpis = [{"label": "Time to automated triage", "value": ("~%g min" % med) if med is not None else "Not evidenced", "note": "AI Tier-1 verdict on %d%% of cases examined" % round(cov) if med is not None else "no AI-analyst verdict on the cases examined"}]
    if tr["with_ai_verdict"]:
        kpis.append({"label": "Escalated cases still open", "value": "%d%s" % (op["escalated"], plus if op["escalated"] else ""), "note": ("oldest escalation %s days" % n(round(op["oldest_escalation_wait_days"]))) if op["oldest_escalation_wait_days"] else "none waiting"})
    else:
        kpis.append({"label": "Serious cases still open", "value": n(opn), "note": ("oldest %s days" % n(round(op["oldest_days"]))) if op["oldest_days"] is not None else "none open"})
    kpis.append({"label": "Cases with a reportability decision", "value": "Yes" if rf else ("n/a" if reg_asserted else "0"), "note": "marker found" if rf else ("recorded outside the SIEM (per counsel)" if reg_asserted else "no significance or materiality flag")})
    kpis.append({"label": "Investigable log history", "value": ("%d days" % md) if md is not None and P["retention"]["max_days"] == md else (("%d-%d days" % (md, P["retention"]["max_days"])) if md is not None else "n/a"), "note": "earliest event held in the key tables"})
    sd = (asof - datetime.timedelta(days=R["window_days"]))
    period = "%s - %s" % (sd.strftime("%d %b").lstrip("0"), asof.strftime("%d %b %Y").lstrip("0"))
    head = {"Not ready": "%s could not yet show that it decided and reported on time", "Partially ready": "%s can detect and decide, but evidence or scope gaps remain", "Ready": "%s is positioned to disclose inside the deadlines"}[rating] % a.tenant
    summ = []
    if tr["with_ai_verdict"]:
        summ.append("%s serious cases in %d days: the AI analyst gave a first verdict on %d%% of those examined, in a median of %g minutes, so the first hours of a disclosure clock are covered." % (n(total), R["window_days"], round(cov), med or 0))
    else:
        summ.append("%s cases at risk %s+ were raised in %d days. None of those examined carries an AI-analyst verdict, so how fast anyone looked at them cannot be shown from the case record." % (n(total), n(R["case_risk_floor"]), R["window_days"]))
    summ.append("%s of them (%d%%) are still open%s. No case carries a determination of whether it is reportable to the SEC, an EU authority or a customer%s." % (
        n(opn), round(pct_open), ", %s older than %d days" % (ge + n(op["older_than_flag"]), op["flag_days"]) if op["older_than_flag"] else "",
        "" if not md else "; logs reach back %s days at most, which is the horizon for any scoping or final report" % (md if P["retention"]["max_days"] == md else "%d-%d" % (md, P["retention"]["max_days"]))))
    summ.append("Whether SEC and NIS2 rules apply has %s; contractual notice periods are assumed." % ("not been established" if app.get("sec", "unknown") == "unknown" or app.get("nis2", "unknown") == "unknown" else "been confirmed by counsel"))
    ask = ("confirm with counsel which regimes apply (SEC registrant status, EU establishment or services, customer notification clauses); approve a disclosure-decision procedure in which every escalated "
           "case receives a recorded reportability determination within %d hours; and fund evidence preservation (12-month log retention, no log clearing) so that any report can be substantiated." % dl)

    # ---- backlog -------------------------------------------------------------------------------------------------
    backlog = [{"bucket": "Serious cases (risk %s+) in %d days" % (n(R["case_risk_floor"]), R["window_days"]), "count": n(total), "note": "Volume the disclosure process must keep pace with"},
               {"bucket": "Still open", "count": n(opn), "note": "No closure or determination recorded"},
               {"bucket": "Open with risk above 8,000", "count": n(op["risk_gt_8000"]) if op["risk_gt_8000"] is not None else "n/a", "note": "Highest-risk cases without a decision"},
               {"bucket": "Open longer than %d days" % op["flag_days"], "count": "%s%s" % (n(op["older_than_flag"]), plus), "note": "Any reportable incident here would already be outside every deadline"}]
    if tr["with_ai_verdict"]:
        backlog.append({"bucket": "AI-escalated for containment, still open", "count": "%s%s" % (n(op["escalated"]), plus), "note": "%s without any human status change" % n(op["escalated_no_human"])})
    backlog.append({"bucket": "Open cases involving personal data (DLP, SSN, health)", "count": n(op["personal_data"]), "note": "Possible privacy-law notification trigger"})
    backlog.append({"bucket": "Closed as true positive", "count": n(reg["true_positive"]), "note": "Confirmed incidents recorded in %d days" % R["window_days"]})
    if reg["closed"]:
        backlog.append({"bucket": "Closed without a classification", "count": "~%s" % n(max(0, reg["closed"] - sum(reg["classification"].values()))), "note": "Unclassified closed cases cannot be shown to have been assessed"})

    # ---- findings ------------------------------------------------------------------------------------------------
    F = []
    if own_bad or opn:
        F.append({"severity": "critical" if own_bad else "high",
                  "title": "Escalated incidents sit without a recorded decision" if op["escalated"] else "Open cases sit without a recorded decision",
                  "finding": ("%s%d cases that the AI analyst escalated remain open with no human status change; the oldest has waited %s days." % (ge, op["escalated"], n(round(op["oldest_escalation_wait_days"]))) if op["escalated_no_human"] else
                              "%s cases (%d%%) of the serious cases in the window are still open%s. The case record shows no analyst action on them." % (n(opn), round(pct_open), (", %s of them older than %d days (oldest %s days)" % (ge + n(op["older_than_flag"]), op["flag_days"], n(round(op["oldest_days"])))) if op["older_than_flag"] else "")),
                  "risk": "Regulators and customers measure the time from awareness to determination. If any of these proved significant, the business would already be days or weeks past every deadline and could not show when, or whether, anyone assessed them.",
                  "recommendation": "Assign an incident owner on call, require human acknowledgement of escalated cases within 1 hour and a recorded reportability decision within %d hours, and clear the current backlog this week starting with the %s cases above risk 8,000." % (dl, n(op["risk_gt_8000"] or 0)),
                  "owner": "CISO / SOC", "timeframe": "7 days", "mitre": "-"})
    if cap["reportability"][0] != "ready":
        F.append({"severity": "high", "title": "Case classification is not linked to reporting thresholds",
                  "finding": "Cases are labelled benign, false positive or true positive only. %d%% are unclassified, and no case records whether it is significant (NIS2), material (SEC) or notifiable to a customer or privacy regulator." % round(100.0 * unc / max(total, 1)),
                  "risk": "Without a documented determination the business cannot evidence timely assessment, and reportable incidents can be closed as routine.",
                  "recommendation": "Add mandatory fields to every escalated case: reportable (yes, no, under assessment), regimes, determination time and approver; define significance and materiality criteria with counsel and finance.",
                  "owner": "CISO / Legal", "timeframe": "30 days", "mitre": "-"})
    if cap["timeline"][0] != "ready" or cap["integrity"][0] == "not ready":
        F.append({"severity": "high", "title": "Evidence needed for reports is short-lived" + (" or destroyed" if cap["integrity"][0] == "not ready" else ""),
                  "finding": "%s%s" % (cap["timeline"][1], (" " + cap["integrity"][1]) if cap["integrity"][0] == "not ready" else ""),
                  "risk": "72-hour and final reports require a defensible timeline of what happened and since when; missing or cleared evidence weakens every regulatory, customer and insurance submission.",
                  "recommendation": "Retain security logs for 12 months, stop any log clearing, enable directory-change auditing, and snapshot relevant logs to immutable storage when a case is escalated.",
                  "owner": "Security Operations", "timeframe": "30 days", "mitre": "T1070.001"})
    if any(app.get(k, "unknown") == "unknown" for k in ("sec", "nis2")):
        F.append({"severity": "high", "title": "Which disclosure regimes apply has not been established",
                  "finding": "No record shows whether %s is an SEC registrant, whether NIS2 applies through EU establishment or services, or what notification periods customer agreements require." % a.tenant,
                  "risk": "Without knowing its obligations, the business cannot design deadlines, owners or templates, and may miss a contractual notice even where no regulator is involved.",
                  "recommendation": "Counsel to confirm applicability within 30 days and produce a single notification-obligations register (regulators, customers, insurers) wired into the incident workflow.",
                  "owner": "General Counsel", "timeframe": "30 days", "mitre": "-"})
    if missing:
        F.append({"severity": "medium", "title": "Incident scope cannot be fully measured",
                  "finding": "This tenant's data has no %s, so the extent of an incident in those areas could not be established from the SIEM." % " or ".join(sc[k]["label"] for k in missing),
                  "risk": "Materiality depends on what data and systems were affected; blind spots force over- or under-reporting.",
                  "recommendation": "Ingest the missing sources (endpoint and server security logs, network traffic, message trace) and maintain a crown-jewel register as the scoping baseline.",
                  "owner": "Security Engineering", "timeframe": "60 days", "mitre": "-"})
    F.append({"severity": "medium", "title": "Supplier incidents could trigger the business's own obligations",
              "finding": "No intake for vendor-reported incidents exists in the SIEM, so supplier breaches reach the incident process only if someone raises them by hand.",
              "risk": "A breach at a supplier can become the business's reportable incident; NIS2 also requires supply-chain security measures.",
              "recommendation": "Add incident-notification clauses and contacts for critical vendors, monitor vendor application sign-ins, and log vendor notifications as cases.",
              "owner": "Vendor management / CISO", "timeframe": "60 days", "mitre": "T1199"})
    if op["personal_data"]:
        F.append({"severity": "medium", "title": "Personal-data cases are not routed to privacy counsel",
                  "finding": "%d open cases matched a DLP rule for personal data and have no recorded assessment." % op["personal_data"],
                  "risk": "Breach-notification laws can apply to personal data independent of cyber disclosure rules.",
                  "recommendation": "Route any DLP match on personal data to privacy counsel automatically and record the notification decision.",
                  "owner": "Privacy / Compliance", "timeframe": "14 days", "mitre": "-"})

    # ---- control map, strengths, gaps, detections ----------------------------------------------------------------
    def st(k):
        return {"ready": "met", "partial": "partial", "not ready": "gap", "confirm": "partial"}[cap[k][0]]
    ctrl = [{"control": "Timely materiality determination and 8-K disclosure", "frameworks": "SEC Form 8-K Item 1.05; Regulation S-K Item 106", "status": "gap" if cap["reportability"][0] == "not ready" else st("reportability"), "evidence": "No determination step or record" if cap["reportability"][0] == "not ready" else cap["reportability"][1]},
            {"control": "Significant-incident reporting (24 h / 72 h / 1 month)", "frameworks": "NIS2 Art. 23", "status": st("ownership"), "evidence": "Open cases wait for a human decision" if cap["ownership"][0] == "not ready" else cap["ownership"][1]},
            {"control": "Major-incident classification and notification", "frameworks": "DORA Art. 17-19 (benchmark)", "status": st("reportability"), "evidence": "No major-incident classification field"},
            {"control": "Personal-data breach notification (72 h)", "frameworks": "GDPR Art. 33; US state breach laws", "status": "partial", "evidence": "No register of notification obligations linked to the workflow"},
            {"control": "Evidence retention and integrity", "frameworks": "NIS2 Art. 21; SEC Reg S-K Item 106", "status": {"met": "met", "partial": "partial", "gap": "gap"}[st("timeline")] if cap["integrity"][0] != "not ready" else "gap", "evidence": cap["timeline"][1]},
            {"control": "Supply-chain incident awareness", "frameworks": "NIS2 Art. 21(2)(d)", "status": "partial", "evidence": "No vendor incident intake in the SIEM"}]
    strengths = []
    if tr["with_ai_verdict"] and cap["triage"][0] == "ready":
        strengths.append("Every serious case examined receives an AI-analyst verdict within minutes, which starts the disclosure clock quickly.")
    if md and md >= R["retention"]["partial_days"]:
        strengths.append("Identity and collaboration logs are held for %d days or more, enough to reconstruct recent incidents." % md)
    if present:
        strengths.append("Evidence sources present: %s." % "; ".join(sc[k]["label"] for k in present))
    if total:
        strengths.append("Serious cases are consistently raised and kept as a searchable register (%s in %d days)." % (n(total), R["window_days"]))
    gaps = ["Whether the tenant is an SEC registrant, an EU entity or a financial entity, and what customer notice clauses require, is not in the SIEM; counsel's answers are needed (see applicability inputs).",
            "Board, legal and customer-notification approvers, templates and the materiality criteria are documents outside the SIEM and were not reviewed.",
            "Time to a human decision is measured from the case comment thread; actions taken outside Fluency (email, chat, ticketing) are invisible to it."]
    if not complete:
        gaps.append("Only %s of %s open cases were read; counts of old, escalated and personal-data cases are lower bounds." % (n(op["fetched"]), n(opn)))
    if not tr["with_ai_verdict"]:
        gaps.append("No AI-analyst verdicts were found, so triage speed and AI escalation could not be measured; the human-action clock above uses case age instead.")
    if missing:
        gaps.append("No %s in this tenant's data, so scope could not be measured there." % " or ".join(sc[k]["label"] for k in missing))
    if cr is None:
        gaps.append("Log-clearing events were not checked in this run.")
    gaps.append("Retention is the age of the oldest event held, so a longer retention policy is understated; it does not prove the data is complete.")
    dets = [{"name": "Start the disclosure clock", "logic": "When the AI escalates a case or risk exceeds 8,000, open a reportability task with a 24-hour timer and a named owner."},
            {"name": "Escalation not acknowledged", "logic": "Alert the on-call lead when an escalated case has no human status change within 1 hour, and again at 4 hours."},
            {"name": "Reportability not recorded", "logic": "Alert when an escalated case is closed, or still open after 24 hours, without a reportable yes/no/under-assessment value."},
            {"name": "Personal data in an open case", "logic": "Route any open case with a DLP match on personal data to privacy counsel and start the 72-hour notification timer."},
            {"name": "Security-log clearing", "logic": "Alert on Windows Event 1102 / 104 or loss of a log source on any domain controller or critical server."},
            {"name": "Vendor application sign-in anomaly", "logic": "Alert when a backup or SaaS vendor application signs in from a new network or reads tenant-wide data."}]
    evidence = [{"source": "behavior_summary_search", "reference": "%d-day case register (risk %s+), open cases and a closed sample" % (R["window_days"], n(R["case_risk_floor"]))},
                {"source": "kql_search", "reference": "earliest and latest event per key table (retention)"},
                {"source": "list_data_tables", "reference": "scope: which log sources exist in this tenant"}]
    out = {"tenant": a.tenant, "assessment_date": a.date, "window_days": R["window_days"], "period_label": period, "readiness_rating": rating, "headline": head,
           "summary": summ, "ciso_ask": ask, "kpis": kpis, "regimes": regimes, "regimes_note": "Regulatory summaries are for readiness planning, not legal advice. Applicability must be confirmed by %s's counsel." % a.tenant,
           "clock_test": clock, "clock_note": "Bars show time used against the tightest likely deadline, a %d-hour early warning (NIS2) or customer notice. Detection is measured from case creation to the first AI-Assistant verdict; acknowledgement from the AI escalation, or the case age where none exists, to the first human status change." % dl,
           "capabilities": capabilities, "backlog": backlog, "findings": F, "control_map": ctrl, "strengths": strengths, "coverage_gaps": gaps, "detections_to_add": dets, "evidence": evidence,
           "applicability_notes": app.get("notes", "")}
    json.dump(out, open(a.out, "w"), indent=1)
    print("%s | rating %s | capabilities: %s | %d findings | wrote %s" % (a.tenant, rating, ", ".join("%s=%s" % (k, v[0]) for k, v in cap.items()), len(F), a.out))


if __name__ == "__main__":
    main()
