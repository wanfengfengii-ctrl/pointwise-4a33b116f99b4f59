from dataclasses import dataclass


SCHEMA = """
CREATE TABLE IF NOT EXISTS recording_receipts (
    recording_receipt INTEGER PRIMARY KEY,
    program TEXT NOT NULL,
    source_frame INTEGER NOT NULL,
    UNIQUE (program, source_frame),
    FOREIGN KEY (program, source_frame) REFERENCES recorded_frames(program, source_frame)
);
"""


@dataclass(frozen=True)
class RecordingReceipt:
    program: str
    source_frame: int
    recording_receipt: int


def write_recording_receipt(db, frame):
    cursor = db.execute("INSERT INTO recording_receipts (program, source_frame) VALUES (?, ?)",
                        (frame.program, frame.source_frame))
    return RecordingReceipt(frame.program, frame.source_frame, cursor.lastrowid)


def read_recording_receipt(db, frame):
    row = db.execute(
        """SELECT program, source_frame, recording_receipt FROM recording_receipts
           WHERE program = ? AND source_frame = ?""",
        (frame.program, frame.source_frame),
    ).fetchone()
    if row is None:
        raise RuntimeError("recorded frame has no recording receipt")
    return RecordingReceipt(**dict(row))
