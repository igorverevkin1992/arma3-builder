# arma3-builder

Multi-agent AI system that turns a high-level campaign brief into a fully-structured,
production-ready Arma 3 (Real Virtuality 4) campaign — including `description.ext`,
`mission.sqm`, `briefing.sqf`, init scripts, and a Campaign `Description.ext` flow.

The system abstracts the SQF/CFG layer so a designer can describe the campaign
in natural language while specialised agents handle code generation, mod-aware
classname lookup, performance linting and packaging.

## Architecture

```
┌──────────────┐    JSON brief     ┌──────────────────┐    PRP graph     ┌──────────────────┐
│   FastAPI    │ ────────────────▶ │   Orchestrator   │ ───────────────▶ │ Narrative Director│
│   /generate  │                   │  (coordination)  │                  │      (FSM)        │
└──────────────┘                   └──────────────────┘                  └──────────────────┘
                                            │                                     │
                                            ▼                                     ▼
                                   ┌──────────────────┐    artefacts    ┌──────────────────┐
                                   │   QA Validator   │ ◀───────────────│  Scripter (SQF)  │
                                   │  sqflint + AST   │                 │  Config Master   │
                                   └──────────────────┘                 └──────────────────┘
                                            │                                     ▲
                                            └──── repair iterations ──────────────┘
```

Five specialised roles communicate through a typed protocol (Procedural
Representation Protocol — PRP) carried as Pydantic models:

| Agent              | Responsibility                                                              |
|--------------------|-----------------------------------------------------------------------------|
| Orchestrator       | Decomposes the user brief, routes work, owns shared memory                  |
| Narrative Director | Builds the FSM graph of states/transitions, briefings, dialogue             |
| Scripter (SQF)     | FSM → init.sqf, initServer.sqf, initPlayerLocal.sqf, briefing.sqf, CBA SM   |
| Config Master      | mission.sqm (Armaclass), description.ext, Campaign Description.ext, layout  |
| QA Validator       | sqflint + AST antipattern scan + cross-file end-state validation + repairs  |

A RAG subsystem feeds agents with verified facts from:

- Bohemia **Biki** wiki (commands, syntax, examples) — semantically chunked
- **CBA / ACE3** macros (`GVAR`, `PREP`, XEH, statemachine helpers)
- Mod **classnames** (RHS, CUP, ACE3, vanilla) parsed from `config.cpp`,
  indexed with hybrid BM25 + dense vector search and metadata filters
  (`tenant`, `type`, `faction`).

## Requirements

- Python 3.10+
- Optional: Qdrant (for production RAG), Ollama (for local QA), `sqflint` (for static
  analysis). All have in-process fallbacks for development.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env

# Generate a campaign from the bundled example brief (no LLM required — uses stub provider)
python scripts/demo.py

# Or run the API
arma3-builder-api
# POST a brief:
curl -X POST http://localhost:8000/generate \
     -H 'Content-Type: application/json' \
     -d @examples/sample_campaign.json
```

The output campaign is written to `./output/<campaign_slug>/` with the directory layout
specified by Bohemia Interactive for SP / coop campaigns.

## Tests

```bash
pytest -q
```

Tests cover the SQM/description.ext/briefing/FSM generators, the QA linter, the RAG
hybrid retriever and the end-to-end pipeline using the stub LLM provider.

## Roadmap

The repository implements **Phase 1 (MVP)** and **Phase 2 (multi-agent + RAG)** of the
TZ. Phase 3 (advanced QA refactoring) is wired in as repair loops; Phase 4 (visual
node editor) consumes the FSM graph emitted by the Narrative Director — a frontend can
render the `/preview` endpoint output directly.
