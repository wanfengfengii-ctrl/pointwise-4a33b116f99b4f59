from dataclasses import dataclass

from studio.programs import get_program


SCHEMA = """
CREATE TABLE IF NOT EXISTS microphones (
    program TEXT NOT NULL REFERENCES programs(program),
    microphone TEXT NOT NULL,
    PRIMARY KEY (program, microphone)
);
"""


@dataclass(frozen=True)
class Microphone:
    program: str
    microphone: str


def register_microphone(db, program, microphone):
    get_program(db, program)
    db.execute(
        "INSERT INTO microphones VALUES (?, ?) ON CONFLICT (program, microphone) DO NOTHING",
        (program, microphone),
    )
    return Microphone(program, microphone)


def get_microphone(db, program, microphone):
    row = db.execute(
        "SELECT program, microphone FROM microphones WHERE program = ? AND microphone = ?",
        (program, microphone),
    ).fetchone()
    return None if row is None else Microphone(**dict(row))
