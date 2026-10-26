# bjauto25

`inject_reply.py` génère une réponse avec Claude et la saisit dans un onglet déjà
ouvert d'un navigateur exposant un port CDP (AdsPower, GoLogin, Chrome avec
`--remote-debugging-port`). Le message est seulement tapé dans le champ : l'envoi reste manuel.

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python inject_reply.py --port 9222 --selector "textarea" --url-contains vinted \
    --prompt "Rédige une réponse courte pour accepter une offre à 15€."
```
