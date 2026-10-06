"""État du graphe et sorties structurées du LLM (Plan, EmailDraft)."""

from datetime import date
from typing import Annotated, Literal, TypedDict

from langgraph.graph.message import add_messages

from pydantic import BaseModel, Field, field_validator

# Trois échanges question/réponse : assez pour résoudre une relance sans alourdir le prompt.
HISTORY_MESSAGES = 6


class Plan(BaseModel):
    """Le plan de recherche, rempli par le LLM (voir agent/nodes/planner.py)."""

    needs_data: bool = Field(
        description="False only for greetings or questions unrelated to the account")
    keyword_queries: list[str] = Field(
        default_factory=list,
        description="Up to 3 full-text queries with exact words: names, products, amounts")
    semantic_queries: list[str] = Field(
        default_factory=list,
        description="Up to 3 short descriptions of the topic, for a search by meaning")
    kind: Literal["call", "email", "any"] = "any"
    date_from: str | None = Field(None, description="YYYY-MM-DD, only if the question gives a period")
    date_to: str | None = Field(None, description="YYYY-MM-DD, only if the question gives a period")
    # Ajoute un appel à list_interactions.
    recent: bool = Field(False, description="True if the question is about the latest calls or emails")
    # Déclenche le nœud email_drafter après la réponse.
    draft_email: bool = Field(False, description="True if the user asks to write or send an email")

    @field_validator("date_from", "date_to")
    @classmethod
    def iso_date_or_none(cls, value):
        """Écarte une date mal formée produite par le LLM plutôt que de faire échouer la recherche."""
        try:
            return date.fromisoformat(value).isoformat() if value else None
        except ValueError:
            return None


class EmailDraft(BaseModel):
    """Le brouillon d'email rempli par le LLM (voir agent/nodes/email_drafter.py)."""
    to: list[str] = Field(description="Recipient email addresses")
    subject: str
    body: str


class State(TypedDict, total=False):
    """État du graphe ; les clés se remplissent au fil des nœuds."""

    # Entrées fournies par l'API.
    question: str
    account_id: int           # issu du token JWT, jamais d'un champ client
    user_email: str

    # Historique persisté par le checkpointer ; add_messages ajoute au lieu de remplacer.
    messages: Annotated[list, add_messages]

    # Champs remplis par les nœuds.
    plan: Plan                # planner
    passages: list[dict]      # retriever : extraits fusionnés et triés
    answer: str               # responder
    sources: list[dict]       # responder : sources citées dans la réponse
    action_id: str | None     # email_drafter : action en attente de validation, ou None


def recent_history(state: State):
    """Derniers messages de la conversation, bornés à HISTORY_MESSAGES."""
    return state.get("messages", [])[-HISTORY_MESSAGES:]
