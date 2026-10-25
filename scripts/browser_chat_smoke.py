"""Real Edge chat QA against compose.chat-test.yaml; fake LLM, actual MCP and PostgreSQL."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    artifacts = Path(__file__).resolve().parents[1] / ".lab-artifacts"
    artifacts.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("http://127.0.0.1:8080")
        expect(page.locator("#notice")).to_contain_text("Local lab ready")
        expect(page.locator("#chat-input")).to_be_enabled()

        def send(prompt):
            page.locator("#chat-input").fill(prompt)
            page.locator("#chat-send").click()
            expect(page.locator("#chat-status")).to_contain_text("Turn complete", timeout=30000)

        send("What is Alice's balance?")
        expect(page.locator("#chat-operations")).to_contain_text("balance_cents")
        send("Transfer $1 from Alice to Bob.")
        card = page.locator(".chat-card").filter(has_text='"amount_cents": 100\n')
        expect(card).to_contain_text("READY")
        before = page.locator("#alice").inner_text()
        card.get_by_role("button", name="Execute via MCP →", exact=True).click()
        expect(card).to_contain_text("SUCCEEDED", timeout=30000)
        after = page.locator("#alice").inner_text()
        assert before != after
        card.get_by_role("button", name="Replay via MCP", exact=True).click()
        expect(page.locator("#chat-status")).to_contain_text("Turn complete", timeout=30000)
        expect(page.locator("#alice")).to_have_text(after)
        send("Transfer $100.01 from Alice to Bob.")
        pending = page.locator(".chat-card").filter(has_text='"amount_cents": 10001')
        expect(pending).to_contain_text("PENDING_APPROVAL")
        assert pending.get_by_role("button", name="Execute via MCP →").count() == 0
        pending.get_by_role("button", name="Inspect / human review", exact=True).click()
        expect(page.locator("#state")).to_have_text("PENDING_APPROVAL")
        page.get_by_role("button", name="✓ Approve", exact=True).click()
        expect(page.locator("#state")).to_have_text("READY")
        pending.get_by_role("button", name="Continue / refresh", exact=True).click()
        expect(pending).to_contain_text("READY", timeout=30000)
        pending.get_by_role("button", name="Execute via MCP →", exact=True).click()
        expect(pending).to_contain_text("SUCCEEDED", timeout=30000)
        expect(pending).to_contain_text("HUMAN_APPROVED")
        op_id = pending.locator("small").inner_text()
        send("Transfer $1,000.01 from Alice to Bob.")
        denied = page.locator(".chat-card").filter(has_text='"amount_cents": 100001')
        expect(denied).to_contain_text("DENIED")
        assert denied.get_by_role("button", name="Execute via MCP →").count() == 0
        send("What happened to my last operation?")
        expect(page.locator("#chat-tools")).to_contain_text("get_operation")
        expect(page.locator("#chat-tools")).to_contain_text("execute_operation")
        # Keep the current-operation filter; page through the persistent audit to this ID.
        for _ in range(100):
            if "OPERATION_EXECUTED" in page.locator("#events").inner_text():
                break
            with page.expect_response(lambda r: "/lab/audit?" in r.url) as response:
                page.get_by_role("button", name="Load more", exact=True).click()
            assert response.value.json()["events"], "Approved chat operation absent from audit"
        expect(page.locator("#events")).to_contain_text("OPERATION_EXECUTED")
        page.locator("#chat").screenshot(path=str(artifacts / "chat-desktop.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(artifacts / "chat-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not errors, errors
        print(
            "PASS: Edge chat — balance, ALLOW, explicit MCP execute/replay, "
            "independent approval, DENY, last status, audit; no JS errors; mobile no overflow"
        )
        print("Approved chat operation: " + op_id)
        browser.close()


if __name__ == "__main__":
    main()
