from sqlalchemy import (
    create_engine,
    Column,
    String,
    Boolean,
    DateTime,
    BigInteger,
    Text,
    MetaData,
    Table,
    text,
    insert,
    update,
    select,
    and_,
    or_,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import sessionmaker, scoped_session

import os
from typing import List, Dict, Any, Optional, Union
from contextlib import contextmanager


class DatabaseHandler:
    """
    Handles a database connection for a guild

    Supports MySQL and SQLlite 3
    """

    def __init__(
        self,
        db_name: str,
        buffer_size: int = 100,
        backend: str = "sqlite",
        data_path: str = ".",
        username: Union[str, None] = None,
        password: Union[str, None] = None,
        host: Union[str, None] = None,
        port: Union[str, None] = None,
    ):
        self.backend = backend
        if backend == "sqlite":
            args = {"database": db_name, "data_path": data_path}
        elif backend == "mysql":
            args = {
                "database": db_name,
                "username": username,
                "password": password,
                "host": host,
                "port": port,
            }
        else:
            raise AttributeError("Backend must be mysql or sqlite!")

        self.engine = self._create_engine(**args)
        self.metadata = MetaData()
        self.SessionFactory = sessionmaker(bind=self.engine)
        self.scoped_session = scoped_session(self.SessionFactory)
        self.buffer_session = self.scoped_session()

        self.tables = {
            "messages": self.message_columns,
            "audit": self.audit_channel_columns,
            "voice": self.voice_channel_columns,
            "attachments": self.attachments_columns,  # store attachments and stickers in messages
        }
        self.metadata.reflect(bind=self.engine)

        for table, cols in self.tables.items():
            self._create_table(table, cols)

        self.insert_buffer: Dict[str, List[Dict[str, Any]]] = {}  # {table_name: [rows]}
        self.update_buffer: Dict[str, List[Dict[str, Any]]] = {}
        self.safe_insert_buffer: Dict[str, List[Dict[str, Any]]] = {}  # used only for syncing
        self.buffer_threshold: int = buffer_size  # Can be adjusted

    def close(self):
        self.flush_all()
        self.buffer_session.close()
        self.scoped_session.remove()
        self.engine.dispose()

    @property
    def message_columns(self) -> List[Column]:
        text = Text if self.backend == "sqlite" else LONGTEXT
        return [
            Column("message_id", BigInteger, primary_key=True),
            Column("channel_id", BigInteger, nullable=False, index=True),
            Column("author_id", BigInteger, nullable=False, index=True),
            Column("datetime", DateTime(), nullable=False, index=True),
            Column("edited_datetime", DateTime()),
            Column("content", text),
            Column("edited_content", text),
            Column("reference_id", BigInteger),
            Column("deleted_by_id", BigInteger),
            # Column("attachments", text),
        ]

    @property
    def audit_channel_columns(self) -> List[Column]:
        text = Text if self.backend == "sqlite" else LONGTEXT
        return [
            Column("id", BigInteger, primary_key=True),
            Column("datetime", DateTime(), nullable=False, index=True),
            Column("action", String(200)),
            Column("category", String(500)),
            Column("author_id", BigInteger, nullable=False, index=True),
            Column("attribute", String(500)),
            Column("before", text),
            Column("after", text),
            Column("extra", text),
            Column("reason", text),
        ]

    @property
    def voice_channel_columns(self) -> List[Column]:
        return [
            Column("datetime", DateTime(), primary_key=True),
            Column("author_id", BigInteger, nullable=False, index=True),
            Column("channel_id", BigInteger, nullable=False, index=True),
            Column("action_type", String(200)),
            Column("state", Boolean),
            Column("moved_to_id", BigInteger),
        ]

    @property
    def attachments_columns(self) -> List[Column]:
        text = Text if self.backend == "sqlite" else LONGTEXT
        return [
            Column("id", BigInteger, primary_key=True),
            Column("message_id", BigInteger, nullable=False, index=True),
            Column("url", text),
            Column("filepath", String(500)),
        ]

    @contextmanager
    def session_scope(self):
        session = self._get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            self.scoped_session.remove()

    def _get_session(self):
        return self.scoped_session()

    def _create_mysql_database_if_not_exists(self, **kwargs):
        user = kwargs["username"]
        password = kwargs["password"]
        host = kwargs.get("host", "localhost")
        db_name = kwargs["database"]
        port = kwargs["port"]
        temp_engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}")
        with temp_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{db_name}`"))

    def _create_engine(self, **kwargs):
        if self.backend == "sqlite":
            db_path = kwargs["data_path"]
            database = kwargs["database"]
            return create_engine(f"sqlite:///{os.path.join(db_path, database)}.db", echo=False)
        elif self.backend == "mysql":
            user = kwargs["username"]
            password = kwargs["password"]
            host = kwargs.get("host", "localhost")
            port = kwargs["port"]
            db_name = kwargs["database"]
            self._create_mysql_database_if_not_exists(**kwargs)
            return create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{db_name}", echo=False)
        else:
            raise ValueError("Unsupported backend")

    def _create_table(self, name: str, columns: List[Column]):
        if name in self.metadata.tables:
            return
        table = Table(name, self.metadata, *columns)
        table.create(self.engine, checkfirst=True)

    def _buffer_insert(self, table_name: str, row_dict: dict, buffer: str = "insert"):
        """
        Buffer a row for Core-based bulk insert

        Args:
            table_name (str): _description_
            row_dict (dict): _description_

        Raises:
            ValueError: _description_
        """
        if table_name not in self.tables:
            raise ValueError(f"Table '{table_name}' does not exist.")

        if buffer == "insert":
            working_buffer = self.insert_buffer
        else:
            working_buffer = self.update_buffer

        if table_name not in working_buffer:
            working_buffer[table_name] = []

        working_buffer[table_name].append(row_dict)

        if len(working_buffer[table_name]) >= self.buffer_threshold:
            self._flush_table(table_name)

    def _flush_table(self, table_name: str):
        """
        Flush buffer using Core insert

        Args:
            table_name (str): _description_
            buffer (str, optional): _description_. Defaults to "insert".
        """
        table = self.metadata.tables[table_name]
        for buffer, working_buffer in {"insert": self.insert_buffer, "update": self.update_buffer}.items():
            if table_name not in working_buffer or not working_buffer[table_name]:
                continue

            try:
                if buffer == "insert":
                    statement = insert(table)
                    self.buffer_session.execute(statement, working_buffer[table_name])
                    self.buffer_session.commit()
                else:
                    # pull out primary key from data
                    primary_keys = [col.name for col in table.primary_key.columns]
                    with self.buffer_session.begin():
                        for row in working_buffer[table_name]:
                            where_clause = and_(*[table.c[pk] == row[pk] for pk in primary_keys])
                            # Build values to update (excluding PKs)
                            update_values = {k: v for k, v in row.items() if k not in primary_keys}

                            statement = update(table).where(where_clause).values(**update_values)
                            self.buffer_session.execute(statement)
                working_buffer[table_name] = []
            except Exception as e:
                self.buffer_session.rollback()
                print(f"Error during buffered {buffer} to '{table_name}': {e}")
                print("Deleting buffer.")
                working_buffer[table_name] = []

    def safe_insert(self, table_name: str, data: dict):
        if table_name not in self.tables:
            raise ValueError(f"Table '{table_name}' not found.")

        if table_name not in self.safe_insert_buffer:
            self.safe_insert_buffer[table_name] = []

        self.safe_insert_buffer[table_name].append(data)

        if len(self.safe_insert_buffer[table_name]) >= self.buffer_threshold:
            table = self.metadata.tables[table_name]

            insert_stmt = insert(table)

            # SQLite: ON CONFLICT DO NOTHING
            if self.backend == "sqlite":
                insert_stmt = insert_stmt.prefix_with("OR IGNORE")

            # MySQL / MariaDB:
            elif self.backend == "mysql":
                insert_stmt = insert_stmt.prefix_with("IGNORE")

            try:
                self.buffer_session.execute(insert_stmt, self.safe_insert_buffer[table_name])
                self.buffer_session.commit()
                self.safe_insert_buffer[table_name] = []
            except Exception as e:
                self.buffer_session.rollback()
                print(f"Error during safe buffered insert to '{table_name}': {e}")
                print("Deleting buffer.")
                self.safe_insert_buffer[table_name] = []

    def flush_all(self):
        for table_name in list(self.tables.keys()):
            self._flush_table(table_name)

    # === Insert and Update ===
    def insert(self, table_name: str, data: dict):
        if table_name not in self.tables:
            raise ValueError(f"Table '{table_name}' not found.")
        self._buffer_insert(table_name, data)

    def update(self, table_name: str, data: dict):
        if table_name not in self.tables:
            raise ValueError(f"Table '{table_name}' not found.")
        self._buffer_insert(table_name, data, buffer="update")

    def query(self, table_name: str, columns: List[str] = [], filters: Optional[Dict[str, Any]] = {}) -> List[dict]:
        """
        Query a table with advanced filters.

        Args:
            table_name (str): The table to query.
            columns: (List[str]): A list of columns to select.
            filters (Dict[str, Any]): A dictionary of column filters.
                Value can be:
                - A direct value (for equality)
                - A dict with operators like {'in': [...]}, {'gte': x}, {'lt': x}

        Returns:
            List[dict]: A list of matching rows.
        """
        if table_name not in self.tables:
            raise ValueError(f"Table '{table_name}' not found.")

        # flush table buffer
        self._flush_table(table_name)

        table = self.metadata.tables[table_name]
        conditions = []

        if columns:
            for col in columns:
                if col not in table.c:
                    raise ValueError(f"Column '{col}' does not exist in table '{table_name}'.")
            selected_columns = [table.c[col] for col in columns]
        else:
            selected_columns = [table]  # This includes all columns

        if "or" in filters:
            or_clauses = []
            for or_filter in filters["or"]:
                or_subconditions = []
                for or_col, or_val in or_filter.items():
                    if or_col not in table.c:
                        raise ValueError(f"Column '{or_col}' does not exist in table '{table_name}'.")

                    column = table.c[or_col]

                    # Handle nested operators
                    if isinstance(or_val, dict):
                        for op, val in or_val.items():
                            if op == "eq":
                                or_subconditions.append(column == val)
                            elif op == "ne":
                                or_subconditions.append(column != val)
                            elif op == "lt":
                                or_subconditions.append(column < val)
                            elif op == "lte":
                                or_subconditions.append(column <= val)
                            elif op == "gt":
                                or_subconditions.append(column > val)
                            elif op == "gte":
                                or_subconditions.append(column >= val)
                            elif op == "in":
                                or_subconditions.append(column.in_(val))
                            elif op == "nin":
                                or_subconditions.append(~column.in_(val))
                            elif op == "like":
                                or_subconditions.append(column.like(val))
                            else:
                                raise ValueError(f"Unsupported filter operation '{op}' in OR block.")
                    else:
                        or_subconditions.append(column == or_val)

                or_clauses.append(and_(*or_subconditions))
            conditions.append(or_(*or_clauses))

        for col_name, condition in filters.items():
            if col_name == "or":
                continue
            if col_name not in table.c:
                raise ValueError(f"Column '{col_name}' does not exist in table '{table_name}'.")

            column = table.c[col_name]

            # === Simple equality ===
            if not isinstance(condition, dict):
                conditions.append(column == condition)
                continue

            # === Advanced conditions ===
            for op, val in condition.items():
                if op == "eq":
                    conditions.append(column == val)
                elif op == "ne":
                    conditions.append(column != val)
                elif op == "lt":
                    conditions.append(column < val)
                elif op == "lte":
                    conditions.append(column <= val)
                elif op == "gt":
                    conditions.append(column > val)
                elif op == "gte":
                    conditions.append(column >= val)
                elif op == "in":
                    conditions.append(column.in_(val))
                elif op == "nin":
                    conditions.append(~column.in_(val))
                elif op == "like":
                    conditions.append(column.like(val))
                else:
                    raise ValueError(f"Unsupported filter operation '{op}' on column '{col_name}'.")

        stmt = select(*selected_columns).where(and_(*conditions)) if conditions else select(*selected_columns)
        try:
            with self.session_scope() as session:
                results = session.execute(stmt).fetchall()
                return [dict(row._mapping) for row in results]
        except Exception as e:
            print(f"Query error for table '{table_name}': {e}")
            return []
