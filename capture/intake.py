from dataclasses import asdict

from capture.contributions import bind_contributions, insert_contributions, read_contributions
from capture.frames import RecordedFrame, insert_frame, read_frame
from capture.receipts import read_recording_receipt, write_recording_receipt
from rehearsal_contract import Problem, label, position
from studio.programs import get_program


def _recorded_payload(receipt, contributions):
    return {
        "origin": asdict(receipt),
        "contributions": [asdict(item) for item in contributions],
    }


def record_frame(db, data):
    program = label(data.get("program"), "program")
    source_frame = position(data.get("source_frame"), "source_frame")
    get_program(db, program)
    if read_frame(db, program, source_frame) is not None:
        raise Problem(409, "source_frame_exists", source_frame=source_frame)

    frame = RecordedFrame(program, source_frame)
    contributions = bind_contributions(db, frame, data.get("contributions"))
    insert_frame(db, frame)
    insert_contributions(db, frame, contributions)
    receipt = write_recording_receipt(db, frame)
    return _recorded_payload(receipt, contributions)


def read_recorded_frame(db, program, source_frame):
    frame = read_frame(db, program, source_frame)
    if frame is None:
        return None
    return _recorded_payload(read_recording_receipt(db, frame), read_contributions(db, frame))
