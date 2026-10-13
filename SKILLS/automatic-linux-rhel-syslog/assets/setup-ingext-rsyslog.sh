#!/usr/bin/env bash
#
# setup-ingext-rsyslog.sh — configure rsyslog on a RHEL-family host to forward its logs to
# the Fluency / Ingext syslog endpoint.
#
# This is the Linux counterpart of setup-ingext-eventhub.sh (Azure) / setup-ingext-guardduty.sh
# (AWS). It is idempotent: re-running rewrites the same drop-in file and restarts rsyslog, so a
# second run against the same endpoint is a no-op in effect.
#
# What it does, in order:
#   preflight (root/sudo, rsyslog installed, TLS deps if --protocol tls)
#   → show the target host + endpoint + protocol and STOP for confirmation (unless --yes)
#   → for TLS: install the CA certificate to --ca-file (downloaded, or supplied with --ca-source)
#   → back up any existing drop-in, then write /etc/rsyslog.d/10-ingext-forward.conf
#   → SELinux: register a non-514 port under syslogd_port_t if needed
#   → VALIDATE the whole rsyslog config (rsyslogd -N1) — refuses to restart if it fails
#   → restart rsyslog and confirm the unit is active
#   → print ONE JSON object to stdout
#
# WHY THE VALIDATION MATTERS: a syntactically broken rsyslog config can leave the host unable to
# log at all. This script never restarts rsyslog on a config that does not validate, and it
# restores the previous drop-in (or removes the one it added) if validation fails.
#
# The drop-in is named 10- so the forward action is registered EARLY — before any later rule in
# /etc/rsyslog.d/ that might discard messages with `stop`. Inspect the host's existing drop-ins
# if messages seem to go missing.
#
# On success stdout carries only:
#   { "host", "endpoint", "port", "protocol", "selector", "configFile", "caFile", "rsyslogStatus" }
# All progress goes to stderr.
#
# PREREQUISITES
#   - root, or a sudo-capable user (run under sudo).
#   - rsyslog installed and enabled (RHEL/Rocky/Alma/CentOS 8+; also fine on Fedora).
#   - For --protocol tls: the rsyslog-gnutls package (the script checks and tells you to install
#     it; it does not install packages itself).
#
# ABOUT THE CA FILE: the bundle at --ca-url is five PUBLIC roots (Amazon Root CA 1-4 + Starfield
# Services Root CA G2), i.e. the Amazon Trust Services roots behind AWS-issued certificates. The
# endpoint certificate is therefore publicly trusted and the system CA bundle would also work.
# Pointing rsyslog at this file instead PINS trust to the Amazon roots only - narrower than the
# system store, which is why it is the default here. It is server-trust only, not a client cert.
#   - Outbound reachability from this host to the endpoint on the chosen port.
#
# USAGE
#   sudo ./setup-ingext-rsyslog.sh --endpoint syslog.example.com --port 6514 --protocol tls
#   sudo ./setup-ingext-rsyslog.sh --endpoint syslog.example.com --port 514  --protocol udp
#   sudo ./setup-ingext-rsyslog.sh --endpoint h --port 1514 --protocol tcp --selector 'authpriv.*;*.info'
#   sudo ./setup-ingext-rsyslog.sh --endpoint h --port 6514 --protocol tls --disk-queue --yes
#   ./setup-ingext-rsyslog.sh --endpoint h --port 514 --protocol udp --dry-run   # print, change nothing

set -euo pipefail

ENDPOINT=""
PORT=""
PROTOCOL="tcp"
SELECTOR="*.*"
CA_URL="https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt"
CA_SOURCE=""
CA_FILE="/etc/pki/rsyslog/ingext-ca.crt"
CONF_FILE="/etc/rsyslog.d/10-ingext-forward.conf"
DISK_QUEUE=0
ASSUME_YES=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --endpoint)   ENDPOINT="$2"; shift 2 ;;
    --port)       PORT="$2"; shift 2 ;;
    --protocol)   PROTOCOL="$2"; shift 2 ;;
    --selector)   SELECTOR="$2"; shift 2 ;;
    --ca-source)  CA_SOURCE="$2"; shift 2 ;;
    --ca-file)    CA_FILE="$2"; shift 2 ;;
    --conf-file)  CONF_FILE="$2"; shift 2 ;;
    --disk-queue) DISK_QUEUE=1; shift ;;
    --yes|-y)     ASSUME_YES=1; shift ;;
    --dry-run)    DRY_RUN=1; shift ;;
    -h|--help)    grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

log() { printf '%s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

[[ -n "$ENDPOINT" ]] || die "--endpoint is required (the Fluency syslog endpoint domain)."
[[ -n "$PORT"     ]] || die "--port is required (the listener port from the site syslog config)."
case "$PROTOCOL" in udp|tcp|tls) ;; *) die "--protocol must be udp, tcp, or tls (got '$PROTOCOL')." ;; esac

# --- Preflight ---------------------------------------------------------------------
if [[ $DRY_RUN -eq 0 && "$(id -u)" -ne 0 ]]; then
  die "must run as root (use sudo). Re-run with --dry-run to preview without root."
fi

if ! command -v rsyslogd >/dev/null 2>&1; then
  if [[ $DRY_RUN -eq 1 ]]; then
    log "NOTE: rsyslogd not found on this machine (dry run — previewing anyway)."
  else
    die "rsyslogd not found. Install rsyslog first (dnf install rsyslog)."
  fi
fi

if [[ "$PROTOCOL" == "tls" ]]; then
  # rsyslog's GnuTLS network stream driver ships separately on RHEL-family distros.
  if ! find /usr/lib64/rsyslog /usr/lib/rsyslog -name 'lmnsd_gtls.so' 2>/dev/null | grep -q .; then
    if [[ $DRY_RUN -eq 1 ]]; then
      log "NOTE: the gtls stream driver is not present here (dry run). The target host will need:"
      log "      dnf install rsyslog-gnutls"
    else
      die "TLS requested but the gtls network stream driver was not found. Install it: dnf install rsyslog-gnutls"
    fi
  fi
fi

HOSTNAME_FQDN="$(hostname -f 2>/dev/null || hostname)"

log "Target host : ${HOSTNAME_FQDN}"
log "Endpoint    : ${ENDPOINT}:${PORT} (${PROTOCOL})"
log "Selector    : ${SELECTOR}"
log "Config file : ${CONF_FILE}"
[[ "$PROTOCOL" == "tls" ]] && log "CA file     : ${CA_FILE}"
log ""

# --- Build the drop-in content -----------------------------------------------------
QUEUE_PARAMS='  queue.type="LinkedList"
  action.resumeRetryCount="-1"
  action.resumeInterval="30"'

if [[ $DISK_QUEUE -eq 1 ]]; then
  WORKDIR="/var/lib/rsyslog"
  if [[ -d "$WORKDIR" ]]; then
    QUEUE_PARAMS='  queue.type="LinkedList"
  queue.filename="ingext-fwd"
  queue.maxDiskSpace="1g"
  queue.saveOnShutdown="on"
  action.resumeRetryCount="-1"
  action.resumeInterval="30"'
  else
    log "WARNING: --disk-queue requested but ${WORKDIR} does not exist; falling back to an"
    log "         in-memory queue. Set a global workDirectory in rsyslog.conf to enable disk queues."
  fi
fi

if [[ "$PROTOCOL" == "tls" ]]; then
  CONF_CONTENT="# Managed by Fluency / Ingext — setup-ingext-rsyslog.sh
# Forwards this host's logs to the Ingext syslog endpoint over TLS.
global(
  DefaultNetstreamDriver=\"gtls\"
  DefaultNetstreamDriverCAFile=\"${CA_FILE}\"
)

${SELECTOR} action(
  type=\"omfwd\"
  target=\"${ENDPOINT}\"
  port=\"${PORT}\"
  protocol=\"tcp\"
  StreamDriver=\"gtls\"
  StreamDriverMode=\"1\"
  StreamDriverAuthMode=\"x509/name\"
  StreamDriverPermittedPeers=\"${ENDPOINT}\"
${QUEUE_PARAMS}
)"
else
  CONF_CONTENT="# Managed by Fluency / Ingext — setup-ingext-rsyslog.sh
# Forwards this host's logs to the Ingext syslog endpoint over ${PROTOCOL^^}.
${SELECTOR} action(
  type=\"omfwd\"
  target=\"${ENDPOINT}\"
  port=\"${PORT}\"
  protocol=\"${PROTOCOL}\"
${QUEUE_PARAMS}
)"
fi

if [[ $DRY_RUN -eq 1 ]]; then
  log "--- ${CONF_FILE} (dry run, nothing written) ---"
  printf '%s\n' "$CONF_CONTENT" >&2
  log "--- end ---"
  exit 0
fi

# --- Confirm -----------------------------------------------------------------------
if [[ $ASSUME_YES -eq 0 ]]; then
  printf 'Write this forwarding config and restart rsyslog on %s? [y/N] ' "$HOSTNAME_FQDN" >&2
  read -r reply < /dev/tty || reply=""
  case "$reply" in y|Y|yes|YES) ;; *) die "aborted by operator." ;; esac
fi

# --- TLS: install the CA certificate ------------------------------------------------
if [[ "$PROTOCOL" == "tls" ]]; then
  mkdir -p "$(dirname "$CA_FILE")"
  if [[ -n "$CA_SOURCE" ]]; then
    log "Installing CA certificate from ${CA_SOURCE} ..."
    cp -f "$CA_SOURCE" "$CA_FILE"
  elif [[ -s "$CA_FILE" ]]; then
    log "CA certificate already present at ${CA_FILE} — reusing."
  else
    log "Downloading CA certificate from ${CA_URL} ..."
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL "$CA_URL" -o "$CA_FILE" || die "failed to download the CA certificate. Fetch it manually and pass --ca-source."
    elif command -v wget >/dev/null 2>&1; then
      wget -qO "$CA_FILE" "$CA_URL" || die "failed to download the CA certificate. Fetch it manually and pass --ca-source."
    else
      die "neither curl nor wget available. Fetch ${CA_URL} manually and pass --ca-source <path>."
    fi
  fi
  chmod 0644 "$CA_FILE"
  grep -q 'BEGIN CERTIFICATE' "$CA_FILE" || die "${CA_FILE} does not look like a PEM certificate."
fi

# --- Back up and write --------------------------------------------------------------
BACKUP=""
if [[ -f "$CONF_FILE" ]]; then
  BACKUP="${CONF_FILE}.bak.$(date +%Y%m%d%H%M%S)"
  cp -p "$CONF_FILE" "$BACKUP"
  log "Existing config backed up to ${BACKUP}"
fi

printf '%s\n' "$CONF_CONTENT" > "$CONF_FILE"
chmod 0644 "$CONF_FILE"
log "Wrote ${CONF_FILE}"

restore() {
  if [[ -n "$BACKUP" ]]; then cp -p "$BACKUP" "$CONF_FILE"; log "Restored previous config from ${BACKUP}"
  else rm -f "$CONF_FILE"; log "Removed ${CONF_FILE}"; fi
}

# --- SELinux: allow a non-standard syslog port --------------------------------------
if [[ "$PORT" != "514" ]] && command -v getenforce >/dev/null 2>&1 && [[ "$(getenforce)" != "Disabled" ]]; then
  SEL_PROTO="tcp"; [[ "$PROTOCOL" == "udp" ]] && SEL_PROTO="udp"
  if command -v semanage >/dev/null 2>&1; then
    if semanage port -l 2>/dev/null | awk '/^syslogd_port_t/' | grep -qw "$PORT"; then
      log "SELinux: port ${PORT}/${SEL_PROTO} already allowed for syslogd."
    else
      log "SELinux: registering ${PORT}/${SEL_PROTO} under syslogd_port_t ..."
      semanage port -a -t syslogd_port_t -p "$SEL_PROTO" "$PORT" 2>/dev/null \
        || semanage port -m -t syslogd_port_t -p "$SEL_PROTO" "$PORT" 2>/dev/null \
        || log "WARNING: could not register the port with SELinux. If messages do not arrive, run:
         semanage port -a -t syslogd_port_t -p ${SEL_PROTO} ${PORT}"
    fi
  else
    log "WARNING: SELinux is enabled but 'semanage' is missing (dnf install policycoreutils-python-utils)."
    log "         A non-514 port may be blocked. Install it and run:"
    log "         semanage port -a -t syslogd_port_t -p ${SEL_PROTO} ${PORT}"
  fi
fi

# --- Validate BEFORE restarting -----------------------------------------------------
log "Validating rsyslog configuration (rsyslogd -N1) ..."
if ! VALIDATION="$(rsyslogd -N1 2>&1)"; then
  log "$VALIDATION"
  restore
  die "rsyslog config validation FAILED — nothing was restarted and the previous state is restored."
fi
if printf '%s' "$VALIDATION" | grep -qiE '(^|[^a-z])error'; then
  log "$VALIDATION"
  restore
  die "rsyslog config validation reported errors — nothing was restarted and the previous state is restored."
fi
log "Configuration validates."

# --- Restart -------------------------------------------------------------------------
log "Restarting rsyslog ..."
if command -v systemctl >/dev/null 2>&1; then
  systemctl restart rsyslog || { restore; die "rsyslog failed to restart; previous config restored. Re-run: systemctl restart rsyslog"; }
  sleep 1
  RSTATUS="$(systemctl is-active rsyslog 2>/dev/null || true)"
  [[ "$RSTATUS" == "active" ]] || { log "$(systemctl status rsyslog --no-pager -l 2>&1 | tail -20)"; restore; die "rsyslog is not active after restart; previous config restored."; }
else
  service rsyslog restart || { restore; die "rsyslog failed to restart; previous config restored."; }
  RSTATUS="restarted"
fi
log "rsyslog is ${RSTATUS}."

# --- Emit the JSON summary (stdout only) ---------------------------------------------
printf '{"host":"%s","endpoint":"%s","port":"%s","protocol":"%s","selector":"%s","configFile":"%s","caFile":"%s","rsyslogStatus":"%s"}\n' \
  "$HOSTNAME_FQDN" "$ENDPOINT" "$PORT" "$PROTOCOL" "$SELECTOR" "$CONF_FILE" \
  "$([[ "$PROTOCOL" == "tls" ]] && printf '%s' "$CA_FILE" || printf '')" "$RSTATUS"

log ""
log "Done. Send a test message with:  logger -p authpriv.notice 'ingext syslog test'"
