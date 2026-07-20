---
name: customer-onboarding
version: 1.1.0
description: >-
  Guide a new Fluency / Ingext customer through getting their data in — present a menu of supported
  applications, route each choice to the right setup skill, verify events are actually landing, and
  loop back for the next source. This is the front door for onboarding: use it when the user does
  NOT already know which application or connector they want, or wants to bring in several sources in
  one session. Triggers: "onboard a new customer", "we're new to Ingext, where do I start", "help us
  get our logs into Fluency", "what can we connect?", "walk me through data import", "set up our
  data sources". Do NOT use this skill when the user has already named a single application and
  wants it set up — route directly to the dedicated skill instead: AWS CloudTrail is
  setup-aws-cloudtrail-connector; the Entra audit app is create-ingext-audit-app; the Defender app
  is automatic-create-ingext-defender-app (preferred — it performs the setup; the older guide-only
  create-ingext-defender-app is the fallback); any other single named connector is add-connector.
  This skill installs nothing itself — it is a router and a verifier.
---

# Customer Onboarding — Fluency / Ingext data import

The front door for a customer bringing data into the platform. This skill owns the **map** from
"what does the customer have?" to "which skill sets it up?", carries credentials across the
hand-off between skills, and confirms events actually arrived.

> **You install nothing here.** Every setup procedure already lives in a dedicated skill. Your job
> is to pick the right one, hand off cleanly, verify the result, and come back for the next source.
> Never paraphrase or inline a sibling skill's runbook — see [Routing rules](#routing-rules).

The application map lives in **`references/application_catalog.md`**. Read it before presenting the
menu. It is the single place to edit when a new application skill lands.

## The flow

```
list_connectors ─→ present menu ─→ route to skill(s) ─→ carry credentials ─→ verify ingestion ─┐
                        ↑                                                                       │
                        └───────────────────── loop for next application ────────────────────┘
```

---

## Step 1 — Ground the menu in reality

Call `list_connectors` before showing anything. Use the result to mark applications that are
**already installed**, so you don't offer a redundant setup. If the call fails, say so and continue
with an unmarked menu — a broken lookup shouldn't block onboarding.

Open with what you found, briefly: what's already connected, and what this session will do.

---

## Step 2 — Present the menu

Read `references/application_catalog.md`, then do **both** of these, in order:

1. **Render the catalog as a table in your reply** — every guided application, what it needs from
   the customer, and anything already installed marked as such. This is the part the customer
   actually reads, so it carries the full picture.
2. **Then call `AskUserQuestion`** for the pick.

`AskUserQuestion` allows a maximum of **4 options**, so the question carries the branches, not the
full list:

| Option | Meaning |
|---|---|
| AWS CloudTrail | Real-time import from an existing S3 bucket |
| Microsoft 365 / Entra audit logs | Office 365 + Azure AD audit events and resources |
| Microsoft Defender | Security incidents and alerts via Graph |
| Something else | You'll list what the platform supports and install it |

The auto-added **"Other"** free-text absorbs a customer who types a vendor name directly ("we run
CrowdStrike") — route that through the **Something else** branch.

If the customer doesn't know what they want, ask what security and cloud tools they actually run —
EDR, firewall, identity provider, cloud accounts — then map their answers onto the catalog and
re-present a narrowed menu.

---

## Step 3 — Route

| Choice | Route |
|---|---|
| AWS CloudTrail | **`setup-aws-cloudtrail-connector`** — self-contained; it ends in `create_connector` itself, so no follow-on |
| Microsoft 365 / Entra audit | **`create-ingext-audit-app`** → then **`add-connector`** (see [hand-off](#step-4--the-credential-hand-off)) |
| Microsoft Defender | **`automatic-create-ingext-defender-app`** (preferred — performs the setup) → then **`add-connector`**; fall back to the guide-only `create-ingext-defender-app` only if the automatic variant isn't installed |
| Something else / named vendor | **`add-connector`** — its Step 1 calls `list_connector_templates` and matches live |
| Not sure | Ask what tools they run, map onto the catalog, return to Step 2 |

Before routing to a Microsoft 365 choice, resolve the **customer-owned app vs. hosted OAuth
consent** fork — the catalog documents both paths and they are not interchangeable. Ask if unclear.

### Routing rules

**Invoke the sibling skill. Do not paraphrase its runbook.** Never inline CloudFormation parameter
tables, Entra permission lists, or connector parameter schemas into your own reply. Those live in
the sibling skill and in the live API; a copy here would drift silently and hand a customer stale
values. Your job ends at the hand-off and resumes at verification.

**If a routed-to skill isn't installed**, say so plainly, name the missing skill, point the user at
`github.com/SecurityDo/ingext_skills`, and stop that branch. Do **not** improvise the procedure from
memory — these runbooks involve IAM trust relationships and admin-consent grants where a wrong guess
is expensive.

---

## Step 4 — The credential hand-off

`create-ingext-audit-app` and the Defender app skill (`automatic-create-ingext-defender-app`, or
its guide-only fallback `create-ingext-defender-app`) each end by producing three values:

```
tenantId, clientId, clientSecret
```

They exist for the downstream install stage — **this step is that stage.** Capture all three on
return and invoke `add-connector` with them already in hand, so it doesn't re-prompt the customer
for values they just generated.

> **`clientSecret` is a credential.** Pass it into the connector install; never echo it back in a
> summary, a checklist, or a progress update. If you need to refer to it, say "the client secret
> from the app registration".

If the app-registration skill fails or the customer abandons it partway, do **not** proceed to
`add-connector` — there's nothing to install with. Mark the application failed in the checklist and
return to the menu.

---

## Step 5 — Verify ingestion

The onboarding of an application is **not done when the connector installs** — it's done when
events land. Work through these in order:

1. **`list_connectors`** — confirm the new instance exists and report its state.

2. **Wait out the honest latency before calling anything broken.** The catalog records a
   first-event latency per application. Roughly: CloudTrail batches to S3 about every ~5 minutes;
   Office 365 Management API events can take ~30–60 minutes to start; OAuth-consent connectors send
   nothing at all until the admin completes the consent email. Tell the customer what to expect
   rather than declaring failure early.

3. **Confirm events landed** — use the **`ingext-kql`** skill to count rows in that application's
   datalake table over the last hour. The catalog holds the table per application; confirm the live
   name with `list_data_tables` rather than trusting the catalog blindly. A plain row count is
   enough — this is a smoke test, not analysis.

4. **If nothing landed after the expected latency**, hand back to the sibling skill's own **Failure
   modes** table (`setup-aws-cloudtrail-connector` has a detailed one) rather than debugging from
   scratch. Report what you observed — connector state, row count, elapsed time — and let the
   specific skill's diagnostics take it.

For a broader "is the whole site healthy, is anything erroring or backing up" question, defer to
**`ingext-health-monitor`**. That is not this skill's job.

---

## Step 6 — Loop

Track every application touched this session:

| State | Meaning |
|---|---|
| ✅ Done | Connector installed **and** events confirmed in the datalake |
| ⏳ Pending | Installed, but still inside the expected first-event window |
| ❌ Failed | Setup didn't complete, or nothing arrived after the expected latency |

After each application, return to **Step 2** with completed ones marked, and ask whether they want
to add another. When the customer is finished, print the final checklist.

**Report ⏳ and ❌ honestly.** A source that installed but never delivered an event is not onboarded,
and silently dropping it from the summary is the one failure mode that actually costs the customer
data. Say what's unverified and what to check later.

---

## Layout

```
customer-onboarding/
├── SKILL.md
├── references/
│   └── application_catalog.md   ← app → route → prerequisites → table → latency
└── evals/
    └── evals.json               ← trigger phrases for skill selection
```
