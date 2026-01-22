import os
from collections import defaultdict

import numpy as np

from app.db import get_psycopg_conn
from app.services.retrieval_pgvector import parse_vector


def normalize_scores(values):
    if not values:
        return []
    min_val = min(values)
    max_val = max(values)
    if max_val - min_val == 0:
        return [0.0 for _ in values]
    return [(v - min_val) / (max_val - min_val) for v in values]


def load_user_top_nodes(conn, user_id: str):
    sql = """
        SELECT category, subcategory, underexplored_score
        FROM user_top_nodes
        WHERE user_id = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (user_id,))
        rows = cur.fetchall()

    node_map = {}
    scores = []
    for category, subcategory, score in rows:
        key = (category or "", subcategory or "")
        score_val = float(score or 0.0)
        node_map[key] = score_val
        scores.append(score_val)

    normalized = normalize_scores(scores)
    normalized_map = {}
    for idx, key in enumerate(node_map.keys()):
        normalized_map[key] = normalized[idx]

    return normalized_map


def fetch_embeddings(conn, news_ids):
    if not news_ids:
        return {}
    sql = "SELECT news_id, embedding FROM items WHERE news_id = ANY(%s)"
    with conn.cursor() as cur:
        cur.execute(sql, (news_ids,))
        rows = cur.fetchall()
    return {row[0]: parse_vector(row[1]) for row in rows}


def compute_weights(explore_level: float):
    explore_level = max(0.0, min(1.0, explore_level))
    w_rel_base = float(os.getenv("W_REL_BASE", 1.0))
    w_top_base = float(os.getenv("W_TOP_BASE", 0.5))
    w_rep_base = float(os.getenv("W_REP_BASE", 0.6))
    w_cov_base = float(os.getenv("W_COV_BASE", 0.4))

    if explore_level <= 0.0:
        return w_rel_base, 0.0, 0.0, 0.0

    w_rel = w_rel_base * (1.0 - 0.7 * explore_level)
    w_top = w_top_base * (0.3 + 0.7 * explore_level)
    w_rep = w_rep_base * (0.3 + 0.7 * explore_level)
    w_cov = w_cov_base * (0.3 + 0.7 * explore_level)

    return w_rel, w_top, w_rep, w_cov


def diversify_greedy(user_id, candidates, reranker_scores, explore_level: float, k: int):
    if not candidates:
        return [], {
            "unique_categories": 0,
            "unique_subcategories": 0,
            "ild_proxy": 0.0,
        }

    conn = get_psycopg_conn()
    try:
        top_nodes = load_user_top_nodes(conn, user_id)
    finally:
        conn.close()

    rel_scores = normalize_scores(reranker_scores)

    w_rel, w_top, w_rep, w_cov = compute_weights(explore_level)
    if explore_level <= 0.0:
        max_subcat = 1_000_000
        max_cat = 1_000_000
    else:
        max_subcat = int(os.getenv("MAX_SUBCAT_PER_FEED", "3"))
        max_cat = int(os.getenv("MAX_CAT_PER_FEED", "8"))

    selected = []
    selected_categories = set()
    selected_subcategories = set()
    cat_counts = defaultdict(int)
    subcat_counts = defaultdict(int)

    for _ in range(min(k, len(candidates))):
        best_idx = None
        best_score = None
        best_breakdown = None

        for idx, cand in enumerate(candidates):
            if cand.get("_selected"):
                continue

            category = cand.get("category") or ""
            subcategory = cand.get("subcategory") or ""
            key = (category, subcategory)
            top_bonus = top_nodes.get(key, 0.0)

            if category and cat_counts[category] >= max_cat:
                continue
            if subcategory and subcat_counts[subcategory] >= max_subcat:
                continue

            redundancy_penalty = 0.0
            if subcategory and subcategory in selected_subcategories:
                redundancy_penalty = 1.0
            elif category and category in selected_categories:
                redundancy_penalty = 0.5

            coverage_gain = 0.0
            if subcategory and subcategory not in selected_subcategories:
                coverage_gain = 1.0
            elif category and category not in selected_categories:
                coverage_gain = 0.5

            rel_score = rel_scores[idx]

            total_score = (
                w_rel * rel_score
                + w_top * top_bonus
                - w_rep * redundancy_penalty
                + w_cov * coverage_gain
            )

            if best_score is None or total_score > best_score:
                best_score = total_score
                best_idx = idx
                best_breakdown = {
                    "rel_score": rel_score,
                    "top_bonus": top_bonus,
                    "redundancy_penalty": redundancy_penalty,
                    "coverage_gain": coverage_gain,
                    "total_score": total_score,
                }

        if best_idx is None:
            break

        item = dict(candidates[best_idx])
        item.update(best_breakdown)
        item["top_path"] = (
            f"{item.get('category')}/{item.get('subcategory')}"
            if item.get("subcategory")
            else item.get("category")
        )
        candidates[best_idx]["_selected"] = True

        selected.append(item)
        if item.get("category"):
            selected_categories.add(item["category"])
            cat_counts[item["category"]] += 1
        if item.get("subcategory"):
            selected_subcategories.add(item["subcategory"])
            subcat_counts[item["subcategory"]] += 1

    ild_proxy = 0.0
    if len(selected) > 1:
        conn = get_psycopg_conn()
        try:
            ids = [item["news_id"] for item in selected]
            emb_map = fetch_embeddings(conn, ids)
        finally:
            conn.close()

        vectors = [vec for vec in (emb_map.get(item["news_id"]) for item in selected) if vec is not None]
        if len(vectors) >= 2:
            mat = np.vstack(vectors).astype(np.float32)
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            mat = mat / norms
            sim = mat @ mat.T
            n = sim.shape[0]
            upper = sim[np.triu_indices(n, k=1)]
            ild_proxy = float(1.0 - float(np.mean(upper))) if upper.size else 0.0

    metrics = {
        "unique_categories": len(selected_categories),
        "unique_subcategories": len(selected_subcategories),
        "ild_proxy": ild_proxy,
    }

    return selected, metrics
