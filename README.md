# Jira AC Assistant

AI-powered acceptance criteria generation for Jira tickets. Automatically generates structured, actionable ACs using Claude AI, enriches context via Barley, and escalates low-confidence results to stakeholders through Slack.

## Features

- **AI-Powered AC Generation** — Uses Claude to generate 3-7 testable acceptance criteria with confidence scoring
- **Automatic Trigger** — Background polling detects new Jira Stories/Tasks and generates ACs automatically
- **Manual Re-Trigger** — Request AC regeneration on demand via Slack DM
- **Barley Context Enrichment** — Queries Barley API for additional project context when ticket descriptions lack detail
- **Slack Escalation** — Sends low-confidence ACs (<0.7) to Product Owners/Delivery Managers via Slack DM for review
- **Jira Writeback** — Updates Jira tickets with generated ACs in Atlassian Document Format (ADF)
- **Graceful Degradation** — Barley and Slack failures are non-blocking; core AC generation continues

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Jira Cloud │◄───►│   FastAPI     │◄───►│  Claude API  │
│   (tickets)  │     │   Backend     │     │  (AC gen)    │
└──────────────┘     └──────┬───────┘     └──────────────┘
                            │
                    ┌───────┼───────┐
                    ▼       ▼       ▼
              ┌─────────┐ ┌─────┐ ┌─────────┐
              │  Slack   │ │ DB  │ │ Barley  │
              │  (DMs)   │ │(SQL)│ │ (context│
              └─────────┘ └─────┘ └─────────┘
```

**Tech Stack:** Python 3.12+ / FastAPI / Anthropic Claude API / SQLite / Slack Bolt SDK

## Project Structure

```
src/
├── ai/                  # Claude-based AC generation with confidence scoring
├── barley/              # Barley API client for context enrichment
├── jira/                # Jira REST API client, AC extraction & formatting
├── slack/               # Slack Bot (Socket Mode + Events API)
│   ├── handlers/        # DM message processing, intent classification
│   └── services/        # Regeneration & escalation workflows
├── polling/             # Background polling service for auto-processing
├── database/            # SQLite persistence, conversation state, migrations
└── main.py              # FastAPI entry point, lifespan management
tests/
├── unit/                # Unit tests
├── integration/         # Integration tests (requires credentials)
└── manual/              # Manual test cases
```

## Prerequisites

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Jira Cloud account with API token
- Anthropic API key
- Slack app with Bot/App tokens (optional, for DM features)
- Barley API access (optional, for context enrichment)

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd jira-ac-assistant

# Install dependencies with uv (recommended)
uv sync

# Or install with pip
pip install -e ".[dev]"
```

## Configuration

Create a `.env` file in the project root with the following variables:

### Required

```env
# Jira
JIRA_BASE_URL=https://your-org.atlassian.net/
JIRA_USER_EMAIL=your-email@company.com
JIRA_API_TOKEN=your-jira-api-token

# AI
ANTHROPIC_API_KEY=sk-ant-api03-your-key
```

### Optional

```env
# Jira — Polling
JIRA_PROJECT_KEY=PROJ                    # Required if polling enabled
JIRA_POLLING_ENABLED=true                # Enable background polling (default: false)
JIRA_POLLING_INTERVAL_SECONDS=300        # Poll interval (default: 300)
JIRA_POLLING_LOOKBACK_DAYS=7             # Lookback window (default: 7)
JIRA_POLLING_MAX_FAILURES=3              # Max failures before labeling (default: 3)
JIRA_ISSUE_TYPES=Story,Task              # Comma-separated issue types
JIRA_MAX_RETRIES=3                       # API retry count

# AI
AI_MODEL=claude-sonnet-4-20250514        # Claude model (default: claude-sonnet-4-20250514)
AI_MAX_TOKENS=1024                       # Max response tokens (default: 1024)
AI_TEMPERATURE=0.3                       # Generation temperature (default: 0.3)

# Barley
BARLEY_ENABLED=true                      # Enable Barley enrichment (default: false)
BARLEY_API_URL=https://your-barley-url
BARLEY_API_TOKEN=your-barley-token
BARLEY_PROJECT_NAME=PROJ                 # Project name in Barley
BARLEY_TIMEOUT=60                        # Request timeout in seconds
BARLEY_MAX_RETRIES=1                     # API retry count

# Slack
SLACK_BOT_TOKEN=xoxb-your-bot-token     # Bot token (xoxb-)
SLACK_APP_TOKEN=xapp-your-app-token      # App token for Socket Mode (xapp-)
SLACK_SIGNING_SECRET=your-signing-secret # For webhook verification
SLACK_SOCKET_MODE_ENABLED=true           # Enable WebSocket real-time events
SLACK_ESCALATION_CONTACT_EMAIL=po@company.com  # PO/DM email for escalations
SLACK_CONFIDENCE_THRESHOLD=0.7           # Escalate below this score (default: 0.7)
SLACK_MAX_RETRIES=3                      # API retry count

# Database
DATABASE_PATH=data/conversations.db      # SQLite file path
```

## Usage

### Running the Server

```bash
# Start the FastAPI server
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

On startup the application will:
1. Validate Jira credentials (exits with code 1 on failure)
2. Initialize SQLite database with auto-migrations
3. Start the polling service (if `JIRA_POLLING_ENABLED=true`)
4. Start Slack Socket Mode (if `SLACK_SOCKET_MODE_ENABLED=true`)
5. Start periodic conversation cleanup (every 24h)

### Health Check

```bash
curl http://localhost:8000/health
```

Returns component status for Slack Socket Mode, database connectivity, and uptime:

```json
{
  "status": "healthy",
  "slack_socket_mode": "connected",
  "database": "ok",
  "uptime_seconds": 123.45
}
```

### Slack Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check with component status |
| `/slack/events` | POST | Slack Events API webhook (fallback for Socket Mode) |

### How It Works

1. **Ticket Detection** — Polling service finds new/modified Jira tickets, or a user sends a ticket key via Slack DM
2. **AC Generation** — Claude AI generates acceptance criteria from the ticket description
3. **Enrichment** — If confidence is low, Barley API provides additional project context for re-generation
4. **Escalation** — If confidence remains below threshold (default 0.7), a Slack DM is sent to the configured PO/DM
5. **Writeback** — Approved ACs are written back to the Jira ticket in ADF format

## Testing

```bash
# Run all tests
pytest

# Run unit tests only
pytest tests/unit/

# Run integration tests (requires real credentials)
pytest tests/integration/

# Run with verbose output
pytest -v

# Run a specific test
pytest -k "test_ac_generator"

# Run with coverage
pytest --cov=src tests/
```

## Development

### Linting

```bash
# Check code style
ruff check src/ tests/

# Auto-fix issues
ruff check --fix src/ tests/

# Format code
ruff format src/ tests/
```

### Debug Logging

Set the `DEBUG` environment variable to enable verbose Slack Bolt logging:

```bash
DEBUG=1 uvicorn src.main:app --reload
```

## Roadmap

- [x] **Phase 1** — Jira integration, AI-powered AC generation, auto-trigger, manual re-trigger
- [x] **Phase 2** — Barley context enrichment, Slack integration foundation, PO/DM escalation
- [ ] **Phase 3** — AC approval workflow in Slack, write approved ACs to Jira, status tracking
