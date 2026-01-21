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
    score: float
    rel_score: float | None = None
    top_bonus: float | None = None
    redundancy_penalty: float | None = None
    coverage_gain: float | None = None
    total_score: float | None = None
    top_path: str | None = None
    is_preferred: bool | None = None
    explanation: Optional[Explanation] = None


class FeedResponse(BaseModel):
    user_id: str
    items: List[FeedItem]
    method: Literal["personalized_top_diversified", "rerank_only", "popular_fallback"]
    diversification: dict | None = None


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


class ExplainResponse(BaseModel):
    item: FeedItem
