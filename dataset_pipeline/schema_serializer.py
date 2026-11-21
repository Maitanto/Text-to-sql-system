import re

def serialize_database_schema(
    conn,
    schema_name: str = "public",
    include_sample_rows: bool = False,
    sample_limit: int = 2,
    business_notes: str | None = None,
) -> str:
    """
    Inspects a live PostgreSQL connection via pg_catalog and returns a
    byte-for-byte deterministic schema string (sorted, lowercase identifiers).
    Business definitions stored via `COMMENT ON TABLE/COLUMN` are included automatically.
    """
    with conn.cursor() as cur:
        tables = _fetch_tables_and_columns(cur, schema_name)
        constraints = _fetch_constraints(cur, schema_name)
        samples = (
            _fetch_samples(cur, schema_name, tables, limit=sample_limit)
            if include_sample_rows
            else {}
        )

    blocks: list[str] = []
    for table_name in sorted(tables.keys()):
        table_meta = tables[table_name]
        lines: list[str] = []
        if table_meta["comment"]:
            lines.append(f"-- {table_meta['comment']}")
        lines.append(f"CREATE TABLE {table_name} (")
        col_lines: list[str] = []
        for col in table_meta["columns"]:
            parts = [f"    {col['name']} {col['type']}"]
            if col["not_null"]:
                parts.append("NOT NULL")
            if col["comment"]:
                parts.append(f"-- {col['comment']}")
            col_lines.append(" ".join(parts))
        for constraint_def in sorted(constraints.get(table_name, [])):
            col_lines.append(f"    {constraint_def}")
        formatted_entries: list[str] = []
        for idx, entry in enumerate(col_lines):
            suffix = "," if idx < len(col_lines) - 1 else ""
            if " -- " in entry:
                stmt, comment = entry.split(" -- ", 1)
                formatted_entries.append(f"{stmt}{suffix} -- {comment}")
            else:
                formatted_entries.append(f"{entry}{suffix}")

        lines.extend(formatted_entries)
        lines.append(");")

        if table_name in samples and samples[table_name]:
            col_names = [c["name"] for c in table_meta["columns"]]
            lines.append(f"-- Sample rows ({', '.join(col_names)}):")
            for row in samples[table_name]:
                rendered = ", ".join(_format_literal(v) for v in row)
                lines.append(f"--   ({rendered})")

        blocks.append("\n".join(lines))

    if business_notes and business_notes.strip():
        blocks.append(f"/* Business Definitions\n{business_notes.strip()}\n*/")

    return "\n\n".join(blocks)


def serialize_ddl_schema(ddl_text: str, business_notes: str | None = None) -> str:
    """
    Deterministic normalizer for FastAPI endpoints accepting raw DDL strings
    rather than live database credentials.
    """
    cleaned = "\n".join(line.rstrip() for line in ddl_text.strip().splitlines())
    if business_notes and business_notes.strip():
        return f"{cleaned}\n\n/* Business Definitions\n{business_notes.strip()}\n*/"
    return cleaned


def _fetch_tables_and_columns(cur, schema_name: str) -> dict:
    cur.execute(
        """
        SELECT
            c.relname AS table_name,
            obj_description(c.oid, 'pg_class') AS table_comment,
            a.attname AS column_name,
            pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
            a.attnotnull AS is_not_null,
            col_description(c.oid, a.attnum) AS column_comment,
            a.attnum AS ordinal_position
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
        WHERE n.nspname = %s
          AND c.relkind IN ('r', 'p')
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY lower(c.relname), a.attnum;
        """,
        (schema_name,),
    )
    tables: dict = {}
    for tbl, tbl_comment, col, dtype, not_null, col_comment, _ in cur.fetchall():
        tbl_key = tbl.lower()
        if tbl_key not in tables:
            tables[tbl_key] = {
                "comment": tbl_comment.strip() if tbl_comment else None,
                "columns": [],
            }
        tables[tbl_key]["columns"].append(
            {
                "name": col.lower(),
                "type": dtype.lower(),
                "not_null": bool(not_null),
                "comment": col_comment.strip() if col_comment else None,
            }
        )
    return tables


def _fetch_constraints(cur, schema_name: str) -> dict[str, list[str]]:
    cur.execute(
        """
        SELECT
            c.relname AS table_name,
            con.contype AS constraint_type,
            pg_catalog.pg_get_constraintdef(con.oid, true) AS constraint_def
        FROM pg_catalog.pg_constraint con
        JOIN pg_catalog.pg_class c ON c.oid = con.conrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND con.contype IN ('p', 'f', 'u', 'c')
        ORDER BY lower(c.relname), con.contype, pg_catalog.pg_get_constraintdef(con.oid, true);
        """,
        (schema_name,),
    )
    by_table: dict[str, list[str]] = {}
    for tbl, contype, raw_def in cur.fetchall():
        tbl_key = tbl.lower()
        formatted = _normalize_constraint_def(contype, raw_def)
        by_table.setdefault(tbl_key, []).append(formatted)
    return by_table


def _normalize_constraint_def(contype: str, raw_def: str) -> str:
    """
    Normalizes pg_get_constraintdef output; simplifies Postgres ARRAY CHECK syntax
    into readable `CHECK (col IN ('a', 'b'))` so allowed values are obvious to the LLM.
    """
    text = raw_def.strip()
    if contype == "c":
        m = re.search(
            r"\(\(?([a-zA-Z0-9_]+)\)?(?:::[a-z\s]+)?\s*=\s*ANY\s*\(\(?ARRAY\[(.*?)\]\)",
            text,
            re.IGNORECASE,
        )
        if m:
            col_name = m.group(1).lower()
            raw_vals = re.findall(r"'([^']*)'", m.group(2))
            if raw_vals:
                vals_str = ", ".join(f"'{v}'" for v in sorted(raw_vals))
                return f"CHECK ({col_name} IN ({vals_str}))"
    return text

def _fetch_samples(cur, schema_name: str, tables: dict, limit: int = 2) -> dict[str, list[tuple]]:
    samples: dict[str, list[tuple]] = {}
    for table_name, meta in sorted(tables.items()):
        first_col = meta["columns"][0]["name"]
        query = f'SELECT * FROM "{schema_name}"."{table_name}" ORDER BY "{first_col}" ASC LIMIT %s;'
        cur.execute(query, (limit,))
        samples[table_name] = cur.fetchall()
    return samples


def _format_literal(val) -> str:
    if val is None:
        return "NULL"
    if isinstance(val, str):
        escaped = val.replace("'", "''")
        return f"'{escaped}'"
    return repr(val)