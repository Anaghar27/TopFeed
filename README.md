# ToPFeed: LLM-guided Diversified Feed using Tree of Preferences

ToPFeed is a monorepo that ingests the MIND-large dataset into Postgres, builds item embeddings using pgvector, and serves a FastAPI backend with a React frontend.

This README covers setup and the current implementation through Step 11 + frontend explainability, preferences, analytics UI, rollout observability, and fresh content ingestion. It will be updated as new stages are completed and pushed to GitHub.

---

## System Architecture (Current)

- Data source: MIND-large dataset (manual download).
- Storage: Postgres as the single system of record.
- Embeddings: pgvector extension in Postgres.
- Backend: FastAPI + Uvicorn.
- Frontend: React + Vite + Tailwind.
- Observability: Prometheus scraping `/metrics`.
- Fresh ingestion: RSS -> Postgres -> embeddings -> feed blending.
- User portal: Postgres-backed user profiles and preferences + admin console (OTP + JWT).
- Orchestration: Docker Compose.


```
MIND-large zips
  |
  v
Extract TSVs
  |
  v
Ingest to Postgres
  |-- items
  |-- sessions
  |-- impressions
  |-- user_history
  |
  v
Build embeddings (title + abstract)
  |
  v
items.embedding (pgvector)
  |
  v
HNSW index + similarity search
  |
  v
Personalized retrieval (FastAPI)
  |
  v
Baseline reranker (FastAPI)
  |
  v
Tree of Preferences (ToP) builder + API
  |
  v
ToP-guided diversified feed (hybrid candidate pool + greedy re-ranker)
  |
  v
Explainability + Preferences UI (Why this, hearts, preferred list)
  |
  v
Event logging + daily metrics (Postgres analytics)
  |
  v
Observability + safe rollout (Prometheus + canary routing)
  |
  v
Fresh-first feed + hourly ToP updates (RSS + incremental updates)
  |
  v
User portal (signup/login + profile) + admin console
```

---

## Repository Structure

```
apps/
  backend/        # FastAPI + Alembic
    app/api/      # API routes (retrieval service)
    app/observability/ # Prometheus metrics
    app/middleware/    # Prometheus middleware
    app/services/ # Retrieval + reranker + ToP logic
  frontend/       # React + Vite + Tailwind
    src/pages/    # Feed + Auth + Profile pages
infra/
  prometheus.yml  # Prometheus scrape config
ml/
  config/         # RSS source config
  data/
    raw/mind/large/
      zips/       # MIND-large zip files (manual download)
      extracted/  # extracted TSVs
  scripts/        # ingestion + embedding scripts
  scripts/sql/    # schema and vector setup SQL
```

---

## Environment

Create `.env` at repo root (or copy from `.env.example`):

```
DB_HOST=postgres
DB_PORT=5432
DB_USER=topfeed
DB_PASSWORD=topfeed
DB_NAME=topfeed
FRONTEND_ORIGIN=http://localhost:5173
VITE_API_BASE=http://localhost:8000
ADMIN_EMAILS=admin1@gmail.com,admin2@gmail.com
ADMIN_JWT_SECRET=change-me
ADMIN_JWT_TTL_MIN=60
ADMIN_BOOTSTRAP_KEY=change-me

SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=your-smtp-user
SMTP_PASSWORD=your-smtp-password
SMTP_FROM=admin@example.com
SMTP_TLS=true

# Admin setup (one-time bootstrap)
1) Apply admin tables:
   cat ml/scripts/sql/users.sql | docker compose exec -T postgres psql -U topfeed -d topfeed
2) Create admin account:
   curl -X POST http://localhost:8000/admin/bootstrap \
     -H "Content-Type: application/json" \
     -H "X-Admin-Bootstrap-Key: <ADMIN_BOOTSTRAP_KEY>" \
     -d '{"email":"admin@example.com","password":"<admin-password>"}'
3) Login flow:
   POST /admin/login/otp/request -> email + password
   POST /admin/login/verify -> email + password + otp (returns JWT)
   Use JWT on /admin/users and /admin/events via Authorization: Bearer <token>

RERANK_MAX_ROWS_TRAIN=200000
RERANK_MAX_ROWS_DEV=50000
RERANK_NEG_PER_POS=5
RERANK_NEG_HASH_PCT=10
RERANK_SPLITS=train,dev
RERANKER_MODEL_PATH=/app/ml/models/reranker_baseline/model.joblib
RERANKER_CONFIG_PATH=/app/ml/models/reranker_baseline/training_config.json

CANDIDATE_POOL_N=200
EXPLORE_POOL_RATIO=0.2
W_REL_BASE=1.0
W_TOP_BASE=0.5
W_REP_BASE=0.6
W_COV_BASE=0.4
MAX_SUBCAT_PER_FEED=3
MAX_CAT_PER_FEED=8

CANARY_ENABLED=false
CANARY_PERCENT=5
CONTROL_MODEL_VERSION=reranker_baseline:v1
CANARY_MODEL_VERSION=reranker_baseline:v2
CANARY_AUTO_DISABLE=false
CTR_DROP_THRESHOLD=0.1
NOVELTY_SPIKE_THRESHOLD=0.1

FRESH_HOURS=168
FRESH_POOL_N=200
FRESH_MIN_ITEMS=20
FRESH_RATIO=0.9
FRESH_REL_WEIGHT=0.7
FRESH_FRESHNESS_WEIGHT=0.3
FRESH_TOP_WEIGHT=0.2

LIVE_EXCLUDE_HOURS=6
LIVE_EXCLUDE_LIMIT=500
```

---

## Run the Stack

```
docker compose up --build
```

- Postgres: `localhost:5432`
- Backend: `http://localhost:8000`
- Frontend: `http://localhost:5173`

---

# Step 1: MIND-large Ingestion (Postgres only)

### 1) Place dataset zips
Download from https://msnews.github.io and place here:

```
ml/data/raw/mind/large/zips/
  - MINDlarge_train.zip
  - MINDlarge_dev.zip
  - MINDlarge_test.zip
```

### 2) Extract TSVs

Host:
```
python ml/scripts/extract_mind_zips.py
```

Container:
```
docker compose exec backend python /app/ml/scripts/extract_mind_zips.py
```

### 3) Ingest into Postgres

Container (recommended):
```
docker compose exec backend python /app/ml/scripts/ingest_mind_to_postgres.py
```

Tables created:
- `items`
- `sessions`
- `impressions`
- `user_history`

### 4) Validate ingestion
```
SELECT split, COUNT(*) FROM sessions GROUP BY split;
SELECT split, COUNT(*) FROM impressions GROUP BY split;
SELECT split, COUNT(*) FROM user_history GROUP BY split;
```

Idempotency: re-running ingestion should show `inserted=0` and only `updated=...`.

---

# Step 2: Item Embeddings (pgvector)

### 1) Add embedding column + HNSW index
```
cat ml/scripts/sql/add_embeddings.sql | docker compose exec -T postgres psql -U topfeed -d topfeed
```

### 2) Build embeddings
```
docker compose exec backend python /app/ml/scripts/build_item_embeddings.py
```

Optional config (env vars):
```
EMB_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
EMB_BATCH_SIZE=128
EMB_FETCH_BATCH=5000
EMB_MAX_ROWS=10000
EMB_FORCE_RECOMPUTE=0
```

### 3) Validate embeddings
```
SELECT COUNT(*) FROM items WHERE embedding IS NOT NULL;
```

Nearest neighbors:
```
SELECT news_id, title
FROM items
WHERE embedding IS NOT NULL
ORDER BY embedding <=> (
  SELECT embedding FROM items WHERE news_id = '<NEWS_ID>' AND embedding IS NOT NULL
)
LIMIT 10;
```

---

# Step 3: Personalized Retrieval (pgvector + FastAPI)

### 1) Start services
```
docker compose up -d --build
```

### 2) Personalized retrieval
```
curl -X POST http://localhost:8000/retrieve \\
  -H "Content-Type: application/json" \\
  -d '{"user_id":"<USER_ID>","top_n":50,"history_k":50}'
```

### 3) Debug user vector
```
curl http://localhost:8000/retrieve/debug/<USER_ID>
```

If a user has no usable clicks/embeddings, the service returns popular items from train/dev.

---

# Step 4: Baseline Reranker (relevance-first)

The reranker is a lightweight logistic regression model trained on train/dev impressions.
It scores candidate items and reorders the retrieval list (relevance-first, no diversification yet).

### 1) Build reranker dataset
```
docker compose exec backend python /app/ml/scripts/build_reranker_dataset.py
```

Optional env vars:
```
RERANK_SPLITS=train,dev
RERANK_MAX_ROWS=50000
RERANK_MAX_ROWS_TRAIN=200000
RERANK_MAX_ROWS_DEV=50000
RERANK_NEG_PER_POS=5
RERANK_NEG_HASH_PCT=10
```

### 2) Train reranker
```
docker compose exec backend python /app/ml/scripts/train_reranker.py
```

Expected metrics output:
- AUC
- nDCG@10
- MRR@10

### 3) Run reranked retrieval
```
curl -X POST http://localhost:8000/retrieve \\
  -H "Content-Type: application/json" \\
  -d '{"user_id":"<USER_ID>","top_n":10,"history_k":50,"rerank":true}'
```

### 4) Compare to retrieval-only
```
curl -X POST http://localhost:8000/retrieve \\
  -H "Content-Type: application/json" \\
  -d '{"user_id":"<USER_ID>","top_n":10,"history_k":50,"rerank":false}'
```

If the order differs, the reranker is active.

---

# Step 5: Tree of Preferences (ToP)

ToP builds a per-user tree from train/dev impressions (root → category → subcategory).
Each node stores exposures, clicks, CTR, recency-weighted interest/exposure, and an underexplored score.

### 1) Create ToP tables
```
cat ml/scripts/sql/create_top_tables.sql | docker compose exec -T postgres psql -U topfeed -d topfeed
```

### 2) Build ToP for one user
```
docker compose exec backend python /app/ml/scripts/build_top.py --user_id U483745
```

### 3) Build ToP for N users
```
docker compose exec backend python /app/ml/scripts/build_top.py --limit_users 1000
```

### 4) Fetch via API
```
curl http://localhost:8000/users/U483745/top
curl http://localhost:8000/users/U483745/top/nodes
```

### 5) Verify in SQL
```
SELECT user_id, generated_at FROM user_top ORDER BY generated_at DESC LIMIT 5;

SELECT path, underexplored_score, clicks, exposures
FROM user_top_nodes
WHERE user_id = '<USER_ID>'
ORDER BY underexplored_score DESC
LIMIT 20;
```

# Step 6: ToP-guided Diversified Feed (Hybrid Candidate Pool)

Step 6 adds a hybrid candidate pool plus a greedy diversification step guided by ToP signals.

Hybrid candidate pool:
- Vector retrieval (personalized neighbors)
- Exploration pool from underexplored categories (fallback: popular items)
- Merge, dedupe, then rerank + diversify to final K

### 1) Candidate pool + diversification
```
curl -X POST http://localhost:8000/retrieve \\
  -H "Content-Type: application/json" \\
  -d '{"user_id":"<USER_ID>","top_n":20,"history_k":50,"explore_level":0.0,"diversify":true}'

curl -X POST http://localhost:8000/retrieve \\
  -H "Content-Type: application/json" \\
  -d '{"user_id":"<USER_ID>","top_n":20,"history_k":50,"explore_level":1.0,"diversify":true}'
```

Expected:
- `explore_level=0.0` keeps relevance strong and diversity low
- `explore_level=1.0` increases category/subcategory coverage and ILD
- `MAX_SUBCAT_PER_FEED` and `MAX_CAT_PER_FEED` cap repetition

### 2) Verify candidate pool diversity
```
curl -X POST http://localhost:8000/retrieve \\
  -H "Content-Type: application/json" \\
  -d '{"user_id":"<USER_ID>","top_n":200,"history_k":50,"rerank":false,"diversify":false}' \\
| python -c "import sys,json; d=json.load(sys.stdin); print(len(set(x['category'] for x in d['items'])))"
```

### 3) Check diversification metrics
```
curl -X POST http://localhost:8000/retrieve \\
  -H "Content-Type: application/json" \\
  -d '{"user_id":"<USER_ID>","top_n":20,"history_k":50,"explore_level":1.0,"diversify":true}' \\
| python -c "import sys,json; d=json.load(sys.stdin); print(d['diversification'])"
```

---

# Frontend UX: Explainability + Preferences

The frontend uses `/feed` for the main list, shows “Why this?” explanations, and supports preferences with a heart icon.

### 1) Fetch the diversified feed (UI)
```
curl -X POST http://localhost:8000/feed \\
  -H "Content-Type: application/json" \\
  -d '{"user_id":"<USER_ID>","top_n":30,"history_k":50,"diversify":true,"explore_level":0.6}'
```

### 2) Save or remove a preference (backend)
```
curl -X POST http://localhost:8000/feedback \\
  -H "Content-Type: application/json" \\
  -d '{"user_id":"<USER_ID>","news_id":"<NEWS_ID>","action":"prefer","split":"live"}'

curl -X POST http://localhost:8000/feedback \\
  -H "Content-Type: application/json" \\
  -d '{"user_id":"<USER_ID>","news_id":"<NEWS_ID>","action":"unprefer","split":"live"}'
```

### 3) Preferred list (backend)
```
curl http://localhost:8000/users/<USER_ID>/preferred?limit=100
```

### 4) UI behavior
- **Heart icon**: filled = preferred, outline = not preferred.
- **Preferences tab**: shows preferred items in a separate view.
- **Why this?** drawer: shows reason tags + score breakdown + evidence.
- **Theme toggle**: switches light/dark mode.
- **Load time badge**: shows feed fetch latency.

---

# Step 9: Event Logging + Analytics (Postgres)

Step 9 logs UI events into Postgres and computes daily metrics for dashboards.

### 1) Create events + metrics tables
```
cat ml/scripts/sql/events_and_metrics.sql | docker compose exec -T postgres psql -U topfeed -d topfeed
```

### 2) Post events (single + batch)
```
curl -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{"user_id":"U483745","event_type":"impression","news_id":"N123","request_id":"req1","model_version":"top_div:v1","method":"personalized_top_diversified","position":1,"explore_level":0.6,"diversify":true}'

curl -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '[{"user_id":"U483745","event_type":"click","news_id":"N123","request_id":"req1","model_version":"top_div:v1","method":"personalized_top_diversified","position":1},{"user_id":"U483745","event_type":"dwell","news_id":"N123","request_id":"req1","model_version":"top_div:v1","method":"personalized_top_diversified","dwell_ms":4200}]'
```

### 3) Compute daily metrics
```
docker compose exec backend python /app/ml/scripts/compute_daily_metrics.py --days 14
```

### 4) Verify metrics in SQL
```
SELECT event_type, COUNT(*) FROM events GROUP BY event_type;

SELECT day, model_version, method, impressions, clicks, ctr
FROM daily_feed_metrics
ORDER BY day DESC
LIMIT 20;
```

### 5) Metrics API
```
curl "http://localhost:8000/metrics/summary?days=14"
curl "http://localhost:8000/metrics/summary?days=14&user_id=U483745"
```

### 6) UI metrics (per user)
- The feed UI shows impressions, clicks, CTR, and avg dwell for the current user over the last 14 days.

---

# Step 10: Observability + Safe Rollout

Step 10 adds Prometheus metrics, deterministic canary routing, and a rollout guard check.

### 1) Create rollout config table (one-time)
```
cat ml/scripts/sql/step10_rollout_config.sql | docker compose exec -T postgres psql -U topfeed -d topfeed
```

### 2) Prometheus metrics endpoint
```
curl http://localhost:8000/metrics | head
```

### 3) Feed response includes variant + model_version
```
curl -sS -X POST http://localhost:8000/feed \
  -H "Content-Type: application/json" \
  -d '{"user_id":"U483745","top_n":10,"history_k":50,"diversify":true,"explore_level":1.0,"include_explanations":false}' | head
```

### 4) Enable canary and set traffic split
```
docker compose exec -T backend psql -h postgres -U topfeed -d topfeed \
  -c "update rollout_config set value='true' where key='CANARY_ENABLED';"

docker compose exec -T backend psql -h postgres -U topfeed -d topfeed \
  -c "update rollout_config set value='50' where key='CANARY_PERCENT';"
```

### 5) Verify mixed variants
```
for u in U1 U2 U3 U4 U5 U6 U7 U8 U9 U10; do
  curl -sS -X POST http://localhost:8000/feed -H "Content-Type: application/json" \
    -d "{\"user_id\":\"$u\",\"top_n\":10,\"history_k\":50,\"diversify\":true,\"explore_level\":1.0,\"include_explanations\":false}" \
    | python -c "import sys,json;print(json.load(sys.stdin)['variant'])"
done
```

### 6) Rollout guard check
```
curl -sS -X POST http://localhost:8000/rollout/check \
  -H "Content-Type: application/json" \
  -d '{"window_minutes":60}' | head
```

---

# Step 11: Fresh News Ingestion + Fast ToP Updates

Step 11 ingests fresh RSS items into `items`, embeds them, and serves a fresh-first feed mode with incremental ToP updates and quality metrics.

### 1) Add schema for fresh items + watermark
```
cat ml/scripts/sql/schema_fresh.sql | docker compose exec -T postgres psql -U topfeed -d topfeed
cat ml/scripts/sql/top_incremental.sql | docker compose exec -T postgres psql -U topfeed -d topfeed
```

### 2) Fetch RSS and ingest fresh items
```
docker compose exec backend python /app/ml/scripts/fetch_fresh_rss.py --hours 168
docker compose exec backend python /app/ml/scripts/ingest_fresh_to_postgres.py --input /tmp/fresh_items.json
```

### 3) Verify fresh items in Postgres
```
SELECT COUNT(*) FROM items WHERE content_type='fresh';
SELECT MAX(published_at) FROM items WHERE content_type='fresh';
SELECT news_id, title, category, subcategory, url
FROM items
WHERE content_type='fresh'
ORDER BY published_at DESC
LIMIT 5;
```

### 4) Fresh-first feed mode
```
curl -sS -X POST http://localhost:8000/feed \
  -H "Content-Type: application/json" \
  -d '{"user_id":"U483745","top_n":20,"history_k":50,"diversify":true,"explore_level":1.0,"feed_mode":"fresh_first","fresh_hours":168,"fresh_ratio":1.0}'
```

Confirm:
- items include `news_id`, `title`, `abstract`, `url`, `category`, `subcategory`
- fresh items include `published_at` and `source`
- explanations include `fresh_content` when within the freshness window

### 5) Incremental ToP updates
```
docker compose exec backend python /app/ml/scripts/update_top_incremental.py --hours 1
```

### 6) Fresh ingest quality metrics
```
curl -sS http://localhost:8000/fresh/quality | head
```

### 7) Cron ingestion (every 10 minutes)
The `cron` service in `docker-compose.yml` runs:
- `fetch_fresh_rss.py` + `ingest_fresh_to_postgres.py` every 10 minutes
- `update_top_incremental.py` hourly

---

# Step 12: User Portal (Signup, Login, Profile)

Step 12 adds a Postgres-backed user portal with signup/login and a profile page.

### 1) Create users table
```
cat ml/scripts/sql/users.sql | docker compose exec -T postgres psql -U topfeed -d topfeed
```

### 2) Signup (new user)
```
curl -sS -X POST http://localhost:8000/users/signup \
  -H "Content-Type: application/json" \
  -d '{"full_name":"Jane Doe","email":"jane@example.com","password":"S3curePass!","location":"Austin","preferences":{"categories":["news","sports"],"subcategories":["tech","newsworld"]}}'
```

### 3) Login (existing user)
```
curl -sS -X POST http://localhost:8000/users/login \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@example.com","password":"S3curePass!"}'
```

Access code login:
```
curl -sS http://localhost:8000/users/U483745
```

### 4) Update profile
```
curl -sS -X PATCH http://localhost:8000/users/U483745 \
  -H "Content-Type: application/json" \
  -d '{"theme_preference":"light","preferences":{"categories":["finance"],"subcategories":["financeeconomy"]},"location":"Boston, MA, US","profile_image_url":"data:image/jpeg;base64,..."}'
```

### 5) Password reset (OTP)
Request OTP:
```
curl -sS -X POST http://localhost:8000/users/password/reset/request \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@example.com"}'
```

Verify OTP only:
```
curl -sS -X POST http://localhost:8000/users/password/reset/otp/verify \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@example.com","otp":"123456"}'
```

Reset with OTP + new password:
```
curl -sS -X POST http://localhost:8000/users/password/reset/verify \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@example.com","otp":"123456","new_password":"N3wS3curePass!"}'
```

### 6) SMTP settings (OTP email)
Add to `.env`:
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=topfeed.noreply@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_FROM=ToPFeed <topfeed.noreply@gmail.com>
SMTP_TLS=true
```

UI behavior:
- Signup uses email + password and does not ask for theme (default is dark).
- Login offers Email first, then Access code.
- Forgot password sends OTP to the user's email; OTP must verify before setting a new password.
- Profile includes photo upload with cropper, preferences, theme, engagement, and app version.
- Profile button shows the avatar; user id and load time are hidden.
- If a user exists without profile details, location defaults to `unknown` until updated.

## Notes

- Postgres is the only database.
- pgvector is enabled via Alembic migration.
- Docker volumes persist data across rebuilds; use `docker compose down -v` only to reset data.

---

## Upcoming (Planned)

- Multi-stage ToP diversification
- LLM-guided preference refinement
- Evaluation dashboard and monitoring
