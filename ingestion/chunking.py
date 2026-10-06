"""Découpage d'un texte en morceaux (chunks) qui se chevauchent.

Le chevauchement garantit qu'une idée coupée entre deux morceaux reste entière dans l'un d'eux.
"""

CHUNK_SIZE = 1200    # taille visée, en caractères
CHUNK_OVERLAP = 200  # caractères repris au début du morceau suivant


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Renvoie des morceaux d'environ `size` caractères, coupés de préférence sur une espace.

    Un texte de longueur <= size donne un seul morceau.
    """
    text = text.strip()
    if len(text) <= size:
        return [text]

    chunks = []
    start = 0
    while True:
        end = min(start + size, len(text))

        if end < len(text):
            space = text.rfind(" ", start, end)
            # Espace retenue seulement dans la seconde moitié : sinon (longue URL, par exemple)
            # le morceau serait trop court, et on coupe à `end`.
            if space > start + size // 2:
                end = space

        chunks.append(text[start:end].strip())

        if end == len(text):
            return chunks

        start = end - overlap
