import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

print("[boot] Importing pydantic, edgartools, anthropic, supabase...", flush=True)
from pydantic import BaseModel, Field
from edgar import set_identity, get_filings
from anthropic import Anthropic
from supabase import create_client

print("[boot] Initializing clients...", flush=True)
set_identity(os.environ["EDGAR_IDENTITY"])
anthropic_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
print("[boot] Clients initialized.", flush=True)

TARGET_FORMS = [
    "N-1A",
    "485APOS",
    "485BPOS",
    "N-2",
    "N-2/A",
    "40-APP",
    "S-1",
    "10-12G",
    "10-12G/A",
    "N-6F",
    "N-54A",
]

BDC_FORMS = {"10-12G", "10-12G/A", "N-6F", "N-54A"}


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


def looks_like_bdc_filing(filing, head_text: str) -> bool:
    """High-signal pre-filter for 10-12G / 10-12G/A / N-6F / N-54A so corporate 10-12G filers are skipped."""
    if filing.form in {"N-6F", "N-54A"}:
        return True

    company_name = (getattr(filing, "company", "") or "").lower()
    file_num = str(getattr(filing, "file_number", "") or "").lower()
    combined_meta = f"{company_name} {file_num}"

    if "814-" in combined_meta or "business development" in combined_meta or re.search(r"\bbdc\b", combined_meta):
        return True

    bdc_patterns = [
        r"business development company",
        r"\bbdc\b",
        r"\b814-\d+",
        r"section 54\(a\)",
        r"sections 55 through 65",
        r"regulated as a business development company",
        r"intent to file an election",
    ]
    return any(re.search(pat, head_text) for pat in bdc_patterns)


class FilingExtraction(BaseModel):
    is_actionable: bool = Field(description="True only for actionable 1940-Act fund/BDC/ETP launches, conversions, or 1940-Act relief; false for routine updates, corporate S-1/10-12G, or Advisers Act 40-APPs.")
    vertical: Literal["etf_launches", "private_markets"] = Field(description="'private_markets' for N-2/N-2/A/BDC/interval/tender/co-invest/on-chain MMF/>15% alts; 'etf_launches' for ETFs/crypto ETPs/ETF relief.")
    brief_category: str = Field(description="Brief category label for the filing.")
    trust_or_registrant_name: Optional[str] = Field(default=None, description="Registrant, trust, or BDC name.")
    fund_name: Optional[str] = Field(default=None, description="Specific fund, BDC, or ETP name.")
    investment_adviser: Optional[str] = Field(default=None, description="Primary adviser or sponsor.")
    sub_adviser: Optional[str] = Field(default=None, description="Sub-adviser if named.")
    legal_counsel_firm: Optional[str] = Field(default=None, description="Outside counsel firm with suffix.")
    lead_attorney: Optional[str] = Field(default=None, description="Named attorney if listed.")
    strategy_asset_class: Optional[str] = Field(default=None, description="1-sentence strategy, wrapper, or relief summary.")
    management_fee: Optional[str] = Field(default=None, description="Stated management/unitary fee or null.")
    listing_exchange: Optional[str] = Field(default=None, description="Target exchange or null.")
    distributor_or_admin: Optional[str] = Field(default=None, description="Distributor or administrator if named.")
    verbatim_key_excerpt: Optional[str] = Field(default=None, description="1-2 sentence verbatim quote from filing.")
    is_tokenized: bool = Field(default=False, description="True only if genuinely tokenized or crypto/digital-asset ETP/fund.")
    tokenization_type: Optional[str] = Field(default=None, description="Tokenized Share Class, On-Chain MMF/Treasury, Spot/Staked Crypto ETP, or Tokenized Private/Interval Fund.")
    digital_transfer_agent: Optional[str] = Field(default=None, description="Tokenization platform or digital TA if named.")
    crypto_custodian: Optional[str] = Field(default=None, description="Crypto/digital asset custodian if named.")
    blockchain_network: Optional[str] = Field(default=None, description="Blockchain network if named.")


def analyze_filing(form_type: str, filing_text: str) -> FilingExtraction:
    excerpt = filing_text[:28000]

    response = anthropic_client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=2048,
        system=(
            "You are a senior 1940-Act & Digital Asset regulatory intelligence analyst. Extract exact facts from the SEC filing. "
            "Never guess or invent names, fees, or exchanges—if blank or '[__]', use null. "
            "For S-1 filings, set is_actionable=true ONLY for crypto/digital-asset ETPs or investment funds. "
            "For 10-12G / 10-12G/A / N-6F / N-54A filings, set is_actionable=true ONLY for BDCs or investment vehicles. "
            "For 40-APP filings, set is_actionable=false for Investment Advisers Act filings (Rule 206(4)-5 pay-to-play or family office exemptions). "
            "Respond ONLY with a single valid JSON object (no markdown fences, no commentary) matching these keys:\n"
            "{"
            '"is_actionable": bool, '
            '"vertical": "etf_launches" | "private_markets", '
            '"brief_category": str, '
            '"trust_or_registrant_name": str | null, '
            '"fund_name": str | null, '
            '"investment_adviser": str | null, '
            '"sub_adviser": str | null, '
            '"legal_counsel_firm": str | null, '
            '"lead_attorney": str | null, '
            '"strategy_asset_class": str | null, '
            '"management_fee": str | null, '
            '"listing_exchange": str | null, '
            '"distributor_or_admin": str | null, '
            '"verbatim_key_excerpt": str | null, '
            '"is_tokenized": bool, '
            '"tokenization_type": str | null, '
            '"digital_transfer_agent": str | null, '
            '"crypto_custodian": str | null, '
            '"blockchain_network": str | null'
            "}"
        ),
        messages=[
            {
                "role": "user",
                "content": f"Form Type: {form_type}\n\nFiling Text:\n{excerpt}"
            }
        ],
    )

    raw_text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ).strip()

    if raw_text.startswith("```"):
        lines = raw_text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw_text = "\n".join(lines).strip()

    payload = json.loads(raw_text)
    if payload.get("vertical") not in ("etf_launches", "private_markets"):
        payload["vertical"] = "private_markets" if form_type in BDC_FORMS or form_type in {"N-2", "N-2/A", "40-APP"} else "etf_launches"

    return FilingExtraction.model_validate(payload)


def get_since_date() -> str:
    explicit_since = (os.environ.get("SCRAPER_SINCE_DATE") or "").strip()
    if explicit_since:
        return explicit_since
    lookback_days = int(os.environ.get("SCRAPER_LOOKBACK_DAYS", "7"))
    return (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")


def run():
    since_date = get_since_date()
    max_filings = int(os.environ.get("SCRAPER_MAX_FILINGS", "80"))
    print(f"[run] Fetching filings since {since_date} (max={max_filings})...", flush=True)

    filings = get_filings(form=TARGET_FORMS, filing_date=f"{since_date}:")
    recent_filings = filings.head(max_filings)
    print(f"[run] Inspecting {len(recent_filings)} filings...", flush=True)

    inserted_count = 0

    for i, filing in enumerate(recent_filings, start=1):
        acc_num = filing.accession_number
        print(f"[{i}/{len(recent_filings)}] Checking {filing.form} ({acc_num})...", flush=True)

        existing = (
            supabase.table("sec_filings")
            .select("accession_number")
            .eq("accession_number", acc_num)
            .execute()
        )
        if existing.data:
            print(f"[{i}/{len(recent_filings)}] Already in DB, skipping {acc_num}.", flush=True)
            continue

        try:
            text = filing.text()
            if not text:
                print(f"[{i}/{len(recent_filings)}] Empty text for {acc_num}, skipping.", flush=True)
                continue

            lower_head = text[:15000].lower()

            if filing.form == "S-1":
                if not any(k in lower_head for k in ("bitcoin", "ethereum", "solana", "digital asset", "crypto", "tokeniz", "trust", "etf", "etp")):
                    print(f"[{i}/{len(recent_filings)}] Pre-filtered non-fund S-1 ({acc_num}).", flush=True)
                    continue

            if filing.form in BDC_FORMS:
                if not looks_like_bdc_filing(filing, lower_head):
                    print(f"[{i}/{len(recent_filings)}] Pre-filtered non-BDC {filing.form} ({acc_num}).", flush=True)
                    continue

            if filing.form == "40-APP":
                if any(k in lower_head for k in ("206(4)-5", "pay-to-play", "pay to play", "political contribution", "202(a)(11)(g)", "family office")):
                    print(f"[{i}/{len(recent_filings)}] Skipping Advisers Act 40-APP ({acc_num}).", flush=True)
                    continue

            print(f"[{i}/{len(recent_filings)}] Running Claude extraction on {filing.form} ({acc_num})...", flush=True)
            extraction = analyze_filing(filing.form, text)

            if not extraction.is_actionable:
                print(f"[{i}/{len(recent_filings)}] Non-actionable {filing.form} ({acc_num}).", flush=True)
                continue

            vertical = extraction.vertical
            brief_category = extraction.brief_category

            if filing.form in BDC_FORMS:
                vertical = "private_markets"
                if brief_category == "Routine Update":
                    brief_category = "Interval & Tender Offer Funds"

            counsel_firm = normalize_law_firm(extraction.legal_counsel_firm)

            row = {
                "accession_number": acc_num,
                "form_type": filing.form,
                "filing_date": str(filing.filing_date),
                "edgar_url": filing.filing_url,
                "vertical": vertical,
                "brief_category": brief_category,
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
            print(f"[{vertical}]{tok_badge} Inserted {filing.form}: {extraction.fund_name or extraction.trust_or_registrant_name}", flush=True)

        except Exception as e:
            print(f"Error processing {acc_num}: {e}", flush=True)

    print(f"Done. Inserted {inserted_count} new actionable filings.", flush=True)


if __name__ == "__main__":
    run()
