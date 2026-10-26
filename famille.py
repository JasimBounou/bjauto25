"""Brouillons de réponses pour plusieurs comptes sur un PC partagé.

Chaque membre de la famille a son propre profil Chrome (dossier séparé, une
seule connexion à faire la première fois). Pour chaque compte, le script ouvre
la messagerie, lit le dernier message, propose une réponse avec Claude, puis
attend ta validation. Rien n'est envoyé sans ton accord.

Usage :
    pip install -r requirements.txt && playwright install chromium
    export ANTHROPIC_API_KEY=sk-ant-...
    python famille.py              # passe sur tous les comptes
    python famille.py --login      # première fois : se connecter sur chaque compte
"""

import argparse
import sys
from pathlib import Path

import anthropic
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

MODEL = "claude-opus-5-5"

# Un dossier de profil par personne : les sessions restent séparées.
COMPTES = {
    "Maman": "profils/maman",
    "Papa": "profils/papa",
    "Moi": "profils/moi",
    # ...
}

URL_MESSAGERIE = "https://exemple.com/inbox"  # à remplacer
SELECTEUR_DERNIER_MESSAGE = ".message-item-text"  # à adapter
SELECTEUR_CHAMP = "textarea"  # à adapter
SELECTEUR_ENVOYER = "button[type='submit']"  # à adapter


def generer_reponse(client, message_recu, consigne):
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=2000,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=(
            "Tu rédiges des réponses courtes et polies en français à des messages d'acheteurs. "
            "Réponds uniquement avec le texte du message."
        ),
        messages=[{
            "role": "user",
            "content": f"Message reçu :\n{message_recu}\n\nConsigne : {consigne or 'réponds poliment.'}",
        }],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Génération refusée.")
    return "".join(b.text for b in response.content if b.type == "text").strip()


def demander(question, choix):
    while True:
        rep = input(question).strip().lower()
        if rep in choix:
            return rep


def traiter_compte(p, client, nom, dossier, login):
    print(f"\n===== {nom} =====")
    context = p.chromium.launch_persistent_context(str(Path(dossier).resolve()), headless=False)
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(URL_MESSAGERIE)

        if login:
            input(f"Connecte-toi sur le compte de {nom}, puis appuie sur Entrée...")
            return

        input("Ouvre la conversation à traiter, puis appuie sur Entrée (ou Ctrl+C pour quitter)...")
        try:
            recu = page.locator(SELECTEUR_DERNIER_MESSAGE).last
            recu.wait_for(state="visible", timeout=10_000)
            texte_recu = recu.inner_text()
        except PlaywrightTimeout:
            print("Aucun message trouvé, compte suivant.")
            return
        print(f"\nMessage reçu :\n{texte_recu}\n")

        consigne = input("Consigne (ex. « accepte 15€ », vide = poli) : ").strip()
        while True:
            reponse = generer_reponse(client, texte_recu, consigne)
            print(f"\nProposition :\n{reponse}\n")
            choix = demander("[e]nvoyer / [m]odifier / [r]égénérer / [p]asser : ", {"e", "m", "r", "p"})
            if choix == "r":
                continue
            if choix == "p":
                return
            if choix == "m":
                reponse = input("Ton texte : ").strip() or reponse
            break

        champ = page.locator(SELECTEUR_CHAMP).first
        champ.fill(reponse)
        if demander(f"Envoyer ce message depuis le compte de {nom} ? [o/n] ", {"o", "n"}) == "o":
            page.locator(SELECTEUR_ENVOYER).first.click()
            print("Envoyé.")
        else:
            print("Laissé dans le champ, non envoyé.")
            input("Appuie sur Entrée pour passer au compte suivant...")
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--login", action="store_true", help="se connecter une première fois sur chaque compte")
    parser.add_argument("--compte", help="ne traiter qu'un compte (nom dans COMPTES)")
    args = parser.parse_args()

    comptes = {args.compte: COMPTES[args.compte]} if args.compte else COMPTES
    client = anthropic.Anthropic()  # lit ANTHROPIC_API_KEY
    with sync_playwright() as p:
        for nom, dossier in comptes.items():
            traiter_compte(p, client, nom, dossier, args.login)
    print("\nTerminé.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nArrêté.")
