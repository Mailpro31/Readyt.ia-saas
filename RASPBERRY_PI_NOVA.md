# Guide de déploiement — Nova sur Raspberry Pi (à la maison)

Faire tourner l'agent **chez toi** sur un Raspberry Pi. Avantage décisif : il
utilise ta **vraie IP internet résidentielle**, celle que Reddit ne bloque pas
(contrairement aux IP de VPS/datacenter et aux proxies commerciaux partagés).

Accès à distance (dashboard depuis ton téléphone, n'importe où) via **Tailscale**,
sans ouvrir aucun port sur ta box.

Coût : **~0 €/mois** (juste l'électricité, ~1 €/mois). Matériel : ~50-80 € une fois.

---

## 0. Matériel à acheter

- **Raspberry Pi 4 (4 Go ou 8 Go)** ou **Pi 5** — un kit complet de préférence
  (Pi + alimentation officielle + boîtier + carte microSD 32 Go+).
- Un moyen de flasher la carte SD depuis un ordi (n'importe lequel, juste pour
  l'installation initiale). Si tu n'as vraiment aucun ordi, un ami peut flasher
  la carte en 5 min, ou certains kits sont vendus avec l'OS préinstallé.
- Le Pi sera relié à ta box en **Ethernet** (idéal) ou **WiFi**.

> Pi 4/5 = architecture **ARM64**. Le projet est compatible ARM64 (image Docker
> `python:3.13-slim` + Chromium Playwright arm64), rien à changer.

---

## 1. Flasher Raspberry Pi OS (une fois, depuis un ordi)

1. Télécharge **Raspberry Pi Imager** (raspberrypi.com/software) sur l'ordi.
2. Insère la carte microSD.
3. Dans Imager :
   - **Choose OS** → *Raspberry Pi OS Lite (64-bit)* (sans bureau, plus léger).
   - **Choose Storage** → ta carte SD.
   - Clique sur l'engrenage ⚙️ (ou "Edit Settings") — **IMPORTANT** :
     - Coche **Enable SSH** → *Use password authentication* (ou colle ta clé
       publique Termius, comme pour le VPS).
     - Définis un **nom d'utilisateur** (ex. `sasha`) et un **mot de passe**.
     - Renseigne ton **WiFi** (SSID + mot de passe) si tu n'utilises pas Ethernet.
     - Définis un **hostname** : `nova` (le Pi sera joignable à `nova.local`).
     - Locale/fuseau : `Europe/Paris`.
   - **Write** → attends la fin.
4. Insère la carte dans le Pi, branche l'alimentation. Au premier démarrage il
   se connecte tout seul à ta box (~1-2 min).

---

## 2. Se connecter au Pi en SSH (Termius)

Depuis ton iPhone (sur le **même WiFi** que le Pi pour cette première étape) :

- Termius → **Hosts** → **+**
- **Address** : `nova.local` (ou l'IP locale du Pi, visible dans l'interface de
  ta box, section "appareils connectés")
- **Username** : celui choisi à l'étape 1 (ex. `sasha`)
- **Auth** : mot de passe ou clé SSH
- Connecte-toi → prompt `sasha@nova:~ $`

---

## 3. Installer Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```
Déconnecte-toi de Termius et reconnecte-toi (pour que le groupe `docker`
s'applique). Puis :
```bash
sudo apt-get update && sudo apt-get install -y git
```

---

## 4. Installer Tailscale (accès à distance sécurisé)

Sur le **Pi** :
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```
Ça affiche une URL — ouvre-la dans un navigateur, connecte-toi (compte Google
ou email), ça relie le Pi à ton "Tailnet". Note l'**IP Tailscale** du Pi
(du type `100.x.y.z`), affichée par :
```bash
tailscale ip -4
```

Sur ton **iPhone** : installe l'app **Tailscale** (App Store), connecte-toi avec
le **même compte**. Ton téléphone et le Pi sont désormais sur le même réseau
privé, où que tu sois (4G, autre WiFi…), **sans ouvrir de port sur ta box**.

---

## 5. Récupérer le code et configurer

```bash
git clone https://github.com/Mailpro31/Readyt.ia-saas.git nova-agent
cd nova-agent
cp .env.example .env
nano .env
```
Dans `.env`, règle au minimum :
```env
MILO_WEB_USER=admin
MILO_WEB_PASS=UnMotDePasseFort
MILO_BIND=0.0.0.0        # nécessaire pour l'accès via Tailscale
TZ=Europe/Paris
TELEGRAM_BOT_TOKEN=...    # (optionnel) ton token bot
```
(`Ctrl+O`, Entrée, `Ctrl+X` pour sauver.)

Puis les configs (identiques au déploiement VPS) :
- `config/llm.yaml` → clés Groq + Gemini (gratuites)
- `config/telegram.yaml` → bot_token + admin_chat_ids
- `config/reddit_accounts.yaml` → ton compte Reddit
- `projects/nova.yaml` → déjà prêt

---

## 6. Lancer

```bash
docker compose up -d
docker compose ps        # doit afficher "Up (healthy)"
```

Colle les cookies Reddit via le dashboard (section COOKIE SESSIONS), comme sur
le VPS.

---

## 7. Accéder au dashboard depuis n'importe où

Sur ton iPhone (Tailscale actif), ouvre dans Safari :
```
http://IP_TAILSCALE_DU_PI:8420
```
(l'IP `100.x.y.z` notée à l'étape 4). Accessible en 4G, en déplacement, partout
— et **Telegram** marche déjà de partout sans rien configurer.

---

## 8. LE test qui compte — Reddit depuis ta vraie IP

C'est tout l'intérêt du Pi. Vérifie que Reddit n'est plus bloqué :
```bash
docker compose exec miloagent python3 -c "import requests; r = requests.get('https://old.reddit.com/api/me.json', headers={'User-Agent':'Mozilla/5.0'}); print(r.status_code)"
```
- **401** ou **200** = 🎉 débloqué (401 = normal ici, ça veut juste dire "pas de
  cookies dans CE test" — l'important c'est que ce n'est plus 403 "Blocked").
- **403** = encore bloqué (peu probable sur IP résidentielle perso).

Si c'est bon, l'agent va enfin pouvoir chauffer le compte et travailler.

---

## Notes / limites

- **Laisse le Pi branché en continu** (consommation ~5 W). L'uptime dépend de ta
  connexion internet maison et de l'électricité — pas de garantie "datacenter",
  mais largement suffisant pour ce projet.
- **Sauvegarde** : la base est dans `nova-agent/data/`. Copie ce dossier de temps
  en temps si tu veux pouvoir tout restaurer.
- **Mises à jour** : `git pull origin claude/new-session-akqio7` puis
  `docker compose up -d --build`.
- Tu peux **abandonner le VPS Hostinger** une fois que le Pi tourne bien — il ne
  sert plus à rien (le blocage Reddit venait justement de son IP).
