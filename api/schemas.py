"""Schémas pydantic des corps de requête de l'API."""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Corps de POST /login : {"email": "...", "password": "..."}"""
    email: str
    password: str


class ChatRequest(BaseModel):
    """Corps de POST /chat : {"question": "...", "conversation_id": "..."}"""
    question: str
    # Identifiant de conversation choisi par le client ; longueur bornée.
    conversation_id: str = Field(default="default", max_length=64)
    # Pas de champ account_id : le compte vient du jeton, un account_id envoyé est ignoré.
