"""Preview or apply a lossless Redis odds format migration using runtime settings."""

import argparse
import json

from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.storage import create_repository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("response", "legacy"), required=True)
    parser.add_argument("--apply", action="store_true", help="Write changes; otherwise report a dry run")
    arguments = parser.parse_args()
    settings = Settings()
    if settings.storage_backend != "redis":
        parser.error("This migration requires STORAGE_BACKEND=redis")
    repository = create_repository(settings)
    try:
        print(json.dumps(repository.rewrite_event_documents(arguments.format, dry_run=not arguments.apply)))
    finally:
        repository.close()


if __name__ == "__main__":
    main()
