import json
from pathlib import Path
import unittest

from tests.support import BenchCase, SEAT, listen_request, scenario


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


if __name__ == "__main__":
    unittest.main()
