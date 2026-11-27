from contextlib import closing

from capture import contributions, frames, intake, receipts
from mix import revisions, sequence
from rehearsal_contract import Problem, label, query_position
from rehearsal_http import JsonHandler, LocalService, connect, create_schema, run_service
from release import edition, freeze, program_audio
from studio import assignments, microphones, programs, roster
from studio.bootstrap import initialize_demo


def _configure(db, data):
    return assignments.configure(db, label(data.get("program"), "program"),
                                 data.get("speakers", {}), data.get("assignments", {}))


def _recorded(db, data):
    program = label(data.get("program"), "program")
    source_frame = query_position(data, "source_frame")
    programs.get_program(db, program)
    recorded = intake.read_recorded_frame(db, program, source_frame)
    if recorded is None:
        raise Problem(404, "source_frame_unavailable", source_frame=source_frame)
    return recorded


def _program_audio(db, data):
    return program_audio.program_audio(db, query_position(data, "edition"), query_position(data, "frame"))


class SourceRequestHandler(JsonHandler):
    operations = {
        ("POST", "/configure"): _configure,
        ("POST", "/record_frame"): intake.record_frame,
        ("GET", "/record_frame"): _recorded,
        ("POST", "/preview"): revisions.preview,
        ("POST", "/freeze"): freeze.freeze,
        ("GET", "/program_audio"): _program_audio,
    }


def serve_source(database, port=0, handler_class=SourceRequestHandler):
    with closing(connect(database)) as db:
        create_schema(db, programs.SCHEMA, roster.SCHEMA, microphones.SCHEMA, assignments.SCHEMA,
                      frames.SCHEMA, contributions.SCHEMA, receipts.SCHEMA,
                      revisions.SCHEMA, sequence.SCHEMA, edition.SCHEMA)
        initialize_demo(db)
    return LocalService(database, port, handler_class)


def main():
    run_service(serve_source, "榆桥联排录音与发行服务", 8001)


if __name__ == "__main__":
    main()
