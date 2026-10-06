"""Exécution d'une action APPROUVÉE : l'envoi de l'email.

Appelé uniquement par actions/approval.py -> decide(), APRÈS l'approbation d'un humain.

DEUX MODES
    - SMTP_HOST configuré : envoi réel par SMTP (ex. Office 365 : smtp.office365.com:587).
    - SMTP_HOST vide (démo en local) : l'email n'est PAS envoyé, il est rangé dans la
      collection MongoDB "outbox". On peut ainsi tester tout le parcours sans risque
      d'envoyer un vrai email.
"""

import asyncio
import smtplib  # librairie standard Python pour envoyer des emails
from datetime import datetime, timezone
from email.message import EmailMessage  # pour construire un email (headers + contenu)

from shared.config import settings


async def execute(db, action):
    """Envoie l'email de l'action. Renvoie "smtp" ou "outbox" selon ce qui a été fait."""
    # Pour l'instant, seul le type "send_email" existe. Un type inconnu = erreur
    # (decide() la transforme en status "failed").
    if action["kind"] != "send_email":
        raise ValueError(f"Unknown action: {action['kind']}")
    email = action["payload"]  # {"to": [...], "subject": "...", "body": "..."}

    if settings.smtp_host:
        # smtplib est BLOQUANT (il attend le serveur SMTP sans rendre la main).
        # asyncio.to_thread le lance dans un thread séparé : pendant l'envoi, l'API continue
        # de répondre aux autres utilisateurs.
        await asyncio.to_thread(send_smtp, email)
        return "smtp"

    # Pas de SMTP : on range l'email dans "outbox" (avec le compte et l'heure).
    # {**email, ...} : une copie de l'email avec des champs en plus.
    await db.outbox.insert_one({**email, "account_id": action["account_id"],
                                "sent_at": datetime.now(timezone.utc)})
    return "outbox"


def send_smtp(email):
    """Envoie réellement l'email par SMTP (fonction normale, exécutée dans un thread)."""
    # 1. Construire le message
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = ", ".join(email["to"])  # plusieurs destinataires séparés par des virgules
    message["Subject"] = email["subject"]
    message.set_content(email["body"])

    # 2. Se connecter au serveur, sécuriser, s'authentifier, envoyer.
    #    "with" ferme la connexion automatiquement à la fin.
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.starttls()  # passer la connexion en chiffré (TLS) avant d'envoyer le mot de passe
        if settings.smtp_user:  # certains serveurs internes n'exigent pas d'authentification
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)
