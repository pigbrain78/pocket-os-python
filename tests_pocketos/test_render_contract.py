from pathlib import Path


RENDER_YAML = Path(__file__).resolve().parents[1] / "render.yaml"


def test_render_tracks_canonical_repository_branch():
    text = RENDER_YAML.read_text()
    assert "branch: master" in text


def test_render_declares_signer_secrets_without_committing_values():
    text = RENDER_YAML.read_text()
    assert "key: POCKETOS_CONSOLE_SIGNER_URL" in text
    assert "key: POCKETOS_CONSOLE_SIGNER_TOKEN" in text
    assert text.count("sync: false") >= 4
    assert 'POCKETOS_CONSOLE_SIGNER_TOKEN\n        value:' not in text


def test_render_keeps_signing_fail_closed_by_default():
    text = RENDER_YAML.read_text()
    assert 'key: POCKETOS_COUNCIL_SIGNATURE_ALGORITHM\n        value: "Ed25519"' in text
    assert 'key: POCKETOS_RUNTIME_ENV\n        value: "production"' in text
    assert "key: POCKETOS_COUNCIL_PUBLIC_KEYS_JSON" in text
    assert 'key: POCKETOS_PRODUCTION_SIGNING_ENABLED\n        value: "0"' in text
    assert 'key: POCKETOS_COUNCIL_DEMO_SIGNING\n        value: "0"' in text
    assert 'key: POCKETOS_COUNCIL_TEST_SIGNER_ENABLED\n        value: "0"' in text
