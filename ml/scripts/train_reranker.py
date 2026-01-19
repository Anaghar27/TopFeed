import json
import os
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


FEATURE_COLUMNS = [
    "position",
    "title_len",
    "abstract_len",
    "category_ctr",
    "subcategory_ctr",
    "category_match",
    "user_recency_days",
    "cosine_sim",
]


def ndcg_at_k(labels, scores, k: int) -> float:
    order = np.argsort(scores)[::-1][:k]
    rel = np.array(labels)[order]
    gains = (2 ** rel - 1)
    discounts = np.log2(np.arange(2, 2 + len(rel)))
    dcg = np.sum(gains / discounts) if len(rel) else 0.0
    ideal = np.sort(labels)[::-1][:k]
    ideal_gains = (2 ** ideal - 1)
    ideal_discounts = np.log2(np.arange(2, 2 + len(ideal)))
    idcg = np.sum(ideal_gains / ideal_discounts) if len(ideal) else 0.0
    return float(dcg / idcg) if idcg > 0 else 0.0


def mrr_at_k(labels, scores, k: int) -> float:
    order = np.argsort(scores)[::-1][:k]
    rel = np.array(labels)[order]
    for idx, val in enumerate(rel, start=1):
        if val > 0:
            return 1.0 / idx
    return 0.0


def evaluate_grouped(df, scores, k: int):
    df = df.copy()
    df["score"] = scores
    ndcgs = []
    mrrs = []
    for _, group in df.groupby("impression_id"):
        labels = group["label"].values
        group_scores = group["score"].values
        ndcgs.append(ndcg_at_k(labels, group_scores, k))
        mrrs.append(mrr_at_k(labels, group_scores, k))
    return float(np.mean(ndcgs)), float(np.mean(mrrs))


def main() -> None:
    data_dir = os.path.join("ml", "data", "processed", "reranker")
    train_path = os.path.join(data_dir, "train.csv")
    val_path = os.path.join(data_dir, "val.csv")
    metadata_path = os.path.join(data_dir, "metadata.json")

    if not os.path.isfile(train_path) or not os.path.isfile(val_path):
        raise RuntimeError("Missing train/val data. Run build_reranker_dataset.py first.")

    train_df = pd.read_csv(train_path)
    val_df = pd.read_csv(val_path)

    X_train = train_df[FEATURE_COLUMNS].values
    y_train = train_df["label"].values

    X_val = val_df[FEATURE_COLUMNS].values
    y_val = val_df["label"].values

    model = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    random_state=42,
                ),
            ),
        ]
    )

    model.fit(X_train, y_train)
    val_scores = model.predict_proba(X_val)[:, 1]

    auc = roc_auc_score(y_val, val_scores)
    ndcg10, mrr10 = evaluate_grouped(val_df, val_scores, 10)

    print(f"AUC: {auc:.4f}")
    print(f"nDCG@10: {ndcg10:.4f}")
    print(f"MRR@10: {mrr10:.4f}")

    os.makedirs("ml/models/reranker_baseline", exist_ok=True)
    model_path = os.path.join("ml", "models", "reranker_baseline", "model.joblib")
    joblib.dump(model, model_path)

    with open(metadata_path, "r") as file:
        metadata = json.load(file)

    config = {
        "model_type": "logistic_regression",
        "feature_columns": FEATURE_COLUMNS,
        "global_ctr": metadata.get("global_ctr", 0.0),
        "category_ctr": metadata.get("category_ctr", {}),
        "subcategory_ctr": metadata.get("subcategory_ctr", {}),
        "history_k": metadata.get("history_k", 50),
        "half_life_days": metadata.get("half_life_days", 7.0),
        "neg_per_pos": metadata.get("neg_per_pos", 5),
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    metrics = {
        "auc": float(auc),
        "ndcg10": float(ndcg10),
        "mrr10": float(mrr10),
    }

    with open(os.path.join("ml", "models", "reranker_baseline", "feature_schema.json"), "w") as file:
        json.dump({"feature_columns": FEATURE_COLUMNS}, file, indent=2)

    with open(os.path.join("ml", "models", "reranker_baseline", "training_config.json"), "w") as file:
        json.dump(config, file, indent=2)

    with open(os.path.join("ml", "models", "reranker_baseline", "metrics.json"), "w") as file:
        json.dump(metrics, file, indent=2)


if __name__ == "__main__":
    main()
