"""Compile causal process events into measured, deterministic motion.

The model chooses actors, stations and narration-bound events, never coordinates.
Source events advance their logical state at their end; intermediate movement is
an explicit visual transition. Generated actions retain their event's anchors for
provenance, while their absolute frame intervals are authoritative for playback.
"""

import math

from .scene_plan import ProcessVisual, initial_open_station_ids, motion_channel, process_problems

STAGE_WIDTH, STAGE_HEIGHT = 1200, 500
ACTOR_SIZE = 0.95
QUEUE_FRONT_X, QUEUE_SPACING, QUEUE_Y = 650, 90, 250
ENTRY_X, SERVICE_X, STATION_X, EXIT_X = 0, 820, 950, 1130
# A .95 person has a 62.7px half-height including stroke. Clear counter/workbench
# (55px) by >12px; the taller server (66px) gets an additional 10px corridor.
EXIT_CLEARANCE = 130
MIN_ARRIVAL_FRAMES = 18
MIN_START_TRAVEL_FRAMES = 18
MIN_WORK_FRAMES = 30
MIN_COMPACTION_FRAMES = 12
MIN_COMPLETE_FRAMES = 12
MIN_EXIT_TRAVEL_FRAMES = 24
MIN_FADE_FRAMES = 8
MIN_OPEN_FRAMES = 18
# Walking routes turn on a short curve instead of a sharp corner, cutting only the inside of the
# corner (at most CORNER_RADIUS / 4 from it), so they never leave their corridors.
CORNER_RADIUS, CORNER_STEPS = 60, 8
# A departing actor keeps walking while it fades, at most this far past the exit point.
EXIT_OVERRUN = 60
# Mirrors the renderer's `walk` easing (renderer/src/motion/engine.ts).
WALK_RAMP = 0.25


class ProcessCompileError(ValueError):
    """A source event cannot be shown faithfully in its measured narration span."""


def _point(x: float, y: float) -> dict:
    return {"x": x * 100 / STAGE_WIDTH, "y": y * 100 / STAGE_HEIGHT}


def _walk(t: float) -> float:
    """Share of a walk's distance covered after share t of its time: smooth start and stop, steady middle."""
    t = min(1.0, max(0.0, t))
    top = 1 / (1 - WALK_RAMP)

    def ramp(x):
        return x ** 3 - x ** 4 / 2
    if t < WALK_RAMP:
        return top * WALK_RAMP * ramp(t / WALK_RAMP)
    if t > 1 - WALK_RAMP:
        return 1 - top * WALK_RAMP * ramp((1 - t) / WALK_RAMP)
    return top * (t - WALK_RAMP / 2)


def _rounded(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Replace each interior corner with a short quadratic curve through the inside of the corner."""
    result = [points[0]]
    for before, corner, after in zip(points, points[1:], points[2:]):
        into, out = math.dist(before, corner), math.dist(corner, after)
        radius = min(CORNER_RADIUS, into / 2, out / 2)
        cross = (corner[0] - before[0]) * (after[1] - corner[1]) - (corner[1] - before[1]) * (after[0] - corner[0])
        if radius < 1 or abs(cross) < 1e-9:
            result.append(corner)
            continue
        start = tuple(c - (c - b) * radius / into for b, c in zip(before, corner))
        end = tuple(c + (a - c) * radius / out for a, c in zip(after, corner))
        for step in range(CORNER_STEPS + 1):
            t = step / CORNER_STEPS
            result.append(tuple((1 - t) ** 2 * s + 2 * (1 - t) * t * c + t ** 2 * e
                                for s, c, e in zip(start, corner, end)))
    result.append(points[-1])
    return result


def _queue_point(index: int) -> tuple[int, int]:
    return QUEUE_FRONT_X - index * QUEUE_SPACING, QUEUE_Y


def _service_list(service: dict[str, str]) -> list[dict]:
    return [{"actorId": actor, "stationId": station} for station, actor in service.items()]


def _event_frames(event, lines: list[dict], scene_start: int, scene_end: int, index: int):
    first, last = lines[event.start_line], lines[event.end_line]
    start = first["from"] + round(first["durationInFrames"] * event.start_offset)
    end = last["from"] + round(last["durationInFrames"] * event.end_offset)
    if not scene_start <= start < end <= scene_end:
        raise ProcessCompileError(f"Process event {index} ({event.kind}) must span positive frames inside "
                                  f"the scene; got {start}–{end} inside {scene_start}–{scene_end}.")
    return start, end


def compile_process_visual(visual: ProcessVisual, lines: list[dict], scene_start: int, scene_end: int):
    """Return (motion visual, processTrace), without changing source data or adding story events.

    Work means an ongoing activity, not a progress percentage or a promise that it
    completes at the scene boundary. Only an authored finish event creates a complete cue.
    """
    problems = process_problems(visual, len(lines), "process")
    if problems:
        raise ProcessCompileError("; ".join(problems))
    if scene_end <= scene_start:
        raise ProcessCompileError("A process scene must have positive duration.")
    station_y = {station.id: (250 if len(visual.stations) == 1 else (140, 360)[index])
                 for index, station in enumerate(visual.stations)}
    station_clearance = {station.id: EXIT_CLEARANCE + (10 if station.kind == "server" else 0)
                         for station in visual.stations}
    queue = list(visual.initial_queue)
    initial_open = initial_open_station_ids(visual)
    open_stations = set(initial_open)
    service = {item.station_id: item.actor_id for item in visual.initial_service}
    completed = []
    active_since = {item.actor_id: scene_start for item in visual.initial_service}
    positions = {actor.id: (ENTRY_X, QUEUE_Y) for actor in visual.actors}
    positions.update({actor: _queue_point(index) for index, actor in enumerate(queue)})
    positions.update({actor: (SERVICE_X, station_y[station]) for station, actor in service.items()})
    visible = set(queue) | set(service.values())
    entities = [{"id": station.id, "kind": station.kind, **_point(STATION_X, station_y[station.id]),
                 "size": 1.0, "rotation": 0.0, "opacity": 1.0, "value": 0.0,
                 "color": station.color, "label": station.label} for station in visual.stations]
    entities += [{"id": actor.id, "kind": visual.actor_kind, **_point(*positions[actor.id]),
                  "size": ACTOR_SIZE, "rotation": 0.0, "opacity": float(actor.id in visible), "value": 0.0,
                  "color": actor.color, "label": actor.label} for actor in visual.actors]
    paths, actions, activities, events = [], [], [], []
    actor_colors = {actor.id: actor.color for actor in visual.actors}
    previous_end = scene_start

    def emit(event, actor_id, kind, start, end, *, path_id="", target=(0, 0), value=0.0, easing="ease-in-out"):
        if not scene_start <= start < end <= scene_end:
            raise ProcessCompileError(f"A compiled {kind} for {actor_id!r} has invalid frame bounds {start}–{end}.")
        actions.append({"entityId": actor_id, "kind": kind,
                        "startLine": event.start_line, "endLine": event.end_line,
                        "startOffset": event.start_offset, "endOffset": event.end_offset,
                        "pathId": path_id, **_point(*target), "value": value, "easing": easing,
                        "from": start, "durationInFrames": end - start})

    def travel(event, event_index, actor_id, start, end, points):
        path_id = f"process-{event_index:02d}-{len(paths):02d}"
        # Straight segments keep routes inside their declared corridors; no curve overshoot.
        cleaned = [point for index, point in enumerate(points) if index == 0 or point != points[index - 1]]
        if len(cleaned) < 2:
            raise ProcessCompileError(f"Process event {event_index} gives {actor_id!r} no travel distance.")
        paths.append({"id": path_id, "points": [_point(*point) for point in _rounded(cleaned)],
                      "curved": False, "closed": False, "color": actor_colors[actor_id]})
        emit(event, actor_id, "follow-path", start, end, path_id=path_id, easing="walk")
        positions[actor_id] = cleaned[-1]

    def work_until(actor_id, end, event_index):
        start = active_since.pop(actor_id)
        if end - start < MIN_WORK_FRAMES:
            raise ProcessCompileError(f"Process event {event_index} (finish) gives {actor_id!r} only "
                                      f"{end - start} visible work frames after reaching its station; "
                                      f"at least {MIN_WORK_FRAMES} are required. Add a narrated hold or finish later.")
        station_id = next(station for station, actor in service.items() if actor == actor_id)
        for entity_id in (actor_id, station_id):
            activities.append({"entityId": entity_id, "kind": "work", "from": start,
                               "durationInFrames": end - start})

    for index, event in enumerate(visual.events):
        start, end = _event_frames(event, lines, scene_start, scene_end, index)
        if start < previous_end:
            raise ProcessCompileError(f"Process event {index} overlaps the previous event after frame compilation.")
        previous_end = end
        duration = end - start
        if event.kind == "arrive":
            minimum = MIN_ARRIVAL_FRAMES * len(event.actor_ids)
        elif event.kind == "start":
            minimum = MIN_START_TRAVEL_FRAMES + MIN_WORK_FRAMES
        elif event.kind == "finish":
            minimum = MIN_COMPLETE_FRAMES + MIN_EXIT_TRAVEL_FRAMES + MIN_FADE_FRAMES
        elif event.kind == "open":
            minimum = MIN_OPEN_FRAMES
        else:
            minimum = 1
        if duration < minimum:
            raise ProcessCompileError(f"Process event {index} ({event.kind}) has {duration} frames; "
                                      f"at least {minimum} are needed for {len(event.actor_ids)} actor(s). "
                                      "Use longer narrated lines or span additional lines.")
        before_queue, before_service, before_completed = list(queue), _service_list(service), list(completed)
        before_open = [station.id for station in visual.stations if station.id in open_stations]
        movement_end = start
        phases = []
        if event.kind == "open":
            # Opening is shown by the renderer from this explicit, measured phase;
            # the station stays in place while its CLOSED marker becomes OPEN.
            phases.append({"kind": "open", "actorIds": [], "stationIds": list(event.station_ids),
                           "from": start, "durationInFrames": duration})
            open_stations.update(event.station_ids)
            movement_end = end
        elif event.kind == "arrive":
            for offset, actor_id in enumerate(event.actor_ids):
                actor_start = start + duration * offset // len(event.actor_ids)
                actor_end = start + duration * (offset + 1) // len(event.actor_ids)
                target = _queue_point(len(queue))
                emit(event, actor_id, "move", actor_start, actor_end, target=target, easing="walk")
                emit(event, actor_id, "opacity", actor_start, actor_start + min(8, actor_end - actor_start), value=1)
                positions[actor_id] = target
                queue.append(actor_id)
                phases.append({"kind": "arrive", "actorIds": [actor_id], "from": actor_start,
                               "durationInFrames": actor_end - actor_start})
            movement_end = end
        elif event.kind == "start":
            # Reserve a legible working interval even when finish immediately follows this event.
            travel_frames = max(MIN_START_TRAVEL_FRAMES, min(round(duration * 0.6), duration - MIN_WORK_FRAMES))
            arrival = start + travel_frames
            for actor_id, station_id in zip(event.actor_ids, event.station_ids):
                x, y = positions[actor_id]
                destination_y = station_y[station_id]
                # Branch vertically at each actor's own queue slot, then move horizontally. Actors
                # heading to different stations never merge into a shared turn or pass the queue.
                travel(event, index, actor_id, start, arrival,
                       [(x, y), (x, destination_y), (SERVICE_X, destination_y)])
                service[station_id] = actor_id
                active_since[actor_id] = arrival
            queue = queue[len(event.actor_ids):]
            for position, actor_id in enumerate(queue):
                target = _queue_point(position)
                emit(event, actor_id, "move", arrival, end, target=target, easing="walk")
                positions[actor_id] = target
            phases.append({"kind": "to-service", "actorIds": list(event.actor_ids), "from": start,
                           "durationInFrames": travel_frames})
            if queue:
                phases.append({"kind": "compact-queue", "actorIds": list(queue), "from": arrival,
                               "durationInFrames": end - arrival})
            movement_end = end if queue else arrival
        elif event.kind == "finish":
            complete_frames = max(MIN_COMPLETE_FRAMES, min(24, duration // 5))
            fade_frames = max(MIN_FADE_FRAMES, min(12, duration // 8))
            # Phase floors remain valid at the shortest accepted event duration.
            if duration - complete_frames - fade_frames < MIN_EXIT_TRAVEL_FRAMES:
                complete_frames, fade_frames = MIN_COMPLETE_FRAMES, MIN_FADE_FRAMES
            travel_start, travel_end = start + complete_frames, end - fade_frames
            for actor_id, station_id in zip(event.actor_ids, event.station_ids):
                work_until(actor_id, start, index)
                activities.append({"entityId": station_id, "kind": "complete", "from": start,
                                   "durationInFrames": complete_frames})
                x, y = positions[actor_id]
                # Leave on the side away from the other station. Crossing the station body is never
                # necessary: first take the corridor at x=820, then pass above/below its entire body.
                clearance = station_clearance[station_id]
                exit_y = y - clearance if y <= QUEUE_Y else y + clearance
                # One unbroken walk: reach the exit as the fade begins and keep going while fading,
                # rather than stopping at the exit and vanishing on the spot.
                reached = _walk((travel_end - travel_start) / (end - travel_start))
                distance = abs(exit_y - y) + EXIT_X - x
                overrun = min(EXIT_OVERRUN, distance * (1 / reached - 1))
                travel(event, index, actor_id, travel_start, end,
                       [(x, y), (x, exit_y), (EXIT_X + overrun, exit_y)])
                emit(event, actor_id, "opacity", travel_end, end, value=0)
                del service[station_id]
                completed.append(actor_id)
            phases.extend([
                {"kind": "complete", "actorIds": list(event.actor_ids), "from": start,
                 "durationInFrames": complete_frames},
                {"kind": "exit", "actorIds": list(event.actor_ids), "from": travel_start,
                 "durationInFrames": travel_end - travel_start},
                {"kind": "fade", "actorIds": list(event.actor_ids), "from": travel_end,
                 "durationInFrames": fade_frames},
            ])
            movement_end = travel_end
        events.append({"kind": event.kind, "from": start, "durationInFrames": duration,
                       "actorIds": list(event.actor_ids), "stationIds": list(event.station_ids),
                       "startLine": event.start_line, "endLine": event.end_line,
                       "startOffset": event.start_offset, "endOffset": event.end_offset,
                       "queueBefore": before_queue, "queueAfter": list(queue),
                       "serviceBefore": before_service, "serviceAfter": _service_list(service),
                       "completedBefore": before_completed, "completedAfter": list(completed),
                       "openStationsBefore": before_open,
                       "openStationsAfter": [station.id for station in visual.stations if station.id in open_stations],
                       "movementEndFrame": movement_end, "minRequiredFrames": minimum, "phases": phases})

    for actor_id, start in active_since.items():
        if scene_end > start:
            station_id = next(station for station, actor in service.items() if actor == actor_id)
            for entity_id in (actor_id, station_id):
                activities.append({"entityId": entity_id, "kind": "work", "from": start,
                                   "durationInFrames": scene_end - start})
    # Guard the expanded representation too; queue compaction, travel and fades may share event
    # anchors but can never compete for an entity's actual frame/property interval.
    channels = {}
    for action in actions:
        key = action["entityId"], motion_channel(action["kind"])
        start, end = action["from"], action["from"] + action["durationInFrames"]
        if any(start < other_end and other_start < end for other_start, other_end in channels.get(key, [])):
            raise ProcessCompileError(f"Compiled process actions overlap for {key[0]!r} on {key[1]!r}.")
        channels.setdefault(key, []).append((start, end))
    result = {"title": visual.title, "entities": entities, "paths": paths, "actions": actions,
              "activities": sorted(activities, key=lambda activity: (activity["from"], activity["entityId"]))}
    trace = {"sourceTemplate": "process", "actorIds": [actor.id for actor in visual.actors],
             "stationEntityIds": [station.id for station in visual.stations],
             "initialOpenStationIds": initial_open,
             "finalOpenStationIds": [station.id for station in visual.stations if station.id in open_stations],
             "initialQueue": list(visual.initial_queue),
             "initialService": [item.model_dump(by_alias=True) for item in visual.initial_service],
             "finalQueue": list(queue), "finalService": _service_list(service), "completed": list(completed),
             "events": events}
    return result, trace
