"""Promote a trained ML model from ml-model/models/vX.Y/ into
Backend/app/ml/models/, replacing the manual copy-paste step.

Runs the exact same cross-validation as app/ml/model_loader.py before
copying anything, so a mismatched model/feature-list/manifest triple can
never make it into the deployed models directory in the first place.

Usage (run from Backend/):
    python scripts/promote_model.py                  # auto-picks the highest vX.Y under ml-model/models/
    python scripts/promote_model.py --source ../ml-model/models/v3.0
"""
import argparse
import importlib.util
import json
import pickle
import re
import shutil
import sys
from pathlib import Path

# Load model_loader.py directly rather than `from app.ml import model_loader` —
# importing the app.ml package eagerly pulls in predictor.py -> database.crud
# -> a live SQLAlchemy engine needing DATABASE_URL, none of which this
# standalone promotion script should ever need.
_spec = importlib.util.spec_from_file_location(
    "model_loader", Path(__file__).parent.parent / "app" / "ml" / "model_loader.py"
)
model_loader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(model_loader)
_validate_model_artifacts = model_loader._validate_model_artifacts
ModelValidationError = model_loader.ModelValidationError

DEST_DIR = Path("app/ml/models")


def _find_latest_version_dir(models_root: Path) -> Path:
    version_dirs = []
    for d in models_root.iterdir():
        if not d.is_dir():
            continue
        m = re.fullmatch(r"v(\d+)\.(\d+)", d.name)
        if m:
            version_dirs.append((int(m.group(1)), int(m.group(2)), d))

    if not version_dirs:
        raise FileNotFoundError(f"No vX.Y model directories found under {models_root}")

    version_dirs.sort(key=lambda t: (t[0], t[1]))
    return version_dirs[-1][2]


def promote(source_dir: Path):
    info_path = source_dir / "model_info.json"
    if not info_path.exists():
        raise FileNotFoundError(
            f"{info_path} not found — every promoted model must ship a model_info.json manifest."
        )

    info = json.loads(info_path.read_text())

    features_file = info.get("features_file", "model_features.pkl")
    model_file = info.get("model_file")
    if not model_file:
        # Older manifests (from before this promotion script existed) don't
        # record model_file explicitly. Fall back to convention: every
        # existing vX.Y directory has exactly one other .pkl file alongside
        # model_features.pkl, and that's the model.
        candidates = [
            p.name for p in source_dir.glob("*.pkl") if p.name != features_file
        ]
        if len(candidates) != 1:
            raise ValueError(
                f"{info_path} doesn't record 'model_file', and {source_dir} "
                f"doesn't have exactly one other .pkl file to fall back to "
                f"(found: {candidates or 'none'}). Add 'model_file' to the manifest."
            )
        model_file = candidates[0]

    model_path = source_dir / model_file
    features_path = source_dir / features_file
    for p in (model_path, features_path):
        if not p.exists():
            raise FileNotFoundError(f"Expected artifact not found: {p}")

    with open(model_path, "rb") as f:
        model = pickle.load(f)
    with open(features_path, "rb") as f:
        features = pickle.load(f)

    # Same check model_loader.py runs at app startup — catches a mismatched
    # model/feature-list/manifest triple before it's ever copied into place.
    _validate_model_artifacts(model, model_path, features)

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    for src in (model_path, features_path):
        shutil.copy2(src, DEST_DIR / src.name)

    # Write the manifest back out with model_file/features_file guaranteed
    # present, even if the source manifest predated this script and relied
    # on the naming-convention fallback above — keeps the deployed manifest
    # fully self-describing for next time.
    info["model_file"] = model_file
    info["features_file"] = features_file
    (DEST_DIR / "model_info.json").write_text(json.dumps(info, indent=2))

    print(f"Promoted {info.get('version', '?')} from {source_dir} -> {DEST_DIR}")
    print(f"  {model_path.name}")
    print(f"  {features_path.name}")
    print(f"  {info_path.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Directory containing the trained model artifacts (default: highest vX.Y under ../ml-model/models/)",
    )
    args = parser.parse_args()

    source_dir = args.source or _find_latest_version_dir(Path("../ml-model/models"))
    source_dir = source_dir.resolve()

    print(f"Validating artifacts in {source_dir}...")
    try:
        promote(source_dir)
    except (ModelValidationError, FileNotFoundError, ValueError) as e:
        print(f"REFUSING to promote: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
