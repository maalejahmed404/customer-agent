"""Interface web (Streamlit) : se connecter, poser des questions, voir les sources,
approuver les emails proposés par l'assistant.

OÙ ÇA TOURNE
    Sur Azure : Container App "ui", port 8501, la SEULE app publique (https://ui.<domaine>).
    En local  : streamlit run ui/streamlit_app.py   ->   http://localhost:8501

À QUI ELLE PARLE
    Uniquement à l'API (variable API_URL). Jamais directement à MongoDB ni au serveur MCP.

COMMENT MARCHE STREAMLIT (important pour comprendre ce fichier)
    - Tout le script est ré-exécuté DE HAUT EN BAS à chaque interaction (clic, message...).
    - st.session_state est un dict qui SURVIT entre ces ré-exécutions (un par utilisateur,
      gardé en mémoire par le serveur Streamlit) : on y garde le token, les messages, etc.
    - st.rerun() relance le script immédiatement (pour afficher le nouvel état).
    - st.stop() arrête le script ici : rien de ce qui suit n'est affiché.

ORGANISATION DU FICHIER
    1. fonctions utiles
    2. écran de connexion   (affiché tant qu'on n'est pas connecté, puis st.stop())
    3. barre latérale       (compte, nouvelle conversation, actions en attente)
    4. le chat
"""

import os
import uuid  # pour générer des identifiants de conversation uniques

import requests  # client HTTP simple (synchrone), suffisant pour une interface
import streamlit as st

# Adresse de l'API. Local : http://localhost:8000 ; docker compose : http://api:8000 ;
# Azure : https://api.internal.<domaine> (défini dans infra/main.bicep).
API_URL = os.getenv("API_URL", "http://localhost:8000")

# Titre de l'onglet du navigateur et icône. Doit être le premier appel Streamlit.
st.set_page_config(page_title="Assistant compte client", page_icon="💼")


# ============================================================ 1. fonctions utiles

def call_api(method, path, **kwargs):
    """Appelle l'API avec le token de l'utilisateur connecté.

    Exemple : call_api("GET", "/actions", params={"status": "pending"})
    **kwargs : tous les autres arguments (json=..., params=...) sont passés tels quels à requests.
    """
    headers = {"Authorization": f"Bearer {st.session_state.token}"}
    # timeout=120 : une question peut prendre du temps (plusieurs appels LLM)
    response = requests.request(method, f"{API_URL}{path}", headers=headers, timeout=120, **kwargs)
    if response.status_code == 401:
        # Token expiré (après 8 h) ou invalide : on efface la session -> au prochain
        # affichage, le script montre l'écran de connexion.
        st.session_state.clear()
        st.rerun()
    return response


def error_message(response):
    """Le message d'erreur renvoyé par l'API (FastAPI le met dans le champ "detail")."""
    try:
        return response.json().get("detail", response.text)
    except ValueError:  # la réponse n'est pas du JSON (ex. page d'erreur HTML)
        return response.text


def show_message(message, index):
    """Affiche un message du chat, avec ses sources et un éventuel email en attente.

    message : {"role": "user" ou "assistant", "content": "...", "sources": [...], "action_id": ...}
    index   : la position du message, pour donner des "key" uniques aux boutons
              (Streamlit exige une clé différente pour chaque bouton de la page).
    """
    with st.chat_message(message["role"]):  # bulle de chat (icône utilisateur ou assistant)
        st.markdown(message["content"])

        # Une section repliable par source citée : "[1] email · 2025-03-10 · Titre"
        for source in message.get("sources", []):
            label = f"[{source['number']}] {source['kind']} · {source['date']} · {source['title']}"
            with st.expander(label):
                st.write(source["text"])  # l'extrait utilisé par l'agent
                # Bouton pour charger l'appel/email COMPLET depuis l'API
                if st.button("Voir la source complète", key=f"full-{index}-{source['number']}"):
                    full = call_api("GET", f"/interactions/{source['interaction_id']}")
                    if full.ok:
                        st.text(full.json()["body"])

        # L'agent a préparé un email : on prévient l'utilisateur qu'il doit le valider
        if message.get("action_id"):
            st.info("Brouillon d'email enregistré. Vérifiez-le dans **Actions en attente** "
                    "avant qu'il ne soit envoyé.")


def start_new_conversation():
    """Vide l'historique affiché et crée un nouvel id de conversation.

    Avec un NOUVEL id, l'API utilise un nouveau thread_id : l'agent repart sans mémoire.
    uuid4().hex : 32 caractères aléatoires, pratiquement impossible d'avoir deux fois le même.
    """
    st.session_state.messages = []
    st.session_state.conversation_id = uuid.uuid4().hex


# ============================================================ 2. écran de connexion

# Pas de token dans la session = pas connecté -> on affiche le formulaire et on s'arrête.
if "token" not in st.session_state:
    st.title("Assistant compte client")
    # st.form : les champs ne sont envoyés qu'au clic sur le bouton (pas à chaque lettre tapée)
    with st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Mot de passe", type="password")  # caractères masqués
        if st.form_submit_button("Se connecter"):
            try:
                # Appel direct (pas call_api) : on n'a pas encore de token
                response = requests.post(f"{API_URL}/login",
                                         json={"email": email, "password": password}, timeout=10)
            except requests.RequestException:
                # Réseau : l'API est arrêtée, ou API_URL est fausse
                st.error("L'API n'est pas joignable.")
                st.stop()
            if response.ok:
                # Connexion réussie : on garde le token et les infos dans la session
                user = response.json()
                st.session_state.token = user["token"]
                st.session_state.email = user["email"]
                st.session_state.account_name = user["account_name"]
                start_new_conversation()
                st.rerun()  # relancer le script : cette fois "token" existe -> on passe au chat
            st.error("Email ou mot de passe incorrect.")
    st.stop()  # tant qu'on n'est pas connecté, on n'affiche rien d'autre


# ============================================================ 3. barre latérale
# (on n'arrive ici que si l'utilisateur est connecté)

with st.sidebar:
    st.subheader(st.session_state.account_name)  # le nom du compte client
    st.caption(st.session_state.email)
    if st.button("Nouvelle conversation"):  # l'assistant oublie les questions précédentes
        start_new_conversation()
        st.rerun()
    if st.button("Se déconnecter"):
        st.session_state.clear()  # plus de token -> écran de connexion
        st.rerun()

    st.divider()
    st.subheader("Actions en attente")
    # Rechargé à chaque exécution du script : la liste est toujours à jour
    response = call_api("GET", "/actions", params={"status": "pending"})
    pending = response.json() if response.ok else []
    if not pending:
        st.caption("Rien à approuver.")
    for action in pending:
        email = action["payload"]
        # Chaque email proposé est affiché EN ENTIER (destinataires compris) : l'humain
        # voit exactement ce qui partira avant de cliquer.
        with st.expander(f"✉️ {email['subject']}", expanded=True):
            st.write("**À :** " + ", ".join(email["to"]))
            st.text(email["body"])
            approve, reject = st.columns(2)  # deux boutons côte à côte
            # key=... : une clé unique par bouton (l'id de l'action)
            if approve.button("Approuver et envoyer", key=f"approve-{action['id']}"):
                call_api("POST", f"/actions/{action['id']}/approve")
                st.rerun()  # l'action n'est plus "pending" -> elle disparaît de la liste
            if reject.button("Refuser", key=f"reject-{action['id']}"):
                call_api("POST", f"/actions/{action['id']}/reject")
                st.rerun()


# ============================================================ 4. le chat

st.title("Assistant compte client")
st.caption("Posez vos questions sur les appels et les emails de ce compte.")

# Réafficher tout l'historique (le script est ré-exécuté à chaque fois, donc l'écran
# est reconstruit entièrement à partir de st.session_state.messages)
for i, message in enumerate(st.session_state.messages):
    show_message(message, i)

# st.chat_input renvoie le texte tapé quand l'utilisateur appuie sur Entrée, sinon None.
# ":=" (opérateur "morse") : affecte ET teste en même temps.
if question := st.chat_input("Ex. : Qu'a dit le client sur le prix ?"):
    # Afficher tout de suite la question (sans attendre la réponse)
    with st.chat_message("user"):
        st.markdown(question)

    # Envoyer la question à l'API, avec l'id de conversation (pour la mémoire de l'agent)
    with st.spinner("Recherche dans les appels et les emails..."):  # animation d'attente
        response = call_api("POST", "/chat", json={
            "question": question,
            "conversation_id": st.session_state.conversation_id,
        })

    if response.ok:
        data = response.json()
        answer = {"role": "assistant", "content": data["answer"], "sources": data["sources"],
                  "action_id": data["action_id"]}
    else:
        answer = {"role": "assistant", "content": f"Erreur : {error_message(response)}"}

    # Ajouter la question et la réponse à l'historique, puis réafficher la page
    st.session_state.messages += [{"role": "user", "content": question}, answer]
    st.rerun()
