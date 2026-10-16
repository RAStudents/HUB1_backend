import os
import types
import logging
import asyncio
import psycopg
from enum import Enum
from psycopg import sql
from typing import Any, List, Dict, Optional
from prettytable import PrettyTable
from core.SQLPGModule.table import Table
from core.SQLPGModule.enums import Status, DBType


logger = logging.getLogger(__name__)


class DataBase:
    MAX_LEN = 100
    """
    A high-level asynchronous wrapper for managing PostgreSQL database connections with automatic recovery.

    This class provides:
    - Secure connection management with automatic reconnection on failures
    - Schema management and table caching
    - ORM-like access to database tables
    - Comprehensive input validation to prevent SQL injection
    - Automatic loading of tables and their primary keys on initialization

    Important: This is an async-first implementation. All database operations must be awaited.
    The class automatically handles connection recovery, but application code should be designed
    to handle potential transient errors during high-load scenarios.
    """

    def __init__(self, dbname: str, user: str, password: str, host: str = "localhost", port: int = 5432):
        """
        Initialize the database wrapper without establishing a connection.

        Note: This constructor only stores connection parameters. No network operations are
        performed at this stage. To establish a connection, call the async connect() method.

        Args:
            dbname: Name of the database to connect to.
            user: Username for authentication (must be valid PostgreSQL identifier).
            password: Password for authentication.
            host: Database host address (default: localhost).
            port: Database port number (default: 5432).

        Raises:
            TypeError: If any parameter has incorrect type.
            ValueError: If any parameter fails validation (length, format).

        Security Note: Passwords are stored in memory but not logged. Ensure your environment
        protects process memory from unauthorized access.
        """
        self.dbname = dbname
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self._connection = None
        self._tables = None

    def __len__(self) -> int:
        """
        Get the number of tables in the database.

        This method returns the count of tables that have been loaded into the internal cache
        during initialization or connection recovery.

        Returns:
            Number of tables in the 'public' schema that are currently cached.
        """
        return len(self.table_names)

    def __str__(self):
        """
        Return a human-readable overview of the database.

        Returns:
            Pretty-formatted string with table names, row counts, and status.
        """
        table = PrettyTable()
        table.title = f"{'Empty ' if not len(self.table_names) > 0 else ''}DataBase"
        table.field_names = ["Name", "Type", "Columns count", "Rows count", "Status"]
        for table_name in self.table_names:
            loop = asyncio.new_event_loop()
            this_table = loop.run_until_complete(self.get_table(table_name))
            db_status = this_table.status
            db_rows_cnt = this_table.count
            db_columns_cnt = this_table.columns_count
            if db_status == Status.ENABLE:
                status = DataBase._set_str_cmd_clr("ENABLE", 'GREEN')
            else:
                status = DataBase._set_str_cmd_clr("EMPTY", 'RED')
            table.add_row([table_name, "<DataBase>", db_columns_cnt, db_rows_cnt, status])
        return str(table)

    def __enter__(self) -> 'DataBase':
        """
        Support for context manager protocol.

        Note: This method does not automatically establish a database connection.
        It simply returns the instance for use in 'with' statements.

        Returns:
            Self for use in 'with' statement.
        """
        return self

    def __exit__(self,
                 exc_type: type[BaseException] | None,
                 exc_val: BaseException | None,
                 exc_tb: types.TracebackType | None) -> bool | None:
        """
        Clean up database connection on exit from context.

        This method closes the database connection when exiting a 'with' block.
        Any exceptions raised within the block are propagated normally.

        Args:
            exc_type: Exception type if raised, otherwise None.
            exc_val: Exception instance if raised, otherwise None.
            exc_tb: Traceback object if raised, otherwise None.
        """
        self.close()

    @property
    def dbname(self) -> str:
        """
        Get the database name used for connection.

        Returns:
            Name of the database.
        """
        return self._dbname

    @dbname.setter
    def dbname(self, dbname: str) -> None:
        """
        Set the database name with validation.

        Args:
            dbname: Name of the database to connect to.

        Raises:
            TypeError: If dbname is not a string.
            ValueError: If dbname length is invalid (must be 1-MAX_LEN characters).

        Security Note: Database names are validated to prevent SQL injection through
        identifier names. Only alphanumeric characters and underscores are permitted
        by PostgreSQL, but this validation enforces additional length constraints.
        """
        if not isinstance(dbname, str):
            raise TypeError(f"Field 'dbname' should be '<str>', but got {type(dbname).__name__}")
        if not 0 < len(dbname) <= self.MAX_LEN:
            raise ValueError(f"'dbname' length should be in range [0, {self.MAX_LEN}], but got '{len(dbname)}'")
        self._dbname = dbname

    @property
    def user(self) -> str:
        """
        Get the username used for authentication.

        Returns:
            Username for database authentication.
        """
        return self._user

    @user.setter
    def user(self, user: str) -> None:
        """
        Set the username with validation.

        Args:
            user: Username for authentication.

        Raises:
            TypeError: If user is not a string.
            ValueError: If user length is invalid (must be 1-MAX_LEN characters).

        Security Note: Usernames are validated to prevent SQL injection through
        identifier names. Only alphanumeric characters and underscores are permitted
        by PostgreSQL, but this validation enforces additional length constraints.
        """
        if not isinstance(user, str):
            raise TypeError(f"Field 'user' should be '<str>', but got {type(user).__name__}")
        if not 0 < len(user) <= self.MAX_LEN:
            raise ValueError(f"'user' length should be in range [0, {self.MAX_LEN}], but got '{len(user)}'")
        self._user = user

    @property
    def password(self) -> str:
        """
        Get the password used for authentication.

        Returns:
            Password for database authentication.

        Security Note: Passwords are stored in memory but not logged. This getter
        should be used with caution as it exposes the password in memory.
        """
        return self._password

    @password.setter
    def password(self, password: str) -> None:
        """
        Set the password with validation.

        Args:
            password: Password for authentication.

        Raises:
            TypeError: If password is not a string.
            ValueError: If password length is invalid (must be 1-MAX_LEN characters).

        Security Note: Passwords are stored in memory but not logged. Ensure your
        environment protects process memory from unauthorized access.
        """
        if not isinstance(password, str):
            raise TypeError(f"Field 'password' should be '<str>', but got {type(password).__name__}")
        if not 0 <= len(password) <= self.MAX_LEN:
            raise ValueError(f"'password' length should be in range [0, {self.MAX_LEN}], but got '{len(password)}'")
        self._password = password

    @property
    def host(self) -> str:
        """
        Get the database host address.

        Returns:
            Host address for database connection.
        """
        return self._host

    @host.setter
    def host(self, host: str) -> None:
        """
        Set the database host address with validation.

        Args:
            host: Database host address.

        Raises:
            TypeError: If host is not a string.
            ValueError: If host length is invalid (must be 1-MAX_LEN characters).

        Security Note: Hostnames are validated for length but not format. Ensure
        you're connecting to a trusted host to prevent man-in-the-middle attacks.
        """
        if not isinstance(host, str):
            raise TypeError(f"Field 'host' should be '<str>', but got {type(host).__name__}")
        if not 0 < len(host) <= self.MAX_LEN:
            raise ValueError(f"'host' length should be in range [0, {self.MAX_LEN}], but got '{len(host)}'")
        self._host = host

    @property
    def port(self) -> int:
        """
        Get the database port number.

        Returns:
            Port number for database connection.
        """
        return self._port

    @port.setter
    def port(self, port: int) -> None:
        """
        Set the database port number with validation.

        Args:
            port: Database port number.

        Raises:
            TypeError: If port is not an integer.
            ValueError: If port is negative.

        Note:
            The port must be non-negative as it's used for network connections.
            This validation ensures data integrity for connection operations.
        """
        if not isinstance(port, int) or isinstance(port, bool):
            raise TypeError(f"Field 'port' should be '<int>', but got {type(port).__name__}")
        if port < 0:
            raise ValueError(f"Field 'port' should be >= 0, but got '{port}'")
        self._port = port

    @property
    def tables(self) -> List[Table]:
        """
        Get a list of all cached Table instances.

        This method returns all tables that have been loaded into the internal cache
        during initialization or connection recovery. The cache is automatically
        updated when connections are restored.

        Returns:
            List of Table objects representing tables in the 'public' schema.
        """
        return list(self._tables.values())

    @property
    def table_names(self) -> List[str]:
        """
        Get a list of all table names in the 'public' schema.

        This method returns table names that have been loaded into the internal cache
        during initialization or connection recovery. The cache is automatically
        updated when connections are restored.

        Returns:
            List of table names in the 'public' schema.
        """
        return list(self._tables.keys())

    @property
    async def is_connected(self) -> bool:
        """
        Check if the database connection is active and responsive.

        Note: This performs an actual SELECT 1 query to verify the connection is not
        just technically open but also responsive. This is more reliable than checking
        only the 'closed' flag, which may not detect broken connections.

        Returns:
            True if connection is active and responsive, False otherwise.

        Warning: This method executes a database query, so it should not be called
        excessively in performance-critical paths. Consider caching the result for
        short periods when appropriate.
        """
        try:
            if self._connection and not self._connection.closed:
                async with self._connection.cursor() as cursor:
                    await cursor.execute("SELECT 1")
                return True
            return False
        except (psycopg.OperationalError, psycopg.InterfaceError, psycopg.DatabaseError) as e:
            logger.error(f"[SQL] Failed to execute admin command: {type(e).__name__}")
            if logger.getEffectiveLevel() <= logging.DEBUG:
                logger.debug(f"[SQL] Detailed error: {e}")
            return False

    @classmethod
    async def create(cls, dbname: str, user: str, password: str, host: str = "localhost", port: int = 5432):
        """
        Factory method to create and initialize a database connection.

        This async constructor pattern ensures proper initialization sequence:
        1. Creates instance with connection parameters
        2. Establishes database connection
        3. Loads table metadata into cache

        Args:
            dbname: Name of the database to connect to.
            user: Username for authentication.
            password: Password for authentication.
            host: Database host address.
            port: Database port number.

        Returns:
            Fully initialized DataBase instance with active connection.

        Raises:
            ConnectionError: If database connection cannot be established.
            DatabaseError: If metadata queries fail after connection.

        Usage:
            db = await DataBase.create(dbname="mydb", user="user", password="pass")
        """
        instance = cls(dbname=dbname, user=user, password=password, host=host, port=port)
        await instance.connect()
        return instance

    async def create_database(self, dbname: str, owner: Optional[str] = None) -> bool:
        """
        Create a new database if it does not exist.

        This method connects to the 'postgres' system database to execute the CREATE DATABASE
        command. It first checks if the database already exists to avoid errors.

        Args:
            dbname: Name for the new database (must be valid identifier).
            owner: Optional role name to own the database.

        Returns:
            True if database was created or already exists, False otherwise.

        Raises:
            TypeError: If parameters have incorrect types.
            ValueError: If parameters fail validation.
            ConnectionError: If unable to connect to system database.

        Security Note: This operation requires superuser privileges or appropriate
        CREATEDB permissions. The method safely handles identifier quoting to prevent
        SQL injection.
        """
        if not isinstance(dbname, str):
            raise TypeError(f"Field 'dbname' should be '<str>', but got {type(dbname).__name__}")
        if not 0 < len(dbname) <= self.MAX_LEN:
            raise ValueError(f"'dbname' length should be in range [0, {self.MAX_LEN}], but got '{len(dbname)}'")

        if owner is not None and not isinstance(owner, str):
            raise TypeError(f"'owner' must be '<str>', but got {type(owner).__name__}")
        if owner is not None and not 0 < len(owner) <= self.MAX_LEN:
            raise ValueError(f"'owner' length should be in range [0, {self.MAX_LEN}], but got '{len(owner)}'")

        if await self._database_exists(dbname):
            logger.info(f"Database '{dbname}' already exists.")
            return True

        query = sql.SQL("CREATE DATABASE {dbname} OWNER {owner}") if owner else sql.SQL("CREATE DATABASE {dbname}")
        query = query.format(dbname=sql.Identifier(dbname), owner=sql.Identifier(owner) if owner else None)
        logger.info(f"[SQL] Create database...")
        if logger.getEffectiveLevel() <= logging.DEBUG:
            logger.debug(f"[SQL] Create database '{self.dbname}' with owner: '{owner}'")
        return await self.execute_admin_command(query)

    async def create_role(self, role_name: str, password: Optional[str] = None, superuser: bool = False) -> None:
        """
        Create a new database role (user account) with specified privileges.

        This method safely creates a role using parameterized queries to prevent SQL injection.
        The password is properly quoted using PostgreSQL's quote_literal function.

        Args:
            role_name: Name of the role to create (must be valid identifier).
            password: Optional password for the role.
            superuser: Whether to grant SUPERUSER privileges.

        Raises:
            TypeError: If parameters have incorrect types.
            ValueError: If parameters fail validation.
            ConnectionError: If unable to connect to system database.
            InsufficientPrivilege: If current user lacks CREATE ROLE permission.

        Security Note: Creating superusers should be done with extreme caution. This
        method validates all inputs and uses secure quoting mechanisms, but the calling
        code should implement additional authorization checks as appropriate for your
        security requirements.
        """
        await self._ensure_connection()

        if not isinstance(role_name, str):
            raise TypeError(f"Field 'role_name' should be '<str>', but got {type(role_name).__name__}")
        if not 0 < len(role_name) <= self.MAX_LEN:
            raise ValueError(f"'role_name' length should be in range [0, {self.MAX_LEN}], but got '{len(role_name)}'")

        if password is not None and not isinstance(password, str):
            raise TypeError(f"Field 'password' should be '<str>', but got {type(password).__name__}")
        if password is not None and not 0 < len(password) <= self.MAX_LEN:
            raise ValueError(f"'password' length should be in range [0, {self.MAX_LEN}], but got '{len(password)}'")

        if not isinstance(superuser, bool):
            raise TypeError(f"Field 'superuser' should be '<bool>', but got {type(password).__name__}")

        query_parts = [sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role_name))]
        if password:
            escaped_password = await self._escape_string(password)
            query_parts.append(sql.SQL("PASSWORD {}").format(sql.Literal(escaped_password)))
        if superuser:
            query_parts.append(sql.SQL("SUPERUSER"))
        await self.execute_admin_command(sql.SQL(" ").join(query_parts))

    async def add_table(self,
                        table_name: str,
                        columns: Dict[str, DBType],
                        primary_key: Optional[str] = None,
                        indexes: Optional[List[str]] = None) -> None:
        """
        Create a new table and add it to the internal cache.

        This method safely creates a table with proper identifier quoting to prevent
        SQL injection. If no primary key is specified, an 'id' column with SERIAL type
        is automatically created as the primary key.

        Args:
            table_name: Name of the table to create (must be valid identifier).
            columns: Dictionary mapping column names to their data types (as Enum values).
            primary_key: Optional name of the primary key column.

        Raises:
            TypeError: If parameters have incorrect types.
            ValueError: If parameters fail validation.
            DatabaseError: If table creation fails at database level.

        Security Note: All identifiers are properly quoted using psycopg's Identifier
        class. Column types must come from trusted Enum sources to prevent execution
        of arbitrary SQL. The method validates all inputs before query construction.
        """
        await self._ensure_connection()
        if not isinstance(table_name, str):
            raise TypeError(f"Field 'table_name' should be '<str>', but got {type(table_name).__name__}")
        if not 0 < len(table_name) <= self.MAX_LEN:
            raise ValueError(f"'table_name' length should be in range [0, {self.MAX_LEN}], but got '{len(table_name)}'")

        column_definitions = []
        for column, col_type in columns.items():
            if not isinstance(column, str):
                raise TypeError(f"Field 'column' should be '<str>', but got {type(column).__name__}")
            if not 0 < len(column) <= self.MAX_LEN:
                raise ValueError(f"'column' length should be in range [0, {self.MAX_LEN}], but got '{len(column)}'")

            if not isinstance(col_type, DBType):
                raise TypeError(f"Field 'col_type' should be one of {list(DBType)}, but got {type(col_type).__name__}")

            column_definitions.append(sql.SQL("{} {}").format(sql.Identifier(column), sql.SQL(col_type.value)))

        if primary_key:
            if not isinstance(primary_key, str):
                raise TypeError(f"Field 'primary_key' should be '<str>', but got {type(primary_key).__name__}")
            if not 0 < len(primary_key) <= self.MAX_LEN:
                raise ValueError(f"'primary_key' length should be in [0, {self.MAX_LEN}], but got '{len(primary_key)}'")
            column_definitions.append(sql.SQL("PRIMARY KEY ({})").format( sql.Identifier(primary_key)))

        query = sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(sql.Identifier(table_name),
                                                                     sql.SQL(", ").join(column_definitions))

        self._tables[table_name] = Table(connection=self._connection,
                                         table_name=table_name,
                                         primary_key=primary_key if primary_key else "id")
        async with self._connection.cursor() as cursor:
            await cursor.execute(query)
        await self._connection.commit()
        logger.info(f"[SQL] Create table...")

        if indexes:
            if not isinstance(indexes, list):
                raise TypeError(f"Field 'indexes' should be '<List[str]>', but got {type(indexes).__name__}")

            for index_column in indexes:
                if not isinstance(index_column, str):
                    raise TypeError(f"Index column name should be '<str>', but got {type(index_column).__name__}")
                if not 0 < len(index_column) <= self.MAX_LEN:
                    raise ValueError(
                        f"Index column name length should be in [0, {self.MAX_LEN}], but got '{len(index_column)}'")

                if index_column not in columns:
                    raise ValueError(f"Column '{index_column}' does not exist in table '{table_name}'")

                index_name = f"idx_{table_name}_{index_column}"
                index_query = sql.SQL("CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column})").format(
                    index_name=sql.Identifier(index_name),
                    table=sql.Identifier(table_name),
                    column=sql.Identifier(index_column)
                )

                async with self._connection.cursor() as cursor:
                    await cursor.execute(index_query)

                logger.info(f"[SQL] Created index '{index_name}' on column '{index_column}'")

            # Отдельный коммит для индексов (гарантируем завершение транзакции)
            await self._connection.commit()

        if logger.getEffectiveLevel() <= logging.DEBUG:
            logger.debug(
                f"[SQL] Created table '{table_name}' in database '{self.dbname}' "
                f"with columns: {list(columns.keys())}, "
                f"primary_key: '{primary_key}', "
                f"indexes: {indexes or []}"
            )

    async def get_table(self, table_name: str) -> Table:
        """
        Get a cached Table instance by name with connection verification.

        This method first ensures the database connection is active before returning
        the table reference. It does not reload table metadata on each call - it uses
        the cached metadata loaded during initialization.

        Args:
            table_name: Name of the table to retrieve (must be valid identifier).

        Returns:
            Table instance providing access to the specified table.

        Raises:
            TypeError: If table_name is not a string.
            ValueError: If table_name fails validation or table doesn't exist in cache.
            ConnectionError: If database connection cannot be established.

        Warning: This returns a cached instance. If the table structure has changed
        externally since initialization, the metadata may be outdated. For critical
        operations requiring up-to-date schema information, consider reconnecting.
        """
        await self._ensure_connection()

        if not isinstance(table_name, str):
            raise TypeError(f"Field 'table_name' should be '<str>', but got {type(table_name).__name__}")
        if not 0 < len(table_name) <= self.MAX_LEN:
            raise ValueError(f"'table_name' length should be in range [0, {self.MAX_LEN}], but got '{len(table_name)}'")
        if table_name not in self.table_names:
            raise ValueError(f"Table '{table_name}' does not exist")

        return self._tables[table_name]

    async def delete_table(self, table_name: str) -> None:
        """
        Drop a table and remove it from the cache.

        This method executes a DROP TABLE command with CASCADE option to remove
        the table and all its dependent objects. It also updates the internal cache.

        Args:
            table_name: Name of the table to drop (must be valid identifier).

        Raises:
            TypeError: If table_name is not a string.
            ValueError: If table_name fails validation or table doesn't exist.
            DatabaseError: If DROP command fails at database level.

        Security Note: This operation requires appropriate DROP privileges. The method
        validates inputs and uses proper identifier quoting to prevent SQL injection.
        Use with caution as this operation is destructive and cannot be undone.
        """
        await self._ensure_connection()

        if not isinstance(table_name, str):
            raise TypeError(f"Field 'table_name' should be '<str>', but got {type(table_name).__name__}")
        if not 0 < len(table_name) <= self.MAX_LEN:
            raise ValueError(f"'table_name' length should be in range [0, {self.MAX_LEN}], but got '{len(table_name)}'")
        if table_name not in self.table_names:
            raise ValueError(f"Table '{table_name}' does not exist")

        query = sql.SQL("DROP TABLE IF EXISTS {table} CASCADE").format(table=sql.Identifier(table_name))
        async with self._connection.cursor() as cursor:
            await cursor.execute(query)
        await self._connection.commit()
        del self._tables[table_name]
        logger.info(f"[SQL] Delete table...")
        if logger.getEffectiveLevel() <= logging.DEBUG:
            logger.debug(f"[SQL] Delete table '{table_name}' from database '{self.dbname}'")

    async def execute_admin_command(self, query: sql.Composed) -> bool:
        """
        Execute an administrative SQL command (e.g., CREATE DATABASE).
        Uses connection to 'postgres' DB with autocommit.

        This method is designed for executing administrative commands that require
        connection to the system 'postgres' database rather than the target database.

        Args:
            query: Prepared SQL command (sql.Composed).

        Returns:
            True on success, False on failure.

        Security Note: This method executes raw SQL commands. The query should be
        constructed using psycopg's Composed class with proper parameterization
        to prevent SQL injection. Never include untrusted input directly in queries.
        """
        try:
            async with await psycopg.AsyncConnection.connect(
                    dbname="postgres",
                    user=self.user,
                    password=self.password,
                    host=self.host,
                    port=self.port
            ) as conn:
                await conn.execute("SET LOCAL statement_timeout = 5000")  # Защита
                await conn.execute(query)
                logger.info("[SQL] Async admin command executed successfully.")
            return True

        except psycopg.Error as e:
            logger.error(f"[SQL] Failed to execute admin command: {type(e).__name__}")
            if logger.getEffectiveLevel() <= logging.DEBUG:
                logger.debug(f"[SQL] Detailed error: {e}")
            return False

    async def connect(self):
        """
        Establish database connection and initialize metadata cache.

        This method performs the following steps:
        1. Creates the database if it doesn't exist
        2. Establishes connection to the target database
        3. Loads all tables and their metadata into cache

        Note: This method is automatically called by the create() factory method.
        Most applications should use create() rather than calling connect() directly.

        Raises:
            ConnectionError: If database connection cannot be established.
            DatabaseError: If metadata queries fail after connection.

        Security Note: Connection parameters are validated before use. SSL is enforced
        in production environments (when PG_SSL_CERT_PATH is set). The connection
        uses keepalive parameters to prevent timeouts during long-running operations.
        """
        await self.create_database(dbname=self.dbname, owner=self.user)
        await self._create_cursor()
        self._tables = await self._load_all_tables()

    async def _load_all_tables(self) -> Dict[str, Table]:
        """
        Internal method to load all tables from the 'public' schema into cache.

        This method queries the information_schema to discover all tables and their
        primary keys in the public schema. It should only be called during initialization
        or after connection recovery.

        Returns:
            Dictionary mapping table names to initialized Table objects.

        Raises:
            ConnectionError: If database connection is not active.
            DatabaseError: If metadata queries fail.

        Implementation Note: This is an internal method and should not be called directly
        by application code. It's used during initialization and connection recovery.
        The method assumes a valid connection exists and will raise errors if not.
        """
        await self._ensure_connection()

        query = """
            SELECT tc.table_name, kcu.column_name AS pk_column
            FROM information_schema.table_constraints tc
            LEFT JOIN information_schema.key_column_usage kcu 
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = 'public'
            ORDER BY tc.table_name;
        """

        async with self._connection.cursor() as cursor:
            await cursor.execute(query)
            tables = {}
            for table_name, pk_column in await cursor.fetchall():
                tables[table_name] = Table(connection=self._connection,
                                           table_name=table_name,
                                           primary_key=pk_column if pk_column else "id")
            return tables

    async def _get_tables_names(self) -> List[str]:
        """
        Internal method to get a list of all table names in the 'public' schema.

        This method queries the information_schema to discover table names.
        It's used internally by other methods and should not be called directly.

        Returns:
            List of table names in the 'public' schema.

        Raises:
            ConnectionError: If database connection is not active.
            DatabaseError: If metadata query fails.

        Implementation Note: This is an internal helper method. Prefer using
        table_names property for application code.
        """
        await self._ensure_connection()

        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name;
            """)
            return [row[0] for row in await cursor.fetchall()]

    async def _create_cursor(self) -> None:
        """
        Internal method to establish a database connection.

        This method creates a new connection with keepalive parameters to prevent
        timeouts during long-running operations. It closes any existing connection
        before creating a new one.

        Note: This is an internal method and should not be called directly by
        application code. Use _ensure_connection() instead, which handles connection
        validation and recovery.

        Security Note: The connection uses SSL with certificate verification in
        production environments. Keepalive parameters help prevent connection
        hijacking through timeout-based attacks.
        """
        if not self._connection or self._connection.closed:
            if self._connection:
                await self._connection.close()
            self._connection = await psycopg.AsyncConnection.connect(
                dbname=self.dbname,
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
                # sslmode='verify-full',
                # sslrootcert=os.path.expanduser('/Users/stepanborodin/Downloads/ca.crt'),
                #
                # # Ключевые параметры для предотвращения таймаутов:
                # keepalives=1,  # Включает keepalive пакеты
                # keepalives_idle=30,  # Отправляет keepalive через 300 секунд бездействия
                # keepalives_interval=30,  # Интервал между keepalive пакетами
                # keepalives_count=100  # Количество попыток перед разрывом соединения
            )
            logger.info(f"[SQL] Created/Updated cursor fjr DB...")
            if logger.getEffectiveLevel() <= logging.DEBUG:
                logger.debug(f"[SQL] Created/Updated cursor for DB={self.dbname}, HOST={self.host}, PORT={self.port}")

    async def _database_exists(self, db_name: str) -> bool:
        """
        Internal method to check if a database with the given name exists.

        This method connects to the system 'postgres' database to query pg_database.

        Args:
            db_name: Name of the database to check.

        Returns:
            True if database exists, False otherwise.

        Raises:
            ConnectionError: If unable to connect to system database.
            DatabaseError: If query fails.

        Security Note: This method uses parameterized queries to prevent SQL injection.
        It's safe to use with untrusted input as long as the input is properly validated
        by the calling method.
        """
        try:
            async with await psycopg.AsyncConnection.connect(
                    dbname="postgres",
                    user=self.user,
                    password=self.password,
                    host=self.host,
                    port=self.port
            ) as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
                    return await cur.fetchone() is not None
        except psycopg.Error as e:
            logger.error(f"[SQL] Error checking database existence: {type(e).__name__}")
            if logger.getEffectiveLevel() <= logging.DEBUG:
                logger.debug(f"[SQL] Detailed error: {e}")
            return False

    async def _ensure_connection(self) -> None:
        """
        Internal method to verify and restore database connection if needed.

        This method performs an actual SELECT 1 query to verify the connection is
        not just technically open but also responsive. If the connection is broken,
        it automatically reconnects and reloads the table metadata cache.

        Implementation Details:
        1. Attempts a simple SELECT 1 query to test connection
        2. On failure, logs warning and initiates reconnection
        3. After reconnection, reloads table metadata cache
        4. Returns silently if connection is healthy

        Raises:
            ConnectionError: If reconnection fails after multiple attempts.

        Security Note: This method uses a separate connection for password escaping
        to prevent potential recursion issues during connection recovery. It's designed
        to be called before any database operation that requires an active connection.
        """
        try:
            if self._connection and not self._connection.closed:
                async with self._connection.cursor() as cursor:
                    await cursor.execute("SELECT 1")
            return
        except (psycopg.OperationalError, psycopg.InterfaceError, psycopg.DatabaseError) as e:
            logger.warning(f"[SQL] Connection issue detected: {type(e).__name__}")
            if logger.getEffectiveLevel() <= logging.DEBUG:
                logger.debug(f"[SQL] Detailed error: {e}")

        logger.warning("[SQL] Connection closed, reconnecting...")
        await asyncio.sleep(0.1)
        await self._create_cursor()
        self._tables = await self._load_all_tables()

    async def _escape_string(self, value: str) -> str:
        """
        Internal method to safely escape string values for SQL queries.

        This method uses a dedicated connection to call PostgreSQL's quote_literal()
        function, ensuring proper escaping of special characters. It's designed to
        work even when the main connection is broken.

        Args:
            value: String value to escape.

        Returns:
            Properly quoted string safe for inclusion in SQL queries.

        Security Note: This is a critical security component that prevents SQL injection
        in administrative commands. It uses PostgreSQL's built-in quoting function rather
        than client-side escaping, which is more reliable. The method creates a temporary
        connection specifically for this purpose to avoid dependency on the main connection.
        """
        async with await psycopg.AsyncConnection.connect(
                dbname=self.dbname,
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port
        ) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT quote_literal(%s)", (value,))
                return (await cursor.fetchone())[0]

    @staticmethod
    def _set_str_cmd_clr(text: str, color: str) -> str:
        """
        Apply ANSI color codes to text for terminal output.

        Args:
            text: Text to colorize.
            color: Color name ('RED', 'GREEN', 'YELLOW').

        Returns:
            Text wrapped with appropriate ANSI color codes.

        Note: This is a utility method for CLI output only. It does not affect
        log files or non-terminal outputs. In production environments, colored
        output is typically disabled.

        Warning: This method does not validate the input text. Ensure that text
        does not contain untrusted user input to prevent ANSI escape sequence attacks.
        """
        clr_text = ""
        if color == 'RED':
            clr_text = "\033[31m {}\033[0m".format(text)
        elif color == 'GREEN':
            clr_text = "\033[32m {}\033[0m".format(text)
        elif color == 'YELLOW':
            clr_text = "\033[33m {}\033[0m".format(text)
        return clr_text

    async def close(self) -> None:
        """
        Gracefully close the database connection and release all resources.

        This method terminates the active database connection, clears the internal
        table cache, and resets internal state to prevent further operations on
        a closed connection. It's designed to be called explicitly when the database
        is no longer needed or as part of cleanup in context managers.

        Raises:
            ConnectionError: If connection closure fails unexpectedly
            Warning: If attempting to close an already closed connection

        Security Note: This method ensures proper cleanup of database resources,
        including sensitive connection credentials that may be stored in memory.
        After calling close(), the instance should not be reused for database operations
        without first calling connect() to re-establish the connection.

        Implementation details:
        - Safely checks if connection exists and is not already closed
        - Closes active PostgreSQL connection using proper async methods
        - Clears internal table cache to prevent dangling references
        - Resets connection state variables to prevent accidental reuse
        - Logs connection closure for audit purposes and debugging

        Note: This method is idempotent - calling it multiple times on an already
        closed connection will not raise errors but will log a warning. Applications
        should avoid reusing database instances after closure; instead, create a new
        instance when needed.
        """
        if hasattr(self, '_connection') and self._connection is not None:
            if not self._connection.closed:
                try:
                    await self._connection.close()
                    logger.info("[SQL] Database connection closed successfully.")
                    if logger.getEffectiveLevel() <= logging.DEBUG:
                        logger.debug(f"[SQL] Closed connection to DB={self.dbname}, HOST={self.host}, PORT={self.port}")
                except psycopg.Error as e:
                    logger.error(f"[SQL] Error closing database connection: {type(e).__name__}")
                    if logger.getEffectiveLevel() <= logging.DEBUG:
                        logger.debug(f"[SQL] Detailed error: {e}")
                    raise ConnectionError(f"Failed to close database connection: {str(e)}") from e
            else:
                logger.warning("[SQL] Attempted to close an already closed database connection.")

        if hasattr(self, '_tables') and self._tables is not None:
            self._tables.clear()
            logger.debug("[SQL] Cleared internal table cache.")

        self._connection = None
        self._tables = None

        logger.info("[SQL] Database resources released successfully.")