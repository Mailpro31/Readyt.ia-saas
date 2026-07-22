# Lessons Learned - MiloAgent

> Erreurs passees et patterns a eviter. Relu au debut de chaque session Claude Code.

## Patterns a eviter

- Ne PAS poster de contenu produit depuis un compte non chauffe : un compte
  neuf qui poste sur un thread lie a Nova se fait shadow-ban avant toute mesure.
  D'ou le gate warm-up (`account_manager.is_warmup_ready`) applique dans
  `get_next_account` des qu'un `project` est passe.
- Ne pas casser le flux de post pour une erreur de tracking : `link_tracker`
  garde le lien brut si la reecriture echoue (jamais d'exception remontee).
- GEO tracking = seul module a APPELS PAYANTS. Toujours le laisser derriere
  `geo.enabled` et une `config/geo.yaml` absente par defaut (`.example` fourni).

## Corrections appliquees

- `detect_citation` (geo_tracker) : le mot "nova" seul genere des faux positifs
  ("Nova Launcher", "Nova Scotia", "innovation"). Corrige via match `\bnova\b`
  + liste de disqualifiers + priorite au domaine `novaspeak`. Couvert par tests.
- `business_manager.reload` : ajout de `data["_key"] = f.stem` pour retrouver la
  cle de config (nom de fichier) d'un projet, utilisee par le GEO lookup.
- `Database` : le pattern est un `executescript` unique dans `_init_tables` +
  helpers `_execute_write`. Les nouvelles tables suivent ce pattern, pas de
  nouveau mecanisme de migration.

## Rules

- Toute nouvelle config = YAML. Tout acces DB = via `core/database.py`.
- Toute nouvelle ecriture (post, DM) reste derriere la validation manuelle du
  dashboard par defaut, avec option explicite pour l'auto.
- Les nouveaux jobs orchestrateur suivent le pattern `add_job(..., id=..., 
  next_run_time=...)` + wrapper `_xxx_safe` qui verifie `_paused` / ressources.
- Lancer `python3 scripts/smoke_test_phase1.py` avant de livrer toute modif
  touchant warm-up / liens / GEO.
