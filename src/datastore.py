"""One table interface, three backends.

The whole point of this module is that `generate_data`, `matching`,
`households` and the Streamlit app never learn where the data actually lives.
That is what lets the identical engine run on a laptop and inside Databricks.

    LocalStore   parquet files on disk          local pipeline, local app
    SparkStore   Unity Catalog Delta via Spark  the Databricks notebooks
    SqlStore     Unity Catalog via DBSQL        the deployed Databricks App

Pick one with `get_store()`; it reads the environment and decides.
"""

from __future__ import annotations

import os
import glob
import shutil
from typing import Iterable

import pandas as pd

from . import config


class BaseStore:
    """Every backend returns and accepts pandas DataFrames."""

    kind = "base"

    def qualified_name(self, table: str) -> str:
        raise NotImplementedError

    def exists(self, table: str) -> bool:
        raise NotImplementedError

    def read(self, table: str) -> pd.DataFrame:
        raise NotImplementedError

    def write(self, table: str, df: pd.DataFrame) -> None:
        """Replace the table contents."""
        raise NotImplementedError

    def append(self, table: str, df: pd.DataFrame) -> None:
        raise NotImplementedError

    def append_row(self, table: str, row: dict) -> None:
        self.append(table, pd.DataFrame([row]))

    def read_or_empty(self, table: str, columns: Iterable[str] = ()) -> pd.DataFrame:
        if self.exists(table):
            return self.read(table)
        return pd.DataFrame(columns=list(columns))

    def drop(self, table: str) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Local parquet
# ---------------------------------------------------------------------------
class LocalStore(BaseStore):
    """Flat parquet files named `<schema>__<table>.parquet`.

    Append does read-concat-write. That is wasteful in general and completely
    fine at POC volumes, and it keeps the local mode dependency free.
    """

    kind = "local"

    def __init__(self, data_dir: str | None = None):
        self.data_dir = data_dir or config.LOCAL_DATA_DIR
        os.makedirs(self.data_dir, exist_ok=True)

    def _schema(self, table: str) -> str:
        return config.TABLE_SCHEMA.get(table, "gold")

    def qualified_name(self, table: str) -> str:
        return f"{self._schema(table)}.{table}"

    def _path(self, table: str) -> str:
        return os.path.join(self.data_dir, f"{self._schema(table)}__{table}.parquet")

    def exists(self, table: str) -> bool:
        return os.path.exists(self._path(table))

    def read(self, table: str) -> pd.DataFrame:
        path = self._path(table)
        if not os.path.exists(path):
            raise FileNotFoundError(f"{self.qualified_name(table)} has not been written yet")
        return pd.read_parquet(path)

    def write(self, table: str, df: pd.DataFrame) -> None:
        df.to_parquet(self._path(table), index=False)

    def append(self, table: str, df: pd.DataFrame) -> None:
        if df.empty:
            return
        if self.exists(table):
            existing = self.read(table)
            df = pd.concat([existing, df], ignore_index=True)
        self.write(table, df)

    def drop(self, table: str) -> None:
        path = self._path(table)
        if os.path.exists(path):
            os.remove(path)

    def drop_all(self) -> int:
        removed = 0
        for path in glob.glob(os.path.join(self.data_dir, "*.parquet")):
            os.remove(path)
            removed += 1
        return removed

    def reset_dir(self) -> None:
        if os.path.isdir(self.data_dir):
            shutil.rmtree(self.data_dir)
        os.makedirs(self.data_dir, exist_ok=True)


# ---------------------------------------------------------------------------
# Spark / Unity Catalog, used inside the notebooks
# ---------------------------------------------------------------------------
class SparkStore(BaseStore):
    """Delta tables in a Unity Catalog catalog, through an active SparkSession."""

    kind = "spark"

    def __init__(self, catalog: str | None = None, spark=None):
        self.catalog = catalog or config.DEMO_CATALOG
        if spark is None:
            from pyspark.sql import SparkSession  # imported lazily, notebook only
            spark = SparkSession.getActiveSession() or SparkSession.builder.getOrCreate()
        self.spark = spark

    def _schema(self, table: str) -> str:
        return config.TABLE_SCHEMA.get(table, "gold")

    def qualified_name(self, table: str) -> str:
        return f"`{self.catalog}`.{self._schema(table)}.{table}"

    def ensure_schemas(self) -> None:
        for schema in config.SCHEMAS:
            self.spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{self.catalog}`.{schema}")

    def exists(self, table: str) -> bool:
        return self.spark.catalog.tableExists(
            f"{self.catalog}.{self._schema(table)}.{table}"
        )

    def read(self, table: str) -> pd.DataFrame:
        return self.spark.table(
            f"{self.catalog}.{self._schema(table)}.{table}"
        ).toPandas()

    def write(self, table: str, df: pd.DataFrame) -> None:
        self.ensure_schemas()
        sdf = self.spark.createDataFrame(_stringify_objects(df))
        (sdf.write.mode("overwrite")
            .option("overwriteSchema", "true")
            .saveAsTable(f"{self.catalog}.{self._schema(table)}.{table}"))

    def append(self, table: str, df: pd.DataFrame) -> None:
        if df.empty:
            return
        self.ensure_schemas()
        sdf = self.spark.createDataFrame(_stringify_objects(df))
        (sdf.write.mode("append")
            .saveAsTable(f"{self.catalog}.{self._schema(table)}.{table}"))

    def drop(self, table: str) -> None:
        self.spark.sql(
            f"DROP TABLE IF EXISTS {self.catalog}.{self._schema(table)}.{table}"
        )


# ---------------------------------------------------------------------------
# Databricks SQL Warehouse, used by the deployed App
# ---------------------------------------------------------------------------
class SqlStore(BaseStore):
    """Read and append over a SQL Warehouse connection.

    The App runs as its own service principal, so no token appears here. The
    Databricks SDK supplies credentials from the App environment.
    """

    kind = "sql"

    def __init__(self, catalog: str | None = None):
        from databricks import sql as dbsql           # lazy, Databricks only
        from databricks.sdk.core import Config

        self._dbsql = dbsql
        cfg = Config()
        host = (cfg.host or "").removeprefix("https://").removeprefix("http://")
        http_path = resolve_http_path()
        if not host:
            raise RuntimeError(
                "No workspace host. On Databricks Apps this is supplied "
                "automatically; set DATABRICKS_HOST only when running outside."
            )
        if not http_path:
            raise RuntimeError(
                "No SQL Warehouse configured. Bind a warehouse to the App as a "
                "resource, or set DATABRICKS_HTTP_PATH (full HTTP path) or "
                "DATABRICKS_WAREHOUSE_ID (bare id)."
            )
        self.http_path = http_path
        self.catalog = catalog or config.DEMO_CATALOG
        self._conn = dbsql.connect(
            server_hostname=host,
            http_path=http_path,
            credentials_provider=lambda: cfg.authenticate,
        )

    def _schema(self, table: str) -> str:
        return config.TABLE_SCHEMA.get(table, "gold")

    def qualified_name(self, table: str) -> str:
        return f"`{self.catalog}`.{self._schema(table)}.{table}"

    def query(self, sql_text: str, params: list | None = None) -> pd.DataFrame:
        with self._conn.cursor() as cur:
            cur.execute(sql_text, parameters=params)
            cols = [c[0] for c in cur.description or []]
            return pd.DataFrame(cur.fetchall(), columns=cols)

    def exists(self, table: str) -> bool:
        try:
            self.query(f"SELECT 1 FROM {self.qualified_name(table)} LIMIT 1")
            return True
        except Exception:
            return False

    def read(self, table: str) -> pd.DataFrame:
        return self.query(f"SELECT * FROM {self.qualified_name(table)}")

    def write(self, table: str, df: pd.DataFrame) -> None:
        raise RuntimeError(
            "The App does not rewrite published tables. Run notebook 02 to publish."
        )

    def append(self, table: str, df: pd.DataFrame) -> None:
        if df.empty:
            return
        cols = list(df.columns)
        placeholders = ", ".join(["?"] * len(cols))
        stmt = (
            f"INSERT INTO {self.qualified_name(table)} "
            f"({', '.join(cols)}) VALUES ({placeholders})"
        )
        with self._conn.cursor() as cur:
            for _, row in df.iterrows():
                cur.execute(stmt, parameters=[_sql_value(v) for v in row.tolist()])

    def drop(self, table: str) -> None:
        raise RuntimeError("The App is not allowed to drop tables.")


# ---------------------------------------------------------------------------
# Helpers and factory
# ---------------------------------------------------------------------------
def _stringify_objects(df: pd.DataFrame) -> pd.DataFrame:
    """Spark cannot infer python lists/dicts reliably; send them as strings."""
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object:
            sample = out[col].dropna()
            if len(sample) and isinstance(sample.iloc[0], (list, dict, tuple, set)):
                out[col] = out[col].map(lambda v: "" if v is None else str(v))
    return out


def _sql_value(value):
    if isinstance(value, (list, dict, tuple, set)):
        return str(value)
    if pd.isna(value):
        return None
    return value


def resolve_http_path() -> str:
    """Work out the warehouse HTTP path from whatever the environment gives.

    This exists because of one easy-to-miss detail in Databricks Apps. When you
    bind a SQL Warehouse as an app resource and reference it with `valueFrom`,
    the value injected is the warehouse **id**, not its HTTP path. Passing that
    id straight to `sql.connect(http_path=...)` fails with an error that does
    not mention the warehouse at all.

    So: accept a full path, a bare id, or a `/sql/1.0/endpoints/...` legacy
    path, and normalise. Checked in order, first non-empty wins.
    """
    candidates = [
        os.environ.get("DATABRICKS_HTTP_PATH", ""),
        os.environ.get("DATABRICKS_WAREHOUSE_ID", ""),
        os.environ.get("DATABRICKS_SQL_WAREHOUSE_ID", ""),
    ]
    for value in candidates:
        value = (value or "").strip()
        if not value:
            continue
        if value.startswith("/"):
            return value                       # already a path
        if "/" in value:
            return "/" + value.lstrip("/")     # path missing its leading slash
        return f"/sql/1.0/warehouses/{value}"  # bare warehouse id
    return ""


def running_in_databricks() -> bool:
    return bool(os.environ.get("DATABRICKS_RUNTIME_VERSION"))


def spark_available() -> bool:
    try:
        from pyspark.sql import SparkSession
        return SparkSession.getActiveSession() is not None
    except Exception:
        return False


def get_store(prefer: str | None = None) -> BaseStore:
    """Choose a backend.

    `EB_STORE` wins if set (local | spark | sql). Otherwise: Spark session
    present means notebook, Databricks App environment means SQL, and the
    fallback is local parquet.
    """
    choice = (prefer or os.environ.get("EB_STORE") or "").strip().lower()
    if choice == "local":
        return LocalStore()
    if choice == "spark":
        return SparkStore()
    if choice == "sql":
        return SqlStore()

    if spark_available():
        return SparkStore()
    if resolve_http_path() and os.environ.get("DATABRICKS_HOST"):
        return SqlStore()
    return LocalStore()
