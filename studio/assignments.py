from dataclasses import dataclass

from rehearsal_contract import Problem, label, object_value
from studio.microphones import get_microphone
from studio.programs import get_program
from studio.roster import get_speaker, list_members, register_speaker


SCHEMA = """
CREATE TABLE IF NOT EXISTS assignments (
    program TEXT NOT NULL,
    microphone TEXT NOT NULL,
    speaker TEXT NOT NULL,
    PRIMARY KEY (program, microphone),
    FOREIGN KEY (program, microphone) REFERENCES microphones(program, microphone),
    FOREIGN KEY (program, speaker) REFERENCES speakers(program, speaker)
);
"""


@dataclass(frozen=True)
class Assignment:
    program: str
    microphone: str
    speaker: str


def configure(db, program, speakers, assignments):
    show = get_program(db, program)
    speakers = object_value(speakers, "speakers")
    assignments = object_value(assignments, "assignments")
    for speaker, name in speakers.items():
        register_speaker(db, program, speaker, name)

    changes = []
    for microphone, speaker in assignments.items():
        microphone = label(microphone, "microphone")
        speaker = label(speaker, "speaker")
        if get_microphone(db, program, microphone) is None:
            raise Problem(400, "unknown_microphone", microphone=microphone)
        if get_speaker(db, program, speaker) is None:
            raise Problem(400, "unknown_speaker", speaker=speaker)
        changes.append((program, microphone, speaker))

    db.executemany(
        """INSERT INTO assignments VALUES (?, ?, ?)
           ON CONFLICT (program, microphone) DO UPDATE SET speaker = excluded.speaker""",
        changes,
    )
    current = db.execute(
        "SELECT microphone, speaker FROM assignments WHERE program = ? ORDER BY microphone", (program,)
    )
    return {
        "program": show.program,
        "title": show.title,
        "speakers": {member.speaker: member.name for member in list_members(db, program)},
        "assignments": {row["microphone"]: row["speaker"] for row in current},
    }


def resolve_assignments(db, program, microphones):
    resolved = {}
    for microphone in microphones:
        row = db.execute(
            "SELECT program, microphone, speaker FROM assignments WHERE program = ? AND microphone = ?",
            (program, microphone),
        ).fetchone()
        if row is None:
            raise Problem(400, "unassigned_microphone", microphone=microphone)
        resolved[microphone] = Assignment(**dict(row))
    return resolved


def seed_missing_assignments(db, program, defaults):
    db.executemany(
        "INSERT INTO assignments VALUES (?, ?, ?) ON CONFLICT (program, microphone) DO NOTHING",
        [(program, microphone, speaker) for microphone, speaker in defaults.items()],
    )
