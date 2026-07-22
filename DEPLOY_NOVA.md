# Guide de déploiement — MiloAgent pour Nova

Guide pas-à-pas pour héberger l'agent sur un VPS. Durée : ~30 min.
Coût : ~5 €/mois (VPS) + 1-4 $/mois si tu actives le GEO tracking.

> ⚠️ Rappel : **pas sur Vercel** (l'agent est un daemon 24/7 avec SQLite +
> scheduler, incompatible avec le serverless). Un petit VPS Linux est requis.

---

## 0. Prérequis

- Un **VPS** Ubuntu 22.04+ (Hetzner CX22, OVH, DigitalOcean… 2 vCPU / 2-4 Go RAM suffisent).
- Un **nom de domaine** ou sous-domaine pointant vers l'IP du VPS
  (ex. `track.novaspeak.app` → un enregistrement DNS **A** vers l'IP).
  Ce domaine sert au **dashboard** ET aux **liens trackés** (`/r/{slug}`).
- Au moins **un compte Reddit** dédié (jamais ton compte perso).
- Optionnel : un **bot Telegram** (via @BotFather) pour les alertes.
- Optionnel : des **clés API** OpenAI / Anthropic / Perplexity pour le GEO.

---

## 1. Préparer le VPS

```bash
ssh root@TON_IP

# Docker + compose
curl -fsSL https://get.docker.com | sh
apt-get update && apt-get install -y git

# Récupérer le code
git clone https://github.com/Mailpro31/Readyt.ia-saas.git nova-agent
cd nova-agent
```

---

## 2. Configurer les secrets (`.env`)

```bash
cp .env.example .env
nano .env
```

Renseigne au minimum :

```env
MILO_WEB_USER=admin
MILO_WEB_PASS=un_mot_de_passe_fort_ici     # accès au dashboard
MILO_PORT=8420
TZ=Europe/Paris

# Optionnel — alertes Telegram (module 1.4)
TELEGRAM_BOT_TOKEN=123456:ABC...

# Optionnel — clés GEO (module 1.2). Peuvent aussi aller dans config/geo.yaml
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
PERPLEXITY_API_KEY=pplx-...
```

> Si tu utilises Anthropic/Perplexity via `.env`, ajoute-les au bloc
> `environment:` du `docker-compose.yml` (seul `OPENAI_API_KEY` y est par défaut).

---

## 3. Configurer le produit Nova

`projects/nova.yaml` est **déjà prêt** (concurrents, subreddits, angle
accessibilité/vie privée). Vérifie juste l'URL et active-le :

```bash
nano projects/nova.yaml     # project.enabled: true (déjà le cas)
```

---

## 4. Configurer les comptes Reddit

Édite `config/reddit_accounts.yaml` (ou crée `config/reddit_accounts.local.yaml`
pour que `git pull` n'écrase jamais tes vrais identifiants) :

```yaml
auth_mode: web
accounts:
  - username: mon_compte_nova
    password: "..."
    enabled: true
    assigned_projects: [Nova]
    cooldown_minutes: 15
    max_actions_per_hour: 4
```

> Tu pourras aussi ajouter un compte plus tard **sans éditer de fichier** :
> `docker compose exec miloagent python3 miloagent.py add-account -u X -p Y --project Nova`
> → il est automatiquement mis en **warm-up** (module 1.0).

---

## 5. (Optionnel) Activer le GEO tracking

```bash
cp config/geo.yaml.example config/geo.yaml
nano config/geo.yaml     # mettre enabled: true et les clés (ou via .env)
```

Les requêtes-sondes pour Nova sont déjà écrites. Laisse `enabled: false` si tu
ne veux pas de coût API pour l'instant — tout le reste marche à 0 €.

---

## 6. Configurer les liens trackés (module 1.1)

Le tracking a besoin d'un domaine **public**. Une fois le domaine pointé sur le
VPS (étape 7 met en place Nginx + SSL), renseigne-le :

```bash
nano config/settings.yaml
```
```yaml
link_tracking:
  track_base_url: "https://track.novaspeak.app"   # ton domaine
```

Les liens Nova postés deviendront alors `https://track.novaspeak.app/r/abc123`,
et Nginx (étape 7) route `/r/…` vers le dashboard qui enregistre le clic.

---

## 7. Lancer — deux options

### Option A — Script tout-en-un (recommandé : Nginx + SSL automatiques)

```bash
sudo ./deploy.sh --setup     # installe Nginx + Certbot, demande ton domaine, obtient le SSL
sudo ./deploy.sh --up        # build + démarrage
sudo ./deploy.sh --status    # vérifie la santé
```

`--setup` configure le reverse-proxy HTTPS vers le dashboard (port 8420, en
local uniquement). Ton domaine sert donc à la fois au dashboard **et** aux
liens `/r/{slug}`.

### Option B — Docker Compose seul (sans SSL auto)

```bash
docker compose up -d
docker compose logs -f
```
Le dashboard est alors sur `http://127.0.0.1:8420` (à exposer toi-même derrière
un reverse-proxy si tu veux le HTTPS + les liens trackés publics).

---

## 8. Vérifier que tout tourne

```bash
# Santé détaillée (module 1.4) : jobs, erreurs 24h, état des comptes
curl -s https://track.novaspeak.app/health/detailed | python3 -m json.tool

# Smoke-test Phase 1 (dans le conteneur)
docker compose exec miloagent python3 scripts/smoke_test_phase1.py
# → attendu : RESULT: 8/8 checks passed — ALL PASS ✅
```

Ou en **une seule commande** avec le script de vérification (conteneur, /health,
/health/detailed, API warm-up, config, SSL public, smoke-test) :

```bash
./scripts/check_deployment.sh                       # tests locaux
./scripts/check_deployment.sh track.novaspeak.app   # + tests HTTPS publics
# → attendu : RÉSULTAT : N OK / 0 échec — déploiement sain ✅
```

Puis ouvre le **dashboard** : `https://track.novaspeak.app/login`
(identifiants = `MILO_WEB_USER` / `MILO_WEB_PASS`).

---

## 9. Ce qui se passe ensuite (automatique)

1. Le(s) compte(s) neufs se **chauffent** plusieurs jours (statut `warming`).
2. Dès le karma/jours atteints → passage auto en `ready`.
3. L'agent commence à **scanner, répondre, tracker les liens**.
4. Si GEO activé : citations IA mesurées tous les 2 jours.
5. **Alertes Telegram** au 1er clic / 1re citation / fin de warm-up.
6. **Rapport hebdo** le dimanche.

Suis la progression du warm-up : `GET /api/warmup` (barre « Jour 6/10 »).

---

## Commandes utiles au quotidien

```bash
sudo ./deploy.sh --update            # git pull + rebuild + restart
sudo ./deploy.sh --status            # santé
docker compose logs -f miloagent     # logs live
docker compose exec miloagent python3 miloagent.py accounts   # santé comptes
docker compose exec miloagent python3 miloagent.py status
docker compose restart miloagent
```

---

## Récap des coûts

| Poste | Coût |
|-------|------|
| VPS (2 vCPU / 2-4 Go) | ~5 €/mois |
| Pipeline organique (LLM gratuits, SQLite, tracking) | **0 €** |
| GEO tracking (optionnel, 6 sondes × 3 IA / 48h) | ~1-4 $/mois |
| Proxies Reddit (optionnel, si multi-comptes) | variable |

---

## Annexe — Déploiement sur Oracle Cloud "Always Free" (0 €/mois)

Oracle Cloud offre une VM Linux **gratuite à vie** (Ampere ARM, jusqu'à 4 OCPU /
24 Go RAM) — largement suffisante et vraiment gratuite. Voici les différences
par rapport au guide ci-dessus.

### A1. Créer la VM

1. Compte sur https://cloud.oracle.com (carte bancaire demandée pour
   vérification, **non débitée** sur le tier Always Free).
2. **Compute → Instances → Create Instance**.
3. **Image** : Ubuntu 22.04. **Shape** : `VM.Standard.A1.Flex` (Ampere/ARM),
   règle par ex. **2 OCPU / 12 Go RAM** (dans les limites gratuites).
4. Ajoute ta **clé SSH publique**, puis crée l'instance.
5. Note l'**IP publique** et fais pointer ton DNS (`track.novaspeak.app` → A → IP).

### A2. ⚠️ Le piège n°1 : ouvrir les ports (DOUBLE pare-feu)

Oracle bloque tout par défaut à **deux endroits**. Il faut ouvrir 80 et 443 aux
deux :

**a) Dans la console Oracle** (Virtual Cloud Network) :
`Networking → VCN → Security Lists → Default → Add Ingress Rules`
- Source `0.0.0.0/0`, TCP, port **80**
- Source `0.0.0.0/0`, TCP, port **443**

**b) Sur la VM elle-même** (les images Ubuntu Oracle ont un iptables restrictif) :
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save     # rend les règles permanentes
```
> Si tu sautes l'étape (b), le SSL (certbot) et le dashboard sembleront
> "injoignables" alors que tout tourne — c'est l'erreur la plus courante.

### A3. Installer et déployer (identique au guide, ARM-compatible)

```bash
ssh ubuntu@TON_IP
curl -fsSL https://get.docker.com | sh
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/Mailpro31/Readyt.ia-saas.git nova-agent
cd nova-agent
```
Puis suis les **étapes 2 à 8** du guide principal. Le `Dockerfile` compile
depuis les sources, donc il fonctionne nativement en **ARM64** — rien à changer.

> Note ARM : si un jour l'auth Reddit par navigateur (Playwright/Chromium) pose
> problème, privilégie `auth_mode: web` avec cookies (déjà le défaut) plutôt
> que le mode navigateur lourd.

### A4. Récap Oracle

| Poste | Coût |
|-------|------|
| VM Ampere ARM (2 OCPU / 12 Go) | **0 € à vie** |
| Pipeline organique | **0 €** |
| GEO tracking (optionnel) | ~1-4 $/mois |

Seul rappel : l'IP d'un datacenter peut être surveillée par Reddit → le warm-up
(module 1.0) atténue le risque, un proxy résidentiel (payant) peut devenir utile
si tu montes en volume.

---

## Points de sécurité

- Ne commit **jamais** `config/*.local.yaml`, `.env`, `config/geo.yaml`
  (déjà dans `.gitignore`).
- Le dashboard n'est accessible qu'en HTTPS via Nginx (port 8420 lié à
  `127.0.0.1` uniquement, jamais exposé en clair).
- Mets un `MILO_WEB_PASS` fort (min. 6 caractères, idéalement 20+).
- Un compte par persona, jamais ton compte Reddit personnel.
```
