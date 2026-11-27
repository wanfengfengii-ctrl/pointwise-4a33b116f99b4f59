from dataclasses import dataclass

from rehearsal_contract import invalid, label, object_value, position


@dataclass(frozen=True)
class FrozenFrameOrigin:
    program: str
    source_frame: int
    recording_receipt: int


def build_origins(program, checked_frames):
    return {reference.frame: read_origin(recorded["origin"], program)
            for reference, recorded in checked_frames}


def read_origin(raw, program):
    value = object_value(raw, "origin")
    if label(value.get("program"), "origin.program") != program:
        raise invalid("origin.program")
    return FrozenFrameOrigin(
        program, position(value.get("source_frame"), "origin.source_frame"),
        position(value.get("recording_receipt"), "origin.recording_receipt"),
    )
