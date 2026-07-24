# Execution spec — per-connector onboarding skills rollout

**Status:** draft for review
**Date:** 2026-07-23
**Audience:** the coding agent implementing the skills (and the human reviewing this plan)
**Input data:** live `list_connector_templates` snapshot taken 2026-07-23 against the connected
Fluency tenant (54 templates). Parameter names quoted below are from that snapshot — **the
implementing agent must re-fetch the live list at build time and treat this document's copies as
hints, not truth** (same rule the skills themselves must follow at runtime).

---

## 1. Goal

Create one dedicated onboarding skill per available connector template, so that
`customer-onboarding` can route *every* application the platform supports to a skill that:

1. **Guides** the customer through the non-Fluency (vendor-side) portion — credential creation,
   log-forwarding configuration, cloud plumbing — with every step backed by vendor documentation
   (or, as a fallback, another major SIEM vendor's integration guide for the same product).
2. **Offers to perform the actions itself** wherever the agent actually can: CLI-drivable clouds
   (az / aws / gcloud), vendor APIs callable with an operator-supplied credential, local config
   files on reachable hosts — and, always, the Fluency-side `create_connector` install.
3. **Is self-contained** — it ends in `create_connector` itself (the
   `setup-aws-cloudtrail-connector` / `automatic-create-ingext-ms-eventhub` shape), so the router
   never chains it into `add-connector`.
4. **Integrates with `customer-onboarding`** — a catalog row, a hand-off contract, honest
   first-event latency, and credential hygiene.

Templates where no meaningful skill can exist (platform-internal, legacy, or vendor procedure
unknowable) are **not** skipped silently — each has a written disposition in §6 for review.

---

## 2. Naming rule

Per the request: `automatic-<name>` where the agent can genuinely perform the **vendor-side**
work, otherwise a plain descriptive `<name>`.

- **`automatic-<slug>`** — the non-Fluency side is executable by the agent: a cloud CLI the
  operator signs into (az / aws / gcloud), a vendor API reachable with a credential the operator
  supplies, or local file config on this or an SSH-reachable machine. Mirrors the existing
  `automatic-create-ingext-*` precedent (Mode A "cowork runs it" / Mode B "guide a third-party
  admin").
- **`setup-<slug>-connector`** — the vendor side is human-portal-only (an admin clicking a SaaS
  console); the skill guides those clicks with cited documentation, then performs the
  Fluency-side install automatically. Mirrors the `setup-aws-cloudtrail-connector` precedent.

The Fluency-side install being automatable is true for *every* skill and therefore earns no
prefix. Do not name anything `add-*` (collides with `add-connector`) or `create-ingext-*`
(reserved for the Entra app-registration family).

---

## 3. Shared skill blueprint

Every new skill follows this structure. Deviations must be justified in the skill itself.

```
<skill-name>/
├── SKILL.md
├── assets/            ← only if the skill bundles scripts / CF templates / reference configs
│   └── references.md  ← vendor-doc citations backing every vendor-side step (required)
└── evals/
    └── evals.json     ← 3–4 evals, house format (see §3.6)
```

### 3.1 SKILL.md required sections

Follow the voice and structure of `automatic-create-ingext-ms-eventhub/SKILL.md` (the best
current exemplar — self-contained, Mode A/B, cost/credential notes, onboarding hand-off):

1. **Frontmatter** — `name`, `version: 1.0.0`, and a `description` that carries: what it sets up,
   the MODE A / MODE B split (for `automatic-*`) or guide+install split (for `setup-*`), 3–5
   trigger phrases, and **anti-triggers** disambiguating siblings (see §3.7). State explicitly
   that it is self-contained and the router must not chain into `add-connector`.
2. **What this creates** — table covering both vendor side and Fluency side. Flag anything
   billable (per the Event Hubs precedent).
3. **Prerequisites** — vendor-side admin role needed (name the vendor's own role term), toolchain
   checks for `automatic-*` skills, and "Fluency Ingext MCP connected" for the install step.
4. **The offer** — before doing anything, establish who acts (AskUserQuestion if unclear):
   - `automatic-*`: Mode A ("I have the rights — do it for me; I'll complete the sign-in") vs
     Mode B ("another admin runs it in their environment — guide them"). Copy the existing
     skills' framing, including "run the script for the operator — don't hand them instructions"
     and "assume they will authenticate".
   - `setup-*`: the guided portal walkthrough is the only vendor-side path, but the skill still
     asks whether the operator wants the agent to **(a)** drive everything it can (Fluency install,
     any vendor API calls the collected credential enables) or **(b)** just print the runbook.
     Default to (a).
5. **Vendor-side runbook** — the guidance core. Every step cites documentation (§4). For
   `automatic-*` skills: bundled idempotent script(s) with confirmation prompts before creating
   anything, JSON-only stdout, progress on stderr — clone the conventions of
   `setup-ingext-eventhub.sh` / `.ps1`.
6. **Ingext-side install** — always performed by the agent when the MCP is connected:
   - `list_connector_templates` live; never trust this plan's snapshot at runtime.
   - `list_connectors` first; duplicate-instance etiquette per `add-connector` Step 3.
   - Instance-id and displayName derivation per `add-connector` Step 5/6 — **never `"default"`**,
     lowercase, ≤20 chars, `-2`/`-3` suffixes on collision.
   - `inputParameters` includes **every** template parameter (user value → default → `""`), per
     `add-connector` Step 6.
   - Templates with an `output` block (HEC family): capture `url` + `token` after install and
     feed them back into the vendor-side step that needs them.
   - Without the MCP: walk the operator through the Fluency UI instead.
7. **When called from `customer-onboarding`** — the hand-off contract: don't re-collect router
   context; hand back instance id, datalake index, and the expected first-event latency; never
   echo credentials into the summary; state whether zero-rows is expected (⏳ not ❌) and why.
8. **Output** — human-readable + JSON block a calling task can parse (existing precedent).
9. **Verification** — `get_connector`/`list_connectors` state; row-count smoke test via the
   `ingext-kql` skill against the datalake index (confirm live name with `list_data_tables`);
   honest latency before declaring failure.
10. **Failure modes** — table. Include vendor-side ones (wrong region/base URL, missing scope,
    token expiry) and Fluency-side ones (duplicate instance, template rename).
11. **Security notes** — least-privilege scope of the credential, rotation story, "never paste
    the secret into logs/tickets/summaries".
12. **Layout** tree.

### 3.2 Credential hygiene (all skills)

Parameters marked `sensitive: true` in the template (and anything that is obviously a secret:
API tokens, client secrets, connection strings, HEC tokens) are credentials. Collect them, pass
them into `create_connector`, and never echo them back — refer to them descriptively ("the API
token from step 2"). This mirrors `customer-onboarding` Step 4 and the Event Hubs skill.

### 3.3 The "offer to act" boundary — what the agent may claim it can do

Be precise in each skill about which actions the agent performs vs guides:

| Action class | Agent can do it? |
|---|---|
| Fluency-side `create_connector` + verification | **Always** (MCP connected) |
| Azure / AWS / GCP resource + IAM changes | **Yes**, Mode A — operator signs in to the CLI on this machine |
| Vendor REST API calls (e.g. Bitdefender Event Push config) | **Yes**, once the operator supplies the API credential |
| Local config on this machine or SSH-reachable hosts (rsyslog, Fluent Bit) | **Yes**, with the operator naming the host and providing access |
| Clicking a SaaS admin portal (Okta, CrowdStrike, Duo, …) | **No** — guide only. Do not promise browser automation; that is out of scope for v1 |
| A network device's own CLI (FortiGate SSH, PAN-OS) | **Guide only by default.** Optionally, if the operator explicitly offers SSH access to the device, the agent may run the documented commands — the skill may mention this but must not push for device credentials |

### 3.4 Latency + empty-source honesty

Each skill states its first-event latency in both its own Verification section and its catalog
row. API-polling connectors: minutes to ~30 min. Syslog: near-real-time *once the device
forwards*. HEC/push connectors and Event-Hub-like shapes: **nothing arrives until the vendor side
actually pushes** — zero rows is expected, mark ⏳ with the follow-up noted.

### 3.5 Variant pickers

Where one vendor has multiple templates, each sibling skill's description carries anti-triggers
naming the other, and the skill opens by confirming the variant if ambiguous:

- Bitdefender: `BitdefenderST` (agent telemetry via HEC) vs `BitdefenderEP` (Event Push API)
- Proofpoint: `ProofpointTAP` vs `ProofpointEssentials`
- Sophos: `SophosFWLog` (Firewall) vs `SophosUTMSyslog` (UTM) vs `SophosEDR` (Central API)
- Mimecast: `MimecastCG` (API 2.0, current) vs `Mimecast` (legacy 1.0 — no skill, see §6.2)
- Google: `GoogleWorkspace` (service-account) vs `GSuite` (hosted OAuth consent → `add-connector`)
- Microsoft 365: existing fork documented in the catalog (customer-owned app vs hosted consent)

### 3.6 Evals

3–4 evals per skill in the house format (see
`SKILLS/automatic-create-ingext-ms-eventhub/evals/evals.json`): (1) "do it for me" happy path,
(2) third-party-admin / guide-only path, (3) a safety/what-will-you-do-first probe, (4) the
`[Invoked from customer-onboarding]` hand-off. Each with `expected_output` prose plus
`expectations` bullets.

### 3.7 Packaging

After each skill lands, package it into `cowork/<name>.skill` following the existing repo
practice (see `cowork/` for current artifacts) and add a release-notes entry under
`release_notes/`.

---

## 4. Research protocol — the DO-NOT-GUESS rule

This plan classifies every vendor-side procedure with a confidence tier. **The implementing
agent must not write vendor-side steps from model memory alone**, regardless of tier:

1. For every vendor step, locate current official documentation at build time (WebSearch /
   WebFetch) and record the URL in the skill's `assets/references.md`. The outlines in §7 say
   *what to search for*, not what to copy.
2. If official docs are login-gated or missing, fall back to a major SIEM vendor's integration
   guide for the same product (Splunk, Elastic, Microsoft Sentinel data-connector docs), cite it,
   and label it a secondary source.
3. If neither exists, **do not invent the procedure**. Ship the step as an explicit stub —
   *"UNVERIFIED: obtain the current procedure from <vendor> support/documentation"* — and record
   the gap in §9 (open items) via a PR note.
4. Never invent OAuth scope names, permission strings, API paths, or console menu paths. A wrong
   scope silently breaks ingestion; a stub does not.

Confidence tiers used in §7:

- **Confident** — flow well-known and stable; verification at build time is confirmation.
- **Verify** — outline known; exact menu paths / credential model must be confirmed before writing.
- **Unknown** — I do not know the vendor procedure; full research required; stub if unresolved.

---

## 5. Cross-cutting unknowns — resolve before / during build

These block whole families or change skill shape. Resolve with the Fluency team or the live
platform; do not guess any of them.

| ID | Question | Blocks |
|---|---|---|
| **R1** | **Syslog transport:** where exactly does a customer point a syslog device — a per-tenant cloud syslog endpoint (host/port/protocol/TLS?), or is an on-site Fluency Collector required for on-prem sources? How does the agent retrieve the endpoint (platform UI "Connectors" page per `add-connector` Step 7.3 — is there an MCP call)? | The entire syslog family (§7.2) |
| **R2** | Fluency Collector install procedure on Rocky Linux 9 (internal docs needed) | `FluencyCollector`, `LDAP` (§6.3) |
| **R3** | `AWSCloudWatchLogGroupS3`: which S3 delivery mechanism/format does the parser expect (Firehose subscription-filter delivery vs. CloudWatch export tasks; gzip/JSON layout)? | `automatic-aws-cloudwatch-logs` |
| **R4** | `GoogleWorkspace`: the exact OAuth scope list to authorize in domain-wide delegation | `automatic-google-workspace` |
| **R5** | `Falcon`: the exact CrowdStrike API scopes the connector needs (Incidents? Alerts? Hosts?) | `setup-crowdstrike-falcon-connector` |
| **R6** | `WindowsSrvNxLog`: does Fluency publish a reference `nxlog.conf` (route, format, port)? | `setup-windows-nxlog` |
| **R7** | `BitdefenderEP`: does the platform itself call the GravityZone Event Push Service API to configure the push (its inputs — companyID/accessUrl/apiKey — plus HEC outputs suggest yes)? If not, the agent can make the documented `setPushEventSettings` call itself | `automatic-bitdefender-eventpush` |
| **R8** | `Zscaler`: the exact NSS/Cloud-NSS feed output format (field format string, HTTP headers) the Fluency parser expects | `setup-zscaler-nss-connector` |
| **R9** | `ManageEngine`: which ManageEngine product(s) the parser expects (ADAudit Plus? EventLog Analyzer? …) | `setup-manageengine-syslog` |
| **R10** | Datalake table names per new connector — template `index` defaults are strong hints (e.g. `Okta`), but confirm with `list_data_tables` against a live instance during build; catalog rows must carry the confirm-live caveat | All catalog rows |
| **R11** | Does Fluency publish per-connector customer docs that should be the primary citation (ahead of vendor docs)? | Citation policy in §4 |

---

## 6. Dispositions — templates that do NOT get a new skill

### 6.1 Already covered (8) — no new skill; catalog already routes or will route via existing skills

| Template | Covered by | Note |
|---|---|---|
| `AWSCloudTrail` | `setup-aws-cloudtrail-connector` | — |
| `AzureEventHubs` | `automatic-create-ingext-ms-eventhub` | — |
| `MSDefender` | `automatic-create-ingext-defender-app` → `add-connector` | — |
| `AzureAudit` | `automatic-create-ingext-azureaudit-app` → `add-connector`; hosted-consent mode via `add-connector` alone | Dual-mode fork already documented in the catalog |
| `Office365` | Same pair as `AzureAudit` | Dual-mode (`useAdminConsent`) |
| `Office365Audit` | Same app's three fields → `add-connector` | Combined O365 + AzureAudit template |
| `Office365ResourceWatch` | Same app's three fields → `add-connector` | Add a one-line note to the catalog's M365 entry so the router knows it exists |
| `GSuite` (hosted OAuth consent) | `add-connector` consent flow | The service-account variant `GoogleWorkspace` **does** get a skill (§7.4) |

### 6.2 Skip — platform-internal or legacy (7) — for reviewer sign-off

| Template | Reason |
|---|---|
| `S3Syslog` | Description starts "Internal:" — platform plumbing, not a customer onboarding surface |
| `S3Collector` | Same |
| `CloudSyslog` | Internal syslog endpoint that *backs* the syslog family; customers never install it directly |
| `ImportCollector` | System category; internal |
| `FluencyAIAssistant` | Internal service integration |
| `BehaviorSummaryNotification` | Internal export |
| `Mimecast` (legacy API 1.0) | Superseded by `MimecastCG`. No skill. The Mimecast skill (§7.5) notes: customers arriving with 1.0 credentials can still be installed via `add-connector`, but steer new setups to CG/2.0 |

### 6.3 Deferred — blocked on Fluency-internal documentation (2)

| Template | Why deferred | Unblock |
|---|---|---|
| `FluencyCollector` | Deploying the collector appliance (Rocky Linux 9) is genuinely automatable by the agent on a reachable host, but the install procedure is not publicly documented in this repo. **DO NOT GUESS.** | R2. When resolved: `automatic-fluency-collector`, and it becomes the prerequisite hop for LDAP and on-prem aggregation |
| `LDAP` | Requires a local Fluency Collector (`collector` param) — blocked on the above. The AD side (least-privilege read-only bind account) is documentable from Microsoft sources. | Build after `FluencyCollector`; name `setup-ldap-connector` |

---

## 7. New skills — per-family specs (37 skills)

Each row: proposed name, template, required params (snapshot), vendor-side outline **(a search
target, not copy-paste truth — §4 applies)**, confidence, and doc anchors (domains/known pages to
start from; verify every deep link at build time).

### 7.1 Family blueprints

- **SYSLOG** (§7.2): connector install is trivial (no or defaults-only params); the deliverable
  is the device forwarding to the Fluency syslog destination (**R1**). Skill = install connector
  → obtain destination → cited device-side forwarding runbook → verify rows. Guide-only on the
  device side (per §3.3, optional SSH assist).
- **AWS** (§7.3): `automatic-*`, aws CLI Mode A / guide Mode B. Reuse the
  `IngextSaasPodRole.yaml` + `IngextS3SqsNotification.yaml` assets and the
  role-registration flow (`get_account_podrole` → `add_assumed_role` → `test_assumed_role`)
  from `setup-aws-cloudtrail-connector` — that skill already documents the swap in
  "Reusing this for other S3-notification sources".
- **GCP** (§7.4): `automatic-*`, gcloud Mode A for project/API/service-account/key; the
  domain-wide-delegation grant is Admin-console-only (no public API) — an explicit manual step
  even in Mode A.
- **SAAS-API** (§7.5): `setup-*-connector`, portal-guided credential creation + automatic
  Fluency install.
- **HEC** (§7.6): the *connector's output* (HEC `url` + `token`) feeds the vendor side; install
  first, then configure the vendor push. Zero rows expected until the push starts.

### 7.2 Syslog family (12 skills)

Shared precondition: **R1 resolved.** All are guide-only on the device side. Datalake index:
per-template default where present, else confirm live (R10).

| Skill | Template | Vendor-side outline (to verify) | Confidence | Doc anchors |
|---|---|---|---|---|
| `setup-fortigate-syslog` | `FortiGateFWLogV2` | FortiOS: `config log syslogd setting` (server, port, format); or GUI Log & Report settings. Note the existing `fortigate-bandwidth` caveat in the catalog | Confident | docs.fortinet.com (FortiOS admin guide → Log settings) |
| `setup-paloalto-syslog` | `PaloAlto_FWLog` | PAN-OS: Syslog server profile (Device → Server Profiles → Syslog) + attach via Log Forwarding profile / log settings | Confident | docs.paloaltonetworks.com (PAN-OS admin guide → Monitoring → Configure syslog forwarding) |
| `setup-cisco-meraki-syslog` | `CiscoMerakiFWLog` | Meraki Dashboard: Network-wide → Configure → General → Reporting → Syslog servers; choose roles (flows, security events, …) | Confident | documentation.meraki.com ("Syslog Server Overview and Configuration") |
| `setup-cisco-asa-syslog` | `CiscoASAFWLog` | ASA CLI: `logging enable`, `logging host <if> <ip>`, `logging trap <level>`; or ASDM equivalent | Confident | cisco.com ASA configuration guides (syslog chapter) |
| `setup-sonicwall-syslog` | `SonicWallFWLog` | SonicOS: Device → Log → Syslog → add syslog server; syslog format selection matters for the parser | Verify | SonicWall technical documentation portal |
| `setup-checkpoint-syslog` | `CheckPointFWLog` | Check Point Log Exporter (`cp_log_export add …`) on the management/log server, syslog format | Confident | support.checkpoint.com — Log Exporter SK (believed sk122323; verify) |
| `setup-sophos-firewall-syslog` | `SophosFWLog` | Sophos Firewall (XG/XGS): System services → Log settings → add syslog server; select log categories | Verify | docs.sophos.com (Sophos Firewall) |
| `setup-sophos-utm-syslog` | `SophosUTMSyslog` | Sophos UTM 9: Logging & Reporting → Log Settings → Remote Syslog. **Note UTM's end-of-life status in the skill** | Verify | docs.sophos.com (UTM 9) |
| `setup-peplink-syslog` | `PeplinkFWLog` | Peplink/InControl: remote syslog under System settings | Verify | Peplink documentation / forum KBs — if only community sources exist, cite as secondary |
| `automatic-linux-rhel-syslog` | `LinuxRHELSyslog` | rsyslog forwarding (`/etc/rsyslog.d/` with omfwd `@@host:port`); **agent-executable** on this or an SSH-reachable host → earns `automatic-` | Confident | Red Hat RHEL documentation (rsyslog remote logging) |
| `setup-windows-nxlog` | `WindowsSrvNxLog` | NXLog CE on Windows Server reading the event log, forwarding via syslog. **The exact `nxlog.conf` must come from R6 — do not invent the route/format** | Verify (blocked: R6) | docs.nxlog.co + Fluency reference config (R6) |
| `setup-manageengine-syslog` | `ManageEngine` | **Unknown which ManageEngine product the parser expects (R9).** Research first; if unresolved, ship the connector-install portion with a stubbed vendor side | Unknown (R9) | manageengine.com product docs, after R9 |

### 7.3 AWS family (3 skills) — `automatic-*`

Mode A: operator signs in to aws CLI on this machine; agent drives CloudFormation/CLI directly.
Mode B: hand the customer the same templates, per the CloudTrail skill. All three register/reuse
`ingextAssumeRole` where applicable and end in `create_connector`.

| Skill | Template | Required params (snapshot) | Vendor-side outline | Confidence |
|---|---|---|---|---|
| `automatic-aws-cloudwatch-logs` | `AWSCloudWatchLogGroupS3` | `Region`, `SQS_URL`; auth = exactly one of `AWS_Role` / access-key pair | Same S3→SQS plumbing as CloudTrail **plus** getting CloudWatch Logs into S3 — mechanism is **R3**; do not guess the delivery format | Plumbing: Confident. Delivery: blocked on R3 |
| `automatic-aws-eks-fluentbit` | `AWSFluentbitS3` | `Region`, `SQS_URL`; auth as above | Fluent Bit `aws-for-fluent-bit` S3 output from EKS to a bucket, then the shared SQS plumbing. Verify the object format the parser expects against R3's answer for consistency | Verify |
| `automatic-amazon-guardduty` | `AmazonGuardDuty` | `Regions` (list), `IAM_AccessKey`, `IAM_AccessSecret` (**both required — no role option in this template**) | Create a least-privilege IAM user + access key with GuardDuty read-only permissions (`guardduty:Get*`/`List*` — verify exact policy at build); agent can do this via aws CLI in Mode A. Catalog note stays: findings already landing in S3 → prefer the CloudTrail-plumbing route instead | Confident |
| | | | Doc anchors: docs.aws.amazon.com (CloudWatch Logs → S3 delivery per R3; Fluent Bit on EKS; GuardDuty API permissions) | |

### 7.4 GCP (1 skill) — `automatic-google-workspace`

Template `GoogleWorkspace`; required: `adminUserEmail`, `serviceAccountKey` (paste JSON,
sensitive); defaults `datalake=managed`, `index=GSuite`.

- Mode A (gcloud): create/select a GCP project, enable the required APIs (Admin SDK Reports API
  at minimum — verify list), create a service account, issue a JSON key. All agent-executable
  once the operator completes `gcloud auth login`.
- **Manual step even in Mode A:** authorize domain-wide delegation for the service account's
  client ID with the required scopes in admin.google.com (Security → API controls → Domain-wide
  delegation). There is no public API for this grant. The **scope list is R4 — never guess
  scopes.**
- Also collect a super-admin (or suitably privileged) `adminUserEmail` for impersonation.
- Anti-trigger: hosted-consent Google Workspace → `add-connector` (`GSuite` template).
- Doc anchors: developers.google.com/workspace (Reports API, service accounts, domain-wide
  delegation); support.google.com/a (DWD admin help — believed answer 162106; verify).
- Confidence: flow Confident; scopes blocked on R4.

### 7.5 SaaS API-credential family (20 skills) — `setup-*-connector` unless noted

Vendor portal issues the credential (guide-only); agent installs the connector. "Params" are the
snapshot's required inputs (sensitive ones marked •).

| Skill | Template | Params | Vendor-side outline (to verify) | Confidence | Doc anchors |
|---|---|---|---|---|---|
| `setup-okta-connector` | `Okta` | `domain`, `token`• | Okta Admin → Security → API → Tokens → create token. Recommend a dedicated read-only service account as the token owner (token inherits the user's permissions and expires after 30 days of non-use — verify current behavior) | Confident | developer.okta.com (API token docs) |
| `setup-crowdstrike-falcon-connector` | `Falcon` | `baseURL`, `clientID`, `clientSecret`• | Falcon console → Support and resources → API clients and keys → create client with the read scopes from **R5**; base URL per cloud (US-1/US-2/EU-1/Gov). CrowdStrike docs are login-gated — SIEM-vendor fallback permitted per §4 | Verify (R5) | falcon.crowdstrike.com/documentation (login); fallback per §4 |
| `setup-sentinelone-connector` | `SentinelOneAPI` | `URL`, `APIToken`• | S1 console: create a service user / API token (Settings → Users); console base URL is the tenant URL. Verify least-privilege role (Viewer) | Verify | SentinelOne docs (login-gated; community/support KBs; fallback per §4) |
| `setup-duo-connector` | `Duo` | `integrationKey`, `secretKey`•, `apiHostname` | Duo Admin Panel → Applications → Protect an Application → **Admin API** → note ikey/skey/API hostname; grant **Grant read log** permission only | Confident | duo.com/docs/adminapi |
| `setup-trendmicro-visionone-connector` | `TrendMicroVisionOne` | `baseURL`, `apiToken`• | Vision One console → Administration → API Keys; role with the needed read access; regional API domains list | Verify | automation.trendmicro.com |
| `setup-sophos-central-connector` | `SophosEDR` | `clientID`, `clientSecret`• | Sophos Central → Global Settings → API Credentials (service principal). Verify tenant vs partner credential type | Confident | developer.sophos.com |
| `setup-mimecast-connector` | `MimecastCG` | `clientId`, `clientSecret`• | Mimecast Administration → Services → API and Platform Integrations → register an API 2.0 application → client ID/secret | Verify | developer.services.mimecast.com (API 2.0) |
| `setup-proofpoint-tap-connector` | `ProofpointTAP` | `principal`, `secret`• | TAP Dashboard → Settings → Connected Applications → create service principal | Verify | help.proofpoint.com (TAP SIEM API) |
| `setup-proofpoint-essentials-connector` | `ProofpointEssentials` | `baseURL` (regional stack), `principal`, `secret`• | **Credential model unclear to me** (API user vs admin credentials; per-stack base URL, default `us-siem.proofpointessentials.com`) — research before writing | Unknown | help.proofpoint.com (Essentials API) |
| `setup-bitwarden-connector` | `Bitwarden` | `region` (US/EU), `clientId`, `clientSecret`• | Bitwarden Admin Console → Settings → Organization info → View API key (organization client_id/secret) | Confident | bitwarden.com/help (public API / event logs) |
| `setup-box-connector` | `BoxCom` | `ClientID`, `ClientSecret`•, `EnterpriseID` | Box Dev Console → Platform App with **Client Credentials Grant** (App + Enterprise access); admin authorizes the app in Admin Console → Integrations; Enterprise ID from Admin Console → Account & Billing | Confident | developer.box.com (client credentials grant) |
| `setup-cortex-xdr-connector` | `CortexXDR` | `apiUrl`, `apiKeyId`, `apiKey`•, `authMode` (default `advanced`) | Cortex XDR console → Settings → Configurations → Integrations → API Keys → new key (**Advanced** security level to match the default `authMode`), note Key ID and the tenant API URL | Verify | docs-cortex.paloaltonetworks.com |
| `setup-abnormal-security-connector` | `AbnormalSecurity` | `token`• | **Exact token-issuance path unknown to me** (Abnormal portal integration settings) — research before writing | Unknown | Abnormal Security docs/API portal, after research |
| `setup-blackkite-connector` | `BlackKiteAPI` | `clientID`, `clientSecret`•, `companyID?` | **Unknown** — Black Kite API credential issuance is not publicly documented to my knowledge. If research fails, ship with the stub "obtain API credentials from your Black Kite representative" | Unknown | Black Kite support, after research |
| `setup-salesforce-event-monitoring-connector` | `SalesforceEM` | `baseURL`, `clientID`, `clientSecret`• | Salesforce: Connected App with OAuth (params imply client-credentials flow — verify), consumer key/secret; base URL = the org's My Domain. **Hard prerequisite: Event Monitoring license (Shield add-on)** — say so up front | Verify | developer.salesforce.com; help.salesforce.com (Event Monitoring) |
| `setup-workday-connector` | `Workday` | `host`, `tenant`, `clientId`, `clientSecret`, `refreshToken`• | Workday: Register API Client for Integrations (OAuth), ISU-style setup, generate refresh token. Specifics live behind Workday Community login — research; stub what can't be cited | Verify/Unknown | community.workday.com (login-gated); fallback per §4 |
| `setup-zscaler-nss-connector` | `Zscaler` | none required (HEC-output template) | Install connector → capture HEC `url`+`token` → configure a ZIA **Cloud NSS feed** (or NSS server feed) pointing at that URL/token. **Feed output format is R8 — do not guess the format string** | Verify (R8) | help.zscaler.com (Cloud NSS) |
| `setup-coro-connector` | `CoroHEC` | none required (HEC-output template) | **Unknown** — I do not know Coro's SIEM-export mechanism or whether it can target a Splunk-compatible HEC. Research; if nothing found, ship connector-install + stub "configure per Coro support" and flag in §9 | Unknown | Coro docs, after research |
| `setup-bitdefender-securitytelemetry-connector` | `BitdefenderST` | none required (HEC-output template) | GravityZone **Security Telemetry** configured to a Splunk-HEC-compatible target using the connector's `url`+`token`. Verify where it's configured (policy vs API) and product-tier availability | Verify | bitdefender.com GravityZone documentation |
| `automatic-bitdefender-eventpush` | `BitdefenderEP` | `companyID`, `accessUrl`, `apiKey`• | GravityZone → My Account → API keys (Event Push Service API + Companies API rights — verify). Then **R7**: either the platform configures the push itself, or the agent calls the documented Event Push Service API (`setPushEventSettings`) with the connector's HEC `url`+`token` — either way vendor-side is agent-executable → `automatic-` | Verify (R7) | bitdefender.com GravityZone public API docs |

### 7.6 Generic HEC (1 skill)

| Skill | Template | Notes |
|---|---|---|
| `setup-hec-passthrough` | `HecPassthrough` | Generic Splunk-HEC-compatible intake for anything not in the catalog. Install → hand back `url`+`token` → generic guidance ("point any HEC-capable product's Splunk/HEC output here"). Low priority but cheap; gives `customer-onboarding` an honest answer for unlisted products that can speak HEC. Zero-rows-expected semantics per §3.4 |

---

## 8. Router & sibling integration tasks

1. **`customer-onboarding/references/application_catalog.md`** — add every new skill. To keep
   the file navigable at ~40 guided rows, restructure the *Guided applications* section into
   family-grouped tables (Syslog devices / AWS / Google / SaaS API / HEC push) with the same
   columns as today (aliases, route, auth path, prerequisites, hands back, datalake table —
   confirm-live caveat per R10, first-event latency). Keep the existing four detailed blocks
   (CloudTrail, M365, Defender, Event Hubs) as-is.
2. **`customer-onboarding/SKILL.md`** — Step 3's "Something else / named vendor" row changes
   from "route to `add-connector`" to: *consult the catalog first; a Guided row routes to its
   dedicated skill; only an unlisted vendor goes to `add-connector`*. The Step 2
   `AskUserQuestion` stays within 4 options — the menu table (rendered from the catalog) carries
   the full list; the question keeps its current branch shape.
3. **`add-connector/SKILL.md` maintenance** (stale against the live snapshot):
   - The Step 2 alias list and the "No match: Add CrowdStrike → not available" example are
     outdated — `Falcon` (CrowdStrike Falcon) now exists. Refresh aliases from the live list
     (`Falcon`, `CortexXDR`, `Workday`, `BoxCom`, `Okta`, …) and replace the no-match example
     with a genuinely absent vendor.
   - `FortiGateFWLog` (V1) no longer appears in the live list — verify and drop it from aliases
     if confirmed.
   - Add one routing note: "if the user still needs the vendor-side setup done and a dedicated
     `setup-*`/`automatic-*` skill exists for the matched template, offer to route there."
4. **Do not duplicate runbooks** — catalog rows point at skills; the router's no-paraphrase rule
   (Routing rules) applies to all 37 new skills.

---

## 9. Phasing & acceptance

### Phasing

- **Phase 0 — unblock & scaffold.** Resolve **R1** (blocks 12 skills) and R10/R11; land the
  catalog restructure (§8.1) and the shared blueprint checked against one pilot skill
  (`setup-okta-connector` — small parameter surface, Confident vendor docs).
- **Phase 1 — high-demand, high-confidence (12).** Okta, CrowdStrike Falcon (after R5),
  SentinelOne, Duo, GuardDuty, Google Workspace (after R4), FortiGate, PaloAlto, Meraki,
  Cisco ASA, Check Point, SonicWall.
- **Phase 2 — remaining Confident/Verify (17).** Rest of §7.2/§7.3/§7.5 not blocked on research,
  plus `setup-hec-passthrough`, `automatic-bitdefender-eventpush` (after R7).
- **Phase 3 — research-gated + deferred (8).** ProofpointEssentials, Abnormal, BlackKite,
  Workday, Zscaler (R8), Coro, ManageEngine (R9), Windows NXLog (R6); then FluencyCollector +
  LDAP once R2 resolves.

### Per-skill acceptance criteria

- [ ] SKILL.md follows §3.1; description carries triggers, anti-triggers, and the
      self-contained/no-`add-connector` statement.
- [ ] Every vendor-side step cites a source in `assets/references.md`; zero uncited procedural
      claims; unresolved steps are explicit UNVERIFIED stubs, never invented.
- [ ] The skill instructs a **live** `list_connector_templates` fetch at runtime and treats any
      embedded parameter names as a snapshot.
- [ ] Sensitive values never echoed; instance-id rules honored (never `"default"`).
- [ ] `evals/evals.json` with 3–4 house-format evals including the onboarding hand-off eval.
- [ ] Catalog row added; latency and zero-rows semantics stated honestly.
- [ ] Packaged into `cowork/` + release note.

### Repo-wide acceptance

- [ ] All 54 templates accounted for: 37 new skills, 8 already-covered, 7 skip, 2 deferred —
      each non-skill disposition reviewable in §6.
- [ ] `add-connector` refreshed per §8.3.
- [ ] Open research items (§5) either resolved or carried forward with owners in the PR
      description.
