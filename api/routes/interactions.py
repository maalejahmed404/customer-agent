"""GET /interactions/{id} : le texte complet d'un appel ou d'un email.

Utilisé par le bouton "Voir la source complète" de l'interface : chaque source citée
contient un interaction_id, qu'on passe ici pour afficher le document entier.
"""

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_current_user
from shared import database, search

router = APIRouter(tags=["interactions"])


# {interaction_id} dans le chemin : FastAPI met la valeur de l'URL dans le paramètre
# du même nom. Ex. GET /interactions/665f1c... -> interaction_id = "665f1c..."
@router.get("/interactions/{interaction_id}")
async def get_interaction(interaction_id: str, user=Depends(get_current_user)):
    # La recherche est limitée au compte du TOKEN : avec l'id d'un document d'un autre
    # compte, on ne trouve rien.
    interaction = await search.get_interaction(database.get_db(), user["account_id"],
                                               interaction_id)
    if interaction is None:
        # 404 dans les deux cas (n'existe pas / autre compte) : on ne révèle rien.
        raise HTTPException(404, "Introuvable")
    return interaction
