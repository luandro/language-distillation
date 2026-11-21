import logging
from collections.abc import Iterator

import pytest

from langpipe.logging import (
    LOGGER_NAME,
    UnsafeLogValue,
    configure_logging,
    log_event,
)

SOURCE_ID = "src_01ARZ3NDEKTSV4RRFFQ69G5FAV"
RUN_ID = "run_01BX5ZZKBKACTAV9WEVGEMMVRZ"
SHA256 = "a" * 64


@pytest.fixture
def logger() -> Iterator[logging.Logger]:
    target = logging.getLogger(LOGGER_NAME)
    saved_level = target.level
    saved_handlers = list(target.handlers)
    yield target
    target.setLevel(saved_level)
    target.handlers[:] = saved_handlers


def test_log_event_formats_sorted_fields(
    logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        log_event(logger, "source.registered", source_id=SOURCE_ID, objects=3, reused=False)
    assert caplog.messages == [
        f"event=source.registered objects=3 reused=false source_id={SOURCE_ID}"
    ]


def test_log_event_rejects_free_text(logger: logging.Logger) -> None:
    with pytest.raises(UnsafeLogValue):
        log_event(logger, "source.registered", source_id="o homem vê")


def test_log_event_rejects_uppercase_sentinel(logger: logging.Logger) -> None:
    with pytest.raises(UnsafeLogValue):
        log_event(logger, "source.registered", source_id="SRC_01ARZ3NDEKTSV4RRFFQ69G5FAV")


def test_log_event_rejects_lowercase_word_filename_and_unknown_key(logger: logging.Logger) -> None:
    with pytest.raises(UnsafeLogValue):
        log_event(logger, "run.finished", status="hello")
    with pytest.raises(UnsafeLogValue):
        log_event(logger, "source.registered", source_id="notes.txt")
    with pytest.raises(UnsafeLogValue):
        log_event(logger, "source.registered", title="Relatório final")
    with pytest.raises(UnsafeLogValue):
        log_event(logger, "Bad Event")


def test_log_event_rejects_wrong_id_prefix(logger: logging.Logger) -> None:
    with pytest.raises(UnsafeLogValue):
        log_event(logger, "source.registered", source_id=RUN_ID)


def test_log_event_rejects_bad_count_and_bool_types(logger: logging.Logger) -> None:
    with pytest.raises(UnsafeLogValue):
        log_event(logger, "source.ingested", objects=-1)
    with pytest.raises(UnsafeLogValue):
        log_event(logger, "source.ingested", objects="3")
    with pytest.raises(UnsafeLogValue):
        log_event(logger, "source.ingested", objects=True)
    with pytest.raises(UnsafeLogValue):
        log_event(logger, "source.ingested", reused=1)


def test_log_event_accepts_ids_and_hashes(
    logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        log_event(
            logger,
            "ingest.completed",
            source_id=SOURCE_ID,
            source_object_id="sobj_01ARZ3NDEKTSV4RRFFQ69G5FAV",
            run_id=RUN_ID,
            artifact_id="artifact_01ARZ3NDEKTSV4RRFFQ69G5FAV",
            policy_id="pol_01ARZ3NDEKTSV4RRFFQ69G5FAV",
            sha256=SHA256,
            operation="ingest",
            decision="allow",
            mode="direct",
            status="succeeded",
            blobs=2,
            count=0,
        )
    assert len(caplog.messages) == 1
    assert caplog.messages[0].startswith("event=ingest.completed ")


def test_log_event_accepts_source_and_run_statuses(logger: logging.Logger) -> None:
    log_event(logger, "source.status", status="registered")
    log_event(logger, "source.status", status="revoked")
    log_event(logger, "run.status", status="running")


def test_log_event_rejects_non_hex_hash(logger: logging.Logger) -> None:
    with pytest.raises(UnsafeLogValue):
        log_event(logger, "object.stored", sha256="A" * 64)
    with pytest.raises(UnsafeLogValue):
        log_event(logger, "object.stored", sha256=SOURCE_ID)


def test_configure_logging_idempotent(logger: logging.Logger) -> None:
    configure_logging("DEBUG")
    handler_count = len(logger.handlers)
    configure_logging("DEBUG")
    configure_logging("WARNING")
    assert len(logger.handlers) == handler_count
    assert logger.level == logging.WARNING
