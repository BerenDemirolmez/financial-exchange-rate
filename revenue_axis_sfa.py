import json
import math
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import norm


INPUT_WORKBOOK = "/Users/beren/Dropbox/FER_Codex/Revenue/fiscal_space_dataset_20260323.xlsx"
DEFAULT_OUTPUT_WORKBOOK = "/Users/beren/Dropbox/FER_Codex/Revenue/revenue_axis_sfa_results.xlsx"

START_YEAR = 2002
END_YEAR = 2025

COUNTRY_MAP = {
    "Austria": "AUT",
    "Belgium": "BEL",
    "Bulgaria": "BGR",
    "Croatia": "HRV",
    "Cyprus": "CYP",
    "Estonia": "EST",
    "Finland": "FIN",
    "France": "FRA",
    "Germany": "DEU",
    "Greece": "GRC",
    "Ireland": "IRL",
    "Italy": "ITA",
    "Latvia": "LVA",
    "Lithuania": "LTU",
    "Luxembourg": "LUX",
    "Malta": "MLT",
    "Netherlands": "NLD",
    "Portugal": "PRT",
    "Slovakia": "SVK",
    "Slovenia": "SVN",
    "Spain": "ESP",
}

ISO3_TO_COUNTRY = {iso3: country for country, iso3 in COUNTRY_MAP.items()}

WB_INDICATORS = {
    "gdp_pc_ppp": "NY.GDP.PCAP.PP.KD",
    "trade_open_pct_gdp": "NE.TRD.GNFS.ZS",
    "agriculture_pct_gdp": "NV.AGR.TOTL.ZS",
    "education_spend_pct_gdp": "SE.XPD.TOTL.GB.ZS",
    "inflation_cpi_pct": "FP.CPI.TOTL.ZG",
    "gini": "SI.POV.GINI",
}


@dataclass
class SFAFit:
    coefficients: pd.DataFrame
    diagnostics: pd.DataFrame
    fitted: pd.DataFrame


def fetch_wb_indicator(indicator_code: str, iso3_codes: List[str]) -> pd.DataFrame:
    country_arg = ";".join(iso3_codes)
    params = urlencode({"format": "json", "per_page": 20000})
    url = f"https://api.worldbank.org/v2/country/{country_arg}/indicator/{indicator_code}?{params}"

    with urlopen(url) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
        raise ValueError(f"Unexpected World Bank response for indicator {indicator_code}")

    rows = []
    for item in payload[1]:
        year = item.get("date")
        value = item.get("value")
        iso3 = item.get("countryiso3code")
        country = ISO3_TO_COUNTRY.get(iso3)
        if country is None or year is None:
            continue

        try:
            year_num = int(year)
        except (TypeError, ValueError):
            continue

        if year_num < START_YEAR or year_num > END_YEAR:
            continue

        rows.append(
            {
                "Country": country,
                "Year": year_num,
                "indicator_code": indicator_code,
                "value": pd.to_numeric(value, errors="coerce"),
            }
        )

    return pd.DataFrame(rows)


def download_wb_panel() -> Tuple[pd.DataFrame, pd.DataFrame]:
    frames = []
    for label, code in WB_INDICATORS.items():
        frame = fetch_wb_indicator(code, list(COUNTRY_MAP.values()))
        frame["indicator"] = label
        frames.append(frame)

    raw = pd.concat(frames, ignore_index=True)
    wide = (
        raw.pivot_table(index=["Country", "Year"], columns="indicator", values="value", aggfunc="mean")
        .reset_index()
        .sort_values(["Country", "Year"])
    )
    return raw, wide


def load_local_inputs(path: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    tax = pd.read_excel(path, sheet_name="tax_revenue_structured")
    tax = tax[["Country", "Year", "total_taxes_pct_gdp"]].copy()
    tax["Country"] = tax["Country"].astype(str).str.strip()
    tax["Year"] = pd.to_numeric(tax["Year"], errors="coerce")
    tax["total_taxes_pct_gdp"] = pd.to_numeric(tax["total_taxes_pct_gdp"], errors="coerce")
    tax = tax.dropna(subset=["Country", "Year"])
    tax["Year"] = tax["Year"].astype(int)
    tax = tax[(tax["Year"] >= START_YEAR) & (tax["Year"] <= END_YEAR)]
    tax = tax[tax["Country"].isin(COUNTRY_MAP)].copy()

    inst = pd.read_excel(path, sheet_name="institutional_indicators")
    inst = inst[inst["Variable"].astype(str).str.strip() == "GE.EST"].copy()
    inst = inst[["Country", "Year", "Value"]].rename(columns={"Value": "government_effectiveness"})
    inst["Country"] = inst["Country"].astype(str).str.strip()
    inst["Year"] = pd.to_numeric(inst["Year"], errors="coerce")
    inst["government_effectiveness"] = pd.to_numeric(inst["government_effectiveness"], errors="coerce")
    inst = inst.dropna(subset=["Country", "Year"])
    inst["Year"] = inst["Year"].astype(int)
    inst = inst[(inst["Year"] >= START_YEAR) & (inst["Year"] <= END_YEAR)]
    inst = inst[inst["Country"].isin(COUNTRY_MAP)].copy()

    return tax, inst


def interpolate_by_country(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    out = df.sort_values(["Country", "Year"]).copy()
    imputation_flags = {}

    for col in columns:
        original_missing = out[col].isna()
        out[col] = (
            out.groupby("Country")[col]
            .transform(lambda s: s.interpolate(method="linear", limit_direction="both"))
        )
        imputation_flags[f"imputed_{col}"] = original_missing & out[col].notna()

    for flag_col, flag_values in imputation_flags.items():
        out[flag_col] = flag_values

    return out


def build_estimation_panel(input_workbook: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw_wb, wb_panel = download_wb_panel()
    tax, inst = load_local_inputs(input_workbook)

    panel = tax.merge(wb_panel, on=["Country", "Year"], how="left")
    panel = panel.merge(inst, on=["Country", "Year"], how="left")

    panel = interpolate_by_country(
        panel,
        columns=[
            "gdp_pc_ppp",
            "trade_open_pct_gdp",
            "agriculture_pct_gdp",
            "education_spend_pct_gdp",
            "inflation_cpi_pct",
            "gini",
            "government_effectiveness",
        ],
    )

    panel["log_tax_ratio"] = np.log(panel["total_taxes_pct_gdp"])
    panel["log_gdp_pc_ppp"] = np.log(panel["gdp_pc_ppp"])
    panel["log_gdp_pc_ppp_sq"] = panel["log_gdp_pc_ppp"] ** 2

    keep_cols = [
        "Country",
        "Year",
        "total_taxes_pct_gdp",
        "log_tax_ratio",
        "gdp_pc_ppp",
        "log_gdp_pc_ppp",
        "log_gdp_pc_ppp_sq",
        "trade_open_pct_gdp",
        "agriculture_pct_gdp",
        "education_spend_pct_gdp",
        "inflation_cpi_pct",
        "gini",
        "government_effectiveness",
        "imputed_gdp_pc_ppp",
        "imputed_trade_open_pct_gdp",
        "imputed_agriculture_pct_gdp",
        "imputed_education_spend_pct_gdp",
        "imputed_inflation_cpi_pct",
        "imputed_gini",
        "imputed_government_effectiveness",
    ]

    panel = panel[keep_cols].sort_values(["Country", "Year"]).reset_index(drop=True)
    estimation = panel.dropna(
        subset=[
            "log_tax_ratio",
            "log_gdp_pc_ppp",
            "log_gdp_pc_ppp_sq",
            "trade_open_pct_gdp",
            "agriculture_pct_gdp",
            "education_spend_pct_gdp",
            "inflation_cpi_pct",
            "gini",
            "government_effectiveness",
        ]
    ).copy()

    estimation["ge_centered"] = estimation["government_effectiveness"] - estimation["government_effectiveness"].mean()
    panel["ge_centered"] = panel["government_effectiveness"] - estimation["government_effectiveness"].mean()

    return raw_wb, panel, estimation


def sfa_negative_log_likelihood(params: np.ndarray, y: np.ndarray, x: np.ndarray, z: np.ndarray) -> float:
    k = x.shape[1]
    beta = params[:k]
    log_sigma_v = params[k]
    log_sigma_u = params[k + 1]
    delta = params[k + 2 :]

    sigma_v = math.exp(log_sigma_v)
    sigma_u_base = math.exp(log_sigma_u)
    sigma_u = sigma_u_base * np.exp(z @ delta)

    eps = y - x @ beta
    sigma = np.sqrt(sigma_v ** 2 + sigma_u ** 2)
    lam = sigma_u / sigma_v

    ll = (
        math.log(2.0)
        - np.log(sigma)
        + norm.logpdf(eps / sigma)
        + norm.logcdf(-(eps * lam / sigma))
    )

    if not np.isfinite(ll).all():
        return 1e12

    return float(-ll.sum())


def conditional_inefficiency(eps: np.ndarray, sigma_v: np.ndarray, sigma_u: np.ndarray) -> np.ndarray:
    sigma = np.sqrt(sigma_v ** 2 + sigma_u ** 2)
    lam = sigma_u / sigma_v
    sigma_star = (sigma_u * sigma_v) / sigma
    m = (eps * lam) / sigma
    denom = np.clip(norm.cdf(-m), 1e-12, None)
    return sigma_star * ((norm.pdf(m) / denom) - m)


def fit_half_normal_sfa(estimation: pd.DataFrame) -> SFAFit:
    feature_cols = [
        "log_gdp_pc_ppp",
        "log_gdp_pc_ppp_sq",
        "trade_open_pct_gdp",
        "agriculture_pct_gdp",
        "education_spend_pct_gdp",
        "inflation_cpi_pct",
        "gini",
    ]
    ineff_cols = ["ge_centered"]

    y = estimation["log_tax_ratio"].to_numpy(dtype=float)
    x = estimation[feature_cols].to_numpy(dtype=float)
    z = estimation[ineff_cols].to_numpy(dtype=float)

    x_mean = x.mean(axis=0)
    x_std = x.std(axis=0, ddof=0)
    x_std[x_std == 0] = 1.0
    x_scaled = (x - x_mean) / x_std
    x_design = np.column_stack([np.ones(len(estimation)), x_scaled])

    z_mean = z.mean(axis=0)
    z_std = z.std(axis=0, ddof=0)
    z_std[z_std == 0] = 1.0
    z_scaled = (z - z_mean) / z_std

    ols_beta, *_ = np.linalg.lstsq(x_design, y, rcond=None)
    resid = y - x_design @ ols_beta

    init = np.concatenate(
        [
            ols_beta,
            np.array([math.log(max(resid.std(ddof=0) * 0.6, 1e-3))]),
            np.array([math.log(max(resid.std(ddof=0) * 0.8, 1e-3))]),
            np.zeros(z_scaled.shape[1]),
        ]
    )

    result = minimize(
        sfa_negative_log_likelihood,
        x0=init,
        args=(y, x_design, z_scaled),
        method="L-BFGS-B",
    )

    if not result.success:
        raise RuntimeError(f"SFA estimation failed: {result.message}")

    params = result.x
    k = x_design.shape[1]
    beta_scaled = params[:k]
    sigma_v = math.exp(params[k])
    sigma_u_base = math.exp(params[k + 1])
    delta = params[k + 2 :]

    beta_raw = np.empty_like(beta_scaled)
    beta_raw[1:] = beta_scaled[1:] / x_std
    beta_raw[0] = beta_scaled[0] - np.sum(beta_scaled[1:] * (x_mean / x_std))

    z_raw = ((z - z_mean) / z_std)
    sigma_u = sigma_u_base * np.exp(z_raw @ delta)
    eps = y - x_design @ beta_scaled
    u_hat = conditional_inefficiency(eps, sigma_v=np.full_like(sigma_u, sigma_v), sigma_u=sigma_u)
    tax_effort = np.exp(-u_hat)
    tax_capacity = estimation["total_taxes_pct_gdp"].to_numpy(dtype=float) / np.clip(tax_effort, 1e-9, None)

    fitted = estimation.copy()
    fitted["frontier_log_tax_ratio"] = x_design @ beta_scaled
    fitted["frontier_tax_pct_gdp"] = np.exp(fitted["frontier_log_tax_ratio"])
    fitted["residual"] = eps
    fitted["sigma_u_obs"] = sigma_u
    fitted["u_hat"] = u_hat
    fitted["tax_effort"] = tax_effort
    fitted["tax_capacity_pct_gdp"] = tax_capacity
    fitted["revenue_headroom_pct_gdp"] = fitted["tax_capacity_pct_gdp"] - fitted["total_taxes_pct_gdp"]

    coef_rows = [("const", beta_raw[0], "frontier")]
    coef_rows.extend((name, value, "frontier") for name, value in zip(feature_cols, beta_raw[1:]))
    coef_rows.append(("log_sigma_v", params[k], "variance"))
    coef_rows.append(("log_sigma_u_base", params[k + 1], "variance"))
    coef_rows.extend((name, value, "inefficiency") for name, value in zip(ineff_cols, delta))

    coefficients = pd.DataFrame(coef_rows, columns=["parameter", "estimate", "block"])

    diagnostics = pd.DataFrame(
        [
            ("optimizer_success", int(result.success)),
            ("optimizer_status", result.status),
            ("negative_log_likelihood", float(result.fun)),
            ("n_obs", int(len(estimation))),
            ("n_countries", int(estimation["Country"].nunique())),
            ("start_year", int(estimation["Year"].min())),
            ("end_year", int(estimation["Year"].max())),
            ("sigma_v", sigma_v),
            ("sigma_u_base", sigma_u_base),
            ("lambda_mean", float(np.mean(sigma_u / sigma_v))),
            ("tax_effort_mean", float(fitted["tax_effort"].mean())),
            ("tax_effort_min", float(fitted["tax_effort"].min())),
            ("tax_effort_max", float(fitted["tax_effort"].max())),
        ],
        columns=["metric", "value"],
    )

    return SFAFit(coefficients=coefficients, diagnostics=diagnostics, fitted=fitted)


def build_outputs(input_workbook: str, output_workbook: str) -> None:
    raw_wb, panel, estimation = build_estimation_panel(input_workbook)
    fit = fit_half_normal_sfa(estimation)

    historical = panel.merge(
        fit.fitted[
            [
                "Country",
                "Year",
                "frontier_log_tax_ratio",
                "frontier_tax_pct_gdp",
                "sigma_u_obs",
                "u_hat",
                "tax_effort",
                "tax_capacity_pct_gdp",
                "revenue_headroom_pct_gdp",
            ]
        ],
        on=["Country", "Year"],
        how="left",
    )

    latest_complete_year = int(fit.fitted["Year"].max())
    snapshot = fit.fitted[fit.fitted["Year"] == latest_complete_year].copy()
    snapshot = snapshot.sort_values("tax_effort", ascending=False).reset_index(drop=True)
    snapshot.insert(0, "rank_tax_effort", np.arange(1, len(snapshot) + 1))

    methodology = pd.DataFrame(
        {
            "section": [
                "Model",
                "Dependent variable",
                "Frontier covariates",
                "Inefficiency shifter",
                "Country sample",
                "Time sample",
                "Imputation",
                "Interpretation",
            ],
            "note": [
                "Half-normal stochastic frontier estimated by maximum likelihood with observation-level inefficiency scale.",
                "Log of total tax revenue as a percent of GDP from the local fiscal space workbook.",
                "Log GDP per capita PPP, its square, trade openness, agriculture share, public education spending, CPI inflation, and Gini.",
                "Government effectiveness from the local workbook enters as a shifter of the inefficiency scale.",
                "Euro-area sample in the provided workbook: 21 countries.",
                f"Annual panel from {START_YEAR} to {END_YEAR}, with the latest complete SFA snapshot determined by data availability.",
                "Missing World Bank or WGI values are filled within country by linear interpolation and boundary carry-forward/backward before estimation.",
                "Tax effort closer to 1 means a country is nearer its estimated tax frontier. Revenue headroom is the gap between estimated tax capacity and observed tax revenue, both in percent of GDP.",
            ],
        }
    )

    local_missingness = pd.DataFrame(
        {
            "column": panel.columns,
            "missing_values": [int(panel[c].isna().sum()) for c in panel.columns],
        }
    )

    with pd.ExcelWriter(output_workbook, engine="openpyxl") as writer:
        snapshot.to_excel(writer, sheet_name="latest_snapshot", index=False)
        historical.to_excel(writer, sheet_name="historical_results", index=False)
        fit.fitted.to_excel(writer, sheet_name="estimation_sample", index=False)
        fit.coefficients.to_excel(writer, sheet_name="coefficients", index=False)
        fit.diagnostics.to_excel(writer, sheet_name="model_diagnostics", index=False)
        raw_wb.to_excel(writer, sheet_name="wb_raw_downloads", index=False)
        panel.to_excel(writer, sheet_name="merged_panel", index=False)
        local_missingness.to_excel(writer, sheet_name="missingness", index=False)
        methodology.to_excel(writer, sheet_name="methodology", index=False)

    print(f"Saved SFA workbook to {output_workbook}")
    print(f"Latest complete snapshot year: {latest_complete_year}")


def main() -> None:
    input_workbook = os.environ.get("REVENUE_SFA_INPUT", INPUT_WORKBOOK)
    output_workbook = os.environ.get("REVENUE_SFA_OUTPUT", DEFAULT_OUTPUT_WORKBOOK)
    build_outputs(input_workbook=input_workbook, output_workbook=output_workbook)


if __name__ == "__main__":
    main()
