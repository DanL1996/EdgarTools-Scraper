import os
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from pydantic import BaseModel, Field
from edgar import set_identity, get_filings
from anthropic import Anthropic
from supabase import create_client

# 1. Initialize clients
set_identity(os.environ["EDGAR_IDENTITY"])
anthropic_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

TARGET_FORMS = ["N-1A", "485APOS", "485BPOS", "N-2", "40-APP"]


# 2. Define strict extraction schema for 1940-Act regulatory intelligence
class FilingExtraction(BaseModel):
    is_actionable: bool = Field(
        description="True ONLY if this filing represents a new fund/ETF launch, new series registration, mutual-fund-to-ETF conversion, closed-end/interval fund launch, or 1940-Act exemptive relief application. False for routine annual prospectus updates with no new series/strategy."
    )
    brief_category: str = Field(
        description="One of: 'New Fund Launch', 'ETF Conversion / Material Amendment', 'Exemptive Relief Application', or 'Routine Update'"
    )
    trust_or_registrant_name: Optional[str] = Field(
        default=None,
        description="Official name of the Investment Company / Trust / Registrant."
    )
    fund_name: Optional[str] = Field(
        default=None,
        description="Specific name(s) of the new fund(s) or ETF(s) being launched or applying for relief."
    )
    investment_adviser: Optional[str] = Field(
        default=None,
        description="Primary Investment Adviser or Sponsor named in the filing."
    )
    sub_adviser: Optional[str] = Field(
        default=None,
        description="Sub-adviser(s) named in the filing (e.g., white-label or portfolio sub-adviser), or null if none."
    )
    legal_counsel_firm: Optional[str] = Field(
        default=None,
        description="Outside law firm representing the trust/applicant (found on cover page 'Copies to:' or legal opinion exhibit)."
    )
    lead_attorney: Optional[str] = Field(
        default=None,
        description="Named individual attorney / partner listed on the cover page ('Copy to:') or signature block, or null if only the firm is listed."
    )
    strategy_asset_class: Optional[str] = Field(
        default=None,
        description="Concise 1-sentence description of the fund's investment strategy, wrapper (Active ETF, Index ETF, Interval Fund), or exemptive relief requested."
    )
    management_fee: Optional[str] = Field(
        default=None,
        description="Stated management fee or unitary fee (e.g., '0.65%'), or null if blank/[__] placeholder."
    )
    listing_exchange: Optional[str] = Field(
        default=None,
        description="Target listing exchange for ETFs/CEFs (e.g., 'NYSE Arca', 'Nasdaq', 'Cboe BZX'), or null if mutual fund or TBD."
    )
    distributor_or_admin: Optional[str] = Field(
        default=None,
        description="Named distributor/underwriter or fund administrator if disclosed, or null if not yet named."
    )
    verbatim_key_excerpt: Optional[str] = Field(
        default=None,
        description="Exact 1-2 sentence verbatim quote from the filing summarizing the new fund objective or relief sought."
    )


def analyze_filing(form_type: str, filing_text: str) -> FilingExtraction:
    # Truncate to first ~28,000 chars (covers cover page, fee table, strategy, adviser/sub-adviser, and counsel)
    excerpt = filing_text[:28000]

    response = anthropic_client.messages.parse(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=(
            "You are a senior 1940-Act regulatory intelligence analyst writing for ETF/mutual fund executives, "
            "fund service providers, and 1940-Act legal counsel. Extract exact facts from the SEC filing. "
            "Never guess or invent names, fees, or exchanges—if a field is blank or '[__]', return null."
        ),
        messages=[
            {
                "role": "user",
                "content": f"Form Type: {form_type}\n\nFiling Text:\n{excerpt}"
            }
        ],
        output_format=FilingExtraction,
    )
    return response.parsed_output


def run():
    since_date = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    print(f"Fetching 1940-Act filings since {since_date}...")

    filings = get_filings(form=TARGET_FORMS, filing_date=f"{since_date}:")
    recent_filings = filings.head(25)
    print(f"Inspecting {len(recent_filings)} filings...")

    inserted_count = 0

    for filing in recent_filings:
        acc_num = filing.accession_number

        # Check if already processed in Supabase
        existing = (
            supabase.table("sec_filings")
            .select("accession_number")
            .eq("accession_number", acc_num)
            .execute()
        )
        if existing.data:
            continue

        try:
            text = filing.text()
            if not text:
                continue

            extraction = analyze_filing(filing.form, text)

            if not extraction.is_actionable:
                print(f"Skipping non-actionable {filing.form} ({acc_num})")
                continue

            row = {
                "accession_number": acc_num,
                "form_type": filing.form,
                "filing_date": str(filing.filing_date),
                "edgar_url": filing.filing_url,
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
            inserted_count += 1
            print(f"Inserted {filing.form}: {extraction.fund_name or extraction.trust_or_registrant_name}")

        except Exception as e:
            print(f"Error processing {acc_num}: {e}")

    print(f"Done. Inserted {inserted_count} new actionable filings.")


if __name__ == "__main__":
    run()
