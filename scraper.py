import os
import json
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional
from pydantic import BaseModel, Field
from edgar import set_identity, get_filings
from anthropic import Anthropic
from supabase import create_client

# 1. Initialize clients
set_identity(os.environ["EDGAR_IDENTITY"])
anthropic_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

TARGET_FORMS = ["N-1A", "485APOS", "485BPOS", "N-2", "N-2/A", "40-APP", "S-1"]


def normalize_law_firm(firm: Optional[str]) -> Optional[str]:
    if not firm:
        return None
    clean = firm.strip()
    low = clean.lower()
    if low.startswith("troutman pepper locke"):
        return "Troutman Pepper Locke LLP"
    if low.startswith("herrick, feinstein") or low.startswith("herrick feinstein"):
        return "Herrick, Feinstein LLP"
    return clean


# 2. Define strict extraction schema for 1940-Act & Digital Asset regulatory intelligence
class FilingExtraction(BaseModel):
    is_actionable: bool = Field(
        description=(
            "True ONLY if this filing represents a new 1940-Act registered fund/ETF launch, new series registration, "
            "mutual-fund-to-ETF conversion, closed-end/interval/tender-offer fund or BDC launch, "
            "spot/staked crypto or tokenized ETP registration (S-1), or an Investment Company Act of 1940 exemptive relief application "
            "(such as co-investment, multi-class shares, ETF share classes, or manager-of-managers relief). "
            "False for routine annual prospectus updates with no new series/strategy, false for non-fund corporate/operating-company S-1 IPOs, "
            "and STRICTLY FALSE for Investment Advisers Act of 1940 exemptive applications (e.g., Rule 206(4)-5 pay-to-play political contribution waivers, "
            "Section 202(a)(11)(G) family office exemptions, or Section 206A adviser exemptions)."
        )
    )
    vertical: Literal["etf_launches", "private_markets"] = Field(
        description=(
            "Route to 'private_markets' if this is an N-2 or N-2/A filing (interval fund, tender offer fund, non-traded BDC, closed-end fund), "
            "a 1940 Investment Company Act 40-APP seeking co-investment relief (Section 17(d)/57(i)) or multi-class interval/tender-offer/tokenized share-class relief, "
            "an on-chain money-market/Treasury fund, or an N-1A/485 filing whose primary strategy allocates >15% to private credit, private equity, venture capital, infrastructure, or unlisted secondaries. "
            "Route all standard ETFs, spot/staked crypto ETPs (S-1/N-1A), mutual-fund-to-ETF conversions, and standard ETF exemptive relief to 'etf_launches'."
        )
    )
    brief_category: str = Field(
        description=(
            "If vertical is 'etf_launches', choose one of: 'New Fund Launch', 'ETF Conversion / Material Amendment', 'Exemptive Relief Application', 'Tokenized / Digital Asset Fund', or 'Routine Update'. "
            "If vertical is 'private_markets', choose one of: 'New Interval / Tender Offer Fund', 'Private Credit / PE ETF Launch', 'Co-Investment & Multi-Class Relief', 'Tokenized / Digital Asset Fund', or 'Routine Update'."
        )
    )
    trust_or_registrant_name: Optional[str] = Field(
        default=None,
        description="Official name of the Investment Company / Trust / Registrant."
    )
    fund_name: Optional[str] = Field(
        default=None,
        description="Specific name(s) of the new fund(s) or ETF(s)/ETP(s) being launched or applying for relief."
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
        description="Complete outside law firm name representing the trust/applicant (found on cover page 'Copies to:' or legal opinion exhibit; include full suffix such as LLP or P.C.)."
    )
    lead_attorney: Optional[str] = Field(
        default=None,
        description="Named individual attorney / partner listed on the cover page ('Copy to:') or signature block, or null if only the firm is listed."
    )
    strategy_asset_class: Optional[str] = Field(
        default=None,
        description="Concise 1-sentence description of the fund's investment strategy, wrapper (Active ETF, Index ETF, Spot/Staked Crypto ETP, Interval Fund, Tender Offer Fund, BDC), or exemptive relief requested."
    )
    management_fee: Optional[str] = Field(
        default=None,
        description="Stated management fee or unitary fee (e.g., '0.65%'), or null if blank/[__] placeholder."
    )
    listing_exchange: Optional[str] = Field(
        default=None,
        description="Target listing exchange for ETFs/ETPs/CEFs (e.g., 'NYSE Arca', 'Nasdaq', 'Cboe BZX'), or null if unlisted interval/tender-offer fund or TBD."
    )
    distributor_or_admin: Optional[str] = Field(
        default=None,
        description="Named distributor/underwriter or fund administrator if disclosed, or null if not yet named."
    )
    verbatim_key_excerpt: Optional[str] = Field(
        default=None,
        description="Exact 1-2 sentence verbatim quote from the filing summarizing the new fund objective, repurchase policy, tokenized structure, or relief sought."
    )
    # --- Tokenization & Digital Asset Fields ---
    is_tokenized: bool = Field(
        default=False,
        description=(
            "True ONLY if this filing genuinely registers or seeks exemptive relief for a tokenized share class, "
            "on-chain money market/Treasury fund, spot/staked crypto ETP, or tokenized interval/private fund. "
            "False if crypto/digital assets are merely mentioned in generic boilerplate risk factors."
        )
    )
    tokenization_type: Optional[
        Literal[
            "Tokenized Share Class",
            "On-Chain MMF/Treasury",
            "Spot/Staked Crypto ETP",
            "Tokenized Private/Interval Fund",
        ]
    ] = Field(
        default=None,
        description="Category of tokenized or digital asset fund if is_tokenized is True, otherwise null."
    )
    digital_transfer_agent: Optional[str] = Field(
        default=None,
        description="Normalized digital transfer agent or tokenization platform if disclosed (e.g., 'Securitize', 'Superstate', 'Franklin Templeton', 'Taurus', 'Tokeny', 'BNY Mellon', 'State Street'), or null."
    )
    crypto_custodian: Optional[str] = Field(
        default=None,
        description="Normalized qualified crypto/digital asset custodian if disclosed (e.g., 'Coinbase Custody', 'Anchorage Digital', 'BitGo', 'Fireblocks', 'BNY Mellon', 'Fidelity Digital Assets'), or null."
    )
    blockchain_network: Optional[str] = Field(
        default=None,
        description="Blockchain network(s) named for on-chain recordkeeping or settlement (e.g., 'Ethereum', 'Solana', 'Stellar', 'Polygon', 'Avalanche', 'Multi-Chain'), or null."
    )


def analyze_filing(form_type: str, filing_text: str) -> FilingExtraction:
    # Truncate to first ~28,000 chars (covers cover page, fee table, strategy, adviser/sub-adviser, and counsel)
    excerpt = filing_text[:28000]

    response = anthropic_client.messages.parse(
        model="claude-sonnet-5-5",
        max_tokens=2048,
        system=(
            "You are a senior 1940-Act & Digital Asset regulatory intelligence analyst writing for ETF/mutual fund executives, "
            "alternative asset managers, fund service providers, and 1940-Act legal counsel. Extract exact facts from the SEC filing. "
            "Never guess or invent names, fees, or exchanges—if a field is blank or '[__]', return null. "
            "For S-1 filings, mark is_actionable=True ONLY if the registrant is a crypto/digital-asset ETP or investment fund (ignore standard corporate IPOs). "
            "For 40-APP filings, mark is_actionable=False if the application is under the Investment Advisers Act of 1940 (such as Rule 206(4)-5 pay-to-play political contribution exemptions or family office exemptions)."
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
    print(f"Fetching 1940-Act & Digital Asset filings since {since_date}...")

    filings = get_filings(form=TARGET_FORMS, filing_date=f"{since_date}:")
    recent_filings = filings.head(40)
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

            lower_head = text[:15000].lower()

            # Fast pre-filter for S-1s so we don't spend tokens on non-fund corporate IPOs
            if filing.form == "S-1":
                if not any(k in lower_head for k in ("bitcoin", "ethereum", "solana", "digital asset", "crypto", "tokeniz", "trust", "etf", "etp")):
                    continue

            # Fast pre-filter for 40-APPs to exclude Investment Advisers Act pay-to-play / family office filings
            if filing.form == "40-APP":
                if any(k in lower_head for k in ("206(4)-5", "pay-to-play", "pay to play", "political contribution", "202(a)(11)(g)", "family office")):
                    print(f"Skipping Advisers Act 40-APP ({acc_num})")
                    continue

            extraction = analyze_filing(filing.form, text)

            if not extraction.is_actionable:
                print(f"Skipping non-actionable {filing.form} ({acc_num})")
                continue

            counsel_firm = normalize_law_firm(extraction.legal_counsel_firm)

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
                "legal_counsel_firm": counsel_firm,
                "lead_attorney": extraction.lead_attorney,
                "strategy_asset_class": extraction.strategy_asset_class,
                "management_fee": extraction.management_fee,
                "listing_exchange": extraction.listing_exchange,
                "distributor_or_admin": extraction.distributor_or_admin,
                "verbatim_key_excerpt": extraction.verbatim_key_excerpt,
                "is_tokenized": extraction.is_tokenized,
                "tokenization_type": extraction.tokenization_type,
                "digital_transfer_agent": extraction.digital_transfer_agent,
                "crypto_custodian": extraction.crypto_custodian,
                "blockchain_network": extraction.blockchain_network,
                "raw_payload": extraction.model_dump(),
            }

            supabase.table("sec_filings").upsert(row).execute()
            inserted_count += 1
            tok_badge = f" [TOKENIZED: {extraction.tokenization_type}]" if extraction.is_tokenized else ""
            print(f"[{extraction.vertical}]{tok_badge} Inserted {filing.form}: {extraction.fund_name or extraction.trust_or_registrant_name}")

        except Exception as e:
            print(f"Error processing {acc_num}: {e}")

    print(f"Done. Inserted {inserted_count} new actionable filings.")


if __name__ == "__main__":
    run()
