from app.main import app
from fastapi.testclient import TestClient


def test_health_ok():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


def test_openapi_served():
    info = TestClient(app).get("/openapi.json").json()["info"]
    assert info["title"] == "VYNZO API"
