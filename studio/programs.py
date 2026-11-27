from dataclasses import dataclass

from rehearsal_contract import Problem


SCHEMA = """
CREATE TABLE IF NOT EXISTS programs (
    program TEXT PRIMARY KEY,
    title TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Program:
    program: str
    title: str


def register_program(db, program, title):
    db.execute(
        "INSERT INTO programs (program, title) VALUES (?, ?) ON CONFLICT (program) DO NOTHING",
        (program, title),
    )
    return get_program(db, program)


def get_program(db, program):
    row = db.execute("SELECT program, title FROM programs WHERE program = ?", (program,)).fetchone()
    if row is None:
        raise Problem(404, "program_unavailable", program=program)
    return Program(**dict(row))
