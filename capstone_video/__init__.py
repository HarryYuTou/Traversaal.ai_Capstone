"""Seedance clips for the existing narrated explainer pipeline."""

MODEL_ID = "doubao-seedance-2-0-fast-260128"
MODEL_NAME = "Doubao-Seedance-2.0-fast"
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
RESOLUTIONS = ("480p", "720p")
OUTPUT_SIZES = {"480p": (854, 480), "720p": (1280, 720)}


class VideoError(RuntimeError):
    """A safe, actionable message that may be shown in the local studio."""


class SubmissionUnknown(VideoError):
    """A POST may have reached the provider. Never automatically submit it again."""
