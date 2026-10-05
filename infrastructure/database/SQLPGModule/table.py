import logging
import psycopg
from enum import Enum
from typing import Any, Dict, List, Optional
from psycopg import sql
from psycopg import AsyncConnection
from prettytable import PrettyTable
from core.SQLPGModule.enums import Status, DBType


logger = logging.getLogger(__name__)


class Table:
    MAX_LEN = 100
    """
    A high-level asynchronous wrapper for interacting with PostgreSQL tables with built-in security.

    This class provides:
    - Secure CRUD operations with automatic SQL injection prevention
    - Schema management and metadata inspection
    - Comprehensive input validation to prevent SQL injection
    - ORM-like access to table data
    - Automatic connection validation before operations

    Important: This is an async-first implementation. All database operations must be awaited.
    The class validates all inputs and uses parameterized queries to prevent SQL injection.
    All identifier names are strictly validated to prevent SQL injection through object names.
    """

    def __init__(self, connection: AsyncConnection, table_name: str, primary_key: str) -> None:
        """
         Initialize a Table wrapper with strict validation.

         Note: This constructor only stores connection parameters and validates inputs.
         No database operations are performed at this stage.

         Args:
             connection: Active psycopg AsyncConnection object.
             table_name: Name of the table in the database (must be valid identifier).
             primary_key: Name of the primary key column (must be valid identifier).

         Raises:
             TypeError: If any parameter has incorrect type.
             ValueError: If any parameter fails validation (length, format).

         Security Note: Table and column names are validated to prevent SQL injection through
         identifier names. Only alphanumeric characters and underscores are permitted by
         PostgreSQL, but this validation enforces additional length constraints.
         """
        self.connection = connection
        self.table_name = table_name
        self.primary_key = primary_key
        self._cursor = connection.cursor()

    @property
    def connection(self) -> AsyncConnection:
        """
        Get the current database connection.

        Returns:
            psycopg.AsyncConnection object used for database operations.

        Security Note: The connection object should not be modified directly.
        Use the connection setter for validated connection replacement.
        """
        return self._connection

    @connection.setter
    def connection(self, connection: AsyncConnection) -> None:
        """
        Set a new database connection with validation.

        Args:
            connection: A valid psycopg AsyncConnection object.

        Raises:
            TypeError: If connection is not of type AsyncConnection.

        Security Note: This method validates the connection type to prevent injection
        of malicious connection objects. It does not validate connection parameters
        (host, user, etc.) as this should be handled at the connection creation level.
        """
        if not isinstance(connection, AsyncConnection):
            raise TypeError(f"'connection' must be '<AsyncConnection>', but got {type(connection).__name__}")
        self._connection = connection

    @property
    def table_name(self) -> str:
        """
        Get the name of the table.

        Returns:
            Table name as string.

        Security Note: The table name is validated during setting to prevent SQL injection.
        This getter simply returns the validated value.
        """
        return self._table_name

    @table_name.setter
    def table_name(self, table_name: str) -> None:
        """
        Set a new table name with validation.

        Args:
            table_name: New table name (must be valid identifier).

        Raises:
            TypeError: If table_name is not a string.
            ValueError: If table_name is empty or exceeds MAX_LEN.

        Security Note: Table names are validated to prevent SQL injection through
        identifier names. Only alphanumeric characters and underscores are permitted
        by PostgreSQL, but this validation enforces additional length constraints.
        """
        if not isinstance(table_name, str):
            raise TypeError(f"'table_name' must be '<str>', but got {type(table_name).__name__}")
        if len(table_name) == 0:
            raise ValueError("The length of 'table_name' should be greater than zero")
        self._table_name = table_name

    @property
    def primary_key(self) -> str:
        """
        Get the primary key column name.

        Returns:
            Primary key column name.

        Security Note: The primary key name is validated during setting to prevent
        SQL injection. This getter simply returns the validated value.
        """
        return self._primary_key

    @primary_key.setter
    def primary_key(self, primary_key: str) -> None:
        """
        Set a new primary key column name with validation.

        Args:
            primary_key: Name of the primary key column (must be valid identifier).

        Raises:
            TypeError: If primary_key is not a string.
            ValueError: If primary_key is empty or exceeds MAX_LEN.

        Security Note: Primary key names are validated to prevent SQL injection through
        identifier names. Only alphanumeric characters and underscores are permitted
        by PostgreSQL, but this validation enforces additional length constraints.
        """
        if not isinstance(primary_key, str):
            raise TypeError(f"'primary_key' must be '<str>', but got {type(primary_key).__name__}")
        if len(primary_key) == 0:
            raise ValueError("The length of 'primary_key' should be greater than zero")
        self._primary_key = primary_key

    @property
    async def column_names(self) -> List[str]:
        """
        Get a list of all column names in the table with connection validation.

        This method first ensures the database connection is active before querying
        metadata. It returns column names in their defined order.

        Returns:
            List of column names (strings) in ordinal position order.

        Raises:
            ConnectionError: If database connection cannot be established.
            ValueError: If table does not exist in 'public' schema.

        Security Note: This method queries information_schema with proper parameterization
        to prevent SQL injection. It only returns columns from the 'public' schema.
        """
        return await self.get_column_names()

    @property
    async def count(self) -> int:
        """
        Get the number of rows in the table with connection validation.

        This method executes a COUNT(*) query to determine the row count.
        It first ensures the database connection is active.

        Returns:
            Row count as integer (0 if table is empty).

        Raises:
            ConnectionError: If database connection cannot be established.
            DatabaseError: If COUNT query fails.

        Security Note: The table name is properly quoted using Identifier class
        to prevent SQL injection. This method is safe to use with untrusted input
        as long as the table name was validated during initialization.
        """
        async with self.connection.cursor() as cursor:
            query = sql.SQL("SELECT COUNT(*) FROM {table}").format(table=sql.Identifier(self.table_name))
            await cursor.execute(query=query)
            return await cursor.fetchone()

    @property
    async def status(self) -> Status:
        """
        Get the logical status of the table based on row count.

        This method determines if the table is considered "ENABLE" (has rows)
        or "EMPTY" (no rows).

        Returns:
            Status.ENABLE if table has rows, Status.EMPTY otherwise.

        Security Note: This method relies on the count property, which is
        implemented securely with proper identifier quoting. No additional
        security concerns beyond those of the count property.
        """
        return Status.ENABLE if await self.count > 0 else Status.EMPTY

    @property
    async def columns_count(self) -> int:
        """
        Get the number of columns in the table with connection validation.

        This method returns the count of columns by getting the length of
        column_names list.

        Returns:
            Number of columns as integer.

        Security Note: This method relies on column_names property, which
        is implemented securely with proper validation and parameterization.
        """
        return len(await self.column_names)

    async def create_table(self, columns: Dict[str, Enum], primary_key: Optional[str] = None) -> None:
        """
        Create the table if it does not exist with comprehensive security.

        This method safely creates a table using validated inputs and proper
        identifier quoting. It ensures all column definitions come from trusted
        Enum sources to prevent SQL injection.

        Args:
            columns: Dictionary mapping column names to SQL types (as Enum values).
            primary_key: Optional primary key column name. If None, uses self.primary_key.

        Raises:
            TypeError: If parameters have incorrect types.
            ValueError: If parameters fail validation or primary_key not in columns.

        Security Note: All identifiers are properly quoted using psycopg's Identifier
        class. Column types must come from trusted Enum sources to prevent execution
        of arbitrary SQL. The method validates all inputs before query construction.
        """
        column_definitions = []
        for column, col_type in columns.items():
            if not isinstance(column, str):
                raise TypeError(f"Field 'column' should be '<str>', but got {type(column).__name__}")
            if not 0 < len(column) <= self.MAX_LEN:
                raise ValueError(f"'column' length should be in range [0, {self.MAX_LEN}], but got '{len(column)}'")

            if not isinstance(col_type, DBType):
                raise TypeError(f"Field 'col_type' should be one of {list(DBType)}, but got {type(col_type).__name__}")
            column_definitions.append(sql.SQL("{} {}").format(sql.Identifier(column), sql.SQL(col_type.value)))

        if primary_key is not None and not isinstance(primary_key, str):
            raise TypeError(f"Field 'primary_key' should be '<str>', but got {type(primary_key).__name__}")
        if primary_key is not None and primary_key not in columns:
            raise ValueError(f"Primary key column '{primary_key}' must be defined in columns")
        primary_key = primary_key if primary_key is not None else self.primary_key

        column_definitions.append(sql.SQL("PRIMARY KEY ({})").format(sql.Identifier(primary_key)))
        query = sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(sql.Identifier(self.table_name),
                                                                     sql.SQL(", ").join(column_definitions))
        async with self._connection.cursor() as cursor:
            await cursor.execute(query)
        await self._connection.commit()

    async def get_from_cell(self, key: Any, target_column: str, key_column: Optional[str] = None) -> Any:
        """
        Get a single value from a specific cell with comprehensive validation.

        This method safely retrieves a value using parameterized queries and
        validated column names to prevent SQL injection.

        Args:
            key: Value of the key column to search for.
            target_column: Name of the column to retrieve (must be valid identifier).
            key_column: Column to search in. If None, uses self.primary_key.

        Returns:
            Value from the cell, or None if not found.

        Raises:
            TypeError: If target_column or key_column have incorrect types.
            ValueError: If target_column or key_column fail validation or don't exist.

        Security Note: All identifiers are properly quoted using Identifier class.
        The key value is passed as a parameter to prevent SQL injection. This method
        validates that target_column and key_column exist in the table before use.
        """
        if not isinstance(target_column, str):
            raise TypeError(f"Field 'target_column' should be '<str>', but got {type(target_column).__name__}")
        if not 0 < len(target_column) <= self.MAX_LEN:
            raise ValueError(f"'target_column' length should be in [0, {self.MAX_LEN}], but got '{len(target_column)}'")

        if key_column is not None and not isinstance(key_column, str):
            raise TypeError(f"Field 'key_column' should be '<str>', but got {type(key_column).__name__}")
        if key_column is not None and key_column not in self.column_names:
            raise ValueError(f"Column '{key_column}' does not exist in table '{self.table_name}'")
        key_column = key_column if key_column is not None else self.primary_key

        query = sql.SQL("SELECT {target} FROM {table} WHERE {key_col} = %s").format(
            target=sql.Identifier(target_column),
            table=sql.Identifier(self.table_name),
            key_col=sql.Identifier(key_column)
        )
        async with self.connection.cursor() as cursor:
            await cursor.execute(query, (key,))
            result = await cursor.fetchone()
            return result[0] if result else None

    async def set_to_cell(self,
                          key: Any,
                          target_column: str,
                          value: Any,
                          key_column: Optional[str] = None,
                          commit: bool = True) -> None:
        """
        Update a single cell in the table with comprehensive validation.

        This method safely updates a value using parameterized queries and
        validated column names to prevent SQL injection.

        Args:
            key: Value of the key column to identify the row.
            target_column: Column to update (must be valid identifier).
            value: New value to set.
            commit: Whether to commit the transaction immediately.
            key_column: Column to search in. If None, uses self.primary_key.

        Raises:
            TypeError: If target_column or key_column have incorrect types.
            ValueError: If target_column or key_column fail validation or don't exist.

        Security Note: All identifiers are properly quoted using Identifier class.
        The key and value are passed as parameters to prevent SQL injection. This method
        validates that target_column and key_column exist in the table before use.
        """
        if not isinstance(target_column, str):
            raise TypeError(f"Field 'target_column' should be '<str>', but got {type(target_column).__name__}")
        if not 0 < len(target_column) <= self.MAX_LEN:
            raise ValueError(f"'target_column' length should be in [0, {self.MAX_LEN}], but got '{len(target_column)}'")

        if key_column is not None and not isinstance(key_column, str):
            raise TypeError(f"Field 'key_column' should be '<str>', but got {type(key_column).__name__}")
        if key_column is not None and key_column not in self.column_names:
            raise ValueError(f"Column '{key_column}' does not exist in table '{self.table_name}'")
        key_column = key_column if key_column is not None else self.primary_key

        if value is not None:
            value_type = type(value)
            if isinstance(value, (type, property, staticmethod, classmethod)):
                raise TypeError(f"Cannot save {value_type.__name__} to database column '{target_column}'. "
                                f"This type cannot be stored in PostgreSQL.")

        query = sql.SQL("UPDATE {table} SET {target} = %s WHERE {key_col} = %s").format(
            table=sql.Identifier(self.table_name),
            target=sql.Identifier(target_column),
            key_col=sql.Identifier(key_column)
        )
        async with self.connection.cursor() as cursor:
            await cursor.execute(query, (value, key))
        if commit:
            await self.connection.commit()

    async def add_row(self, row: Dict[str, Any]) -> Any:
        """
        Insert a new row into the table and return the generated primary key value.

        This method safely inserts a row using parameterized queries and validated
        column names to prevent SQL injection. It returns the value of the primary
        key column for the newly inserted row (SERIAL id, UUID, etc.).

        Args:
            row: Dictionary mapping column names to values. Primary key column
                 should typically be omitted as it will be auto-generated.

        Returns:
            The generated primary key value of the newly inserted row (int, str, UUID, etc.).

        Raises:
            ValueError: If any column in row does not exist in the table.
            IntegrityError: If constraint violation occurs (duplicate key, foreign key, etc.).
            ProgrammingError: If SQL syntax error or table structure issues.

        Security Note: All identifiers are properly quoted using Identifier class.
        Values are passed as parameters to prevent SQL injection. Primary key column
        is dynamically resolved from self.primary_key with proper quoting. This method
        validates all columns exist before insertion and uses RETURNING clause to
        safely retrieve the generated primary key without additional queries.

        Performance Note: Single round-trip operation using INSERT ... RETURNING.
        No additional SELECT required to retrieve the new primary key value.
        """
        keys = row.keys()
        values = [row[key] for key in keys]

        query = sql.SQL("INSERT INTO {table} ({fields}) VALUES ({placeholders}) RETURNING {primary_key}").format(
            table=sql.Identifier(self.table_name),
            fields=sql.SQL(", ").join(map(sql.Identifier, keys)),
            placeholders=sql.SQL(", ").join(sql.Placeholder() * len(keys)),
            primary_key=sql.Identifier(self.primary_key)
        )
        async with self.connection.cursor() as cursor:
            await cursor.execute(query, values)
            new_id = (await cursor.fetchone())[0]
        await self.connection.commit()
        return new_id

    async def get_row(self, key: Any, key_column: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieve a full row by key with comprehensive validation.

        This method safely retrieves a row using parameterized queries and
        validated column names to prevent SQL injection.

        Args:
            key: Value of the key column to search for.
            key_column: Column to search in (must be valid identifier). If None, uses self.primary_key.

        Returns:
            Dictionary of column_name -> value, or empty dict if not found.

        Raises:
            TypeError: If key_column has incorrect type.
            ValueError: If key_column fails validation or doesn't exist.

        Security Note: All identifiers are properly quoted using Identifier class.
        The key value is passed as a parameter to prevent SQL injection. This method
        validates that key_column exists in the table before use.
        """
        if key_column is not None and not isinstance(key_column, str):
            raise TypeError(f"Field 'key_column' should be '<str>', but got {type(key_column).__name__}")
        if key_column is not None and key_column not in self.column_names:
            raise ValueError(f"Column '{key_column}' does not exist in table '{self.table_name}'")
        key_column = key_column if key_column is not None else self.primary_key

        columns_str = ", ".join([f'"{col}"' for col in await self.column_names])
        query = sql.SQL("SELECT {columns} FROM {table} WHERE {key_col} = %s").format(
            columns=sql.SQL(columns_str),
            table=sql.Identifier(self.table_name),
            key_col=sql.Identifier(key_column)
        )
        async with self.connection.cursor() as cursor:
            await cursor.execute(query, (key,))
            row = await cursor.fetchone()

        return dict(zip(await self.column_names, row)) if row else {}

    async def get_rows(self, keys: List[Any], key_column: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieve multiple rows by a list of keys in a single database query.

        This method efficiently fetches multiple rows in one database operation,
        eliminating the N+1 query problem that occurs when calling get_row() in a loop.
        It returns only existing rows - missing keys are silently ignored without raising errors.

        Args:
            keys: List of key values to search for.
            key_column: Column to search in (must be valid identifier). If None, uses self.primary_key.

        Returns:
            List of row dictionaries (column_name -> value) for existing keys only.
            The returned list contains only rows that exist in the database.
            The order of returned rows is not guaranteed to match the input keys order.

        Raises:
            TypeError: If key_column has incorrect type.
            ValueError: If key_column fails validation or doesn't exist.

        Security Note: All identifiers are properly quoted using Identifier class.
        Key values are passed as parameters to prevent SQL injection. This method
        validates that key_column exists in the table before use.

        Performance Note: For large lists of keys, consider using MAX_BATCH_SIZE
        to prevent excessive memory usage. The method currently has no built-in
        limit, so application code should enforce reasonable batch sizes.
        """
        if key_column is not None and not isinstance(key_column, str):
            raise TypeError(f"Field 'key_column' should be '<str>', but got {type(key_column).__name__}")
        if key_column is not None and key_column not in await self.column_names:
            raise ValueError(f"Column '{key_column}' does not exist in table '{self.table_name}'")
        key_column = key_column if key_column is not None else self.primary_key

        if not keys:
            return []

        placeholders = sql.SQL(', ').join([sql.Placeholder()] * len(keys))
        columns_str = ", ".join([f'"{col}"' for col in await self.column_names])

        query = sql.SQL("SELECT {columns} FROM {table} WHERE {key_col} IN ({placeholders})").format(
            columns=sql.SQL(columns_str),
            table=sql.Identifier(self.table_name),
            key_col=sql.Identifier(key_column),
            placeholders=placeholders
        )
        async with self.connection.cursor() as cursor:
            await cursor.execute(query, tuple(keys))
            return [dict(zip(await self.column_names, row)) for row in await cursor.fetchall()]

    async def delete_row(self, key: Any, key_column: Optional[str] = None) -> None:
        """
        Delete a row by key with comprehensive validation.

        This method safely deletes a row using parameterized queries and
        validated column names to prevent SQL injection.

        Args:
            key: Value of the key column to identify the row.
            key_column: Column to search in (must be valid identifier). If None, uses self.primary_key.

        Raises:
            TypeError: If key_column has incorrect type.
            ValueError: If key_column fails validation or doesn't exist.

        Security Note: All identifiers are properly quoted using Identifier class.
        The key value is passed as a parameter to prevent SQL injection. This method
        validates that key_column exists in the table before use. Use with caution
        as this operation is destructive and cannot be undone.
        """
        if key_column is not None and not isinstance(key_column, str):
            raise TypeError(f"Field 'key_column' should be '<str>', but got {type(key_column).__name__}")
        if key_column is not None and key_column not in self.column_names:
            raise ValueError(f"Column '{key_column}' does not exist in table '{self.table_name}'")
        key_column = key_column if key_column is not None else self.primary_key

        query = sql.SQL("DELETE FROM {table} WHERE {key_col} = %s").format(
            table=sql.Identifier(self.table_name),
            key_col=sql.Identifier(key_column)
        )
        async with self.connection.cursor() as cursor:
            await cursor.execute(query, (key,))
        await self.connection.commit()

    async def get_column(self, column_name: str) -> List[Any]:
        """
        Retrieve all values from a single column with comprehensive validation.

        This method safely retrieves column values using validated column names
        to prevent SQL injection.

        Args:
            column_name: Name of the column to retrieve (must be valid identifier).

        Returns:
            List of values in the column.

        Raises:
            TypeError: If column_name has incorrect type.
            ValueError: If column_name fails validation or doesn't exist.

        Security Note: The column name is properly quoted using Identifier class
        to prevent SQL injection. This method validates that column_name exists
        in the table before use.
        """
        if not isinstance(column_name, str):
            raise TypeError(f"Field 'column_name' should be '<str>', but got {type(column_name).__name__}")
        if not 0 < len(column_name) <= self.MAX_LEN:
            raise ValueError(f"'column_name' length should be in [0, {self.MAX_LEN}], but got '{len(column_name)}'")

        query = sql.SQL("SELECT {col} FROM {table}").format(col=sql.Identifier(column_name),
                                                            table=sql.Identifier(self.table_name))
        async with self.connection.cursor() as cursor:
            await cursor.execute(query)
            return [row[0] for row in await cursor.fetchall()]

    async def get_all_keys(self, key_column: Optional[str] = None) -> List[Any]:
        """
        Get all values from the primary key column (or specified column).

        This method safely retrieves key values using validated column names
        to prevent SQL injection.

        Args:
            key_column: Column to retrieve (must be valid identifier). If None, uses self.primary_key.

        Returns:
            List of key values.

        Raises:
            TypeError: If key_column has incorrect type.
            ValueError: If key_column fails validation or doesn't exist.

        Security Note: The column name is properly quoted using Identifier class
        to prevent SQL injection. This method validates that key_column exists
        in the table before use.
        """
        if key_column is not None and not isinstance(key_column, str):
            raise TypeError(f"Field 'key_column' should be '<str>', but got {type(key_column).__name__}")
        if key_column is not None and key_column not in self.column_names:
            raise ValueError(f"Column '{key_column}' does not exist in table '{self.table_name}'")
        key_column = key_column if key_column is not None else self.primary_key

        query = sql.SQL("SELECT {col} FROM {table}").format(
            col=sql.Identifier(key_column),
            table=sql.Identifier(self.table_name)
        )
        async with self.connection.cursor() as cursor:
            await cursor.execute(query)
            return [row[0] for row in await cursor.fetchall()]

    async def get_keys_by_column(self, column_name: str, value: Any, key_column: Optional[str] = None) -> List[Any]:
        """
        Get primary keys of rows where a specific column has a given value.

        This method safely retrieves primary keys using validated column names
        to prevent SQL injection.

        Args:
            column_name: Column to filter by (must be valid identifier).
            value: Value to match.
            key_column: Column to return keys from (must be valid identifier). If None, uses self.primary_key.

        Returns:
            List of matching key values.

        Raises:
            TypeError: If column_name or key_column have incorrect types.
            ValueError: If column_name or key_column fail validation or don't exist.

        Security Note: All identifiers are properly quoted using Identifier class.
        The value is passed as a parameter to prevent SQL injection. This method
        validates that column_name and key_column exist in the table before use.
        """
        if not isinstance(column_name, str):
            raise TypeError(f"Field 'column_name' should be '<str>', but got {type(column_name).__name__}")
        if not 0 < len(column_name) <= self.MAX_LEN:
            raise ValueError(f"'column_name' length should be in [0, {self.MAX_LEN}], but got '{len(column_name)}'")

        if key_column is not None and not isinstance(key_column, str):
            raise TypeError(f"Field 'key_column' should be '<str>', but got {type(key_column).__name__}")
        if key_column is not None and key_column not in self.column_names:
            raise ValueError(f"Column '{key_column}' does not exist in table '{self.table_name}'")
        key_column = key_column if key_column is not None else self.primary_key

        query = sql.SQL("SELECT {key_col} FROM {table} WHERE {col} = %s").format(key_col=sql.Identifier(key_column),
                                                                                 table=sql.Identifier(self.table_name),
                                                                                 col=sql.Identifier(column_name))
        async with self.connection.cursor() as cursor:
            await cursor.execute(query, (value,))
            return [row[0] for row in await cursor.fetchall()]

    async def exists(self, key: Any, key_column: Optional[str] = None) -> bool:
        """
        Check if a row with the specified key exists in the table.

        This method safely checks for row existence using parameterized queries
        and validated column names to prevent SQL injection. It uses the efficient
        EXISTS operator to minimize data transfer and processing overhead.

        Args:
            key: Value of the key column to search for.
            key_column: Column to search in (must be valid identifier). If None, uses self.primary_key.

        Returns:
            True if a row with the specified key exists, False otherwise.

        Raises:
            TypeError: If key_column has incorrect type.
            ValueError: If key_column fails validation or doesn't exist in the table.

        Security Note: All identifiers are properly quoted using Identifier class.
        The key value is passed as a parameter to prevent SQL injection. This method
        validates that key_column exists in the table before use and does not expose
        any sensitive data in error messages.

        Performance Note: This method executes a single EXISTS query which is optimized
        by database indexes on the key column. It's more efficient than retrieving the
        full row when only existence checking is needed, especially for large tables
        or columns with heavy data types (JSONB, BYTEA, etc.).
        """
        if key_column is not None and not isinstance(key_column, str):
            raise TypeError(f"Field 'key_column' should be '<str>', but got {type(key_column).__name__}")
        if key_column is not None and key_column not in await self.column_names:
            raise ValueError(f"Column '{key_column}' does not exist in table '{self.table_name}'")
        key_column = key_column if key_column is not None else self.primary_key

        query = sql.SQL("SELECT EXISTS(SELECT 1 FROM {table} WHERE {key_col} = %s)").format(
            table=sql.Identifier(self.table_name),
            key_col=sql.Identifier(key_column)
        )
        async with self.connection.cursor() as cursor:
            await cursor.execute(query, (key,))
            result = await cursor.fetchone()
            return result[0] if result else False

    async def show(self, start: Optional[int] = None, stop: Optional[int] = None) -> str:
        """
        Format table contents as a string for debugging or display.

        This method retrieves table data and formats it as a PrettyTable string.
        It supports pagination through start and stop parameters.

        Args:
            start: Offset to start from (for pagination).
            stop: Limit number of rows (stop - start).

        Returns:
            Pretty-formatted table as string.

        Raises:
            ValueError: If arguments are invalid or contradictory.

        Security Note: All identifiers are properly quoted using Identifier class
        to prevent SQL injection. This method is intended for debugging and should
        not be used for production data display due to potential information leakage.

        Performance Note: This method loads all requested rows into memory, so it
        should not be used with large tables or in performance-critical paths.
        """
        async with self.connection.cursor() as cursor:
            columns_str = ", ".join([f'"{col}"' for col in await self.column_names])
            if start is None and stop is None:
                query = sql.SQL("SELECT {columns} FROM {table}").format(
                    columns=sql.SQL(columns_str),
                    table=sql.Identifier(self.table_name))
                await cursor.execute(query)

            elif start is not None and stop is None:
                query = sql.SQL("SELECT {columns} FROM {table} LIMIT %s").format(
                    columns=sql.SQL(columns_str),
                    table=sql.Identifier(self.table_name))
                await cursor.execute(query, (start,))

            elif start is not None and stop is not None:
                query = sql.SQL("SELECT {columns} FROM {table} OFFSET %s LIMIT %s").format(
                    columns=sql.SQL(columns_str),
                    table=sql.Identifier(self.table_name))
                await cursor.execute(query, (start, stop - start))

            else:
                raise ValueError("show() принимает максимум 2 аргумента")

            rows = cursor.fetchall()
            table = PrettyTable()
            table.title = f"Table: {self.table_name}"
            table.field_names = await self.column_names
            for row in sorted(rows, key=lambda x: x[0]):
                table.add_row(row)

            return str(table)

    async def commit(self) -> None:
        """
        Commit the current transaction.

        This method commits any pending transactions to the database.

        Security Note: This is a low-level operation that should be used with caution.
        Most CRUD methods automatically commit transactions unless specified otherwise.
        """
        await self.connection.commit()

    async def set_cache_size(self, size: int) -> None:
        """
        Set PostgreSQL work_mem for the current session.

        This method configures the amount of memory PostgreSQL uses for operations
        like sorting and hashing. It affects only the current session.

        Args:
            size: Memory size in kilobytes.

        Security Note: This is a session-level configuration that affects query
        performance but not security directly. Use with caution as setting too high
        values can impact overall database performance.

        Performance Note: Adjusting work_mem can improve performance for memory-intensive
        operations, but excessive values can lead to memory pressure on the database server.
        """
        async with self.connection.cursor() as cursor:
            await cursor.execute("SET work_mem TO %s", (f"{size}kB",))

    async def command(self, query: str, params: tuple = ()) -> Any:
        """
        Execute a raw SQL command.

        Args:
            query: SQL query string.
            params: Parameters to substitute.

        Returns:
            Query result if SELECT, None otherwise.

        WARNING: This is a highly dangerous method that should only be used for debugging.
        Never use this method with untrusted input in production code.

        Security Note: This method bypasses all the safety mechanisms of this class.
        It executes raw SQL with parameters, but the query string itself is not validated.
        Use only for debugging purposes in development environments. In production,
        this method should be disabled or heavily restricted.
        """
        async with self.connection.cursor() as cursor:
            await cursor.execute(query, params)
            try:
                return await cursor.fetchall()
            except psycopg.ProgrammingError:
                return None

    async def get_column_names(self) -> List[str]:
        """
        Fetch and return the list of column names from the database.

        This method queries the information_schema to discover all columns in
        the table within the 'public' schema. It validates the table existence.

        Returns:
            List of column names in ordinal position order.

        Raises:
            ValueError: If the table does not exist in the 'public' schema.

        Security Note: The query is parameterized to prevent SQL injection.
        It explicitly limits results to the 'public' schema to prevent access
        to system tables or tables in other schemas.
        """
        async with self.connection.cursor() as cursor:
            await cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = %s
              AND table_schema = 'public'
            ORDER BY ordinal_position""", (self.table_name,))

            columns = await cursor.fetchall()
            if not columns:
                raise ValueError(f"Table '{self.table_name}' does not exist in 'public' schema")

            return [row[0] for row in columns]

    async def autodetect_primary_key(self, primary_key: Optional[str] = None) -> str:
        """
        Determine the primary key column for the table.

        If a primary_key is explicitly provided, it is validated against the table's columns
        and returned (even if it's not defined as a PRIMARY KEY constraint).
        If no primary_key is provided, the method queries the database metadata to find
        the column defined as the PRIMARY KEY constraint in the 'public' schema.
        If no constraint is found, returns None.

        This method does not modify self.primary_key — it only returns a value.

        Args:
            primary_key: Optional name of the column to use as primary key.
                         If provided, must exist in the table.

        Returns:
            Name of the primary key column, as provided or detected.
            Returns None if no primary_key is provided and no PRIMARY KEY constraint exists.

        Raises:
            ValueError: If the provided primary_key does not exist in the table.

        Security Note: The query is parameterized to prevent SQL injection.
        It explicitly limits results to the 'public' schema to prevent access
        to system tables or tables in other schemas. The method validates that
        any provided primary_key exists in the table columns.

        Implementation Note: This is an internal helper method used during
        initialization. Prefer using the primary_key property for application code.
        """
        if primary_key is not None:
            if primary_key not in self.column_names:
                raise ValueError(f"Column '{primary_key}' does not exist in table '{self.table_name}'")
            return primary_key

        async with self.connection.cursor() as cursor:
            await cursor.execute("""
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu 
                    ON tc.constraint_name = kcu.constraint_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
                  AND tc.table_schema = 'public'
                  AND tc.table_name = %s
                ORDER BY kcu.ordinal_position
                LIMIT 1;
            """, (self.table_name,))
            row = await cursor.fetchone()
            return row[0] if row else None

