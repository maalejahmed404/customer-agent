"""Validation humaine des actions (aujourd'hui : envoyer un email).

CYCLE DE VIE D'UNE ACTION (champ "status" dans la collection "actions")

    pending ──(approve)──► approved ──► sent     (ou "failed" si l'envoi échoue)
       │
       └─────(reject)───► rejected

QUI FAIT QUOI ?
    - L'agent peut seulement PROPOSER (propose -> "pending"). Il n'a aucun moyen d'envoyer.
      (appelé par agent/nodes/email_drafter.py)
    - Seul un utilisateur connecté du MÊME compte peut approuver ou refuser, via l'API.
      (appelé par api/routes/actions.py)
    - Le changement de statut est ATOMIQUE : une action n'est exécutée qu'une seule fois,
      même en cas de double clic (voir decide).

EXEMPLE DE DOCUMENT
    {"_id": ObjectId(...), "account_id": 1, "kind": "send_email",
     "payload": {"to": ["helene@clinique.fr"], "subject": "...", "body": "..."},
     "status": "pending", "proposed_by": "camille@vendor.fr", "created_at": ...}
"""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument

from actions import email_sender


def now():
    """L'heure actuelle en UTC (on stocke toujours les dates en UTC pour éviter les soucis de fuseau)."""
    return datetime.now(timezone.utc)


async def propose(db, account_id, proposed_by, kind, payload):
    """Enregistre une action "pending". Renvoie son id (texte). N'exécute RIEN.

    kind    : le type d'action ("send_email")
    payload : le contenu de l'action (pour un email : to, subject, body)
    """
    result = await db.actions.insert_one({
        "account_id": account_id, "kind": kind, "payload": payload, "status": "pending",
        "proposed_by": proposed_by, "created_at": now(),
    })
    # inserted_id est un ObjectId : on le convertit en texte pour le renvoyer en JSON
    return str(result.inserted_id)


async def list_actions(db, account_id, status=None):
    """Les 50 dernières actions du compte (filtrées par statut si demandé, ex. "pending").

    Utilisé par l'interface pour afficher la liste "Actions en attente".
    """
    query = {"account_id": account_id}  # toujours limité au compte de l'utilisateur
    if status:
        query["status"] = status
    # sort("created_at", -1) : les plus récentes d'abord ; to_list(50) : 50 au maximum
    actions = await db.actions.find(query).sort("created_at", -1).to_list(50)
    for action in actions:
        # "_id" (ObjectId) -> "id" (texte) pour que ce soit lisible en JSON
        action["id"] = str(action.pop("_id"))
    return actions


async def decide(db, account_id, action_id, user_email, approve):
    """Approuve (et exécute) ou refuse une action "pending" du compte de l'utilisateur.

    approve : True = approuver et envoyer ; False = refuser.
    Renvoie l'action mise à jour, ou None s'il n'y a pas d'action "pending" avec cet id
    dans ce compte (mauvais id, autre compte, ou déjà décidée). L'API transforme None en 404.
    """
    # Un id invalide ("abc") -> None plutôt qu'une erreur 500
    try:
        _id = ObjectId(action_id)
    except (InvalidId, TypeError):
        return None

    # ÉTAPE CLÉ : find_one_and_update cherche ET modifie en UNE SEULE opération atomique.
    # Le filtre exige les 3 conditions en même temps :
    #   - le bon id,
    #   - le compte de l'utilisateur (un autre compte ne trouve rien),
    #   - status == "pending" (une action déjà décidée ne trouve rien).
    # Si deux clics arrivent en même temps, MongoDB garantit qu'un seul modifie le document ;
    # pour le second, le statut n'est plus "pending" -> None -> pas de double envoi.
    action = await db.actions.find_one_and_update(
        {"_id": _id, "account_id": account_id, "status": "pending"},
        {"$set": {"status": "approved" if approve else "rejected",
                  "decided_by": user_email,   # QUI a décidé (traçabilité)
                  "decided_at": now()}},      # QUAND
        # renvoyer le document APRÈS modification (par défaut ce serait l'ancien)
        return_document=ReturnDocument.AFTER,
    )
    if action is None:
        return None

    # Si approuvée : on exécute (on envoie l'email) et on enregistre le résultat.
    if approve:
        try:
            # execute renvoie "smtp" ou "outbox" : la façon dont l'email a été "livré"
            update = {"status": "sent", "delivery": await email_sender.execute(db, action)}
        except Exception as exc:
            # L'envoi a échoué (serveur SMTP injoignable...) : on le note, sans planter l'API.
            # L'action reste consultable avec l'erreur.
            update = {"status": "failed", "error": str(exc)}
        await db.actions.update_one({"_id": _id}, {"$set": update})
        action.update(update)  # mettre à jour aussi la copie qu'on va renvoyer

    action["id"] = str(action.pop("_id"))
    return action
