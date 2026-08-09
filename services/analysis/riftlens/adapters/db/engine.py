from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from riftlens.adapters.db.loaders import RuleDefinitionLoader, TaxonomyLoader
from riftlens.config import Settings

ANALYSIS_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = ANALYSIS_ROOT / "alembic.ini"


class SchemaTooNewError(RuntimeError):
    """Raised when the on-disk Alembic revision is unknown to this binary."""


def sqlite_url(path: Path) -> str:
    """Return a SQLAlchemy SQLite URL. Assumes ``path`` is a filesystem location."""
    return "sqlite:///" + path.resolve().as_posix()


def apply_sqlite_pragmas(engine: Engine) -> None:
    """Register connect-time PRAGMAs. Assumes ``engine`` is a SQLite engine."""

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def create_sqlite_engine(db_path: Path) -> Engine:
    """Return a file-backed SQLite engine with WAL pragmas. Assumes the parent dir exists."""
    engine = create_engine(
        sqlite_url(db_path),
        connect_args={"check_same_thread": False, "timeout": 5.0},
    )
    apply_sqlite_pragmas(engine)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a sessionmaker bound to ``engine``. Assumes the engine is already configured."""
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def alembic_config(url: str) -> Config:
    """Return Alembic config pointed at ``url``. Assumes ``alembic.ini`` exists."""
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ANALYSIS_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def assert_schema_compatible(engine: Engine) -> None:
    """Refuse to start when the DB revision is newer than this binary.

    Assumes Alembic metadata is readable. An empty database (no revision) is allowed.
    """
    cfg = alembic_config(engine.url.render_as_string(hide_password=False))
    script = ScriptDirectory.from_config(cfg)
    known = {revision.revision for revision in script.walk_revisions()}
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    if current is None:
        return
    if current not in known:
        heads = ", ".join(script.get_heads()) or "(none)"
        raise SchemaTooNewError(
            f"Database schema revision {current!r} is newer than this RiftLens binary "
            f"(known heads: {heads}). Upgrade the application before opening this database."
        )


def upgrade_schema(engine: Engine) -> None:
    """Apply Alembic migrations through head. Assumes the engine URL is writable SQLite."""
    cfg = alembic_config(engine.url.render_as_string(hide_password=False))
    with engine.connect() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
        connection.commit()


def checkpoint_wal(engine: Engine) -> None:
    """Flush the WAL into the main DB file. Assumes WAL mode is active."""
    with engine.connect() as connection:
        connection.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        connection.commit()


def init_database(settings: Settings) -> Engine:
    """Create, migrate, and seed the SQLite database.

    Returns the configured engine. Assumes ``settings.data_dir`` is writable. Raises
    ``SchemaTooNewError`` when the on-disk Alembic head is newer than this binary.
    """
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.db_path)
    assert_schema_compatible(engine)
    upgrade_schema(engine)
    factory = make_session_factory(engine)
    TaxonomyLoader(factory).load()
    RuleDefinitionLoader(factory).load()
    return engine
