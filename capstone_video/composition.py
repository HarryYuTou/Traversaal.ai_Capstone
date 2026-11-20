"""Build continuous full-video coverage without changing narration or animation mode."""

import copy

from . import OUTPUT_SIZES, VideoError


def full_video_timeline(timeline, resolution):
    """Give the former card/pause intervals to the following generated scene."""
    if resolution not in OUTPUT_SIZES:
        raise VideoError("Choose 480p or 720p for the entire video.")
    result = copy.deepcopy(timeline)
    cursor = 0
    for scene in result["scenes"]:
        start, frames = scene["from"], scene["durationInFrames"]
        if type(start) is not int or type(frames) is not int or frames <= 0 or start < cursor:
            raise VideoError("The narrated scenes overlap or have invalid timing.")
        end = start + frames
        scene.update({"from": cursor, "durationInFrames": end - cursor})
        for line in scene["lines"]:
            # Quotes no longer have a separate text card, so their narration needs captions too.
            line.pop("highlightQuote", None)
        cursor = end
    if cursor != result["durationInFrames"] or not result["scenes"]:
        raise VideoError("Generated scenes must cover the complete narrated timeline.")
    result.update(visualMode="seedance-full", titleFrames=0, chapters=[])
    result["width"], result["height"] = OUTPUT_SIZES[resolution]
    return result


def require_full_coverage(timeline, plan):
    """Reject partial plans before any generation request, including missing cards or scenes."""
    if timeline.get("visualMode") != "seedance-full":
        raise VideoError("The full-video plan requires a full-video timeline.")
    cursor, total_shots = 0, 0
    for scene in timeline["scenes"]:
        shots = [shot for shot in plan["shots"] if shot["sceneId"] == scene["id"]]
        if scene["from"] != cursor or not shots:
            raise VideoError("Every frame must have Seedance footage; animation fallback is disabled.")
        end = 0
        for shot in shots:
            if shot["offsetFrames"] != end:
                raise VideoError("The generated shot plan contains a gap or overlap.")
            end += shot["durationInFrames"]
        if end != scene["durationInFrames"]:
            raise VideoError("The generated shots do not cover the complete scene.")
        cursor += end
        total_shots += len(shots)
    if cursor != timeline["durationInFrames"] or total_shots != len(plan["shots"]):
        raise VideoError("The generated shot plan does not cover the complete video.")
