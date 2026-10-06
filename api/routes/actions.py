"""GET /actions, POST /actions/{id}/approve et /reject : validation humaine des emails proposés.

Seul point d'approbation : l'agent ne peut que proposer. La logique est dans actions/approval.py.
"""

from fastapi import APIRouter, Depends, HTTPException

# Le paquet actions/ de la racine du projet, pas ce module.
from actions import approval
from api.dependencies import get_current_user
from shared import database

router = APIRouter(tags=["actions"])


@router.get("/actions")
async def list_actions(status: str | None = None, user=Depends(get_current_user)):
    return await approval.list_actions(database.get_db(), user["account_id"], status)


@router.post("/actions/{action_id}/approve")
async def approve_action(action_id: str, user=Depends(get_current_user)):
    return await decide(action_id, user, approve=True)


@router.post("/actions/{action_id}/reject")
async def reject_action(action_id: str, user=Depends(get_current_user)):
    return await decide(action_id, user, approve=False)


async def decide(action_id, user, approve):
    """Approuve ou refuse une action en attente du compte ; l'email du décideur est tracé."""
    action = await approval.decide(database.get_db(), user["account_id"], action_id,
                                   user["email"], approve)
    if action is None:
        # 404 unique : id inconnu, action d'un autre compte ou déjà décidée.
        raise HTTPException(404, "Aucune action en attente avec cet id")
    return action
