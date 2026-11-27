from copy import deepcopy
from http.client import RemoteDisconnected

from monitor.listen_service import serve_monitor
from tests.support import BenchCase, HttpService, SEAT, listen_request, scalar, scenario


class MonitorTests(BenchCase):
    drop_request = "lost"

    def prepare(self):
        bench = self.bench
        bench.configure(assignments={"m2": "a"})
        origin = bench.record(101, {"m1": 80, "m2": 10, "m3": 60})["origin"]
        bench.record(103, {})
        frozen = bench.publish("rehearsal", [101, 103])
        bench.install(frozen)
        bench.handover("a")
        return frozen["edition"], origin

    def test_n6_bad_install_leaves_valid_offline_load(self):
        bench = self.bench
        origin = bench.record(101, {"m3": 42})["origin"]
        frozen = bench.publish("valid", [101])
        bench.install(frozen)
        bench.handover("a")

        bad = deepcopy(frozen["package"])
        del bad["frames"][0]["origin"]
        status, error = bench.monitor.call("load", {"seat": SEAT, "package": bad})
        self.assertEqual((status, error), (400, {"error": "invalid_edition", "field": "origin"}))
        bad = deepcopy(frozen["package"])
        del bad["frames"][0]["monitor_samples"]["b"]
        status, error = bench.monitor.call("load", {"seat": SEAT, "package": bad})
        self.assertEqual((status, error), (400, {"error": "invalid_edition", "field": "monitor_samples"}))
        bad = deepcopy(frozen["package"])
        bad["frames"][0]["program_sample"] = 43
        status, error = bench.monitor.call("load", {"seat": SEAT, "package": bad})
        self.assertEqual((status, error["error"]), (409, "edition_conflict"))
        self.assertEqual(scalar(bench.monitor_db, "SELECT COUNT(*) FROM installed_editions"), 1)
        bench.stop_source()
        self.assertEqual(bench.handover("a")["edition"], frozen["edition"])
        played = bench.listen("valid-after-rejection", frozen["edition"])
        self.assertEqual((played["operator"], played["sample"], played["origin"]), ("a", 42, origin))

    def test_n7_overlap_excludes_all_of_actual_speakers_contributions(self):
        bench = self.bench
        bench.configure(assignments={"m2": "a"})
        origin = bench.record(101, {"m1": 80, "m2": 10, "m3": 60})["origin"]
        bench.configure(assignments={"m2": "b"})
        frozen = bench.publish("historical-owners", [101])
        edition = frozen["edition"]
        self.assertEqual(bench.program_audio(edition, 1)["sample"], 127)
        bench.install(frozen)
        bench.stop_source()
        bench.handover("a")
        played = bench.listen("first", edition)
        self.assertEqual(played, dict(listen_request("first", edition), operator="a", sample=60,
                                      sequence=1, origin=origin))
        self.assertEqual(bench.receipt("first"), played)

    def test_n7_same_program_sound_can_have_different_offline_returns(self):
        bench = self.bench
        bench.configure(assignments={"m2": "a"})
        inputs = [{"m1": 80, "m2": 10, "m3": 60}, {"m1": 80, "m2": 10, "m3": 90}]
        origins = [bench.record(frame, samples)["origin"] for frame, samples in enumerate(inputs, 101)]
        bench.record(103, {})
        first = bench.publish("sixty", [101, 103])
        second = bench.publish("ninety", [102, 103])
        editions = [first["edition"], second["edition"]]
        self.assertNotEqual(*editions)
        programme = [bench.program_audio(edition, 1) for edition in editions]
        samples = [result["sample"] for result in programme]
        self.assertEqual(samples, [127, 127])
        self.assertEqual([result["origin"] for result in programme], origins)
        with HttpService(serve_monitor, bench.root / "comparison.sqlite") as other:
            bench.install(first)
            other.ok("load", {"seat": SEAT, "package": second["package"]})
            bench.stop_source()
            bench.handover("a")
            other.ok("handover", {"seat": SEAT, "operator": "a"})
            played = [bench.listen("solo", editions[0]), other.ok("listen_frame", listen_request("solo", editions[1]))]
        expected = [dict(listen_request("solo", edition), operator="a", sample=sample, sequence=1, origin=origin)
                    for edition, sample, origin in zip(editions, [60, 90], origins)]
        self.assertEqual(played, expected)
        scenario("n7.same_program", inputs, [127, 127], samples, expected, played,
                 ["release/freeze.py", "release/distribution.py", "monitor/install.py", "monitor/playback.py"],
                 "两次排除甲的 80 和 10，只剩乙的 60 或 90；节目总和分别为 150 和 180。")

    def test_n8_lost_reply_keeps_original_result_after_handover_and_reopen(self):
        bench = self.bench
        edition, origin = self.prepare()
        self.assertEqual(bench.program_audio(edition, 1)["sample"], 127)
        bench.stop_source()
        original = listen_request("lost", edition)
        with self.assertRaises(RemoteDisconnected):
            bench.monitor.call("listen_frame", original)
        expected_first = dict(original, operator="a", sample=60, sequence=1, origin=origin)
        self.assertEqual(bench.dropped, [expected_first])
        self.assertEqual(scalar(bench.monitor_db, "SELECT COUNT(*) FROM listen_events"), 1)
        bench.handover("b")
        bench.restart_monitor()

        receipt = bench.receipt("lost")
        replay = bench.monitor.ok("listen_frame", original)
        new = bench.listen("new", edition)
        expected_new = dict(listen_request("new", edition), operator="b", sample=90, sequence=2, origin=origin)
        self.assertEqual(receipt, expected_first)
        self.assertEqual(replay, expected_first)
        self.assertEqual(new, expected_new)
        for changed in [dict(original, frame=2), dict(original, edition=edition + 1)]:
            self.assertEqual(bench.monitor.call("listen_frame", changed),
                             (409, {"error": "request_conflict", "request": "lost"}))
        self.assertEqual(bench.receipt("lost"), expected_first)
        count = scalar(bench.monitor_db, "SELECT COUNT(*) FROM listen_events")
        self.assertEqual(count, 2)
        scenario("n8", {"contributions": {"m1": 80, "m2": 10, "m3": 60},
                        "events": ["甲出声", "回包丢失", "交给乙", "重开", "复领", "乙新听"]},
                 expected_first, bench.dropped[0],
                 {"receipt": expected_first, "replay": expected_first, "new": expected_new, "count": 2},
                 {"receipt": receipt, "replay": replay, "new": new, "count": count},
                 ["monitor/seats.py", "monitor/listen_service.py", "monitor/playback.py", "monitor/receipts.py"],
                 "按提交顺序及手算余声核对。甲余 60，乙余 80＋10，复领取第一次实听。")

    def test_n8_unknown_member_is_ineligible_even_if_added_to_source_later(self):
        bench = self.bench
        edition, _ = self.prepare()
        bench.configure(speakers={"c": "丙"})
        bench.stop_source()
        status, error = bench.monitor.call("handover", {"seat": SEAT, "operator": "c"})
        self.assertEqual((status, error), (400, {"error": "operator_not_in_roster", "operator": "c"}))
        played = bench.listen("after-invalid-handover", edition)
        self.assertEqual((played["operator"], played["sample"]), ("a", 60))

    def test_n8_unavailable_targets_leave_no_sound_or_receipt(self):
        bench = self.bench
        edition, origin = self.prepare()
        bench.stop_source()
        unavailable = [("missing-edition", edition + 1, 1, "edition_unavailable"),
                       ("missing-frame", edition, 99, "frame_unavailable")]
        for request, target, frame, code in unavailable:
            status, error = bench.monitor.call("listen_frame", listen_request(request, target, frame))
            self.assertEqual((status, error["error"]), (404, code))
            status, error = bench.monitor.call("receipt", seat=SEAT, request=request)
            self.assertEqual((status, error["error"]), (404, "receipt_unavailable"))
        self.assertEqual(scalar(bench.monitor_db, "SELECT COUNT(*) FROM listen_events"), 0)
        played = bench.listen("missing-frame", edition)
        self.assertEqual(played, dict(listen_request("missing-frame", edition), operator="a", sample=60,
                                      sequence=1, origin=origin))
