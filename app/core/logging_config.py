"""Logs structures pour Cloud Run.

logging.basicConfig() par defaut n'affiche jamais les champs extra={...}
passes aux appels logger.*() - ils sont silencieusement absents du texte
formate. Ce module emet du JSON sur stdout/stderr a la place : Cloud Run
detecte automatiquement les lignes JSON et les promeut en jsonPayload
structure (avec severity correctement mappee), ce qui rend enfin ces champs
consultables et filtrables dans Cloud Logging.
"""

import json
import logging

_RESERVED_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
