import json
import logging
import os
from datetime import datetime

import joblib
import numpy as np

from app.services.retrieval_pgvector import build_user_vector, get_user_click_history, parse_time, parse_vector


DEFAULT_MODEL_PATH = "/app/ml/models/reranker_baseline/model.joblib"
DEFAULT_CONFIG_PATH = "/app/ml/models/reranker_baseline/training_config.json"

_MODEL = None
_CONFIG = None

logger = logging.getLogger(__name__)


def load_model():
    global _MODEL, _CONFIG
    if _MODEL is not None and _CONFIG is not None:
        return _MODEL, _CONFIG

    model_path = os.getenv("RERANKER_MODEL_PATH", DEFAULT_MODEL_PATH)
    config_path = os.getenv("RERANKER_CONFIG_PATH", DEFAULT_CONFIG_PATH)

    if not os.path.isfile(model_path) or not os.path.isfile(config_path):
        logger.warning("Reranker disabled: missing model or config at %s / %s", model_path, config_path)
        return None, None

    _MODEL = joblib.load(model_path)
    with open(config_path, "r") as file:
        _CONFIG = json.load(file)

    logger.info("Loaded reranker model from %s", model_path)
    return _MODEL, _CONFIG


def get_item_embeddings(conn, news_ids):
    if not news_ids:
        return {}
    sql = """
        SELECT news_id, embedding, title, abstract, category, subcategory, url
        FROM items
        WHERE news_id = ANY(%s)
    """
    with conn.cursor() as cur:
        cur.execute(sql, (news_ids,))
        rows = cur.fetchall()
    return {
        row[0]: {
            "embedding": parse_vector(row[1]),
            "title": row[2],
            "abstract": row[3],
            "category": row[4],
            "subcategory": row[5],
            "url": row[6],
        }
        for row in rows
    }


def get_news_categories(conn, news_ids):
    if not news_ids:
        return {}
    sql = "SELECT news_id, category FROM items WHERE news_id = ANY(%s)"
    with conn.cursor() as cur:
        cur.execute(sql, (news_ids,))
        rows = cur.fetchall()
    return {row[0]: row[1] for row in rows}


def compute_features(candidate, item_data, user_vec, user_categories, user_last_time, config, rank_position):
    category = item_data.get("category")
    subcategory = item_data.get("subcategory")
    title = item_data.get("title") or candidate.get("title") or ""
    abstract = item_data.get("abstract") or candidate.get("abstract") or ""

    title_len = len(title)
    abstract_len = len(abstract)

    global_ctr = config.get("global_ctr", 0.0)
    category_ctr = config.get("category_ctr", {}).get(category, global_ctr)
    subcategory_ctr = config.get("subcategory_ctr", {}).get(subcategory, global_ctr)

    category_match = 1.0 if category and category in user_categories else 0.0

    user_recency_days = 0.0
    if user_last_time:
        user_recency_days = max((datetime.utcnow() - user_last_time).total_seconds() / 86400.0, 0.0)

    cosine_sim = 0.0
    item_vec = item_data.get("embedding")
    if user_vec is not None and item_vec is not None:
        denom = np.linalg.norm(user_vec) * np.linalg.norm(item_vec)
        if denom > 0:
            cosine_sim = float(np.dot(user_vec, item_vec) / denom)

    return [
        float(rank_position),
        float(title_len),
        float(abstract_len),
        float(category_ctr),
        float(subcategory_ctr),
        float(category_match),
        float(user_recency_days),
        float(cosine_sim),
    ]


def rerank(conn, user_id: str, candidates, history_k: int, half_life_days: float):
    model, config = load_model()
    if model is None or config is None:
        return candidates

    clicks = get_user_click_history(conn, user_id, history_k)
    user_vec, _ = build_user_vector(conn, clicks, half_life_days)
    if user_vec is None:
        return candidates

    user_last_time = None
    for click in clicks:
        ts = parse_time(click.get("time"))
        if ts and (user_last_time is None or ts > user_last_time):
            user_last_time = ts

    news_ids = [item["news_id"] for item in candidates]
    item_map = get_item_embeddings(conn, news_ids)

    user_categories = set()
    click_ids = [click.get("news_id") for click in clicks]
    click_categories = get_news_categories(conn, click_ids)
    for category in click_categories.values():
        if category:
            user_categories.add(category)

    features = []
    for idx, cand in enumerate(candidates, start=1):
        item_info = item_map.get(cand["news_id"], {})
        features.append(
            compute_features(cand, item_info, user_vec, user_categories, user_last_time, config, idx)
        )

    scores = model.predict_proba(np.array(features))[:, 1]

    reranked = []
    for cand, score in zip(candidates, scores):
        updated = dict(cand)
        updated["score"] = float(score)
        reranked.append(updated)

    reranked.sort(key=lambda x: x["score"], reverse=True)
    return reranked
