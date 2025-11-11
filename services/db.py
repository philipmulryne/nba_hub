# services/db.py

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DB_URL = os.getenv(
    "NBA_DB_URL",
    "postgresql://philipmulryne:YOUR_PASSWORD@localhost:5432/basketball_data",
)

engine = create_engine(DB_URL, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
