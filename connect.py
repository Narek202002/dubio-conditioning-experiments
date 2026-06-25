# Copyright (c) 2026 Narek Moradian, University of Twente.
# Released under the MIT License. See LICENSE for details.
#
# connect.py
# ----------
# Database connection helper for the DuBio conditioning experiments.
#
# Reads PostgreSQL connection parameters from environment variables so that
# credentials are never hard-coded in the repository. Copy .env.example to
# .env, fill in your values, and either source it or install python-dotenv
# (already listed in requirements.txt) so it is loaded automatically.
#
# Required environment variables:
#   DB_HOST      — PostgreSQL server hostname
#   DB_PORT      — PostgreSQL port (default: 5432)
#   DB_NAME      — database name
#   DB_USER      — database user
#   DB_PASSWORD  — database password

import os
import psycopg2
from dotenv import load_dotenv

# Load variables from a .env file if one exists in the working directory.
# Has no effect when the variables are already set in the shell environment.
load_dotenv()

DB_HOST     = os.environ["DB_HOST"]
DB_PORT     = int(os.environ.get("DB_PORT", 5432))
DB_NAME     = os.environ["DB_NAME"]
DB_USER     = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]


def get_connection():
    """Return a new psycopg2 connection using the configured credentials."""
    conn = psycopg2.connect(
        host     = DB_HOST,
        port     = DB_PORT,
        dbname   = DB_NAME,
        user     = DB_USER,
        password = DB_PASSWORD,
    )
    return conn


if __name__ == "__main__":
    # Quick smoke-test: verify the connection parameters work.
    try:
        conn = get_connection()
        print("Connected successfully!")
        conn.close()
    except Exception as e:
        print(f"Connection failed: {e}")
