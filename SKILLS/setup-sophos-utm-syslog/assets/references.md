# References — Sophos UTM 9 syslog vendor-side steps, end-of-life status & platform transport

Verified 2026-07-28. Device documentation checked against the **Sophos UTM 9.721** administration
guide (the newest version published on docs.sophos.com; the 9.717 and 9.708 pages carry identical
wording).

## End of life — verify this first, state it to the customer

| Claim in SKILL.md | Source |
|---|---|
| **All Sophos UTM products reach end of life on 30 June 2026**, across SG hardware, third-party hardware, virtual and AWS deployments | [Sophos Community — "Sophos UTM/SG End-of-life: Frequently Asked Questions" (Lifecycle and Migration, Sophos-authored)](https://community.sophos.com/utm-firewall/lifecycle-and-migration/f/recommended-reads/139151/sophos-utm-sg-end-of-life-frequently-asked-questions); [Sophos — "Sophos UTM EOL: 3 Actions to Take Before June 30, 2026" (sophos.com partner news)](https://www.sophos.com/en-us/partner-news/sophos-utm-eol-3-actions-to-take-before-june-30-2026) — "Sophos UTM reaches end of life on June 30, 2026." |
| After EoL: **no further updates to the UTM operating system and software**, and **no patches or fixes** for newly discovered vulnerabilities | Community EoL FAQ (above) — "there will be no further updates to the Sophos UTM operating system and software. In the event that vulnerabilities are discovered…Sophos will not provide patches or fixes." |
| Protection content stops: **anti-virus signature and engine updates (Sophos and Avira), IPS signature and engine updates, anti-spam (SASI) updates, URL classification lookups (SXL)** | Community EoL FAQ (above) |
| **No support beyond 31 December 2026**, regardless of license expiry date | Community EoL FAQ (above); [Sophos Community blog — "Sophos UTM EOL: 3 Actions to Take Before June 30, 2026"](https://community.sophos.com/utm-firewall/lifecycle-and-migration/b/blog/posts/sophos-utm-eol-3-actions-to-take-before-june-30-2026) — "no support can be offered beyond December 31, 2026" |
| License/renewal ordering deadlines have already passed (last renewal orders for all subscription terms: 31 December 2025; 1-year renewals: 30 June 2025) | Community EoL FAQ (above) |
| The vendor's path forward is **Sophos Firewall (SFOS) / XGS Series**, with migration incentives | Community EoL FAQ + partner-news page (above) |

## Sophos UTM 9 device side

| Claim in SKILL.md | Source |
|---|---|
| Remote syslog lives on the **Logging & Reporting → Log Settings → Remote Syslog Server** tab; enable via the **toggle switch** (turns amber and makes **Remote Syslog Settings** editable, green after Apply); **Plus** icon in the **Syslog Servers** box opens the **Add Syslog Server** dialog | [Remote Syslog Server — Sophos UTM 9.721 administration guide](https://docs.sophos.com/nsg/sophos-utm/utm/9.721/help/en-us/Content/utm/utmAdminGuide/LoggingSettingsRemoteSyslogServer.htm) |
| The Add Syslog Server dialog has exactly three settings — **Name**, **Server** (a network definition), **Port** (a service definition) — **and no TLS/encryption option** | Same page (the field list is complete on that page; the absence of any encryption setting is the basis for the skill's "no TLS on this device" statement) |
| **Caution:** do not use one of the UTM's own interfaces as the remote syslog host — it creates a logging loop | Same page |
| **Remote Syslog Buffer** = number of log lines kept in the buffer, **default 1000** | Same page |
| **Remote Syslog Log Selection** is editable only when remote syslog is enabled; "select the checkboxes of the logs that should be delivered to the syslog server"; **Select All** selects everything; then **Apply** | Same page |
| The remote host "must run a logging daemon that is compatible to the syslog protocol" | Same page |
| Network definition types: **Host** (a single IP address) and **DNS host** ("a DNS hostname, dynamically resolved by the system to produce an IP address… re-resolved periodically according to the TTL"), created at **Definitions & Users → Network Definitions** | [Network Definitions — Sophos UTM 9.721](https://docs.sophos.com/nsg/sophos-utm/utm/9.721/help/en-us/Content/utm/utmAdminGuide/NetworkDefinitionsNetworkDefinitions.htm) |
| Service definitions are created at **Definitions & Users → Service Definitions → New Service Definition** with **Type of definition** TCP or UDP, plus **Destination port** and **Source port** (single port or `from:to` range) | [Service Definitions — Sophos UTM 9.721](https://docs.sophos.com/nsg/sophos-utm/utm/9.721/help/en-us/Content/utm/utmAdminGuide/ServiceDefinitions.htm) |
| Device-side ground truth: **Logging & Reporting → View Log Files → Today's Log Files**, with **Live Log** (real-time pop-up, **Autoscroll**, filter box), **View**, and **Clear**; files larger than **512 MB** cannot be viewed | [Today's Log Files — Sophos UTM 9.721](https://docs.sophos.com/nsg/sophos-utm/utm/9.721/help/en-us/Content/utm/utmAdminGuide/LoggingViewLogFilesTodays.htm); [View Log Files — Sophos UTM 9.721](https://docs.sophos.com/nsg/sophos-utm/utm/9.721/help/en-us/Content/utm/utmAdminGuide/LoggingViewLogFiles.htm) |

### Secondary sources (labelled as such in the skill)

| Claim | Source | Why secondary |
|---|---|---|
| The practical configuration is a **UDP** service definition (type UDP, destination port 514, source port `1:65535`) or the appliance's built-in **Syslog (Remote Logging Protocol)** service, followed by **Select All** in the log selection | [ActZero — Configure Sophos UTM](https://docs.actzero.ai/log-forwarding-sophos-utm/); [ManageEngine Firewall Analyzer — Configure Sophos UTM firewalls](https://www.manageengine.com/products/firewall/help/configure-sophos-utm-firewalls.html); [WebSpy — How to configure Sophos logging and reporting](https://www.webspy.com/getting-started/sophos/) (drags the built-in "Syslog (Remote Logging Protocol)" service onto the Port field, then ticks **Web Filtering**) | Third-party SIEM/reporting vendors, not Sophos |
| Subsystem names that appear in the Remote Syslog Log Selection (packet filter/firewall, web filtering, IPS, authentication) | [Elastic — Sophos integration](https://www.elastic.co/docs/reference/integrations/sophos) ("check the log types to forward (e.g., Firewall, Packet Filter)"); WebSpy (above, "Web Filtering") | Third-party; **not** a complete or exact label list — see UNVERIFIED below |
| The log selection is **global, not per-server** — "If you specify multiple destination syslog servers, they will all receive the same syslog information" | [Fastvue — Filtering and forwarding Sophos UTM syslog data with syslog-ng](https://www.fastvue.co/sophos/blog/syslog-filtering-sophos-utm-syslog-ng-linux/) | Third-party blog (2017); consistent with the single global selection area shown in Sophos's own page, but not stated by Sophos |
| TCP for remote syslog is not established: a user reporting TCP 5140 attempts ended up solving the problem with a RAW/UDP input instead | [Sophos Community — "Need help with Remote Syslog Settings"](https://community.sophos.com/utm-firewall/f/management-networking-logging-and-reporting/101788/need-help-with-remote-syslog-settings) | Community thread, inconclusive — the skill therefore drives UDP and warns against experimenting |

## Explicit UNVERIFIED items

1. **The exact checkbox labels under "Remote Syslog Log Selection".** Sophos's administration
   guide documents the mechanism and the **Select All** option but publishes no list of subsystem
   labels, and no authoritative enumeration was found elsewhere. The skill says so plainly, tells
   the operator to read the labels off the screen (they mirror the subsystems under *View Log
   Files*), and offers only secondary-source hints.
2. **TCP support for UTM 9 remote syslog.** The Port field takes any service definition and UTM
   service definitions can be TCP, but Sophos documents no TCP behaviour for remote syslog and
   community reports are inconclusive. The skill drives **UDP** and says not to experiment on a
   production appliance.
3. **The datalake table name** — the `SophosUTMSyslog` template carries no index parameter, so the
   platform assigns it. Confirm live with `list_data_tables`; no live MCP session was available at
   build time.

## Fluency platform side (not vendor documentation)

The syslog transport mechanism is platform guidance from the Fluency team (2026-07-28), recorded
in `plans/connector-skills-rollout.md` (R1 resolution):

- `syslog_get_config` — read the site's syslog configuration.
- `syslog_register_config` — create it; **once per site, ever** — never when one exists.
- `syslog_update_config` — enable an additional listener (e.g. `syslog_udp`) on an existing
  configuration, leaving other listeners untouched.
- TLS-capable sources (**not** Sophos UTM 9) use the `syslog_tls` listener with the platform CA
  certificate: https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt
- Exact parameter shapes come from the live MCP tool schemas at runtime.
