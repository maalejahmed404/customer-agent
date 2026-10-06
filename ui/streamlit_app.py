"""Interface Streamlit : connexion, chat avec sources, validation des emails proposés.

Ne parle qu'à l'API (API_URL), jamais directement à MongoDB ni au serveur MCP.
"""

import os
import uuid

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="Assistant compte client", page_icon="💼")


# ============================================================ fonctions utiles

def call_api(method, path, **kwargs):
    """Appelle l'API avec le jeton de la session ; sur 401, vide la session et relance le script."""
    headers = {"Authorization": f"Bearer {st.session_state.token}"}
    # Délai long : une question enchaîne plusieurs appels LLM.
    response = requests.request(method, f"{API_URL}{path}", headers=headers, timeout=120, **kwargs)
    if response.status_code == 401:
        # Jeton expiré ou invalide : retour à l'écran de connexion.
        st.session_state.clear()
        st.rerun()
    return response


def error_message(response):
    """Renvoie le champ "detail" de la réponse d'erreur, ou son texte brut hors JSON."""
    try:
        return response.json().get("detail", response.text)
    except ValueError:
        return response.text


def show_message(message, index):
    """Affiche un message du chat, ses sources et l'avis d'email en attente le cas échéant.

    `index` (position du message) sert à rendre uniques les clés des boutons.
    """
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

        for source in message.get("sources", []):
            label = f"[{source['number']}] {source['kind']} · {source['date']} · {source['title']}"
            with st.expander(label):
                st.write(source["text"])
                if st.button("Voir la source complète", key=f"full-{index}-{source['number']}"):
                    full = call_api("GET", f"/interactions/{source['interaction_id']}")
                    if full.ok:
                        st.text(full.json()["body"])

        if message.get("action_id"):
            st.info("Brouillon d'email enregistré. Vérifiez-le dans **Actions en attente** "
                    "avant qu'il ne soit envoyé.")


def start_new_conversation():
    """Vide l'historique et tire un nouvel id de conversation : l'agent repart sans mémoire."""
    st.session_state.messages = []
    st.session_state.conversation_id = uuid.uuid4().hex


# ============================================================ écran de connexion

if "token" not in st.session_state:
    st.title("Assistant compte client")
    with st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Mot de passe", type="password")
        if st.form_submit_button("Se connecter"):
            try:
                # Pas de call_api : aucun jeton à ce stade.
                response = requests.post(f"{API_URL}/login",
                                         json={"email": email, "password": password}, timeout=10)
            except requests.RequestException:
                st.error("L'API n'est pas joignable.")
                st.stop()
            if response.ok:
                user = response.json()
                st.session_state.token = user["token"]
                st.session_state.email = user["email"]
                st.session_state.account_name = user["account_name"]
                start_new_conversation()
                st.rerun()
            st.error("Email ou mot de passe incorrect.")
    st.stop()


# ============================================================ barre latérale

with st.sidebar:
    st.subheader(st.session_state.account_name)
    st.caption(st.session_state.email)
    if st.button("Nouvelle conversation"):
        start_new_conversation()
        st.rerun()
    if st.button("Se déconnecter"):
        st.session_state.clear()
        st.rerun()

    st.divider()
    st.subheader("Actions en attente")
    response = call_api("GET", "/actions", params={"status": "pending"})
    pending = response.json() if response.ok else []
    if not pending:
        st.caption("Rien à approuver.")
    for action in pending:
        email = action["payload"]
        # Email affiché en entier, destinataires compris : l'approbation porte sur ce qui partira.
        with st.expander(f"✉️ {email['subject']}", expanded=True):
            st.write("**À :** " + ", ".join(email["to"]))
            st.text(email["body"])
            approve, reject = st.columns(2)
            if approve.button("Approuver et envoyer", key=f"approve-{action['id']}"):
                call_api("POST", f"/actions/{action['id']}/approve")
                st.rerun()
            if reject.button("Refuser", key=f"reject-{action['id']}"):
                call_api("POST", f"/actions/{action['id']}/reject")
                st.rerun()


# ============================================================ chat

st.title("Assistant compte client")
st.caption("Posez vos questions sur les appels et les emails de ce compte.")

for i, message in enumerate(st.session_state.messages):
    show_message(message, i)

if question := st.chat_input("Ex. : Qu'a dit le client sur le prix ?"):
    # Question affichée avant l'appel à l'API, sans attendre la réponse.
    with st.chat_message("user"):
        st.markdown(question)

    with st.spinner("Recherche dans les appels et les emails..."):
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

    st.session_state.messages += [{"role": "user", "content": question}, answer]
    st.rerun()
