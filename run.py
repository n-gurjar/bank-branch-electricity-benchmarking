"""Run the full pipeline: SQL analysis (DuckDB), then the Python model. Writes results/summary.txt."""
import re
from pathlib import Path
import duckdb
import os

os.chdir(Path(__file__).parent)
Path("results").mkdir(exist_ok=True)

def run_sql(path):
    con = duckdb.connect()
    sql = re.sub(r"--[^\n]*", "", Path(path).read_text())
    out = []
    for stmt in (s for s in sql.split(";") if s.strip()):
        res = con.execute(stmt)
        if res.description and not stmt.strip().upper().startswith(("CREATE", "COPY")):
            out.append(res.df().to_string(index=False))
    return out

if __name__ == "__main__":
    sql_out = run_sql("sql/analysis.sql")
    print("\n\n".join(sql_out), "\n")
    from src.model import main as model_main
    model_lines = model_main()
    import src.figures  # noqa: F401  (writes figures/*.png)
    Path("results/summary.txt").write_text("== SQL ==\n\n" + "\n\n".join(sql_out) + "\n\n" + "\n".join(model_lines) + "\n")
