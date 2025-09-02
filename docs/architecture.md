# Architecture Overview

This project follows a modular layout to support a multi-agent orchestration
pattern using Amazon Bedrock models.  The core components are:

- **src/agents** – specialised agents that score and handle user requests.  New
  agents can be added by subclassing `AgentBase`.
- **src/llm** – wrappers around Amazon Bedrock models.  The `LLMManager` reads
  configuration from YAML and instantiates the appropriate client.
- **src/database** – thin database layer built on SQLAlchemy used by agents for
  data access.
- **src/ui** – Streamlit application providing the chat interface.
- **src/config** – YAML configuration files for the LLM and database.
- **scripts** – helper scripts such as `init_db.py` for bootstrapping the
  database.

Agents are coordinated by `AgentManager` which scores all agents for each user
request.  After an agent responds, a lightweight `ResponseEvaluator` judges the
answer; if the score is low the manager retries with the next best agent.  This
dynamic routing keeps responses accurate and allows future orchestration layers
(CrewAI, LangChain agents, etc.) to be plugged in without major rewrites.
