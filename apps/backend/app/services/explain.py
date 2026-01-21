import math


def _normalize(values):
    if not values:
        return []
    min_val = min(values)
    max_val = max(values)
    if max_val - min_val == 0:
        return [0.0 for _ in values]
    return [(v - min_val) / (max_val - min_val) for v in values]


def _top_percent_threshold(values, percent):
    if not values:
        return 1.0
    values_sorted = sorted(values, reverse=True)
    idx = max(0, math.ceil(len(values_sorted) * percent) - 1)
    return values_sorted[idx]


def load_top_node_stats(conn, user_id: str):
    sql = """
        SELECT category, subcategory, clicks, exposures, underexplored_score
        FROM user_top_nodes
        WHERE user_id = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (user_id,))
        rows = cur.fetchall()

    stats = {}
    for category, subcategory, clicks, exposures, under_score in rows:
        if not category:
            continue
        path = f"{category}/{subcategory}" if subcategory else category
        stats[path] = {
            "clicks": int(clicks or 0),
            "exposures": int(exposures or 0),
            "underexplored_score": float(under_score or 0.0),
        }
    return stats


def load_recent_clicks(conn, clicks, limit: int = 3):
    if not clicks:
        return []
    ordered_ids = []
    for click in clicks:
        news_id = click.get("news_id")
        if news_id and news_id not in ordered_ids:
            ordered_ids.append(news_id)
        if len(ordered_ids) >= limit:
            break
    if not ordered_ids:
        return []

    sql = "SELECT news_id, title FROM items WHERE news_id = ANY(%s)"
    with conn.cursor() as cur:
        cur.execute(sql, (ordered_ids,))
        rows = cur.fetchall()

    title_map = {row[0]: row[1] for row in rows}
    return [{"news_id": nid, "title": title_map.get(nid)} for nid in ordered_ids]


def load_user_preferred_ids(conn, user_id: str):
    sql = """
        SELECT im.news_id
        FROM impressions im
        JOIN sessions s
          ON s.impression_id = im.impression_id
         AND s.split = im.split
        WHERE s.user_id = %s
          AND im.clicked = TRUE
          AND s.split = 'live'
    """
    with conn.cursor() as cur:
        cur.execute(sql, (user_id,))
        rows = cur.fetchall()
    return {row[0] for row in rows}


def build_explanations(user_id, ranked_items, context):
    method = context.get("method", "rerank_only")
    top_node_stats = context.get("top_node_stats", {})
    recent_clicks = context.get("recent_clicks", [])
    has_top = bool(top_node_stats)
    preferred_ids = context.get("preferred_ids", set())

    rel_base = [float(item.get("rel_score", item.get("score", 0.0))) for item in ranked_items]
    top_base = [float(item.get("top_bonus", 0.0)) for item in ranked_items]
    rep_base = [float(item.get("redundancy_penalty", 0.0)) for item in ranked_items]
    cov_base = [float(item.get("coverage_gain", 0.0)) for item in ranked_items]

    rel_norm = _normalize(rel_base)
    top_norm = _normalize(top_base)
    rep_norm = _normalize(rep_base)
    cov_norm = _normalize(cov_base)

    rel_threshold = _top_percent_threshold(rel_norm, 0.2)
    top_threshold = _top_percent_threshold(top_norm, 0.3)

    explained = []
    for idx, item in enumerate(ranked_items):
        top_path = item.get("top_path")
        if not top_path:
            category = item.get("category")
            subcategory = item.get("subcategory")
            top_path = f"{category}/{subcategory}" if subcategory else category

        reason_tags = []
        if rel_norm[idx] >= rel_threshold:
            reason_tags.append("relevant_to_you")
        if has_top and top_norm[idx] >= top_threshold:
            reason_tags.append("underexplored_interest")
        if cov_norm[idx] > 0:
            reason_tags.append("adds_topic_variety")
        if rep_norm[idx] > 0 and (rel_norm[idx] >= rel_threshold or top_norm[idx] >= top_threshold):
            reason_tags.append("reduces_repetition")
        if method == "popular_fallback":
            reason_tags.append("popular_fallback")

        evidence = {
            "recent_clicks_used": recent_clicks,
            "top_node_stats": top_node_stats.get(top_path),
        }

        explanation = {
            "top_path": top_path,
            "reason_tags": reason_tags,
            "score_breakdown": {
                "rel_score_norm": rel_norm[idx],
                "top_bonus_norm": top_norm[idx],
                "redundancy_penalty_norm": rep_norm[idx],
                "coverage_gain_norm": cov_norm[idx],
                "total_score": float(item.get("total_score", item.get("score", 0.0))),
            },
            "evidence": evidence,
            "method": method,
        }

        updated = dict(item)
        if updated.get("news_id") in preferred_ids:
            updated["is_preferred"] = True
        updated["explanation"] = explanation
        explained.append(updated)

    return explained
