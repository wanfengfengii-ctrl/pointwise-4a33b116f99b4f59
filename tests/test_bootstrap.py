from contextlib import closing
import sqlite3

from tests.support import BenchCase, PROGRAM


class BootstrapTests(BenchCase):
    def test_n1_repeat_init_completes_defaults_and_preserves_history(self):
        bench = self.bench
        self.assertEqual(bench.configure()["assignments"], {"m1": "a", "m2": "b", "m3": "b"})
        bench.configure(assignments={"m2": "a"})
        recorded = bench.record(101, {"m1": 80, "m2": 10})
        frozen = bench.publish("opening", [101])
        before = bench.program_audio(frozen["edition"], 1)
        bench.install(frozen)
        bench.handover("b")
        heard = bench.listen("before-reopen", frozen["edition"])
        self.assertEqual(heard["sample"], 90)
        bench.configure(assignments={"m1": "b"})
        bench.stop_source()
        # Recreate the state of a source database whose third default was never supplied.
        with closing(sqlite3.connect(bench.source_db)) as db, db:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("DELETE FROM assignments WHERE program = ? AND microphone = 'm3'", (PROGRAM,))
            db.execute("DELETE FROM microphones WHERE program = ? AND microphone = 'm3'", (PROGRAM,))

        for _ in range(2):
            bench.restart_source()
            config = bench.configure()
            self.assertEqual(config["speakers"], {"a": "甲", "b": "乙"})
            self.assertEqual(config["assignments"], {"m1": "b", "m2": "a", "m3": "b"})
            self.assertEqual(bench.recorded(101), recorded)
            self.assertEqual(bench.program_audio(frozen["edition"], 1), before)
            self.assertEqual(bench.receipt("before-reopen"), heard)
        newest = bench.record(102, {"m1": 1, "m3": 3})
        self.assertEqual([item["speaker"] for item in newest["contributions"]], ["b", "b"])
