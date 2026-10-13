# References — rsyslog host-side steps & platform transport

Verified 2026-07-28.

## rsyslog / Red Hat host side

| Claim in SKILL.md and the script | Source |
|---|---|
| `omfwd` is the forwarding output module; supports UDP and TCP; `target` / `port` / `protocol` action parameters; modern `action(type="omfwd" …)` RainerScript form | [omfwd: syslog Forwarding Output Module — rsyslog documentation](https://rsyslog.readthedocs.io/en/latest/configuration/modules/omfwd.html); [Forwarding Logs — rsyslog documentation](https://rsyslog.readthedocs.io/en/latest/getting_started/forwarding_logs.html) |
| Legacy shorthand: `@host:port` = UDP, `@@host:port` = TCP (mentioned only as background; the skill writes the modern form) | [Your First Remote Log Server — rsyslog documentation](https://docs.rsyslog.com/doc/getting_started/beginner_tutorials/06-remote-server.html) |
| TLS forwarding: `global(DefaultNetstreamDriver="gtls" DefaultNetstreamDriverCAFile="…")` plus action parameters `StreamDriver="gtls"`, `StreamDriverMode="1"`, `StreamDriverAuthMode="x509/name"`, `StreamDriverPermittedPeers` | [Configuring a remote logging solution — RHEL 9 Security hardening, Red Hat](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/security_hardening/assembly_configuring-a-remote-logging-solution_security-hardening) (chapter "Configuring a remote logging solution"); rsyslog omfwd parameter docs (above) |
| `StreamDriverMode="1"` means TLS-only; `x509/name` checks the peer certificate name against `StreamDriverPermittedPeers` rather than accepting any CA-signed cert | rsyslog TLS documentation as summarised in the RHEL chapter above; corroborated by [GoLinuxCloud — secure remote logging with rsyslog TLS](https://www.golinuxcloud.com/secure-remote-logging-rsyslog-tls-certificate/) — **secondary** |
| TLS requires the GnuTLS stream driver, packaged as `rsyslog-gnutls` on RHEL-family distros | RHEL 9 remote-logging chapter (above); corroborated by the GoLinuxCloud guide — **secondary** |
| Action queue parameters for resilience (`queue.type`, `queue.filename`, `queue.maxDiskSpace`, `queue.saveOnShutdown`, `action.resumeRetryCount`) and the purpose of an action queue (avoid message loss when the server is unavailable) | [Configuring a remote logging solution — RHEL 9, Red Hat](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/security_hardening/assembly_configuring-a-remote-logging-solution_security-hardening) |
| Client config belongs in `/etc/rsyslog.d/*.conf`; main config `/etc/rsyslog.conf` | RHEL 9 remote-logging chapter (above); [Configuring logging — RHEL 8, Red Hat](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/8/html/configuring_basic_system_settings/configuring-logging_configuring-basic-system-settings) |
| `rsyslogd -N1` performs a config validation run without starting the service | [Troubleshooting problems — rsyslog documentation](https://docs.rsyslog.com/doc/troubleshooting/troubleshoot.html) |
| A non-514 syslog port must be registered with SELinux: `semanage port -a -t syslogd_port_t -p {tcp,udp} <port>`; `semanage` comes from `policycoreutils-python-utils` | [syslogd_selinux(8) man page](https://linux.die.net/man/8/syslogd_selinux); [Configuring rsyslog on a logging server — Red Hat](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/6/html/deployment_guide/s1-configuring_rsyslog_on_a_logging_server); corroborated by [Logz.io — troubleshooting rsyslog SELinux](https://docs.logz.io/docs/log-management/troubleshooting/troubleshooting-rsyslog-selinux/) — **secondary** |

Notes and deliberate non-claims:

- `docs.redhat.com` returns HTTP 403 to automated fetches, so the RHEL chapters above were read
  through search-engine extracts of their content rather than fetched directly. The parameter
  names and config shapes are additionally corroborated by the rsyslog project documentation and
  the secondary guides listed. Treat the RHEL chapter as the authority if they ever disagree.
- **No claim is made about what a given host's `/etc/rsyslog.conf` already contains** (imjournal,
  existing forwards, `stop` rules). The skill instructs reading the host's real config instead —
  the host is present, so ground truth beats documentation.
- The `10-` filename prefix is a deliberate ordering choice explained in the skill (register the
  forward action before any later rule that could `stop` processing), not a vendor-documented
  convention.
- FIPS-mode hosts: RHEL 9.2+ with FIPS enabled constrains TLS (EMS extension / TLS 1.3). Noted
  here rather than in the skill because it was not verified end-to-end for this integration; if a
  FIPS host fails the TLS handshake, this is the first thing to check.

## Fluency platform side (not vendor documentation)

Platform guidance from the Fluency team (2026-07-28), recorded in
`plans/connector-skills-rollout.md` (R1 resolution):

- `syslog_get_config` — read the site's syslog configuration.
- `syslog_register_config` — create it; **once per site, ever** — never when one exists.
- `syslog_update_config` — enable an additional listener on an existing configuration, leaving
  other listeners untouched.
- Platform CA certificate for TLS listeners:
  https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt
- Exact parameter shapes come from the live MCP tool schemas at runtime.

### What that CA file contains (inspected 2026-07-28)

Downloaded and inspected directly with `openssl x509`: a 5888-byte PEM bundle of **five
self-signed public roots** —

| Subject |
|---|
| `C=US, O=Amazon, CN=Amazon Root CA 1` |
| `C=US, O=Amazon, CN=Amazon Root CA 2` |
| `C=US, O=Amazon, CN=Amazon Root CA 3` |
| `C=US, O=Amazon, CN=Amazon Root CA 4` |
| `C=US, ST=Arizona, L=Scottsdale, O=Starfield Technologies, Inc., CN=Starfield Services Root Certificate Authority - G2` |

These are the Amazon Trust Services roots used by AWS-issued (ACM) certificates. Therefore:

- the syslog TLS endpoint presents a **publicly trusted** certificate — a current
  `ca-certificates` package already trusts it, so TLS does not depend on shipping this file;
- pointing rsyslog at this bundle **pins trust to the Amazon roots only**, which is narrower than
  the system store — the reason the skill installs it by default;
- it is a **server-trust** bundle, not a client certificate; nothing here enables mutual TLS.

This is an observed property of the file, not a documented Fluency statement — re-inspect if the
platform ever re-issues its endpoint certificate from a private CA.
