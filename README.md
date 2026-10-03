# Bank Branch Electricity Benchmarking

Estimating annual electricity use and Scope 2 emissions for a 4,000-branch U.S. bank portfolio where 27% of branches have no meter data and another 20% have only partial-year data.

> **Data note:** This is a learning case study built on a **synthetic dataset** that simulates a realistic bank branch portfolio (formats, HVAC types, metering arrangements, data gaps). No real company or client data is used.

## Results

| Metric | Value |
|---|---|
| Portfolio electricity | **314 GWh** (58% metered, 20% annualized, 22% modeled) |
| Scope 2, location-based | **~117,000 tCO₂** (eGRID2022 U.S. average) |
| Seasonal vs. linear annualization error | **2.1% vs. 4.6%** median (backtest, 2,047 sites) |
| Regression for unmetered branches | **R² = 0.72**, 12.3% median error vs. 17.7% for a format-median benchmark |
| Electric-resistance vs. gas-heat rooftop units | **+58%** electricity per sq ft, controlling for size, format, hours, and location |
| Savings if above-median branches reach format median | **25.6 GWh** (14% of metered use); half from **150 sites** |

## The problem

Branches fall into three data tiers:

| Tier | Branches | Electricity data |
|---|---|---|
| 1 | 2,108 | All 12 months |
| 2 | 810 | 3–8 consecutive months |
| 3 | 1,082 | None (landlord-paid or shared, unmetered) |

A portfolio total that only sums the bills undercounts by about 40%. The job is to fill the gaps with methods that are tested, not assumed.

## Method

All data work is in SQL (DuckDB); only the regression is in Python.

1. **Profile** (`sql/analysis.sql` §1): 4,000 branches, 50 states + DC, 50,312 monthly records across 5 fuel types.
2. **Quality checks** (§2, §4): 202 zero-kWh months traced to 30 net-metered solar sites, so these are real readings, not errors. 14 intensity outliers (3×IQR); 11 are small drive-thru branches where kWh/sq ft is naturally high. Both kept.
3. **Seasonal profiles** (§5): each state's monthly share of annual use, from complete non-solar branches, via window functions.
4. **Backtest** (§6): hide months on complete branches, annualize the rest two ways, compare against the true total. Seasonal scaling halves the error because partial years that miss summer understate annual use.
5. **Annualize tier 2** (§7) using the seasonal method.
6. **Model tier 3** (`src/model.py`): OLS on log(kWh/sq ft) with format, HVAC, lighting, building age, operating hours, ATMs, drive-thru lanes, floor area, and state. Validated with 5-fold cross-validation.
7. **Savings potential** (§8): gap between each branch and its format median, ranked to find where savings concentrate.

## Repo structure

```
data/                     synthetic input CSVs
sql/analysis.sql          profiling, QC, backtest, annualization, savings (DuckDB)
src/model.py              regression, cross-validation, portfolio roll-up
run.py                    runs everything, writes results/summary.txt
results/                  outputs (summary.txt committed; CSVs regenerated)
```

## Run it

```bash
pip install -r requirements.txt
python run.py
```

## Limitations

- **Emission factor:** uses a single U.S. average. State or eGRID subregion factors would be more accurate and would change the tCO₂ figure.
- **Solar sites:** 12 unmetered branches have on-site solar. The model estimates their gross consumption, not net grid purchases, so it slightly overstates them.
- **Synthetic data:** relationships in the data were designed by a generator. Findings demonstrate the method, not real-world bank energy patterns.
