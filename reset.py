# Copyright (c) 2026 Narek Moradian, University of Twente.
# Released under the MIT License. See LICENSE for details.
#
# reset.py
# --------
# Restores the original DuBio demonstration tables and dictionary to their
# pre-experiment state on the configured PostgreSQL server.
#
# This script is NOT part of the RQ1/RQ2/RQ3 experiment pipeline.  It exists
# solely to undo any manual exploration or ad-hoc conditioning done against the
# built-in 'drives', 'saw', and 'mydict' objects that ship with the DuBio
# example database, so the server can be returned to a clean baseline.
#
# The data here matches the car-witness entity-resolution example from the DuBio
# documentation:
#   drives: witness-sighting entity candidates with BDD sentences d1=1, d2=1, …
#   saw:    witness observations with BDD sentences s1=1, s1=2, s1=3, …
#   mydict: probability dictionary for all d* and s* variables

from connect import get_connection


def reset():
    """
    Truncate and repopulate the 'drives', 'saw', and '_dict' tables with
    the original DuBio demonstration data.
    """
    conn = get_connection()
    cur  = conn.cursor()

    # ── drives ────────────────────────────────────────────────────────────────
    cur.execute('DELETE FROM "pp2526_49"."drives";')
    cur.execute("""
        INSERT INTO "pp2526_49"."drives" (id, person, color, car, _sentence) VALUES
            (1, 'frank', 'red',   'toyota', 'd1=1'),
            (1, 'frank', 'blue',  'toyota', 'd1=2'),
            (2, 'billy', 'blue',  'honda',  'd2=1'),
            (3, 'jimmy', 'green', 'mazda',  'd3=1'),
            (3, 'johnny','green', 'mazda',  'd3=2');
    """)

    # ── saw ───────────────────────────────────────────────────────────────────
    cur.execute('DELETE FROM "pp2526_49"."saw";')
    cur.execute("""
        INSERT INTO "pp2526_49"."saw" (id, witness, color, car, _sentence) VALUES
            (1, 'amy',   'blue',  'honda',  's1=1'),
            (1, 'amy',   'red',   'toyota', 's1=2'),
            (1, 'amy',   'green', 'toyota', 's1=3'),
            (2, 'betty', 'green', 'mazda',  's2=1'),
            (2, 'betty', 'green', 'toyota', 's2=2'),
            (2, 'betty', 'green', 'honda',  's2=3'),
            (2, 'betty', 'green', 'accura', 's2=4'),
            (3, 'cathy', 'red',   'acura',  's3=1'),
            (4, 'diane', 'red',   'toyota', 's4=1'),
            (4, 'diane', 'blue',  'toyota', 's4=2');
    """)

    # ── dictionary ───────────────────────────────────────────────────────────
    cur.execute("""
        UPDATE "pp2526_49"."_dict"
        SET dict = dictionary('')
        WHERE name = 'mydict';
    """)
    cur.execute("""
        UPDATE "pp2526_49"."_dict"
        SET dict = add(dict,
            'd1=1:0.8; d1=2:0.2; d2=1:0.7; d2=2:0.3; d3=1:0.5; d3=2:0.5; '
            's1=1:0.7; s1=2:0.2; s1=3:0.1; '
            's2=1:0.25; s2=2:0.25; s2=3:0.25; s2=4:0.25; '
            's3=1:0.6; s3=2:0.4; s4=1:0.9; s4=2:0.1')
        WHERE name = 'mydict';
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("Reset complete.")


if __name__ == "__main__":
    reset()
