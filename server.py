"""AirDNA Market Intelligence MCP — Emerald Vista Cabin / Broken Bow OK"""
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path
from dotenv import load_dotenv
import httpx
from fastmcp import FastMCP

load_dotenv()

API_BASE = "https://api.airdna.co/api"

# Broken Bow market IDs (discovered via Playwright network capture 2026-03-22)
SUBMARKET_ID = "airdna-5638"   # Broken Bow submarket
MARKET_ID = "airdna-375"       # Broken Bow Lake market (parent)
HOCHATOWN_ID = "airdna-5639"   # Hochatown submarket (same parent market)

TOKEN_FILE = Path(__file__).parent / ".airdna_token"

mcp = FastMCP(
    name="airdna",
    instructions=(
        "AirDNA market intelligence for Emerald Vista Cabin (EVC) in Broken Bow, Oklahoma. "
        "Provides STR market data: ADR, occupancy, revenue benchmarks, comp listings, "
        "seasonal trends, and market score. Data source: Airbnb + VRBO combined. "
        "Submarket: Broken Bow (airdna-5638). Market: Broken Bow Lake (airdna-375)."
    ),
)


# ── AUTH ─────────────────────────────────────────────────────────────────────

_token: str | None = None
_token_exp: float = 0


def _load_token() -> str | None:
    """Load cached token from file."""
    global _token, _token_exp
    if TOKEN_FILE.exists():
        try:
            data = json.loads(TOKEN_FILE.read_text())
            token = data.get("token", "")
            exp = data.get("exp", 0)
            if token and time.time() < exp - 60:
                _token = token
                _token_exp = exp
                return token
        except Exception:
            pass
    return None


def _save_token(token: str, exp: float) -> None:
    TOKEN_FILE.write_text(json.dumps({"token": token, "exp": exp}))
    TOKEN_FILE.chmod(0o600)


def _get_token() -> str:
    """Return valid bearer token, auto-refreshing if expired."""
    global _token, _token_exp

    # Check env override (for testing)
    env_token = os.getenv("AIRDNA_TOKEN", "").strip()
    if env_token:
        return env_token

    # Use cached token if still valid
    if _token and time.time() < _token_exp - 60:
        return _token

    # Try loading from file
    t = _load_token()
    if t:
        return t

    # Auto-refresh if credentials available
    email = os.getenv("AIRDNA_EMAIL", "")
    password = os.getenv("AIRDNA_PASSWORD", "")
    if email and password:
        try:
            from auth import refresh_token
            t = refresh_token(email, password)
            _token = t
            _token_exp = time.time() + 900
            return t
        except Exception as e:
            raise RuntimeError(
                f"Auto token refresh failed: {e}. "
                "Check AIRDNA_EMAIL/AIRDNA_PASSWORD in .env, or run airdna_refresh_token()."
            )

    raise RuntimeError(
        "No valid AirDNA token. Add AIRDNA_PASSWORD to ~/DEV/Agents/airdna-mcp/.env "
        "or run airdna_refresh_token() with your password."
    )


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://app.airdna.co",
        "Referer": "https://app.airdna.co/",
    }


def _get(path: str) -> dict:
    resp = httpx.get(f"{API_BASE}{path}", headers=_headers(), timeout=30)
    resp.raise_for_status()
    body = resp.json()
    if body.get("status", {}).get("type") == "error":
        raise RuntimeError(f"AirDNA error: {body['status'].get('message', 'unknown')[:200]}")
    return body.get("payload", {})


def _post(path: str, data: dict) -> dict:
    resp = httpx.post(f"{API_BASE}{path}", headers=_headers(), json=data, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    if body.get("status", {}).get("type") == "error":
        raise RuntimeError(f"AirDNA error: {body['status'].get('message', 'unknown')[:200]}")
    return body.get("payload", {})


def _date_range(months_back: int = 12) -> dict:
    """Build a rolling date range filter."""
    end = date.today().replace(day=1) - timedelta(days=1)
    start = (end.replace(day=1) - timedelta(days=30 * (months_back - 1))).replace(day=1)
    return {"data_source": "airbnb_vrbo", "date_range": {"start": str(start), "end": str(end)}}


def _bedroom_filter(bedrooms: int) -> dict:
    return {"field": "bedrooms", "type": "select", "value": bedrooms}


def _fmt_pct(v: float | None) -> str:
    return f"{(v or 0) * 100:.1f}%" if v and v <= 1 else f"{v or 0:.1f}%"


# ── TOOLS ────────────────────────────────────────────────────────────────────

@mcp.tool()
def airdna_set_token(token: str) -> str:
    """Manually store AirDNA JWT token. Use when headless login is unavailable.
    Get token from: app.airdna.co → browser console → JSON.parse(localStorage.getItem('auth')).appToken"""
    global _token, _token_exp
    import base64
    try:
        payload = token.split(".")[1] + "==="
        claims = json.loads(base64.urlsafe_b64decode(payload))
        exp = claims.get("exp", time.time() + 900)
    except Exception:
        exp = time.time() + 900
    _token = token
    _token_exp = exp
    _save_token(token, exp)
    try:
        _get(f"/explorer/v1/submarket/{SUBMARKET_ID}")
        return f"Token saved and validated ✅ (expires {time.strftime('%H:%M', time.localtime(exp))})"
    except Exception as e:
        return f"Token saved but validation failed: {e}"


@mcp.tool()
def airdna_refresh_token(password: str = "") -> str:
    """Headless Playwright login to refresh AirDNA token automatically.
    Uses AIRDNA_EMAIL + AIRDNA_PASSWORD from .env, or pass password directly.
    Token TTL is 15 min — call this before a research session."""
    global _token, _token_exp
    try:
        from auth import refresh_token
        email = os.getenv("AIRDNA_EMAIL", "juanpa.ruiz@gmail.com")
        pwd = password or os.getenv("AIRDNA_PASSWORD", "")
        if not pwd:
            return (
                "AIRDNA_PASSWORD not set. Add it to ~/DEV/Agents/airdna-mcp/.env "
                "or pass password= directly to this tool."
            )
        token = refresh_token(email, pwd)
        import base64
        payload = token.split(".")[1] + "==="
        claims = json.loads(base64.urlsafe_b64decode(payload))
        exp = claims.get("exp", time.time() + 900)
        _token = token
        _token_exp = exp
        return f"Token refreshed ✅ Valid until {time.strftime('%H:%M:%S', time.localtime(exp))}"
    except Exception as e:
        return (
            f"Headless refresh failed: {e}\n"
            "Fallback: log into app.airdna.co manually, then run airdna_set_token() with "
            "the value from: JSON.parse(localStorage.getItem('auth')).appToken"
        )


@mcp.tool()
def airdna_market_overview() -> str:
    """Broken Bow Lake market overview: market score, revenue, ADR, occupancy, RevPAR.
    Returns both parent market and Broken Bow submarket stats."""
    try:
        market = _get(f"/explorer/v1/market/{MARKET_ID}")
        sub = _get(f"/explorer/v1/submarket/{SUBMARKET_ID}")

        mm = market.get("metrics", {})
        sm = sub.get("metrics", {})

        return (
            f"=== Broken Bow Lake Market (parent) ===\n"
            f"Market Score: {mm.get('market_score', 0):.0f}/100\n"
            f"Annual Revenue: ${mm.get('revenue', 0):,.0f}\n"
            f"ADR: ${mm.get('daily_rate', 0):.2f}\n"
            f"Occupancy: {_fmt_pct(mm.get('booked'))}\n"
            f"RevPAR: ${mm.get('revpar', 0):.2f}\n"
            f"Total Listings: {mm.get('listing_count') or 'N/A'}\n"
            f"\n=== Broken Bow Submarket ===\n"
            f"Market Score: {sm.get('market_score', 0):.0f}/100\n"
            f"Annual Revenue: ${sm.get('revenue', 0):,.0f}\n"
            f"ADR: ${sm.get('daily_rate', 0):.2f}\n"
            f"Occupancy: {_fmt_pct(sm.get('booked'))}\n"
            f"RevPAR: ${sm.get('revpar', 0):.2f}\n"
        )
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def airdna_comp_benchmarks(bedrooms: int = 3, months: int = 12) -> str:
    """Percentile benchmarks (p25/median/p75) for ADR, occupancy, and annual revenue
    filtered by bedroom count. Default: 3-bed comps matching EVC."""
    try:
        dr = _date_range(months)
        filters = [_bedroom_filter(bedrooms)] if bedrooms > 0 else []
        data = _post(
            f"/explorer/v1/submarket/{SUBMARKET_ID}/metric_percentiles",
            {"scope": "str", "percentiles": [25, 50, 75], "date": dr, "filters": filters}
        )
        m = data.get("metrics", {})
        count = data.get("count", 0)
        adr = m.get("average_daily_rate_ltm", {})
        occ = m.get("occupancy_rate_ltm", {})
        rev = m.get("revenue_ltm", {})
        rat = m.get("rating_overall", {})

        bed_label = f"{bedrooms}-bed " if bedrooms > 0 else "all "
        return (
            f"=== {bed_label}Broken Bow Comp Benchmarks ({count} listings, last {months}mo) ===\n"
            f"ADR       p25=${adr.get('p25', 0):.0f}  median=${adr.get('p50', 0):.0f}  p75=${adr.get('p75', 0):.0f}\n"
            f"Occupancy p25={occ.get('p25', 0)*100:.0f}%  median={occ.get('p50', 0)*100:.0f}%  p75={occ.get('p75', 0)*100:.0f}%\n"
            f"Rev/yr    p25=${rev.get('p25', 0):,.0f}  median=${rev.get('p50', 0):,.0f}  p75=${rev.get('p75', 0):,.0f}\n"
            f"Rating    p25={rat.get('p25', 0):.0f}  median={rat.get('p50', 0):.0f}  p75={rat.get('p75', 0):.0f}\n"
        )
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def airdna_top_comps(bedrooms: int = 3, limit: int = 10, months: int = 12) -> str:
    """Top competing listings by revenue. Filters by bedroom count. Shows title, revenue,
    ADR, occupancy, rating, reviews. Useful for identifying top performers to benchmark against."""
    try:
        dr = _date_range(months)
        filters = [_bedroom_filter(bedrooms)] if bedrooms > 0 else []
        data = _post(
            f"/explorer/v1/submarket/{SUBMARKET_ID}/listings",
            {
                "date": dr,
                "filters": filters,
                "pagination": {"offset": 0, "page_size": limit},
                "sort": {"field": "revenue", "order": "desc"},
            }
        )
        listings = data.get("listings", data.get("items", []))
        total = data.get("total", len(listings))
        if not listings:
            return f"No listings found for {bedrooms}-bed Broken Bow"

        lines = [f"Top {len(listings)} of {total} {bedrooms}-bed listings by revenue (last {months}mo):"]
        for i, lt in enumerate(listings, 1):
            title = lt.get("title", "?")
            rev = lt.get("revenue_ltm", lt.get("revenue", 0))
            adr = lt.get("average_daily_rate_ltm", lt.get("adr", 0))
            occ = lt.get("occupancy_rate_ltm", lt.get("occupancy", 0))
            rating = lt.get("rating", 0)
            reviews = lt.get("reviews", 0)
            loc = lt.get("location", {})
            lat, lng = loc.get("lat", ""), loc.get("lng", "")
            abnb_id = lt.get("airbnb_property_id", "")
            url = f"https://www.airbnb.com/rooms/{abnb_id}" if abnb_id else "n/a"
            lines.append(
                f"{i:2}. {title}\n"
                f"    Revenue: ${rev:,.0f}/yr | ADR: ${adr:.0f} | Occ: {occ:.0f}% | ★{rating:.1f} ({reviews} reviews)\n"
                f"    Coords: {lat}, {lng} | Airbnb: {url}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def airdna_evc_vs_market(evc_revenue: float, evc_adr: float, evc_occupancy: float,
                          bedrooms: int = 3, months: int = 12) -> str:
    """Compare EVC performance vs Broken Bow market benchmarks.
    Pass EVC's actual revenue, ADR, and occupancy (as decimal, e.g. 0.65 for 65%).
    Returns percentile ranking and gap analysis."""
    try:
        dr = _date_range(months)
        data = _post(
            f"/explorer/v1/submarket/{SUBMARKET_ID}/metric_percentiles",
            {"scope": "str", "percentiles": [25, 50, 75], "date": dr,
             "filters": [_bedroom_filter(bedrooms)]}
        )
        m = data.get("metrics", {})
        adr_p = m.get("average_daily_rate_ltm", {})
        occ_p = m.get("occupancy_rate_ltm", {})
        rev_p = m.get("revenue_ltm", {})

        def rank(val, p25, p50, p75) -> str:
            if val >= p75: return "top 25% 🟢"
            if val >= p50: return "above median 🟡"
            if val >= p25: return "below median 🟠"
            return "bottom 25% 🔴"

        lines = [
            f"=== EVC vs {bedrooms}-bed Broken Bow Market ===",
            f"",
            f"Annual Revenue:",
            f"  EVC:     ${evc_revenue:>8,.0f}",
            f"  Market:  p25=${rev_p.get('p25',0):,.0f} | median=${rev_p.get('p50',0):,.0f} | p75=${rev_p.get('p75',0):,.0f}",
            f"  Status:  {rank(evc_revenue, rev_p.get('p25',0), rev_p.get('p50',0), rev_p.get('p75',0))}",
            f"  Gap to p75: ${max(0, rev_p.get('p75',0) - evc_revenue):,.0f}",
            f"",
            f"ADR:",
            f"  EVC:     ${evc_adr:.0f}",
            f"  Market:  p25=${adr_p.get('p25',0):.0f} | median=${adr_p.get('p50',0):.0f} | p75=${adr_p.get('p75',0):.0f}",
            f"  Status:  {rank(evc_adr, adr_p.get('p25',0), adr_p.get('p50',0), adr_p.get('p75',0))}",
            f"",
            f"Occupancy:",
            f"  EVC:     {evc_occupancy*100:.1f}%",
            f"  Market:  p25={occ_p.get('p25',0)*100:.0f}% | median={occ_p.get('p50',0)*100:.0f}% | p75={occ_p.get('p75',0)*100:.0f}%",
            f"  Status:  {rank(evc_occupancy, occ_p.get('p25',0), occ_p.get('p50',0), occ_p.get('p75',0))}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def airdna_search_market(query: str) -> str:
    """Search for AirDNA markets/submarkets by name. Returns market ID needed for other tools."""
    try:
        data = _get(f"/search/v1/markets/verbose?q={query.replace(' ', '+')}&limit=8")
        items = data.get("items", [])
        if not items:
            return f"No markets found for '{query}'"
        lines = [f"Markets matching '{query}':"]
        for it in items:
            lines.append(
                f"  {it.get('id')} | {it.get('name')} ({it.get('type')}) | "
                f"score={it.get('metrics', {}).get('market_score', 'N/A')}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def airdna_health_check() -> str:
    """Check AirDNA MCP connectivity and token validity."""
    try:
        data = _get(f"/explorer/v1/submarket/{SUBMARKET_ID}")
        m = data.get("metrics", {})
        return (
            f"AIRDNA MCP — HEALTHY ✅\n"
            f"Submarket: {data.get('name')} ({SUBMARKET_ID})\n"
            f"Market Score: {m.get('market_score', 0):.0f} | "
            f"ADR: ${m.get('daily_rate', 0):.0f} | "
            f"Occupancy: {_fmt_pct(m.get('booked'))}"
        )
    except Exception as e:
        return f"AIRDNA MCP — ERROR ❌\n{e}\nRun airdna_set_token() to refresh authentication."


if __name__ == "__main__":
    mcp.run(transport="stdio")
