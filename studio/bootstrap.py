from studio.assignments import seed_missing_assignments
from studio.microphones import register_microphone
from studio.programs import register_program
from studio.roster import get_speaker, register_speaker


DEFAULT_PROGRAM = "rehearsal"
DEFAULT_SPEAKERS = {"a": "甲", "b": "乙"}
DEFAULT_ASSIGNMENTS = {"m1": "a", "m2": "b", "m3": "b"}


def initialize_demo(db):
    with db:
        db.execute("BEGIN IMMEDIATE")
        show = register_program(db, DEFAULT_PROGRAM, "榆桥社区广播剧联排")
        for speaker, name in DEFAULT_SPEAKERS.items():
            if get_speaker(db, show.program, speaker) is None:
                register_speaker(db, show.program, speaker, name)
        for microphone in DEFAULT_ASSIGNMENTS:
            register_microphone(db, show.program, microphone)
        seed_missing_assignments(db, show.program, DEFAULT_ASSIGNMENTS)
