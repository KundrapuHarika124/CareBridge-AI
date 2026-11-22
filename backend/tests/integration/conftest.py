"""Integration test setup. These tests need a real PostgreSQL database.

Set TEST_DATABASE_URL to an EMPTY, DISPOSABLE database (every table in it is dropped):

    TEST_DATABASE_URL=postgresql+psycopg://carebridge:carebridge@localhost:5432/carebridge_test pytest

Without it, the tests in this folder are not collected at all. SQLite is not supported: the behaviour
under test (row locks, partial unique indexes) does not exist there.
"""
import os
from urllib.parse import urlparse

import pytest

TEST_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_URL:
    parsed_test_url = urlparse(TEST_URL)
    test_database = parsed_test_url.path.lstrip("/")
    if test_database != "carebridge_test":
        raise RuntimeError(
            "Integration tests require TEST_DATABASE_URL to target database "
            "'carebridge_test'; refusing to use any other database."
        )
    # Must be set before any application module is imported.
    os.environ["DATABASE_URL"] = TEST_URL
    os.environ["APP_ENV"] = "test"
    os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-test-only-secret-key-0123456789"
    os.environ["LLM_PROVIDER"] = "none"
    os.environ["SPEECH_PROVIDER"] = "none"
    os.environ["RUN_JOBS"] = "false"


# Without a test database the test modules are not even imported, so `pytest` on a machine
# with no database reports only the unit tests rather than failing during collection.
collect_ignore_glob = [] if TEST_URL else ["test_*.py"]


def pytest_report_header(config):
    if not TEST_URL:
        return "integration tests NOT COLLECTED: TEST_DATABASE_URL is not set (they need PostgreSQL)"
    return "integration tests enabled against TEST_DATABASE_URL"


@pytest.fixture(scope="session")
def _schema():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect, text

    from app.core.database import Base, engine
    import app.models  # noqa: F401

    def assert_test_database() -> None:
        with engine.connect() as connection:
            database = connection.execute(text("SELECT current_database()")).scalar_one()
            if database != "carebridge_test":
                raise RuntimeError(
                    "REFUSED: database-changing integration fixture operation "
                    "detected a database other than 'carebridge_test'."
                )

    assert_test_database()
    alembic_config = Config("alembic.ini")

    inspector = inspect(engine)
    application_tables = set(Base.metadata.tables) & set(
        inspector.get_table_names(schema="public")
    )
    if application_tables:
        command.downgrade(alembic_config, "base")
        assert_test_database()

    revision_row = None
    with engine.connect() as connection:
        has_version_table = inspector.has_table("alembic_version", schema="public")
        if has_version_table:
            revision_row = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
    if revision_row is not None and revision_row not in ("", "base"):
        # Clean stale migration state after a previous create_all/drop_all run.
        command.stamp(alembic_config, "base")
        assert_test_database()

    command.upgrade(alembic_config, "head")
    assert_test_database()

    yield

    from app.core.database import SessionLocal

    assert_test_database()
    cleanup = SessionLocal()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            cleanup.execute(table.delete())
        cleanup.commit()
    finally:
        cleanup.close()


@pytest.fixture()
def db(_schema):
    """A session on a database emptied before each test, with limiters and providers reset."""
    from app.core import ratelimit
    from app.core.database import Base, engine, SessionLocal
    from app.integrations import email, llm, speech
    from sqlalchemy import text

    def assert_test_database() -> None:
        with engine.connect() as connection:
            database = connection.execute(text("SELECT current_database()")).scalar_one()
            if database != "carebridge_test":
                raise RuntimeError(
                    "REFUSED: database cleanup fixture detected a database "
                    "other than 'carebridge_test'."
                )

    session = SessionLocal()
    try:
        assert_test_database()
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
    except Exception:
        session.rollback()
        session.close()
        raise

    for limiter in ratelimit.ALL_LIMITERS:
        limiter.reset()
    llm.set_llm(llm.NoneLLM())
    speech.set_speech(speech.NoneSpeech())
    email.set_email(email.MockEmail())
    try:
        yield session
    finally:
        original_error = None
        try:
            session.rollback()
        except Exception as exc:
            original_error = exc
        try:
            session.close()
        except Exception as exc:
            if original_error is None:
                original_error = exc

        assert_test_database()
        cleanup = SessionLocal()
        try:
            for table in reversed(Base.metadata.sorted_tables):
                cleanup.execute(table.delete())
            cleanup.commit()
        except Exception:
            cleanup.rollback()
            raise
        finally:
            cleanup.close()
        if original_error is not None:
            raise original_error


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def world(db):
    from tests.integration.helpers import build_world

    return build_world(db)
