```
███████╗██╗ ██████╗ ███╗   ██╗  █████╗ ██╗     ██╗███████╗
██╔════╝██║██╔════╝ ████╗  ██║ ██╔══██╗██║     ██║██╔════╝
███████╗██║██║  ███╗██╔██╗ ██║ ███████║██║     ██║███████╗
╚════██║██║██║   ██║██║╚██╗██║ ██╔══██║██║     ██║╚════██║
███████║██║╚██████╔╝██║ ╚████║ ██║  ██║███████╗██║███████║
╚══════╝╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═╝  ╚═╝╚══════╝╚═╝╚══════╝
```

**Signal intelligence and outreach data — from raw input to enriched, structured CSV.**

Signalis is a command-line framework for outreach teams. It takes raw, messy contact data — scraped lists, CRM exports, Apify datasets — and transforms it into clean, signal-enriched records ready for campaigns. Shape data in the **Shaper**, then run the **Connector** to match supply to demand, find missing emails, generate AI intros, and push directly to your campaign platform.

```
  ⚗  Shaper      Raw CSV / Apify → normalised 6-column CSVs
  ⚯  Connector   Supply + Demand CSVs → matched pairs, intros, campaigns
```

No browser. No SaaS. No upload limits. Just your data, your terminal, and your API keys.

---

## ⟶  Install

Three lines. One command does everything — creates a virtual environment, installs dependencies, adds `signalis` to your PATH, and walks you through API key setup.

### macOS / Linux

```bash
git clone https://github.com/ChatsuboDigital/signalis-framework.git
cd signalis-framework
chmod +x install.sh && ./install.sh
```

### Windows

**PowerShell (recommended):**
```powershell
git clone https://github.com/ChatsuboDigital/signalis-framework.git
cd signalis-framework
powershell -ExecutionPolicy Bypass -File install.ps1
```

**Command Prompt:**
```cmd
git clone https://github.com/ChatsuboDigital/signalis-framework.git
cd signalis-framework
install.bat
```

> Requires Python 3.9+. Get it from [python.org](https://www.python.org/downloads/). On Windows, check **Add Python to PATH** during installation.

After install, run from any directory — no activation needed, no path changes, no flags.

---

## ☉  Launch

```bash
signalis
```

The interactive menu guides you through everything:

```
  1  ⚗  Shaper       Transform raw data into outreach-ready CSVs
  2  ⚯  Connector    Match supply & demand · enrich contacts · generate intros
  3  ◈  Settings     Configure API keys
  4  ⟶  Update       Pull latest version from GitHub
  0  ⊗  Exit
```

| Command | What it does |
|---------|-------------|
| `signalis` | Launch the interactive menu |
| `signalis setup` | Configure or update API keys |
| `signalis config` | Show which services are active |
| `signalis update` | Pull latest code and reinstall dependencies |
| `signalis connect run -d demand.csv -s supply.csv` | Run the connector directly |

---

## ⚗  Shaper

Takes raw data and produces clean, normalised CSVs. Auto-detects columns, cleans domains and names, resolves missing data via AI, and exports a consistent 6-column schema — regardless of what the input looked like.

```
  Raw input (CSV or Apify dataset)
      │
      ├─ 1. Load          Read CSV or fetch from Apify by dataset ID
      ├─ 2. Map fields     Auto-detect columns or assign them manually
      ├─ 3. Preview        Inspect records before any processing
      ├─ 4. Normalize      Clean domains, names, emails, encoding
      ├─ 5. Signal & ctx   Set signals manually, map from a column, or use Exa
      ├─ 6. Enrich         Domain resolution → AI signals → company context
      └─ 7. Export         Timestamped CSV written to output/
```

### Output schema

Every export — 3 columns in or 30 — produces the same structure:

| Full Name | Company Name | Domain | Email | Context | Signal |
|-----------|--------------|--------|-------|---------|--------|
| Jane Smith | Acme Corp | acme.com | jane@acme.com | SaaS platform for HR teams | Hiring 3 sales engineers |
| John Doe | Bolt Inc | bolt.io | | Fast-growing logistics network | Raised $40M Series B |

This is the universal format. The Connector expects it, and so do most campaign platforms.

---

## ⚯  Connector

Where supply meets demand. Takes two shaped CSVs and runs a pipeline that scores every possible pair, finds missing emails, generates personalised AI intros, and optionally sends leads to your campaign platform.

```
  supply.csv  +  demand.csv
      │
      ├─ 1. Normalize        Standardise both datasets
      ├─ 2. Match            Score every supply–demand pair
      ├─ 3. Enrich           Find missing emails (Apollo → Anymail → SSM cascade)
      ├─ 4. AI Intros        Generate personalised intros per match
      ├─ 5. Send             Push to Instantly.ai or Plusvibe (optional)
      └─ 6. Export           Matched CSV with intros written to output/
```

Launch from the menu or run directly:

```bash
signalis connect run --demand demand.csv --supply supply.csv
```

### Matching

The matching engine scores pairs using weighted factors — industry alignment, signal relevance, capability fit, semantic keyword overlap — and classifies each match into a confidence tier (strong, good, or open). You set the minimum threshold before each run.

### Enrichment

Missing emails are resolved through a cascading system — cache first, then Apollo, then Anymail Finder, then SSM as final fallback. Successful results are cached locally for 90 days, so re-runs on similar data cost zero API calls.

> **SSM (Sales System Mastery)** is a Skool community built around modern outreach and sales systems — and the community that inspired this tool. Members get access to the SSM enrichment provider as a final-stage fallback in the cascade. [Join SSM on Skool](https://www.skool.com/ssmasters) to get your API key.

```bash
signalis connect cache          # View cache stats
signalis connect cache-clear    # Wipe the cache
```

### AI intros

For each match, an AI model (OpenAI or Anthropic — your choice) generates personalised email intros using the match context. Two intros per pair: one for each side. Fallback templates kick in if the API fails.

### Campaign sending

Leads can be pushed directly to **Instantly.ai** or **Plusvibe** campaigns — no manual CSV upload. Each lead routes to the correct campaign ID, with built-in rate limiting and per-lead status tracking. Sending is always opt-in.

---

## ☾  Signals

A **signal** is a short statement describing why someone is worth reaching out to *right now*. The timing trigger that makes outreach relevant.

**Demand signals** — companies buying or hiring:
```
  Hiring 3 Senior Sales Engineers
  Raised $40M Series B — announced March 2025
  Opening London office, expanding into EMEA
```

**Supply signals** — people offering services:
```
  Recruiting senior sales talent for B2B SaaS, needs deal flow
  IT staffing for healthcare orgs, needs qualified buyer intros
  Fractional CFO for Series A startups, needs warm intros
```

Signals can come from a column in your data, a global string applied to all records, a prefix prepended to existing values, or generated per-company by Exa AI.

---

## ◈  Services & API Keys

The core pipeline works with zero API keys. Services layer on intelligence when you need it.

| Service | What it does | Used by |
|---------|-------------|---------|
| **Exa** | Domain resolution, AI signal generation, company context | Shaper |
| **OpenAI / Anthropic** | Signal synthesis, intro generation | Both |
| **Apollo** | Email enrichment | Connector |
| **Anymail Finder** | Email enrichment fallback | Connector |
| **SSM** ⬡ | Email enrichment — final fallback (Sales System Mastery members) | Connector |
| **Instantly.ai** | Campaign sending | Connector |
| **Plusvibe** | Campaign sending (alternative) | Connector |
| **Apify** | Dataset loading | Shaper |

⬡ **SSM (Sales System Mastery)** is a Skool community for outreach and sales teams — and the community that inspired this tool. Members get access to the SSM enrichment provider. [Join SSM on Skool](https://www.skool.com/ssmasters) to get your API key.

Configure keys interactively with `signalis setup` or edit `.env` by hand. Run `signalis config` to see what's active.

---

## ▲  Configuration

```bash
signalis setup          # Interactive — walks you through each key
signalis config         # Show what's active
```

Or edit `.env` directly:

```env
# ── Shaper ───────────────────────────────────────────────────
EXA_API_KEY=                  # Domain resolution, signals, context
AI_PROVIDER=openai            # openai or anthropic
OPENAI_API_KEY=               # Required if AI_PROVIDER=openai

# ── Connector — Email Enrichment ─────────────────────────────
APOLLO_API_KEY=               # Email enrichment
ANYMAIL_API_KEY=              # Email enrichment fallback
SSM_API_KEY=                  # SSM members only — skool.com/ssmasters

# ── Connector — Campaign Sending (optional) ───────────────────
SENDING_PROVIDER=instantly    # instantly or plusvibe

# Campaign IDs — used by whichever platform is active above
DEMAND_CAMPAIGN_ID=
SUPPLY_CAMPAIGN_ID=

# Instantly.ai
INSTANTLY_API_KEY=

# PlusVibe (alternative to Instantly)
# PLUSVIBE_API_KEY=
# PLUSVIBE_WORKSPACE_ID=
```

---

## ⊗  Troubleshooting

**Python not found** — Install Python 3.9+ and ensure it's on your PATH. macOS: `brew install python3`. Linux: `sudo apt install python3 python3-venv`. Windows: [python.org](https://www.python.org/downloads/).

**Import errors** — If you bypassed the installer: `source venv/bin/activate` then `pip install -e ".[all]"`.

**Permission denied** — `chmod +x install.sh && ./install.sh`

**Garbled CSV text** — Re-save as UTF-8 from your spreadsheet app before importing.

**No signals from Exa** — Both `EXA_API_KEY` and an AI provider key must be set. Records without a domain or company name are skipped.

**No emails found** — Check `APOLLO_API_KEY` or `ANYMAIL_API_KEY`. Run `signalis setup` to configure.

**Emails not sending** — Verify `SENDING_PROVIDER`, the matching API key, and at least one campaign ID in `.env`. Run `signalis config` to check.

**`signalis connect` not found** — Run `pip install -e ".[all]"` from the project folder (with venv active) to register the connector. The `update` command does this automatically.

**Update failing** — Run `signalis update`, or manually: `git pull && pip install -e ".[all]"`.

---

## ─  License

MIT
