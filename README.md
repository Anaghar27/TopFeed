# ToPFeed: LLM-guided Diversified Feed using Tree of Preferences

ToPFeed is a monorepo that ingests the MIND-large dataset into Postgres, builds item embeddings using pgvector, and serves a FastAPI backend with a React frontend.

This README covers setup and the current implementation through Step 2. It will be updated as new stages are completed and pushed to GitHub.

---

## System Architecture (Current)

- Data source: MIND-large dataset (manual download).
- Storage: Postgres as the single system of record.
- Embeddings: pgvector extension in Postgres.
- Backend: FastAPI + Uvicorn.
- Frontend: React + Vite + Tailwind.
- Orchestration: Docker Compose.

Flow (Step 1 + Step 2):

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
```

---

## Repository Structure (Current)

```
apps/
  backend/        # FastAPI + Alembic
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
