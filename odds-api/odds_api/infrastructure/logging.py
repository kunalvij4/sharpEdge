import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record):
        # Allowlist fields; never serialize exception text, headers, bodies or URLs.
        result = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        for name in (
            "league",
            "market",
            "run",
            "duration",
            "outcome",
            "selections",
            "warnings",
            "error_type",
            "provider_path",
            "provider_http_status",
            "failure_reason",
            "job",
            "state",
            "last_attempt",
            "last_success",
            "counts",
            "duration_seconds",
            "process_name",
            "exit_code",
        ):
            if hasattr(record, name):
                result[name] = getattr(record, name)
        return json.dumps(result)


def configure_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
