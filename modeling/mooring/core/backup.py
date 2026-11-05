"""Local SQLite online backup and offline restore into a NEW path only.

Usage: python -m mooring.core.backup backup SOURCE TARGET
       python -m mooring.core.backup restore BACKUP NEW_TARGET
The destination is never overwritten. Restore migrates and validates the copy;
stop the service before selecting the restored file with MOORING_DB.
"""
from contextlib import closing
import argparse
import os
import sqlite3
from pathlib import Path
from .store import Database


def backup(database: Database, target: str):
    path = Path(target)
    # Exclusive creation prevents accidental overwriting of a live database.
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with database.lock, closing(sqlite3.connect(path)) as dest:
            database.conn.backup(dest)
            if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("backup integrity check failed")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def restore(source: str, target: str):
    if not Path(source).is_file(): raise ValueError("backup source does not exist")
    # Read source without migrating/modifying the backup itself.
    src = sqlite3.connect(Path(source).resolve().as_uri()+"?mode=ro",uri=True)
    try:
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok": raise ValueError("invalid backup")
        fd = os.open(target,os.O_CREAT | os.O_EXCL | os.O_WRONLY,0o600); os.close(fd)
        try:
            with closing(sqlite3.connect(target)) as dest: src.backup(dest)
            d=Database(target)
            d.close()
        except BaseException:
            Path(target).unlink(missing_ok=True)
            raise
    finally: src.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["backup","restore"])
    parser.add_argument("source"); parser.add_argument("target")
    args=parser.parse_args()
    if args.action == "restore": restore(args.source,args.target)
    else:
        if not Path(args.source).is_file(): parser.error("source database does not exist")
        d=Database(args.source)
        try: backup(d,args.target)
        finally: d.close()


if __name__ == "__main__": main()
