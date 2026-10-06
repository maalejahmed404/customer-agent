"""Le modèle de langage (LLM).

RÔLE
    Créer le client du LLM utilisé par les nœuds planner, responder et email_drafter.

POURQUOI "COMPATIBLE OPENAI" ?
    Presque tous les fournisseurs (Lightning AI, Azure OpenAI, OpenAI, Groq, Ollama, vLLM...)
    proposent la même API que OpenAI. On utilise donc le client OpenAI de LangChain et on
    change seulement l'adresse : changer de fournisseur = changer LLM_BASE_URL, LLM_API_KEY
    et CHAT_MODEL, sans toucher au code.

POURQUOI UNE FONCTION (et pas une variable globale) ?
    Les nœuds appellent `llm.get_llm()` à chaque fois. Dans les tests, on remplace cette
    fonction par une qui renvoie un faux LLM (tests/fakes.py -> FakeLLM) : aucune clé API
    n'est nécessaire et les réponses sont toujours les mêmes.
"""

from langchain_openai import ChatOpenAI

from shared.config import settings


def get_llm():
    """Renvoie un client de chat prêt à l'emploi.

    Utilisations dans les nœuds :
        await get_llm().ainvoke(messages)                          -> une réponse texte
        get_llm().with_structured_output(Plan).ainvoke(prompt)     -> un objet Plan rempli
    """
    return ChatOpenAI(model=settings.chat_model, api_key=settings.llm_api_key,
                      # "or None" : si l'adresse est vide, None = adresse officielle d'OpenAI
                      base_url=settings.llm_base_url or None,
                      # temperature=0 : le modèle choisit toujours le mot le plus probable ->
                      # réponses stables et factuelles (pas de "créativité" pour ce métier).
                      temperature=0)
