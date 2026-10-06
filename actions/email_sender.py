"""Exécution d'une action approuvée : envoi de l'email.

Sans SMTP_HOST, l'email n'est pas envoyé mais rangé dans la collection « outbox ».
"""

import asyncio
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

from shared.config import settings


async def execute(db, action):
    """Envoie l'email de l'action ; renvoie « smtp » ou « outbox » selon le mode de livraison.

    Lève ValueError pour un type d'action inconnu.
    """
    if action["kind"] != "send_email":
        raise ValueError(f"Unknown action: {action['kind']}")
    email = action["payload"]

    if settings.smtp_host:
        # smtplib est bloquant : exécuté dans un thread pour ne pas figer la boucle asyncio.
        await asyncio.to_thread(send_smtp, email)
        return "smtp"

    # Repli sans SMTP : le parcours complet reste testable sans envoi réel.
    await db.outbox.insert_one({**email, "account_id": action["account_id"],
                                "sent_at": datetime.now(timezone.utc)})
    return "outbox"


def send_smtp(email):
    """Envoie l'email par SMTP (appel bloquant)."""
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = ", ".join(email["to"])
    message["Subject"] = email["subject"]
    message.set_content(email["body"])

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.starttls()
        # Certains relais internes n'exigent pas d'authentification.
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)
