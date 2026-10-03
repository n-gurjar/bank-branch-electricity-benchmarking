-- Bank Branch Electricity Benchmarking — SQL (DuckDB)
CREATE OR REPLACE TABLE branches AS SELECT * FROM read_csv_auto('data/branch_portfolio.csv');
CREATE OR REPLACE TABLE monthly  AS SELECT * FROM read_csv_auto('data/monthly_consumption.csv');

-- 1. Profiling
SELECT COUNT(*) AS branches, COUNT(DISTINCT state) AS states FROM branches;
SELECT COUNT(*) AS records, COUNT(DISTINCT energy_type) AS fuels FROM monthly;
SELECT data_tier, COUNT(*) AS branches FROM branches GROUP BY 1 ORDER BY 1;

CREATE OR REPLACE VIEW elec AS
SELECT m.site_id, m.month, m.quantity AS kwh, b.*  EXCLUDE (site_id)
FROM monthly m JOIN branches b USING (site_id)
WHERE m.energy_type = 'electricity';

-- 2. QC: zero-kWh months and the solar link
SELECT COUNT(*) AS zero_months, COUNT(DISTINCT site_id) AS sites,
       SUM(CASE WHEN onsite_solar_kw > 0 THEN 1 ELSE 0 END) AS rows_at_solar_sites
FROM elec WHERE kwh = 0;

-- 3. Annual intensity for complete (tier 1) sites
CREATE OR REPLACE TABLE t1_annual AS
SELECT site_id, branch_format, gross_floor_area_sqft, onsite_solar_kw,
       SUM(kwh) AS kwh, SUM(kwh)/gross_floor_area_sqft AS eui
FROM elec WHERE data_tier = 1
GROUP BY site_id, branch_format, gross_floor_area_sqft, onsite_solar_kw;

-- 4. Outliers (3x IQR)
WITH q AS (SELECT quantile_cont(eui,0.25) q1, quantile_cont(eui,0.75) q3 FROM t1_annual)
SELECT COUNT(*) AS outliers,
       SUM(CASE WHEN branch_format='drive_thru_only' THEN 1 ELSE 0 END) AS drive_thru_only
FROM t1_annual, q WHERE eui < q1-3*(q3-q1) OR eui > q3+3*(q3-q1);

-- 5. State seasonal profile (non-solar tier 1)
CREATE OR REPLACE TABLE season AS
SELECT state, month, SUM(kwh) / SUM(SUM(kwh)) OVER (PARTITION BY state) AS share
FROM elec WHERE data_tier = 1 AND onsite_solar_kw = 0
GROUP BY state, month;

-- 6. Backtest: hide months on tier-1 sites, compare linear vs seasonal annualization
--    (deterministic window: months 1..k where k = 3 + hash(site) % 6)
CREATE OR REPLACE TABLE bt AS
WITH s AS (
  SELECT site_id, state, 3 + (hash(site_id) % 6) AS k FROM branches
  WHERE data_tier = 1 AND onsite_solar_kw = 0),
obs AS (
  SELECT e.site_id, s.k, SUM(e.kwh) AS obs_kwh, SUM(se.share) AS obs_share
  FROM elec e JOIN s USING (site_id)
  JOIN season se ON se.state = e.state AND se.month = e.month
  WHERE CAST(right(e.month,2) AS INT) <= s.k
  GROUP BY e.site_id, s.k),
tru AS (SELECT site_id, SUM(kwh) AS true_kwh FROM elec WHERE data_tier=1 GROUP BY 1)
SELECT o.site_id,
       ABS(o.obs_kwh*12.0/o.k - t.true_kwh)/t.true_kwh AS err_linear,
       ABS(o.obs_kwh/o.obs_share - t.true_kwh)/t.true_kwh AS err_seasonal
FROM obs o JOIN tru t USING (site_id) WHERE t.true_kwh > 0;
SELECT COUNT(*) AS sites, median(err_linear) AS mdape_linear, median(err_seasonal) AS mdape_seasonal FROM bt;

-- 7. Annualize partial (tier 2) sites with seasonal profile
CREATE OR REPLACE TABLE t2_annual AS
SELECT e.site_id, SUM(e.kwh) / SUM(se.share) AS kwh
FROM elec e JOIN season se ON se.state = e.state AND se.month = e.month
WHERE e.data_tier = 2 GROUP BY e.site_id;

-- 8. Savings potential: tier-1 sites above their format median
WITH med AS (SELECT branch_format, median(eui) AS m FROM t1_annual GROUP BY 1),
sav AS (
  SELECT site_id, GREATEST(eui - m, 0) * gross_floor_area_sqft AS sav_kwh
  FROM t1_annual JOIN med USING (branch_format)),
ranked AS (
  SELECT sav_kwh, SUM(sav_kwh) OVER (ORDER BY sav_kwh DESC) / SUM(sav_kwh) OVER () AS cum
  FROM sav WHERE sav_kwh > 0)
SELECT COUNT(*) AS above_median_sites, SUM(sav_kwh)/1e6 AS savings_gwh,
       SUM(sav_kwh)/(SELECT SUM(kwh) FROM t1_annual) AS pct_of_metered,
       SUM(CASE WHEN cum <= 0.5 THEN 1 ELSE 0 END)+1 AS sites_for_half
FROM ranked;

-- 9. Export tier-3 feature table for the Python regression
COPY (SELECT * FROM branches WHERE data_tier = 3) TO 'results/tier3_features.csv' (HEADER);
COPY (SELECT a.kwh, a.eui, b.* FROM t1_annual a JOIN branches b USING (site_id) WHERE a.onsite_solar_kw = 0)
  TO 'results/tier1_training.csv' (HEADER);
-- Totals (metered + annualized; modeled tier 3 added after regression)
SELECT (SELECT SUM(kwh) FROM t1_annual)/1e6 AS metered_gwh, (SELECT SUM(kwh) FROM t2_annual)/1e6 AS annualized_gwh;

-- 10. Export metered and annualized totals for the final roll-up in Python
COPY (SELECT site_id, kwh FROM t1_annual) TO 'results/tier1_annual.csv' (HEADER);
COPY (SELECT * FROM t2_annual) TO 'results/tier2_annualized.csv' (HEADER);
