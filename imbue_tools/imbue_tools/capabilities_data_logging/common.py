import abc
import datetime
import subprocess
from enum import StrEnum
from pathlib import Path
from typing import Any
from typing import Iterable

from loguru import logger
from psycopg.sql import SQL

from imbue_core.pydantic_serialization import SerializableModel

IMBUE_AUTOMATIC_TESTING_ORGANIZATION_ID = "imbue-automatic-testing"
NEON_PROJECT_ID = (
    "holy-butterfly-05886102"  # This is the ID of the crafty project in neon.tech. TODO: reuse this for now
)


# TODO: this should be shared with `sculptor` but there's not a great shared module right now.
# Make sure if this is updated the value in `sculptor` also gets updated
# Path where imbue verify will log data and logged data will be expected to be found
CAPABILITIES_DATA_LOGGING_PATH = Path("/tmp/sculptor/capabilities_logging")


class ProductDataBaseEventRecord(SerializableModel, abc.ABC):
    """
    This is a base class for all product data events.
    It contains the fields that are common to all product data events.
    """

    id: str
    user_id: str
    organization_id: str
    created_at: datetime.datetime


class SculptorDataTables(StrEnum):
    PRODUCT_TOOL_DATA = "PRODUCT_TOOL_DATA"


def build_product_feature_data_query_args(
    user_id: str | None = None,
    creation_bounds: tuple[datetime.datetime | None, datetime.datetime | None] = (None, None),
    ids: Iterable[str] | None = None,
    filter_test_users: bool = False,
) -> tuple[Any, tuple[Any, ...]]:
    where_clause: Any = SQL("1 = 1")
    where_args: tuple[Any, ...] = ()
    start, end = creation_bounds
    if start is not None:
        where_clause = SQL("{} AND {}").format(where_clause, SQL("created_at >= %s"))
        where_args += (start,)
    if end is not None:
        where_clause = SQL("{} AND {}").format(where_clause, SQL("created_at <= %s"))
        where_args += (end,)
    if user_id is not None:
        where_clause = SQL("{} AND {}").format(where_clause, SQL("user_id = %s"))
        where_args += (user_id,)
    if ids is not None:
        where_clause = SQL("{} AND {}").format(where_clause, SQL("id = ANY(%s)"))
        where_args += (ids,)
    if filter_test_users:
        where_clause = SQL("{} AND NOT {}").format(where_clause, SQL("organization_id = %s"))
        where_args += (IMBUE_AUTOMATIC_TESTING_ORGANIZATION_ID,)
    return where_clause, where_args


UNKNOWN_USER_NAME = "unknown"


def get_current_user_name() -> str:
    try:
        possible_username = subprocess.check_output(["git", "config", "user.name"], universal_newlines=True).strip()
        assert possible_username != ""
        return possible_username
    except subprocess.CalledProcessError:
        pass
    logger.info("Using UNKNOWN_USER_NAME")
    return UNKNOWN_USER_NAME
