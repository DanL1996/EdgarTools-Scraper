import os
from typing import Literal, Optional
from pydantic import BaseModel, Field
from edgar import set_identity, get_filings
from anthropic import Anthropic
from supabase import create_client

set_identity(os.environ["EDGAR_IDENTITY"])
anthropic_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# Focus specifically on Private Markets & Exemptive Relief forms
BACKFILL_FORMS = ["N-2", "N-2/A", "40-APP", "40-APP/A"]


class BackfillExtraction(BaseModel):
    is_actionable: bool = Field(
        description=(
            "True if this is an initial N-2 registration, an N-2/A pre-effective amendment that introduces or updates "
            "material fund details (fees, sub-adviser, distributor, strategy, or repurchase terms), or a 40-APP / 40-APP/A "
            "exemptive relief application. False if it is purely a clerical exhibit-only filing with no fund details."
        )
    )
    vertical: Literal["etf_launches", "private_markets"] = Field(
        description=(
            "Route to 'private_markets' for all N-2 and N-2/A filings (interval funds, tender offer funds, BDCs, closed-end funds) "
            "and for any 40-APP / 40-APP/A seeking co-investment relief (Section 17(d)/57(i)) or multi-class interval/tender-offer relief. "
            "Route standard ETF exemptive relief (e.g., custom baskets, ETF share class of mutual fund) to 'etf_launches'."
        )
    )
    brief_category: str = Field(
        description=(
            "If vertical is 'private_markets', choose one of: 'New Interval, Tender Offer & CEF Launch', "
            "'Private Credit / PE ETF Launch', 'Co-Investment & Multi-Class Relief', or 'Routine Update'. "
            "If vertical is 'etf_launches', choose one of: 'New Fund Launch', 'ETF Conversion / Material Amendment', "
            "'Exemptive Relief Application', or 'Routine Update'."
        )
    )
    trust_or_registrant_name: Optional[str] = Field(
        default=None,
        description="Official name of the Investment Company / Trust / BDC / Applicant."
    )
    fund_name: Optional[str] = Field(
        default=None,
        description="Specific name(s) of the fund(s) being registered or applying for relief."
    )
    investment_adviser: Optional[str] = Field(
        default=None,
        description="Primary Investment Adviser or Sponsor named in the filing."
    )
    sub_adviser: Optional[str] = Field(
        default=None,
        description="Sub-adviser(s) named in the filing, or null if none."
    )
    legal_counsel_firm: Optional[str] = Field(
        default=None,
        description="Outside law firm representing the registrant/applicant (found on cover page 'Copies to:')."
    )
    lead_attorney: Optional[str] = Field(
        default=None,
        description="Named individual attorney / partner listed on the cover page ('Copy to:') or signature block, or null."
    )
    strategy_asset_class: Optional[str] = Field(
        default=None,
        description=(
            "Start with the exact wrapper in brackets—e.g., [Interval Fund], [Tender Offer Fund], [BDC], [Listed CEF], or [Exemptive Relief]—"
            "followed by a concise 1-sentence description of the strategy, repurchase/liquidity terms, or material updates added in this amendment."
        )
    )
    management_fee: Optional[str] = Field(
        default=None,
        description="Stated management fee (e.g., '1.25%' or '1.50% on gross assets'), or null if blank/[__]."
    )
    listing_exchange: Optional[str] = Field(
        default=None,
        description="Target listing exchange (e.g., 'NYSE', 'Nasdaq') if listed CEF/BDC, or null if unlisted interval/tender-offer fund."
    )
    distributor_or_admin: Optional[str] = Field(
        default=None,
        description="Named distributor/underwriter or fund administrator if disclosed, or null if blank/[__]."
    )
    verbatim_key_excerpt: Optional[str] = Field(
        default=None,
        description="Exact 1-2 sentence verbatim quote summarizing the investment objective, repurchase frequency, or relief sought."
    )


def analyze_filing(form_type: str, filing_text: str) -> BackfillExtraction:
    # First 16,000 chars captures cover page, counsel, adviser, fee table, and investment objective
    excerpt = filing_text[:16000]
    response = anthropic_client.messages.parse(
        model="claude-sonnet-5-5",
        max_tokens=1024,
        system=(
            "You are a senior 1940-Act regulatory intelligence analyst covering interval funds, tender-offer funds, BDCs, "
            "closed-end funds, and exemptive relief. Extract exact facts from the SEC filing. When analyzing an N-2/A or 40-APP/A "
            "amendment, capture all newly populated details (fees, sub-advisers, distributors, repurchase terms). Never invent data."
        ),
        messages=[
            {
                "role": "user",
                "content": f"Form Type: {form_type}\n\nFiling Text:\n{excerpt}"
            }
        ],
        output_format=BackfillExtraction,
    )
    return response.parsed_output


def run():
    start_date = os.environ.get("BACKFILL_START_DATE", "2026-01-01")
    max_inspect = int(os.environ.get("BACKFILL_LIMIT", "150"))
    target_year = int(start_date[:4])

    print(f"Fetching {BACKFILL_FORMS} filings for {target_year} from {start_date} to present...")
    filings = get_filings(year=target_year, form=BACKFILL_FORMS, filing_date=f"{start_date}:")
    print(f"Found {len(filings)} total matching filings in {target_year}. Will inspect up to {max_inspect} NEW filings...")

    # Pre-load all existing accession numbers in one query for instant deduplication
    existing_resp = supabase.table("sec_filings").select("accession_number").execute(),existing_accs.add(acc_num)

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
            print(f"[{extraction.vertical}] {filing.filing_date} | {filing.form}: {extraction.fund_name or extraction.trust_or_registrant_name}")

        except Exception as e:
            err_str = str(e)
            print(f"Error processing {acc_num}: {err_str}")
            if "credit balance is too low" in err_str or "authentication_error" in err_str:
                print("Stopping backfill immediately due to Anthropic API billing/auth error.")
                break

            print(f"Error processing {acc_num}: {e}")

    print(f"Backfill complete. Inserted: {inserted_count} | Already in DB: {skipped_existing}")


if __name__ == "__main__":
    run()
