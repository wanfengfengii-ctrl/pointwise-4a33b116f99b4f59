from dataclasses import dataclass

from rehearsal_contract import Problem, label
from studio.programs import get_program


SCHEMA = """
CREATE TABLE IF NOT EXISTS speakers (
    program TEXT NOT NULL REFERENCES programs(program),
    speaker TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (program, speaker)
);
"""


@dataclass(frozen=True)
class Speaker:
    program: str
    speaker: str
    name: str


def register_speaker(db, program, speaker, name):
    get_program(db, program)
    speaker = label(speaker, "speaker")
    name = label(name, "name")
    db.execute(
        "INSERT INTO speakers VALUES (?, ?, ?) ON CONFLICT (program, speaker) DO NOTHING",
        (program, speaker, name),
    )
    member = get_speaker(db, program, speaker)
    if member.name != name:
        raise Problem(409, "speaker_already_registered", speaker=speaker)
    return member


def get_speaker(db, program, speaker):
    row = db.execute(
        "SELECT program, speaker, name FROM speakers WHERE program = ? AND speaker = ?",
        (program, speaker),
    ).fetchone()
    return None if row is None else Speaker(**dict(row))


def list_members(db, program):
    rows = db.execute(
        "SELECT program, speaker, name FROM speakers WHERE program = ? ORDER BY speaker", (program,)
    )
    return tuple(Speaker(**dict(row)) for row in rows)
