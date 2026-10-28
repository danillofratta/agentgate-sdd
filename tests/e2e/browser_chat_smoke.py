"""Opt-in Edge QA with compose.chat-test.yaml: fake LLM, actual MCP/API/PostgreSQL."""

import os
from pathlib import Path

from browser_smoke import inspect_audit, responsive_checks, review
from playwright.sync_api import expect, sync_playwright


def main():
    artifacts = Path(__file__).resolve().parents[2] / ".lab-artifacts"
    artifacts.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel=os.environ.get("AGENTGATE_BROWSER_CHANNEL", "msedge") or None, headless=True
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("http://127.0.0.1:8080")
        expect(page.locator("#notice")).to_contain_text("Local lab ready")
        page.get_by_role("link", name="AI Assistant", exact=True).click()

        def send(prompt):
            page.locator("#chat-input").fill(prompt)
            page.locator("#chat-send").click()
            expect(page.locator("#chat-status")).to_contain_text("Turn complete", timeout=30000)

        send("What is Alice's balance?")
        expect(page.locator("#result")).to_contain_text("balance:")
        send("Transfer $1 from Alice to Bob.")
        expect(page.locator("#state")).to_have_text("Authorized — not executed")
        before = page.locator("#alice").inner_text()
        page.locator("#execute").click()
        expect(page.locator("#state")).to_have_text("Completed", timeout=30000)
        after = page.locator("#alice").inner_text()
        assert before != after
        page.locator("#replay").click()
        expect(page.locator("#chat-status")).to_contain_text("Turn complete", timeout=30000)
        expect(page.locator("#alice")).to_have_text(after)
        send("Transfer $100.01 from Alice to Bob.")
        expect(page.locator("#state")).to_have_text("Awaiting human approval")
        review(page)
        expect(page.locator("#alice")).to_have_text(after)
        page.locator("#execute").click()
        expect(page.locator("#state")).to_have_text("Completed", timeout=30000)
        page.locator("details.reference > summary").click()
        operation_id = page.locator("#operation-id").inner_text()
        assert operation_id
        page.get_by_role("link", name="Operations", exact=True).click()
        expect(page.locator("#operation-id")).to_have_text(operation_id)
        assert page.locator("#operation-workspace").count() == 1
        inspect_audit(page)
        page.get_by_role("link", name="AI Assistant", exact=True).click()
        send("Transfer $1,000.01 from Alice to Bob.")
        expect(page.locator("#state")).to_have_text("Denied by policy")
        expect(page.locator("#execute")).to_be_hidden()
        send("What happened to my last operation?")
        responsive_checks(page, artifacts, "assistant")
        assert not errors, errors
        print(
            "PASS: balance chat, proposal, MCP execute/replay, independent review, navigation, deny"
        )
        browser.close()


if __name__ == "__main__":
    main()
