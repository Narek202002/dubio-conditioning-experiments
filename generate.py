# Copyright (c) 2026 Narek Moradian, University of Twente.
# Released under the MIT License. See LICENSE for details.
#
# generate.py
# -----------
# Synthetic probabilistic table generator for DuBio conditioning experiments.
#
# Creates a BDD table and a probability dictionary on the configured PostgreSQL
# server.  Each row's BDD sentence is a randomly constructed Boolean formula
# over a shared pool of random variables (RVAs).  Three expression types are
# supported:
#
#   and_heavy  — conjunctions of 2–4 RVAs  (prone to contradictions at small
#                variable counts; contradicting rows are regenerated until none
#                remain)
#   or_heavy   — disjunctions of 2–4 RVAs
#   random     — mix of single literals and short conjunctions/disjunctions
#
# Variables are named alphabetically (a, b, …, z, aa, ab, …).  Each variable
# has `num_values` possible integer values (1..num_values); probabilities are
# drawn uniformly at random and then normalised so they sum to 1.
#
# Tables and dictionaries are named after the run configuration so that
# multiple configurations can coexist on the same server without collision.
#
# Typical usage (called by benchmark.py and effectiveness.py):
#
#   from generate import generate
#   generate(num_rows=1000, num_variables=32, num_values=25,
#            expression_type='or_heavy', seed=42)

import random
from connect import get_connection

# ── Default parameters (overridden by callers in benchmark/effectiveness) ─────
NUM_ROWS        = 100
NUM_VARIABLES   = 4
NUM_VALUES      = 3
EXPRESSION_TYPE = 'and_heavy'   # random | and_heavy | or_heavy | mixed
SEED            = 42


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_variable_names(n):
    """
    Return a list of n variable names using a base-26 alphabetic scheme:
    a, b, …, z, aa, ab, …  (same convention as spreadsheet column labels).
    """
    names = []
    for i in range(n):
        name = ""
        while i >= 0:
            name = chr(ord('a') + i % 26) + name
            i = i // 26 - 1
        names.append(name)
    return names


def make_rva(var, val):
    """Format a random variable assignment as the string 'var=val'."""
    return f"{var}={val}"


def make_expression(variables, num_values, expression_type):
    """
    Build a single BDD sentence string for one table row.

    The sentence is a Boolean formula over `variables` expressed in DuBio's
    BDD literal syntax (e.g. 'a=1&b=2|c=3').  Expression structure is
    controlled by `expression_type`:

      and_heavy — conjunction of 2–4 randomly chosen RVAs
      or_heavy  — disjunction of 2–4 randomly chosen RVAs
      mixed     — compound expression: (rva OP rva) OP rva
      random    — single literal or short conjunction/disjunction of 1–4 RVAs
    """
    def rand_rva():
        var = random.choice(variables)
        val = random.randint(1, num_values)
        return make_rva(var, val)

    if expression_type == 'and_heavy':
        n = random.randint(2, 4)
        return '&'.join(rand_rva() for _ in range(n))

    elif expression_type == 'or_heavy':
        n = random.randint(2, 4)
        return '|'.join(rand_rva() for _ in range(n))

    elif expression_type == 'mixed':
        # (rva OP rva) OP rva
        left  = rand_rva()
        right = rand_rva()
        op    = random.choice(['&', '|'])
        extra = rand_rva()
        op2   = random.choice(['&', '|'])
        return f"({left}{op}{right}){op2}{extra}"

    else:  # 'random'
        n = random.randint(1, 4)
        if n == 1:
            return rand_rva()
        op = random.choice(['&', '|'])
        return f"({op.join(rand_rva() for _ in range(n))})"


def make_dict_string(variables, num_values):
    """
    Generate a DuBio dictionary string with random, normalised probabilities.

    For each variable, `num_values` probabilities are drawn uniformly at
    random and normalised so they sum to 1.  Format:
      'a=1:0.3456; a=2:0.6544; b=1:0.1234; …'
    """
    parts = []
    for var in variables:
        probs = [random.random() for _ in range(num_values)]
        total = sum(probs)
        probs = [p / total for p in probs]
        for val, prob in zip(range(1, num_values + 1), probs):
            parts.append(f"{var}={val}:{prob:.4f}")
    return '; '.join(parts)


# ── Main generation routine ───────────────────────────────────────────────────

def generate(num_rows=NUM_ROWS, num_variables=NUM_VARIABLES,
             num_values=NUM_VALUES, expression_type=EXPRESSION_TYPE,
             seed=SEED):
    """
    Create (or replace) a probabilistic BDD table and its dictionary on the
    configured PostgreSQL server.

    Steps:
      1. Drop and recreate the BDD table.
      2. Insert `num_rows` rows with randomly generated BDD sentences.
      3. Detect and replace any contradicting rows (isfalse(_sentence) = true)
         iteratively until none remain.  AND-heavy expressions are prone to
         contradictions when the variable pool is small relative to sentence
         length; without this step those rows would always condition in near-
         zero time and skew timing results downward.
      4. Delete any existing dictionary entry with the same name, then insert
         a fresh one with normalised random probabilities.

    Table name  : narek_{num_rows}_{expression_type}
    Dictionary  : narek_{num_rows}_{abbr}  (abbr keeps it under 20 chars)
    """
    random.seed(seed)

    # DuBio dictionary names are capped at ~20 characters; use abbreviations.
    short_type = {'random': 'r', 'and_heavy': 'ah', 'or_heavy': 'oh', 'mixed': 'm'}
    abbr       = short_type.get(expression_type, expression_type)
    table_name = f"narek_{num_rows}_{expression_type}"
    dict_name  = f"narek_{num_rows}_{abbr}"
    variables  = make_variable_names(num_variables)

    conn = get_connection()
    cur  = conn.cursor()

    # 1. Fresh BDD table
    cur.execute(f'DROP TABLE IF EXISTS "pp2526_49"."{table_name}";')
    cur.execute(
        f'CREATE TABLE "pp2526_49"."{table_name}" (id integer, _sentence bdd);'
    )

    # 2. Insert all rows in a single batch statement
    rows = [
        (i, make_expression(variables, num_values, expression_type))
        for i in range(1, num_rows + 1)
    ]
    args = ','.join(cur.mogrify('(%s,%s)', row).decode() for row in rows)
    cur.execute(
        f'INSERT INTO "pp2526_49"."{table_name}" (id, _sentence) VALUES {args}'
    )

    # 3. Replace contradicting sentences (BDD evaluates to false) iteratively
    while True:
        cur.execute(
            f'SELECT id FROM "pp2526_49"."{table_name}" WHERE isfalse(_sentence)'
        )
        false_ids = [row[0] for row in cur.fetchall()]
        if not false_ids:
            break
        replacements = [
            (row_id, make_expression(variables, num_values, expression_type))
            for row_id in false_ids
        ]
        args = ','.join(
            cur.mogrify('(%s,%s)', r).decode() for r in replacements
        )
        cur.execute(
            f'UPDATE "pp2526_49"."{table_name}" SET _sentence = v.expr::bdd '
            f'FROM (VALUES {args}) AS v(id, expr) '
            f'WHERE "{table_name}".id = v.id'
        )

    # 4. Dictionary — drop existing entry then insert a fresh one
    dict_str = make_dict_string(variables, num_values)
    cur.execute(
        f"DELETE FROM \"pp2526_49\".\"_dict\" WHERE name = '{dict_name}';"
    )
    cur.execute(
        f"INSERT INTO \"pp2526_49\".\"_dict\" (name, dict) "
        f"VALUES ('{dict_name}', dictionary('{dict_str}'));"
    )

    conn.commit()
    cur.close()
    conn.close()

    print(f"Generated table '{table_name}' with {num_rows} rows, "
          f"{num_variables} variables.")


if __name__ == "__main__":
    generate()
