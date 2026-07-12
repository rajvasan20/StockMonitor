import json
import os
from collections import Counter

BASE_DIR = "C:/Users/VinothRajapandian/Personal Claude/Stock Monitor/data/kpi_database"

def classify_maruti(kpi_key, kpi_data):
    label = kpi_data.get("label", "").lower()
    category = kpi_data.get("category", "").lower()

    # Critical: sales/production volumes, capacity utilization, ASP, material cost ratio, export volume
    critical_keys = {
        "total_sales_volume", "domestic_sales_volume", "export_volume",
        "cng_sales_volume", "shev_sales_volume", "manufacturing_capacity",
        "capacity_utilization_implied", "material_cost_ratio",
        "pending_order_backlog", "discount_incentives",
        "production_loss_semiconductor"
    }
    if kpi_key in critical_keys:
        return "critical"

    # Supporting: market share, dealer count, mix ratios, R&D, service network
    supporting_keys = {
        "domestic_pv_market_share", "suv_market_share", "cng_market_share",
        "export_share_india_pv", "sales_outlets", "service_touchpoints",
        "suv_share_domestic_sales", "cng_share_domestic_sales",
        "green_vehicle_share", "models_count", "cng_models_offered",
        "export_countries", "non_urban_sales_share", "first_time_buyer_share",
        "export_share_total_sales", "r_and_d_expenditure", "r_and_d_engineers",
        "vehicles_serviced", "true_value_outlets", "smart_finance_share",
        "royalty_to_smc", "royalty_as_pct_net_sales", "cost_savings_suggestions",
        "rail_dispatch_volume", "rail_dispatch_share", "digital_enquiry_share",
        "patents_filed"
    }
    if kpi_key in supporting_keys:
        return "supporting"

    # Context: sustainability, ESG, employee generic
    context_keys = {
        "solar_power_capacity", "female_representation", "voluntary_attrition",
        "employee_count"
    }
    if kpi_key in context_keys:
        return "context"

    # Fallback
    if category in ("sustainability",):
        return "context"
    if "market_share" in label or "market share" in label:
        return "supporting"
    if "volume" in label or "sales" in label or "production" in label:
        return "critical"
    return "supporting"


def classify_natcopharm(kpi_key, kpi_data):
    label = kpi_data.get("label", "").lower()
    category = kpi_data.get("category", "").lower()

    # Critical: segment revenues, geography revenues
    critical_keys = {
        "revenue_international_fdf", "revenue_domestic_fdf", "revenue_api",
        "revenue_crop_health", "revenue_us", "revenue_canada", "revenue_brazil",
        "domestic_oncology_revenue", "domestic_non_oncology_revenue",
        "chs_segment_result", "us_revenue_share",
        "customer_concentration_top1", "customer_concentration_pct"
    }
    if kpi_key in critical_keys:
        return "critical"

    # Supporting: pipeline, filings, R&D, salesforce, market position
    supporting_keys = {
        "para_iv_pipeline", "para_iv_approved", "andas_filed_during_year",
        "cumulative_andas_approved", "active_dmfs", "cumulative_dmfs_filed",
        "solo_ftf_products", "r_and_d_expenditure", "r_and_d_pct_of_revenue",
        "domestic_new_launches", "brands_above_100m", "salesforce_size",
        "countries_presence", "manufacturing_facilities",
        "active_fdfs_india", "active_fdfs_row",
        "international_patents_filed", "international_patents_granted",
        "scientists"
    }
    if kpi_key in supporting_keys:
        return "supporting"

    # Context
    context_keys = {
        "subsidiaries_count"
    }
    if kpi_key in context_keys:
        return "context"

    # Fallback
    if "revenue" in label:
        return "critical"
    return "supporting"


def classify_ncc(kpi_key, kpi_data):
    label = kpi_data.get("label", "").lower()
    category = kpi_data.get("category", "").lower()

    # Critical: order book, order inflow, direct cost, book-to-bill
    critical_keys = {
        "order_inflow", "group_order_book", "standalone_order_book",
        "remaining_performance_obligations", "book_to_bill_ratio",
        "direct_cost_pct", "overheads_pct_of_turnover",
        "finance_cost_pct_of_turnover", "avg_cost_of_borrowing"
    }
    if kpi_key in critical_keys:
        return "critical"

    # Supporting: order book mix, customer concentration, assets, capital allocation
    supporting_keys = {
        "order_book_buildings_pct", "order_book_transportation_pct",
        "order_book_water_pct", "order_book_electrical_pct",
        "order_book_mining_pct", "order_book_irrigation_pct",
        "order_book_railways_pct", "customer_concentration_top1_pct",
        "amaravati_outstanding", "ppe_gross_block_cwip",
        "investments_in_subsidiaries", "loans_to_group_companies",
        "credit_rating", "total_human_capital_base",
        "employee_benefits_expense", "key_mgmt_compensation"
    }
    if kpi_key in supporting_keys:
        return "supporting"

    # Context: CSR, governance, workforce training, technology
    context_keys = {
        "total_employees", "training_programs", "training_coverage_employees",
        "attrition_rate", "median_remuneration_increase", "md_to_median_pay_ratio",
        "csr_spend", "electoral_bonds", "digitization_expenses",
        "software_acquisition_expenses", "elearning_courses",
        "audit_committee_meetings", "branches_joint_operations"
    }
    if kpi_key in context_keys:
        return "context"

    # Fallback
    if "order" in label:
        return "critical"
    if category in ("governance", "social_impact", "workforce", "technology"):
        return "context"
    return "supporting"


def classify_reliance(kpi_key, kpi_data):
    label = kpi_data.get("label", "").lower()
    category = kpi_data.get("category", "").lower()

    # Critical: segment revenues, segment EBITDA, subscribers, ARPU, production, throughput
    critical_keys = {
        "segment_revenue_o2c_cr", "segment_revenue_retail_cr",
        "segment_revenue_digital_services_cr", "segment_revenue_oil_gas_cr",
        "segment_revenue_media_cr",
        "segment_ebitda_o2c_cr", "segment_ebitda_retail_cr",
        "segment_ebitda_digital_services_cr", "segment_ebitda_oil_gas_cr",
        "segment_ebitda_media_cr",
        "jio_subscribers_mn", "jio_arpu_rs_per_month",
        "o2c_total_throughput_mmt", "o2c_production_for_sale_mmt",
        "ep_kg_d6_gas_production_mmscmd", "ep_gas_production_total_bcf",
        "ep_oil_condensate_kbd", "ep_cbm_production_mmscmd",
        "consumer_ebitda_share_pct",
        "retail_transactions_bn",
        "jio_data_traffic_annual_bn_gb",
        "jio_per_capita_data_usage_gb_month",
        "jio_connected_premises_mn", "jio_5g_users_mn"
    }
    if kpi_key in critical_keys:
        return "critical"

    # Supporting: store count, store area, customer base, capex, market shares, distribution
    supporting_keys = {
        "retail_store_count", "retail_store_area_msqft",
        "retail_registered_customers_mn", "retail_footfalls_mn",
        "retail_new_stores_added", "retail_digital_commerce_pct_revenue",
        "retail_merchant_partners_mn", "retail_warehouse_space_msqft",
        "retail_campa_market_share_pct",
        "jio_bp_fuel_outlets", "jio_bp_ev_charging_points",
        "jio_voice_usage_min_month",
        "jio_monthly_data_traffic_exabytes",
        "jio_spectrum_footprint_mhz",
        "jio_india_data_traffic_share_pct",
        "jio_5g_data_traffic_share_pct",
        "jio_airfiber_home_additions_share_pct",
        "jio_airfiber_towns", "jio_5g_cities_covered",
        "jio_patent_applications_filed", "jio_5g_sites",
        "o2c_transportation_fuels_exported_mmt",
        "o2c_domestic_polymer_market_share_pct",
        "ep_india_gas_production_share_pct",
        "ep_cbm_wells_in_production",
        "ep_offshore_uptime_pct",
        "new_energy_solar_gw_commissioned",
        "new_energy_cbg_plants", "new_energy_cbg_capacity_tpd",
        "media_jiohotstar_maus_mn", "media_ipl_reach_mn",
        "media_jiohotstar_ipl_pay_subs_mn", "media_tv_viewership_share_pct",
        "capex_consolidated_cr", "capex_digital_services_cr",
        "capex_retail_cr", "capex_o2c_cr",
        "r_and_d_expenditure_cr", "researchers_scientists",
        "patents_granted_annual"
    }
    if kpi_key in supporting_keys:
        return "supporting"

    # Context: employee counts, women employees
    context_keys = {
        "total_employees", "employees_retail", "employees_jio",
        "employees_o2c", "women_employees_pct"
    }
    if kpi_key in context_keys:
        return "context"

    # Fallback
    if "segment_revenue" in kpi_key or "segment_ebitda" in kpi_key:
        return "critical"
    if "employee" in label:
        return "context"
    return "supporting"


CLASSIFIERS = {
    "MARUTI": classify_maruti,
    "NATCOPHARM": classify_natcopharm,
    "NCC": classify_ncc,
    "RELIANCE": classify_reliance,
}

def add_impact_tier(ticker):
    filepath = os.path.join(BASE_DIR, f"{ticker}.json")
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    classifier = CLASSIFIERS[ticker]
    counts = Counter()

    print(f"\n{'='*60}")
    print(f"  {ticker} — {data.get('company', '')}")
    print(f"{'='*60}")

    new_kpis = {}
    for kpi_key, kpi_data in data["kpis"].items():
        tier = classifier(kpi_key, kpi_data)
        counts[tier] += 1

        # Insert impact_tier right after category
        new_kpi = {}
        for k, v in kpi_data.items():
            new_kpi[k] = v
            if k == "category":
                new_kpi["impact_tier"] = tier

        # If category wasn't found (shouldn't happen), append at end
        if "impact_tier" not in new_kpi:
            new_kpi["impact_tier"] = tier

        new_kpis[kpi_key] = new_kpi
        print(f"  {tier:10s}  {kpi_key:45s}  [{kpi_data.get('label', '')}]")

    data["kpis"] = new_kpis

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n  Summary: critical={counts['critical']}, supporting={counts['supporting']}, context={counts['context']}")
    print(f"  Total: {sum(counts.values())} KPIs")
    return counts


if __name__ == "__main__":
    tickers = ["MARUTI", "NATCOPHARM", "NCC", "RELIANCE"]
    grand_total = Counter()

    for t in tickers:
        c = add_impact_tier(t)
        grand_total += c

    print(f"\n{'='*60}")
    print(f"  GRAND TOTAL")
    print(f"{'='*60}")
    print(f"  critical={grand_total['critical']}, supporting={grand_total['supporting']}, context={grand_total['context']}")
    print(f"  Total: {sum(grand_total.values())} KPIs across {len(tickers)} companies")
