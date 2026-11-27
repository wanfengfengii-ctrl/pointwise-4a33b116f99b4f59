import sqlite3
from contextlib import ExitStack, closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from monitor.listen_service import serve_monitor
from monitor.listener import sound_operation, stop_operation
from studio.source_service import serve_source
from tests.support import HttpService
from tests.test_listener_device import DeviceControls, serve_device


SEAT = "booth"
PROGRAM = "rehearsal"


class ListenerBench:
    """Source service, bound seat service and the external device fixture."""

    def __init__(self):
        self.stack = ExitStack()
        self.controls = DeviceControls()

    def __enter__(self):
        root = self.root = Path(self.stack.enter_context(TemporaryDirectory(prefix="listener-")))
        self.source_db = root / "source.sqlite"
        self.monitor_db = root / "monitor.sqlite"
        self.device_db = root / "device.sqlite"
        self.device = self.stack.enter_context(
            HttpService(serve_device, self.device_db, controls=self.controls)
        )
        self.device_port = self.device.server.server_address[1]
        self.source = self.stack.enter_context(
            HttpService(serve_source, self.source_db)
        )
        self.start_monitor()
        return self

    def __exit__(self, *exc):
        self.stack.close()

    def start_monitor(self):
        self.monitor = HttpService(
            serve_monitor, self.monitor_db, device_seat=SEAT, device_port=self.device_port
        )
        self.monitor.__enter__()
        self.stack.callback(self.monitor.__exit__, None, None, None)

    def restart_monitor(self):
        self.monitor.server.shutdown()
        self.monitor.thread.join()
        self.monitor.server.server_close()
        self.start_monitor()

    # -- source side ------------------------------------------------------- #
    def configure(self, **values):
        return self.source.ok("configure", {"program": PROGRAM, **values})

    def record(self, frame, samples):
        return self.source.ok("record_frame",
                              {"program": PROGRAM, "source_frame": frame, "contributions": samples})

    def publish(self, frames):
        revision = "evening"
        preview = self.source.ok("preview",
                                 {"program": PROGRAM, "revision": revision, "source_frames": frames})
        assert preview["freezable"], preview
        return self.source.ok("freeze", {"program": PROGRAM, "revision": revision})

    # -- seat side --------------------------------------------------------- #
    def install(self, frozen):
        return self.monitor.ok("load", {"seat": SEAT, "package": frozen["package"]})

    def handover(self, request, operator):
        return self.monitor.call("handover",
                                 {"seat": SEAT, "request": request, "operator": operator})

    def listen(self, request, edition, frame=1):
        return self.monitor.call("listen_frame",
                                 {"seat": SEAT, "request": request, "edition": edition, "frame": frame})

    def receipt(self, request):
        return self.monitor.call("receipt", seat=SEAT, request=request)


def prepare(bench):
    """Frame 101: m1=-15 (a), m3=25 (b); freeze [101], install, stop source."""
    bench.configure(speakers={"a": "甲", "b": "乙"},
                    assignments={"m1": "a", "m2": "b", "m3": "b"})
    recorded = bench.record(101, {"m1": -15, "m3": 25})
    frozen = bench.publish([101])
    edition = frozen["edition"]
    bench.install(frozen)
    # The release/source side is stopped; the seat keeps working offline.
    bench.source.server.shutdown()
    bench.source.thread.join()
    return edition, recorded["origin"]


class BoundListenerTests(unittest.TestCase):
    def setUp(self):
        self.bench = self.enterContext(ListenerBench())

    def test_delayed_sound_is_superseded_by_handover_and_late_delivery_stays_silent(self):
        bench = self.bench
        edition, origin = prepare(bench)
        status, initial = bench.handover("initial", "a")
        self.assertEqual((status, initial["status"]), (200, "completed"))

        # Accept q for operator a, but the sound command is held by the fixture.
        bench.controls.defer_next_sound()
        status, pending = bench.listen("q", edition)
        self.assertEqual((status, pending), (202, {"seat": SEAT, "request": "q", "status": "pending"}))
        self.assertEqual(bench.controls.sounds(), [])
        # A receipt query never reaches the device and never produces a sound.
        self.assertEqual(bench.receipt("q"),
                         (202, {"seat": SEAT, "request": "q", "status": "pending"}))

        # Device answers again; the held command has not been delivered yet.
        bench.controls.set_unavailable(False)
        # Handover must settle the old request (here via an intercept advance).
        status, handed = bench.handover("to-b", "b")
        self.assertEqual(status, 200)
        self.assertEqual(handed["status"], "completed")
        self.assertEqual(handed["operator"], "b")

        # The late delivery of a's sound now conflicts: no 25 ever sounds.
        delayed = bench.controls.take_deferred()
        self.assertEqual(delayed["sample"], 25)
        self.assertEqual(bench.device.call("operate", delayed)[0], 409)
        self.assertEqual(bench.controls.sounds(), [])

        # The old number can only reclaim its terminal, stopped result.
        self.assertEqual(bench.receipt("q"),
                         (200, {"seat": SEAT, "edition": edition, "frame": 1,
                                "request": "q", "status": "stopped"}))
        status, replayed = bench.listen("q", edition)
        self.assertEqual((status, replayed["status"]), (200, "stopped"))

        # b uses a new number and really hears -15 exactly once.
        status, played = bench.listen("r", edition)
        self.assertEqual(status, 200)
        self.assertEqual(played, {"seat": SEAT, "edition": edition, "frame": 1,
                                  "request": "r", "status": "played", "operator": "b",
                                  "sample": -15, "sequence": 1,
                                  "origin": origin, "device_number": 2})
        self.assertEqual([entry["sample"] for entry in bench.controls.sounds()], [-15])
        self.assertEqual(bench.device.ok("state")["number"], 2)

    def test_played_result_survives_dropped_reply_reopen_and_later_device_overwrite(self):
        bench = self.bench
        edition, origin = prepare(bench)
        self.assertEqual(bench.handover("initial", "a")[1]["status"], "completed")

        # q really plays 25, but the device's HTTP reply is dropped.
        bench.controls.drop_next_commit()
        status, pending = bench.listen("q", edition)
        self.assertEqual((status, pending["status"]), (202, "pending"))
        self.assertEqual([entry["sample"] for entry in bench.controls.sounds()], [25])

        # Reopen the seat with the same seat database; device becomes reachable.
        bench.restart_monitor()
        bench.controls.set_unavailable(False)
        self.assertEqual(bench.handover("to-b", "b")[1]["status"], "completed")

        # Re-driving q fixes the already-played fact and issues the first receipt.
        status, reclaimed = bench.listen("q", edition)
        self.assertEqual(status, 200)
        self.assertEqual(reclaimed, {"seat": SEAT, "edition": edition, "frame": 1,
                                     "request": "q", "status": "played", "operator": "a",
                                     "sample": 25, "sequence": 1,
                                     "origin": origin, "device_number": 1})
        self.assertEqual(bench.receipt("q"), (200, reclaimed))

        # b's new number overwrites the device head; q is still fully recoverable.
        status, second = bench.listen("r", edition)
        self.assertEqual(status, 200)
        self.assertEqual(second["sample"], -15)
        self.assertEqual(second["device_number"], 2)
        head = bench.device.ok("state")
        self.assertEqual(head["number"], 2)
        self.assertEqual(head["last"]["sample"], -15)
        self.assertEqual([entry["sample"] for entry in bench.controls.sounds()], [25, -15])
        # Each sound happened once; replaying q must not re-sound.
        status, replay = bench.listen("q", edition)
        self.assertEqual((status, replay["sample"]), (200, 25))
        self.assertEqual([entry["sample"] for entry in bench.controls.sounds()], [25, -15])

    def test_unverifiable_request_stays_pending_and_blocks_further_acceptance(self):
        bench = self.bench
        edition, origin = prepare(bench)
        self.assertEqual(bench.handover("initial", "a")[1]["status"], "completed")

        bench.controls.set_unavailable(True)
        status, pending = bench.listen("q", edition)
        self.assertEqual((status, pending), (202, {"seat": SEAT, "request": "q",
                                                   "status": "pending"}))
        # Query only; the device is never touched and no sound is produced.
        self.assertEqual(bench.receipt("q"), (202, pending))
        # Another listen cannot overwrite the unverified evidence; retry later.
        status, busy = bench.listen("other", edition)
        self.assertEqual((status, busy), (202, {"seat": SEAT, "request": "other",
                                                "status": "busy"}))
        self.assertEqual(bench.controls.sounds(), [])

        # Handover also cannot complete while the old request is unverifiable.
        status, held = bench.handover("to-b", "b")
        self.assertEqual((status, held), (202, {"seat": SEAT, "request": "to-b",
                                                "status": "pending"}))

        bench.controls.set_unavailable(False)
        # Same number, same parameters resumes and reaches its terminal played.
        status, played = bench.listen("q", edition)
        self.assertEqual(status, 200)
        self.assertEqual(played["sample"], 25)
        self.assertEqual(played["operator"], "a")
        self.assertEqual(played["origin"], origin)
        self.assertEqual(played["device_number"], 1)
        self.assertEqual([entry["sample"] for entry in bench.controls.sounds()], [25])

        # The held handover can now complete under its original number.
        status, handed = bench.handover("to-b", "b")
        self.assertEqual((status, handed["status"]), (200, "completed"))

    def test_same_number_with_changed_parameters_is_refused_without_driving_device(self):
        bench = self.bench
        edition, _ = prepare(bench)
        self.assertEqual(bench.handover("initial", "a")[1]["status"], "completed")
        bench.controls.set_unavailable(True)
        self.assertEqual(bench.listen("q", edition)[0], 202)
        changed_frame = {"seat": SEAT, "request": "q", "edition": edition, "frame": 2}
        changed_edition = {"seat": SEAT, "request": "q", "edition": edition + 1, "frame": 1}
        for body in (changed_frame, changed_edition):
            status, error = bench.monitor.call("listen_frame", body)
            self.assertEqual((status, error), (409, {"error": "request_conflict", "request": "q"}))
        bench.controls.set_unavailable(False)
        self.assertEqual(bench.controls.sounds(), [])
        status, played = bench.listen("q", edition)
        self.assertEqual((status, played["status"]), (200, "played"))

    def test_handover_number_is_idempotent_and_rejects_changed_operator(self):
        bench = self.bench
        edition, _ = prepare(bench)
        self.assertEqual(bench.handover("initial", "a")[1]["status"], "completed")
        first_status, first = bench.handover("move", "b")
        self.assertEqual(first_status, 200)
        # Same number/operator reclaims the identical result.
        self.assertEqual(bench.handover("move", "b"), (200, first))
        # Same number with a different operator is a conflict.
        self.assertEqual(bench.handover("move", "a"),
                         (409, {"error": "request_conflict", "request": "move"}))

    def test_handover_recovers_already_played_pending_request_and_reuses_receipt(self):
        bench = self.bench
        edition, origin = prepare(bench)
        self.assertEqual(bench.handover("initial", "a")[1]["status"], "completed")

        # q plays, but the reply to the seat is dropped (commit outlives response).
        bench.controls.drop_next_commit()
        self.assertEqual(bench.listen("q", edition)[0], 202)
        self.assertEqual([entry["sample"] for entry in bench.controls.sounds()], [25])
        bench.controls.set_unavailable(False)

        # Handover must recognize the sound really happened (old sound is
        # reconciled against operator a) before assigning the seat to b.
        status, handed = bench.handover("to-b", "b")
        self.assertEqual((status, handed["status"]), (200, "completed"))
        status, reclaimed = bench.listen("q", edition)
        self.assertEqual(status, 200)
        self.assertEqual((reclaimed["operator"], reclaimed["sample"]), ("a", 25))
        self.assertEqual(reclaimed["sequence"], 1)
        self.assertEqual(reclaimed["origin"], origin)
        # The sound happened exactly once; reconciliation did not replay it.
        self.assertEqual([entry["sample"] for entry in bench.controls.sounds()], [25])
        # b's fresh listen works with the new operator's value.
        status, played_b = bench.listen("r", edition)
        self.assertEqual((status, played_b["operator"], played_b["sample"]), (200, "b", -15))
        self.assertEqual([entry["sample"] for entry in bench.controls.sounds()], [25, -15])

    def test_handover_held_pending_resumes_by_original_number_after_recovery(self):
        bench = self.bench
        edition, _ = prepare(bench)
        self.assertEqual(bench.handover("initial", "a")[1]["status"], "completed")

        bench.controls.set_unavailable(True)
        self.assertEqual(bench.listen("q", edition)[0], 202)
        status, held = bench.handover("move", "b")
        self.assertEqual((status, held["status"]), (202, "pending"))

        # While down, re-issuing the same handover keeps returning pending.
        self.assertEqual(bench.handover("move", "b")[0], 202)
        bench.controls.set_unavailable(False)
        status, handed = bench.handover("move", "b")
        self.assertEqual(status, 200)
        self.assertEqual(handed, {"seat": SEAT, "operator": "b", "edition": edition,
                                  "request": "move", "status": "completed"})
        # q was intercepted (advance), so its number now reports stopped.
        self.assertEqual(bench.receipt("q"),
                         (200, {"seat": SEAT, "edition": edition, "frame": 1,
                                "request": "q", "status": "stopped"}))
        self.assertEqual(bench.controls.sounds(), [])
        # The new owner can immediately listen under a new number.
        status, played = bench.listen("r", edition)
        self.assertEqual((status, played["operator"], played["sample"]), (200, "b", -15))

    def _seat_row(self, request):
        with closing(sqlite3.connect(self.bench.monitor_db)) as db:
            db.row_factory = sqlite3.Row
            return dict(db.execute(
                "SELECT * FROM device_listens WHERE seat = ? AND request = ?",
                (SEAT, request)).fetchone())

    def test_persisted_operation_matches_device_and_redelivery_keeps_original_id(self):
        bench = self.bench
        edition, _ = prepare(bench)
        self.assertEqual(bench.handover("initial", "a")[1]["status"], "completed")

        # q plays; the seat must keep the same unique operation id the device ran.
        status, played = bench.listen("q", edition)
        self.assertEqual(status, 200)
        row = self._seat_row("q")
        expected_op = sound_operation(SEAT, "q")
        self.assertEqual(row["operation"], expected_op)
        self.assertEqual(row["status"], "played")
        head = bench.device.ok("state")
        self.assertEqual(head["last"]["operation"], expected_op)
        self.assertEqual(head["number"], row["device_number"])

        # Re-posting the original command (same operation id, expected, sample)
        # now conflicts because the head advanced; it never re-sounds.
        original = {"expected": 0, "operation": expected_op, "kind": "sound",
                    "sample": played["sample"]}
        self.assertEqual(bench.device.call("operate", original)[0], 409)
        self.assertEqual([entry["sample"] for entry in bench.controls.sounds()], [25])

    def test_stopped_request_persists_intercept_operation_and_terminal_device_number(self):
        bench = self.bench
        edition, _ = prepare(bench)
        self.assertEqual(bench.handover("initial", "a")[1]["status"], "completed")
        bench.controls.defer_next_sound()
        self.assertEqual(bench.listen("q", edition)[0], 202)
        bench.controls.set_unavailable(False)
        self.assertEqual(bench.handover("to-b", "b")[1]["status"], "completed")

        # The late sound command arrives only after the intercept advance and
        # therefore conflicts; the head still belongs to the intercept.
        delayed = bench.controls.take_deferred()
        self.assertEqual(bench.device.call("operate", delayed)[0], 409)

        row = self._seat_row("q")
        self.assertEqual(row["status"], "stopped")
        self.assertEqual(row["stop_operation"], stop_operation(SEAT, "q"))
        head = bench.device.ok("state")
        self.assertEqual(head["last"]["operation"], row["stop_operation"])
        self.assertEqual(head["number"], row["device_number"])
        self.assertEqual(head["last"]["kind"], "advance")
        self.assertIsNone(head["last"]["sample"])
        self.assertEqual(bench.controls.sounds(), [])

    def test_unknown_request_receipt_is_404_and_acceptance_uses_acceptance_time_owner(self):
        bench = self.bench
        edition, origin = prepare(bench)
        self.assertEqual(bench.handover("initial", "a")[1]["status"], "completed")
        self.assertEqual(bench.receipt("never"),
                         (404, {"error": "receipt_unavailable", "request": "never"}))
        status, played = bench.listen("a-only", edition)
        self.assertEqual(status, 200)
        self.assertEqual((played["operator"], played["sample"]), ("a", 25))
        # After handover the same frame yields b's value for a new request.
        self.assertEqual(bench.handover("to-b", "b")[1]["status"], "completed")
        status, played_b = bench.listen("b-only", edition)
        self.assertEqual((status, played_b["operator"], played_b["sample"]), (200, "b", -15))
        self.assertEqual(played["origin"], origin)


if __name__ == "__main__":
    unittest.main()
