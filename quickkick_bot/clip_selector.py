#!/usr/bin/env python3
"""
CLIP Image Selector
===================
Given a list of scene descriptions and a folder of local photos,
returns the best-matching image per scene using OpenAI CLIP semantics.

Dependencies (install once via setup_clip.bat):
    pip install open-clip-torch Pillow

Usage:
    from clip_selector import select_images_by_scenes
    from pathlib import Path

    photos = select_images_by_scenes(
        scene_descriptions=["Colonel Tom Parker signing a contract", "Elvis on stage in Vegas"],
        image_folder=Path("Quickkick Upscale/batch_001"),
    )
    # Returns: [Path("...Colonel_Tom_Parker...png"), Path("...Elvis_Vegas...png")]
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Cache model between calls within the same process run
_MODEL_CACHE: dict = {}


def _load_model():
    """Load and cache the CLIP model (ViT-B/32, ~350MB download first time)."""
    if "model" in _MODEL_CACHE:
        return _MODEL_CACHE["model"], _MODEL_CACHE["preprocess"], _MODEL_CACHE["tokenizer"]

    try:
        import open_clip
        import torch
    except ImportError:
        raise ImportError(
            "open-clip-torch is not installed. Run setup_clip.bat to install it."
        )

    logger.info("[CLIP] Loading ViT-B/32 model (first run downloads ~350MB)...")
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="openai"
    )
    tokenizer = open_clip.get_tokenizer("ViT-B-32")
    model.eval()

    _MODEL_CACHE["model"] = model
    _MODEL_CACHE["preprocess"] = preprocess
    _MODEL_CACHE["tokenizer"] = tokenizer
    logger.info("[CLIP] Model loaded.")
    return model, preprocess, tokenizer


def _encode_images(image_paths: list[Path], preprocess, model) -> "torch.Tensor":
    """Encode a list of images into CLIP feature vectors."""
    import torch
    from PIL import Image

    features = []
    for p in image_paths:
        try:
            img_tensor = preprocess(Image.open(p).convert("RGB")).unsqueeze(0)
            with torch.no_grad():
                feat = model.encode_image(img_tensor)
                feat = feat / feat.norm(dim=-1, keepdim=True)
            features.append(feat)
        except Exception as e:
            logger.warning(f"[CLIP] Could not encode {p.name}: {e} — skipping")
            features.append(None)

    # Replace failed images with zero vectors so indexing stays consistent
    if features:
        dim = next(f for f in features if f is not None).shape[-1]
        features = [
            f if f is not None else torch.zeros(1, dim)
            for f in features
        ]
        return torch.cat(features, dim=0)  # [N, D]
    return torch.zeros(0, 512)


def select_images_by_scenes(
    scene_descriptions: list[str],
    image_folder: Path,
    allow_reuse: bool = False,
) -> list[Path]:
    """
    For each scene description, find the best matching image in image_folder.

    Parameters
    ----------
    scene_descriptions : list of str
        One description per scene (narration text or visual direction).
    image_folder : Path
        Folder containing .png / .jpg photos to choose from.
    allow_reuse : bool
        If True, the same photo can be used for multiple scenes.
        If False (default), each photo is used at most once.

    Returns
    -------
    list of Path  — same length as scene_descriptions (or shorter if not enough photos).
    """
    import torch

    # Gather all candidate images
    images = (
        sorted(image_folder.glob("*.png"))
        + sorted(image_folder.glob("*.jpg"))
        + sorted(image_folder.glob("*.jpeg"))
    )
    if not images:
        logger.warning(f"[CLIP] No images found in {image_folder}")
        return []

    if not scene_descriptions:
        return images[: len(scene_descriptions)]

    model, preprocess, tokenizer = _load_model()

    # Encode all images
    logger.info(f"[CLIP] Encoding {len(images)} photos...")
    img_features = _encode_images(images, preprocess, model)  # [N, D]

    # Encode all scene descriptions
    # CLIP tokenizer truncates at 77 tokens; trim descriptions to be safe
    trimmed_descs = [d[:300] for d in scene_descriptions]
    with torch.no_grad():
        text_tokens = tokenizer(trimmed_descs)
        text_features = model.encode_text(text_tokens)  # [S, D]
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)

    # Cosine similarity matrix: [S, N]
    similarity = (text_features @ img_features.T).cpu().tolist()

    # Greedy assignment: each scene picks its best unused photo
    used: set[int] = set()
    result: list[Path] = []

    for scene_idx, scores in enumerate(similarity):
        ranked = sorted(range(len(images)), key=lambda x: scores[x], reverse=True)

        chosen = None
        for img_idx in ranked:
            if allow_reuse or img_idx not in used:
                chosen = img_idx
                break

        if chosen is None:
            # Fallback: reuse best match
            chosen = ranked[0]

        used.add(chosen)
        result.append(images[chosen])
        logger.info(
            f"[CLIP] Scene {scene_idx + 1}: {images[chosen].name} "
            f"(score {scores[chosen]:.3f})"
        )

    return result
