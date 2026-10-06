"""Des faux pour le LLM et les embeddings : pas de clé API, et toujours le même résultat."""

import hashlib
import re

from langchain_core.messages import AIMessage


def fake_vector(text):
    """Vecteur "sac de mots" déterministe : deux textes qui partagent des mots ont des vecteurs proches."""
    vector = [0.0] * 256
    for word in re.findall(r"\w+", text.lower()):
        vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % 256] += 1.0
    return vector


class FakeLLM:
    """Remplace ChatOpenAI : renvoie un plan, une réponse et un brouillon d'email fixés à l'avance.

    Un plan ou un brouillon peut être une exception, pour simuler une panne du modèle.
    Chaque prompt reçu est gardé dans `prompts`.
    """

    def __init__(self, plan=None, answer="OK", draft=None):
        self.plan, self.answer, self.draft = plan, answer, draft
        self.prompts = []

    def with_structured_output(self, schema, **kwargs):
        fake = self

        class Structured:
            async def ainvoke(self, prompt):
                fake.prompts.append(prompt)
                value = fake.plan if schema.__name__ == "Plan" else fake.draft
                if isinstance(value, Exception):
                    raise value
                return value

        return Structured()

    async def ainvoke(self, messages):
        self.prompts.append(messages)
        return AIMessage(content=self.answer)
