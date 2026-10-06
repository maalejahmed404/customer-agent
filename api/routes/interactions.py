"""GET /interactions/{id} : texte complet d'un appel ou d'un email cité comme source."""

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_current_user
from shared import database, search

router = APIRouter(tags=["interactions"])


@router.get("/interactions/{interaction_id}")
async def get_interaction(interaction_id: str, user=Depends(get_current_user)):
    interaction = await search.get_interaction(database.get_db(), user["account_id"],
                                               interaction_id)
    if interaction is None:
        # 404 plutôt que 403 : ne révèle pas qu'un id existe dans un autre compte.
        raise HTTPException(404, "Introuvable")
    return interaction
