"""Generate README charts into figures/. Run after sql/analysis.sql and src/model.py (run.py does this)."""
import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

NAVY, AMBER, TEAL, SLATE, PALE = "#14213D", "#F4A300", "#2A9D8F", "#8D99AE", "#CBD3DE"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.spines.left": False, "axes.edgecolor": SLATE,
                     "axes.titleweight": "bold", "axes.titlesize": 13, "axes.titlelocation": "left"})

con = duckdb.connect()
con.execute("CREATE TABLE b AS SELECT * FROM read_csv_auto('data/branch_portfolio.csv')")
con.execute("CREATE TABLE m AS SELECT * FROM read_csv_auto('data/monthly_consumption.csv')")
con.execute("""CREATE TABLE t1 AS
  SELECT m.site_id, b.branch_format, b.hvac_system, b.onsite_solar_kw, b.gross_floor_area_sqft AS sqft,
         SUM(m.quantity) AS kwh, SUM(m.quantity) / b.gross_floor_area_sqft AS eui
  FROM m JOIN b USING (site_id) WHERE m.energy_type = 'electricity' AND b.data_tier = 1
  GROUP BY m.site_id, b.branch_format, b.hvac_system, b.onsite_solar_kw, b.gross_floor_area_sqft""")


def title(fig, text):
    fig.suptitle(text, x=0.02, ha="left", fontweight="bold", fontsize=13, color=NAVY)


def finish(ax, path, fmt="{:,.0f}", horizontal=False):
    if horizontal:
        ax.set_xticks([]); ax.set_xlim(0, ax.get_xlim()[1] * 1.12)
    else:
        ax.set_yticks([]); ax.set_ylim(0, ax.get_ylim()[1] * 1.15)
    for c in ax.containers:
        ax.bar_label(c, labels=[fmt.format(v) for v in c.datavalues], padding=3, color=NAVY)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


# 1. Coverage
tiers = dict(con.execute("SELECT data_tier, COUNT(*) FROM b GROUP BY 1").fetchall())
fig, ax = plt.subplots(figsize=(7, 3.6))
ax.bar(["Complete (12 mo)", "Partial (3–8 mo)", "No meter data"], [tiers[1], tiers[2], tiers[3]], color=[TEAL, SLATE, AMBER], width=0.6)
title(fig, "Only half the branches report a full year of electricity")
finish(ax, "figures/01_coverage.png")

# 2. Validation (values from the SQL backtest and model cross-validation)
fig, ax = plt.subplots(figsize=(7, 3.6))
x = [0, 1]
ax.bar([i - 0.18 for i in x], [4.6, 17.7], 0.36, color=PALE, label="Simple alternative")
ax.bar([i + 0.18 for i in x], [2.1, 12.3], 0.36, color=AMBER, label="Chosen method")
ax.set_xticks(x, ["Partial-year branches\n(seasonal vs linear)", "Unmetered branches\n(regression vs format median)"])
title(fig, "Median absolute error (%): each method beat its alternative")
ax.legend(frameon=False, loc="upper left")
finish(ax, "figures/02_validation.png", "{:.1f}%")

# 3. Portfolio roll-up
import pandas as pd
parts = {"Metered": pd.read_csv("results/tier1_annual.csv").kwh.sum() / 1e6,
         "Annualized": pd.read_csv("results/tier2_annualized.csv").kwh.sum() / 1e6,
         "Modeled": pd.read_csv("results/tier3_modeled.csv").kwh.sum() / 1e6}
fig, ax = plt.subplots(figsize=(5.5, 4))
ax.pie(parts.values(), labels=[f"{k}\n{v:.0f} GWh" for k, v in parts.items()], colors=[TEAL, SLATE, AMBER],
       startangle=90, counterclock=False, wedgeprops={"width": 0.38, "edgecolor": "white"})
ax.text(0, 0, f"{sum(parts.values()):.0f}\nGWh", ha="center", va="center", fontsize=18, fontweight="bold", color=NAVY)
title(fig, "Portfolio electricity: 42% estimated")
plt.tight_layout(); plt.savefig("figures/03_portfolio.png", dpi=160); plt.close()

# 4. HVAC intensity
names = {"boiler_with_split_ac": "Gas boiler + split AC", "rtu_gas_heat": "Gas rooftop unit",
         "split_ac_gas_furnace": "Gas furnace + split AC", "heat_pump": "Heat pump",
         "host_building_system": "Host building system", "rtu_electric_heat": "Electric-resistance RTU"}
hv = con.execute("SELECT hvac_system, median(eui) FROM t1 WHERE onsite_solar_kw = 0 GROUP BY 1 ORDER BY 2").fetchall()
fig, ax = plt.subplots(figsize=(7, 3.8))
ax.barh([names[h] for h, _ in hv], [v for _, v in hv],
        color=[AMBER if h == "rtu_electric_heat" else SLATE if v > 20 else PALE for h, v in hv], height=0.6)
ax.spines["bottom"].set_visible(False)
title(fig, "Median electricity intensity by HVAC type (kWh/sq ft/yr)")
finish(ax, "figures/04_hvac_intensity.png", "{:.1f}", horizontal=True)

# 5. Savings concentration
sav = con.execute("""
  WITH med AS (SELECT branch_format, median(eui) m FROM t1 GROUP BY 1)
  SELECT GREATEST(eui - m, 0) * sqft AS s FROM t1 JOIN med USING (branch_format) WHERE eui > m ORDER BY s DESC
""").df().s
tot = sav.sum()
bands = [("Top 150", 0, 150), ("151–250", 150, 250), ("251–500", 250, 500), (f"501–{len(sav):,}", 500, len(sav))]
fig, ax = plt.subplots(figsize=(7, 3.6))
ax.bar([b[0] for b in bands], [sav.iloc[a:z].sum() / tot * 100 for _, a, z in bands], color=[AMBER, PALE, PALE, PALE], width=0.6)
title(fig, f"Share of {tot/1e6:.1f} GWh savings, by branch rank")
finish(ax, "figures/05_savings_concentration.png", "{:.0f}%")
print("figures written")
