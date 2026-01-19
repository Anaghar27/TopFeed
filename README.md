# ToPFeed: LLM-guided Diversified Feed using Tree of Preferences

ToPFeed is a monorepo that ingests the MIND-large dataset into Postgres, builds item embeddings using pgvector, and serves a FastAPI backend with a React frontend.

This README covers setup and the current implementation through Step 5. It will be updated as new stages are completed and pushed to GitHub.

---

## System Architecture (Current)

- Data source: MIND-large dataset (manual download).
- Storage: Postgres as the single system of record.
- Embeddings: pgvector extension in Postgres.
- Backend: FastAPI + Uvicorn.
- Frontend: React + Vite + Tailwind.
- Orchestration: Docker Compose.

Flow (Step 1 + Step 2 + Step 3 + Step 4 + Step 5):

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
```

---

## Repository Structure (Current)

```
apps/
  backend/        # FastAPI + Alembic
    app/api/      # API routes (retrieval service)
    app/services/ # Retrieval + reranker + ToP logic
  frontend/       # React + Vite + Tailwind
infra/
ml/
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
RERANK_NEG_PER_POS=1
RERANK_NEG_HASH_PCT=5
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

## Notes

- Postgres is the only database.
- pgvector is enabled via Alembic migration.
- Docker volumes persist data across rebuilds; use `docker compose down -v` only to reset data.

---

## Upcoming (Planned)

- User embeddings
- Retrieval + diversification logic
- API endpoints for personalized feed
- Evaluation and monitoring
