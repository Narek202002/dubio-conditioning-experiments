# Copyright (c) 2026 Narek Moradian, University of Twente.
# Released under the MIT License. See LICENSE for details.
#
# effectiveness.py
# ----------------
# RQ2 / RQ3 experiment: expected precision, recall, and F1 under incremental
# cumulative conditioning.
#
# Unlike benchmark.py (which resets the table between runs), here evidence is
# applied cumulatively step by step on a single table — the table is NOT reset
# between steps.  This directly models the real PDI workflow where quality
# improves as evidence accumulates over time.
#
# Evidence types:
#   true_heavy   — one strong item per variable (var, 1, TRUE); resolves the
#                  entire table in NUM_VARS steps.
#   false_heavy  — (NUM_VALUES - 1) weak items per variable ((var, val, FALSE)
#                  for val = 2..NUM_VALUES), one at a time; full resolution
#                  requires all TOTAL_STEPS = NUM_VARS * (NUM_VALUES - 1) steps.
#   random_mixed — per-variable choice (seeded) between the above two styles,
#                  shuffled into one sequence; included for completeness but
#                  note that its trajectories are less interpretable because the
#                  resolution step for each variable differs between seeds.
#
# Ground truth: value 1 is the correct value for every variable.  This is
# arbitrary but fixed and unbiased given that expressions are generated with
# uniform value sampling.
#
# Quality metrics (van Keulen & de Keijzer, 2009):
#   precision = Σ prob(r) for TRUE rows / Σ prob(r) for ALL rows
#   recall    = Σ prob(r) for TRUE rows / |TRUE rows|
#   F1        = 2 * precision * recall / (precision + recall)
#
# Multi-seed averaging: the procedure is repeated for each seed in SEEDS.
# Each seed produces an independently generated table, dictionary, and
# 31-point trajectory.  Precision/recall/F1 are averaged across seeds at
# each step index; standard deviation is reported as a robustness indicator.
#
# Floating-point note: after many cumulative restrict()/renormalise operations,
# pgbdd's internal probability_check can raise an error when rounding pushes a
# value slightly outside [0, 1].  Affected seeds are excluded from the average
# at that configuration; the number of retained seeds is reported in the output.

import random
import statistics
from generate import generate, make_variable_names
from condition import condition_batch
from connect import get_connection

# ── Configuration ─────────────────────────────────────────────────────────────

ROW_SIZES        = [5000]
NUM_VARS         = 10
NUM_VALUES       = 4
EXPRESSION_TYPES = ['or_heavy']   # set to ['random', 'and_heavy', 'or_heavy'] for full sweep
EVIDENCE_TYPES   = ['false_heavy']
SEEDS            = [42, 43, 44, 45, 46, 47, 48, 49, 50, 51]

VARIABLES   = make_variable_names(NUM_VARS)
TOTAL_STEPS = NUM_VARS * (NUM_VALUES - 1)   # steps needed for full determination


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_evidence_schedule(evidence_type, seed):
    """
    Build a TOTAL_STEPS-length schedule of single evidence items (or no-ops).

    All schedule types use the same step budget so their precision/recall
    trajectories are directly comparable; only the rate of convergence differs.

    Returns a list of TOTAL_STEPS lists, each containing zero or one evidence
    triple (variable, value, positive).
    """
    if evidence_type == 'true_heavy':
        # One strong item per variable: resolves each variable in a single step.
        items = [(var, 1, True) for var in VARIABLES]

    elif evidence_type == 'false_heavy':
        # (NUM_VALUES - 1) weak items per variable: removes one wrong value per step.
        items = []
        for var in VARIABLES:
            for val in range(2, NUM_VALUES + 1):
                items.append((var, val, False))

    elif evidence_type == 'random_mixed':
        # Per-variable random choice between true_heavy and false_heavy style.
        rng   = random.Random(seed)
        items = []
        for var in VARIABLES:
            if rng.random() < 0.5:
                items.append((var, 1, True))
            else:
                for val in range(2, NUM_VALUES + 1):
                    items.append((var, val, False))
        rng.shuffle(items)

    else:
        raise ValueError(f"Unknown evidence type: {evidence_type!r}")

    # One item per step; pad with empty (no-op) steps once the table is resolved.
    schedule = [[item] for item in items]
    while len(schedule) < TOTAL_STEPS:
        schedule.append([])
    return schedule


def evaluate_ground_truth(cur, table_name, variables, num_values):
    """
    Label each row TRUE or FALSE under the fixed ground truth (value 1 is
    correct for all variables).

    This is a pure SELECT — the table is NOT modified.  Returns a dict
    mapping row_id → bool.
    """
    expr, params = "_sentence", []
    # Restrict all non-1 values to FALSE …
    for var in variables:
        for val in range(2, num_values + 1):
            expr = f"restrict({expr}, %s, %s, FALSE)"
            params.extend([var, val])
    # … then restrict value 1 to TRUE.
    for var in variables:
        expr = f"restrict({expr}, %s, %s, TRUE)"
        params.extend([var, 1])

    cur.execute(
        f'SELECT id, istrue({expr}) FROM "pp2526_49"."{table_name}"',
        params,
    )
    return {row_id: is_true for row_id, is_true in cur.fetchall()}


def measure_quality(cur, table_name, dict_name, ground_truth):
    """
    Compute expected precision, recall, and F1 at the current conditioning
    state using DuBio's prob() function.

    Returns (precision, recall, f1).
    """
    cur.execute(
        f'SELECT t.id, prob(d.dict, t._sentence) '
        f'FROM "pp2526_49"."{table_name}" t, "pp2526_49"."_dict" d '
        f'WHERE d.name = %s',
        (dict_name,),
    )
    probs    = {row_id: float(p) for row_id, p in cur.fetchall()}
    true_ids = {rid for rid, gt in ground_truth.items() if gt}

    sum_all  = sum(probs.values())
    sum_true = sum(probs.get(rid, 0.0) for rid in true_ids)

    precision = sum_true / sum_all       if sum_all  > 0 else 0.0
    recall    = sum_true / len(true_ids) if true_ids else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0 else 0.0
    )
    return precision, recall, f1


def stdev_or_zero(values):
    """Return the sample standard deviation, or 0.0 for single-element lists."""
    return statistics.stdev(values) if len(values) > 1 else 0.0


# ── Main experiment ───────────────────────────────────────────────────────────

def run_effectiveness():
    """
    Run the effectiveness sweep and print step-by-step precision/recall/F1
    averaged across seeds.

    Returns a list of result tuples:
      (num_rows, expression_type, evidence_type, agg, all_seed_steps)

    where:
      agg            = [(step, prec_mean, prec_std, rec_mean, rec_std,
                         f1_mean, f1_std), …]
      all_seed_steps = [[(step, precision, recall, f1), …] per seed]
    """
    results    = []
    short_type = {'random': 'r', 'and_heavy': 'ah', 'or_heavy': 'oh', 'mixed': 'm'}

    for expression_type in EXPRESSION_TYPES:
        abbr = short_type.get(expression_type, expression_type)

        for evidence_type in EVIDENCE_TYPES:
            for num_rows in ROW_SIZES:
                table_name = f"narek_{num_rows}_{expression_type}"
                dict_name  = f"narek_{num_rows}_{abbr}"

                print(f"\n{'='*60}")
                print(f"Config: {num_rows} rows, {NUM_VARS} variables, "
                      f"{NUM_VALUES} values")
                print(f"Expression type: {expression_type}  |  "
                      f"Evidence type: {evidence_type}")
                print(f"Total steps: {TOTAL_STEPS}  |  Seeds: {SEEDS}")
                print(f"{'='*60}")

                all_seed_steps = []
                failed_seeds   = []

                for seed in SEEDS:
                    # Generate a fresh table for this seed.
                    generate(
                        num_rows        = num_rows,
                        num_variables   = NUM_VARS,
                        num_values      = NUM_VALUES,
                        expression_type = expression_type,
                        seed            = seed,
                    )

                    evidence_schedule = make_evidence_schedule(evidence_type, seed)

                    conn = get_connection()
                    cur  = conn.cursor()

                    # Label rows against the fixed ground truth (SELECT only).
                    ground_truth = evaluate_ground_truth(
                        cur, table_name, VARIABLES, NUM_VALUES
                    )

                    # Step 0: baseline quality before any conditioning.
                    steps       = []
                    seed_failed = False
                    try:
                        precision, recall, f1 = measure_quality(
                            cur, table_name, dict_name, ground_truth
                        )
                        steps.append((0, precision, recall, f1))
                    except Exception as e:
                        conn.rollback()
                        print(f"Seed {seed}: FAILED at baseline ({e}) — skipping")
                        seed_failed = True
                    finally:
                        cur.close()
                        conn.close()

                    # Steps 1..TOTAL_STEPS: apply evidence cumulatively.
                    if not seed_failed:
                        for step, batch in enumerate(evidence_schedule, 1):
                            if batch:
                                # Apply this step's evidence (no-op if batch is empty).
                                condition_batch(
                                    table     = table_name,
                                    dict_name = dict_name,
                                    evidence  = batch,
                                    silent    = True,
                                )

                            conn = get_connection()
                            cur  = conn.cursor()
                            try:
                                precision, recall, f1 = measure_quality(
                                    cur, table_name, dict_name, ground_truth
                                )
                                steps.append((step, precision, recall, f1))
                            except Exception as e:
                                # pgbdd floating-point probability_check failure:
                                # prob value drifts slightly outside [0, 1] after
                                # many cumulative restrict()/renormalise ops.
                                # Exclude this seed to keep step alignment clean.
                                conn.rollback()
                                print(f"Seed {seed}: FAILED at step {step} "
                                      f"({e}) — skipping seed")
                                seed_failed = True
                            finally:
                                cur.close()
                                conn.close()

                            if seed_failed:
                                break

                    if seed_failed:
                        failed_seeds.append(seed)
                        continue

                    print(f"Seed {seed}: done ({len(steps)} steps incl. baseline)")
                    all_seed_steps.append(steps)

                if failed_seeds:
                    print(f"\nWARNING: {len(failed_seeds)} seed(s) failed and "
                          f"were excluded: {failed_seeds}")

                if not all_seed_steps:
                    print(f"\nNo successful seeds for "
                          f"{expression_type} / {evidence_type} — skipping.")
                    results.append((
                        num_rows, expression_type, evidence_type, [], all_seed_steps
                    ))
                    continue

                # Aggregate across seeds: mean ± std dev at each step index.
                num_steps = TOTAL_STEPS + 1
                agg = []
                for step_idx in range(num_steps):
                    precs = [s[step_idx][1] for s in all_seed_steps]
                    recs  = [s[step_idx][2] for s in all_seed_steps]
                    f1s   = [s[step_idx][3] for s in all_seed_steps]
                    agg.append((
                        step_idx,
                        statistics.mean(precs), stdev_or_zero(precs),
                        statistics.mean(recs),  stdev_or_zero(recs),
                        statistics.mean(f1s),   stdev_or_zero(f1s),
                    ))

                # Summary table
                print(f"\n{'='*60}")
                print(f"Summary — {num_rows} rows, {NUM_VARS} vars, "
                      f"{NUM_VALUES} vals, {expression_type} / {evidence_type}, "
                      f"averaged over {len(all_seed_steps)}/{len(SEEDS)} seeds")
                print(f"{'='*60}")
                print(f"{'Step':>6}  {'Precision (mean±std)':>22}  "
                      f"{'Recall (mean±std)':>22}  {'F1 (mean±std)':>22}")
                print(f"{'-'*80}")
                for step_idx, p_mean, p_std, r_mean, r_std, f_mean, f_std in agg:
                    print(f"{step_idx:>6}  "
                          f"{p_mean:>10.4f} ± {p_std:<8.4f}  "
                          f"{r_mean:>10.4f} ± {r_std:<8.4f}  "
                          f"{f_mean:>10.4f} ± {f_std:<8.4f}")

                results.append((
                    num_rows, expression_type, evidence_type, agg, all_seed_steps
                ))

    # Return value structure:
    #   list of (num_rows, expression_type, evidence_type, agg, all_seed_steps)
    #   agg            = [(step_idx, p_mean, p_std, r_mean, r_std, f_mean, f_std), …]
    #   all_seed_steps = [[(step_idx, precision, recall, f1), …] per seed]
    return results


if __name__ == "__main__":
    run_effectiveness()
