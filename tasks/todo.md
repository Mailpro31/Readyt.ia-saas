# Todo - MiloAgent

> Plan courant du projet. Chaque tache doit etre checkable.

## Current Sprint

- [ ] Deployer le service de redirection de liens sur un domaine public
      (`track.novaspeak.app` ou reverse-proxy `/r/` sur `novaspeak.app`) et
      renseigner `link_tracking.track_base_url` dans `config/settings.yaml`.
- [ ] Creer `config/geo.yaml` a partir de `config/geo.yaml.example` et fournir
      les cles API (OpenAI / Anthropic / Perplexity) pour le GEO tracking.
- [ ] Ajouter le rendu front dashboard (HTML/JS) pour warm-up / liens / GEO —
      les endpoints API existent deja (`/api/warmup`, `/api/links`, `/api/geo`,
      `/health/detailed`), reste le rendu dans `dashboard/static/`.

## Backlog

- [ ] Phase 2.1 — DM de relance apres reponse reussie (`platforms/reddit_bot.py`
      n'a toujours PAS de fonction d'envoi de message prive).
- [ ] Phase 2.2 — Score de risque de ban explicable (`safety/risk_scorer.py`).
- [ ] Phase 2.3 — Veille concurrentielle active dans `core/subreddit_intel.py`
      (les `competitors` + `trigger_keywords` sont deja dans `projects/nova.yaml`).

## Completed

- [x] 1.0 Warm-up actif des comptes (`safety/warmup_scheduler.py`, table
      `warmup_progress`, job orchestrateur, CLI `add-account`, gate dans
      `account_manager.get_next_account`, flux add->warming->ready automatique).
- [x] 1.1 Attribution des leads (`core/link_tracker.py`, tables `tracked_links`
      + `link_clicks`, endpoint `GET /r/{slug}` 302, `/api/links`).
- [x] 1.2 GEO / AEO tracking (`core/geo_tracker.py`, table `geo_citations`,
      job 48h, `config/geo.yaml.example`, `/api/geo`).
- [x] 1.3 Tests unitaires (`tests/test_link_tracker.py`,
      `tests/test_geo_tracker.py`) + `scripts/smoke_test_phase1.py` (8/8 PASS).
- [x] 1.4 Health check etendu (`/health/detailed`) + alertes Telegram
      (premier clic, premiere citation IA, palier warm-up).
- [x] 1.5 Boucle de feedback (`learning_engine._learn_from_real_conversions`
      croise clics reels + citations avec les weights `strategy`).
- [x] 1.6 Rapport hebdomadaire enrichi (clics + citations + recommandations).

## Review Notes

- Toutes les nouvelles ecritures produit restent derriere le gate warm-up
  (`status = ready`) et la validation manuelle du dashboard par defaut.
- Rien n'a ete retire de `safety/` (rate limiting, cooldowns, dedup intacts).
