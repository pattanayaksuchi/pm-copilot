from sentence_transformers import SentenceTransformer
import numpy as np
import os

# Load once per process, explicitly on CPU to avoid MPS/meta tensor issues on macOS.
_model = None


def get_model():
    global _model
    if _model is None:
        device = os.getenv("EMBEDDING_DEVICE", "cpu")  # cpu|cuda
        try:
            _model = SentenceTransformer("all-MiniLM-L6-v2", device=device)
        except NotImplementedError:
            # Fallback to CPU if a meta-tensor/device issue occurs
            _model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
    return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    model = get_model()
    # normalize for clustering robustness
    vecs = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return np.asarray(vecs, dtype="float32")
