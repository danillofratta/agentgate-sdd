from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.application.exceptions.not_found import NotFound
from agentgate.transport.configure import configure_http


def test_concealed_not_found_maps_to_sanitized_404():
    application = FastAPI()
    configure_http(application)

    @application.get("/probe")
    def probe():
        raise NotFound

    with TestClient(application) as client:
        response = client.get("/probe")
    assert response.status_code == 404
    assert response.json() == {"error": "NOT_FOUND"}
