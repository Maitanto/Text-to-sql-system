# Text-to-SQL LLM

> **Status: work in progress.** Started in November 2026 and actively developed.
> Last updated: 2026-11-18. See the [roadmap](#roadmap) for what is done and what comes next.

An end-to-end pipeline that translates natural-language questions into SQL queries, given the schema of a database. The core of the project is fine-tuning **Llama 3 8B** with **LoRA** so that the model learns to *read the schema it is given* instead of memorizing specific tables.

## Goals

- Build synthetic (schema, question, SQL) training data, validated by actually executing the queries.
- Fine-tune Llama 3 8B with LoRA (Hugging Face PEFT / TRL).
- Measure the gain over the base model with **execution accuracy** (does the generated query return the same result as the reference query?), including on a schema never seen during training.
- Serve the model behind a FastAPI + vLLM API, running generated queries safely against PostgreSQL.

## Roadmap

- [x] Design two mock relational databases ([project notes](doc/PROJECT_NOTES.md))
- [x] PostgreSQL environment with Docker Compose (one container, two databases)
- [x] Table definitions for both databases (`initdb.d/`)
- [ ] Populate the mock databases with data
- [ ] Write a set of reference queries (`queries.sql`)
- [ ] Generate the synthetic training dataset (schema, question, SQL) and validate it by execution
- [ ] LoRA fine-tuning of Llama 3 8B (model + LoRA adapter setup started in `data_to_sql.py`)
- [ ] Evaluation: base model vs. fine-tuned model (execution accuracy, held-out schema)
- [ ] Serving with FastAPI + vLLM
- [ ] Safe execution of generated queries with SQLAlchemy
- [ ] Containerize the full stack

## Planned architecture

```
 question + schema ──► fine-tuned Llama 3 8B (LoRA) ──► SQL query ──► PostgreSQL ──► result
                              ▲
              served with vLLM behind a FastAPI endpoint
```

## Mock databases

Two PostgreSQL databases are used so the model sees different schemas. They are created by the scripts in `initdb.d/`.

**`transactions` (retail sales)**

| Table | Description |
|---|---|
| `customers` | login (PK), name, age, gender, address, company name (if representing a company) |
| `products` | name (PK), price, release date, cost of production |
| `transactions` | id (PK), product, customer, date, quantity |

**`subscriptions`**

| Table           | Description                                                         |
| --------------- | ------------------------------------------------------------------- |
| `users`         | login (PK), name, age, gender, signup date                          |
| `plans`         | name (PK), price, billing period (monthly, annual)         |
| `subscriptions` | id (PK), user, start date, end date (`NULL` while active), plan     |
| `payments`      | id (PK), subscription, amount, payment method, status, payment date |

Design choices: natural keys, `CHECK` constraints on prices, quantities and enumerated values (payment status, billing period, payment method), and PostgreSQL rather than SQLite to work with a realistic database engine.

## Tech stack

| Used now | Planned |
|---|---|
| Python, PyTorch, Hugging Face Transformers, PEFT | TRL, Pandas (dataset generation) |
| PostgreSQL 17, Docker Compose | vLLM, FastAPI |
| Git / GitHub | SQLAlchemy |

## Repository structure

```
.
├── data_to_sql.py        # model loading + LoRA configuration (work in progress)
├── docker-compose.yml    # PostgreSQL service
├── initdb.d/             # database creation and table definitions, run at first startup
├── populate.sql          # mock data (to do)
├── queries.sql           # reference queries (to do)
└── doc/PROJECT_NOTES.md  # design notes for the mock databases
```

## Getting started

**Prerequisites:** Docker and Docker Compose.

1. Create a `.env` file at the root of the repository (it is gitignored), for example by copying `.env.example`:

   ```
   POSTGRES_DB=transactions
   POSTGRES_USER=<your_user>
   POSTGRES_PASSWORD=<your_password>
   ```

   `POSTGRES_DB` must be `transactions`: the official image creates that database at startup, and the scripts in `initdb.d/` then create the `subscriptions` database and connect to each one to create its tables.

2. Start the database:

   ```bash
   docker compose up -d
   ```

3. Connect with any SQL client (e.g. DBeaver) on `localhost:5436`.

> The scripts in `initdb.d/` only run the first time the volume is created. To rebuild the databases from scratch: `docker compose down -v && docker compose up -d`.

## Data

Datasets and model artifacts are not versioned (`data/`, `*.csv`, `models/`, `checkpoints/` are gitignored). The scripts used to regenerate them will be documented here as they are written.

## Results

Evaluation has not been run yet. This table will be filled in once it has.

| Model | Execution accuracy (seen schemas) | Execution accuracy (held-out schema) |
|---|---|---|
| Llama 3 8B (base) | – | – |
| Llama 3 8B + LoRA | – | – |
