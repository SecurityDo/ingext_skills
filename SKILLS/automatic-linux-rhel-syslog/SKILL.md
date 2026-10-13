---
name: automatic-linux-rhel-syslog
version: 1.0.0
description: >-
  Automatic variant for importing Red Hat Enterprise Linux (and Rocky / Alma / CentOS / Fedora)
  host logs into Fluency / Ingext via syslog. The agent performs the whole Fluency side — it
  resolves the site's syslog endpoint via the syslog MCP calls (syslog_get_config,
  syslog_register_config once per site, syslog_update_config to enable the listener the host will
  use) and installs the "Linux (RHEL) Syslog" connector (LinuxRHELSyslog) — and, unlike the
  portal-only firewall syslog skills, it can also perform the HOST side: MODE A — the operator
  gives it root/sudo on this machine or an SSH-reachable host, so it runs a bundled idempotent
  script that writes an rsyslog drop-in (TLS preferred, with the platform CA certificate), handles
  SELinux for non-514 ports, VALIDATES the config before restarting, and restarts rsyslog; MODE B
  — a fallback that hands a Linux admin the same script or the equivalent manual rsyslog steps.
  SELF-CONTAINED: it ends by creating the connector itself — when routed from customer-onboarding,
  do NOT chain into add-connector afterward. Triggers: "forward our Linux server logs to Ingext",
  "set up rsyslog forwarding to Fluency", "get RHEL syslog into the datalake", "configure rsyslog
  on these hosts for Ingext". Do NOT use for network appliances that emit syslog (FortiGate, Palo
  Alto, Meraki, Cisco ASA, SonicWall, Check Point, Sophos, Peplink — each has its own skill), and
  not for Windows hosts (that would be the NXLog path, which has no skill yet — route to
  add-connector).
---

# Set up Linux (RHEL) syslog forwarding — automatically (rsyslog)

Import a **Red Hat–family Linux host's** logs — authentication, sudo, systemd units, kernel,
anything rsyslog sees — into Fluency / Ingext via **syslog**. Three pieces, and unlike the
appliance syslog skills, the agent can do **all three**:

- **Site syslog transport (yours):** the platform's syslog endpoint for this site — domain, port,
  protocol — via the `syslog_*` MCP calls. Created **once per site**, then shared by every syslog
  integration that follows.
- **Fluency connector (yours):** install **`LinuxRHELSyslog`** ("Linux (RHEL) Syslog"), which
  parses the stream. The template takes no parameters.
- **Host side (yours in Mode A):** an rsyslog drop-in that forwards to that endpoint. rsyslog
  supports **UDP, TCP, and TLS**, so unlike most appliances this integration can and should be
  encrypted — the platform CA certificate is genuinely used here.

Host-side steps are backed by Red Hat and rsyslog documentation; citations live in
`assets/references.md`.

> **Scope: one host per run.** The bundled script configures the host it runs on. A fleet of
> dozens is a **configuration-management** job — see
> [Fleets](#fleets--dont-hand-configure-fifty-hosts) before starting down a per-host path.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Ingext | Site syslog endpoint | Via `syslog_register_config` — **only if the site has none yet**; otherwise reused. Enable the listener the host will use (`syslog_tls` preferred) with `syslog_update_config` if missing |
| Ingext | Connector | Template **`LinuxRHELSyslog`** ("Linux (RHEL) Syslog"), instance e.g. `linuxrhelsyslog`, no parameters |
| Host | rsyslog drop-in | `/etc/rsyslog.d/10-ingext-forward.conf` — an `omfwd` action to the endpoint. Numbered `10-` so it registers before any later rule that might `stop` processing |
| Host | CA certificate (TLS only) | `/etc/pki/rsyslog/ingext-ca.crt` — the platform CA, from https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt |
| Host | SELinux port registration | Only when the port isn't 514: `semanage port -a -t syslogd_port_t …` |

Nothing here is billable on either side.

---

## Prerequisites

- **rsyslog installed and running** on the host (the default on RHEL 8/9 and rebuilds). Check with
  `systemctl is-active rsyslog`.
- **root or sudo** on the target host — this is the Mode A equivalent of the cloud skills'
  interactive sign-in. Without it, Mode B.
- For **TLS**: the `rsyslog-gnutls` package on the host (ships the `gtls` stream driver). The
  script checks for it and tells you to install it; it does not install packages itself.
- **Outbound reachability** from the host to the endpoint on the chosen port.
- The **Fluency Ingext MCP** connected, including the `syslog_*` tools (re-authenticate the MCP if
  they aren't listed). Without it, read the endpoint from the platform UI and install there.

---

## Pick a mode

**Ask who is at the keyboard and what the agent may touch** (use `AskUserQuestion` if unclear):

- **Mode A — "run it on this host / this host I'll give you access to."** The agent runs the
  bundled script with sudo, here or over SSH against a host the operator names. This is the
  primary path.
- **Mode B — "our Linux admin will apply it"** (their servers, no access, or change-control
  requires it). The agent does the Fluency side and hands over the script or the manual steps.

> **Why the distinction matters here is different from the cloud skills.** There, the blocker was
> credentials. Here it's **blast radius**: a bad rsyslog config can stop a production host logging
> altogether. The script validates with `rsyslogd -N1` and restores the previous state rather than
> restarting on a broken config — but the host still belongs to the customer, and change control
> may reasonably own the change. Don't push for sudo on production hosts; offer Mode B freely.

---

## Step 1 — Resolve the site's syslog transport (yours)

The syslog endpoint is **site-level, not per-integration**. Use the live MCP tool schemas at
runtime — the shapes below describe intent, not exact parameters.

1. **`syslog_get_config`** — read the site's existing syslog configuration.
2. **No configuration at all** → **`syslog_register_config`** to create it. This is a
   **once-per-site** action: never register when a configuration already exists, and never
   re-register to "fix" one — that's what update is for.
3. **Configuration exists but lacks the listener you want** → **`syslog_update_config`** to enable
   it. Leave existing listeners untouched; other devices depend on them.
4. **Prefer TLS.** rsyslog speaks TLS natively, so unlike Peplink or Meraki there is no reason to
   settle for cleartext. Drive `syslog_tls` unless the customer has a specific reason not to
   (an ancient rsyslog build, or a policy that forbids the extra package).
5. **Capture the deliverables:** endpoint **domain**, **port**, **protocol**. These become the
   script's `--endpoint`, `--port`, `--protocol`.

### What the platform CA file actually is

**https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt** is a PEM bundle of **five
public root CAs** — Amazon Root CA 1–4 and Starfield Services Root CA G2 — i.e. the Amazon Trust
Services roots behind AWS-issued certificates. Two consequences worth knowing before you touch a
host:

- **The endpoint certificate is publicly trusted.** Any host with a current `ca-certificates`
  package already trusts it, so `DefaultNetstreamDriverCAFile` could equally point at
  `/etc/pki/tls/certs/ca-bundle.crt`. TLS is not gated on getting this file onto the box.
- **Pinning to this bundle is the better default anyway.** The script installs it and points
  rsyslog at it so the forwarder trusts *only* the Amazon roots, rather than every CA in the
  system store. That is a narrower trust boundary, which is why it's the default here — not
  because a private CA must be imported.
- **It is not a client certificate.** It authenticates the server to the host, one-way. Nothing
  in this integration presents a client certificate.

The script downloads it automatically, accepts a local copy via `--ca-source`, and reuses an
existing copy if one is already in place.

---

## Step 2 — Install the connector (yours)

1. **`list_connector_templates`** — locate the live **`LinuxRHELSyslog`** template ("Linux (RHEL)
   Syslog") and use its current schema; in the 2026-07 snapshot it has **no parameters**, but the
   live template is the truth.
2. **`list_connectors`** — if a LinuxRHELSyslog instance already exists, the site is already
   ingesting Linux syslog; additional hosts just point at the same endpoint and share it. Only add
   a second instance deliberately.
3. **`create_connector`** with:
   - `application`: `LinuxRHELSyslog`
   - `instance`: `linuxrhelsyslog` (lowercase, ≤20 chars, **never `"default"`**; `-2` on collision)
   - `displayName`: `Linux (RHEL) Syslog`
   - `inputParameters`: every parameter the live template defines (none, per the snapshot).
4. Confirm the instance exists and reports healthy (`list_connectors` / `get_connector`).

**Without the MCP:** walk the operator through the Fluency UI — Connectors → Add → **Linux (RHEL)
Syslog** — and read the syslog endpoint from the platform's Connectors page.

---

## Step 3 — Configure the host

### Before you write anything: read the host's actual rsyslog setup

Don't assume — the host is right there, so look:

```bash
systemctl is-active rsyslog          # is it even running?
rsyslogd -v                          # version
ls /etc/rsyslog.d/                   # existing drop-ins — anything with `stop` can swallow messages
grep -rn "omfwd\|@@\|^\*\.\*" /etc/rsyslog.conf /etc/rsyslog.d/  # is it already forwarding somewhere?
```

If the host already forwards to another collector, **say so before changing anything** — adding a
second destination is fine (rsyslog happily fans out), but the customer should know.

### Choose the selector — how much to send

The script defaults to `*.*` (everything rsyslog sees). That is the safe default for security
monitoring and the noisiest one. Discuss it:

- `*.*` — everything. Best coverage; highest volume.
- `authpriv.*;auth.*` — authentication and sudo only. Small, high-signal.
- `*.info;mail.none;authpriv.none;cron.none` — the classic "general messages" shape.

Volume is a real cost consideration on the datalake side; pick deliberately rather than by
default.

### Mode A — the agent runs it

```bash
# TLS (preferred)
sudo bash ${SKILL_DIR}/assets/setup-ingext-rsyslog.sh \
  --endpoint <domain> --port <port> --protocol tls

# plain TCP / UDP
sudo bash ${SKILL_DIR}/assets/setup-ingext-rsyslog.sh \
  --endpoint <domain> --port <port> --protocol tcp

# narrower selector, disk-assisted queue, non-interactive
sudo bash ${SKILL_DIR}/assets/setup-ingext-rsyslog.sh \
  --endpoint <domain> --port 6514 --protocol tls --selector 'authpriv.*;*.info' --disk-queue --yes
```

**Preview first on anything production-like:** `--dry-run` prints the exact drop-in and changes
nothing (it needs no root and works even where rsyslog isn't installed).

The script **stops for a confirmation prompt** naming the host and endpoint unless run with
`--yes`. Surface that prompt; only pass `--yes` when the operator has explicitly approved the
host.

What it does, in order: preflight (root, rsyslog present, `gtls` driver if TLS) → show host +
endpoint and confirm → install the CA certificate (TLS) → back up any existing drop-in and write
`/etc/rsyslog.d/10-ingext-forward.conf` → register the port with SELinux if it isn't 514 →
**validate with `rsyslogd -N1`** → restart rsyslog and confirm it came back active → print one
JSON object to stdout (progress on stderr).

> **The validation step is the safety property.** If the config doesn't validate, or rsyslog
> doesn't come back active, the script **restores the previous state and exits non-zero** — it
> never leaves a host unable to log. Report that outcome honestly rather than retrying blindly.

**Over SSH**, the same script applies — copy it to the host and run it there, e.g.
`scp assets/setup-ingext-rsyslog.sh host:/tmp/ && ssh -t host 'sudo bash /tmp/setup-ingext-rsyslog.sh --endpoint … --port … --protocol tls'`.
Confirm with the operator which hosts are in scope before touching any of them.

### Mode B — hand it to the Linux admin

Give them `${SKILL_DIR}/assets/setup-ingext-rsyslog.sh` with the endpoint/port/protocol filled in,
or the manual equivalent. Manual TLS setup:

1. `dnf install rsyslog-gnutls` (and `policycoreutils-python-utils` if `semanage` is missing).
2. Install the CA certificate:
   ```bash
   sudo mkdir -p /etc/pki/rsyslog
   sudo curl -fsSL https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt \
     -o /etc/pki/rsyslog/ingext-ca.crt
   ```
3. Create `/etc/rsyslog.d/10-ingext-forward.conf`:
   ```
   global(
     DefaultNetstreamDriver="gtls"
     DefaultNetstreamDriverCAFile="/etc/pki/rsyslog/ingext-ca.crt"
   )

   *.* action(
     type="omfwd"
     target="<endpoint domain>"
     port="<port>"
     protocol="tcp"
     StreamDriver="gtls"
     StreamDriverMode="1"
     StreamDriverAuthMode="x509/name"
     StreamDriverPermittedPeers="<endpoint domain>"
     queue.type="LinkedList"
     action.resumeRetryCount="-1"
   )
   ```
   For plain TCP or UDP, drop the `global()` block and the four `StreamDriver*` parameters, and
   set `protocol="tcp"` or `protocol="udp"`.
4. If the port isn't 514: `sudo semanage port -a -t syslogd_port_t -p tcp <port>`
5. **Validate, then restart:** `sudo rsyslogd -N1 && sudo systemctl restart rsyslog`
6. Test: `logger -p authpriv.notice 'ingext syslog test'`

### Fleets — don't hand-configure fifty hosts

For more than a handful of hosts, the deliverable is the **drop-in file**, not fifty SSH sessions.
Generate it once (`--dry-run` prints exactly what to ship) and hand it to whatever the customer
already uses — Ansible, Puppet, Chef, Salt, a golden image, or a package. Say this out loud rather
than quietly looping; it is the difference between a five-minute rollout and an afternoon.

---

## When called from `customer-onboarding`

- **This skill is the complete stage — transport + connector included.** Do **not** hand off to
  `add-connector`; finish Steps 1–2 before returning.
- **Don't re-collect** what the router already established (connected instance, existing
  connectors from its `list_connectors` call).
- **Hand back** for the checklist: the connector `instance` id, the datalake table (confirm the
  live name with `list_data_tables` — the template defines no index), the endpoint
  domain/port/protocol, **which hosts were actually configured**, and whether a fleet rollout is
  still outstanding. None of these are credentials.
- **Latency expectation:** syslog is near-real-time — a `logger` test message should appear within
  a minute or two. Unlike the appliance skills there's no "quiet device" excuse: you can generate
  an event on demand, so **verify properly instead of marking ⏳**. Mark ⏳ only when hosts remain
  unconfigured (a fleet rollout in progress); ❌ if a configured host's test message never lands.

---

## Output — the deliverable

Report human-readably plus a JSON block a calling task can parse (nothing here is secret):

```json
{
  "connector": "LinuxRHELSyslog",
  "instance": "linuxrhelsyslog",
  "table": "<confirm live with list_data_tables>",
  "syslogEndpoint": "<domain>",
  "syslogPort": "<port>",
  "protocol": "tls",
  "hostsConfigured": ["host1.example.com"],
  "selector": "*.*",
  "fleetRolloutOutstanding": false
}
```

---

## Verification

1. `list_connectors` / `get_connector` — instance present, no error state.
2. **Generate a test event on the host** — this is the advantage of a Linux source over an
   appliance:
   ```bash
   logger -p authpriv.notice "ingext syslog test $(date +%s)"
   ```
3. **Check the host actually sent it.** `journalctl -u rsyslog --since '5 min ago'` shows rsyslog's
   own complaints (TLS handshake failures, connection refused, name resolution). For TLS/TCP,
   `ss -tnp | grep rsyslog` should show an established connection to the endpoint.
4. Count rows in the Linux table over the last hour via the **`ingext-kql`** skill (confirm the
   live table name with `list_data_tables` first), and look for the unique string from step 2.
5. **Honest latency:** seconds to a couple of minutes. If the test message doesn't land, it is a
   real failure — go to Failure modes rather than waiting.

---

## Failure modes

| Situation | Response |
|---|---|
| Script exits "config validation FAILED" | Working as designed — nothing was restarted and the previous drop-in is restored. The host is still logging. Read the `rsyslogd -N1` output it printed; usually a typo in the endpoint or a `global()` conflict (below). |
| `global()` conflict / "DefaultNetstreamDriver already set" | Another drop-in already configures a netstream driver. Don't fight it: reuse the existing driver/CA settings and put only the `action()` in the Ingext drop-in. |
| rsyslog restarts but nothing arrives (UDP) | UDP drops silently. Check the endpoint and port, then SELinux (non-514 ports need `semanage port -a -t syslogd_port_t -p udp <port>`), then egress firewall. Prefer switching to TLS/TCP, which fails loudly. |
| TLS handshake failures in `journalctl -u rsyslog` | Check `StreamDriverPermittedPeers` first — it must match the name on the endpoint's certificate, so an alias or a bare IP will fail the `x509/name` check even though the CA is fine. If the CA file is suspect, remember the endpoint cert is publicly trusted: temporarily pointing `DefaultNetstreamDriverCAFile` at `/etc/pki/tls/certs/ca-bundle.crt` isolates "bad CA file" from "wrong peer name". |
| "could not load module lmnsd_gtls" | `rsyslog-gnutls` isn't installed. `dnf install rsyslog-gnutls`, then restart rsyslog. |
| `semanage: command not found` | `dnf install policycoreutils-python-utils`, then register the port. The script warns and continues rather than failing here. |
| Site syslog config exists with only the wrong listener | `syslog_update_config` to add the one the host needs — do **not** re-register the site config, and leave other listeners alone. |
| No site syslog config at all | `syslog_register_config` — once per site. Always `syslog_get_config` first. |
| `syslog_*` tools not visible on the MCP | The MCP session may need re-authentication — reconnect, or read the endpoint from the platform UI's Connectors page. |
| Host was already forwarding elsewhere | Expected in some shops; rsyslog fans out to multiple destinations fine. Tell the customer rather than silently adding a second stream. |
| Volume higher than expected | The `*.*` selector sends everything. Narrow it (`authpriv.*`, `*.info` with exclusions) and re-run — the script is idempotent. |
| Messages lost during an endpoint outage | The default queue is in-memory and bounded. Re-run with `--disk-queue` for a disk-assisted queue that survives restarts (needs rsyslog's work directory, normally `/var/lib/rsyslog`). |

---

## Security notes

- **Prefer TLS here — the host can do it.** UDP and plain TCP syslog cross the network in
  cleartext and unauthenticated; a Linux host's logs include authentication activity, sudo usage,
  and usernames. This is the one syslog skill where encryption costs a single package.
- `StreamDriverMode="1"` makes the action TLS-only (no silent downgrade to cleartext), and
  `StreamDriverAuthMode="x509/name"` verifies the endpoint's certificate name rather than
  accepting anything the CA signed. Don't relax either to "make it work" — fix the name mismatch.
- The drop-in and the CA certificate are world-readable (`0644`) by design; neither is a secret.
  There is no credential in this integration at all.
- **Blast radius:** editing rsyslog config on a production host can stop it logging. The script's
  validate-then-restart-else-restore behavior is the mitigation; keep it, and prefer `--dry-run`
  plus change control on anything critical.
- Forwarding is additive — it does not stop the host writing its own local logs.

---

## Layout

```
automatic-linux-rhel-syslog/
├── SKILL.md
├── assets/
│   ├── setup-ingext-rsyslog.sh   ← writes the drop-in, handles SELinux + CA, validates, restarts
│   └── references.md             ← Red Hat / rsyslog citations; platform syslog-transport notes
└── evals/
    └── evals.json                ← trigger phrases for skill selection
```
