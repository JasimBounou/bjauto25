"""Réponses automatiques pour plusieurs comptes de la famille sur un PC partagé.

Chaque compte a son propre profil Chrome (dossier séparé, connexion à faire une
seule fois avec --login). Une passe complète :

  1. ouvre chaque compte, parcourt les conversations non lues et lit le
     dernier message reçu ;
  2. Claude rédige une réponse selon les règles du compte (prix mini, ton...) ;
  3. affiche le récapitulatif de toutes les réponses : tu valides tout en une
     touche, ou une par une ;
  4. envoie les réponses validées.

Usage :
    pip install -r requirements.txt && playwright install chromium
    export ANTHROPIC_API_KEY=sk-ant-...
    python famille.py --login      # première fois : se connecter sur chaque compte
    python famille.py              # passe complète sur les 6 comptes
    python famille.py --compte Lina
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import anthropic
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

MODEL = "claude-opus-5-5"

# Un profil par compte. « regles » est envoyé à Claude pour chaque réponse.
COMPTES = {
    "Compte1": {"dossier": "profils/compte1", "regles": "Prix minimum : 10 € en dessous du prix affiché. Ton amical."},
    "Compte2": {"dossier": "profils/compte2", "regles": "N'accepte pas de baisse de plus de 15 %."},
    "Compte3": {"dossier": "profils/compte3", "regles": "Ton poli et bref."},
    "Compte4": {"dossier": "profils/compte4", "regles": "Ton poli et bref."},
    "Compte5": {"dossier": "profils/compte5", "regles": "Ton poli et bref."},
    "Compte6": {"dossier": "profils/compte6", "regles": "Ton poli et bref."},
}

# À adapter au site (clic droit > Inspecter).
URL_MESSAGERIE = "https://exemple.com/inbox"
SELECTEUR_CONV_NON_LUE = ".conversation.unread a"  # liens vers les conversations non lues
SELECTEUR_MESSAGE_RECU = ".message.received"  # messages de l'autre personne
SELECTEUR_CHAMP = "textarea"
SELECTEUR_ENVOYER = "button[type='submit']"
MAX_CONVERSATIONS_PAR_COMPTE = 20


@dataclass
class Brouillon:
    compte: str
    url: str
    recu: str
    reponse: str


def generer_reponse(client, message_recu, regles):
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=2000,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=(
            "Tu rédiges des réponses courtes et polies en français à des messages d'acheteurs, "
            "en respectant strictement les règles du vendeur. "
            "Si le message demande une info que tu n'as pas (mesures, état précis, photo...), "
            "commence ta réponse par « [À VÉRIFIER] ». "
            "Réponds uniquement avec le texte du message."
        ),
        messages=[{"role": "user", "content": f"Règles du vendeur : {regles}\n\nMessage reçu :\n{message_recu}"}],
    )
    if response.stop_reason == "refusal":
        return "[À VÉRIFIER] (génération refusée)"
    return "".join(b.text for b in response.content if b.type == "text").strip()


def ouvrir(p, dossier, headless):
    return p.chromium.launch_persistent_context(str(Path(dossier).resolve()), headless=headless)


def collecter(p, client, nom, config, headless):
    """Lit les conversations non lues d'un compte et prépare les réponses."""
    brouillons = []
    context = ouvrir(p, config["dossier"], headless)
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(URL_MESSAGERIE)
        page.wait_for_load_state("domcontentloaded")
        liens = page.locator(SELECTEUR_CONV_NON_LUE)
        urls = [liens.nth(i).get_attribute("href") for i in range(min(liens.count(), MAX_CONVERSATIONS_PAR_COMPTE))]
        urls = [urljoin(page.url, u) for u in urls if u]
        print(f"[{nom}] {len(urls)} conversation(s) non lue(s)")

        for url in urls:
            page.goto(url)
            try:
                recu = page.locator(SELECTEUR_MESSAGE_RECU).last
                recu.wait_for(state="visible", timeout=10_000)
                texte = recu.inner_text().strip()
            except PlaywrightTimeout:
                print(f"[{nom}] pas de message lisible sur {url}, ignoré")
                continue
            brouillons.append(Brouillon(nom, url, texte, generer_reponse(client, texte, config["regles"])))
    finally:
        context.close()
    return brouillons


def valider(brouillons):
    """Affiche le récap et renvoie les brouillons à envoyer."""
    print("\n" + "=" * 50 + "\nRÉCAPITULATIF\n" + "=" * 50)
    for i, b in enumerate(brouillons, 1):
        print(f"\n#{i} [{b.compte}]\n  Reçu    : {b.recu}\n  Réponse : {b.reponse}")

    a_verifier = [b for b in brouillons if b.reponse.startswith("[À VÉRIFIER]")]
    surs = [b for b in brouillons if b not in a_verifier]
    print(f"\n{len(surs)} réponse(s) prête(s), {len(a_verifier)} à vérifier.")

    choix = input("[t]out envoyer (sauf « à vérifier ») / [u]ne par une / [a]nnuler : ").strip().lower()
    if choix == "a":
        return []
    if choix == "t":
        selection = surs
        pending = a_verifier
    else:
        selection, pending = [], brouillons

    for b in pending:
        print(f"\n[{b.compte}] Reçu : {b.recu}\nRéponse : {b.reponse}")
        rep = input("[e]nvoyer / [m]odifier / [p]asser : ").strip().lower()
        if rep == "m":
            b.reponse = input("Ton texte : ").strip() or b.reponse
            rep = "e"
        if rep == "e" and not b.reponse.startswith("[À VÉRIFIER]"):
            selection.append(b)
        elif rep == "e":
            print("Retire « [À VÉRIFIER] » en modifiant le texte avant d'envoyer.")
    return selection


def envoyer(p, brouillons, headless):
    par_compte = {}
    for b in brouillons:
        par_compte.setdefault(b.compte, []).append(b)
    for nom, liste in par_compte.items():
        context = ouvrir(p, COMPTES[nom]["dossier"], headless)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            for b in liste:
                page.goto(b.url)
                champ = page.locator(SELECTEUR_CHAMP).first
                champ.wait_for(state="visible", timeout=10_000)
                champ.fill(b.reponse)
                page.locator(SELECTEUR_ENVOYER).first.click()
                page.wait_for_timeout(1500)
                print(f"[{nom}] envoyé : {b.reponse[:60]}")
        finally:
            context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--login", action="store_true", help="se connecter une première fois sur chaque compte")
    parser.add_argument("--compte", help="ne traiter qu'un compte (nom dans COMPTES)")
    parser.add_argument("--headless", action="store_true", help="navigateur invisible (après le --login)")
    args = parser.parse_args()

    comptes = {args.compte: COMPTES[args.compte]} if args.compte else COMPTES

    with sync_playwright() as p:
        if args.login:
            for nom, config in comptes.items():
                context = ouvrir(p, config["dossier"], headless=False)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(URL_MESSAGERIE)
                input(f"Connecte-toi sur le compte {nom}, puis appuie sur Entrée...")
                context.close()
            return 0

        client = anthropic.Anthropic()  # lit ANTHROPIC_API_KEY
        brouillons = []
        for nom, config in comptes.items():
            brouillons += collecter(p, client, nom, config, args.headless)

        if not brouillons:
            print("Aucun message à traiter.")
            return 0
        a_envoyer = valider(brouillons)
        envoyer(p, a_envoyer, args.headless)
        print(f"\nTerminé : {len(a_envoyer)} message(s) envoyé(s).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nArrêté.")
