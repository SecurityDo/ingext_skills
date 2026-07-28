# References — Check Point Log Exporter vendor-side steps & platform transport

Verified 2026-07-28.

Primary sources are Check Point's own documentation portal (`sc1.checkpoint.com` — the Log Exporter
Administration Guide, the Logging and Monitoring Administration Guides, and the CLI reference
guides) and Check Point's support centre (`support.checkpoint.com`). Anything else is labelled
**secondary**.

## Check Point side

| Claim in SKILL.md | Source |
|---|---|
| Log Exporter is "an easy and secure method for exporting Check Point logs over the syslog protocol"; it is a **multi-threaded daemon on a Management Server / Log Server** (and SmartEvent server) that extracts, transforms and exports logs; "It is recommended to deploy the Log Exporter on every server that contains logs to be exported" | [Log Exporter Administration Guide — Introduction](https://sc1.checkpoint.com/documents/Log_Exporter/EN/Content/Topics/Introduction.htm); [R82 Logging and Monitoring Admin Guide — Log Exporter](https://sc1.checkpoint.com/documents/R82/WebAdminGuides/EN/CP_R82_LoggingAndMonitoring_AdminGuide/Content/Topics-LMG/Log-Exporter.htm) |
| The canonical SK for Log Exporter is **sk122323 — "Log Exporter - Check Point Log Export"** | [sk122323](https://support.checkpoint.com/results/sk/sk122323) — the SK page body is JavaScript-rendered and was not retrievable at build time; the title was confirmed from the support-centre listing. Every procedural claim below is cited to the Administration Guides instead, which carry the same content |
| Transports are **syslog over TCP or UDP**; formats are **Syslog (default), Splunk, CEF, LEEF, Generic, JSON, LogRhythm, RSA**; TLS is **"mutual authentication based on TLS 1.2"**; **Security logs, Audit logs, or both** can be exported, with filtering by field value | [Log Exporter Admin Guide — Introduction](https://sc1.checkpoint.com/documents/Log_Exporter/EN/Content/Topics/Introduction.htm); [R82 Logging and Monitoring — Log Exporter](https://sc1.checkpoint.com/documents/R82/WebAdminGuides/EN/CP_R82_LoggingAndMonitoring_AdminGuide/Content/Topics-LMG/Log-Exporter.htm) |
| Log Exporter "stops exporting when disconnected from the 3rd party server and remembers the last position exported", resuming on reconnect; it handles current and archived logs and throttles offline export to prioritise online logs | [R81 Logging and Monitoring — How Log Exporter Works](https://sc1.checkpoint.com/documents/R81/WebAdminGuides/EN/CP_R81_LoggingAndMonitoring_AdminGuide/Topics-LMG/Log-Exporter-How-it-works.htm) |
| CLI configuration is done **in Expert mode on the Management Server or Log Server**; add syntax: `cp_log_export add name <Name> [domain-server {mds \| all}] target-server <HostName or IP> target-port <Port> protocol {tcp \| udp} format {cef \| generic \| json \| leef \| logrhythm \| rsa \| splunk \| syslog} [--apply-now]`; without `--apply-now`, apply with `cp_log_export restart` | [R81 Logging and Monitoring — Log Exporter Basic Configuration in CLI](https://sc1.checkpoint.com/documents/R81/WebAdminGuides/EN/CP_R81_LoggingAndMonitoring_AdminGuide/Topics-LMG/Log-Exporter-Configuration-in-CLI-Basic.htm) |
| Name rules: "Allowed characters are: Latin letters, digits (0-9), minus (-), underscore (_), and period (.). Must start with a letter. Minimum length is two characters." | Same page |
| Full subcommand set — `add`, `delete name <Name>`, `reexport`, `restart name <Name>`, `set name <Name> [args]`, `show [args]`, `start name <Name>`, `status [args]`, `stop name <Name>`; `--apply-now` "Applies immediately any change that was done with the add, set, delete, or reexport command"; `format` default **syslog**; `read-mode` is `raw` (no unification) or `semi-unified` (default); `encrypted {true\|false}`, `ca-cert` (*.pem), `client-cert` (*.p12), `client-secret` (challenge phrase); `export-attachment-ids`; `domain-server {mds\|all}` | [R82 Security Management Admin Guide — cp_log_export](https://sc1.checkpoint.com/documents/R82/WebAdminGuides/EN/CP_R82_SecurityManagement_AdminGuide/Content/Topics-SECMG/CLI/cp_log_export.htm); [R81 CLI Reference Guide — cp_log_export](https://sc1.checkpoint.com/documents/R81/WebAdminGuides/EN/CP_R81_CLI_ReferenceGuide/Topics-CLIG/MDSG/cp_log_export.htm) |
| TLS export requires **mutual authentication only**; needs a CA certificate in PEM (the CA that signed both the client and the target-server certificates) and a client certificate in P12 on the Management/Log Server; both go in `$EXPORTERDIR/targets/<Name>/certs/` and need read permission (`chmod -v +r`); the documented command adds `encrypted true ca-cert … client-cert … client-secret …`; client material is generated with OpenSSL (key → CSR → certificate signed by the CA → `pkcs12` export), and the export challenge phrase is what `client-secret` expects | [Log Exporter Admin Guide — TLS Configuration](https://sc1.checkpoint.com/documents/Log_Exporter/EN/Content/Topics/TLS-Configuration.htm); also [R81 Logging and Monitoring — Log Exporter TLS Configuration](https://sc1.checkpoint.com/documents/R81/WebAdminGuides/EN/CP_R81_LoggingAndMonitoring_AdminGuide/Topics-LMG/Log-Exporter-TLS-configuration.htm) |
| SmartConsole path: **Objects > More object types > Server > Log Exporter/SIEM**; General page has **Export Configuration** (Enabled), **Target Server**, **Target Port**, **Protocol** ("UDP (default) or TCP"); Data Manipulation page has **Format** ("Syslog (default), Common Event Format (CEF), Log Event Extended Format (LEEF), Generic, Splunk, LogRhythm, Json"), the connection-log aggregation mode (Semi unified / First and Last / Last only) and **Aggregate log updates before export**; attach it under the Management/Log/SmartEvent server object → **Logs > Export** → [+]; then **Install database** (menu → Install database → select all objects → Install), repeated after a server upgrade | [Log Exporter Admin Guide — Deployment of Log Exporter in SmartConsole](https://sc1.checkpoint.com/documents/Log_Exporter/EN/Content/Topics/Deployment-SmartConsole.htm); [R81 Logging and Monitoring — Configuring Log Exporter in SmartConsole](https://sc1.checkpoint.com/documents/R81/WebAdminGuides/EN/CP_R81_LoggingAndMonitoring_AdminGuide/Topics-LMG/Log-Exporter-Configuration-in-SmartConsole.htm) |
| Per-target files live under `$EXPORTERDIR/targets/<Name>/` (`targetConfiguration.xml`, `conf/FilterConfiguration.xml`); source logs are read from `$FWDIR/log/` (e.g. `fw.log`); on Multi-Domain, `$EXPORTERDIR` "exists in each Domain, and its value is changed automatically when you switch between context of Domains" via `mdsenv`; **"you must restart the Log Exporter instance for the new settings to take effect"** (`cp_log_export restart`) | [Log Exporter Admin Guide — Advanced Configuration](https://sc1.checkpoint.com/documents/Log_Exporter/EN/Content/Topics/Advanced-Configuration.htm) |
| For a syslog receiver, Check Point's own guidance treats the `syslog` format as standard syslog-protocol framing — its syslog-ng example is `source s_network { network(transport("tcp") port(514) flags(syslog-protocol) ); };` | [R81 Logging and Monitoring — Log Exporter Appendix](https://sc1.checkpoint.com/documents/R81/WebAdminGuides/EN/CP_R81_LoggingAndMonitoring_AdminGuide/Topics-LMG/Log-Exporter-Appendix.htm) |
| A gateway's logging destination is set on the gateway object's **Logs** page: **"Send gateway logs to server"** (the Management Server), a selected dedicated Log Server, or **"Save logs locally, on this server"**; the change requires publishing and then **installing policy on the Security Gateway** | [R80.40 Logging and Monitoring — Configuring the Security Gateways for Logging](https://sc1.checkpoint.com/documents/R80.40/WebAdminGuides/EN/CP_R80.40_LoggingAndMonitoring_AdminGuide/Topics-LMG/Configuring-security-gateways-for-logging.htm) — the R81/R82 equivalents were not reachable at build time; the page is version-stable in wording |
| Device-side ground truth is the **SmartConsole Logs & Monitor → Logs view** (queries, time period, query search bar, statistics and results panes) | [R82 Logging and Monitoring — Using the Logs View](https://sc1.checkpoint.com/documents/R82/WebAdminGuides/EN/CP_R82_LoggingAndMonitoring_AdminGuide/Content/Topics-LMG/Using-log-view.htm); [R81 — Searching the Logs](https://sc1.checkpoint.com/documents/R81/WebAdminGuides/EN/CP_R81_LoggingAndMonitoring_AdminGuide/Topics-LMG/Searching-Logs.htm) |
| `cp_log_export reexport name <Name> --apply-now` resets the exporter's log position and re-exports from it | [R82 Security Management Admin Guide — cp_log_export](https://sc1.checkpoint.com/documents/R82/WebAdminGuides/EN/CP_R82_SecurityManagement_AdminGuide/Content/Topics-SECMG/CLI/cp_log_export.htm) |
| Troubleshooting for Log Exporter is scoped to `cp_log_export show`, `cp_log_export restart name <Name>` and the XML configuration files under `$EXPORTERDIR/conf/` (R81.20+) | [Log Exporter Admin Guide — Troubleshooting](https://sc1.checkpoint.com/documents/Log_Exporter/EN/Content/Topics/Troubleshooting.htm) |

## Unverified / gaps (do not guess these)

- **Which format Fluency's `CheckPointFWLog` parser expects — UNVERIFIED.** Fluency does not publish
  it and no source was found at build time. The skill keeps Log Exporter's default **`syslog`** and
  tells the operator to ask Fluency support before switching, rather than cycling through
  cef/leef/json. Do not assert a format the platform has not confirmed.
- **Whether the Fluency syslog TLS listener works with Log Exporter — RESOLVED 2026-07-28: it does
  not.** Log Exporter
  supports encrypted export with **mutual authentication only**: it always presents a client
  certificate, and Check Point documents the CA as the one that signed both the client and the
  server certificates. The platform CA file
  (https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt) was inspected at build time
  (`openssl storeutl -noout -text`, 2026-07-28) and is a **PEM bundle of five public roots — Amazon
  Root CA 1, 2, 3, 4 and Starfield Services Root Certificate Authority G2** — so the endpoint uses a
  publicly-trusted server certificate and that file serves as `ca-cert`. The remaining question —
  whether the listener requests a client certificate and would accept a customer-generated one —
  was **answered by the Fluency team on 2026-07-28: no client certificate is accepted** (plan §5,
  R13). Since Log Exporter's encrypted export is mutual-authentication-only and Check Point
  provides no one-way TLS mode, **TLS cannot be used for this connector at all**. The skill states
  **TCP** as the correct transport rather than a fallback, keeps its TLS section explicitly gated
  off for the day that changes, and points customers who require encryption in transit at a
  private network path. Re-check the CA bundle before relying on it — it can change.
- **Exporting directly from a Security Gateway that stores logs locally — UNVERIFIED.** The current
  Log Exporter and Logging & Monitoring guides scope Log Exporter to Management Servers / Log
  Servers. The skill says so and offers the supported alternative (point the gateway at the
  management/log server) rather than inventing a gateway-side procedure.
- **Log Exporter's own diagnostic log file location — NOT PUBLISHED in the pages verified.** The
  Troubleshooting topic covers `cp_log_export show`, restarts and the XML files; it does not name a
  log path, so the skill does not name one. Check Point's CheckMates community carries community
  answers on this (secondary), but the post could not be fetched at build time and nothing in the
  skill depends on it.
- **Whether a policy install is needed for the export itself — NO.** The documented apply steps are
  `--apply-now` / `cp_log_export restart` for the CLI path and **Install database** for the
  SmartConsole path. **Install Policy** appears only for changing a *gateway's* logging destination.
  The skill keeps these separate deliberately.

## Fluency platform side (not vendor documentation)

The syslog transport mechanism is platform guidance from the Fluency team (2026-07-28), recorded in
`plans/connector-skills-rollout.md` (R1 resolution):

- `syslog_get_config` — read the site's syslog configuration.
- `syslog_register_config` — create it; **once per site, ever** — never when one exists.
- `syslog_update_config` — enable an additional listener (e.g. `syslog_tcp`, `syslog_udp`,
  `syslog_tls`) on an existing configuration, leaving other listeners untouched.
- TLS-capable sources use the `syslog_tls` listener with the platform CA certificate:
  https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt
- Exact parameter shapes come from the live MCP tool schemas at runtime.
- The `CheckPointFWLog` template ("Check Point Firewall Syslog", category `onpremise`,
  resourceGroups `["Checkpoint"]`, **no parameters**) is a 2026-07-23 snapshot of
  `list_connector_templates` — the skill re-fetches live. The datalake table is not defined by the
  template; confirm with `list_data_tables`.
