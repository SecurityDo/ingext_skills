# References — Sophos Firewall (SFOS) syslog vendor-side steps & platform transport

Verified 2026-07-28 against the current documentation set, **SFOS 22.0 MR2** (docs.sophos.com
landing page dated 14 Jul 2026). Paths were spot-checked against SFOS 18.5 / 19.0 / 20.0 / 21.5
help versions and have been stable across them.

## Sophos Firewall device side

| Claim in SKILL.md | Source |
|---|---|
| Syslog server is added at **System services → Log settings → Add**; fields are **Name**, **IP address/domain**, **Secure log transmission** (TLS), **Port**, **Facility**, **Severity level**, **Format**; after saving you must "Go to Log settings and select the logs you want to send to the syslog server" | [Add a syslog server — SFOS 22.0](https://docs.sophos.com/nsg/sophos-firewall/22.0/Help/en-us/webhelp/onlinehelp/AdministratorHelp/SystemServices/LogSettings/SyslogServerAdd/index.html) |
| Facility values **DAEMON / KERNEL / USER / LOCAL0–LOCAL7**, with the documented "LOCAL1 for firewall 1, LOCAL2 for firewall 2" tagging example | Same page |
| Severity level is the **minimum** level; the firewall logs everything at that level and above; `Debug` includes all messages | Same page |
| Format is either **Standard syslog protocol** (renamed from "Central Reporting Format") or **Device standard format (legacy)**, "a custom format in which the number of log data fields differs for each module" | Same page |
| Full API-level field/enum list (`SyslogServers`: Name, ServerAddress, Port, EnableSecureConnection, Facility, SeverityLevel, Format), severity enum `Emergency/Alert/Critical/Error/Warning/Notification/Information/Debug` | [API reference — Add/Update Syslog Servers, SFOS 22.0](https://docs.sophos.com/nsg/sophos-firewall/22.0/api/configure/system%20services/syslogservers/operations/AddSyslogServers&UpdateSyslogServers.html) |
| **Up to five syslog servers**; "the syslog protocol normally uses UDP port 514"; the Log settings matrix has columns for **Local reporting**, **Central reporting**, and each syslog server; logs can be selected "by module or feature, or you can select all logs" | [Log settings — SFOS 22.0](https://docs.sophos.com/nsg/sophos-firewall/22.0/Help/en-us/webhelp/onlinehelp/AdministratorHelp/SystemServices/LogSettings/index.html) |
| The 13 log categories and their descriptions (Firewall, IPS, Antivirus, Anti-spam, Content filtering, Events, Web server protection, Active threat response, Wireless, Heartbeat, System health, Zero-day protection, SD-WAN) | Same page |
| **Active threat response → Remote source match (inbound traffic) is not on by default**; **Wireless → Access points & SSID is off by default under Local reporting** because wireless logs aren't shown in the Log viewer | Same page |
| **Log suppression** ("Suppress logs" → All) collapses consecutive identical entries and applies to the Log viewer, Sophos Central **and** third-party syslog servers; currently only Firewall logs can be suppressed | Same page |
| Establishing TLS **in LINCE mode requires the certificate's CN or SAN to match the syslog server's domain; with LINCE off the firewall only verifies the CN** | Same page |
| Firewall rules need **Log firewall traffic** selected, SSL/TLS inspection rules need **Log connections**, and web-policy events require the associated firewall rule to log traffic | Same page + [Logs — SFOS 22.0](https://docs.sophos.com/nsg/sophos-firewall/22.0/Help/en-us/webhelp/onlinehelp/AdministratorHelp/Logs/index.html) |
| Per-category **sub-selections** enumerated in the skill's category table (Firewall: PolicyRules, InvalidTraffic, LocalACLs, DoSAttack, DroppedICMPRedirectedPacket, DroppedSourceRoutedPacket, DroppedFragmentedTraffic, MACFiltering, IP-MACPairFiltering, IPSpoofPrevention, SSLVPNTunnel, ProtectedApplicationServer, Heartbeat, ICMPErrorMessage, BridgeACLs · IPS: Anomaly, Signatures · AntiVirus: HTTP, FTP, SMTP, POP3, IMAP, IM, HTTPS, SMTPS, POPS, IMAPS · AntiSpam: SMTP, POP3, IMAP, SMTPS, POPS, IMAPS · ContentFiltering: WebFilter, ApplicationFilter, WebContentPolicy · Events: AdminEvents, AuthenticationEvents, SystemEvents · WebServerProtection: WAFEvents · ATP: ATRDestMatch, ATRSourceInboundMatch, ATRSourceOutboundMatch · Wireless: AccessPoints_SSID · Heartbeat: EndpointStatus · SystemHealth: Usage · ZeroDayProtection: ZeroDayProtectionEvents) | [API reference — Add/Update Syslog Servers, SFOS 22.0](https://docs.sophos.com/nsg/sophos-firewall/22.0/api/configure/system%20services/syslogservers/operations/AddSyslogServers&UpdateSyslogServers.html) — the `<LogSettings>` payload. **Note:** these are the API tag names; the console shows friendlier labels. **SD-WAN has no sub-selection block in the API sample**, which is why the skill's table says "read the console" for it |
| TLS syslog: enable **Secure log transmission**, Sophos's worked example uses port **6514**, and the documented flow uses the firewall's **default CA** (`Certificates → Certificate authorities → Default` → download → `Default.pem`) installed on a `syslog-ng` server configured with `peer_verify(required-trusted)` | [Configure a secure connection to a syslog server — SFOS 22.0](https://docs.sophos.com/nsg/sophos-firewall/22.0/Help/en-us/webhelp/onlinehelp/AdministratorHelp/SystemServices/LogSettings/LogsConfigureSecureSyslogServerWithExternalCertificate/index.html) |
| Importing an external CA: **Certificates → Certificate authorities → Add**, upload or paste; SFOS auto-detects format and supports X.509 `.pem`, `.der`, `.cer`; when no CSR matches, you choose the purpose **Validation only** vs **Signing and validation** (the latter needs the private key) | [Add a CA — SFOS 22.0](https://docs.sophos.com/nsg/sophos-firewall/22.0/Help/en-us/webhelp/onlinehelp/AdministratorHelp/Certificates/CertificateAuthorities/CertificatesAuthorityAdd/index.html) |
| **Log viewer** opens from the **upper-right corner of any page** in the web admin console, updates automatically, and filters by module | [Log viewer — SFOS 22.0](https://docs.sophos.com/nsg/sophos-firewall/22.0/Help/en-us/webhelp/onlinehelp/AdministratorHelp/Logs/LogViewer/index.html) |
| **Diagnostics → Packet capture** shows packets passing an interface and per-module processing details | [Packet capture — SFOS 22.0](https://docs.sophos.com/nsg/sophos-firewall/22.0/help/en-us/webhelp/onlinehelp/AdministratorHelp/Diagnostics/PacketCapture/index.html) |
| **Data anonymization** can encrypt identities in logs and reports (offered as a System services feature) | [Logs — SFOS 22.0](https://docs.sophos.com/nsg/sophos-firewall/22.0/Help/en-us/webhelp/onlinehelp/AdministratorHelp/Logs/index.html) (the "Tip" pointing at Data anonymization) |
| Syslog message structure, `log_id` composition and the per-log-type field tables (used to explain what each category emits) | [SFOS syslog file guide 22.0](https://docs.sophos.com/nsg/sophos-firewall/22.0/syslog/index.html) |

### Secondary sources (labelled as such in the skill)

| Claim | Source | Why secondary |
|---|---|---|
| Other SIEM integrations for this device specify **Device standard format** for correct parsing — used only as a starting hint for the Fluency format question, never as a Sophos statement | [Elastic — Sophos integration](https://www.elastic.co/docs/reference/integrations/sophos) ("For Sophos XG, the syslog format set to `Device Standard Format` or `Default` for correct parsing"); [WebSpy — Configuring Sophos logging](https://www.webspy.com/getting-started/sophos/) (Format = Device Standard Format) | Third-party SIEM vendors, not Sophos |
| `DAEMON` + `Information` as the conventional facility/severity choice for a SIEM feed | [Elastic — Sophos integration](https://www.elastic.co/docs/reference/integrations/sophos); [RocketCyber/Kaseya — Configuring Sophos firewall](https://help.rocketcyber.kaseya.com/help/Content/network-device-firewall/configure-network-device-sophos-firewall.html) | Third-party guidance; Sophos documents the semantics, not a recommendation |

## Explicit UNVERIFIED items

1. **Which log Format the Fluency `SophosFWLog` parser expects** — Sophos offers "Standard syslog
   protocol" and "Device standard format (legacy)". No Fluency documentation for this connector
   was found. The skill tells the operator to start with Device standard format (secondary-source
   convention) and settle it empirically or with Fluency support.
2. **Whether Fluency's `syslog_tls` listener requires a client certificate from the sending
   device (mutual TLS).** Sophos's only documented TLS-syslog procedure assumes the syslog server
   trusts the firewall's default CA, i.e. client authentication. The skill covers server-side
   trust (importing the platform CA) and CN/SAN matching, flags the mutual-TLS question, and falls
   back to UDP rather than guessing.
3. **The datalake table name** — the `SophosFWLog` template carries no index parameter, so the
   platform assigns it. Confirm live with `list_data_tables`; no live MCP session was available at
   build time.

## Fluency platform side (not vendor documentation)

The syslog transport mechanism is platform guidance from the Fluency team (2026-07-28), recorded
in `plans/connector-skills-rollout.md` (R1 resolution):

- `syslog_get_config` — read the site's syslog configuration.
- `syslog_register_config` — create it; **once per site, ever** — never when one exists.
- `syslog_update_config` — enable an additional listener (e.g. `syslog_tls` or `syslog_udp`) on an
  existing configuration, leaving other listeners untouched.
- TLS-capable sources — Sophos Firewall is one — use the `syslog_tls` listener with the platform
  CA certificate: https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt
- Exact parameter shapes come from the live MCP tool schemas at runtime.
