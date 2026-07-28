# References — SonicWall syslog vendor-side steps & platform transport

Verified 2026-07-28.

Primary sources are SonicWall's technical-documentation portal (`sonicwall.com/support/technical-documentation`)
and SonicWall's knowledge base (`sonicwall.com/support/knowledge-base`). Anything else is labelled
**secondary**.

## SonicWall device side

| Claim in SKILL.md | Source |
|---|---|
| Syslog servers live at **Device > Log > Syslog → Syslog Servers tab → Add**; dialog fields are **Event Profile** (0–23, 24 groups, "Each group can have a maximum of 7 Syslog servers"), **Name or IP Address** (address-object dropdown), **Port** (default 514), **Server Type** (Syslog Server \| Analyzer), **Syslog Format**, **Syslog Facility** (default Local Use 0), **Syslog ID** (default `firewall`, 0–32 alphanumeric/underscore chars), **Event Rate Limiting** (0–1000/s, default 1000), **Data Rate Limiting** (0–1,000,000,000 B/s, default 10,000,000), **Local Interface** / **Outbound Interface** | [SonicOS 7.0 Device Log — Adding a Syslog Server](https://www.sonicwall.com/support/technical-documentation/docs/sonicos-7.0.1-device_log/Content/Logs_Syslog/logs-syslog-adding-syslogserver.htm); [SonicOS 7.1 Device Log — Syslog Servers](https://www.sonicwall.com/support/technical-documentation/docs/sonicos-7-1-device_log/Content/Logs_Syslog/logs-syslog-servers.htm); [SonicOS 7.1 Device Log — Adding a Syslog Server](https://www.sonicwall.com/support/technical-documentation/docs/sonicos-7-1-device_log/Content/Logs_Syslog/logs-syslog-adding-syslogserver.htm) |
| **Syslog Format** options are **Default (default), WebTrends, Enhanced Syslog, ArcSight** | [SonicOS 7.1 Device Log — Syslog Servers](https://www.sonicwall.com/support/technical-documentation/docs/sonicos-7-1-device_log/Content/Logs_Syslog/logs-syslog-servers.htm); [SonicOS 7.0 Device Log — Adding a Syslog Server](https://www.sonicwall.com/support/technical-documentation/docs/sonicos-7.0.1-device_log/Content/Logs_Syslog/logs-syslog-adding-syslogserver.htm) |
| **SonicOS 7.0/7.1 have no protocol selector — syslog leaves over UDP** (default port 514) | The 7.0/7.1 Add-Syslog-Server dialogs and the 7.1 Syslog Servers table columns contain no Protocol field ([7.0](https://www.sonicwall.com/support/technical-documentation/docs/sonicos-7.0.1-device_log/Content/Logs_Syslog/logs-syslog-adding-syslogserver.htm), [7.1](https://www.sonicwall.com/support/technical-documentation/docs/sonicos-7-1-device_log/Content/Logs_Syslog/logs-syslog-servers.htm)), and SonicWall's verification KB states syslog is sent "on UDP port 514": [How can I check if SonicWall sends out logs to syslog server…](https://www.sonicwall.com/support/knowledge-base/how-can-i-check-if-sonicwall-sends-out-logs-to-syslog-server-and-syslog-server-receives-them/170502760959816) |
| **SonicOS 8 adds a Protocol selector — UDP (default), TCP, TLS**; port auto-fills **514** for UDP/TCP and **6514** for TLS; **Ignore TLS Certificate Error** option exists; Syslog Servers table gains a **Protocol** column and connection status for TCP/TLS | [SonicOS 8 Device Log — Syslog Servers](https://www.sonicwall.com/support/technical-documentation/docs/sonicos8-device_log/Content/Logs_Syslog/logs-syslog-servers.htm); [SonicOS 8 Device Log — Adding a Syslog Server](https://www.sonicwall.com/support/technical-documentation/docs/sonicos8-device_log/Content/Logs_Syslog/logs-syslog-adding-syslogserver.htm) |
| SonicOS 8 encrypted syslog is **TLS 1.2 and 1.3, per RFC 5425**; the firewall validates the server certificate and fails closed; issuers in the built-in CA list are trusted automatically, others must be imported into the SonicWall certificate store; "Ignore TLS Certificate Error" bypasses validation and is not for production | [SonicOS 8: Encrypted Syslog FAQ](https://www.sonicwall.com/support/knowledge-base/sonicos-8-encrypted-syslog-faq/kA1VN000001ImK90AK) |
| **Encrypted syslog is a SonicOS 8 feature** — the FAQ and the protocol selector appear only in the SonicOS 8 documentation set; no SonicOS 7.x source documents a TLS/TCP syslog option | Same FAQ + the 7.0/7.1 pages above (absence of the field). See "Unverified / gaps" below for 7.2/7.3 |
| **Syslog Settings**: Enhanced Syslog and ArcSight formats expose a field-selection dialog — "By default, all options are selected; the Host and Event ID options are dimmed as they cannot be changed", with **Enable All** / **Disable All**; page also carries **Enable NDPP Enforcement for Syslog Server** and **Display Syslog Timestamp in UTC**; under GMS the format is forced to Default and the ID to `firewall` (both greyed out) | [SonicOS 7.1 Device Log — Syslog Settings](https://www.sonicwall.com/support/technical-documentation/docs/sonicos-7-1-device_log/Content/Logs_Syslog/logs-syslog-settings.htm); [SonicOS 7.0 Device Log — Syslog Settings](https://www.sonicwall.com/support/technical-documentation/docs/sonicos-7.0.1-device_log/Content/Logs_Syslog/logs-syslog-settings.htm) |
| The **Syslog ID** is emitted on every message prefixed with `id=` (default `id=firewall`) | [SonicOS 7.0/7.1 Device Log — Syslog Settings](https://www.sonicwall.com/support/technical-documentation/docs/sonicos-7-1-device_log/Content/Logs_Syslog/logs-syslog-settings.htm) |
| **Device > Log > Settings** carries the **Logging Level** (Emergency…Debug, default **Inform**) and **Alert Level**; the table columns are **Category, Color, ID, Priority, GUI, Alert, Syslog, IPFIX, Email, Event Count**; the **Syslog** checkbox marks whether an event/group/category is sent to a syslog server; priority and destinations are editable at category, group or event level | [SonicOS 7.0 Device Log — Setting the Logging Level](https://www.sonicwall.com/support/technical-documentation/docs/sonicos-7.0.1-device_log/Content/Logs_Settings/logs-settings-setting-the-logging-level.htm); [SonicOS 7.1 Device Log — Setting the Logging Level](https://www.sonicwall.com/support/technical-documentation/docs/sonicos-7-1-device_log/Content/Logs_Settings/logs-settings-setting-the-logging-level.htm) |
| **Event Profile** routing: a syslog server is given a profile number, and categories are pointed at it by editing the category under **Device \| Log \| Settings** and setting **Use This Syslog Server Profile** to the matching number | [KB: Configuring Syslog Server with custom event profile on SonicWall](https://www.sonicwall.com/support/knowledge-base/configuring-syslog-server-with-custom-event-profile-on-sonicwall/kA1VN0000000G850AE) |
| **SonicOS 6.5 path** is **Manage \| Log Settings \| SYSLOG → Syslog tab → Add** (SonicOS 7.x is **Device \| Log \| Syslog → Syslog Servers → Add**) | [KB: How can I configure a syslog server on a SonicWall firewall?](https://www.sonicwall.com/support/knowledge-base/how-can-i-configure-a-syslog-server-on-a-sonicwall-firewall/kA1VN0000000TWl0AM) |
| SonicWall's own KB recommends selecting **Enhanced** — in the context of feeding SonicWall GMS/On-Premises Analytics, which the KB names as its prerequisite | Same KB. Cited in SKILL.md only to explain why it is *not* evidence about the Fluency parser |
| Address objects: **Object \| Match Objects \| Addresses → Address Objects → Add**; types are **Host, Range, Network, MAC, FQDN**; FQDN objects "are resolved using the DNS servers configured on the firewall in the NETWORK \| DNS page"; address objects are selectable from the dropdown on any screen that takes one | [SonicOS 7.1 Objects — Addresses key features](https://www.sonicwall.com/support/technical-documentation/docs/sonicos-7-1-objects/Content/Match_Objects/Addresses/key-features.htm); [KB: Understanding Address Objects in SonicOS](https://www.sonicwall.com/support/knowledge-base/understanding-address-objects-in-sonicos/kA1VN0000000EPe0AM) |
| CA certificate import: **Device \| Settings > Certificates → Import →** "Import a CA certificate from a PKCS#7 (\*.p7b) or DER (.der or .cer) encoded file" **→ Add File → Open → Import**; the entry then appears in the Certificates table | [SonicOS 7 Device Settings — Importing a Certificate Authority Certificate](https://www.sonicwall.com/support/technical-documentation/docs/sonicos-7-0-0-0-device_settings/Content/Topics/Certificates/certificates-local-importing.htm) (same path referenced by the SonicOS 8 Encrypted Syslog FAQ for importing a syslog server's CA) |
| Device-side ground truth is **Monitor \| Logs > System Logs** | [SonicOS 7.0 Monitor Logs — System Logs](https://www.sonicwall.com/support/technical-documentation/docs/sonicos-7-0-0-0-monitor_logs/Content/Logs_System/logs_system.htm); [SonicOS 7.1 Monitor Logs](https://www.sonicwall.com/support/technical-documentation/docs/sonicos-7-1-monitor_logs/Content/monitor-logs.htm) |
| Packet-capture proof that the firewall is emitting syslog: **Monitor \| Packet Monitor → General**; *Monitor Filter* Ether Type(s) `IP`, IP Type(s) `UDP`, Destination Port(s) `514`, **Bidirectional Address and Port Matching**; *Display Filter* all checkboxes; *Advanced Monitor Filter* **Monitor Firewall Generated Packets** + **Monitor Intermediate Packets**; **Start Capture**. SonicOS 6.5 equivalent: **Investigate \| Packet monitor → Configure** | [KB: How can I check if SonicWall sends out logs to syslog server and syslog server receives them?](https://www.sonicwall.com/support/knowledge-base/how-can-i-check-if-sonicwall-sends-out-logs-to-syslog-server-and-syslog-server-receives-them/170502760959816) |

## Certificate conversion (not SonicWall documentation)

| Claim in SKILL.md | Source |
|---|---|
| The platform CA file at https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt is a **PEM bundle of five root certificates** — Amazon Root CA 1, 2, 3, 4 and Starfield Services Root Certificate Authority G2 | Inspected at build time (2026-07-28) with `openssl storeutl -noout -text`: five `BEGIN CERTIFICATE` blocks, self-signed Amazon/Starfield roots. Re-check before relying on it — the bundle can change |
| `openssl crl2pkcs7 -nocrl -certfile <pem> -outform DER -out <p7b>` packages one or more PEM certificates into a PKCS#7 file; `-certfile` "Specifies a filename containing one or more certificates in PEM format. All certificates in the file will be added to the PKCS#7 structure"; `-nocrl` omits the CRL | [OpenSSL docs — openssl-crl2pkcs7](https://docs.openssl.org/master/man1/openssl-crl2pkcs7/) |

## Unverified / gaps (do not guess these)

- **Which syslog format Fluency's `SonicWallFWLog` parser expects — UNVERIFIED.** Fluency does not
  publish it and no source was found at build time. The skill recommends the SonicOS **Default**
  format (the factory setting) and gives an explicit diagnostic (unparsed rows → try **Enhanced
  Syslog** → otherwise ask Fluency support). Do not assert a format the platform has not confirmed.
- **SonicOS 7.2 / 7.3 syslog transport — UNVERIFIED.** The 7.3 Device Log guide was not reachable
  at build time (404 on the expected paths) and search returned no 7.3 syslog page. The skill tells
  the admin to look for a **Protocol** field in the Add Syslog Server dialog and branch on what is
  actually there. SonicOS 8 documents the field; 7.0/7.1 do not.
- **A "send test syslog" mechanism — UNVERIFIED.** No SonicWall documentation found for one. The
  skill substitutes the documented Packet Monitor capture plus a benign self-generated event.
- **SonicOS CLI syntax for syslog servers — NOT USED.** The procedure is documented in the web UI
  only in the sources above; no CLI syntax was verified, so none is published in the skill. If a
  customer needs it, get it from the SonicOS CLI Reference Guide for their firmware — do not
  improvise it.
- **Whether the firewall's built-in CA list already trusts Amazon Trust Services — UNVERIFIED.**
  SonicWall does not publish the built-in list. The skill therefore says: try TLS first, import the
  converted bundle only if validation fails.
- **SonicWall community posts** (e.g. the "Difference between Default syslog format and Enhanced
  Syslog Format" discussion) were considered as secondary sources but are **not cited** — the page
  could not be fetched at build time, and no claim in the skill depends on it.

## Fluency platform side (not vendor documentation)

The syslog transport mechanism is platform guidance from the Fluency team (2026-07-28), recorded in
`plans/connector-skills-rollout.md` (R1 resolution):

- `syslog_get_config` — read the site's syslog configuration.
- `syslog_register_config` — create it; **once per site, ever** — never when one exists.
- `syslog_update_config` — enable an additional listener (e.g. `syslog_udp`, `syslog_tcp`,
  `syslog_tls`) on an existing configuration, leaving other listeners untouched.
- TLS-capable sources use the `syslog_tls` listener with the platform CA certificate:
  https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt
- Exact parameter shapes come from the live MCP tool schemas at runtime.
- The `SonicWallFWLog` template ("SonicWall NGFW Syslog", category `onpremise`, resourceGroups
  `["SonicWall"]`, **no parameters**) is a 2026-07-23 snapshot of `list_connector_templates` — the
  skill re-fetches live. The datalake table is not defined by the template; confirm with
  `list_data_tables`.
