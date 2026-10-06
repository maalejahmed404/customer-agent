"""Les données qui circulent dans le graphe LangGraph.

C'EST QUOI L'"ÉTAT" (State) ?
    LangGraph fait passer un dictionnaire d'un nœud à l'autre : c'est l'état.
    Chaque nœud :
        1. reçoit l'état complet,
        2. renvoie UNIQUEMENT les champs qu'il veut modifier (ex. {"plan": ...}),
        3. LangGraph fusionne ces champs dans l'état, puis passe au nœud suivant.

    Exemple pour une question :
        API        -> {"question", "account_id", "user_email"}
        planner    -> ajoute "plan"
        retriever  -> ajoute "passages"
        responder  -> ajoute "answer", "sources", "messages"
        email_drafter (si demandé) -> ajoute "action_id"

CE FICHIER CONTIENT
    - State      : la forme de l'état
    - Plan       : ce que le planner décide de chercher (sortie structurée du LLM)
    - EmailDraft : le brouillon d'email écrit par l'email_drafter (sortie structurée du LLM)
    - recent_history : les derniers messages de la conversation
"""

from datetime import date
from typing import Annotated, Literal, TypedDict

# add_messages : une "fonction de fusion" fournie par LangGraph pour les listes de messages
from langgraph.graph.message import add_messages

# pydantic : décrit et VALIDE des données (types, valeurs par défaut, descriptions)
from pydantic import BaseModel, Field, field_validator

# Nombre de messages gardés comme historique : 6 = les 3 dernières questions + 3 réponses.
# Suffisant pour comprendre une relance ("et le prix ?"), sans alourdir le prompt.
HISTORY_MESSAGES = 6


class Plan(BaseModel):
    """Le plan de recherche, rempli par le LLM (voir agent/nodes/planner.py).

    SORTIE STRUCTURÉE : au lieu de demander au LLM du texte libre qu'il faudrait analyser,
    on lui donne ce modèle pydantic comme un "formulaire à remplir". LangChain le transforme
    en schéma JSON d'outil (function calling) ; le LLM répond avec les champs remplis, et
    pydantic vérifie les types. Les descriptions (Field(description=...)) sont lues par le
    LLM pour savoir quoi mettre dans chaque champ : elles restent en anglais, comme les prompts.
    """

    # Faut-il chercher dans les données ? False pour "Bonjour" ou une question hors sujet.
    needs_data: bool = Field(
        description="False only for greetings or questions unrelated to the account")
    # Recherches par mots-clés (-> outil keyword_search). default_factory=list : liste vide
    # par défaut (on n'écrit jamais "= []" directement, la liste serait partagée).
    keyword_queries: list[str] = Field(
        default_factory=list,
        description="Up to 3 full-text queries with exact words: names, products, amounts")
    # Recherches par le sens (-> outil semantic_search)
    semantic_queries: list[str] = Field(
        default_factory=list,
        description="Up to 3 short descriptions of the topic, for a search by meaning")
    # Literal : seulement ces 3 valeurs sont acceptées
    kind: Literal["call", "email", "any"] = "any"
    # Période (optionnelle). "str | None" : un texte, ou rien.
    date_from: str | None = Field(None, description="YYYY-MM-DD, only if the question gives a period")
    date_to: str | None = Field(None, description="YYYY-MM-DD, only if the question gives a period")
    # True -> on appelle aussi list_interactions (les derniers appels/emails)
    recent: bool = Field(False, description="True if the question is about the latest calls or emails")
    # True -> le nœud email_drafter sera exécuté après la réponse
    draft_email: bool = Field(False, description="True if the user asks to write or send an email")

    # Un "validator" pydantic : exécuté automatiquement sur date_from et date_to à la création du Plan.
    @field_validator("date_from", "date_to")
    @classmethod
    def iso_date_or_none(cls, value):
        """Garde la date seulement si elle est au format AAAA-MM-JJ, sinon la remplace par None.

        Le LLM peut écrire "le mois dernier" ou "2025-13-45" : plutôt que de faire planter la
        recherche (ou de filtrer n'importe comment), on ignore simplement ce filtre.
        """
        try:
            # fromisoformat lève ValueError si le format est mauvais ;
            # isoformat() réécrit la date proprement ("2025-03-10").
            return date.fromisoformat(value).isoformat() if value else None
        except ValueError:
            return None


class EmailDraft(BaseModel):
    """Le brouillon d'email rempli par le LLM (voir agent/nodes/email_drafter.py)."""
    to: list[str] = Field(description="Recipient email addresses")
    subject: str
    body: str


class State(TypedDict, total=False):
    """La forme de l'état du graphe.

    TypedDict : un dict "normal" dont on décrit les clés et leurs types (aide à la lecture
    et à l'autocomplétion). total=False : toutes les clés sont optionnelles, car l'état se
    remplit au fil des nœuds.
    """

    # --- Entrées (données par l'API dans api/routes/chat.py) ---
    question: str
    account_id: int           # vient du token JWT, jamais de l'utilisateur
    user_email: str

    # --- Mémoire de la conversation (sauvegardée dans MongoDB par le checkpointer) ---
    # Annotated[list, add_messages] : pour ce champ, quand un nœud renvoie des messages,
    # LangGraph les AJOUTE à la liste existante au lieu de la remplacer.
    # C'est ainsi que la conversation s'allonge de question en question.
    # (Tous les autres champs, eux, sont simplement REMPLACÉS par la nouvelle valeur.)
    messages: Annotated[list, add_messages]

    # --- Remplis par les nœuds ---
    plan: Plan                # planner
    passages: list[dict]      # retriever : les extraits trouvés, fusionnés et triés
    answer: str               # responder : la réponse
    sources: list[dict]       # responder : les sources citées dans la réponse
    action_id: str | None     # email_drafter : l'email en attente de validation (ou None)


def recent_history(state: State):
    """Les derniers messages de la conversation (questions et réponses).

    [-HISTORY_MESSAGES:] : les 6 derniers éléments de la liste (moins s'il y en a moins).
    .get("messages", []) : liste vide pour la toute première question.
    """
    return state.get("messages", [])[-HISTORY_MESSAGES:]
