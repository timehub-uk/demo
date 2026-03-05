#!/usr/bin/env python3
"""
Database initialisation script.
Run once after PostgreSQL is set up:
    python scripts/init_db.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.models import Base
from sqlalchemy import create_engine

DB_URL = "postgresql+psycopg2://binanceml:binanceml@localhost:5432/binanceml"

def main():
    print("Creating all database tables…")
    engine = create_engine(DB_URL)
    Base.metadata.create_all(engine)
    print("✅ Done.")

if __name__ == "__main__":
    main()
