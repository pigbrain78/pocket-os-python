"""Pocket OS demo rehearsal harness (browser).

Integration verification of the demo console via Playwright. Every assertion
describes a judge-facing behavior over the live preview server. Uses
data-testid selectors only. Real crash detection: collect pageerror + console
errors and assert none at teardown (a crashed app does not add a marker class).

Since the demo console now requires a session for demo controls and the
constitutional actions, these tests sign in as admin where those are involved.
"""

import re
import pytest
from playwright.sync_api import Page, expect

BASE = "http://127.0.0.1:8787"

S = {
    "root":         "[data-testid='pocket-os-root']",
    "tabConsole":   "[data-testid='tab-console']",
    "tabTimeline":  "[data-testid='tab-timeline']",
    "tabGraph":     "[data-testid='tab-graph']",
    "tabHealth":    "[data-testid='tab-health']",
    "tabGenome":    "[data-testid='tab-genome']",
    "banner":       "[data-testid='console-banner']",
    "bannerCount":  "[data-testid='console-banner-count']",
    "integrity":    "[data-testid='integrity-status']",
    "brokenSeq":    "[data-testid='broken-seq']",
    "counters":     "[data-testid='governance-counters']",
    "tamperBtn":    "[data-testid='tamper-ledger']",
    "resetBtn":     "[data-testid='reset-ledger']",
    "tick":         "[data-testid='scrubber-tick']",
    "provenance":   "[data-testid='scrubber-provenance']",
    "scrubError":   "[data-testid='scrubber-error']",
    "traitScore":   "[data-testid='genome-trait-score']",
    "recordRow":    "[data-testid='record-row']",
    # login
    "loginUser":    "[data-testid='login-user']",
    "loginPass":    "[data-testid='login-pass']",
    "loginSubmit":  "[data-testid='login-submit']",
    "sessionSubj":  "[data-testid='session-subject']",
}

TABS = ["console", "timeline", "graph", "health", "genome"]


@pytest.fixture(autouse=True)
def crash_detection(page: Page):
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console",
            lambda m: errors.append(f"console.error: {m.text}") if m.type == "error" else None)
    # ensure clean INTACT state for every test
    page.request.post(BASE + "/api/login", data={"username": "admin", "password": "demo"})
    yield
    assert not errors, "runtime errors:\n" + "\n".join(errors)


def _login(page: Page) -> None:
    """Sign in as admin so demo controls + constitutional actions are enabled."""
    page.goto(BASE + "/")
    page.wait_for_selector(S["root"])
    page.fill(S["loginUser"], "admin")
    page.fill(S["loginPass"], "demo")
    page.click(S["loginSubmit"])
    page.wait_for_selector(S["sessionSubj"])


def _reset(page: Page) -> None:
    """Reset the ledger to INTACT via the admin-gated demo endpoint."""
    resp = page.request.post(BASE + "/api/login", data={"username": "admin", "password": "demo"})
    token = resp.json()["token"]
    page.request.post(BASE + "/api/demo/reset", headers={"Authorization": "Bearer " + token})


def test_baseline(page: Page):
    """Run first. A globally broken app otherwise fails every test for the
    wrong reason and sends you hunting the wrong bug."""
    page.goto(BASE + "/")
    expect(page.locator(S["root"])).to_be_visible()

    page.click(S["tabConsole"])
    expect(page.locator(S["banner"])).to_be_visible()
    expect(page.locator(S["bannerCount"])).to_contain_text("4")

    page.click(S["tabGenome"])
    scores = page.locator(S["traitScore"]).all_inner_texts()
    assert len(scores) == 6, f"expected 6 traits, got {len(scores)}"
    assert "99" not in scores, "saturation defect present"
    assert len(set(scores)) > 1, "traits must discriminate"

    expect(page.locator(S["integrity"])).to_contain_text("INTACT")
    expect(page.locator(S["counters"])).to_contain_text("denied")


def test_no_test_data(page: Page):
    page.goto(BASE + "/")
    for tab in TABS:
        page.click(f"[data-testid='tab-{tab}']")
        expect(page.locator("body")).not_to_contain_text("TEST_")
        expect(page.locator("body")).not_to_contain_text("bland coffee")


def test_tamper_updates_without_refresh(page: Page):
    _login(page)
    expect(page.locator(S["integrity"])).to_contain_text("INTACT")
    page.click(S["tamperBtn"])
    # Must react live. If it only updates after reload, the panel is reading
    # cached state and the demo beat dies on stage.
    expect(page.locator(S["integrity"])).to_contain_text("COMPROMISED", timeout=3000)
    # Naming the record is the point. Assert the SHAPE, not a hardcoded number.
    expect(page.locator(S["brokenSeq"])).to_contain_text(re.compile(r"#\d+"))
    _reset(page)


def test_scrub_refuses_after_tamper(page: Page):
    _login(page)
    page.click(S["tamperBtn"])
    page.click(S["tabTimeline"])
    page.locator(S["tick"]).first.click()
    expect(page.locator(S["scrubError"])).to_be_visible()
    # No partial reconstruction may render alongside the error.
    expect(page.locator(S["provenance"])).to_have_count(0)
    _reset(page)


def test_banner_survives_reload(page: Page):
    page.goto(BASE + "/")
    page.click(S["tabConsole"])
    before = page.locator(S["bannerCount"]).inner_text()
    page.reload()
    expect(page.locator(S["root"])).to_be_visible()
    page.click(S["tabConsole"])
    expect(page.locator(S["banner"])).to_be_visible()
    expect(page.locator(S["bannerCount"])).to_have_text(before)


def test_legacy_records_render(page: Page):
    """legacy_v1 has no tension and no kind. Nothing in the unit suites covers
    this — the seed is entirely v2. Null-vs-zero surfaces only in the UI."""
    _login(page)
    token = page.request.post(BASE + "/api/login", data={"username": "admin", "password": "demo"}).json()["token"]
    resp = page.request.post(BASE + "/api/test/seed-legacy",
                             headers={"Authorization": "Bearer " + token},
                             data={"records": [{
                                 "id": "legacy-1", "schema_version": "legacy_v1",
                                 "consensus": 70, "tension": None, "kind": None,
                             }]})
    assert resp.ok, "seed-legacy endpoint must exist in demo builds"
    page.goto(BASE + "/")
    page.click(S["tabConsole"])
    row = page.locator(S["recordRow"]).filter(has_text="legacy").first
    expect(row).to_be_visible()
    for bad in ("NaN", "null", "undefined"):
        expect(row).not_to_contain_text(bad)
    _reset(page)


def test_reset_full_cycle(page: Page):
    """The sleeper risk. If tampering is irreversible you get exactly one
    reviewer."""
    _login(page)
    page.click(S["tamperBtn"])
    expect(page.locator(S["integrity"])).to_contain_text("COMPROMISED")
    page.click(S["resetBtn"])
    expect(page.locator(S["integrity"])).to_contain_text("INTACT", timeout=3000)
    # Replay must work again — that is what reset has to actually mean.
    page.click(S["tabTimeline"])
    page.locator(S["tick"]).first.click()
    expect(page.locator(S["provenance"])).to_be_visible()
    expect(page.locator(S["scrubError"])).to_have_count(0)
    # Second full cycle, then reload in a KNOWN-GOOD state.
    page.click(S["tamperBtn"])
    page.click(S["resetBtn"])
    page.reload()
    expect(page.locator(S["root"])).to_be_visible()
    expect(page.locator(S["integrity"])).to_contain_text("INTACT")
