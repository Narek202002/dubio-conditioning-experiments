# DuBio Conditioning Experiments

Experiment scripts for the paper **"Scalability and Effectiveness of Conditioning in a BDD-Based Probabilistic Database: An Empirical Evaluation"** (Narek Moradian, TScIT 45, University of Twente, 2026).

These scripts measure the scalability and effectiveness of conditioning in [DuBio](https://github.com/utwente-db/DuBio), a BDD-based probabilistic database built on PostgreSQL.

---

## Requirements

- Python 3.11+
- PostgreSQL with the DuBio extension installed — see the [DuBio repository](https://github.com/utwente-db/DuBio) for installation instructions
- Install Python dependencies:

```bash
pip install -r requirements.txt
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your PostgreSQL connection details:

```bash
cp .env.example .env
```

```
DB_HOST=your-postgres-host
DB_PORT=5432
DB_NAME=your_database_name
DB_USER=your_username
DB_PASSWORD=your_password
```

---

## File Overview

| File | Description |
|------|-------------|
| `connect.py` | Database connection helper; reads credentials from `.env` |
| `generate.py` | Generates synthetic probabilistic BDD tables and dictionaries |
| `condition.py` | Core conditioning logic (`condition_batch` and `condition_table`) |
| `benchmark.py` | RQ1 — scalability experiment (timing across row/variable/value/evidence configurations) |
| `effectiveness.py` | RQ2/RQ3 — effectiveness experiment (precision, recall, F1 under incremental evidence) |
| `reset.py` | Restores the original DuBio demo tables (`drives`, `saw`, `mydict`) |

---

## Running the Experiments

**Sanity check** (small table, verifies everything works end-to-end):
```bash
python benchmark.py  # calls run_sanity_check() if you swap __main__
```

**RQ1 — Scalability:**
```bash
python benchmark.py
```
Edit `ROW_SIZES`, `VARIABLE_COUNTS`, `VALUE_COUNTS`, and `EXPRESSION_TYPE` at the top of `benchmark.py` to configure the sweep. Run separately for each expression type (`and_heavy`, `or_heavy`, `random`).

**RQ2/RQ3 — Effectiveness:**
```bash
python effectiveness.py
```
Edit `EXPRESSION_TYPES`, `EVIDENCE_TYPES`, and `SEEDS` at the top of `effectiveness.py` to configure the sweep.

---

## Evidence Format

Evidence items are triples `(variable, value, positive)`:
- `('a', 1, True)` — variable `a` is observed to equal `1` (all other values restricted FALSE)
- `('b', 2, False)` — variable `b` is observed to NOT equal `2` (only that value restricted FALSE)

---

## Note on Database Access

These experiments were run on a PostgreSQL server hosted at the University of Twente with the DuBio extension installed. That server is not publicly accessible. To run the scripts yourself you will need your own PostgreSQL instance with DuBio installed. See the [DuBio repository](https://github.com/utwente-db/DuBio) for installation instructions.

---

## License

MIT — see [LICENSE](LICENSE).
