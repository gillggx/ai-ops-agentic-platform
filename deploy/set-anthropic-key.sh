#!/usr/bin/env bash
# set-anthropic-key.sh — rotate the Anthropic API key stored as a systemd
# encrypted credential (2026-07-10; replaces plaintext ANTHROPIC_API_KEY in
# python_ai_sidecar/.env).
#
# The key is encrypted with the host key (/var/lib/systemd/credential.secret,
# TPM2 when available) into /etc/credstore.encrypted/anthropic_api_key. The
# sidecar unit loads it via `ImportCredential=anthropic_api_key`; systemd
# decrypts it into the service-private $CREDENTIALS_DIRECTORY and
# python_ai_sidecar/main.py lifts it into the env at startup.
#
# Usage (on EC2):
#   sudo bash deploy/set-anthropic-key.sh          # silent prompt (recommended
#                                                  #  — key stays out of shell
#                                                  #  history and `ps`)
#   sudo bash deploy/set-anthropic-key.sh sk-ant-… # arg mode (convenience)
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "[no] must run as root:  sudo bash deploy/set-anthropic-key.sh" >&2
  exit 1
fi

KEY="${1:-}"
if [ -z "$KEY" ]; then
  read -rsp "New ANTHROPIC_API_KEY: " KEY
  echo
fi
case "$KEY" in
  sk-ant-*) ;;
  *) echo "[no] value does not look like an Anthropic key (sk-ant-…)" >&2; exit 1 ;;
esac

mkdir -p /etc/credstore.encrypted
printf '%s' "$KEY" | systemd-creds encrypt --name=anthropic_api_key - \
  /etc/credstore.encrypted/anthropic_api_key
chmod 600 /etc/credstore.encrypted/anthropic_api_key
echo "[ok] credential written to /etc/credstore.encrypted/anthropic_api_key"

# Scrub any plaintext copies so the credential is the single source.
SIDECAR_ENV_DIR=/opt/aiops/python_ai_sidecar
for f in "$SIDECAR_ENV_DIR"/.env "$SIDECAR_ENV_DIR"/.env.bak* "$SIDECAR_ENV_DIR"/.env.*.bak "$SIDECAR_ENV_DIR"/.env.haiku.bak; do
  [ -f "$f" ] || continue
  if grep -q '^ANTHROPIC_API_KEY=..*' "$f"; then
    sed -i 's|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=|' "$f"
    echo "[ok] scrubbed plaintext key from $f"
  fi
done

systemctl restart aiops-python-sidecar
sleep 3
if systemctl is-active --quiet aiops-python-sidecar; then
  echo "[ok] aiops-python-sidecar restarted with the new credential"
else
  echo "[no] sidecar failed to restart — check: journalctl -u aiops-python-sidecar -n 50" >&2
  exit 1
fi
