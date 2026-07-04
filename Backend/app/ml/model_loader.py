import pickle
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_cached_model = None
_model_version = None


class ModelValidationError(Exception):
    """Raised when the loaded model, its feature list, and its manifest
    don't all agree — signals a mismatched/stale copy from the training
    notebooks rather than a matched set of artifacts."""


def _validate_model_artifacts(model, model_path: Path, features: list | None):
    """Cross-check the model's own feature schema against model_features.pkl
    and model_info.json, so a mismatched copy-paste from the training
    notebooks fails loudly at load time instead of silently degrading
    predictions later."""
    info_path = model_path.parent / "model_info.json"
    if not info_path.exists():
        logger.warning(
            f"No model_info.json found next to {model_path.name} — "
            "skipping model/feature manifest validation."
        )
        return info_path, None

    with open(info_path, "r") as f:
        info = json.load(f)

    manifest_model_file = info.get("model_file")
    if manifest_model_file and manifest_model_file != model_path.name:
        raise ModelValidationError(
            f"model_info.json expects model file '{manifest_model_file}' "
            f"but '{model_path.name}' was loaded — mismatched artifact pair."
        )

    manifest_features = info.get("features")
    if manifest_features is not None:
        if features is not None and list(features) != list(manifest_features):
            raise ModelValidationError(
                "model_features.pkl does not match the feature list recorded "
                f"in model_info.json for {model_path.name}. "
                f"model_features.pkl has {len(features)} features, "
                f"manifest expects {len(manifest_features)}."
            )

        model_feature_names = getattr(model, "feature_names_in_", None)
        if model_feature_names is not None and list(model_feature_names) != list(manifest_features):
            raise ModelValidationError(
                f"The trained model's own feature_names_in_ does not match "
                f"model_info.json's feature list for {model_path.name} — "
                "this model was not trained on the features this manifest describes."
            )

    return info_path, info


def load_model(model_path="app/ml/models/f1_winner_model_v3.pkl"):
    global _cached_model, _model_version

    if _cached_model is not None:
        return _cached_model

    model_path = Path(model_path)

    if not model_path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")

    with open(model_path, 'rb') as f:
        model = pickle.load(f)

    features = load_model_features()
    _, info = _validate_model_artifacts(model, model_path, features)
    _model_version = info.get('version', '3.0') if info else "3.0"

    _cached_model = model
    return _cached_model

def load_model_features():
    """Load the list of features used by the model"""
    features_path = Path("app/ml/models/model_features.pkl")
    if features_path.exists():
        with open(features_path, 'rb') as f:
            return pickle.load(f)
    return None

def get_model_version():
    return _model_version if _model_version else "Not loaded"