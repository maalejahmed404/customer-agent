"""Validation humaine des actions proposées par l'agent (aujourd'hui : l'envoi d'email).

Statuts : pending -> approved -> sent | failed, ou pending -> rejected.
L'agent ne peut que proposer ; seul un utilisateur du même compte approuve ou refuse.
"""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument

from actions import email_sender


def now():
    """Renvoie l'heure courante en UTC."""
    return datetime.now(timezone.utc)


async def propose(db, account_id, proposed_by, kind, payload):
    """Enregistre une action « pending » et renvoie son id ; n'exécute rien."""
    result = await db.actions.insert_one({
        "account_id": account_id, "kind": kind, "payload": payload, "status": "pending",
        "proposed_by": proposed_by, "created_at": now(),
    })
    return str(result.inserted_id)


async def list_actions(db, account_id, status=None):
    """Renvoie les 50 dernières actions du compte, filtrées par statut si demandé."""
    query = {"account_id": account_id}
    if status:
        query["status"] = status
    actions = await db.actions.find(query).sort("created_at", -1).to_list(50)
    for action in actions:
        action["id"] = str(action.pop("_id"))
    return actions


async def decide(db, account_id, action_id, user_email, approve):
    """Approuve (et exécute) ou refuse une action « pending » du compte.

    Renvoie l'action mise à jour, ou None si aucune action « pending » ne porte cet id
    dans ce compte (id invalide, autre compte, action déjà décidée).
    """
    try:
        _id = ObjectId(action_id)
    except (InvalidId, TypeError):
        return None

    # find_one_and_update est atomique : sur deux décisions concurrentes, une seule trouve
    # le statut « pending », ce qui exclut un double envoi.
    action = await db.actions.find_one_and_update(
        {"_id": _id, "account_id": account_id, "status": "pending"},
        {"$set": {"status": "approved" if approve else "rejected",
                  "decided_by": user_email,
                  "decided_at": now()}},
        return_document=ReturnDocument.AFTER,
    )
    if action is None:
        return None

    if approve:
        try:
            update = {"status": "sent", "delivery": await email_sender.execute(db, action)}
        except Exception as exc:
            # L'échec d'envoi est consigné sur l'action plutôt que propagé à l'API.
            update = {"status": "failed", "error": str(exc)}
        await db.actions.update_one({"_id": _id}, {"$set": update})
        action.update(update)

    action["id"] = str(action.pop("_id"))
    return action
