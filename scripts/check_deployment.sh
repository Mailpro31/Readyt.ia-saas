#!/usr/bin/env bash
# =============================================================================
# check_deployment.sh — Vérification post-déploiement (Nova / MiloAgent)
# =============================================================================
# Teste en une commande : conteneur, /health, /health/detailed, API warm-up,
# liens trackés, config GEO, SSL du domaine, et le smoke-test Phase 1.
#
# Usage :
#   ./scripts/check_deployment.sh                 # tests locaux (localhost:8420)
#   ./scripts/check_deployment.sh track.novaspeak.app   # + tests HTTPS publics
#
# Code de sortie : 0 si tout est OK, 1 si au moins un test échoue.
# =============================================================================

set -uo pipefail

DOMAIN="${1:-}"
PORT="${MILO_PORT:-8420}"
LOCAL="http://127.0.0.1:${PORT}"
PASS=0
FAIL=0

green() { printf '\033[0;32m%s\033[0m\n' "$1"; }
red()   { printf '\033[0;31m%s\033[0m\n' "$1"; }
info()  { printf '\033[0;36m%s\033[0m\n' "$1"; }

ok()   { green "  [PASS] $1"; PASS=$((PASS+1)); }
ko()   { red   "  [FAIL] $1"; FAIL=$((FAIL+1)); }

# Détecte comment invoquer l'app (docker compose vs python direct)
if docker compose ps >/dev/null 2>&1 && docker compose ps 2>/dev/null | grep -q miloagent; then
    RUNNER="docker compose exec -T miloagent"
elif command -v docker >/dev/null 2>&1 && docker ps 2>/dev/null | grep -q miloagent; then
    RUNNER="docker exec miloagent"
else
    RUNNER=""   # exécution locale directe
fi

# ── 1. Conteneur / process ──────────────────────────────────────────
info "1. Conteneur / process"
if [ -n "$RUNNER" ]; then
    if docker ps 2>/dev/null | grep -q miloagent; then
        ok "conteneur miloagent en cours d'exécution"
    else
        ko "conteneur miloagent introuvable"
    fi
else
    info "  (pas de conteneur détecté — mode exécution locale)"
fi

# ── 2. Health check local ───────────────────────────────────────────
info "2. Health check (local ${LOCAL})"
if curl -fsS --max-time 5 "${LOCAL}/health" 2>/dev/null | grep -q '"status"'; then
    ok "/health répond OK"
else
    ko "/health injoignable sur ${LOCAL}"
fi

# ── 3. Health détaillé (module 1.4) ─────────────────────────────────
info "3. Health détaillé (/health/detailed)"
DETAILED="$(curl -fsS --max-time 5 "${LOCAL}/health/detailed" 2>/dev/null || true)"
if echo "$DETAILED" | grep -q '"jobs"'; then
    ok "/health/detailed expose les jobs"
    JOBS=$(echo "$DETAILED" | grep -o '"id"' | wc -l | tr -d ' ')
    ERRS=$(echo "$DETAILED" | grep -o '"errors_24h":[0-9]*' | grep -o '[0-9]*$' || echo "?")
    info "     jobs planifiés: ${JOBS} · erreurs 24h: ${ERRS}"
    echo "$DETAILED" | grep -q '"geo_enabled":true' && info "     GEO tracking: activé" \
        || info "     GEO tracking: désactivé"
else
    ko "/health/detailed ne répond pas comme attendu"
fi

# ── 4. API warm-up (module 1.0) ─────────────────────────────────────
info "4. API warm-up (/api/warmup — nécessite auth, on vérifie juste la route)"
CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${LOCAL}/api/warmup" 2>/dev/null); CODE="${CODE:-000}"
# 401 = route existe mais protégée (normal), 200 = ouverte
if [ "$CODE" = "401" ] || [ "$CODE" = "200" ]; then
    ok "/api/warmup présent (HTTP ${CODE})"
else
    ko "/api/warmup inattendu (HTTP ${CODE})"
fi

# ── 5. Config GEO ───────────────────────────────────────────────────
info "5. Config GEO"
if [ -f config/geo.yaml ]; then
    ok "config/geo.yaml présent"
else
    info "  (config/geo.yaml absent — GEO désactivé, OK si voulu)"
fi

# ── 6. Config link tracking ─────────────────────────────────────────
info "6. Config link tracking"
if grep -q "track_base_url" config/settings.yaml 2>/dev/null; then
    BASE=$(grep -A1 "^link_tracking:" config/settings.yaml | grep "track_base_url" | sed 's/.*track_base_url: *//; s/"//g')
    if [ -n "$BASE" ] && [ "$BASE" != "''" ]; then
        ok "track_base_url configuré: ${BASE}"
    else
        info "  track_base_url vide — les liens seront relatifs (/r/slug). OK en dev."
    fi
else
    ko "clé link_tracking.track_base_url absente de settings.yaml"
fi

# ── 7. SSL / HTTPS public (si domaine fourni) ───────────────────────
if [ -n "$DOMAIN" ]; then
    info "7. HTTPS public (https://${DOMAIN})"
    if curl -fsS --max-time 8 "https://${DOMAIN}/health" 2>/dev/null | grep -q '"status"'; then
        ok "https://${DOMAIN}/health répond (SSL OK, ports ouverts)"
    else
        ko "https://${DOMAIN}/health injoignable (vérifie DNS, ports 80/443, SSL)"
    fi
    # Test d'un slug bidon → doit renvoyer 404 (route /r/ active)
    RCODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "https://${DOMAIN}/r/__nope__" 2>/dev/null); RCODE="${RCODE:-000}"
    if [ "$RCODE" = "404" ]; then
        ok "route de redirection /r/{slug} active (404 sur slug inconnu)"
    else
        ko "route /r/{slug} inattendue (HTTP ${RCODE})"
    fi
else
    info "7. HTTPS public — ignoré (aucun domaine passé en argument)"
fi

# ── 8. Smoke-test Phase 1 ───────────────────────────────────────────
info "8. Smoke-test Phase 1"
if [ -n "$RUNNER" ]; then
    SMOKE="$($RUNNER python3 scripts/smoke_test_phase1.py 2>&1 || true)"
else
    SMOKE="$(python3 scripts/smoke_test_phase1.py 2>&1 || true)"
fi
if echo "$SMOKE" | grep -q "ALL PASS"; then
    ok "smoke-test : $(echo "$SMOKE" | grep RESULT | sed 's/^[[:space:]]*//')"
else
    ko "smoke-test échoué (lance-le à la main pour le détail)"
fi

# ── Résumé ──────────────────────────────────────────────────────────
echo
echo "============================================================"
if [ "$FAIL" -eq 0 ]; then
    green "RÉSULTAT : ${PASS} OK / 0 échec — déploiement sain ✅"
    exit 0
else
    red "RÉSULTAT : ${PASS} OK / ${FAIL} échec(s) — voir ci-dessus ❌"
    exit 1
fi
