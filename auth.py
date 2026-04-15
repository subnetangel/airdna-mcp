"""AirDNA token refresh via Playwright.

Strategy 1 (primary): Email+password headless login — used for evc@ravncap.com (email-based account).
Strategy 2 (fallback): Navigate to app while session is active, extract fresh token from localStorage.

Note: juanpa.ruiz@gmail.com used Google SSO / passkey (old account).
evc@ravncap.com uses standard email+password — Strategy 1 is preferred.
"""
import json
import os
import time
from pathlib import Path

TOKEN_FILE = Path(__file__).parent / ".airdna_token"
APP_URL = "https://app.airdna.co/data"
LOGIN_URL = (
    "https://auth.airdna.co/oauth2/authorize"
    "?tenantId=1fb206a8-177b-4684-af1f-8fff7cc153a0"
    "&client_id=5f040464-0aef-48a1-a1d1-daa9fbf81415"
    "&redirect_uri=https%3A%2F%2Fapp.airdna.co"
    "&response_type=code&scope=profile%20openid"
    "&state=%7B%22path%22%3A%22%2Flogin%22%7D"
)

JS_EXTRACT_TOKEN = """() => {
    const auth = JSON.parse(localStorage.getItem('auth') || '{}');
    const token = auth.appToken || '';
    if (!token) return null;
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        return JSON.stringify({ token, exp: payload.exp, uid: payload.uid });
    } catch { return JSON.stringify({ token, exp: 0 }); }
}"""


def _save_token(token: str, exp: float) -> None:
    TOKEN_FILE.write_text(json.dumps({"token": token, "exp": exp}))
    TOKEN_FILE.chmod(0o600)


def refresh_via_session(user_data_dir: str | None = None) -> str:
    """Extract fresh token from existing browser session (no login needed).
    Works as long as the mcporter Playwright Chrome profile has an active AirDNA session."""
    import shutil, tempfile
    from playwright.sync_api import sync_playwright

    default_profile = os.path.expanduser(
        "~/Library/Caches/ms-playwright/mcp-chrome"
    )
    profile_dir = user_data_dir or default_profile

    # Copy profile to avoid lock conflicts with running Chrome instance
    tmp_dir = tempfile.mkdtemp(prefix="airdna_profile_")
    try:
        default_src = os.path.join(profile_dir, "Default")
        if os.path.exists(default_src):
            shutil.copytree(default_src, os.path.join(tmp_dir, "Default"))

        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                tmp_dir,
                headless=True,
                args=["--no-first-run", "--disable-sync", "--no-sandbox"],
            )
            try:
                page = ctx.new_page()
                page.goto(APP_URL, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(3000)

                if "login" in page.url or "oauth2" in page.url:
                    raise RuntimeError(
                        "Browser session expired — log in manually at app.airdna.co first."
                    )

                result = page.evaluate(JS_EXTRACT_TOKEN)
                if not result:
                    raise RuntimeError("No auth token in localStorage")

                data = json.loads(result)
                token = data.get("token", "")
                exp = data.get("exp", 0)

                if not token:
                    raise RuntimeError("Empty token in localStorage")

                _save_token(token, exp)
                return token
            finally:
                ctx.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def refresh_token(email: str | None = None, password: str | None = None) -> str:
    """Refresh AirDNA token. Tries email+password first (evc@ravncap.com), falls back to session."""
    email = email or os.getenv("AIRDNA_EMAIL", "")
    password = password or os.getenv("AIRDNA_PASSWORD", "")

    # Strategy 1: email+password (preferred — evc@ravncap.com is email-based)
    if email and password:
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(LOGIN_URL, wait_until="networkidle")
                    page.fill("input#loginId", email)
                    page.wait_for_timeout(500)
                    page.fill("input#password", password)
                    page.wait_for_timeout(500)
                    page.click("button:has-text('Log In')")
                    page.wait_for_url("https://app.airdna.co/**", timeout=20000)
                    page.wait_for_load_state("networkidle")

                    result = page.evaluate(JS_EXTRACT_TOKEN)
                    if not result:
                        raise RuntimeError("Login succeeded but no token in localStorage")

                    data = json.loads(result)
                    token = data.get("token", "")
                    exp = data.get("exp", 0)
                    _save_token(token, exp)
                    return token
                finally:
                    browser.close()
        except Exception as login_err:
            login_error = str(login_err)
    else:
        login_error = "No email/password configured"

    # Strategy 2: session-based fallback (requires active browser session at app.airdna.co)
    try:
        return refresh_via_session()
    except Exception as session_err:
        raise RuntimeError(
            f"Email+password login failed ({login_error}). "
            f"Session refresh also failed ({session_err}). "
            "Check AIRDNA_EMAIL / AIRDNA_PASSWORD in .env."
        )


if __name__ == "__main__":
    token = refresh_token()
    import base64
    payload = token.split(".")[1] + "==="
    claims = json.loads(base64.urlsafe_b64decode(payload))
    print(f"Token refreshed. Expires: {time.strftime('%H:%M:%S', time.localtime(claims.get('exp', 0)))}")
