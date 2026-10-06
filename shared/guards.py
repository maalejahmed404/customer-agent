"""Garde-fous contre l'injection de prompt et validation des entrées.

Le contenu des emails et des appels vient de tiers : il est traité comme une donnée,
jamais comme une instruction. Défense en couches : marqueurs aléatoires (wrap_untrusted),
suppression des caractères cachés (sanitize), et approbation humaine de tout envoi
(actions/approval.py).
"""

import re
import secrets

MAX_QUESTION_CHARS = 2000

# Caractères de contrôle ASCII, hors tabulation, saut de ligne et retour chariot.
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Caractères invisibles (largeur zéro, marques directionnelles, BOM), utilisés pour
# dissimuler des instructions dans un email.
HIDDEN_CHARS = re.compile("[​-‏‪-‮⁠-⁤﻿]")

# Toute séquence pouvant imiter nos marqueurs de données.
MARKERS = re.compile(r"<{3,}|>{3,}")

# Une seule adresse : espaces, chevrons, virgules et points-virgules sont refusés pour
# empêcher d'en glisser plusieurs dans un même champ.
EMAIL = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[A-Za-z]{2,}$")


def clean_question(question):
    """Nettoie la question de l'utilisateur ; lève ValueError si elle est vide ou trop longue."""
    question = CONTROL_CHARS.sub("", question).strip()
    if not question:
        raise ValueError("La question est vide.")
    if len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"La question dépasse {MAX_QUESTION_CHARS} caractères.")
    return question


def sanitize(text):
    """Supprime les caractères cachés et toute séquence pouvant imiter nos marqueurs."""
    return MARKERS.sub("", HIDDEN_CHARS.sub("", text))


def wrap_untrusted(text):
    """Entoure un texte non fiable de marqueurs à tag aléatoire, renouvelé à chaque appel.

    Un contenu rédigé à l'avance ne peut ni deviner le marqueur de fin ni en forger un,
    sanitize() ayant retiré tous les chevrons triples.
    """
    tag = secrets.token_hex(6)
    return f"<<<DATA {tag}>>>\n{sanitize(text)}\n<<<END DATA {tag}>>>"


def is_valid_email(address):
    """Indique si `address` est une adresse email unique et bien formée."""
    return bool(EMAIL.match(address))
