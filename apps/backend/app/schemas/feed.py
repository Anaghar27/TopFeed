from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class FeedRequest(BaseModel):
    user_id: str
    top_n: int = Field(default=200, ge=1, le=1000)
    history_k: int = Field(default=50, ge=1, le=500)
    rerank: bool = True
    explore_level: float = Field(default=0.3, ge=0.0, le=1.0)
    diversify: bool = True
    include_explanations: bool = True
    feed_mode: Literal["historical", "fresh_first"] = "historical"
    fresh_hours: int | None = Field(default=None, ge=1, le=168)
    fresh_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    fresh_pool_n: int | None = Field(default=None, ge=1, le=2000)
    fresh_min_items: int | None = Field(default=None, ge=0, le=1000)


class ScoreBreakdown(BaseModel):
    rel_score_norm: float
    top_bonus_norm: float
    redundancy_penalty_norm: float
    coverage_gain_norm: float
    total_score: float


class Evidence(BaseModel):
    recent_clicks_used: List[dict]
    top_node_stats: Optional[dict] = None


class Explanation(BaseModel):
    top_path: str | None
    reason_tags: List[str]
    score_breakdown: ScoreBreakdown
    evidence: Evidence
    method: Literal["personalized_top_diversified", "rerank_only", "popular_fallback"]


class FeedItem(BaseModel):
    news_id: str
    title: str | None
    abstract: str | None
    category: str | None
    subcategory: str | None
    url: str | None
    published_at: str | None = None
    source: str | None = None
    content_type: str | None = None
    score: float
    rel_score: float | None = None
    top_bonus: float | None = None
    redundancy_penalty: float | None = None
    coverage_gain: float | None = None
    total_score: float | None = None
    top_path: str | None = None
    is_preferred: bool | None = None
    is_new_interest: bool | None = None
    explanation: Optional[Explanation] = None


class FeedResponse(BaseModel):
    user_id: str
    items: List[FeedItem]
    method: Literal["personalized_top_diversified", "rerank_only", "popular_fallback"]
    diversification: dict | None = None
    request_id: str | None = None
    model_version: str | None = None
    variant: Literal["control", "canary"] | None = None


class PreferredItem(BaseModel):
    news_id: str
    title: str | None
    abstract: str | None
    category: str | None
    subcategory: str | None
    url: str | None
    last_time: str | None = None
    is_preferred: bool = True


class PreferredResponse(BaseModel):
    user_id: str
    items: List[PreferredItem]


class ExplainRequest(BaseModel):
    user_id: str
    item: FeedItem
    method: Literal["personalized_top_diversified", "rerank_only", "popular_fallback"] = "rerank_only"
    score_context: dict | None = None


class ExplainResponse(BaseModel):
    item: FeedItem
