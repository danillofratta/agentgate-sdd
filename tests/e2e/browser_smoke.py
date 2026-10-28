"""Opt-in Edge QA against a running lab. Creates simulated operations; never starts Docker."""

import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def review(page, *, approve=True):
    page.locator("#review").click()
    expect(page.get_by_role("dialog")).to_be_visible()
    expect(page.locator("#approve")).to_be_disabled()
    if approve:
        page.locator("#approval-confirm").check()
        page.locator("#approve").click()
        expect(page.locator("#state")).to_have_text("Approved — awaiting execution")
    else:
        page.locator("#reject").click()
        expect(page.locator("#state")).to_have_text("Rejected by reviewer")


def inspect_audit(page):
    page.locator("#timeline > summary").click()
    for _ in range(100):
        if "Operation completed" in page.locator("#events").inner_text():
            break
        with page.expect_response(lambda r: "/lab/audit?" in r.url) as response:
            page.locator("#more-audit").click()
        assert response.value.json()["events"], "Operation absent from loaded audit pages"
    expect(page.locator("#events")).to_contain_text("Operation completed")


def responsive_checks(page, artifacts, prefix):
    for width, height, label in [
        (1440, 1100, "desktop"),
        (820, 1000, "tablet"),
        (390, 844, "mobile"),
    ]:
        page.set_viewport_size({"width": width, "height": height})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        expect(page.get_by_role("navigation")).to_be_visible()
        page.screenshot(path=str(artifacts / f"{prefix}-{label}.png"), full_page=True)


def main() -> None:
    artifacts = Path(__file__).resolve().parents[2] / ".lab-artifacts"
    artifacts.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel=os.environ.get("AGENTGATE_BROWSER_CHANNEL", "msedge") or None, headless=True
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8080")
        expect(page.locator("#notice")).to_contain_text("Local lab ready")
        before = page.locator("#alice").inner_text()
        page.get_by_role("button", name="Create manually", exact=True).click()
        page.locator('[data-amount="100.01"]').click()
        page.locator("#submit").click()
        expect(page.locator("#state")).to_have_text("Awaiting human approval")
        expect(page.locator("#alice")).to_have_text(before)
        page.locator("#review").click()
        expect(page.get_by_role("dialog")).to_be_visible()
        expect(page.locator("#review")).to_be_enabled()
        page.keyboard.press("Escape")
        expect(page.locator("#review")).to_be_focused()
        review(page)
        expect(page.locator("#alice")).to_have_text(before)
        page.locator("#execute").click()
        expect(page.locator("#state")).to_have_text("Completed")
        page.locator("details.reference > summary").click()
        operation_id = page.locator("#operation-id").inner_text()
        assert operation_id
        after = page.locator("#alice").inner_text()
        assert before != after
        page.locator("#replay").click()
        expect(page.locator("#notice")).to_contain_text("Stored outcome retrieved")
        expect(page.locator("#alice")).to_have_text(after)
        inspect_audit(page)
        page.reload()
        expect(page.locator("#state")).to_have_text("Completed")
        expect(page.locator("#operation-id")).to_have_text(operation_id)
        for amount, state in [
            ("1000.01", "Denied by policy"),
            ("100.01", "Awaiting human approval"),
        ]:
            page.locator("#new-operation").click()
            page.locator("#amount").fill(amount)
            page.locator("#submit").click()
            expect(page.locator("#state")).to_have_text(state)
        review(page, approve=False)
        page.locator("#new-operation").click()
        page.locator("#amount").fill("1.00")
        page.locator("#submit").click()
        expect(page.locator("#state")).to_have_text("Authorized — not executed")
        page.locator("#execute").click()
        expect(page.locator("#state")).to_have_text("Completed")
        responsive_checks(page, artifacts, "console")
        assert not errors, errors
        print("PASS: manual proposal, approval/rejection, execute/replay, restore, audit, layouts")
        browser.close()


if __name__ == "__main__":
    main()
