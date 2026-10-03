"""Estimate electricity for branches with no meter data (tier 3) and roll up the portfolio.

Trains a log-intensity OLS regression on complete (tier 1, non-solar) branches exported by
sql/analysis.sql, validates it with 5-fold cross-validation against a format-median benchmark,
then combines metered + annualized + modeled kWh into portfolio totals and Scope 2 emissions.
"""
import warnings
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")  # in_store and host_building_system HVAC are collinear by design

# eGRID2022 U.S. average CO2 output rate (lb/MWh). Swap for state or subregion factors for precision.
EGRID_LB_PER_MWH = 823.1
FORMULA = (
    "leui ~ C(branch_format) + C(hvac_system) + C(lighting) + age + weekly_operating_hours"
    " + atm_count + C(atm_vestibule_24h) + drive_thru_lanes + lsqft + C(state)"
)


def prep(df):
    df = df.copy()
    df["age"] = 2025 - df["year_built"]
    df["lsqft"] = np.log(df["gross_floor_area_sqft"])
    return df


def predict_kwh(model, df):
    # exp(mse/2) corrects the retransformation bias from predicting in log space
    return np.exp(model.predict(df)) * df["gross_floor_area_sqft"] * np.exp(model.mse_resid / 2)


def main():
    train = prep(pd.read_csv("results/tier1_training.csv"))
    train["leui"] = np.log(train["eui"])
    tier3 = prep(pd.read_csv("results/tier3_features.csv"))

    # Cross-validation: regression vs. format-median benchmark
    ape_model, ape_bench = [], []
    for tr, te in KFold(5, shuffle=True, random_state=0).split(train):
        a, b = train.iloc[tr], train.iloc[te]
        m = smf.ols(FORMULA, a).fit()
        ape_model += list(abs(predict_kwh(m, b) - b.kwh) / b.kwh)
        med = a.groupby("branch_format").eui.median()
        ape_bench += list(abs(b.branch_format.map(med) * b.gross_floor_area_sqft - b.kwh) / b.kwh)

    model = smf.ols(FORMULA, train).fit()
    tier3["kwh"] = predict_kwh(model, tier3)
    tier3[["site_id", "kwh"]].to_csv("results/tier3_modeled.csv", index=False)

    p = model.params
    elec_vs_gas = np.exp(p["C(hvac_system)[T.rtu_electric_heat]"] - p["C(hvac_system)[T.rtu_gas_heat]"]) - 1

    metered = pd.read_csv("results/tier1_annual.csv").kwh.sum()
    annualized = pd.read_csv("results/tier2_annualized.csv").kwh.sum()
    modeled = tier3.kwh.sum()
    total = metered + annualized + modeled
    tco2 = total / 1000 * EGRID_LB_PER_MWH / 2204.62

    lines = [
        "== Model ==",
        f"R-squared: {model.rsquared:.2f}",
        f"CV median abs. error: regression {np.median(ape_model):.1%} vs format-median {np.median(ape_bench):.1%}",
        f"Electric-resistance RTU vs gas RTU (kWh/sq ft, controlled): {elec_vs_gas:+.0%}",
        "",
        "== Portfolio roll-up ==",
        f"Metered (tier 1):     {metered/1e6:8.1f} GWh",
        f"Annualized (tier 2):  {annualized/1e6:8.1f} GWh",
        f"Modeled (tier 3):     {modeled/1e6:8.1f} GWh",
        f"Total:                {total/1e6:8.1f} GWh  ({metered/total:.0%} metered)",
        f"Scope 2 (location-based, eGRID2022 US avg): {tco2:,.0f} tCO2",
        "Note: 12 tier-3 branches have on-site solar; the model estimates their gross use, not net purchases.",
    ]
    print("\n".join(lines))
    return lines


if __name__ == "__main__":
    main()
