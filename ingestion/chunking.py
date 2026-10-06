"""Découper un long texte en morceaux ("chunks").

POURQUOI DÉCOUPER ?
    Un appel peut faire des milliers de caractères et parler de 10 sujets. Si on le
    gardait en un seul bloc :
      - son embedding serait un "mélange" de tous les sujets -> recherche par le sens imprécise,
      - on enverrait tout l'appel au LLM alors qu'un seul paragraphe est utile -> coûteux.
    En morceaux d'environ 1200 caractères, chaque chunk parle d'un sujet précis.

POURQUOI UN CHEVAUCHEMENT ?
    Les morceaux se chevauchent de 200 caractères : une idée coupée entre deux morceaux
    reste entière dans au moins l'un des deux.

    texte :   [=========== morceau 1 ===========]
                                     [=========== morceau 2 ===========]
                                     <-- 200 -->  (partie commune)
"""

CHUNK_SIZE = 1200    # taille visée d'un morceau, en caractères
CHUNK_OVERLAP = 200  # nombre de caractères repris au début du morceau suivant


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Renvoie une liste de morceaux d'environ `size` caractères, coupés sur des espaces.

    Exemple : un texte de 3000 caractères -> environ 3 morceaux de ~1200 caractères.
    Un texte court (<= size) -> une liste avec un seul morceau : [texte].
    """
    text = text.strip()  # enlever les espaces/sauts de ligne au début et à la fin
    if len(text) <= size:
        return [text]

    chunks = []
    start = 0  # position (index) du début du morceau en cours
    while True:
        # Fin "idéale" du morceau : start + size, sans dépasser la fin du texte.
        end = min(start + size, len(text))

        # Si on n'est pas à la fin du texte, on évite de couper un mot en deux :
        # on recule jusqu'au dernier espace avant `end`.
        if end < len(text):
            space = text.rfind(" ", start, end)  # position du dernier espace, ou -1 si aucun
            # On n'accepte cet espace que s'il est dans la 2e moitié du morceau. Sinon (un
            # "mot" énorme, comme une URL très longue), on couperait trop court : on garde `end`.
            if space > start + size // 2:
                end = space

        chunks.append(text[start:end].strip())

        # Dernier morceau atteint : on a fini.
        if end == len(text):
            return chunks

        # Le morceau suivant commence `overlap` caractères AVANT la fin de celui-ci :
        # c'est ce qui crée le chevauchement.
        start = end - overlap
