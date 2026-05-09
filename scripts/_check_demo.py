import sqlite3
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "data/demo.db"
c = sqlite3.connect(path)
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print(f"DB: {path}")
print(f"Tables ({len(tables)}):", ", ".join(tables) or "<aucune>")
for t in ("collection", "item", "fichier"):
    if t in tables:
        n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} rows")
