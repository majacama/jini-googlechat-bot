import json
import logging

from app.core.logging_config import JsonFormatter


def test_json_formatter_includes_extra_fields() -> None:
    formatter = JsonFormatter()
    logger = logging.getLogger("test.rag")
    record = logger.makeRecord(
        name="test.rag",
        level=logging.WARNING,
        fn="rag.py",
        lno=1,
        msg="rag_search_failed",
        args=(),
        exc_info=None,
        extra={"status": 403, "body": "permission denied"},
    )
    data = json.loads(formatter.format(record))
    assert data["message"] == "rag_search_failed"
    assert data["severity"] == "WARNING"
    assert data["status"] == 403
    assert data["body"] == "permission denied"


def test_json_formatter_includes_exception_traceback() -> None:
    formatter = JsonFormatter()
    logger = logging.getLogger("test.rag")
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logger.makeRecord(
            name="test.rag",
            level=logging.ERROR,
            fn="rag.py",
            lno=1,
            msg="rag_search_crashed",
            args=(),
            exc_info=sys.exc_info(),
        )
    data = json.loads(formatter.format(record))
    assert "ValueError: boom" in data["exception"]
