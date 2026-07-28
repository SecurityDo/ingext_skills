# References — PAN-OS syslog vendor-side steps & platform transport

Verified 2026-07-28.

Primary sources are Palo Alto Networks' own documentation (docs.paloaltonetworks.com) and its
official knowledge base (knowledgebase.paloaltonetworks.com). The knowledge base is
vendor-authored but is labelled **secondary** below where it is the only source for a claim, per
the research protocol (`plans/connector-skills-rollout.md` §4).

## Palo Alto Networks / PAN-OS device side

| Claim in SKILL.md | Source |
|---|---|
| Syslog server profile is created at **Device → Server Profiles → Syslog → Add**, with a **Name**, a **Location** (vsys or Shared on multi-vsys), and a **Servers** tab | [PAN-OS Admin Guide — "Configure Syslog Monitoring"](https://docs.paloaltonetworks.com/pan-os/11-1/pan-os-admin/monitoring/use-syslog-for-monitoring/configure-syslog-monitoring); [Configure Syslog Monitoring (PAN-OS)](https://docs.paloaltonetworks.com/ngfw/administration/monitoring/use-syslog-for-monitoring/configure-syslog-monitoring/configure-syslog-monitoring-pan-os) |
| Per-server fields: **Name** (≤31 chars, case-sensitive, unique), **Syslog Server** (IP or FQDN), **Transport** (TCP / UDP / **SSL**), **Port**, **Format** (**BSD** default, or IETF), **Facility** (**LOG_USER** default). Name/Location cannot be changed after saving | [PAN-OS Web Interface Help — "Device > Server Profiles > Syslog"](https://docs.paloaltonetworks.com/ngfw/help/10-1/device/device-server-profiles-syslog) |
| Default ports: **UDP 514**, **SSL 6514**; TCP has no default and must be specified. "You must use the same port number on the firewall and the syslog server" | Same Web Interface Help page; port statement also in [Configure Syslog Monitoring](https://docs.paloaltonetworks.com/pan-os/11-1/pan-os-admin/monitoring/use-syslog-for-monitoring/configure-syslog-monitoring) |
| Format guidance: "Traditionally, BSD format is over UDP and IETF format is over TCP or SSL/TLS"; Facility is "one of the Syslog standard values" per RFC 3164 (BSD) / RFC 5424 (IETF) | [PAN-OS Web Interface Help — "Device > Server Profiles > Syslog"](https://docs.paloaltonetworks.com/ngfw/help/10-1/device/device-server-profiles-syslog) |
| The **Custom Log Format** tab exists and lets a custom format and escape sequences be defined per log type | Same Web Interface Help page |
| For SSL transport "the firewall supports only **TLSv1.2**" | [Configure Syslog Monitoring](https://docs.paloaltonetworks.com/pan-os/11-1/pan-os-admin/monitoring/use-syslog-for-monitoring/configure-syslog-monitoring) |
| A certificate for secure syslog is "required only if the syslog server uses client authentication"; it is created at **Device → Certificate Management → Certificates → Device Certificates → Generate**, then "Click the certificate Name to edit it, select the **Certificate for Secure Syslog** check box, and click OK". The private key must be on the firewall (not an HSM); subject and issuer must differ; "The syslog server and the sending firewall must have certificates that the same trusted certificate authority (CA) signed" | [Configure Syslog Monitoring](https://docs.paloaltonetworks.com/pan-os/11-1/pan-os-admin/monitoring/use-syslog-for-monitoring/configure-syslog-monitoring); corroborated by [PAN KB — "How To Setup Syslog Monitoring Over TLS"](https://knowledgebase.paloaltonetworks.com/KCSArticleDetail?id=kA14u000000HCLCCA4) — **secondary** (KB adds: CN must match the firewall's IP used for syslog connectivity; SSL default port 6514) |
| "The connection to a Syslog server over TLS is validated using the Online Certificate Status Protocol (OCSP) or using Certificate Revocation Lists (CRL) so long as each certificate in the trust chain specifies one or both of these extensions. However, you cannot bypass OCSP or CRL failures…" | [Configure Syslog Monitoring](https://docs.paloaltonetworks.com/pan-os/11-1/pan-os-admin/monitoring/use-syslog-for-monitoring/configure-syslog-monitoring) |
| Additional enterprise/private CAs are imported at **Device → Certificate Management → Certificates** (Device Certificates on PAN-OS ≤11.2, Custom Certificates on 12.1.0+); the **Trusted Root CA** option marks a CA the organization trusts that is not in the pre-installed list; PEM (Base64 Encoded Certificate) and PKCS12 import formats are supported | [PAN-OS Admin Guide — "Default Trusted Certificate Authorities (CAs)"](https://docs.paloaltonetworks.com/pan-os/11-1/pan-os-admin/certificate-management/default-trusted-cas); [PAN-OS Web Interface Help — "Manage Default Trusted Certificate Authorities"](https://docs.paloaltonetworks.com/pan-os/11-0/pan-os-web-interface-help/device/device-certificate-management-certificates/manage-default-trusted-certificate-authorities); [PAN-OS Admin Guide — "Import a Certificate and Private Key"](https://docs.paloaltonetworks.com/pan-os/10-2/pan-os-admin/certificate-management/obtain-certificates/import-a-certificate-and-private-key) |
| Policy-match log types are forwarded via **Objects → Log Forwarding → Add** with match lists carrying **Name**, **Log Type** (**Traffic, Threat, WildFire Submission, URL Filtering, Data Filtering, Tunnel, Authentication**), **Filter** (Filter Builder), and **Forward Method** (Panorama / SNMP / Email / Syslog / HTTP). Naming the profile **`default`** makes it apply automatically to newly created rules and zones | [Configure Log Forwarding (PAN-OS)](https://docs.paloaltonetworks.com/ngfw/administration/monitoring/configure-log-forwarding/configure-log-forwarding-pan-os) |
| The profile is attached at **Policies → Security →** *rule* **→ Actions** tab, selecting the Log Forwarding profile; for traffic logs choose **Log at Session Start** and/or **Log at Session End** | Same page |
| **System, Configuration, GlobalProtect, HIP Match, User-ID and Correlation** logs are configured at **Device → Log Settings** — "For System and Correlation logs, click each Severity level, select the Syslog server profile, and click OK" | Same page; and [Configure Syslog Monitoring (PAN-OS)](https://docs.paloaltonetworks.com/ngfw/administration/monitoring/use-syslog-for-monitoring/configure-syslog-monitoring/configure-syslog-monitoring-pan-os) |
| The procedure ends with **Commit** | [Configure Syslog Monitoring (PAN-OS)](https://docs.paloaltonetworks.com/ngfw/administration/monitoring/use-syslog-for-monitoring/configure-syslog-monitoring/configure-syslog-monitoring-pan-os) — "Click Commit." |
| PAN-OS publishes **no test-log-message feature** for syslog server profiles: the documented verification is "To review the logs, refer to the documentation of your syslog management software" | Same page (verified by reading the procedure's final step) |
| "The firewall locally stores all log files and **automatically generates Configuration and System logs by default**" — so a config change/commit or an admin login produces fresh entries under **Monitor → Logs** | [PAN-OS Admin Guide — "Log Types and Severity Levels"](https://docs.paloaltonetworks.com/ngfw/administration/monitoring/view-and-manage-logs/log-types-and-severity-levels) |
| Troubleshooting CLI — connectivity: `ping host <IP>`, `traceroute host <IP>`, `show netstat numeric-host yes numeric-port yes all yes` piped to `match 514`; statistics: `debug log-receiver statistics`; process status pre-11.1 `debug syslog-ng status` / `debug syslog-ng stats`, 11.1+ `show system software status` piped to `match logrcvr`, plus `show syslog-ssl-conn-validation` and `show system state filter sw.logrcvr.syslog*`; 12.2.x (backported to 12.1.5) `debug log-receiver syslog-connections`; capture: `tcpdump filter "port 514" snaplen 0` and `scp export mgmt-pcap from mgmt.pcap to username@host:path` | [PAN KB — "How To Troubleshoot Connection Failures To Syslog Servers"](https://knowledgebase.paloaltonetworks.com/KCSArticleDetail?id=kA14u0000004NC4CAM) — **secondary** (vendor KB) |
| Panorama can forward the logs it collects to syslog itself: "Select **Panorama → Server Profiles → Syslog** and Add a new syslog server profile" (IP/FQDN, transport UDP/TCP/SSL, port, BSD/IETF). Syslog forwarding is enabled on an interface under **Panorama → Setup → Interfaces** (local Log Collectors) or **Panorama → Managed Collectors** (Dedicated Log Collectors), and "you can enable syslog forwarding on only a single interface" | [Panorama Admin Guide — "Configure Syslog Forwarding to External Destinations"](https://docs.paloaltonetworks.com/panorama/administration/manage-log-collection/configure-syslog-forwarding-to-external-destinations) |

### Explicit gaps (not guessed)

- **UNVERIFIED — syslog message format expected by the Fluency `PaloAlto_FWLog` parser.** PAN-OS
  offers **BSD** (RFC 3164) and **IETF** (RFC 5424) framing plus a Custom Log Format tab; no public
  Fluency documentation states which the parser consumes. The skill starts at the PAN-OS default
  (BSD), names IETF as the first thing to try if events land unparsed, and tells the operator to
  leave Custom Log Format alone.
- **UNVERIFIED — whether the Fluency `syslog_tls` listener requires a client certificate.** This
  matters because PAN-OS documents that, when the server uses client authentication, the firewall's
  and the server's certificates must be signed by the *same* CA — a constraint a customer cannot
  satisfy alone against a hosted endpoint. The skill instructs the operator to confirm with Fluency
  support before committing to the SSL path, rather than asserting either way.
- **PARTIALLY VERIFIED — Panorama push mechanics.** Panorama's *own* syslog forwarding is cited
  above. The split whereby the syslog server profile and Device → Log Settings are pushed from a
  **Template** while the Log Forwarding profile is pushed from a **Device Group** is stated in the
  Panorama administration guide's log-forwarding chapter, but that page would not render for
  automated retrieval at build time. The skill mentions the split as orientation and explicitly
  tells the operator to confirm it against the Panorama admin guide for the customer's version
  before executing.

## Fluency platform side (not vendor documentation)

The syslog transport mechanism is platform guidance from the Fluency team (2026-07-28), recorded
in `plans/connector-skills-rollout.md` (R1 resolution):

- `syslog_get_config` — read the site's syslog configuration.
- `syslog_register_config` — create it; **once per site, ever** — never when one exists.
- `syslog_update_config` — enable an additional listener (e.g. `syslog_tls`) on an existing
  configuration, leaving other listeners untouched.
- TLS-capable sources — which PAN-OS is, via its **SSL** transport — use the `syslog_tls` listener
  with the platform CA certificate:
  https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt
- Exact parameter shapes come from the live MCP tool schemas at runtime.

Connector template `PaloAlto_FWLog` ("PaloAlto Firewall Syslog", category `onpremise`,
resourceGroups `["PaloAlto"]`, **no parameters**) is from the live `list_connector_templates`
snapshot of 2026-07-23; re-fetch live at runtime. The datalake table is **not** defined by the
template — confirm with `list_data_tables`.
