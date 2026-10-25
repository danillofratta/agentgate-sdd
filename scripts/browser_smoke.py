"""Optional real-browser QA using installed Edge; separate from offline Pytest."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    artifacts = Path(__file__).resolve().parents[1] / ".lab-artifacts"
    artifacts.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8080")
        expect(page.locator("#notice")).to_contain_text("Local lab ready")
        page.screenshot(path=str(artifacts / "lab-desktop.png"), full_page=True)
        page.get_by_role("button", name="$200 · Approval", exact=True).click()
        page.get_by_role("button", name="Submit for policy evaluation", exact=False).click()
        expect(page.locator("#state")).to_have_text("PENDING_APPROVAL")
        expect(page.locator("#intent")).to_contain_text('"amount_cents": 20000')
        operation_id = page.locator("#operation-id").input_value()
        page.get_by_role("button", name="✓ Approve", exact=True).click()
        expect(page.locator("#state")).to_have_text("READY")
        page.get_by_role("button", name="Execute operation", exact=False).click()
        expect(page.locator("#state")).to_have_text("SUCCEEDED")
        expect(page.locator("#effective")).to_contain_text("HUMAN_APPROVED")
        expect(page.locator("#replay")).to_be_enabled()
        alice = page.locator("#alice").inner_text()
        page.get_by_role("button", name="↻ Replay result", exact=True).click()
        expect(page.locator("#replay")).to_be_enabled()
        expect(page.locator("#notice")).to_contain_text("State verified")
        expect(page.locator("#alice")).to_have_text(alice)
        expect(page.locator("#events")).to_contain_text("OPERATION_EXECUTED")
        expect(page.locator("#request-view")).to_contain_text("execute")
        page.screenshot(path=str(artifacts / "lab-approved.png"), full_page=True)
        page.get_by_role("button", name="$1,000.01 · Deny", exact=True).click()
        page.get_by_role("button", name="Submit for policy evaluation", exact=False).click()
        expect(page.locator("#state")).to_have_text("DENIED")
        expect(page.locator("#decision")).to_have_text("DENY")
        expect(page.locator("#execute")).to_be_disabled()
        page.get_by_role("button", name="$200 · Approval", exact=True).click()
        page.get_by_role("button", name="Submit for policy evaluation", exact=False).click()
        expect(page.locator("#state")).to_have_text("PENDING_APPROVAL")
        page.get_by_role("button", name="× Reject", exact=True).click()
        expect(page.locator("#state")).to_have_text("REJECTED")
        expect(page.locator("#execute")).to_be_disabled()
        page.get_by_role("button", name="$1 · Allow", exact=True).click()
        page.get_by_role("button", name="Submit for policy evaluation", exact=False).click()
        expect(page.locator("#state")).to_have_text("READY")
        expect(page.locator("#decision")).to_have_text("ALLOW")
        page.get_by_role("button", name="Execute operation", exact=False).click()
        expect(page.locator("#state")).to_have_text("SUCCEEDED")
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(artifacts / "lab-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not errors, errors
        print(
            "PASS: real Edge UI — approve, reject, DENY, ALLOW, execution, replay, inspector, audit"
        )
        print("PASS: mobile 390px has no horizontal overflow; no JavaScript errors")
        print("UI approved operation: " + operation_id)
        print("Screenshots: .lab-artifacts/lab-desktop.png, lab-approved.png, lab-mobile.png")
        browser.close()


if __name__ == "__main__":
    main()
