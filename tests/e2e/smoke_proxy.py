"""Real Nginx/BFF security and independent delivery acceptance; no paid calls."""

import json
import subprocess
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "http://127.0.0.1:8080"


def main() -> None:
    config = json.loads(
        subprocess.run(
            ["docker", "compose", "config", "--format", "json"],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
        ).stdout
    )
    frontend = config["services"]["frontend"]
    bff = config["services"]["lab-bff"]
    assert not frontend.get("secrets") and not frontend.get("volumes")
    assert not frontend.get("environment") and not bff.get("ports")
    assert frontend["build"]["context"] == str(ROOT / "frontend/apps/lab-console")
    assert config["services"]["api"]["build"]["context"] == str(ROOT / "backend/services/agentgate")
    for name in ("agent_token", "approver_token", "mcp_token", "llm_api_key"):
        assert name in {item["source"] for item in bff["secrets"]}
    subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "frontend",
            "sh",
            "-c",
            "test ! -d /run/secrets && ! command -v python && ! command -v uv",
        ],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    with httpx.Client(base_url=ORIGIN, timeout=10, trust_env=False) as client:
        content = ""
        for path in ("/", "/app.js", "/style.css", "/unknown"):
            response = client.get(path)
            assert response.status_code == (404 if path == "/unknown" else 200)
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["referrer-policy"] == "no-referrer"
            assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
            content += response.text
        for name in ("agent_token", "approver_token", "mcp_token", "llm_api_key"):
            value = (ROOT / ".lab-secrets" / name).read_text().strip()
            assert not value or value not in content, "Credential exposed in browser assets"
        session = client.get("/lab/session")
        assert session.status_code == 200
        cookie = session.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
        headers = {"Origin": ORIGIN, "X-Lab-CSRF": session.json()["csrf"]}
        before = client.get("/lab/accounts").json()
        # Valid transport/CSRF reaches a missing operation, without creating business state.
        missing = "/lab/operations/00000000-0000-4000-8000-000000000001/execute"
        assert client.post(missing, headers=headers).status_code == 404
        for bad in (
            {"Host": "evil.example:8080"},
            {"Origin": "https://evil.example"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Sec-Fetch-Site": "same-site"},
            {"X-Lab-CSRF": "wrong"},
            {"Authorization": "Bearer untrusted"},
            {"Cookie": "lab_session=invalid"},
        ):
            assert (
                client.post("/lab/operations", json={}, headers={**headers, **bad}).status_code
                == 403
            )
        assert client.post("/lab/operations", json={}).status_code == 403
        assert (
            client.get(
                "/lab/session",
                headers={
                    "Forwarded": "host=evil.example;proto=https",
                    "X-Forwarded-Host": "evil.example",
                    "X-Forwarded-Proto": "https",
                },
            ).status_code
            == 200
        )
        assert client.get("/lab/accounts").json() == before
    print(
        "PASS: independent contexts, no Python/secrets in frontend, static/error headers, "
        "session cookies, CSRF, Host/Origin/fetch-site/authorization and forwarding isolation"
    )


if __name__ == "__main__":
    main()
