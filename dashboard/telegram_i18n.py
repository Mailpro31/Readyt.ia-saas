"""Bilingual (FR/EN) strings for the Telegram bot.

One place for: the command catalog (name + short description per language,
used for both /help and Telegram's native "/" command menu) and the UI labels
used in command replies. Add a language by adding its key to each entry.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

DEFAULT_LANG = "en"
SUPPORTED = ("en", "fr")

# ── Command catalog ──────────────────────────────────────────────────────
# group -> ordered list of (command, {lang: short description})
_GROUPS_ORDER = ["monitor", "intel", "accounts", "control", "debug"]

_GROUP_TITLES = {
    "monitor":  {"en": "📊 Check on me",       "fr": "📊 Me surveiller"},
    "intel":    {"en": "🧠 Intelligence",       "fr": "🧠 Intelligence"},
    "accounts": {"en": "👥 Accounts",           "fr": "👥 Comptes"},
    "control":  {"en": "🎮 Tell me what to do", "fr": "🎮 Me piloter"},
    "debug":    {"en": "🛠 Debug & help",       "fr": "🛠 Débogage & aide"},
}

# (command, group, en, fr)
_CATALOG: List[Tuple[str, str, str, str]] = [
    ("status",       "monitor",  "How I'm doing right now",        "Mon état en ce moment"),
    ("stats",        "monitor",  "What I did in the last 24h",     "Ce que j'ai fait en 24h"),
    ("report",       "monitor",  "Full daily breakdown",           "Récap quotidien complet"),
    ("last",         "monitor",  "My last N actions (full text)",  "Mes N dernières actions"),
    ("messages",     "monitor",  "Messages posted in last N hours","Messages postés (N dernières h)"),
    ("health",       "monitor",  "Are my accounts OK",             "Santé de mes comptes"),
    ("warmup",       "monitor",  "Account warm-up progress",       "Avancement du chauffage des comptes"),
    ("insights",     "monitor",  "What I've learned so far",       "Ce que j'ai appris"),
    ("projects",     "monitor",  "Projects I'm working on",        "Projets sur lesquels je travaille"),

    ("intel",        "intel",    "Subreddit opportunity analysis", "Analyse des opportunités subreddits"),
    ("presence",     "intel",    "Community presence & trust",     "Présence & confiance communautés"),
    ("research",     "intel",    "What's trending right now",      "Tendances du moment"),
    ("friends",      "intel",    "Relationship stats",             "Stats de relations"),
    ("conversations","intel",    "Recent DM conversations",        "Conversations DM récentes"),
    ("hubs",         "intel",    "Owned subreddit hubs",           "Subreddits que je gère"),
    ("performance",  "intel",    "Performance score & tips",       "Score de performance & conseils"),
    ("llm",          "intel",    "AI provider stats",              "Stats des IA (Groq/Gemini)"),

    ("accounts",     "accounts", "List all accounts",              "Lister tous les comptes"),
    ("cookies",      "accounts", "Session cookie health",          "Santé des cookies de session"),
    ("testtwitter",  "accounts", "Test X now (connect + scan)",    "Tester X (connexion + scan)"),
    ("addreddit",    "accounts", "Add a Reddit account",           "Ajouter un compte Reddit"),
    ("addtwitter",   "accounts", "Add an X account",               "Ajouter un compte X"),
    ("pastecookies", "accounts", "Paste session cookies",          "Coller des cookies de session"),
    ("removeaccount","accounts", "Disable an account",             "Désactiver un compte"),

    ("scan",         "control",  "Scan for opportunities now",     "Scanner maintenant"),
    ("post",         "control",  "Reply to the best one now",      "Répondre au meilleur maintenant"),
    ("learn",        "control",  "Analyze & adapt now",            "Analyser & s'adapter"),
    ("pause",        "control",  "Take a break",                   "Faire une pause"),
    ("resume",       "control",  "Get back to work",               "Reprendre le travail"),
    ("lang",         "control",  "Switch language (FR/EN)",        "Changer de langue (FR/EN)"),

    ("debug",        "debug",    "Why am I not acting?",           "Pourquoi je n'agis pas ?"),
    ("help",         "debug",    "Show this menu",                 "Afficher ce menu"),
]


def _desc(entry: Tuple[str, str, str, str], lang: str) -> str:
    return entry[3] if lang == "fr" else entry[2]


def build_help(lang: str) -> str:
    """Render the grouped, bilingual /help message."""
    lang = lang if lang in SUPPORTED else DEFAULT_LANG
    header = (
        "🤖 NOVA BOT — commandes\n"
        "Voici tout ce que je sais faire :"
        if lang == "fr" else
        "🤖 NOVA BOT — commands\n"
        "Here's everything I can do:"
    )
    lines = [header]
    for group in _GROUPS_ORDER:
        title = _GROUP_TITLES[group][lang]
        lines.append(f"\n{title}")
        for entry in _CATALOG:
            if entry[1] != group:
                continue
            lines.append(f"  /{entry[0]} — {_desc(entry, lang)}")
    footer = (
        "\n💡 Astuce : tape « / » pour voir la liste avec l'autocomplétion. "
        "Change de langue avec /lang fr ou /lang en."
        if lang == "fr" else
        "\n💡 Tip: type \"/\" to see the list with autocomplete. "
        "Switch language with /lang fr or /lang en."
    )
    lines.append(footer)
    return "\n".join(lines)


def native_commands(lang: str) -> List[Tuple[str, str]]:
    """(command, description) pairs for Telegram's setMyCommands menu."""
    lang = lang if lang in SUPPORTED else DEFAULT_LANG
    out = []
    for entry in _CATALOG:
        # Telegram command descriptions are capped at 256 chars; ours are short.
        out.append((entry[0], _desc(entry, lang)))
    return out


# ── UI labels used inside command replies ────────────────────────────────
_L: Dict[str, Dict[str, str]] = {
    "not_connected":   {"en": "I'm not connected to the main engine right now.",
                        "fr": "Je ne suis pas connecté au moteur principal pour l'instant."},
    "no_account_mgr":  {"en": "Account manager not available.",
                        "fr": "Gestionnaire de comptes indisponible."},

    # Generic error surfaced by the global error handler.
    "cmd_error":       {"en": "⚠️ The command {cmd} failed.\n📋 Reason: {detail}\n\n"
                              "If it keeps happening, forward me this message.",
                        "fr": "⚠️ La commande {cmd} a échoué.\n📋 Cause : {detail}\n\n"
                              "Si ça se reproduit, transfère-moi ce message."},

    # /lang
    "lang_usage":      {"en": "Usage: /lang fr  (or)  /lang en",
                        "fr": "Usage : /lang fr  (ou)  /lang en"},
    "lang_set":        {"en": "✅ Language set to English.",
                        "fr": "✅ Langue réglée sur le français."},
    "lang_unknown":    {"en": "Unknown language. Choose: fr or en.",
                        "fr": "Langue inconnue. Choisis : fr ou en."},

    # /status
    "status_header":   {"en": "📊 STATUS (last 24h)", "fr": "📊 ÉTAT (dernières 24h)"},
    "status_working":  {"en": "▶️ Working",           "fr": "▶️ En activité"},
    "status_paused":   {"en": "⏸ Paused (on a break)","fr": "⏸ En pause"},
    "status_state":    {"en": "State", "fr": "État"},
    "status_actions":  {"en": "Actions taken", "fr": "Actions réalisées"},
    "status_pending":  {"en": "Opportunities waiting", "fr": "Opportunités en attente"},
    "status_quality":  {"en": "Avg opportunity quality", "fr": "Qualité moyenne des opportunités"},
    "status_by_plat":  {"en": "By platform", "fr": "Par plateforme"},
    "status_nothing":  {"en": "Nothing done yet today — still warming up.",
                        "fr": "Rien de fait aujourd'hui — encore en chauffage."},

    # /health
    "health_header":   {"en": "🩺 ACCOUNT HEALTH", "fr": "🩺 SANTÉ DES COMPTES"},
    "health_none":     {"en": "No accounts configured yet.", "fr": "Aucun compte configuré."},
    "health_good":     {"en": "Good", "fr": "Bon"},
    "health_cooldown": {"en": "Cooling down", "fr": "En refroidissement"},
    "health_flagged":  {"en": "Flagged", "fr": "Signalé"},
    "health_banned":   {"en": "BANNED", "fr": "BANNI"},
    "health_unknown":  {"en": "Unknown", "fr": "Inconnu"},
    "health_actions":  {"en": "actions today", "fr": "actions aujourd'hui"},
    "health_back":     {"en": "back online", "fr": "de retour"},

    # /accounts
    "accounts_header": {"en": "👥 ACCOUNTS", "fr": "👥 COMPTES"},
    "accounts_none":   {"en": "No accounts configured yet.", "fr": "Aucun compte configuré."},
    "accounts_cookies_ok": {"en": "cookies OK", "fr": "cookies OK"},
    "accounts_no_cookies": {"en": "no cookies", "fr": "pas de cookies"},
    "accounts_persona":{"en": "persona", "fr": "persona"},
    "accounts_projects":{"en": "projects", "fr": "projets"},

    # /warmup
    "warmup_header":   {"en": "🔥 WARM-UP PROGRESS", "fr": "🔥 AVANCEMENT DU CHAUFFAGE"},
    "warmup_none":     {"en": "No accounts warming up yet.", "fr": "Aucun compte en chauffage pour l'instant."},
    "warmup_ready":    {"en": "READY to promote", "fr": "PRÊT à promouvoir"},
    "warmup_day":      {"en": "day", "fr": "jour"},
    "warmup_actions":  {"en": "actions today", "fr": "actions aujourd'hui"},
    "warmup_footer":   {"en": "ℹ️ An account only starts promoting Nova once it's READY. "
                              "You'll get a 🎓 message the moment each one graduates.",
                        "fr": "ℹ️ Un compte ne promeut Nova qu'une fois PRÊT. "
                              "Tu recevras un message 🎓 dès qu'un compte est chaud."},

    # /cookies
    "cookies_header":  {"en": "🍪 COOKIE STATUS", "fr": "🍪 ÉTAT DES COOKIES"},
    "cookies_none":    {"en": "No accounts configured yet.", "fr": "Aucun compte configuré."},
    "cookies_no_file": {"en": "no cookie file — use /pastecookies",
                        "fr": "aucun fichier cookie — utilise /pastecookies"},
    "cookies_missing": {"en": "missing", "fr": "manquant"},
    "cookies_ok":      {"en": "session cookies present", "fr": "cookies de session présents"},
    "cookies_repaste": {"en": "re-paste with", "fr": "recolle avec"},
    "cookies_footer":  {"en": "ℹ️ Cookies expire over time. If a platform stops working, "
                              "re-export them (Cookie-Editor) and re-paste with /pastecookies.",
                        "fr": "ℹ️ Les cookies expirent. Si une plateforme s'arrête, ré-exporte-les "
                              "(Cookie-Editor) et recolle avec /pastecookies."},

    # /scan, /post
    "scan_msg":        {"en": "🔍 Scanning now (Reddit + X) for posts matching your keywords…\n"
                              "This runs in the background — I'll message you when opportunities "
                              "are found (or check /status).",
                        "fr": "🔍 Je scanne (Reddit + X) les posts qui matchent tes mots-clés…\n"
                              "Ça tourne en arrière-plan — je te préviens quand je trouve des "
                              "opportunités (ou vois /status)."},
    "scan_error":      {"en": "⚠️ Something went wrong:", "fr": "⚠️ Un souci est survenu :"},
    "post_paused":     {"en": "⏸ I'm paused right now — /resume me first.",
                        "fr": "⏸ Je suis en pause — fais /resume d'abord."},
    "post_msg":        {"en": "✍️ Looking for the best opportunity to reply to right now…\n"
                              "I'll act on it in the background (respecting rate limits) — "
                              "check /last to see what I posted.",
                        "fr": "✍️ Je cherche la meilleure opportunité de réponse…\n"
                              "J'agis en arrière-plan (dans les limites anti-ban) — "
                              "vois /last pour voir ce que j'ai posté."},
    "post_error":      {"en": "⚠️ Couldn't do it:", "fr": "⚠️ Impossible :"},

    # /testtwitter
    "tt_start":        {"en": "🐦 Testing X — connecting and running a real scan…\n"
                              "I'll send the result in a moment.",
                        "fr": "🐦 Test de X — connexion et vrai scan en cours…\n"
                              "Je t'envoie le résultat dans un instant."},
}


def t(lang: str, key: str, **kwargs) -> str:
    """Translate a label key; falls back to English, then the key itself."""
    entry = _L.get(key, {})
    text = entry.get(lang) or entry.get(DEFAULT_LANG) or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            pass
    return text
