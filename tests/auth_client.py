from fastapi.testclient import TestClient


class OwnerClient(TestClient):
    """Existing API regressions now run with a legitimately authenticated owner."""

    def __init__(self, app, *args, **kwargs):
        password = "synthetic-owner-test-passphrase"
        if not app.state.auth.configured():
            app.state.auth.initialize(password)
        token = app.state.auth.issue("owner", password)
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = "Bearer " + token
        super().__init__(app, *args, headers=headers, **kwargs)
