"""Hachage des mots de passe (PBKDF2) et jetons JWT.

L'account_id du jeton est la seule source de vérité sur le compte d'une requête.
"""

import hashlib
import secrets
import time

import jwt

from shared.config import settings

ALGORITHM = "HS256"
PASSWORD_ITERATIONS = 200_000


def get_secret():
    """Renvoie JWT_SECRET ; lève RuntimeError s'il est absent ou trop court pour résister à la force brute."""
    if len(settings.jwt_secret) < 32:
        raise RuntimeError("JWT_SECRET must be set and at least 32 characters long")
    return settings.jwt_secret


# ------------------------------------------------------------------ mots de passe

def hash_password(password):
    """Renvoie "sel$empreinte" (PBKDF2-SHA256, sel aléatoire propre à chaque appel)."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(),
                                 PASSWORD_ITERATIONS).hex()
    return f"{salt}${digest}"


def verify_password(password, stored):
    """Vérifie un mot de passe contre la valeur stockée "sel$empreinte"."""
    salt, digest = stored.split("$")
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(),
                                PASSWORD_ITERATIONS).hex()
    # Comparaison en temps constant : évite une attaque temporelle sur l'empreinte.
    return secrets.compare_digest(check, digest)


# --------------------------------------------------------------------- tokens JWT

def create_token(email, account_id):
    """Crée un jeton signé pour cet utilisateur et ce compte, valable jwt_expire_minutes."""
    payload = {
        "sub": email,
        "account_id": account_id,
        "exp": int(time.time()) + settings.jwt_expire_minutes * 60,
    }
    return jwt.encode(payload, get_secret(), algorithm=ALGORITHM)


def decode_token(token):
    """Vérifie un jeton et renvoie son contenu.

    Lève jwt.PyJWTError si la signature est invalide, si le jeton est expiré ou s'il
    manque l'un des champs "sub", "account_id", "exp".
    """
    # Algorithme épinglé : refuse notamment les jetons « alg: none ».
    return jwt.decode(token, get_secret(), algorithms=[ALGORITHM],
                      options={"require": ["sub", "account_id", "exp"]})
