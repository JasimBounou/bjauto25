"""Génère une réponse avec Claude puis la saisit dans un onglet déjà ouvert.

Le navigateur (AdsPower, GoLogin, Chrome lancé avec --remote-debugging-port...)
doit déjà tourner et exposer son port CDP en local. Le texte est seulement
saisi dans le champ : l'envoi reste manuel.

Usage :
    export ANTHROPIC_API_KEY=sk-ant-...
    python inject_reply.py --port 9222 --selector "textarea" \
        --url-contains vinted --prompt "Rédige une réponse courte pour accepter une offre à 15€."
"""

import argparse
import random
import sys

import anthropic
from playwright.sync_api import sync_playwright

MODEL = "claude-opus-5-5"


def generer_texte(client, consigne):
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=2000,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=(
            "Tu rédiges des messages courts et cordiaux en français. "
            "Réponds uniquement avec le texte du message, sans guillemets ni commentaire."
        ),
        messages=[{"role": "user", "content": consigne}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("La génération a été refusée par le modèle.")
    # Avec la réflexion activée, le premier bloc n'est pas forcément du texte.
    texte = "".join(b.text for b in response.content if b.type == "text").strip()
    if not texte:
        raise RuntimeError(f"Réponse vide (stop_reason={response.stop_reason}).")
    return texte


def trouver_page(browser, url_contains):
    pages = [page for context in browser.contexts for page in context.pages]
    if not pages:
        raise RuntimeError("Aucun onglet ouvert dans le navigateur.")
    if url_contains:
        for page in pages:
            if url_contains in page.url:
                return page
        raise RuntimeError(f"Aucun onglet dont l'URL contient « {url_contains} ».")
    return pages[0]


def injecter_texte_navigateur(port_cdp, selecteur, texte, url_contains=None):
    with sync_playwright() as p:
        print(f"Connexion au navigateur sur le port {port_cdp}...")
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port_cdp}")

        page = trouver_page(browser, url_contains)
        page.bring_to_front()
        print(f"Onglet : {page.url}")

        champ = page.locator(selecteur).first
        champ.wait_for(state="visible", timeout=10_000)
        champ.click()

        print("Saisie du texte en cours...")
        champ.press_sequentially(texte, delay=random.randint(50, 150))
        print("Texte saisi. Relis-le et envoie-le toi-même dans le navigateur.")
        # Pas de browser.close() : on quitte sans fermer le navigateur ni l'onglet,
        # la sortie du bloc « with » coupe juste la connexion CDP.


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=9222, help="port CDP fourni par AdsPower/GoLogin")
    parser.add_argument("--selector", required=True, help="sélecteur CSS du champ de saisie")
    parser.add_argument("--url-contains", help="choisit l'onglet dont l'URL contient ce texte")
    parser.add_argument(
        "--prompt",
        default="Rédige une réponse courte pour accepter une offre à 15€.",
        help="consigne envoyée à Claude",
    )
    parser.add_argument("--yes", action="store_true", help="saisir sans demander de confirmation")
    args = parser.parse_args()

    client = anthropic.Anthropic()  # lit ANTHROPIC_API_KEY dans l'environnement
    texte = generer_texte(client, args.prompt)
    print(f"Texte généré :\n{texte}\n")

    if not args.yes and input("Saisir ce texte dans le navigateur ? [o/N] ").strip().lower() not in ("o", "oui", "y"):
        print("Annulé.")
        return 0

    injecter_texte_navigateur(args.port, args.selector, texte, args.url_contains)
    return 0


if __name__ == "__main__":
    sys.exit(main())
