"""Client du LLM, via une API compatible OpenAI.

Le fournisseur se change par configuration (LLM_BASE_URL, LLM_API_KEY, CHAT_MODEL).
"""

from langchain_openai import ChatOpenAI

from shared.config import settings


def get_llm():
    """Renvoie le client de chat ; les tests remplacent cette fonction par un faux LLM."""
    return ChatOpenAI(model=settings.chat_model, api_key=settings.llm_api_key,
                      # Adresse vide : endpoint OpenAI par défaut.
                      base_url=settings.llm_base_url or None,
                      # Réponses stables et factuelles.
                      temperature=0)
