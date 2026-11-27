from tests.support import BenchCase, PROGRAM, revision_request, scalar, scenario


class PublishTests(BenchCase):
    def test_n3_positive_negative_and_empty_frames(self):
        bench = self.bench
        inputs = [{"m1": 80, "m2": 10, "m3": 60}, {"m1": -80, "m2": -10, "m3": -60}, {}]
        origins = [bench.record(101 + index, samples)["origin"] for index, samples in enumerate(inputs)]
        self.assertEqual(bench.recorded(103)["contributions"], [])
        self.assertEqual(origins, [
            {"program": PROGRAM, "source_frame": 101, "recording_receipt": 1},
            {"program": PROGRAM, "source_frame": 102, "recording_receipt": 2},
            {"program": PROGRAM, "source_frame": 103, "recording_receipt": 3},
        ])
        proof = bench.preview("performance", [101, 102, 103])
        self.assertTrue(proof["freezable"])
        self.assertEqual(proof["missing"], [])
        expected = [{"frame": index, "sample": sample, "origin": origin}
                    for index, (sample, origin) in enumerate(zip([127, -127, 0], origins), 1)]
        self.assertEqual(proof["frames"], expected)
        frozen = bench.freeze("performance")
        edition = frozen["edition"]
        audio = [bench.program_audio(edition, index) for index in (1, 2, 3)]
        downstream = [dict(frame, edition=edition) for frame in expected]
        self.assertEqual(audio, downstream)
        scenario("n3", inputs, expected, proof["frames"], downstream, audio,
                 ["mix/preview.py", "mix/revisions.py", "release/freeze.py", "release/program_audio.py"],
                 "手算 150、−150、空和 0，在每帧全部求和后将前两项限幅。")

    def test_n3_cancellation_uses_unclipped_sum(self):
        bench = self.bench
        inputs = [{"m1": 100, "m2": 80, "m3": -70}, {"m1": -100, "m2": -80, "m3": 70}]
        origins = [bench.record(index, samples)["origin"] for index, samples in enumerate(inputs, 201)]
        proof = bench.preview("cancellation", [201, 202])
        expected = [110, -110]
        actual = [frame["sample"] for frame in proof["frames"]]
        self.assertEqual(actual, expected)
        self.assertEqual([frame["origin"] for frame in proof["frames"]], origins)
        edition = bench.freeze("cancellation")["edition"]
        audio = [bench.program_audio(edition, frame) for frame in (1, 2)]
        sounds = [frame["sample"] for frame in audio]
        self.assertEqual(sounds, expected)
        self.assertEqual([frame["origin"] for frame in audio], origins)
        scenario("n3.cancellation", inputs, expected, actual, expected, sounds,
                 ["capture/contributions.py", "mix/preview.py", "release/program_audio.py"],
                 "手算 100＋80−70＝110，反号后为 −110。")

    def test_integer_accumulation_exceeds_sqlite_integer_width(self):
        bench = self.bench
        large = 2**70
        recorded = bench.record(201, {"m1": large + 9, "m3": -large})
        self.assertEqual(bench.recorded(201), recorded)
        self.assertEqual([item["sample"] for item in recorded["contributions"]], [large + 9, -large])
        edition = bench.publish("wide", [201])["edition"]
        self.assertEqual(bench.program_audio(edition, 1)["sample"], 9)

    def test_n4_missing_revision_cannot_publish(self):
        bench = self.bench
        bench.record(101, {"m1": 18})
        old = bench.publish("old", [101])["edition"]
        previous = bench.program_audio(old, 1)
        proof = bench.preview("gap", [101, 404, 404])
        missing = [{"frame": 2, "source_frame": 404}, {"frame": 3, "source_frame": 404}]
        self.assertFalse(proof["freezable"])
        self.assertEqual(proof["missing"], missing)
        self.assertEqual([frame["frame"] for frame in proof["frames"]], [1])
        status, error = bench.source.call("freeze", revision_request("gap"))
        self.assertEqual((status, error), (409, {"error": "revision_not_freezable", "revision": "gap",
                                                 "missing": missing}))
        self.assertEqual(scalar(bench.source_db, "SELECT COUNT(*) FROM editions"), 1)
        self.assertEqual(bench.program_audio(old, 1), previous)
        bench.record(404, {})
        completed = bench.preview("gap", [101, 404, 404])
        self.assertTrue(completed["freezable"])
        self.assertEqual([frame["sample"] for frame in completed["frames"]], [18, 0, 0])
        self.assertNotEqual(bench.freeze("gap")["edition"], old)

    def test_n5_old_and_new_editions_keep_their_positions(self):
        bench = self.bench
        positive = bench.record(101, {"m1": 80, "m3": 60})["origin"]
        blank = bench.record(102, {})["origin"]
        first = bench.publish("first", [101, 102])["edition"]
        second = bench.publish("second", [102, 101, 102])["edition"]
        self.assertNotEqual(first, second)
        for edition, sequence in [(first, [(127, positive), (0, blank)]),
                                  (second, [(0, blank), (127, positive), (0, blank)])]:
            for frame, (sample, origin) in enumerate(sequence, 1):
                self.assertEqual(bench.program_audio(edition, frame),
                                 {"edition": edition, "frame": frame, "sample": sample, "origin": origin})
        status, error = bench.source.call("preview", revision_request("first", source_frames=[102, 101]))
        self.assertEqual((status, error["error"]), (409, "revision_sequence_conflict"))
        for edition, frame, code in [(first, 3, "frame_unavailable"), (999, 1, "edition_unavailable")]:
            status, error = bench.source.call("program_audio", edition=edition, frame=frame)
            self.assertEqual((status, error["error"]), (404, code))
