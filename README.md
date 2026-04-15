# AirDNA MCP

A FastMCP server that provides AI agents with access to AirDNA short-term rental market data.

## Tools
- `airdna_market_overview` — Get market ADR, occupancy, revenue stats for a location
- `airdna_top_comps` — Find top performing STR comps by bedrooms near a location
- `airdna_comp_benchmarks` — Get percentile benchmarks for a market
- `airdna_evc_vs_market` — Compare a property's performance to market benchmarks
- `airdna_refresh_token` — Refresh the AirDNA session token

## Setup
1. Clone the repo
2. Create a venv: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
3. Get an AirDNA account at airdna.com and capture your session token
4. Set `AIRDNA_TOKEN` in `.env`
5. Register with mcporter: add to `~/.mcporter/mcporter.json`

## Usage
Works with OpenClaw via mcporter. Call tools with `mcporter call airdna.<tool_name>`.
