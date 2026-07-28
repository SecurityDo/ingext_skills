# References — Cisco Meraki syslog vendor-side steps & platform transport

Verified 2026-07-28. Primary source page last updated by Meraki **Jul 6, 2026**.

## Cisco Meraki Dashboard side

| Claim in SKILL.md | Source |
|---|---|
| Menu path **Network-wide → Configure → General**; buttons **Add a syslog server** / **Update syslog servers**; enter server address + port and select roles; multiple syslog servers per network | [Cisco Meraki — Syslog Server Overview and Configuration → "Configure the Dashboard"](https://documentation.meraki.com/Platform_Management/Dashboard_Administration/Operate_and_Maintain/Monitoring_and_Reporting/Syslog_Server_Overview_and_Configuration) |
| In single-device-type networks (Appliance-only / Switch-only / Wireless-only) the section is labelled **Logging** instead of **Reporting** | Same page, "Configure the Dashboard" |
| **FQDN** server addresses supported beginning with **MX26.1** firmware | Same page, "Configure the Dashboard" + "Prerequisites" |
| Example configuration uses **UDP port 514** | Same page, "Configure a syslog server on Linux" (syslog-ng example) |
| Roles by product: **MX** sends Event Log, IDS Security Alerts, URLs, Flows; **MR** sends the same except IDS Security Alerts and adds **Air Marshal events**; **MS** supports **only Event Log** | Same page, "Types of syslog messages" |
| **Event log** role sends a copy of the messages under **Network-wide → Monitor → Event log** (the ground truth used in Verification) | Same page, "Appliance/Switch/Wireless Event Log" |
| **Flows** carry source, destination, ports and the matched firewall rule; **URLs** log every HTTP GET; **Security events** are the MX-only IDS role; **Air Marshal events** are MR-only | Same page, per-role sections with message samples |
| With **MX26.1**, `URLs` splits into **Appliance URLs** / **Wireless URLs** and `Flows` splits into **Appliance Flows** / **Wireless Flows**; existing configs get both halves selected | Same page, "Appliance/Wireless URLs" and "Appliance/Wireless Flows" |
| **TCP syslog (with or without TLS) requires MX26.1 and above**; encrypted syslog is supported **only on MX Security Appliances running MX26.1**; MS and MR "will support it in a future release"; **Z-series Teleworker Gateways do not support encrypted syslog** | Same page, "Prerequisites" and "Troubleshoot encrypted syslog connectivity" |
| TLS encryption over TCP is defined in **RFC 5425**; TLS is only supported over TCP; select TCP to expose the **Encrypted (TLS) syslog** checkbox | Same page, "Configure encrypted (TLS) syslog"; [RFC 5425](https://datatracker.ietf.org/doc/html/rfc5425) |
| On an encrypted entry configure **only** Appliance Event log / Appliance Flows / Appliance URLs; add a **separate** syslog server entry for Switch or Wireless roles | Same page, "Configure encrypted (TLS) syslog" |
| By default the MX authenticates the syslog server's certificate using the **Common CA Database (CCADB)**; to use your own CA bundle, upload it on **Organization → Certificates**, then use **Select a certificate** next to the **Enable** checkbox for **Encrypted (TLS) syslog**; if none is selected the entry falls back to CCADB | Same page, "Certificate authentication" |
| An MX configured for encrypted syslog and **downgraded below MX26.1 sends no syslog whatsoever** and must be reconfigured without encryption | Same page, "Troubleshoot encrypted syslog connectivity" |
| Encrypted syslog deployed in a **Configuration Template before 6 March 2026** did not work; fix is to delete and re-add the encrypted syslog server entry in the template | Same page, "Troubleshoot encrypted syslog connectivity" — also the confirmation that syslog server entries **can** live in a configuration template |
| Per-firewall-rule flow logging is toggled at **Security & SD-WAN → Configure → Firewall**, **Syslog** column (applies when the Appliance Flows role is on) | Same page, "Enable or disable per-rule flow logging" |
| Expected traffic flow: **LAN** → sources from the VLAN interface (or transit VLAN via static route); **WAN** → sources from the public interface; **AutoVPN** → sources from the highest VLAN participating in AutoVPN and is subject to **site-to-site outbound firewall rules** (allow rule at **Security & SD-WAN → Configure → Site-to-site VPN → Organization-wide settings → Add a rule**) | Same page, "Expected traffic flow" |
| Across a VPN the source IP is `6.X.X.X` when no VLANs are in VPN mode / MX in passthrough / MX in Routed-NAT single-LAN mode; with full-tunnel VPN use **VPN Full-Tunnel Exclusion** together with encrypted syslog | Same page, "Types of syslog messages" and "Expected traffic flow" |
| Syslog — **flows especially** — consumes large amounts of storage | Same page, "Prerequisites" and "Storage allocation" |
| Non-alphanumeric characters in device hostnames are replaced with underscores (expected behaviour, not corruption) | Same page, "Errant underscores" |
| Syslog is scoped **per network**; the Dashboard API models it as `PUT /networks/{networkId}/syslogServers` with a body of `servers: [{ host, port, roles }]` | [Meraki Dashboard API v1 — Update Network Syslog Servers](https://developer.cisco.com/meraki/api-v1/update-network-syslog-servers/) |
| API role strings (case-insensitive): `Wireless event log`, `Appliance event log`, `Switch event log`, `Air Marshal events`, `Flows`, `URLs`, `IDS alerts`, `Security events` | Same API reference |
| Current firmware version per network: **Organization → Monitor → Firmware upgrades** (*Schedule upgrades* tab, *Current firmware version* column), or per network at **Network-wide → Configure → General** under *Firmware upgrades* | [Cisco Meraki — Managing Firmware Upgrades](https://documentation.meraki.com/Platform_Management/Product_Information/Compatibility_and_Firmware/Firmware_Upgrades/Managing_Firmware_Upgrades) |
| Secondary corroboration of role coverage and the Network-wide → Configure → General path | [Cisco Meraki — Meraki Device Reporting: Syslog, SNMP, and API](https://documentation.meraki.com/Platform_Management/Dashboard_Administration/Operate_and_Maintain/Monitoring_and_Reporting/Meraki_Device_Reporting_-_Syslog,_SNMP,_and_API) — **secondary** (same vendor, older article; its text still describes TLS as "available at a future date", so the syslog article above supersedes it on transport) |

Notes:

- **Correction to a common assumption:** Meraki is *not* UDP-only. TCP and encrypted (TLS) syslog
  are documented for **MX Security Appliances on MX26.1+**. This skill therefore prefers TLS on
  qualifying MX hardware and falls back to UDP only where the documentation says TLS is
  unavailable (MS, MR, Z-series, pre-26.1 MX).
- **No test-message facility.** The Meraki syslog documentation describes no "send a test syslog"
  action. The skill states this as verified-by-absence and verifies against
  **Network-wide → Monitor → Event log** instead. If a future Dashboard release adds one, prefer
  the Dashboard over this file.
- **UNVERIFIED:** whether **MS switches / MR access points** can use plain **TCP** (without TLS).
  Meraki's documentation states the TCP prerequisite as an *MX26.1* firmware requirement and
  states the *encryption* limitation as MX-only, but does not say explicitly whether MS/MR accept
  a TCP-without-TLS server entry. The skill routes MS/MR to **UDP**, which is unambiguously
  supported. Confirm in the Dashboard against the live protocol selector before relying on TCP for
  switch or wireless roles.
- **UNVERIFIED:** the exact wording/label of the protocol selector control on the syslog server
  row. The documentation names the values (UDP / TCP) and the **Encrypted (TLS) syslog** checkbox,
  but does not label the selector itself; follow the live Dashboard.

## Fluency platform side (not vendor documentation)

The syslog transport mechanism is platform guidance from the Fluency team (2026-07-28), recorded
in `plans/connector-skills-rollout.md` (R1 resolution):

- `syslog_get_config` — read the site's syslog configuration.
- `syslog_register_config` — create it; **once per site, ever** — never when one exists.
- `syslog_update_config` — enable an additional listener (e.g. `syslog_tls`, `syslog_udp`) on an
  existing configuration, leaving other listeners untouched.
- TLS-capable sources use the `syslog_tls` listener with the platform CA certificate:
  https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt
- Exact parameter shapes come from the live MCP tool schemas at runtime.
- Connector template snapshot (2026-07-23): `CiscoMerakiFWLog`, displayName "Cisco Meraki Syslog",
  description "Cisco Meraki Router / Firewall Events via Syslog", category `onpremise`,
  resourceGroups `["CiscoMeraki"]`, parameters `datalake` (default `managed`) and `index` (default
  `Meraki`). Re-fetch with `list_connector_templates` at runtime — the snapshot is a hint, not
  truth.
