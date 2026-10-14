from functools import lru_cache

import numpy as np

from .config import EMBED_MODEL


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(EMBED_MODEL)


def embed(texts: list[str]) -> np.ndarray:
    vecs = np.array(list(_model().embed(texts, batch_size=64)), dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12
    return vecs


def embed_query(text: str) -> np.ndarray:
    # bge models are trained with this prefix on queries (not on passages)
    return embed(["Represent this sentence for searching relevant passages: " + text])[0]
