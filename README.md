# Retail Inventory Multi‑Agent Application

This project is a green‑field re‑implementation of the original WarehouseManagerAI
application.  It preserves the idea of using a conversational assistant to help
with retail inventory management while redesigning the internals around modern
best practices: modular code organisation, multi‑agent orchestration and
explicit configuration for LLMs, data sources and runtime environment.

## Features

- **Modular architecture** – the source tree is broken into separate
  components (`src/llm`, `src/agents`, `src/database`, `src/ui`, `src/config` and
  `scripts`) so that each concern lives in its own module.  This makes it
  easier to extend or swap out parts of the system without affecting the rest.
- **Amazon Bedrock models** – all LLM interactions are routed through
  Amazon Bedrock via `boto3` and LangChain wrappers.  Changing models or
  parameters is as simple as editing a YAML file (`src/config/llm_config.yaml`).
- **Multi‑agent orchestration** – user requests are dispatched to one or more
  agent objects that evaluate the prompt, score their relevance and produce
  replies.  Agents can specialise in tasks such as product lookup, inventory
  availability, or generic chat.  An `AgentManager` coordinates the scoring and
  selects the highest scoring agent for each request.
- **Streamlit user interface** – the front‑end is a simple Streamlit app
  (`src/ui/app.py`) that presents a chat box and conversation history.  It
  demonstrates how to integrate agents and LLMs into a modern web UI.
- **Database integration** – a relational database (PostgreSQL by default) is
  used to store and query inventory data.  A helper script
  (`scripts/init_db.py`) downloads a `.sql` dump from S3 and creates the
  database.  Database credentials and S3 details are stored in `.env`.  The
  Docker setup relies on the `ankane/pgvector` image and an init script that
  runs `CREATE EXTENSION IF NOT EXISTS vector;` so the pgvector extension is
  available for similarity search.
- **Dockerised deployment** – the provided `Dockerfile` and
  `docker-compose.yaml` enable reproducible local or cloud deployments.  A
  `run_all.sh` script demonstrates a typical end‑to‑end workflow: build
  containers, initialise the database and launch the Streamlit UI.
- **Testing and scripts** – skeleton unit tests under `tests/` help verify
  agent scoring and LLM integrations.  Additional scripts (`clear_out.sh`,
  etc.) are provided to tear down the environment between runs.

## Quick start

1. **Clone the repository and navigate into it**

   ```sh
   git clone <repo-url> new_app
   cd new_app
   ```

2. **Create a Python virtual environment and install dependencies**

   ```sh
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Copy the `.env.example` to `.env` and edit it** – set your AWS region,
   Bedrock model ID, database credentials, S3 bucket and key.

4. **Initialise the database**

   ```sh
   python scripts/init_db.py
   ```

5. **Run the Streamlit app**

   ```sh
   streamlit run src/ui/app.py
   ```

For Docker users, run `./run_all.sh` to build and start all services.  See
`docs/architecture.md` for a high‑level overview of the system and detailed
instructions.
