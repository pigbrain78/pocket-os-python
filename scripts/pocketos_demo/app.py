
# External signer integration: keep private key material out of PocketOS.
# Configure SIGNER_URL and optional SIGNER_API_KEY in Render's environment.
SIGNER_URL = os.getenv("SIGNER_URL", "").rstrip("/")
SIGNER_API_KEY = os.getenv("SIGNER_API_KEY", "")

async def sign_externally(payload: dict[str, Any]) -> dict[str, Any]:
    """Ask the configured off-box signer to sign a canonical payload."""
    if not SIGNER_URL:
        raise HTTPException(status_code=503, detail="external signer is not configured")
    import urllib.request
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json"}
    if SIGNER_API_KEY:
        headers["Authorization"] = f"Bearer {SIGNER_API_KEY}"
    req = urllib.request.Request(f"{SIGNER_URL}/sign", data=body, headers=headers, method="POST")
    try:
        response = await asyncio.to_thread(urllib.request.urlopen, req, timeout=15)
        result = json.loads(response.read().decode())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"external signer unavailable: {exc}") from exc
    if not isinstance(result, dict) or not result.get("signature"):
        raise HTTPException(status_code=502, detail="external signer returned no signature")
    return result


