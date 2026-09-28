# Storm Readiness AI

Hackathon project for the "AI-Powered Storm Preparedness & Response Intelligence" use case — turns official hurricane forecasts into localized impact predictions and an optimized, pre-landfall resource staging plan, orchestrated by an AI agent whose outputs are verified by a trust layer before human review.

See [`docs/proposal.md`](docs/proposal.md) for the full proposal: rationale, architecture, tech stack, data sources, models, evaluation plan, and open questions for sponsors.

## Run the demo on your laptop

The demo is a chat app: a Python backend (agent + trust layer) and a React frontend. All data is **fake stub data** for now.

### 1. Install the prerequisites

- **Python 3.11+**: check with `python3 --version` (Windows: `python --version`)
- **Node.js 20.19+ or 22.12+**: check with `node --version`
- **Git**

### 2. Get the code

```bash
git clone https://github.com/tyakovenko/storm-readiness-ai.git
cd storm-readiness-ai
git switch c/agent-trust-layer   # until this branch is merged into main
```

### 3. Create your `.env` file

In the repo root, create a file named `.env`:

```
LLM_MODEL=mock
```

`mock` runs a scripted demo: no API key, no cost. To use a real model instead:

```
LLM_MODEL=anthropic/claude-opus-5
ANTHROPIC_API_KEY=sk-ant-...
```

`.env` is gitignored. **Never commit an API key or paste it in chat.**

### 4. Start the backend (terminal 1)

macOS / Linux:

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --reload --port 8001
```

Windows (PowerShell):

```powershell
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\uvicorn app:app --reload --port 8001
```

The install step is only needed the first time. Wait for `Application startup complete`.

### 5. Start the frontend (terminal 2)

```bash
cd frontend
npm install
npm run dev
```

`npm install` is only needed the first time. Open the URL it prints, usually **http://localhost:5173**.

### 6. Try it

Click an example question, or type one like *"We only have 6 trucks and Shelter 2 is closed. Re-plan."* Expand **Trust checks** and **Tool calls** under an answer to see how it got there. In mock mode, the **Trust demo** button shows the trust layer blocking a made-up number.

Stop both servers with **Ctrl+C**.

### Troubleshooting

| Problem | Fix |
|---|---|
| Backend exits with `LLM_MODEL is not set` or `Missing credentials` | Check that `.env` is in the repo root (not in `backend/`) and has the lines above |
| `address already in use` | Another app is on that port. Stop it, or use another port and update `frontend/vite.config.js` to match |
| UI says "Can't reach the backend" | Start the backend first and keep that terminal open |
| Blank white page | Run only one `npm run dev` at a time; restart it with `npm run dev -- --force` and hard-refresh (Cmd/Ctrl+Shift+R) |
| `npm install` fails or Vite won't start | Update Node.js to 20.19+ or 22.12+ |

How the code fits together and what's still stubbed: [`backend/README.md`](backend/README.md).
