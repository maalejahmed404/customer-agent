"""Le format des corps de requêtes JSON (validé automatiquement par FastAPI).

Quand un endpoint déclare `body: LoginRequest`, FastAPI :
    - lit le JSON envoyé par le client,
    - vérifie qu'il contient les bons champs avec les bons types,
    - sinon, répond automatiquement une erreur 422 avec le détail du problème.
Le code de l'endpoint reçoit donc toujours des données propres.
"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Corps de POST /login : {"email": "...", "password": "..."}"""
    email: str
    password: str


class ChatRequest(BaseModel):
    """Corps de POST /chat : {"question": "...", "conversation_id": "..."}"""
    question: str
    # Un id par conversation : l'interface en crée un nouveau à la connexion et à chaque
    # clic sur "Nouvelle conversation". Même id = même conversation = l'agent se souvient.
    # max_length=64 : évite qu'un client envoie un id énorme.
    conversation_id: str = Field(default="default", max_length=64)
    # Remarque : il n'y a PAS de champ account_id. Le compte vient du token.
    # Si un client en envoie un quand même, pydantic l'ignore (un test le vérifie).
