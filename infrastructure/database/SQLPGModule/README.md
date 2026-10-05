# SQLPGModule Documentation

## Overview

The **SQLPGModule** represents a **data access layer** designed for high-performance interaction with PostgreSQL databases in Telegram bot applications. Built following Clean Architecture principles, it provides a safe, ORM-like interface while maintaining direct control over SQL operations.

This module contains:
- **Table**: High-level wrapper for single table operations (CRUD, metadata)
- **DataBase**: Database manager with schema inspection, table caching, and connection pooling
- **Enums**: Domain-specific types and statuses for type safety

All components are designed to be **infrastructure-aware but framework-agnostic**, making them reusable across different application layers.

The module ensures:
- ✅ Protection against SQL injection
- ✅ High performance under load (200k+ users/day)
- ✅ Automatic primary key detection
- ✅ Connection and metadata caching
- ✅ Full type safety and IDE support

---

### Folder structure

|-> `foundation/`
&nbsp;&nbsp;&nbsp;&nbsp; ∟ `SQLPGModule/`
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ∟ `table.py` - Table-level operations and CRUD interface. [Learn more.](#tablepy)  
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ∟ `base.py` - Database-level operations and schema management. [Learn more.](#databasepy)  
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ∟ `enums.py` - PostgreSQL type definitions and status enumerations. [Learn more.](#enumspy)  

---

### [foundation](foundation) / [SQLPGModule](SQLPGModule) / [base.py](base.py)
><details><summary>Class `DataBase` - High-level asynchronous wrapper for PostgreSQL database management.</summary><p>
>
>* `__init__()`: [None](#databasepy) - Initializes database connection parameters without establishing connection. ✅  
>* `__len__()`: [int](#databasepy) - Returns count of tables in the 'public' schema cache. ✅  
>* `__str__()`: [str](#databasepy) - Returns human-readable overview of database tables, counts, and status. ✅  
>* `__enter__()`: [`DataBase`](#databasepy) - _Magic method_ for context manager support (returns self). ✅  
>* `__exit__()`: [None](#databasepy) - _Magic method_ that cleans up database connection on context exit. ✅  
>* `dbname`: [str](#databasepy) - _Property_ for getting/setting database name with validation (1-MAX_LEN chars). ✅  
>* `user`: [str](#databasepy) - _Property_ for getting/setting username with validation (1-MAX_LEN chars). ✅  
>* `password`: [str](#databasepy) - _Property_ for getting/setting password with validation (1-MAX_LEN chars). ✅  
>* `host`: [str](#databasepy) - _Property_ for getting/setting host address with validation (1-MAX_LEN chars). ✅  
>* `port`: [int](#databasepy) - _Property_ for getting/setting port number with validation (non-negative). ✅  
>* `tables`: [List[Table]](#databasepy) - _Property_ returning all cached Table instances for 'public' schema. ✅  
>* `table_names`: [List[str]](#databasepy) - _Property_ returning names of all tables in 'public' schema cache. ✅  
>* `is_connected`: [bool](#databasepy) - _Property_ verifying active and responsive database connection. ✅  
>* `create()`: [`DataBase`](#databasepy) - Class method factory for async initialization and connection setup. ✅  
>* `create_database()`: [bool](#databasepy) - Creates database if it doesn't exist (requires superuser privileges). ✅  
>* `create_role()`: [None](#databasepy) - Creates database role with validated inputs and secure password handling. ✅  
>* `add_table()`: [None](#databasepy) - Creates new table with proper identifier quoting to prevent SQL injection. ✅  
>* `get_table()`: [`Table`](#databasepy) - Retrieves cached Table instance by name with connection verification. ✅  
>* `delete_table()`: [None](#databasepy) - Drops table with CASCADE and updates internal cache (destructive operation). ✅  
>* `execute_admin_command()`: [bool](#databasepy) - Executes administrative commands using system 'postgres' database. ✅  
>* `connect()`: [None](#databasepy) - Establishes connection and initializes metadata cache (called by create()). ✅  
>* `_load_all_tables()`: [Dict[str, Table]](#databasepy) - Internal method loading tables with primary keys into cache. ✅  
>* `_get_tables_names()`: [List[str]](#databasepy) - Internal method retrieving table names from information_schema. ✅  
>* `_create_cursor()`: [None](#databasepy) - Internal method establishing secure database connection with keepalives. ✅  
>* `_database_exists()`: [bool](#databasepy) - Internal method checking database existence via system catalog. ✅  
>* `_ensure_connection()`: [None](#databasepy) - Internal method verifying/restoring connection with auto-recovery. ✅  
>* `_escape_string()`: [str](#databasepy) - Internal method safely escaping strings using PostgreSQL's quote_literal(). ✅  
>* `_set_str_cmd_clr()`: [str](#databasepy) - Static method applying ANSI color codes for CLI output formatting. ✅  
>
></p></details>


### [foundation](foundation) / [SQLPGModule](SQLPGModule) / [table.py](table.py)
><details><summary>Class `Table` - High-level asynchronous wrapper for PostgreSQL table operations with built-in security.</summary><p>
>
>* `__init__()`: [None](#tablepy) - Initializes Table wrapper with connection, name, and primary key with strict validation. ✅  
>* `connection`: [`AsyncConnection`](#tablepy) - _Property_ for getting/setting database connection with type validation. ✅  
>* `table_name`: [str](#tablepy) - _Property_ for getting/setting table name with validation (non-empty string). ✅  
>* `primary_key`: [str](#tablepy) - _Property_ for getting/setting primary key column name with validation (non-empty string). ✅  
>* `column_names`: [List[str]](#tablepy) - _Property_ returning cached column names in ordinal position order. ✅  
>* `count`: [int](#tablepy) - _Property_ executing COUNT(*) query to determine row count. ✅  
>* `status`: [`Status`](#enumspy) - _Property_ returning ENABLE if table has rows, EMPTY otherwise. ✅  
>* `columns_count`: [int](#tablepy) - _Property_ returning number of columns in the table. ✅  
>* `create_table()`: [None](#tablepy) - Creates table with validated inputs and proper identifier quoting to prevent SQL injection. ✅  
>* `get_from_cell()`: [Any](#tablepy) - Retrieves single cell value with comprehensive validation and parameterized queries. ✅  
>* `set_to_cell()`: [None](#tablepy) - Updates single cell value with comprehensive validation and parameterized queries. ✅  
>* `add_row()`: [None](#tablepy) - Inserts new row with validated column names and parameterized values. ✅  
>* `get_row()`: [Dict[str, Any]](#tablepy) - Retrieves full row by key with comprehensive validation. ✅  
>* `get_rows()`: [List[Dict[str, Any]]](#tablepy) - Efficiently fetches multiple rows in one query (eliminates N+1 problem). ✅  
>* `delete_row()`: [None](#tablepy) - Deletes row by key with comprehensive validation (destructive operation). ✅  
>* `get_column()`: [List[Any]](#tablepy) - Retrieves all values from specified column with validation. ✅  
>* `get_all_keys()`: [List[Any]](#tablepy) - Retrieves all primary key values with validation. ✅  
>* `get_keys_by_column()`: [List[Any]](#tablepy) - Retrieves primary keys where column matches value with validation. ✅  
>* `show()`: [str](#tablepy) - Returns pretty-printed table preview for debugging with pagination support. ✅  
>* `commit()`: [None](#tablepy) - Commits current transaction to the database. ✅  
>* `set_cache_size()`: [None](#tablepy) - Configures PostgreSQL work_mem parameter for current session. ✅  
>* `command()`: [Any](#tablepy) - Executes raw SQL (highly dangerous - for debugging only). ✅  
>* `get_column_names()`: [List[str]](#tablepy) - Fetches column names from information_schema with schema restriction. ✅  
>* `autodetect_primary_key()`: [str](#tablepy) - Determines primary key from metadata or validates provided one. ✅  
>
></p></details>

---

### [foundation](foundation) / [SQLPGModule](SQLPGModule) / [enums.py](enums.py)
><details><summary>Enum `DBType` - Comprehensive PostgreSQL data type definitions.</summary><p>
>
>* **Numeric Types**  
>  `SMALLINT`, `INTEGER`, `BIGINT`, `DECIMAL`, `NUMERIC`, `REAL`, `DOUBLE_PRECISION`,  
>  `SERIAL`, `BIGSERIAL`, `SMALLSERIAL` - Integer and floating-point types with auto-increment variants  
>
>* **Character/String Types**  
>  `CHAR`, `VARCHAR`, `TEXT` - Fixed-length, variable-length, and unlimited text storage  
>
>* **Boolean Type**  
>  `BOOLEAN` - Logical true/false values  
>
>* **Date/Time Types**  
>  `DATE`, `TIME`, `TIMESTAMP`, `TIMESTAMPTZ` (timestamp with timezone), `INTERVAL` - Temporal data types  
>
>* **Monetary Type**  
>  `MONEY` - Currency amount with locale-aware formatting  
>
>* **UUID Type**  
>  `UUID` - Universally Unique Identifiers storage  
>
>* **JSON Types**  
>  `JSON`, `JSONB` - JSON data storage (text vs binary format)  
>
>* **Network Address Types**  
>  `INET`, `CIDR`, `MACADDR` - IPv4/IPv6, network blocks, and MAC addresses  
>
>* **Array Types**  
>  `INTEGER_ARRAY`, `TEXT_ARRAY`, `BOOLEAN_ARRAY`, `UUID_ARRAY` - Array variants of common types  
>
>* **Specialized Types**  
>  `BYTEA` (binary data), `XML`, `TSVECTOR` (text search), `TSQUERY` (text search queries)  
>
>Used for type-safe table creation with comprehensive PostgreSQL type coverage.  
>As a str-based Enum, values can be directly used in SQL queries without conversion.
>
></p></details>

><details><summary>Enum `Status` - Table operational status indicators.</summary><p>
>
>* `EMPTY` - Table exists but contains no rows (logical empty state)  
>* `ENABLE` - Table contains one or more rows (logical active state)  
>
>Used in `Table.status` property for logical state representation.  
>Unlike direct row count checks, this provides a clear semantic meaning  
>for application logic that needs to differentiate between empty and populated tables.
>
></p></details>
