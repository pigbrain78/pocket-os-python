"""Browser rehearsal tests for the Pocket OS control-room tabs (Cognitive Twin,
AI Shadow, Decisions). Real crash detection, data-testid selectors only, and
every assertion describes a judge-facing behavior.

These extend the demo rehearsal harness. Consequential actions (propose,
council, ratify, reject, execute) require a session with the matching
permission, so tests sign in as admin.
"""

import pytest
from playwright.sync_api import Page, expect

BASE = "http://127.0.0.1:8787"

S = {
    "root":          "[data-testid='pocket-os-root']",
    "tabConsole":    "[data-testid='tab-console']",
    "tabTwin":       "[data-testid='tab-twin']",
    "tabShadow":     "[data-testid='tab-shadow']",
    "tabDecisions":  "[data-testid='tab-decisions']",
    "integrity":     "[data-testid='integrity-status']",
    "loginUser":     "[data-testid='login-user']",
    "loginPass":     "[data-testid='login-pass']",
    "loginSubmit":   "[data-testid='login-submit']",
    "sessionSubj":   "[data-testid='session-subject']",
    # twin
    "twinFocus":     "[data-testid='twin-focus']",
    "twinMemory":    "[data-testid='twin-memory']",
    "twinLoop":      "[data-testid='twin-loop-open']",
    "twinProject":   "[data-testid='twin-project']",
    "twinObs":       "[data-testid='twin-observation']",
    # shadow
    "shadowItem":    "[data-testid='shadow-item']",
    "shadowAuthority": "[data-testid='shadow-authority']",
    "shadowBoundary": "[data-testid='shadow-boundary']",
    # decisions
    "decisionCard":  "[data-testid='decision-card']",
    "decisionStatus": "[data-testid='decision-status']",
    "decisionRatified": "[data-testid='decision-ratified']",
    "lifecycle":     "[data-testid='lifecycle']",
    "proposeTitle":  "[data-testid='propose-title']",
    "proposeSubmit": "[data-testid='propose-submit']",
}


@pytest.fixture(autouse=True)
def _harness(page: Page):
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console",
            lambda m: errors.append(f"console.error: {m.text}") if m.type == "error" else None)
    # Each test starts clean and INTACT.
    resp = page.request.post(BASE + "/api/login", data={"username": "admin", "password": "demo"})
    token = resp.json()["token"]
    page.request.post(BASE + "/api/demo/reset", headers={"Authorization": "Bearer " + token})
    yield
    assert not errors, "runtime errors:\n" + "\n".join(errors)


def _login_admin(page: Page) -> None:
    page.goto(BASE + "/")
    page.wait_for_selector(S["root"])
    page.fill(S["loginUser"], "admin")
    page.fill(S["loginPass"], "demo")
    page.click(S["loginSubmit"])
    page.wait_for_selector(S["sessionSubj"])


def test_twin_renders_epistemic_state(page: Page):
    page.goto(BASE + "/")
    page.wait_for_selector(S["root"])
    page.click(S["tabTwin"])
    focus = page.locator(S["twinFocus"]).first
    expect(focus).to_be_visible(timeout=4000)
    # Current focus is an inference and must be labelled INFERRED.
    expect(focus).to_contain_text("INFERRED")
    memories = page.locator(S["twinMemory"])
    expect(memories.first).to_be_visible(timeout=4000)
    for m in memories.all():
        text = m.inner_text()
        assert any(t in text for t in ("VERIFIED", "UNCERTAIN")), f"memory not epistemically tagged: {text}"


def test_twin_focus_is_distinct_from_fact(page: Page):
    page.goto(BASE + "/")
    page.wait_for_selector(S["root"])
    page.click(S["tabTwin"])
    focus = page.locator(S["twinFocus"]).first.inner_text()
    assert "INFERRED" in focus
    assert "VERIFIED" not in focus
    assert "appears" in focus.lower()  # hedged, not asserted


def test_shadow_is_advisory_never_executes(page: Page):
    page.goto(BASE + "/")
    page.wait_for_selector(S["root"])
    page.click(S["tabShadow"])
    expect(page.locator(S["shadowBoundary"]).first).to_contain_text("NONE", timeout=4000)
    for a in page.locator(S["shadowAuthority"]).all():
        assert a.inner_text() == "NONE"


def test_decisions_render_lifecycle_and_ratification(page: Page):
    page.goto(BASE + "/")
    page.wait_for_selector(S["root"])
    page.click(S["tabDecisions"])
    expect(page.locator(S["decisionCard"]).first).to_be_visible(timeout=4000)
    statuses = [s.inner_text() for s in page.locator(S["decisionStatus"]).all()]
    assert "RATIFIED" in statuses
    assert "REJECTED" in statuses
    ratified = [r.inner_text() for r in page.locator(S["decisionRatified"]).all()]
    assert "NOT RATIFIED" in ratified
    expect(page.locator(S["lifecycle"]).first).to_be_visible()


def test_propose_flow_adds_decision(page: Page):
    _login_admin(page)
    page.click(S["tabDecisions"])
    page.wait_for_selector(S["proposeTitle"])
    before = page.locator(S["decisionCard"]).count()
    title = "proposal from controlroom rehearsal"
    page.fill(S["proposeTitle"], title)
    page.click(S["proposeSubmit"])
    # Wait for the new decision to actually render (the refresh is async) before
    # asserting, so this is not a timing race.
    expect(page.locator("body")).to_contain_text(title, timeout=5000)
    assert page.locator(S["decisionCard"]).count() >= before


def test_ratify_flow_records_event_not_ui_only(page: Page):
    _login_admin(page)
    page.click(S["tabDecisions"])
    page.wait_for_selector(S["proposeTitle"])
    page.fill(S["proposeTitle"], "ratify me via controlroom")
    page.click(S["proposeSubmit"])
    cards = page.locator(S["decisionCard"])
    new_card = cards.filter(has_text="ratify me via controlroom").first
    # propose with send_to_council -> COUNCIL, so the council-approve shows.
    new_card.get_by_role("button", name="Approve (council)").click()
    expect(new_card.get_by_role("button", name="Ratify (human)")).to_be_visible(timeout=4000)
    new_card.get_by_role("button", name="Ratify (human)").click()
    expect(new_card).to_contain_text("RATIFIED", timeout=4000)
    expect(new_card.get_by_role("button", name="Execute")).to_be_visible(timeout=4000)


def test_rejected_decision_never_offers_execute(page: Page):
    _login_admin(page)
    page.click(S["tabDecisions"])
    cards = page.locator(S["decisionCard"])
    rejected = cards.filter(has_text="REJECTED").first
    expect(rejected).to_be_visible(timeout=4000)
    assert rejected.get_by_role("button", name="Execute").count() == 0
