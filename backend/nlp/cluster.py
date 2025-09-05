from sklearn.cluster import KMeans
import numpy as np

def kmeans_clusters(vectors: np.ndarray, k: int, random_state: int = 42):
    if len(vectors) == 0:
        return np.array([]), None
    k = max(1, min(k, len(vectors)))
    km = KMeans(n_clusters=k, n_init=10, random_state=random_state)
    labels = km.fit_predict(vectors)
    return labels, km.cluster_centers_

def top_terms_for_cluster(texts: list[str], labels, k_top=3):
    # naive: choose the shortest/most central texts as hints
    # you can improve with c-TF-IDF later
    from collections import defaultdict
    groups = defaultdict(list)
    for t, l in zip(texts, labels):
        groups[l].append(t)
    hints = {}
    for l, g in groups.items():
        g_sorted = sorted(g, key=lambda x: len(x))
        sample = " | ".join(g_sorted[:2])
        hints[l] = sample[:120]
    return hints
