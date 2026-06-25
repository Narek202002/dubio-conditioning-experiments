# Copyright (c) 2026 Narek Moradian, University of Twente.
# Released under the MIT License. See LICENSE for details.
#
# condition.py
# ------------
# Core conditioning logic for DuBio BDD-based probabilistic tables.
#
# Conditioning incorporates a piece of evidence by restricting the BDD of
# every row in the table and renormalising the probability dictionary.
# DuBio exposes this through the SQL function restrict(bdd, var, val, bool).
#
# Two public entry points are provided:
#
#   condition_table(table, dict_name, variable, chosen_value, positive)
#       Single-evidence conditioning.  Issues one UPDATE per restrict call
#       (one full table scan per call).  Kept for reference; prefer
#       condition_batch for experiments.
#
#   condition_batch(table, dict_name, evidence, silent=False)
#       Multi-evidence conditioning.  Chains all restrict() calls into a
#       single nested SQL expression so the table is scanned exactly once
#       regardless of how many evidence items are in the batch.  Returns
#       (bdd_ms, dict_ms) so callers can track the two cost components
#       independently.
#
# Evidence format:
#   A list of (variable: str, value: int, positive: bool) triples.
#   positive=True  → variable=value is observed TRUE; all other values of
#                    that variable are restricted FALSE, then value is set
#                    TRUE, and the whole variable is removed from the dict.
#   positive=False → variable=value is observed FALSE; only that RVA is
#                    restricted FALSE.  If only one value remains after the
#                    restriction, that value is automatically promoted to TRUE
#                    and the variable is removed from the dict.
#
# Note on restrict call order: FALSE restricts must be applied before TRUE
# restricts within a single chained expression.  Reversing the order causes
# incorrect BDD results.  The reason is that DuBio's restrict() resolves a
# variable assignment in-place; if a TRUE restriction is applied first, the
# subsequent FALSE restrictions for the same variable have no effect because
# the variable is already resolved.

from connect import get_connection


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_all_values(cur, dict_name, variable):
    """
    Return the list of integer values currently registered for `variable`
    in the named probability dictionary.
    """
    cur.execute(
        'SELECT alternatives(dict, %s) FROM "pp2526_49"."_dict" WHERE name = %s;',
        (variable, dict_name),
    )
    result = cur.fetchone()
    return [int(v.strip()) for v in result[0].split(',')]


def explain_update(cur, sql, params):
    """
    Run EXPLAIN ANALYZE on `sql` and return the server-side execution time
    in milliseconds.  Returns None if the timing line is not found.
    """
    cur.execute(f"EXPLAIN ANALYZE {sql}", params)
    for row in cur.fetchall():
        line = row[0]
        if line.startswith("Execution Time:"):
            return float(line.split(":")[1].strip().replace(" ms", ""))
    return None


def build_restrict_ops(cur, dict_name, evidence):
    """
    Translate a list of evidence triples into three operation lists:

      false_ops  — (variable, value) pairs to restrict FALSE
      true_ops   — (variable, value) pairs to restrict TRUE
      dict_dels  — dictionary deletion keys ('var=val' or 'var=*')

    FALSE operations must be applied before TRUE ones (see module docstring).
    """
    false_ops = []
    true_ops  = []
    dict_dels = []

    for variable, chosen_value, positive in evidence:
        if positive:
            # Observe variable=chosen_value as TRUE:
            # restrict every other value to FALSE first, then chosen_value to TRUE.
            all_values = get_all_values(cur, dict_name, variable)
            for val in all_values:
                if val != chosen_value:
                    false_ops.append((variable, val))
            true_ops.append((variable, chosen_value))
            dict_dels.append(f"{variable}=*")   # remove entire variable from dict
        else:
            # Observe variable=chosen_value as FALSE:
            # restrict only that RVA to FALSE.
            false_ops.append((variable, chosen_value))
            all_values = get_all_values(cur, dict_name, variable)
            remaining  = [v for v in all_values if v != chosen_value]
            if len(remaining) == 1:
                # Only one value remains — it is now certain; promote it TRUE.
                true_ops.append((variable, remaining[0]))
                dict_dels.append(f"{variable}=*")
            else:
                dict_dels.append(f"{variable}={chosen_value}")

    return false_ops, true_ops, dict_dels


# ── Single-evidence conditioning (reference implementation) ───────────────────

def condition_table(table, dict_name, variable, chosen_value, positive):
    """
    Condition `table` on a single piece of evidence.

    Issues one UPDATE per restrict() call, so the table is scanned once per
    call.  Included for reference and manual inspection; condition_batch is
    preferred for benchmarking because it batches all restrict calls into one
    table scan.
    """
    conn      = get_connection()
    cur       = conn.cursor()
    total_ms  = 0.0

    false_ops, true_ops, dict_dels = build_restrict_ops(
        cur, dict_name, [(variable, chosen_value, positive)]
    )

    for var, val in false_ops:
        sql = f'UPDATE "pp2526_49"."{table}" SET _sentence = restrict(_sentence, %s, %s, FALSE)'
        ms  = explain_update(cur, sql, (var, val))
        print(f"restrict({var}={val}, FALSE): {ms:.3f} ms")
        total_ms += ms

    for var, val in true_ops:
        sql = f'UPDATE "pp2526_49"."{table}" SET _sentence = restrict(_sentence, %s, %s, TRUE)'
        ms  = explain_update(cur, sql, (var, val))
        print(f"restrict({var}={val}, TRUE): {ms:.3f} ms")
        total_ms += ms

    for dict_del in dict_dels:
        dict_sql = 'UPDATE "pp2526_49"."_dict" SET dict = del(dict, %s) WHERE name = %s'
        ms = explain_update(cur, dict_sql, (dict_del, dict_name))
        print(f"dict del({dict_del}): {ms:.3f} ms")
        total_ms += ms

    conn.commit()

    print(f"\nTotal conditioning time: {total_ms:.3f} ms")
    print(f"Table: {table} | Variable: {variable}={chosen_value} | Positive: {positive}")
    print(f"\nDictionary after conditioning:")
    cur.execute(
        'SELECT print(dict) FROM "pp2526_49"."_dict" WHERE name = %s;',
        (dict_name,),
    )
    print(cur.fetchone()[0])

    cur.close()
    conn.close()


# ── Batched conditioning (used by benchmark.py and effectiveness.py) ──────────

def condition_batch(table, dict_name, evidence, silent=False):
    """
    Condition `table` on a batch of evidence items in a single table scan.

    All restrict() calls are chained into one nested SQL expression, so the
    BDD table is scanned exactly once regardless of batch size.  The
    probability dictionary is updated in a separate step (one SQL UPDATE per
    evidence item; the dictionary is always a single row so this is fast).

    Parameters
    ----------
    table     : str   — name of the BDD table to condition
    dict_name : str   — name of the dictionary row in _dict
    evidence  : list  — list of (variable, value, positive) triples
    silent    : bool  — suppress per-call print output (used by benchmark.py)

    Returns
    -------
    (restrict_ms, dict_ms) : tuple[float, float]
        Server-side execution times for the BDD UPDATE and the dictionary
        updates respectively, in milliseconds.
    """
    conn = get_connection()
    cur  = conn.cursor()

    false_ops, true_ops, dict_dels = build_restrict_ops(cur, dict_name, evidence)

    # Build one nested restrict() expression: FALSE ops first, then TRUE.
    expr   = "_sentence"
    params = []
    for var, val in false_ops:
        expr = f"restrict({expr}, %s, %s, FALSE)"
        params.extend([var, val])
    for var, val in true_ops:
        expr = f"restrict({expr}, %s, %s, TRUE)"
        params.extend([var, val])

    # Single UPDATE — one full table scan regardless of evidence batch size.
    sql         = f'UPDATE "pp2526_49"."{table}" SET _sentence = {expr}'
    restrict_ms = explain_update(cur, sql, params)
    if not silent:
        print(f"Batch restrict ({len(false_ops)} FALSE, {len(true_ops)} TRUE): "
              f"{restrict_ms:.3f} ms")

    # Dictionary updates — loop over deletion keys (dictionary is one row).
    dict_ms = 0.0
    for dict_del in dict_dels:
        dict_sql = (
            'UPDATE "pp2526_49"."_dict" SET dict = del(dict, %s) WHERE name = %s'
        )
        ms = explain_update(cur, dict_sql, (dict_del, dict_name))
        dict_ms += ms
    if not silent:
        print(f"Dict updates: {dict_ms:.3f} ms")

    conn.commit()
    total_ms = restrict_ms + dict_ms

    if not silent:
        print(f"\nBDD conditioning time:  {restrict_ms:.3f} ms")
        print(f"Dict conditioning time: {dict_ms:.3f} ms")
        print(f"Total conditioning time: {total_ms:.3f} ms")
        print(f"Table: {table} | Evidence: {evidence}")
        print(f"\nDictionary after conditioning:")
        cur.execute(
            'SELECT print(dict) FROM "pp2526_49"."_dict" WHERE name = %s;',
            (dict_name,),
        )
        print(cur.fetchone()[0])

    cur.close()
    conn.close()

    # Return separate times so callers can analyse BDD and dict costs independently.
    return restrict_ms, dict_ms
