import os
import sys
import shutil
import zipfile

RAW_ZIP_DIR = os.path.join("ml", "data", "raw", "mind", "large", "zips")
EXTRACT_DIR = os.path.join("ml", "data", "raw", "mind", "large", "extracted")

SPLITS = {
    "train": "MINDlarge_train.zip",
    "dev": "MINDlarge_dev.zip",
    "test": "MINDlarge_test.zip",
}


def extract_zip(split: str, zip_name: str) -> None:
    zip_path = os.path.join(RAW_ZIP_DIR, zip_name)
    target_dir = os.path.join(EXTRACT_DIR, split)

    if not os.path.exists(zip_path):
        raise FileNotFoundError(f"Missing zip: {zip_path}")

    os.makedirs(target_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(target_dir)

    news_path = os.path.join(target_dir, "news.tsv")
    behaviors_path = os.path.join(target_dir, "behaviors.tsv")

    if not os.path.isfile(news_path) or not os.path.isfile(behaviors_path):
        for root, _, files in os.walk(target_dir):
            if "news.tsv" in files and not os.path.isfile(news_path):
                shutil.move(os.path.join(root, "news.tsv"), news_path)
            if "behaviors.tsv" in files and not os.path.isfile(behaviors_path):
                shutil.move(os.path.join(root, "behaviors.tsv"), behaviors_path)

    if not os.path.isfile(news_path) or not os.path.isfile(behaviors_path):
        raise RuntimeError(
            f"Extraction failed for {split}: expected news.tsv and behaviors.tsv"
        )

    print(f"Extracted {zip_name} -> {target_dir}")


def main() -> None:
    for split, zip_name in SPLITS.items():
        extract_zip(split, zip_name)

    print("All splits extracted successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
