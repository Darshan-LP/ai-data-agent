from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "AI Data Agent API is running.",
        "docs": "/docs",
        "health": "/health",
    }
    
def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert data["postgres_host"] == "localhost"
    assert data["postgres_db"] == "ai_data_agent"
    assert data["admin_connection"] is True
    assert data["readonly_connection"] is True
    
def test_agent_rejects_empty_question():
    response = client.post(
        "/agent/run",
        json={"question": ""},
    )

    assert response.status_code == 422
    
def test_agent_rejects_question_over_max_length():
    response = client.post(
        "/agent/run",
        json={"question": "a" * 2001},
    )

    assert response.status_code == 422
    
def test_unknown_route_returns_404():
    response = client.get("/this-route-does-not-exist")

    assert response.status_code == 404