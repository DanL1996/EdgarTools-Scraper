import os
from typing import Literal, Optional
from pydantic import BaseModel, Field
from edgar import set_identity, get_filings
from supabase import create_client, Client
import anthropic

# 1. Initialize Clients
SEC_IDENTITY = os.environ.get("SEC_IDENTITY", "PrivateMarketsIntel research@example.com")
set_identity(SEC_IDENTITY)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

BACKFILL_FORMS = ["N-2", "N-2/A", "40-APP", "40-APP/A"]


# 2. Structured Extraction Schema
class FilingExtraction(BaseModel):
    is_actionable: bool = Field(
        description=(
            "True ONLY if this filing represents a NEW or pre-launch registered fund "
            "(interval fund, tender offer fund, non-traded BDC, listed CEF) filing an initial "
            "N-2 or substantive pre-effective N-2/A, OR a new/amended 40-APP exemptive relief "
            "application (e.g., co-investment relief, multi-class shares, interval fund liquidity). "
            "False for routine annual updates, shelf takedowns, prospectus supplements, or operating companies."
        )
    )
    vertical: Literal["private_markets", "exemptive_relief", "other"] = Field(
        description="Categorize as private_markets (N-2/N-2A) or exemptive_relief (40-APP/40-APP/A)."
    )
    brief_category: str = Field(
        description="Short category label (e.g., 'New Interval Fund N-2', 'Non-Traded BDC N-2', 'Co-Investment 40-APP', 'Multi-Class 40-APP')."
    )
    trust_or_registrant_name: str = Field(
        description="Legal name of the registrant, trust, or lead applicant."
    )
    fund_name: str = Field(
        description="Specific fund name(s) or lead applicant(s) covered by this filing."
    )
    investment_adviser: Optional[str] = Field(
        default=None, description="Primary investment adviser / sponsor."
    )
    sub_adviser: Optional[str] = Field(
        default=None, description="Sub-adviser(s), if any."
    )
    legal_counsel_firm: Optional[str] = Field(
        default=None, description="Outside fund or applicant legal counsel law firm."
    )
    lead_attorney: Optional[str] = Field(
        default=None, description="Lead partner / attorney named on the cover or signature block."
    )
    strategy_asset_class: Optional[str] = Field(
        default=None, description="Core investment strategy and asset class (e.g., 'Direct Lending / Private Credit', 'Secondaries / Private Equity')."
    )
    management_fee: Optional[str] = Field(
        default=None, description="Stated annual management fee and any incentive/performance fee structure."
    )
    listing_exchange: Optional[str] = Field(
        default=None, description="Target exchange if listed (e.g., 'NYSE'), or 'Non-Traded / Interval' or 'Non-Traded / Tender Offer'."
    )
    distributor_or_admin: Optional[str] = Field(
        default=None, description="Principal underwriter / distributor and/or fund administrator."
    )
    verbatim_key_excerpt: str = Field(
        description="1-2 sentence verbatim quote from the filing describing the fund's investment objective or exemptive relief requested."
    )


# 3. LLM Analyzer (Cost-Optimized with Claude Haiku 5.5)
def analyze_filing(form_type: str, filing_text: str) -> FilingExtraction:
    truncated_text = filing_text[:20000]

    prompt = (
        f"You are an institutional 1940 Act & Private Markets regulatory intelligence analyst. "
        f"Analyze the following SEC Form {form_type} filing text and extract structured intelligence.\n\n"
        f"FILING TEXT:\n{truncated_text}"
    )

    response = claude.messages.parse(
        model="claude-haiku-5-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
        output_format=FilingExtraction,
    )
    return response.parsed_output


# 4. Main Backfill Runner
def run():
    start_date = os.environ.get("BACKFILL_START_DATE", "2026-01-01")
    max_inspect = int(os.environ.get("BACKFILL_LIMIT", "250"))
    target_year = int(start_date[:4])

    print(f"Fetching {BACKFILL_FORMS} filings for {target_year} from {start_date} to present...")
    filings = get_filings(year=target_year, form=BACKFILL_FORMS, filing_date=f"{start_date}:")
    print(f"Found {len(filings)} total matching filings in {target_year}. Will inspect up to {max_inspect} NEW filings...")

    existing_resp = supabase.table("sec_filings").select("accession_number").execute()
    existing_accs = {row["accession_number"] for row in (existing_resp.data or [])}
    print(f"Loaded {len(existing_accs)} existing records from Supabase to skip.")

    inserted_count = 0
    skipped_existing = 0
    new_checked = 0

    for filing in filings:
        if new_checked >= max_inspect:
            break

        acc_num = filing.accession_number
        if acc_num in existing_accs:
            skipped_existing += 1
            continue

        new_checked += 1

        try:
            text = filing.text()
            if not text:
                existing_accs.add(acc_num)
                continue

            extraction = analyze_filing(filing.form, text)
            if not extraction.is_actionable:
                print(f"Skipping non-actionable {filing.form} ({acc_num})")
                existing_accs.add(acc_num)
                continue

            row = {
                "accession_number": acc_num,
                "form_type": filing.form,
                "filing_date": str(filing.filing_date),
                "edgar_url": filing.filing_url,
                "vertical": extraction.vertical,
                "brief_category": extraction.brief_category,
                "trust_or_registrant_name": extraction.trust_or_registrant_name,
                "fund_name": extraction.fund_name,
                "investment_adviser": extraction.investment_adviser,
                "sub_adviser": extraction.sub_adviser,
                "legal_counsel_firm": extraction.legal_counsel_firm,
                "lead_attorney": extraction.lead_attorney,
                "strategy_asset_class": extraction.strategy_asset_class,
                "management_fee": extraction.management_fee,
                "listing_exchange": extraction.listing_exchange,
                "distributor_or_admin": extraction.distributor_or_admin,
                "verbatim_key_excerpt": extraction.verbatim_key_excerpt,
                "raw_payload": extraction.model_dump(),
            }

            supabase.table("sec_filings").upsert(row).execute()
            existing_accs.add(acc_num)
            inserted_count += 1
            print(
                f"[{extraction.vertical}] {filing.filing_date} | {filing.form}: "
                f"{extraction.fund_name or extraction.trust_or_registrant_name}"
            )

        except Exception as e:
            err_str = str(e)
            print(f"Error processing {acc_num}: {err_str}")
            if "credit balance is too low" in err_str or "authentication_error" in err_str:
                print("Stopping backfill immediately due to Anthropic API billing/auth error.")
                break

    print(f"Backfill complete. Inserted: {inserted_count} | Already in DB: {skipped_existing}")


if __name__ == "__main__":
    run()
