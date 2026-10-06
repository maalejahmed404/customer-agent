"""Endpoints des actions : lister, approuver, refuser les emails proposés par l'agent.

    GET  /actions?status=pending      la liste (l'interface l'affiche dans la barre latérale)
    POST /actions/{id}/approve        l'humain approuve -> l'email est envoyé
    POST /actions/{id}/reject         l'humain refuse   -> rien n'est envoyé

C'est le SEUL endroit où une action peut être approuvée : l'agent, lui, ne peut que proposer.
Toute la logique est dans actions/approval.py ; ce fichier ne fait que la relier au HTTP.
"""

from fastapi import APIRouter, Depends, HTTPException

# Attention aux noms : ce fichier s'appelle api/routes/actions.py, mais "from actions import"
# importe le dossier actions/ À LA RACINE du projet (les imports sont toujours absolus).
from actions import approval
from api.dependencies import get_current_user
from shared import database

router = APIRouter(tags=["actions"])


# `status: str | None = None` : paramètre optionnel lu dans l'URL (?status=pending)
@router.get("/actions")
async def list_actions(status: str | None = None, user=Depends(get_current_user)):
    # Seulement les actions du compte de l'utilisateur (account_id du token)
    return await approval.list_actions(database.get_db(), user["account_id"], status)


@router.post("/actions/{action_id}/approve")
async def approve_action(action_id: str, user=Depends(get_current_user)):
    return await decide(action_id, user, approve=True)


@router.post("/actions/{action_id}/reject")
async def reject_action(action_id: str, user=Depends(get_current_user)):
    return await decide(action_id, user, approve=False)


async def decide(action_id, user, approve):
    """Code commun à /approve et /reject (pas un endpoint : pas de @router)."""
    # L'email de l'utilisateur est enregistré comme "decided_by" (qui a approuvé/refusé)
    action = await approval.decide(database.get_db(), user["account_id"], action_id,
                                   user["email"], approve)
    if action is None:
        # Mauvais id, action d'un autre compte, ou déjà décidée (double clic)
        raise HTTPException(404, "Aucune action en attente avec cet id")
    return action
