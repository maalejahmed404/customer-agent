"""L'agent LangGraph : assemble les 4 nœuds en un graphe.

C'EST QUOI LANGGRAPH ?
    Une librairie pour décrire un agent comme un GRAPHE :
      - des NŒUDS   = des fonctions (ici async) qui lisent l'état et renvoient des changements,
      - des ARÊTES  = l'ordre d'exécution, fixes ou conditionnelles (un "if" entre deux nœuds),
      - un ÉTAT     = le dict partagé qui circule de nœud en nœud (voir agent/state.py).

LE GRAPHE

    START
      │
      ▼
    planner ───── pas besoin de données (salutation...) ─────┐
      │                                                      │
      │ besoin de données                                    │
      ▼                                                      │
    retriever                                                │
      │                                                      │
      ▼                                                      │
    responder ◄──────────────────────────────────────────────┘
      │
      ├── email demandé ──► email_drafter ──► END
      └── sinon ─────────────────────────────► END

- planner       (nodes/planner.py)       : le LLM décide quoi chercher
- retriever     (nodes/retriever.py)     : les recherches partent en parallèle vers le serveur MCP
- responder     (nodes/responder.py)     : le LLM répond en citant ses sources [1], [2]
- email_drafter (nodes/email_drafter.py) : le LLM rédige l'email -> action "pending"

MÉMOIRE DES CONVERSATIONS (le "checkpointer")
    Avec un checkpointer (MongoDB dans l'API), LangGraph sauvegarde l'état de chaque
    conversation après chaque nœud, sous un identifiant appelé "thread_id".
    À la question suivante sur le même thread_id, LangGraph recharge cet état : le champ
    `messages` contient alors les questions/réponses précédentes. C'est ce qui permet les
    relances ("et le prix ?"). Sans checkpointer (tests), chaque question part de zéro.

QUI LANCE L'AGENT ?
    L'agent n'a pas de serveur HTTP à lui : il est créé par api/dependencies.py (get_agent)
    et lancé par l'API dans POST /chat (api/routes/chat.py) avec agent.ainvoke(...).
"""

from langgraph.graph import END, START, StateGraph

from agent.nodes.email_drafter import email_drafter_node
from agent.nodes.planner import planner_node
from agent.nodes.responder import responder_node
from agent.nodes.retriever import retriever_node
from agent.state import State

# ------------------------------------------------------- fonctions de "routage"
# Une fonction de routage reçoit l'état et renvoie le NOM du prochain nœud (ou END).
# LangGraph l'appelle après le nœud concerné pour savoir où aller.

def route_after_planner(state: State):
    """Pas de recherche pour les salutations et les questions hors sujet."""
    return "retriever" if state["plan"].needs_data else "responder"


def route_after_responder(state: State):
    """On ne rédige un email que si l'utilisateur l'a demandé."""
    return "email_drafter" if state["plan"].draft_email else END


# ---------------------------------------------------------- construction du graphe

def build_graph(checkpointer=None):
    """Construit et renvoie l'agent, prêt à être lancé avec `await agent.ainvoke(...)`.

    checkpointer : où sauvegarder les conversations (MongoDBSaver dans l'API,
                   InMemorySaver ou None dans les tests). None = pas de mémoire.
    """
    # Un graphe dont l'état a la forme de `State`
    graph = StateGraph(State)

    # 1. Les nœuds : un nom (utilisé dans les arêtes et sur le dessin) -> une fonction
    graph.add_node("planner", planner_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("responder", responder_node)
    graph.add_node("email_drafter", email_drafter_node)

    # 2. Les arêtes
    # START -> planner : tout commence par le planner
    graph.add_edge(START, "planner")
    # Après le planner : la fonction de routage choisit entre "retriever" et "responder".
    # La liste donne les destinations possibles (utile pour dessiner le graphe).
    graph.add_conditional_edges("planner", route_after_planner, ["retriever", "responder"])
    # Après le retriever : toujours le responder
    graph.add_edge("retriever", "responder")
    # Après le responder : email_drafter ou fin
    graph.add_conditional_edges("responder", route_after_responder, ["email_drafter", END])
    # Après l'email_drafter : fin
    graph.add_edge("email_drafter", END)

    # 3. "Compiler" : vérifie que le graphe est cohérent (pas de nœud orphelin...) et
    #    renvoie un objet exécutable. Le checkpointer est branché ici.
    return graph.compile(checkpointer=checkpointer)
