# Part 1 - Mock databases:

## Fisrt mock database model:

Products - Customers - transactions

The customers are defined by a unique id, first name, last name, gender, age, adress, company name(if representing a company)

Products would be associated to a name, a price, release_date, 

Transactions have an unique id, a product, customer_id, date, cost_of_production, quantity sold

## Second mock database model:

Users - Subscriptions - Payments - Plans

Users have an unique id, first name, last name, gender, age, signup_date

Subscriptions have an id, user id, start date, end date(null while active so date only appears when subscription ends), plans name

Payments have an unique id, a subscription id, payment method, a status, payment date

Plans have a name, price, billing period


Module	Core Responsibility	Failure Mode It Prevents	Production Reuse
schema_serializer.py	Queries live PostgreSQL catalogs for tables, columns, keys, and CHECK constraints.	Schema drift & blind guessing: Eliminates mismatches between your README and actual column names (USER_LOGIN vs. user) and exposes valid enum values ('paid').	Formats incoming database schemas identically inside your FastAPI endpoint.
validator.py	Enforces read-only SQL checks, query timeouts, and result-set sanity rules inside a rolled-back transaction.	Poisoned training data: Blocks broken SQL, runaway joins, and contradictory filters that return empty [None] rows.	Acts as the SQLAlchemy execution sandbox protecting PostgreSQL from unsafe LLM outputs.
generator.py	Uses queries_for_training.sql as few-shot anchors to synthesize new (question, SQL) pairs.	Trivial query bias: Ensures the dataset covers complex LEFT JOINs, NULL checks, and date intervals rather than basic SELECT * queries.	Generates new training examples whenever you add a domain schema.
prepare_dataset.py	Uses Pandas to deduplicate queries, balance SQL difficulty tiers, format Llama 3 prompt-completion masks, and split by database.	Memorization & data leakage: Stops easy queries from dominating gradients and keeps your held-out database completely isolated.	Reproducibly builds clean Parquet splits before every fine-tuning run.
eval_metrics.py	Compares actual query result DataFrames (ignoring alias or row-order differences) and groups errors by failure stage.	False negatives in evaluation: Credits valid SQL even when the model picks a different column alias (AS total vs. AS count), while pinpointing exact failure types.	Benchmarks base Llama 3 8B vs. your LoRA adapter for your README results table.
