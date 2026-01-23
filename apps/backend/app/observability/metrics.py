from __future__ import annotations

from typing import Iterable

from prometheus_client import Counter, Histogram, Summary

REQUEST_COUNT = Counter(
    "request_count_total",
    "Total HTTP requests",
    ["route", "method", "status"],
)
REQUEST_LATENCY = Histogram(
    "request_latency_seconds",
    "HTTP request latency in seconds",
    ["route", "method"],
)
ERROR_COUNT = Counter(
    "error_count_total",
    "Total HTTP errors",
    ["route", "method"],
)

FEED_REQUESTS = Counter(
    "feed_requests_total",
    "Total feed requests",
    ["method", "variant"],
)
FEED_LATENCY = Histogram(
    "feed_latency_seconds",
    "Feed request latency in seconds",
    ["variant"],
)
FEED_ITEMS_RETURNED = Histogram(
    "feed_items_returned",
    "Feed items returned per response",
    ["variant"],
    buckets=(1, 5, 10, 20, 50, 100, 200, 500, 1000),
)
FEED_DIVERSIFY_ENABLED = Counter(
    "feed_diversify_enabled_total",
    "Feed requests with diversification enabled",
    ["variant"],
)
FEED_EXPLORE_LEVEL = Summary(
    "feed_explore_level",
    "Explore level used for feed requests",
    ["variant"],
)

FEED_UNIQUE_CATEGORIES = Summary(
    "feed_unique_categories_count",
    "Unique categories per feed response",
    ["variant"],
)
FEED_UNIQUE_SUBCATEGORIES = Summary(
    "feed_unique_subcategories_count",
    "Unique subcategories per feed response",
    ["variant"],
)
FEED_REPETITION_RATE = Summary(
    "feed_repetition_rate",
    "Repetition rate per feed response",
    ["variant"],
)
FEED_AVG_TOP_BONUS = Summary(
    "feed_avg_top_bonus",
    "Average top bonus per feed response",
    ["variant"],
)
FEED_AVG_REDUNDANCY_PENALTY = Summary(
    "feed_avg_redundancy_penalty",
    "Average redundancy penalty per feed response",
    ["variant"],
)


def _safe_mean(values: Iterable[float]) -> float | None:
    values = [value for value in values if value is not None]
    if not values:
        return None
    return float(sum(values)) / float(len(values))


def observe_feed_response(
    *,
    variant: str,
    method: str,
    latency_seconds: float,
    items: list[dict],
    diversify_enabled: bool,
    explore_level: float,
) -> None:
    FEED_REQUESTS.labels(method=method, variant=variant).inc()
    FEED_LATENCY.labels(variant=variant).observe(latency_seconds)
    FEED_ITEMS_RETURNED.labels(variant=variant).observe(len(items))
    FEED_EXPLORE_LEVEL.labels(variant=variant).observe(float(explore_level or 0.0))
    if diversify_enabled:
        FEED_DIVERSIFY_ENABLED.labels(variant=variant).inc()

    categories = {item.get("category") for item in items if item.get("category")}
    subcategories = {item.get("subcategory") for item in items if item.get("subcategory")}
    unique_categories = len(categories)
    unique_subcategories = len(subcategories)
    k = len(items)
    repetition_rate = 0.0
    if k > 0:
        repetition_rate = 1.0 - (float(unique_subcategories) / float(k))

    FEED_UNIQUE_CATEGORIES.labels(variant=variant).observe(unique_categories)
    FEED_UNIQUE_SUBCATEGORIES.labels(variant=variant).observe(unique_subcategories)
    FEED_REPETITION_RATE.labels(variant=variant).observe(repetition_rate)

    avg_top_bonus = _safe_mean(
        [float(item.get("top_bonus")) for item in items if item.get("top_bonus") is not None]
    )
    if avg_top_bonus is not None:
        FEED_AVG_TOP_BONUS.labels(variant=variant).observe(avg_top_bonus)

    avg_redundancy_penalty = _safe_mean(
        [
            float(item.get("redundancy_penalty"))
            for item in items
            if item.get("redundancy_penalty") is not None
        ]
    )
    if avg_redundancy_penalty is not None:
        FEED_AVG_REDUNDANCY_PENALTY.labels(variant=variant).observe(avg_redundancy_penalty)
