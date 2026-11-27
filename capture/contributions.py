from dataclasses import dataclass

from rehearsal_contract import invalid, label, object_value
from studio.assignments import resolve_assignments


SCHEMA = """
CREATE TABLE IF NOT EXISTS contributions (
    program TEXT NOT NULL,
    source_frame INTEGER NOT NULL,
    microphone TEXT NOT NULL,
    speaker TEXT NOT NULL,
    sample TEXT NOT NULL,
    PRIMARY KEY (program, source_frame, microphone),
    FOREIGN KEY (program, source_frame) REFERENCES recorded_frames(program, source_frame),
    FOREIGN KEY (program, microphone) REFERENCES microphones(program, microphone),
    FOREIGN KEY (program, speaker) REFERENCES speakers(program, speaker)
);
"""


@dataclass(frozen=True)
class Contribution:
    microphone: str
    speaker: str
    sample: int


def bind_contributions(db, frame, samples):
    samples = object_value(samples, "contributions")
    for microphone, sample in samples.items():
        label(microphone, "microphone")
        if type(sample) is not int:
            raise invalid(f"contributions.{microphone}")
    microphones = sorted(samples)
    assignments = resolve_assignments(db, frame.program, microphones)
    return tuple(
        Contribution(microphone, assignments[microphone].speaker, samples[microphone])
        for microphone in microphones
    )


def insert_contributions(db, frame, contributions):
    db.executemany(
        "INSERT INTO contributions VALUES (?, ?, ?, ?, ?)",
        [(frame.program, frame.source_frame, item.microphone, item.speaker, str(item.sample))
         for item in contributions],
    )


def read_contributions(db, frame):
    rows = db.execute(
        """SELECT microphone, speaker, sample FROM contributions
           WHERE program = ? AND source_frame = ? ORDER BY microphone""",
        (frame.program, frame.source_frame),
    )
    return tuple(Contribution(row["microphone"], row["speaker"], int(row["sample"])) for row in rows)
