from sklearn.cluster import KMeans
from .nlp.embeddings import get_model

def generate_themes(texts, n_clusters=10):
    # Lazily load the model when called to avoid initializing tokenizers at import time
    model = get_model()
    embeddings = model.encode(texts)
    clustering = KMeans(n_clusters=n_clusters, random_state=42)
    clustering.fit(embeddings)
    labels = clustering.labels_

    themes = {}
    for i, text in enumerate(texts):
        cluster_id = int(labels[i])
        themes.setdefault(cluster_id, []).append(text)

    return themes
