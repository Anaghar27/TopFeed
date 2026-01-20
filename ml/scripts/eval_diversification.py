import argparse
import math
import os
from collections import Counter

import numpy as np
import psycopg2
from dotenv import load_dotenv
from prettytable import PrettyTable
from tqdm import tqdm

import sys

sys.path.append("/app")

from app.services.retrieval_pgvector import build_user_vector, get_user_click_history, retrieve_by_vector
from app.services.reranker import score_candidates
from app.services.diversify_top import diversify_greedy


def get_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def get_conn():
    return psycopg2.connect(
        host=get_env("DB_HOST"),
        port=get_env("DB_PORT"),
        dbname=get_env("DB_NAME"),
        user=get_env("DB_USER"),
        password=get_env("DB_PASSWORD"),
    )


def ndcg_at_k(relevance, k):
    rel = np.array(relevance[:k])
    gains = (2 ** rel - 1)
    discounts = np.log2(np.arange(2, 2 + len(rel)))
    dcg = np.sum(gains / discounts) if len(rel) else 0.0
    ideal = sorted(relevance, reverse=True)[:k]
    ideal_gains = (2 ** np.array(ideal) - 1)
    ideal_discounts = np.log2(np.arange(2, 2 + len(ideal)))
    idcg = np.sum(ideal_gains / ideal_discounts) if len(ideal) else 0.0
    return float(dcg / idcg) if idcg > 0 else 0.0


def mrr_at_k(relevance, k):
    for idx, val in enumerate(relevance[:k], start=1):
        if val > 0:
            return 1.0 / idx
    return 0.0


def get_popularity_map(conn):
    sql = """
        SELECT im.news_id, COUNT(*) AS clicks
        FROM impressions im
        WHERE im.split IN ('train','dev') AND im.clicked = TRUE
        GROUP BY im.news_id
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    counts = {row[0]: row[1] for row in rows}
    if not counts:
        return {}, []
    sorted_counts = sorted(counts.values())
    return counts, sorted_counts


def percentile(sorted_vals, value):
    if not sorted_vals:
        return 0.0
    idx = np.searchsorted(sorted_vals, value, side="right")
    return float(idx) / len(sorted_vals)


def fetch_embeddings(conn, news_ids):
    if not news_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute("SELECT news_id, embedding FROM items WHERE news_id = ANY(%s)", (news_ids,))
        rows = cur.fetchall()
    emb_map = {}
    for news_id, vec in rows:
        text = str(vec).strip().lstrip("[").rstrip("]")
        if not text:
            continue
        emb_map[news_id] = np.fromstring(text, sep=",", dtype=np.float32)
    return emb_map


def ild(embeddings):
    if len(embeddings) < 2:
        return 0.0
    pairs = 0
    total = 0.0
    keys = list(embeddings.keys())
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a = embeddings[keys[i]]
            b = embeddings[keys[j]]
            denom = np.linalg.norm(a) * np.linalg.norm(b)
            if denom == 0:
                continue
            sim = float(np.dot(a, b) / denom)
            total += (1.0 - sim)
            pairs += 1
    return total / pairs if pairs else 0.0


def main():
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=100)
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()

    conn = get_conn()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT s.user_id
            FROM sessions s
            WHERE s.split IN ('train','dev')
            LIMIT %s
            """,
            (args.users,),
        )
        user_ids = [row[0] for row in cur.fetchall()]

    popularity_map, popularity_values = get_popularity_map(conn)

    levels = [0.0, 0.3, 0.6, 1.0]
    results = []

    for level in levels:
        ndcgs = []
        mrrs = []
        coverages = []
        novelties = []
        ilds = []

        for user_id in tqdm(user_ids, desc=f"eval-{level}", unit="user"):
            clicks = get_user_click_history(conn, user_id, 50)
            user_vec, _ = build_user_vector(conn, clicks, 7.0)
            if user_vec is None:
                continue

            candidates = retrieve_by_vector(conn, user_vec, 200, [])
            reranker_scores = score_candidates(conn, user_id, candidates, 50, 7.0)
            ranked, _ = diversify_greedy(user_id, candidates, reranker_scores, level, args.k)

            clicked_ids = {c["news_id"] for c in clicks}
            relevance = [1 if item["news_id"] in clicked_ids else 0 for item in ranked]

            ndcgs.append(ndcg_at_k(relevance, args.k))
            mrrs.append(mrr_at_k(relevance, args.k))

            categories = [item.get("category") for item in ranked if item.get("category")]
            subcategories = [item.get("subcategory") for item in ranked if item.get("subcategory")]
            coverage = len(set(categories)) + len(set(subcategories)) * 0.5
            coverages.append(coverage)

            novelty_vals = []
            for item in ranked:
                clicks_count = popularity_map.get(item["news_id"], 0)
                novelty_vals.append(1.0 - percentile(popularity_values, clicks_count))
            novelties.append(float(np.mean(novelty_vals)) if novelty_vals else 0.0)

            emb_map = fetch_embeddings(conn, [item["news_id"] for item in ranked])
            ilds.append(ild(emb_map))

        results.append(
            {
                "explore_level": level,
                "ndcg10": float(np.mean(ndcgs)) if ndcgs else 0.0,
                "mrr10": float(np.mean(mrrs)) if mrrs else 0.0,
                "coverage": float(np.mean(coverages)) if coverages else 0.0,
                "novelty": float(np.mean(novelties)) if novelties else 0.0,
                "ild": float(np.mean(ilds)) if ilds else 0.0,
            }
        )

    table = PrettyTable()
    table.field_names = ["explore_level", "ndcg10", "mrr10", "coverage", "novelty", "ild"]
    table.align = "r"
    for row in results:
        table.add_row(
            [
                f"{row['explore_level']:.1f}",
                f"{row['ndcg10']:.4f}",
                f"{row['mrr10']:.4f}",
                f"{row['coverage']:.2f}",
                f"{row['novelty']:.4f}",
                f"{row['ild']:.4f}",
            ]
        )
    print(table)

    conn.close()


if __name__ == "__main__":
    main()
