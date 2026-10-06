"""Sécurité : mots de passe et tokens JWT.

RÔLE
    - hash_password / verify_password : stocker et vérifier un mot de passe SANS le garder en clair
    - create_token / decode_token     : créer et vérifier les tokens JWT

C'EST QUOI UN TOKEN JWT ?
    Une chaîne de texte en 3 parties "entête.contenu.signature". Le contenu est lisible
    (ex. {"sub": "camille@vendor.fr", "account_id": 1, "exp": ...}), mais la SIGNATURE
    est calculée avec JWT_SECRET : sans connaître le secret, impossible de modifier le
    contenu (par exemple changer account_id) sans que la vérification échoue.

    Parcours : /login crée le token -> l'interface l'envoie à chaque requête
    (header "Authorization: Bearer <token>") -> l'API et le serveur MCP le vérifient.

RÈGLE D'OR
    L'account_id contenu dans le token est la SEULE source de vérité pour savoir à quel
    compte appartient une requête. On ne lit jamais l'account_id dans le corps d'une
    requête ni dans l'argument d'un outil MCP.
"""

import hashlib  # fonctions de hachage (ici PBKDF2 avec SHA-256)
import secrets  # nombres aléatoires sûrs pour la cryptographie + comparaison sécurisée
import time

import jwt  # la librairie PyJWT

from shared.config import settings

# HS256 = signature HMAC avec SHA-256 : le même secret sert à signer et à vérifier.
ALGORITHM = "HS256"

# Nombre de tours de hachage des mots de passe. Plus il y en a, plus le hachage est lent :
# c'est voulu ! Vérifier UN mot de passe reste rapide (quelques ms), mais un pirate qui
# essaie des millions de mots de passe est fortement ralenti.
PASSWORD_ITERATIONS = 200_000


def get_secret():
    """Renvoie JWT_SECRET, ou refuse de continuer s'il est absent ou trop court.

    Un secret court peut être deviné par force brute : n'importe qui pourrait alors
    fabriquer un token valide pour n'importe quel compte. Mieux vaut planter au démarrage.
    """
    if len(settings.jwt_secret) < 32:
        raise RuntimeError("JWT_SECRET must be set and at least 32 characters long")
    return settings.jwt_secret


# ------------------------------------------------------------------ mots de passe

def hash_password(password):
    """Transforme un mot de passe en "sel$empreinte". Le mot de passe lui-même n'est jamais stocké.

    - Le SEL est une valeur aléatoire différente pour chaque utilisateur : deux personnes
      avec le même mot de passe ont des empreintes différentes, et les tables de mots de
      passe pré-calculées ("rainbow tables") deviennent inutiles.
    - L'EMPREINTE est calculée avec PBKDF2 (hachage répété 200 000 fois).
    Exemple de résultat : "9f86d081884c7d65...$5e884898da28047151d0e56f8dc62927..."
    """
    salt = secrets.token_hex(16)  # 16 octets aléatoires, écrits en hexadécimal (32 caractères)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(),
                                 PASSWORD_ITERATIONS).hex()
    return f"{salt}${digest}"


def verify_password(password, stored):
    """Vérifie un mot de passe contre la valeur stockée "sel$empreinte".

    On ne peut pas "déchiffrer" l'empreinte : on refait le même calcul avec le même sel
    et on compare les deux résultats.
    """
    salt, digest = stored.split("$")  # sépare le sel et l'empreinte
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(),
                                PASSWORD_ITERATIONS).hex()
    # compare_digest compare en TEMPS CONSTANT : un "==" classique s'arrête au premier
    # caractère différent, et un attaquant pourrait mesurer ce temps pour deviner l'empreinte.
    return secrets.compare_digest(check, digest)


# --------------------------------------------------------------------- tokens JWT

def create_token(email, account_id):
    """Crée un token signé pour cet utilisateur et ce compte (appelé au login, et par l'agent)."""
    payload = {
        "sub": email,               # "subject" : QUI est l'utilisateur (nom standard en JWT)
        "account_id": account_id,   # À QUEL compte il a accès
        # "exp" (expiration) : un timestamp Unix (secondes depuis 1970). Après cette date,
        # decode_token refusera le token automatiquement.
        "exp": int(time.time()) + settings.jwt_expire_minutes * 60,
    }
    return jwt.encode(payload, get_secret(), algorithm=ALGORITHM)


def decode_token(token):
    """Vérifie un token et renvoie son contenu (un dict).

    Lève une exception jwt.PyJWTError si :
      - la signature est fausse (token modifié ou signé avec un autre secret),
      - il est expiré ("exp" dépassé),
      - il manque un des champs obligatoires "sub", "account_id" ou "exp".
    """
    # algorithms=[ALGORITHM] : on accepte UNIQUEMENT HS256. Sans cette liste, un attaquant
    # pourrait envoyer un token avec l'algorithme "none" (pas de signature du tout).
    return jwt.decode(token, get_secret(), algorithms=[ALGORITHM],
                      options={"require": ["sub", "account_id", "exp"]})
