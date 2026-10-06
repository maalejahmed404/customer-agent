"""Assemblage du graphe LangGraph de l'agent.

    START -> planner -> retriever -> responder -> [email_drafter] -> END

Le planner court-circuite le retriever quand aucune donnée n'est nécessaire.
"""

from langgraph.graph import END, START, StateGraph

from agent.nodes.email_drafter import email_drafter_node
from agent.nodes.planner import planner_node
from agent.nodes.responder import responder_node
from agent.nodes.retriever import retriever_node
from agent.state import State


def route_after_planner(state: State):
    """Saute la recherche pour les salutations et les questions hors sujet."""
    return "retriever" if state["plan"].needs_data else "responder"


def route_after_responder(state: State):
    """Ne passe par email_drafter que si un email a été demandé."""
    return "email_drafter" if state["plan"].draft_email else END


def build_graph(checkpointer=None):
    """Compile le graphe de l'agent.

    Sans checkpointer (tests), aucune mémoire de conversation : chaque question
    repart d'un état vide.
    """
    graph = StateGraph(State)

    graph.add_node("planner", planner_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("responder", responder_node)
    graph.add_node("email_drafter", email_drafter_node)

    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", route_after_planner, ["retriever", "responder"])
    graph.add_edge("retriever", "responder")
    graph.add_conditional_edges("responder", route_after_responder, ["email_drafter", END])
    graph.add_edge("email_drafter", END)

    return graph.compile(checkpointer=checkpointer)
