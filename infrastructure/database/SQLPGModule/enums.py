import uuid
import datetime
from enum import Enum
from decimal import Decimal
from typing import Dict, Union, Tuple, Type, Any


class DBType(str, Enum):
    # Numeric
    SMALLINT = "SMALLINT"
    INTEGER = "INTEGER"
    BIGINT = "BIGINT"
    DECIMAL = "DECIMAL"
    NUMERIC = "NUMERIC"
    REAL = "REAL"
    DOUBLE_PRECISION = "DOUBLE PRECISION"
    SERIAL = "SERIAL"
    BIGSERIAL = "BIGSERIAL"
    SMALLSERIAL = "SMALLSERIAL"

    # Symbolic
    CHAR = "CHAR"
    VARCHAR = "VARCHAR"
    TEXT = "TEXT"

    # Logic
    BOOLEAN = "BOOLEAN"

    # Date & Time
    DATE = "DATE"
    TIME = "TIME"
    TIMESTAMP = "TIMESTAMP"
    TIMESTAMPTZ = "TIMESTAMPTZ"  # timestamp with time zone
    INTERVAL = "INTERVAL"

    # Money money
    MONEY = "MONEY"

    # UUID
    UUID = "UUID"

    # JSON
    JSON = "JSON"
    JSONB = "JSONB"

    # Networks
    INET = "INET"
    CIDR = "CIDR"
    MACADDR = "MACADDR"

    # Arrays
    INTEGER_ARRAY = "INTEGER[]"
    TEXT_ARRAY = "TEXT[]"
    BOOLEAN_ARRAY = "BOOLEAN[]"
    UUID_ARRAY = "UUID[]"

    # Special
    BYTEA = "BYTEA"
    XML = "XML"
    TSVECTOR = "TSVECTOR"
    TSQUERY = "TSQUERY"


class Status(Enum):
    EMPTY = 'EMPTY'
    ENABLE = 'ENABLE'

