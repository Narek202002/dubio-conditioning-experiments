# Copyright (c) 2026 Narek Moradian, University of Twente.
# Released under the MIT License. See LICENSE for details.
#
# benchmark.py
# ------------
# RQ1 scalability experiment for DuBio conditioning.
#
# Measures BDD conditioning time and dictionary update time across combinations
# of row count, variable count, value count, expression type, and evidence
# batch size.  Each configuration is run RUNS times (with different seeds so
# each run uses a freshly generated table); the median execution time is
# reported to reduce the influence of server-load spikes.
#
# The top-level parameters below correspond directly to the experimental design
# described in the paper.  To reproduce the full sweep, set:
#
#   ROW_SIZES       = [100, 1000, 10000, 100000]
#   VARIABLE_COUNTS = [2, 8, 32, 128, 256]
#   VALUE_COUNTS    = [2, 5, 25, 50, 100]
#   EXPRESSION_TYPE = 'or_heavy'   # run separately for 'and_heavy' and 'random'
#   RUNS            = 5
#
# For a quick sanity check, call run_sanity_check() instead of run_benchmark().
#
# Output: tab-separated summary printed to stdout (copy into a spreadsheet or
# redirect to a file).

import statistics
from generate import generate
from condition import condition_batch
from connect import get_connection

# ── Experiment parameters ─────────────────────────────────────────────────────

ROW_SIZES       = [100, 1000, 10000, 100000]
VARIABLE_COUNTS = [32]
VALUE_COUNTS    = [25]
EXPRESSION_TYPE = 'or_heavy'   # random | and_heavy | or_heavy | mixed
RUNS            = 5            # runs per configuration; median is reported
SEED            = 42           # base seed; each run uses SEED + run_index

# Evidence batch configurations to sweep.
# Each entry is one complete evidence batch (list of (variable, value, positive)
# triples).  Variable names follow the alphabetic scheme from generate.py, so
# VARIABLE_COUNTS must be large enough to include every variable referenced here
# (32 variables covers a–af).
EVIDENCE_CONFIGS = [
    # 1 item
    [('a', 1, True)],
    # 2 items
    [('a', 1, True), ('b', 2, False)],
    # 4 items
    [('a', 1, True), ('b', 2, False), ('c', 1, True), ('d', 2, False)],
    # 16 items
    [('a', 1, True), ('b', 2, False), ('c', 1, True), ('d', 2, False),
     ('e', 1, True), ('f', 2, False), ('g', 1, True), ('h', 2, False),
     ('i', 1, True), ('j', 2, False), ('k', 1, True), ('l', 2, False),
     ('m', 1, True), ('n', 2, False), ('o', 1, True), ('p', 2, False)],
    # 32 items
    [('a', 1, True), ('b', 2, False), ('c', 1, True), ('d', 2, False),
     ('e', 1, True), ('f', 2, False), ('g', 1, True), ('h', 2, False),
     ('i', 1, True), ('j', 2, False), ('k', 1, True), ('l', 2, False),
     ('m', 1, True), ('n', 2, False), ('o', 1, True), ('p', 2, False),
     ('q', 1, True), ('r', 2, False), ('s', 1, True), ('t', 2, False),
     ('u', 1, True), ('v', 2, False), ('w', 1, True), ('x', 2, False),
     ('y', 1, True), ('z', 2, False), ('aa', 1, True), ('ab', 2, False),
     ('ac', 1, True), ('ad', 2, False), ('ae', 1, True), ('af', 2, False)],
]


# ── Benchmark runner ──────────────────────────────────────────────────────────

def run_benchmark():
    """
    Run the full scalability sweep and print a summary table to stdout.

    For each combination of (value count, variable count, row count, evidence
    batch), the function:
      1. Generates a fresh table for each of RUNS seeds.
      2. Applies condition_batch with silent=True (suppresses per-run output).
      3. Records BDD and dict execution times separately.
      4. Prints per-run times and the median across runs.
    """
    results = []

    short_type = {'random': 'r', 'and_heavy': 'ah', 'or_heavy': 'oh', 'mixed': 'm'}
    abbr = short_type.get(EXPRESSION_TYPE, EXPRESSION_TYPE)

    for num_values in VALUE_COUNTS:
        for num_vars in VARIABLE_COUNTS:
            for num_rows in ROW_SIZES:
                for evidence in EVIDENCE_CONFIGS:
                    ev_count = len(evidence)
                    print(f"\n{'='*60}")
                    print(f"Config: {num_rows} rows, {num_vars} variables, "
                          f"{num_values} values, {ev_count} evidence item(s)")
                    print(f"Evidence: {evidence}")
                    print(f"{'='*60}")

                    bdd_times  = []
                    dict_times = []

                    for run in range(1, RUNS + 1):
                        # Fresh table for every run (different seed → different expressions).
                        generate(
                            num_rows        = num_rows,
                            num_variables   = num_vars,
                            num_values      = num_values,
                            expression_type = EXPRESSION_TYPE,
                            seed            = SEED + run,
                        )

                        table_name = f"narek_{num_rows}_{EXPRESSION_TYPE}"
                        dict_name  = f"narek_{num_rows}_{abbr}"

                        bdd_ms, dict_ms = condition_batch(
                            table     = table_name,
                            dict_name = dict_name,
                            evidence  = evidence,
                            silent    = True,
                        )
                        bdd_times.append(bdd_ms)
                        dict_times.append(dict_ms)
                        print(f"Run {run}: BDD={bdd_ms:.3f} ms  "
                              f"Dict={dict_ms:.3f} ms  "
                              f"Total={bdd_ms + dict_ms:.3f} ms")

                    median_bdd  = statistics.median(bdd_times)
                    median_dict = statistics.median(dict_times)
                    print(f" → Median: BDD={median_bdd:.3f} ms  "
                          f"Dict={median_dict:.3f} ms  "
                          f"Total={median_bdd + median_dict:.3f} ms")
                    results.append((
                        num_rows, num_vars, num_values, ev_count,
                        median_bdd, median_dict,
                    ))

    # Final summary table
    print(f"\n{'='*60}")
    print(f"{'Rows':>12} {'Variables':>12} {'Values':>12} "
          f"{'Evidence':>12} {'BDD ms':>12} {'Dict ms':>12} {'Total ms':>12}")
    print(f"{'-'*84}")
    for num_rows, num_vars, num_values, ev_count, median_bdd, median_dict in results:
        print(f"{num_rows:>12} {num_vars:>12} {num_values:>12} "
              f"{ev_count:>12} {median_bdd:>12.3f} "
              f"{median_dict:>12.3f} {median_bdd + median_dict:>12.3f}")


# ── Sanity check ──────────────────────────────────────────────────────────────

def run_sanity_check():
    """
    Quick functional check on a small table.

    Generates a 50-row AND-heavy table with 2 variables and 2 values, then
    conditions on a=1 TRUE and prints the table and dictionary before and
    after.  Use this to verify that the connection, generation, and
    conditioning pipeline all work end-to-end before running the full sweep.
    """
    NUM_ROWS_TEST = 50
    NUM_VARS_TEST = 2        # variables: a, b
    NUM_VALS_TEST = 2        # values: 1, 2
    EVIDENCE_TEST = [('a', 1, True)]
    EXPR_TEST     = 'and_heavy'

    generate(
        num_rows        = NUM_ROWS_TEST,
        num_variables   = NUM_VARS_TEST,
        num_values      = NUM_VALS_TEST,
        expression_type = EXPR_TEST,
        seed            = 99,
    )

    short_type = {'random': 'r', 'and_heavy': 'ah', 'or_heavy': 'oh', 'mixed': 'm'}
    table_name = f"narek_{NUM_ROWS_TEST}_{EXPR_TEST}"
    dict_name  = f"narek_{NUM_ROWS_TEST}_{short_type[EXPR_TEST]}"

    conn = get_connection()
    cur  = conn.cursor()

    print("\n--- BEFORE conditioning ---")
    cur.execute(
        f'SELECT id, _sentence::text FROM "pp2526_49"."{table_name}" ORDER BY id;'
    )
    for row_id, sentence in cur.fetchall():
        print(f"  Row {row_id}: {sentence}")
    cur.execute(
        'SELECT print(dict) FROM "pp2526_49"."_dict" WHERE name = %s;',
        (dict_name,),
    )
    print(f"  Dict: {cur.fetchone()[0]}")

    cur.close()
    conn.close()

    print(f"\nConditioning on evidence: {EVIDENCE_TEST}")
    condition_batch(
        table     = table_name,
        dict_name = dict_name,
        evidence  = EVIDENCE_TEST,
        silent    = False,
    )

    conn = get_connection()
    cur  = conn.cursor()

    print("\n--- AFTER conditioning ---")
    cur.execute(
        f'SELECT id, _sentence::text FROM "pp2526_49"."{table_name}" ORDER BY id;'
    )
    for row_id, sentence in cur.fetchall():
        print(f"  Row {row_id}: {sentence}")
    cur.execute(
        'SELECT print(dict) FROM "pp2526_49"."_dict" WHERE name = %s;',
        (dict_name,),
    )
    result = cur.fetchone()
    print(f"  Dict: {result[0] if result else '(empty)'}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    run_benchmark()
