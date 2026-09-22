# Source this to target a provider from /etc/fluency_grid_config.json.
#   . env.sh [provider]      (default: develop2)
# Exports INGEXT_SITE_URL and INGEXT_TOKEN. The token is never printed.
_p="${1:-develop2}"
export INGEXT_SITE_URL="$(python3 -c "
import json
d=json.load(open('/etc/fluency_grid_config.json'))
m=[p['url'] for p in d['ingextProviders'] if p['name']=='$_p']
print(m[0] if m else '')")"
export INGEXT_TOKEN="$(python3 -c "
import json
d=json.load(open('/etc/fluency_grid_config.json'))
m=[p['token'] for p in d['ingextProviders'] if p['name']=='$_p']
print(m[0] if m else '')")"
if [ -z "$INGEXT_SITE_URL" ]; then
  echo "no such provider: $_p" >&2
  python3 -c "
import json
d=json.load(open('/etc/fluency_grid_config.json'))
print('available:', ', '.join(p['name'] for p in d['ingextProviders']))" >&2
else
  echo "provider $_p -> $INGEXT_SITE_URL (token ${#INGEXT_TOKEN} chars)"
fi
unset _p
