# Lab console

Framework-free browser application served by unprivileged Nginx. No Python,
JavaScript packages or credentials are needed to build it.

```sh
node --test tests/console.test.cjs
docker build -t agentgate-console .
```

From the repository root, `docker compose up --build -d --wait` starts the complete
lab at http://127.0.0.1:8080. Nginx proxies `/lab/*` to the backend `lab-bff` process
with the original Host, Origin, cookies and CSRF header. It never retries requests.
Only the backend mounts credentials. Other paths return 404; there is no SPA fallback.
