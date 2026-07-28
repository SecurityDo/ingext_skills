# References — Cisco ASA syslog vendor-side steps & platform transport

Verified 2026-07-28. Primary sources are Cisco's own ASA 9.23 documentation set unless marked
otherwise.

Short names used in the table below:

- **[LOG-CLI]** — [CLI Book 1: Cisco Secure Firewall ASA Series General Operations CLI Configuration Guide, 9.23 — Logging](https://www.cisco.com/c/en/us/td/docs/security/asa/asa923/configuration/general/asa-923-general-config/monitor-syslog.html)
- **[LOG-ASDM]** — [ASDM Book 1: Cisco Secure Firewall ASA Series General Operations ASDM Configuration Guide, 7.23 — Logging](https://www.cisco.com/c/en/us/td/docs/security/asa/asa923/asdm723/general/asdm-723-general-config/monitor-syslog.html)
- **[CMD-REF]** — [Cisco Secure Firewall ASA Series Command Reference, I–R Commands — log – lz](https://www.cisco.com/c/en/us/td/docs/security/asa/asa-cli-reference/I-R/asa-command-ref-I-R/m_log-lz.html)
- **[CERTS]** — [CLI Book 1, 9.23 — Digital Certificates](https://www.cisco.com/c/en/us/td/docs/security/asa/asa923/configuration/general/asa-923-general-config/basic-certs.html)
- **[MGMT]** — [CLI Book 1, 9.23 — Management Access](https://www.cisco.com/c/en/us/td/docs/security/asa/asa923/configuration/general/asa-923-general-config/admin-management.html)
- **[TAC-SYSLOG]** — [Cisco TAC — Configure Adaptive Security Appliance (ASA) Syslog](https://www.cisco.com/c/en/us/support/docs/security/pix-500-series-security-appliances/63884-config-asa-00.html)
- **[TAC-MISSING]** — [Cisco TAC — ASA Troubleshooting Guide: Missing Logs at Syslog Destination(s)](https://www.cisco.com/c/en/us/support/docs/security/asa-5500-x-series-next-generation-firewalls/113603-asa-missing-logs-00.html)
- **[MSG]** — [Cisco Secure Firewall ASA Series Syslog Messages — Syslog Messages 101001 to 199027](https://www.cisco.com/c/en/us/td/docs/security/asa/syslog/asa-syslog/syslog-messages-101001-to-199021.html)

## Cisco ASA device side

| Claim in SKILL.md | Source |
|---|---|
| `logging enable` enables transmission of syslog messages to all output locations | [LOG-CLI] "Enable Logging"; [TAC-SYSLOG] |
| `logging host interface_name syslog_ip [tcp[/port] \| udp[/port]] [format emblem \| timestamp [legacy\|rfc5424]] [secure [reference-identity name]]` | [CMD-REF] `logging host`; [LOG-CLI] "Send Syslog Messages to an External Syslog Server" |
| `syslog_ip` is **the IP address (IPv4 or IPv6) of the syslog server** — no FQDN form documented | [CMD-REF] `logging host`, Syntax Description |
| Default protocol is **UDP**; default **UDP port 514**, default **TCP port 1470**; valid ports **1025–65535** for either protocol | [CMD-REF] `logging host`, Command Default; [LOG-CLI] Step 1 |
| `format emblem` is **UDP only** | [CMD-REF]; [LOG-CLI] |
| **TCP warning:** "If you specify TCP, when the ASA discovers syslog server failures, for security reasons, new connections through the ASA are blocked." / "If the server is inaccessible, or the TCP connection to the server cannot be established, the ASA, by default, blocks ALL new connections." | [LOG-CLI] Step 1 Warning; [TAC-SYSLOG] "Send Logging Information to a Syslog Server" |
| **TLS warning:** "A secure logging connection can only be established with an SSL/TLS-capable syslog server. If an SSL/TLS connection cannot be established, all new connections will be denied. You may change this default behavior by entering the `logging permit-hostdown` command." | [CMD-REF] `logging host`, `secure` keyword note |
| `logging permit-hostdown` "makes the status of a TCP-based syslog server irrelevant to new user sessions"; **default is false / off** | [CMD-REF] `logging permit-hostdown`; [LOG-CLI] Step 3 |
| Since **8.3(2)** the block also triggers when the **logging queue is full**; syslog messages **414005–414008** were introduced; Cisco: "Unless required, we recommended allowing connections when syslog messages cannot be sent or received." | [LOG-CLI] "History for Logging" → *Enhanced logging and connection blocking*; [LOG-ASDM] same table |
| `%ASA-3-201008: Disallowing new connections.` is the error seen when the ASA cannot contact the TCP syslog server | [TAC-SYSLOG] "%ASA-3-201008: Disallowing New Connections" |
| `logging trap {severity_level \| message_list}`; sending level *N* sends *N and more severe*; level names 0 `emergencies` … 7 `debugging`; **ASA does not generate level 0** | [CMD-REF] `logging trap`; [LOG-CLI] "Syslog message severity levels" (Table 1) |
| Debugging output "can render the system unusable" — use level 7 only for deliberate troubleshooting | [CMD-REF] `logging trap`, Note |
| Guideline: with **two or more logging servers, limit the logging severity level to warnings for all of them**; "Assign only one list or class to each syslog server and location" | [LOG-CLI] "Syslog server configuration guidelines" and "Generate Syslog Messages in EMBLEM Format to a Syslog Server" |
| `logging timestamp`; `logging timestamp rfc5424` renders `YYYY-MM-DDTHH:MM:SSZ` (UTC) | [CMD-REF] `logging timestamp`; [LOG-CLI] "Include the Date and Time in Syslog Messages" |
| `logging device-id {cluster-id \| context-name \| hostname \| ipaddress interface_name [system] \| string text}` | [LOG-CLI] "Include the Device ID in Non-EMBLEM Format Syslog Messages" |
| `logging list name {level level [class message_class] \| message start_id[-end_id]}`; a message is logged if it satisfies **any** criterion, and only once; list names must not be (or start with the first three characters of) severity-level names | [LOG-CLI] "Create a Custom Event List" Steps 1–2 |
| `no logging message <id>` disables a message; `logging message <id> level <sev>` changes its severity; `show logging message <id>`; `clear configure logging disabled` / `clear configure logging level` reset them | [LOG-CLI] "Disable a Syslog Message" / "Change the Severity Level of a Syslog Message"; [TAC-SYSLOG] |
| ACL `log` keyword generates **106100** for matching permit/deny flows; denies generate **106023** by default without it; default log level for a new ACE is 6 | [TAC-SYSLOG] "Log ACL Hits" |
| `logging queue message_count` — default **512**, range **0–8192** depending on platform, 0 = maximum; `show logging queue` shows drops | [LOG-CLI] "Configure the Logging Queue"; [TAC-MISSING] "Output of show logging queue" |
| `logging facility number` — default **20**, "which is what most UNIX systems expect" | [LOG-CLI] Step 4 |
| Up to **16 syslog servers**; in multiple context mode, **four per context** | [LOG-CLI] "Syslog server configuration guidelines" |
| **TCP syslog is not supported on a standby device**; TCP opens **4 connections**; a downed TCP host takes ~**six minutes** to change from *Connected* to *Not connected* | [LOG-CLI] "TCP and UDP connections for syslog" |
| Syslog configured on an interface with **management-only access enabled** drops dataplane messages **302015, 302014, 106023, 304001** | [LOG-CLI] "Configure an Output Destination" |
| The syslog server should be reachable through the ASA; deny ICMP unreachable on that interface; suppress **313001, 313004, 313005** | [LOG-CLI] "Syslog server configuration guidelines" |
| In **9.18.3.60 and higher**, the interface named in `logging host` takes precedence over a route lookup | [CMD-REF] `logging host`, Usage Guidelines |
| **IPv6 cannot be used for secure logging** | [LOG-CLI] "Restrictions for IPv6 logging" |
| The syslog server's certificate must contain **`ServAuth`** in the Extended Key Usage field (checked on non-self-signed certificates) | [LOG-CLI] "Syslog server configuration guidelines" |
| Secure syslog on ASA is **one-way TLS** — no client certificate / mutual TLS | [LOG-CLI] "Syslog server configuration guidelines" (stated for Firewall Threat Defense syslog); corroborated by [CMD-REF] `secure`, which defines the option purely as the ASA using SSL/TLS toward the server |
| `crypto ca trustpoint <name>` → `enrollment terminal` (manual, paste-in enrolment) → `revocation-check {crl \| none \| ocsp}` | [CERTS] "Configure Trustpoints" Steps 1, 3, 5 |
| `crypto ca authenticate <trustpoint>` imports the CA certificate; the ASA prompts `Enter the base 64 encoded CA certificate. End with a blank line or the word "quit" on a line by itself`, then a fingerprint confirmation, then `Trustpoint CA certificate accepted.` / `% Certificate successfully imported` | [CERTS] "Obtain Certificates Manually" Step 1 |
| `show crypto ca certificate` displays the trustpoint's CA certificate | [CERTS] "Obtain Certificates Manually" |
| `crypto ca reference-identity <name>` with `dns-id` / `cn-id` / `srv-id` / `uri-id`; RFC 6125 checks; **reference identities are used when connecting to the Syslog Server and the Smart Licensing server only**; if the presented identity cannot be matched the connection is not established and an error is logged. Cisco's own example configures one for a syslog server | [CERTS] "Configure Reference Identities" (incl. the `syslogServer` example) |
| A CA certificate from the server's issuing chain must be trusted — "exists in a trustpoint or the ASA trustpool" | [CERTS] "Additional Guidelines" |
| `logging host inside 10.0.0.1 TCP/1500 secure reference-identity syslogServer` (secure-logging example) | [LOG-CLI] "Enable Secure Logging" |
| `write memory` persists the running configuration | [MGMT] (used as the documented save step throughout the ASA configuration guide) |
| `show logging` output fields — `Syslog logging: enabled`, `Facility:`, `Timestamp logging:`, `Trap logging: level …, facility …, N messages logged`, `Logging to <interface> <ip>`, `Permit-hostdown logging:` | [LOG-CLI] "Examples for Logging" |
| Monitoring commands: `show logging`, `show logging message`, `show logging message <id>`, `show logging queue`, `show running-config logging` | [LOG-CLI] "Monitoring the Logs" |
| `%ASA-5-111008: User 'user' executed the 'string' command.` (severity 5) and `%ASA-7-111009: User 'user' executed cmd: string` (severity 7) — the documented test-event basis | [MSG] entries 111008 and 111009 |
| ASDM paths: **Configuration → Device Management → Logging → Logging Setup / Syslog Servers / Logging Filters / Event Lists / Syslog Setup / Rate Limit**; **Monitoring → Logging → Real-Time Log Viewer** and **Log Buffer Viewer** | [LOG-ASDM] "History for Logging" table |
| ASDM secure-logging procedure: select the syslog server → **Edit** → click the **TCP** radio button → check **Enable secure syslog with SSL/TLS** → optionally specify a **Reference Identity** object | [LOG-ASDM] "Enable Secure Logging" |
| ASDM checkbox **Allow user traffic to pass when TCP syslog server is down** on the **Syslog Servers** pane is the `logging permit-hostdown` equivalent | [LOG-ASDM] Step 4 of "Generate Syslog Messages in EMBLEM Format to a Syslog Server" + "History for Logging" table |
| Secondary corroboration: a healthy TLS syslog host shows four connected TCP/TLS connections in `show logging` | [Cisco Community — "Secure syslog using SSL/TLS on Cisco switches, router and Firewall"](https://community.cisco.com/t5/network-security/secure-syslog-using-ssl-tls-on-cisco-switches-router-and/td-p/3690273) — **secondary** (community answer, not Cisco staff, 2019). Consistent with [LOG-CLI]'s primary statement that TCP syslog opens 4 connections. |
| Secondary corroboration: "The ASAs support [secure syslog] and you only need to add the CA certificates of the root CA to the ASA if your syslog server sends the complete intermediate certificate chain" | Same community thread — **secondary**. The primary basis for importing the CA is [CERTS] "Additional Guidelines" (the issuing chain must exist in a trustpoint or the trustpool). |

Notes:

- **Version scope.** Commands and paths above are taken from the ASA **9.23** general-operations
  guides and ASDM **7.23**. Every command cited has been present for many releases (secure logging
  since 8.0(2), reference identities since 9.6(2), `logging permit-hostdown` since well before
  8.3(2)), but confirm against the ASA's own `?` help if the customer runs something much older.
- **Do not confuse ASA with FTD.** `logging permit-hostdown`, `logging host … secure`, and the
  trustpoint import are ASA CLI. A Firepower Threat Defense device managed by FMC configures
  syslog in the management centre instead — that is out of scope for this skill and its
  anti-triggers say so.
- **UNVERIFIED:** the exact ASDM toolbar wording for saving the running configuration to flash.
  The skill states the CLI equivalent (`write memory`) and says ASDM changes still need saving,
  without naming a menu item. Follow the live ASDM.
- **UNVERIFIED:** whether the Fluency platform's `syslog_tls` listener certificate carries
  `ServAuth` in its Extended Key Usage. Cisco requires it for non-self-signed server certificates;
  the skill lists it as the first thing to check if the ASA rejects the certificate. Confirm with
  the Fluency team if a TLS handshake fails despite a correctly imported CA.

## Fluency platform side (not vendor documentation)

The syslog transport mechanism is platform guidance from the Fluency team (2026-07-28), recorded
in `plans/connector-skills-rollout.md` (R1 resolution):

- `syslog_get_config` — read the site's syslog configuration.
- `syslog_register_config` — create it; **once per site, ever** — never when one exists.
- `syslog_update_config` — enable an additional listener (e.g. `syslog_tls`, `syslog_tcp`,
  `syslog_udp`) on an existing configuration, leaving other listeners untouched.
- TLS-capable sources use the `syslog_tls` listener with the platform CA certificate:
  https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt
- Exact parameter shapes come from the live MCP tool schemas at runtime.
- Connector template snapshot (2026-07-23): `CiscoASAFWLog`, displayName "Cisco ASA Syslog",
  category `onpremise`, resourceGroups `["CiscoASA"]`, parameters `datalake` (default `managed`)
  and `index` (default `CiscoASA`). Re-fetch with `list_connector_templates` at runtime — the
  snapshot is a hint, not truth.
