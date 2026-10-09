"""Turn an exception from a background run into a message that is safe to show users.

Database errors carry the SQL statement and row values; those go to the logs (and Sentry),
never into `run.error`, which the API returns to the browser.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import SQLAlchemyError

log = logging.getLogger(__name__)

GENERIC = "The run failed because of an internal error. The team has been alerted; try again."


def run_error(exc: BaseException) -> str:
    if isinstance(exc, SQLAlchemyError):
        log.error("background run failed with a database error", exc_info=exc)
        return GENERIC
    return str(exc)[:2000] or GENERIC
