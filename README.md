# My AI

A friendly, beginner-friendly AI chatbot you can run on your own computer or deploy for free. It has a modern chat interface, streaming replies, and saved conversation history.

> **Disclaimer:** My AI is an independent project. It is not affiliated with or endorsed by OpenAI. The app uses the OpenAI Python library only as a client — you can point it at OpenAI **or** at a free provider like Groq by changing one line in `.env`.

---

## Features

- 💬 Real-time chat with streamed replies (text appears word by word)
- 🧠 Conversation memory — messages are saved in SQLite and survive refreshes
- 🌙 Light and dark themes, with your choice remembered
- 📱 Responsive layout for phones, tablets, and desktops
- 📋 Copy button on every reply
- 🔒 API key kept in `.env`, never in the browser or the code
- 🆓 Works with **Groq's free API** — no credit card needed

---

## Project structure

```
my-ai/
├── backend/
│   ├── main.py          # FastAPI routes, streaming, static files
│   ├── ai_service.py    # AI client, key handling, safe errors
│   ├── database.py      # SQLite conversations and messages
│   └── models.py        # Request/response validation
├── frontend/
│   ├── index.html       # Page structure
│   ├── style.css        # Themes and responsive design
│   └── script.js        # Chat behaviour and API calls
├── tests/
│   └── test_smoke.py    # Free automated tests
├── .env                 # YOUR SECRETS - never commit this
├── .env.example         # Safe template to copy from
├── .gitignore           # Keeps .env and *.db out of Git
├── requirements.txt     # Python dependencies
├── render.yaml          # Free Render deployment config
└── README.md            # This file
```

---

## Part 1 — Run it locally

### What you need
- Python 3 (this project was built with Python 3.15)
- A terminal (Terminal on Mac, PowerShell on Windows)

### Steps

**1. Open a terminal in the project folder**

```bash
cd /Users/chaithu/Documents/my-ai
```
(Change the path if you saved the project somewhere else.)

**2. Create a private Python environment (one time only)**

```bash
python3 -m venv .venv
```

**3. Install the dependencies (one time only)**

```bash
.venv/bin/pip install -r requirements.txt
```
On Windows, use `.venv\Scripts\pip install -r requirements.txt` instead.

**4. Start the app**

```bash
.venv/bin/uvicorn backend.main:app --reload
```

**5. Open your browser**

Go to <http://127.0.0.1:8000>

You should see "How can I help you today?". To explore the API, open <http://127.0.0.1:8000/docs>.

Press `Ctrl + C` in the terminal to stop the server.

---

## Part 2 — Get a free API key (Groq)

OpenAI does not offer a permanent free API tier, but **Groq** does — no credit card needed.

1. Go to <https://console.groq.com/keys>
2. Sign up or log in.
3. Click **Create API Key**, name it something like `My AI MacBook`, and copy it immediately.
4. Free limits (at the time of writing): 30 requests/minute and 1,000 requests/day — plenty for personal use.

⚠️ Treat the key like a password. Never share it, paste it in chat, or add it to a file that gets uploaded to GitHub.

---

## Part 3 — Configure the key

Open `.env` in a text editor and fill in your key:

```dotenv
OPENAI_API_KEY=paste_your_groq_key_here
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_MODEL=openai/gpt-oss-20b
```

Important:
- No quotes around the key, and no spaces around `=`.
- Save the file, then **restart the server** (`.env` is not hot-reloaded).

Check that it worked **without printing your key**:

```bash
.venv/bin/python -c "from backend.ai_service import config_summary; print(config_summary())"
```

You want to see `'configured': True`, the Groq URL, and the model name.

### Using OpenAI instead
If you have a paid OpenAI account, set:
```dotenv
OPENAI_API_KEY=sk-your-openai-key
OPENAI_BASE_URL=
OPENAI_MODEL=gpt-4o-mini
```

---

## Part 4 — Test locally

Send this message in the browser:

```
Say hello in one short sentence.
```

The reply should stream in word by word. Refresh the page and click the conversation in the sidebar — your messages should still be there.

Run the free automated tests (they use a fake AI and a temporary database, so they cost nothing and never touch your real data):

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Expected ending: `Ran 12 tests ... OK`.

---

## Part 5 — Deploy for free on Render

Render has a free Python web service. It deploys straight from GitHub.

### Before you start
Your code must be on GitHub. From the project folder:

```bash
git status
```
Make sure `.env` and `chat.db` are **not** listed — they are protected by `.gitignore`.

If you have not committed or pushed yet:

```bash
git add .
git commit -m "Add My AI chatbot"
git push -u origin main
```

### Deploy steps

1. Sign up at <https://render.com> using GitHub.
2. Click **New + → Blueprint**.
3. Connect your GitHub account and select the repository (`my-ai-model`).
4. Render reads `render.yaml` and asks you to fill in `OPENAI_API_KEY`.
5. Paste your **Groq key** there. The other settings are filled in automatically.
6. Click **Apply** and wait for the build to finish.
7. Open the URL Render gives you, e.g. `https://my-ai.onrender.com` (the name comes from `render.yaml`).

### Verify the deployment
- `https://your-app.onrender.com/api/health` → `{"status":"ok",...}`
- `https://your-app.onrender.com/api/config` → `configured: true` with the Groq URL
- Send a chat message and confirm you get a real reply

### Free-tier caveats (important)
- **Chat history resets.** Render's free plan has a temporary filesystem, so the SQLite file (`chat.db`) is deleted when the service restarts or sleeps. The app still works; only saved conversations are lost. To keep history permanently, you would need a paid plan with a persistent disk, or a hosted database.
- **Sleeps after 15 minutes of inactivity.** The first visitor after a quiet period waits about a minute while the service wakes up.
- **750 free instance-hours per month.** Render shows your usage in the dashboard.

---

## Environment variables

| Variable | Example | Purpose |
|----------|---------|---------|
| `OPENAI_API_KEY` | `gsk_...` | Your Groq (or OpenAI) key — secret |
| `OPENAI_BASE_URL` | `https://api.groq.com/openai/v1` | Which provider to call; blank means OpenAI |
| `OPENAI_MODEL` | `openai/gpt-oss-20b` | Model ID to use |
| `SYSTEM_PROMPT` | (optional) | Instructions that shape the assistant's behaviour |
| `ALLOWED_ORIGINS` | (optional) | Comma-separated browser origins allowed to call the API |
| `DATABASE_PATH` | (optional) | Where to store `chat.db`; useful with a persistent volume |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "This site can't be reached" | The server isn't running. Start it with the command in Part 1 and keep the terminal open. |
| `OPENAI_API_KEY is not set` | Fill in `.env`, save it, and restart the server. |
| `configured: False` | Check for extra spaces in `.env` and restart the server. |
| Error about the model | Make sure `OPENAI_MODEL` matches a model your provider offers. |
| Port 8000 already in use | Run with `--port 8001` and open `http://127.0.0.1:8001`. |
| Browser shows old code | Hard-refresh with `Cmd + Shift + R`. |
| Want to reset chat history | Stop the server, delete `chat.db`, then start it again. |

---

## Security notes

- Your key lives only in `.env` locally, or in Render's dashboard when deployed.
- `.gitignore` excludes `.env`, `.env.*` (except the example), `*.db`, and the virtual environment.
- No key is ever sent to the browser or printed by `/api/config`.
- Never commit a file containing a real key. If a key leaks, revoke it in the provider's console and create a new one.

---

## License / credits

Built as a learning project. Uses FastAPI, the OpenAI Python SDK, SQLite, and plain HTML/CSS/JavaScript. Not affiliated with OpenAI or Groq.
