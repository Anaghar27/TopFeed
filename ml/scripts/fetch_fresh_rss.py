import argparse
import json
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

sys.path.append("/app")

from app.services.fresh_ingest import fetch_rss_items


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--config", type=str, default="/app/ml/config/rss_sources.json")
    parser.add_argument("--output", type=str, default="/tmp/fresh_items.json")
    args = parser.parse_args()

    items = fetch_rss_items(args.config, args.hours)
    serialized_items = []
    for item in items:
        data = dict(item.__dict__)
        if data.get("published_at"):
            data["published_at"] = data["published_at"].isoformat()
        serialized_items.append(data)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hours": args.hours,
        "items": serialized_items,
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as handle:
        json.dump(payload, handle)

    print(f"items_fetched={len(items)}")
    print(f"output_path={args.output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
