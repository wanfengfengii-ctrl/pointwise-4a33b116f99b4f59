from tests.support import BenchCase, PROGRAM, record_request, scalar


class RecordTests(BenchCase):
    def test_n1_recording_keeps_acceptance_owner(self):
        bench = self.bench
        self.assertEqual(bench.configure()["assignments"]["m2"], "b")
        configured = bench.configure(assignments={"m2": "a"})
        self.assertEqual(configured["speakers"], {"a": "甲", "b": "乙"})
        self.assertEqual(configured["assignments"], {"m1": "a", "m2": "a", "m3": "b"})
        recorded = bench.record(101, {"m1": 80, "m2": 10, "m3": 60})
        self.assertEqual(recorded["contributions"], [
            {"microphone": "m1", "speaker": "a", "sample": 80},
            {"microphone": "m2", "speaker": "a", "sample": 10},
            {"microphone": "m3", "speaker": "b", "sample": 60},
        ])
        self.assertEqual(recorded["origin"], {"program": PROGRAM, "source_frame": 101, "recording_receipt": 1})
        bench.configure(assignments={"m2": "b"})
        self.assertEqual(bench.recorded(101), recorded)
        later = bench.record(102, {"m2": 10})
        self.assertEqual(later["contributions"], [{"microphone": "m2", "speaker": "b", "sample": 10}])
        status, error = bench.source.call("record_frame", record_request(101, {}))
        self.assertEqual((status, error["error"]), (409, "source_frame_exists"))
        self.assertEqual(bench.recorded(101), recorded)

    def test_n2_unassigned_microphone_rejects_entire_frame(self):
        bench = self.bench
        accepted = bench.record(101, {"m1": 10})
        status, error = bench.source.call("record_frame", record_request(102, {"m1": 5, "z": 20}))
        self.assertEqual((status, error), (400, {"error": "unassigned_microphone", "microphone": "z"}))
        status, error = bench.source.call("record_frame", program=PROGRAM, source_frame=102)
        self.assertEqual((status, error["error"]), (404, "source_frame_unavailable"))
        self.assertEqual(scalar(bench.source_db, "SELECT COUNT(*) FROM contributions"), 1)
        self.assertEqual(scalar(bench.source_db, "SELECT COUNT(*) FROM recording_receipts"), 1)
        self.assertEqual(bench.recorded(101), accepted)

    def test_n2_unknown_speaker_rejects_configuration_atomically(self):
        bench = self.bench
        before = bench.configure()
        status, error = bench.source.call("configure", {
            "program": PROGRAM,
            "speakers": {"guest": "客串"},
            "assignments": {"m1": "b", "m2": "unregistered"},
        })
        self.assertEqual((status, error), (400, {"error": "unknown_speaker", "speaker": "unregistered"}))
        self.assertEqual(bench.configure(), before)
        registered = bench.configure(speakers={"guest": "客串"}, assignments={"m2": "guest"})
        self.assertEqual(registered["speakers"]["guest"], "客串")
        self.assertEqual(bench.record(104, {"m2": 2})["contributions"][0]["speaker"], "guest")

    def test_n2_non_integer_rejects_null_boolean_string_and_fraction(self):
        bench = self.bench
        for value in [None, True, "2", 1.5, 2.0]:
            with self.subTest(value=value):
                status, error = bench.source.call("record_frame", record_request(107, {"m1": 3, "m2": value}))
                self.assertEqual((status, error), (400, {"error": "invalid_input", "field": "contributions.m2"}))
                self.assertEqual(bench.source.call("record_frame", program=PROGRAM, source_frame=107)[0], 404)
        self.assertEqual(scalar(bench.source_db, "SELECT COUNT(*) FROM contributions"), 0)
        self.assertEqual(scalar(bench.source_db, "SELECT COUNT(*) FROM recording_receipts"), 0)
