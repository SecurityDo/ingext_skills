# References — FortiGate syslog vendor-side steps & platform transport

Verified 2026-07-28.

Primary sources are Fortinet's own Document Library (docs.fortinet.com). Where the Document
Library page would not render for automated retrieval, the equivalent claim was taken from
Fortinet's official community knowledge base (community.fortinet.com) — Fortinet-authored, but
labelled **secondary** below per the research protocol (`plans/connector-skills-rollout.md` §4).

## FortiGate / FortiOS device side

| Claim in SKILL.md | Source |
|---|---|
| `config log syslogd setting` exists with `status`, `server`, `mode`, `port`, `facility`, `source-ip`, `format`, `enc-algorithm`, `ssl-min-proto-version`, `certificate`; `server` max 63 chars; `port` 0–65535; `certificate` is "Certificate used to communicate with Syslog server" | [FortiOS CLI Reference — `log syslogd setting` (6.2.1)](https://docs.fortinet.com/document/fortigate/6.2.1/cli-reference/352620/log-syslogd-setting) |
| `mode` accepts `udp` / `legacy-reliable` / `reliable`; `enc-algorithm` accepts `high-medium` / `high` / `low` / `disable` and is described as "Enable/disable reliable syslogging with **TLS encryption**"; `ssl-min-proto-version` accepts `default` / `SSLv3` / `TLSv1` / `TLSv1-1` / `TLSv1-2` | Same page (6.2.1 CLI Reference). Current-branch equivalents: [7.6.5](https://docs.fortinet.com/document/fortigate/7.6.5/cli-reference/141516630/config-log-syslogd-setting), [7.6.2](https://docs.fortinet.com/document/fortigate/7.6.2/cli-reference/141516630/config-log-syslogd-setting) |
| Current-branch parameter set also includes `format` (values `default`, `csv`, `cef`, `rfc5424`, `json`), `priority`, `max-log-rate`, `interface`, `interface-select-method`, `source-ip-interface`, `vrf-select`, `custom-log-format` | [Fortinet Community — "Technical Tip: Configuring multiple Syslog servers"](https://community.fortinet.com/t5/FortiGate/Technical-Tip-Configuring-multiple-Syslog-servers/ta-p/194117) — **secondary** (Fortinet-authored KB; reproduces the current CLI schema) |
| `legacy-reliable` = RFC 3195 (BEEP RAW profile, TCP/601); `reliable` = RFC 6587 | [Fortinet Community — "Technical Tip: Enabling reliable delivery of syslog messages from a FortiGate to a syslog server - RFC 3195"](https://community.fortinet.com/t5/FortiGate/Technical-Tip-Enabling-reliable-delivery-of-syslog-messages-from/ta-p/193012) — **secondary** |
| FortiOS v6.0+ frames TCP syslog with **RFC 6587 octet counting**; receivers expecting non-transparent (newline) framing may treat many logs as one long message | [Fortinet Community — "Troubleshooting Tip: FortiGate syslog via TCP and log parsing"](https://community.fortinet.com/t5/FortiGate/Troubleshooting-Tip-FortiGate-syslog-via-TCP-and-log-parsing/ta-p/198397) — **secondary** |
| GUI path **Log & Report → Log Settings**, toggle **Send Logs to Syslog** → Enabled, enter collector address, **Apply**; example CLI block `config log syslogd setting / set status enable / set server / set mode udp / set port 514 / end`; `set source-ip`, `set interface-select-method specify`, `set interface`, `set source-ip-interface` (v7.6.0+) variants | [Fortinet Community — "Technical Tip: How to configure syslog on FortiGate"](https://community.fortinet.com/t5/FortiGate/Technical-Tip-How-to-configure-syslog-on-FortiGate/ta-p/331959) — **secondary**. GUI location corroborated by [FortiOS 7.6.2 Administration Guide — "Log settings and targets"](https://docs.fortinet.com/document/fortigate/7.6.2/administration-guide/250999/log-settings-and-targets) |
| Default port 514; default `mode` udp; default facility **local7** | [Fortinet Community — "Technical Tip: How to use the facility function of syslogd"](https://community.fortinet.com/t5/FortiGate/Technical-Tip-How-to-use-the-facility-function-of-syslogd/ta-p/287911) and the "How to configure syslog on FortiGate" tip above — **secondary** |
| A FortiGate can send to **up to four** syslog servers: `config log syslogd setting` plus `syslogd2` / `syslogd3` / `syslogd4`, each with its own `filter` block (display with `show full-configuration log syslogd filter`, and the same for the numbered variants) | [Fortinet Community — "Technical Tip: Configuring multiple Syslog servers"](https://community.fortinet.com/t5/FortiGate/Technical-Tip-Configuring-multiple-Syslog-servers/ta-p/194117) — **secondary**; corroborated by [FortiOS Administration Guide — "Configuring multiple FortiAnalyzers (or syslog servers) per VDOM"](https://docs.fortinet.com/document/fortigate/7.0.5/administration-guide/610676/configuring-multiple-fortianalyzers-or-syslog-servers-per-vdom) |
| `config log syslogd filter` options: `severity` — values `emergency`, `alert`, `critical`, `error`, `warning`, `notification`, `information`, `debug` ("Lowest severity level to log") — plus `forward-traffic`, `local-traffic`, `multicast-traffic`, `sniffer-traffic`, `anomaly`, `voip`, `gtp`, `filter` (string, max 511) and `filter-type` (`include` / `exclude`) | [FortiOS CLI Reference — `log syslogd filter` (6.2.4)](https://docs.fortinet.com/document/fortigate/6.2.4/cli-reference/426620/log-syslogd-filter); current branch: [7.0.4](https://docs.fortinet.com/document/fortigate/7.0.4/cli-reference/450620/config-log-syslogd-filter) |
| Event logging is governed by `config log eventfilter` (`event`, `system`, `vpn`, `user`, `router`, `wireless-activity`, `endpoint`, `ha`, `security-rating`, `fortiextender`, `connector`, …) and **all event logging is enabled by default** | [FortiOS CLI Reference — `log eventfilter` (6.2.1)](https://docs.fortinet.com/document/fortigate/6.2.1/cli-reference/375620/log-eventfilter); [7.2.4](https://docs.fortinet.com/document/fortigate/7.2.4/cli-reference/484620/config-log-eventfilter); default-enabled statement: [Fortinet Community — "Technical Tip: No system event logs"](https://community.fortinet.com/fortigate-3/technical-tip-no-system-event-logs-96100) — **secondary** |
| Traffic logging is per firewall policy: GUI **Policy & Objects → Firewall Policy → Log Allowed Traffic → Security Events (UTM) / All Sessions**; CLI `config firewall policy` → `edit <id>` → `set logtraffic` with values `all`, `utm` or `disable`. "All Sessions" logs every accepted/denied connection; "Security Events" logs only traffic matching an applied security profile, and is the lighter recommended default | [Fortinet Community — "Technical Tip: Difference between 'Security Events' and 'All session' in Log Allowed Traffic in Firewall Policy"](https://community.fortinet.com/t5/FortiGate/Technical-Tip-Difference-between-Security-Events-and-All-session/ta-p/206881) — **secondary** |
| CA certificate import GUI path: **System → Certificates → Import → CA Certificate → File**; on builds where Certificates is hidden, enable it first under **System → Feature Visibility** | [Fortinet Community — "Technical Tip: How to import the CA certificate for full SSL inspection"](https://community.fortinet.com/t5/FortiGate/Technical-Tip-How-to-import-the-CA-certificate-for-full-SSL/ta-p/189786) — **secondary**; corroborated by [FortiOS 7.6.5 Administration Guide — "Import a certificate"](https://docs.fortinet.com/document/fortigate/7.6.5/administration-guide/907098/import-a-certificate) |
| When the FortiGate is the syslog **client**, importing the CA that signed the syslog server's certificate is what makes the FortiGate trust that server; a client certificate is **not** required unless the server demands client authentication. Imported CAs appear as `CA_Cert_1`, `CA_Cert_2`, …; the CLI object is `config vpn certificate ca` | [Fortinet Community — "Syslog over TLS with local CA — has anyone gotten this to work?"](https://community.fortinet.com/t5/Support-Forum/Syslog-over-TLS-with-local-CA-has-anyone-gotten-this-to-work/td-p/292038) — **secondary** (Fortinet forum, staff/expert answers) |
| Handshake failures on syslog TLS surface as an SSL alert **Unknown CA** from the FortiGate; missing intermediates in the chain are a common cause | [Fortinet Community — "Configuring Syslog TLS on FortiGate resulted in Handshake Error (Unknown CA)"](https://community.fortinet.com/t5/Support-Forum/Configuring-Syslog-TLS-on-FortiGate-resulted-in-Handshake-Error/m-p/204607) — **secondary** |
| `diagnose log test` generates test log entries (virus, URL block, DLP, IPS, botnet, anomaly, application control, antispam, SSH/SSL, …) written to local storage **and to configured syslog servers / FortiAnalyzer / WebTrends / the dashboard**; its optional arguments differ between FortiOS versions | [Fortinet Community — "Technical Tip: How to perform a syslog and log test on a FortiGate with the 'diagnose log test' command"](https://community.fortinet.com/t5/FortiGate/Technical-Tip-How-to-perform-a-syslog-and-log-test-on-a/ta-p/194606) — **secondary** |
| Connectivity checks: `execute ping <server>`, `execute traceroute <server>`, `execute telnet <server> 514`; config display via `show full-configuration log syslogd setting`, or `get` inside the filter block | [Fortinet Community — "Troubleshooting Tip: Syslog and log troubleshooting via CLI"](https://community.fortinet.com/t5/FortiGate/Troubleshooting-Tip-Syslog-and-log-troubleshooting-via-CLI/ta-p/192137) — **secondary**; `execute ping-options source` / `execute ping` variants from the "How to configure syslog on FortiGate" tip |

### Explicit gaps (not guessed)

- **UNVERIFIED — wire format expected by the Fluency `FortiGateFWLogV2` parser.** FortiOS offers
  `set format default | csv | cef | rfc5424 | json`; no public Fluency documentation states which
  one the parser consumes. The skill recommends leaving `format` at FortiOS's own `default`
  (native `key=value`) and escalating to Fluency support if events land unparsed, rather than
  guessing a format.
- **UNVERIFIED — CLI syntax for importing a PEM CA certificate.** `config vpn certificate ca` is
  the correct configuration object (cited above), but none of the sources checked document the
  exact CLI incantation for loading the PEM body. The skill directs the admin to the documented
  GUI import and explicitly says not to hand-craft the CLI form.
- **RESOLVED 2026-07-28 (was UNVERIFIED) — the platform handles RFC 6587 octet-counted framing
  on a dedicated listener.** Per the Fluency team: `syslog_get_config` reports the fields
  **`tls_rfc6587`** and **`tls_rfc6587_port`** for exactly this case, and
  `syslog_register_config` can create that listener when the site has none. The skill therefore
  targets `tls_rfc6587` for FortiGate's TLS path rather than plain `syslog_tls`, and the
  merged-records failure mode now points at "wrong listener" instead of "escalate to support".
  This is platform guidance, not vendor documentation (plan §5, R14).

## Fluency platform side (not vendor documentation)

The syslog transport mechanism is platform guidance from the Fluency team (2026-07-28), recorded
in `plans/connector-skills-rollout.md` (R1 resolution):

- `syslog_get_config` — read the site's syslog configuration.
- `syslog_register_config` — create it; **once per site, ever** — never when one exists.
- `syslog_update_config` — enable an additional listener (e.g. `syslog_tls`) on an existing
  configuration, leaving other listeners untouched.
- TLS-capable sources — which FortiGate is — use the `syslog_tls` listener with the platform CA
  certificate: https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt
- Exact parameter shapes come from the live MCP tool schemas at runtime.

Connector template `FortiGateFWLogV2` ("FortiGate NGFW Syslog V2", category `onpremise`,
resourceGroups `["Fortigate"]`, **no parameters**) is from the live `list_connector_templates`
snapshot of 2026-07-23; re-fetch live at runtime. The datalake table is **not** defined by the
template — confirm with `list_data_tables`. The repo's `fortigate-bandwidth` skill refers to a
`NetworkFortigateTraffic` / `fortigatetraffic`-style table; treat that as a hint only.
