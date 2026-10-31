"""Process compiler: causal states, readable phases and collision-free deterministic routes."""

import copy
import hashlib
import itertools
import json
import math
from pathlib import Path
import unittest

from capstone_script.process import (
    ACTOR_SIZE, MIN_ARRIVAL_FRAMES, MIN_COMPLETE_FRAMES, MIN_EXIT_TRAVEL_FRAMES,
    MIN_FADE_FRAMES, MIN_OPEN_FRAMES, MIN_WORK_FRAMES, ProcessCompileError, compile_process_visual,
)
from capstone_script.scene_plan import dump_plan, validate_plan
from capstone_script.timeline import (
    CHAPTER_FRAMES, END_FRAMES, LEAD_FRAMES, TITLE_FRAMES, TimelineError, build_timeline,
)
from test_process_contract import event, process_plan


def narrated(plan, frames=120):
    return {"status": "completed", "sampleRate": 48000,
            "planSha256": hashlib.sha256(dump_plan(plan).encode()).hexdigest(),
            "blocks": [{"narrationId": line.id, "sampleRate": 48000, "channels": 1,
                        "sampleCount": 1600 * frames, "audioPath": f"audio/{line.id}.wav"}
                       for scene in plan.scenes for line in scene.narration]}


def build(data=None, frames=120):
    plan = validate_plan(data or process_plan())
    return build_timeline(plan, narrated(plan, frames))


def walk(fraction, ramp=0.25):
    """Steady pace between smooth starts and stops: speed follows smoothstep over each ramp."""
    top = 1 / (1 - ramp)
    if fraction > 1 - ramp:
        return 1 - walk(1 - fraction, ramp)
    if fraction < ramp:
        x = fraction / ramp
        return top * ramp * (x ** 3 - x ** 4 / 2)
    return top * (fraction - ramp / 2)


def states_at(visual, frame):
    """Independent playback oracle for the compiler's straight paths and eased scalar movements.

    Geometry invariants are checked over every rendered frame rather than snapshotting the
    compiler's output. This intentionally supports only the finite process grammar's output.
    """
    paths = {path["id"]: path for path in visual["paths"]}
    states = {}
    for entity in visual["entities"]:
        state = {"x": entity["x"] * 12, "y": entity["y"] * 5, "opacity": entity["opacity"]}
        for action in sorted((a for a in visual["actions"] if a["entityId"] == entity["id"]), key=lambda a: a["from"]):
            if frame < action["from"]:
                continue
            fraction = min(1, (frame - action["from"]) / action["durationInFrames"])
            if action["easing"] == "walk":
                eased = walk(fraction)
            else:
                eased = 4 * fraction ** 3 if fraction < 0.5 else 1 - (-2 * fraction + 2) ** 3 / 2
            if action["kind"] == "opacity":
                state["opacity"] += (action["value"] - state["opacity"]) * eased
            elif action["kind"] == "move":
                state["x"] += (action["x"] * 12 - state["x"]) * eased
                state["y"] += (action["y"] * 5 - state["y"]) * eased
            elif action["kind"] == "follow-path":
                points = [(point["x"] * 12, point["y"] * 5) for point in paths[action["pathId"]]["points"]]
                lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
                remaining = sum(lengths) * eased
                for a, b, length in zip(points, points[1:], lengths):
                    if remaining <= length:
                        ratio = remaining / length
                        state.update(x=a[0] + (b[0] - a[0]) * ratio, y=a[1] + (b[1] - a[1]) * ratio)
                        break
                    remaining -= length
                else:
                    state.update(x=points[-1][0], y=points[-1][1])
            else:
                raise AssertionError(f"Unexpected process action {action['kind']}")
        states[entity["id"]] = state
    return states


class ProcessTimelineTests(unittest.TestCase):
    def test_process_compiles_to_motion_and_keeps_source_plan_unchanged(self):
        data = process_plan()
        plan = validate_plan(data)
        timeline = build_timeline(plan, narrated(plan))
        scene = timeline["scenes"][0]
        self.assertEqual(scene["template"], "motion")
        self.assertEqual(json.loads(dump_plan(plan)), data)
        self.assertEqual(scene["processTrace"]["sourceTemplate"], "process")
        self.assertEqual(scene["processTrace"]["actorIds"], ["a", "b", "c"])
        self.assertEqual(scene["processTrace"]["stationEntityIds"], ["one", "two"])
        self.assertEqual(scene["processTrace"]["finalQueue"], ["c"])
        self.assertEqual(scene["processTrace"]["completed"], ["a", "b"])
        self.assertEqual(scene["lines"][0]["from"], TITLE_FRAMES + LEAD_FRAMES)
        first_action = scene["visual"]["actions"][0]
        self.assertEqual(first_action["from"], scene["lines"][0]["from"])
        self.assertEqual((first_action["startLine"], first_action["endLine"]), (0, 0))
        self.assertTrue(all("highlight" not in str(line) for line in scene["lines"]))

    def test_trace_records_state_before_and_after_each_authored_event(self):
        scene = build()["scenes"][0]
        trace = scene["processTrace"]["events"]
        self.assertEqual([item["kind"] for item in trace], ["start", "hold", "finish", "arrive"])
        self.assertEqual(trace[0]["queueBefore"], ["a", "b"])
        self.assertEqual(trace[0]["queueAfter"], [])
        self.assertEqual(trace[0]["serviceAfter"], [{"actorId": "a", "stationId": "one"},
                                                 {"actorId": "b", "stationId": "two"}])
        self.assertEqual(trace[1]["serviceBefore"], trace[1]["serviceAfter"])
        self.assertEqual(trace[2]["completedBefore"], [])
        self.assertEqual(trace[2]["completedAfter"], ["a", "b"])
        self.assertEqual(trace[2]["serviceAfter"], [])
        self.assertEqual(trace[3]["queueAfter"], ["c"])

    def test_open_keeps_actors_and_stations_in_place_then_enables_service(self):
        data = process_plan()
        data["scenes"][0]["visual"]["events"] = [event("hold"),
                                                    event("open", stations=("two",), line=1),
                                                    event("start", ("a", "b"), ("one", "two"), 2),
                                                    event("hold", line=3)]
        scene = build(data)["scenes"][0]
        trace = scene["processTrace"]
        opening = trace["events"][1]
        self.assertEqual(trace["initialOpenStationIds"], ["one"])
        self.assertEqual(trace["finalOpenStationIds"], ["one", "two"])
        self.assertEqual(opening["openStationsBefore"], ["one"])
        self.assertEqual(opening["openStationsAfter"], ["one", "two"])
        self.assertEqual(opening["queueBefore"], opening["queueAfter"])
        self.assertEqual(opening["serviceBefore"], opening["serviceAfter"])
        self.assertEqual(opening["minRequiredFrames"], MIN_OPEN_FRAMES)
        phase = opening["phases"][0]
        self.assertEqual(phase, {"kind": "open", "actorIds": [], "stationIds": ["two"],
                                "from": opening["from"], "durationInFrames": opening["durationInFrames"]})
        for frame in (scene["from"], opening["from"], opening["from"] + opening["durationInFrames"]):
            state = states_at(scene["visual"], frame)
            self.assertAlmostEqual(state["a"]["x"], 650)
            self.assertAlmostEqual(state["two"]["x"], 950)
            self.assertEqual(state["two"]["opacity"], 1)
        self.assert_geometry(scene)

    def test_existing_plans_keep_all_stations_open_without_added_open_events(self):
        trace = build()["scenes"][0]["processTrace"]
        self.assertEqual(trace["initialOpenStationIds"], ["one", "two"])
        self.assertTrue(all(event["openStationsBefore"] == event["openStationsAfter"] == ["one", "two"]
                            for event in trace["events"]))

    def test_explicit_closed_station_remains_visible_and_closed_without_an_open_event(self):
        data = process_plan()
        visual = data["scenes"][0]["visual"]
        visual["stations"][0]["initialState"] = "open"
        visual["stations"][1]["initialState"] = "closed"
        visual["events"] = [event("start", ("a",), ("one",)), event("hold", line=1),
                            event("finish", ("a",), ("one",), 2), event("hold", line=3)]
        scene = build(data)["scenes"][0]
        trace = scene["processTrace"]
        self.assertEqual(trace["initialOpenStationIds"], ["one"])
        self.assertEqual(trace["finalOpenStationIds"], ["one"])
        self.assertTrue(all(item["openStationsBefore"] == item["openStationsAfter"] == ["one"]
                            for item in trace["events"]))
        self.assertFalse(any(item["entityId"] == "two" for item in scene["visual"]["activities"]))
        for frame in (scene["from"], scene["from"] + scene["durationInFrames"] - 1):
            self.assertEqual(states_at(scene["visual"], frame)["two"]["opacity"], 1)
        self.assert_geometry(scene)

    def test_explicit_and_legacy_openings_compile_to_the_same_station_lifecycle(self):
        data = process_plan()
        visual = data["scenes"][0]["visual"]
        visual["events"] = [event("open", stations=("two",)),
                            event("start", ("a", "b"), ("one", "two"), 1),
                            event("hold", line=2, end_line=3)]
        legacy = build(data)["scenes"][0]
        for state in (None, "closed"):
            with self.subTest(initial_state=state):
                visual["stations"][1]["initialState"] = state
                explicit = build(data)["scenes"][0]
                self.assertEqual(explicit["processTrace"], legacy["processTrace"])
                self.assertEqual(explicit["visual"], legacy["visual"])

    def test_open_minimum_is_measured_and_rejects_unreadable_speech_span(self):
        data = process_plan()
        data["scenes"][0]["visual"]["events"] = [event("open", stations=("one", "two"))]
        with self.assertRaisesRegex(TimelineError, f"at least {MIN_OPEN_FRAMES} are needed"):
            build(data, frames=MIN_OPEN_FRAMES - 1)
        trace = build(data, frames=MIN_OPEN_FRAMES)["scenes"][0]["processTrace"]
        self.assertEqual(trace["initialOpenStationIds"], [])
        self.assertEqual(trace["finalOpenStationIds"], ["one", "two"])

    def test_counter_comparison_fixture_proves_two_vs_one_completed_service_rounds(self):
        path = Path(__file__).resolve().parents[1] / "fixtures" / "scene-plan.process-counter-comparison.json"
        data = json.loads(path.read_text())
        timeline = build(data)
        baseline, replay = timeline["scenes"]
        self.assertEqual(baseline["processTrace"]["initialQueue"], replay["processTrace"]["initialQueue"])
        self.assertEqual(baseline["processTrace"]["initialService"], replay["processTrace"]["initialService"])
        # Count observed completion rounds before the same last actor starts, not
        # animation seconds, which follow spoken explanation rather than a clock.
        rounds = []
        for scene in timeline["scenes"]:
            before_last = []
            for event_data in scene["processTrace"]["events"]:
                if event_data["kind"] == "start" and "customer-c" in event_data["actorIds"]:
                    break
                before_last.append(event_data)
            rounds.append(sum(event_data["kind"] == "finish" for event_data in before_last))
            self.assert_geometry(scene)
        self.assertEqual(rounds, [2, 1])
        baseline_entities = {entity["id"]: entity for entity in baseline["visual"]["entities"]}
        replay_entities = {entity["id"]: entity for entity in replay["visual"]["entities"]}
        for entity_id in baseline_entities:
            for key in ("kind", "x", "y", "color", "label"):
                self.assertEqual(baseline_entities[entity_id][key], replay_entities[entity_id][key])
        self.assertEqual(baseline["processTrace"]["initialOpenStationIds"], ["counter-1"])
        self.assertEqual(baseline["processTrace"]["finalOpenStationIds"], replay["processTrace"]["initialOpenStationIds"])
        opening, result_hold = baseline["processTrace"]["events"][-2:]
        self.assertEqual((opening["kind"], result_hold["kind"]), ("open", "hold"))
        self.assertEqual(opening["from"] + opening["durationInFrames"], result_hold["from"])
        self.assertGreater(result_hold["durationInFrames"], opening["durationInFrames"])

    def test_complete_then_exit_then_fade_are_sequential_and_work_precedes_them(self):
        scene = build()["scenes"][0]
        finish = scene["processTrace"]["events"][2]
        complete, travel, fade = finish["phases"]
        self.assertEqual([part["kind"] for part in finish["phases"]], ["complete", "exit", "fade"])
        self.assertGreaterEqual(complete["durationInFrames"], MIN_COMPLETE_FRAMES)
        self.assertGreaterEqual(travel["durationInFrames"], MIN_EXIT_TRAVEL_FRAMES)
        self.assertGreaterEqual(fade["durationInFrames"], MIN_FADE_FRAMES)
        self.assertEqual(complete["from"] + complete["durationInFrames"], travel["from"])
        self.assertEqual(travel["from"] + travel["durationInFrames"], fade["from"])
        work = next(item for item in scene["visual"]["activities"] if item["entityId"] == "a" and item["kind"] == "work")
        self.assertGreaterEqual(work["durationInFrames"], MIN_WORK_FRAMES)
        self.assertEqual(work["from"] + work["durationInFrames"], complete["from"])
        complete_entities = {item["entityId"] for item in scene["visual"]["activities"] if item["kind"] == "complete"}
        self.assertEqual(complete_entities, {"one", "two"})
        state = states_at(scene["visual"], fade["from"])
        self.assertEqual(state["a"]["opacity"], 1)
        self.assertAlmostEqual(state["a"]["x"], 1130, delta=1)
        final = states_at(scene["visual"], finish["from"] + finish["durationInFrames"])
        # The departure is one walk: the actor keeps moving away while it fades, never stops to vanish.
        self.assertGreater(final["a"]["x"], state["a"]["x"] + 5)
        self.assertEqual(final["a"]["opacity"], 0)
        self.assertEqual(final["b"]["opacity"], 0)

    def test_unfinished_service_remains_working_through_final_hold_without_false_completion(self):
        data = process_plan()
        data["scenes"][0]["visual"]["events"] = [event("start", ("a",), ("one",)), event("hold", line=1, end_line=3)]
        scene = build(data)["scenes"][0]
        end = scene["from"] + scene["durationInFrames"]
        work = [item for item in scene["visual"]["activities"] if item["kind"] == "work"]
        self.assertEqual({item["entityId"] for item in work}, {"a", "one"})
        self.assertTrue(all(item["from"] + item["durationInFrames"] == end for item in work))
        self.assertFalse(any(item["kind"] == "complete" for item in scene["visual"]["activities"]))
        self.assertGreaterEqual(end - scene["lines"][-1]["from"] - scene["lines"][-1]["durationInFrames"], END_FRAMES)

    def test_initial_service_is_visible_exactly_and_requires_time_before_finish(self):
        data = process_plan()
        data["scenes"][0]["visual"].update(initialQueue=["b"], initialService=[{"actorId": "a", "stationId": "one"}],
                                           events=[event("hold"), event("finish", ("a",), ("one",), 1)])
        scene = build(data)["scenes"][0]
        actors = {item["id"]: item for item in scene["visual"]["entities"]}
        self.assertEqual(actors["a"]["opacity"], 1)
        self.assertAlmostEqual(actors["a"]["x"] * 12, 820)
        self.assertAlmostEqual(actors["b"]["x"] * 12, 650)
        self.assertEqual(actors["c"]["opacity"], 0)
        data["scenes"][0]["visual"]["events"] = [event("finish", ("a",), ("one",))]
        with self.assertRaisesRegex(TimelineError, "only 6 visible work frames"):
            build(data)

    def test_arrivals_are_staggered_in_queue_order_and_never_recycle_departed_actors(self):
        data = process_plan()
        data["scenes"][0]["visual"].update(initialQueue=[], events=[event("arrive", ("a", "b", "c"))])
        scene = build(data)["scenes"][0]
        phases = scene["processTrace"]["events"][0]["phases"]
        self.assertEqual([item["actorIds"] for item in phases], [["a"], ["b"], ["c"]])
        for before, after in zip(phases, phases[1:]):
            self.assertEqual(before["from"] + before["durationInFrames"], after["from"])
        state = states_at(scene["visual"], phases[1]["from"] - 1)
        self.assertEqual(state["b"]["opacity"], 0)
        self.assertEqual(state["c"]["opacity"], 0)
        final = states_at(scene["visual"], phases[-1]["from"] + phases[-1]["durationInFrames"])
        self.assertEqual([round(final[key]["x"]) for key in ("a", "b", "c")], [650, 560, 470])

    def test_queue_compaction_waits_until_removed_actors_reach_service(self):
        data = process_plan()
        data["scenes"][0]["visual"].update(initialQueue=["a", "b", "c"], events=[event("start", ("a",), ("one",))])
        scene = build(data)["scenes"][0]
        transfer, compaction = scene["processTrace"]["events"][0]["phases"]
        self.assertEqual(transfer["from"] + transfer["durationInFrames"], compaction["from"])
        for frame in range(transfer["from"], compaction["from"]):
            state = states_at(scene["visual"], frame)
            self.assertEqual(state["b"]["x"], 560)
            self.assertEqual(state["c"]["x"], 470)
        end = compaction["from"] + compaction["durationInFrames"]
        state = states_at(scene["visual"], end)
        self.assertEqual(round(state["b"]["x"]), 650)
        self.assertEqual(round(state["c"]["x"]), 560)

    def test_chapters_and_later_scenes_keep_absolute_frames_and_deterministic_results(self):
        data = process_plan()
        second = copy.deepcopy(data["scenes"][0])
        second["id"] = "scene-02"
        for index, line in enumerate(second["narration"], 1):
            line["id"] = f"scene-02-line-{index:02d}"
        data["scenes"].append(second)
        data["chapters"] = [{"id": f"chapter-{i:02d}", "title": f"Chapter {i}", "sceneIds": [scene["id"]]}
                            for i, scene in enumerate(data["scenes"], 1)]
        first = build(data)
        self.assertEqual(first, build(data))
        self.assertEqual(first["scenes"][0]["visual"]["actions"][0]["from"], TITLE_FRAMES + CHAPTER_FRAMES + LEAD_FRAMES)
        for scene in first["scenes"]:
            for action in scene["visual"]["actions"]:
                self.assertGreaterEqual(action["from"], scene["from"])
                self.assertLessEqual(action["from"] + action["durationInFrames"], scene["from"] + scene["durationInFrames"])
        self.assertGreater(first["scenes"][1]["processTrace"]["events"][0]["from"], first["scenes"][0]["from"])

    def test_insufficient_action_time_fails_with_event_context_instead_of_skipping_motion(self):
        cases = [(event("arrive", ("c",)), MIN_ARRIVAL_FRAMES - 1, "arrive"),
                 (event("start", ("a",), ("one",)), 47, "start")]
        for item, duration, kind in cases:
            with self.subTest(kind=kind):
                data = process_plan()
                data["scenes"][0]["visual"]["events"] = [item]
                with self.assertRaisesRegex(TimelineError, f"Process event 0 \\({kind}\\) has {duration} frames"):
                    build(data, frames=duration)
        data = process_plan()
        data["scenes"][0]["visual"].update(initialQueue=["b"], initialService=[{"actorId": "a", "stationId": "one"}],
                                           events=[event("hold"), event("finish", ("a",), ("one",), 1)])
        with self.assertRaisesRegex(TimelineError, "at least 44"):
            build(data, frames=43)

    def test_shortest_start_still_leaves_one_second_of_visible_work(self):
        data = process_plan()
        data["scenes"][0]["visual"]["events"] = [event("start", ("a", "b"), ("one", "two")),
                                                    event("finish", ("a", "b"), ("one", "two"), 1)]
        scene = build(data, frames=48)["scenes"][0]
        durations = [item["durationInFrames"] for item in scene["visual"]["activities"] if item["kind"] == "work"]
        self.assertTrue(all(duration >= MIN_WORK_FRAMES for duration in durations))

    def test_every_frame_keeps_people_clear_of_station_bodies_and_other_people(self):
        # Exercise both station orders, departures, new arrivals and compaction, including eight
        # initially queued actors. Match the renderer's measured glyph bounds plus stroke.
        for station_count, reversed_order, station_kind, actor_kind in itertools.product(
                (1, 2), (False, True), ("counter", "workbench", "server"), ("person", "packet", "box", "coin")):
            with self.subTest(station_count=station_count, reversed=reversed_order,
                              station=station_kind, actor=actor_kind):
                data = process_plan()
                v = data["scenes"][0]["visual"]
                ids = [f"actor-{n}" for n in range(8)]
                v["actors"] = [{"id": actor, "color": "accent", "label": ""} for actor in ids]
                v["actorKind"] = actor_kind
                v["initialQueue"] = ids[:]
                v["stations"] = v["stations"][:station_count]
                for station in v["stations"]:
                    station["kind"] = station_kind
                stations = [station["id"] for station in v["stations"]]
                if reversed_order:
                    stations.reverse()
                v["events"] = [event("start", ids[:station_count], stations), event("hold", line=1),
                               event("finish", ids[:station_count], stations, 2),
                               event("start", ids[station_count:2 * station_count], stations, 3)]
                scene = build(data)["scenes"][0]
                self.assert_geometry(scene)
        arrival = process_plan()
        arrival["scenes"][0]["visual"].update(initialQueue=[], events=[event("arrive", ("a", "b", "c"))])
        self.assert_geometry(build(arrival)["scenes"][0])

    def test_eight_arrivals_fit_the_queue_and_even_the_last_actor_moves(self):
        data = process_plan()
        v = data["scenes"][0]["visual"]
        ids = [f"actor-{n}" for n in range(8)]
        v["actors"] = [{"id": actor, "color": "accent", "label": ""} for actor in ids]
        v.update(initialQueue=[], events=[event("arrive", ids)])
        scene = build(data, frames=240)["scenes"][0]
        end = scene["processTrace"]["events"][0]["movementEndFrame"]
        initial, final = states_at(scene["visual"], scene["from"]), states_at(scene["visual"], end)
        self.assertEqual(round(final[ids[-1]]["x"]), 20)
        self.assertTrue(all(final[actor]["x"] > initial[actor]["x"] for actor in ids))
        self.assertTrue(all(entity["size"] == 0.95 for entity in scene["visual"]["entities"] if entity["id"] in ids))
        self.assert_geometry(scene)

    def assert_geometry(self, scene):
        v = scene["visual"]
        actors = set(scene["processTrace"]["actorIds"])
        station_ids = set(scene["processTrace"]["stationEntityIds"])
        entities = {entity["id"]: entity for entity in v["entities"]}
        # Source of truth: renderer/src/motion/metrics.ts. The 3px margin includes strokes.
        measured = {"person": (41, 63), "packet": (36, 28), "box": (43, 49), "coin": (41, 46),
                    "counter": (58, 52), "workbench": (58, 52), "server": (44, 63)}
        bounds = {key: tuple((extent + 3) * entity["size"] for extent in measured[entity["kind"]])
                  for key, entity in entities.items()}
        for frame in range(scene["from"], scene["from"] + scene["durationInFrames"]):
            state = states_at(v, frame)
            visible = [actor for actor in actors if state[actor]["opacity"] > 0.01]
            for actor in visible:
                person = state[actor]
                self.assertTrue(0 <= person["x"] <= 1200 and 0 <= person["y"] <= 500)
                for station_id in station_ids:
                    station = state[station_id]
                    overlap = abs(person["x"] - station["x"]) < bounds[actor][0] + bounds[station_id][0] \
                        and abs(person["y"] - station["y"]) < bounds[actor][1] + bounds[station_id][1]
                    self.assertFalse(overlap, (frame, actor, station_id, person, station))
            for a, b in itertools.combinations(visible, 2):
                overlap = abs(state[a]["x"] - state[b]["x"]) < bounds[a][0] + bounds[b][0] \
                    and abs(state[a]["y"] - state[b]["y"]) < bounds[a][1] + bounds[b][1]
                self.assertFalse(overlap, (frame, a, b, state[a], state[b]))


if __name__ == "__main__":
    unittest.main()
