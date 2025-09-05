from sentence_transformers import SentenceTransformer
import numpy as np

# Load once per process
_model = None
def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model

def embed_texts(texts: list[str]) -> np.ndarray:
    model = get_model()
    # normalize for clustering robustness
    vecs = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return np.asarray(vecs, dtype="float32")
