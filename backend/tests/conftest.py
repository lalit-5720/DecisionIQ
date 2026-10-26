import pytest

from app.auth.deps import get_current_user
from app.core.config import settings
from app.db.models import User
from app.main import app


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """No test may touch the real database (audit entries, settings, alerts, users...)."""
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'isolated.db'}")


@pytest.fixture(autouse=True)
def fake_admin(request):
    """Most tests exercise features, not login: they run as an Admin. Mark a test `real_auth` to use real JWT authentication."""
    if request.node.get_closest_marker("real_auth"):
        yield
        return
    app.dependency_overrides[get_current_user] = lambda: User(id=0, email="test.admin@example.com", full_name="Test Admin", role="Admin", password_hash="", active=True)
    yield
    app.dependency_overrides.pop(get_current_user, None)
