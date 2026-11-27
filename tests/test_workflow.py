import json
from pathlib import Path
import unittest

from tests.support import BenchCase, SEAT, listen_request, scenario
from tests.test_listener_seat import ListenerBench, prepare


SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "rehearsal.json"


class RehearsalWorkflowTests(BenchCase):
    def test_rehearsal_day(self):
        bench = self.bench
        sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
        config = bench.source.ok("configure", sample["configure"])
        self.assertEqual(config["assignments"], {"m1": "a", "m2": "a", "m3": "b"})
        recorded = [bench.source.ok("record_frame", body) for body in sample["record_frames"]]
        bench.configure(assignments={"m2": "b"})
        self.assertEqual(bench.recorded(101), recorded[0])
        preview = bench.source.ok("preview", sample["preview"])
        self.assertTrue(preview["freezable"])
        expected_programme = [127, -127, 0]
        self.assertEqual([frame["sample"] for frame in preview["frames"]], expected_programme)
        frozen = bench.freeze(sample["preview"]["revision"])
        edition = frozen["edition"]
        programme = [bench.program_audio(edition, frame) for frame in (1, 2, 3)]
        sounds = [frame["sample"] for frame in programme]
        self.assertEqual(sounds, expected_programme)
        self.assertEqual([frame["origin"] for frame in programme], [frame["origin"] for frame in recorded])
        self.assertEqual(bench.install(frozen)["edition"], edition)
        bench.stop_source()
        self.assertEqual(bench.monitor.ok("handover", sample["handover"])["operator"], "a")
        first = bench.listen("example-first", edition)
        expected_first = dict(listen_request("example-first", edition), operator="a", sample=60,
                              sequence=1, origin=recorded[0]["origin"])
        self.assertEqual(first, expected_first)
        bench.handover("b")
        bench.restart_monitor()
        second = bench.listen("example-second", edition)
        expected_second = dict(listen_request("example-second", edition), operator="b", sample=90,
                               sequence=2, origin=recorded[0]["origin"])
        self.assertEqual(second, expected_second)
        receipt = bench.monitor.ok("receipt", seat=SEAT, request="example-first")
        self.assertEqual(receipt, expected_first)
        scenario("n7", sample, expected_programme, sounds,
                 {"first": expected_first, "second": expected_second, "receipt": expected_first},
                 {"first": first, "second": second, "receipt": receipt},
                 ["studio/assignments.py", "capture/intake.py", "mix/revisions.py", "release/freeze.py",
                  "monitor/install.py", "monitor/playback.py", "monitor/receipts.py"],
                 "独立手算 150、−150、0 的节目值，以及排除甲后为 60、排除乙后为 90 的余声。")


class ListenerHandoverWorkflowTests(unittest.TestCase):
    """Demo the bound listener: real sound order, handover, original-number reclaim.

    Uses the LISTENER.md joint-rehearsal setup: frame 101 carries m1=-15 (a)
    and m3=25 (b); programme sound on frame 1 is 10, a's foldback is 25 and
    b's is -15.  The release side is stopped before any foldback happens.
    """

    def test_listener_handover_demo(self):
        bench = self.enterContext(ListenerBench())
        edition, origin = prepare(bench)
        controls = bench.controls

        # Operator a takes the booth; their q is held in transit, then the
        # booth is handed to b while the late command is still undelivered.
        self.assertEqual(bench.handover("initial", "a")[1]["status"], "completed")
        controls.defer_next_sound()
        status, pending = bench.listen("q", edition)
        self.assertEqual((status, pending["status"]), (202, "pending"))
        controls.set_unavailable(False)
        handed = bench.handover("to-b", "b")[1]
        self.assertEqual(handed["status"], "completed")

        # Late delivery of a's 25 conflicts and never sounds.
        delayed = controls.take_deferred()
        self.assertEqual(bench.device.call("operate", delayed)[0], 409)
        stopped = bench.receipt("q")[1]
        self.assertEqual(stopped["status"], "stopped")

        # b plays -15 under a new number; the only real sound is b's.
        played_b = bench.listen("r", edition)[1]
        self.assertEqual((played_b["operator"], played_b["sample"]), ("b", -15))
        sound_order = [entry["sample"] for entry in controls.sounds()]
        self.assertEqual(sound_order, [-15])

        scenario(
            "listener.handover",
            {"frame": 101, "m1": -15, "m3": 25, "programme_frame_1": 10,
             "events": ["受理 q(甲,25)", "延迟送达", "交席给乙", "迟到命令 409", "乙新号实出 -15"]},
            {"late_sound": "intercepted", "sound_order": [-15]},
            {"late_status": bench.device.call("state")[0], "sounds": sound_order},
            {"handover": handed, "q_receipt": stopped, "r": played_b},
            {"handover": handed,
             "q_receipt": {"seat": stopped["seat"], "request": stopped["request"],
                           "status": stopped["status"]},
             "r": {"request": played_b["request"], "operator": played_b["operator"],
                   "sample": played_b["sample"], "device_number": played_b["device_number"],
                   "origin": played_b["origin"]}},
            ["monitor/device.py", "monitor/listener.py", "monitor/listen_service.py"],
            "甲的 25 在交席后失去出声资格被 advance 截停；迟到命令预期号不匹配返回 409；"
            "乙用新号实出 −15，实际出声次序只有一笔 −15，原号 q 可查回 stopped。",
        )


if __name__ == "__main__":
    unittest.main()
