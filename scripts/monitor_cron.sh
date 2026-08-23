#!/usr/bin/env bash
# =============================================================================
# monitor_cron.sh — Monitoring horaire + alerte Telegram (Nova / MiloAgent)
# =============================================================================
# Lance scripts/check_deployment.sh et, EN CAS D'ÉCHEC, envoie une alerte
# Telegram (même bot/chat que les alertes de l'agent, lus dans
# config/telegram.yaml — ou surchargés par les variables d'env).
#
# Anti-spam : n'alerte qu'au PASSAGE en échec et à la RÉCUPÉRATION (transitions),
# pas à chaque exécution, via un fichier d'état.
#
# Installation (voir bas de fichier) :
#   crontab -e   →   0 * * * * /chemin/nova-agent/scripts/monitor_cron.sh
# =============================================================================

set -uo pipefail

# Se placer à la racine du projet (le script est dans scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.." || exit 1

DOMAIN="${1:-${MILO_DOMAIN:-}}"
STATE_FILE="${MILO_MONITOR_STATE:-data/.monitor_state}"
LOG_FILE="${MILO_MONITOR_LOG:-logs/monitor.log}"
mkdir -p "$(dirname "$STATE_FILE")" "$(dirname "$LOG_FILE")" 2>/dev/null || true

# ── Résolution du token + chat_id Telegram ─────────────────────────
# Priorité : variables d'env, sinon config/telegram(.local).yaml
TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TG_CHAT="${TELEGRAM_CHAT_ID:-}"

_tg_conf="config/telegram.local.yaml"
[ -f "$_tg_conf" ] || _tg_conf="config/telegram.yaml"
if [ -z "$TG_TOKEN" ] && [ -f "$_tg_conf" ]; then
    TG_TOKEN=$(grep -E '^\s*bot_token:' "$_tg_conf" | head -1 | sed -E 's/.*bot_token:\s*"?([^"]*)"?.*/\1/')
fi
if [ -z "$TG_CHAT" ] && [ -f "$_tg_conf" ]; then
    # premier id sous admin_chat_ids
    TG_CHAT=$(awk '/admin_chat_ids:/{f=1;next} f&&/- /{gsub(/[^0-9-]/,"",$0);print;exit}' "$_tg_conf")
fi

send_telegram() {
    local msg="$1"
    if [ -z "$TG_TOKEN" ] || [ "$TG_TOKEN" = "YOUR_TELEGRAM_BOT_TOKEN" ] || [ -z "$TG_CHAT" ] || [ "$TG_CHAT" = "000000000" ]; then
        echo "[$(date '+%F %T')] Telegram non configuré — alerte non envoyée: $msg" >>"$LOG_FILE"
        return
    fi
    curl -fsS --max-time 10 \
        "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
        -d chat_id="${TG_CHAT}" \
        --data-urlencode text="$msg" >/dev/null 2>&1 \
        || echo "[$(date '+%F %T')] Échec envoi Telegram" >>"$LOG_FILE"
}

# ── Exécution du check ─────────────────────────────────────────────
OUTPUT="$(./scripts/check_deployment.sh "$DOMAIN" 2>&1)"
RESULT=$?

PREV="ok"
[ -f "$STATE_FILE" ] && PREV="$(cat "$STATE_FILE")"

TS="$(date '+%F %T')"
echo "[$TS] check exit=$RESULT (prev=$PREV)" >>"$LOG_FILE"

if [ "$RESULT" -ne 0 ]; then
    # Échec : n'alerter que si on vient de basculer (ok -> fail)
    if [ "$PREV" != "fail" ]; then
        FAILS="$(echo "$OUTPUT" | grep -i 'FAIL' | sed 's/\x1b\[[0-9;]*m//g' | head -6)"
        send_telegram "🚨 Nova/MiloAgent — problème détecté (${TS})
${DOMAIN:+domaine: $DOMAIN}
$FAILS"
    fi
    echo "fail" >"$STATE_FILE"
else
    # OK : si on récupère d'un état d'échec, notifier la résolution
    if [ "$PREV" = "fail" ]; then
        send_telegram "✅ Nova/MiloAgent — de nouveau opérationnel (${TS})"
    fi
    echo "ok" >"$STATE_FILE"
fi

exit "$RESULT"

# =============================================================================
# INSTALLATION DU CRON
# -----------------------------------------------------------------------------
# 1) Rends le script exécutable :
#      chmod +x scripts/monitor_cron.sh scripts/check_deployment.sh
#
# 2) Édite le crontab :
#      crontab -e
#
# 3) Ajoute UNE ligne (remplace le chemin et le domaine) :
#      0 * * * * /home/ubuntu/nova-agent/scripts/monitor_cron.sh track.novaspeak.app >> /home/ubuntu/nova-agent/logs/monitor.log 2>&1
#
#    → s'exécute chaque heure (minute 0). Alerte Telegram seulement aux
#      transitions (panne / rétablissement), pas de spam.
#
# 4) (Optionnel) Test immédiat :
#      ./scripts/monitor_cron.sh track.novaspeak.app
# =============================================================================
