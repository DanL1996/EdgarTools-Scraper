import os
import re
import json
from typing import Literal, Optional
from pydantic import BaseModel, Field
from edgar import set_identity, get_filings
from anthropic import Anthropic
from supabase import create_client

# 1. Initialize clients (matching scraper.py)
set_identity(os.environ["EDGAR_IDENTITY"])
anthropic_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# Regex pre-filter: requires >=2 distinct tokenization/digital-asset keywords before calling Claude
TOK_REGEX = re.compile(
    r"\b("
    r"tokeniz\w+|blockchain|distributed ledger|on-chain|onchain|smart contract|"
    r"digital asset\w*|cryptocurrenc\w+|bitcoin|ethereum|solana|stablecoin|"
    r"securitize|superstate|digital transfer agent|erc-20|erc-1400|erc-3643"
    r")\b",
    re.IGNORECASE,
)

WINDOW_REGEX = re.compile(
    r"(transfer agent|custodian|outside counsel|legal counsel|distributed ledger|blockchain|tokeniz\w+|digital asset)",
    re.IGNORECASE,
)


# 2. Strict Pydantic extraction schema for Tokenization & Digital Asset filings
class TokenizationExtraction(BaseModel):
    is_tokenized: bool = Field(
        description=(
            "True ONLY if this filing genuinely registers or seeks exemptive relief for a tokenized share class, "
            "on-chain money market/Treasury fund, spot/staked crypto ETP, or tokenized interval/private fund. "
            "False if crypto/digital assets are merely mentioned in generic boilerplate risk disclosures."
        )
    )
    tokenization_type: Optional[
        Literal[
            "Tokenized Share Class",
            "On-Chain MMF/Treasury",
            "Spot/Staked Crypto ETP",
            "Tokenized Private/Interval Fund",
        ]
    ] = Field(default=None)
    vertical: Literal["etf_launches", "private_markets"] = Field(
        description=(
            "Route to 'private_markets' for N-2 interval/tender-offer/closed-end funds, on-chain MMFs/Treasury funds, "
            "or 40-APP tokenized share-class/multi-class exemptive relief. "
            "Route to 'etf_launches' for spot/staked crypto ETPs, crypto index ETFs, or tokenized ETF share classes."
        )
    )
    brief_category: str = Field(
        description="Use 'Tokenized / Digital Asset Fund' or 'Tokenization Exemptive Relief'."
    )
    trust_or_registrant_name: Optional[str] = Field(default=None)
    fund_name: Optional[str] = Field(default=None)
    investment_adviser: Optional[str] = Field(default=None)
    legal_counsel_firm: Optional[str] = Field(
        default=None,
        description="Normalized outside law firm (e.g., 'Dechert LLP', 'Ropes & Gray LLP', 'Stradley Ronon Stevens & Young, LLP', 'Cahill Gordon & Reindel LLP', 'Chapman and Cutler LLP')."
    )
    digital_transfer_agent: Optional[str] = Field(
        default=None,
        description="Normalized digital transfer agent / tokenization platform (e.g., 'Securitize', 'Superstate', 'Franklin Templeton', 'Taurus', 'Tokeny', 'BNY Mellon', 'State Street')."
    )
    crypto_custodian: Optional[str] = Field(
        default=None,
        description="Normalized qualified crypto custodian (e.g., 'Coinbase Custody', 'Anchorage Digital', 'BitGo', 'Fireblocks', 'BNY Mellon', 'Fidelity Digital Assets')."
    )
    blockchain_network: Optional[str] = Field(
        default=None,
        description="Blockchain network(s) named (e.g., 'Ethereum', 'Solana', 'Stellar', 'Polygon', 'Avalanche', 'Multi-Chain')."
    )
    strategy_asset_class: Optional[str] = Field(default=None)
    verbatim_key_excerpt: Optional[str] = Field(
        default=None,
        description="Exact 1-2 sentence verbatim quote summarizing the tokenized structure, digital transfer agent, or digital asset strategy."
    )


def slice_relevant_windows(text: str, max_chars: int = 12000) -> str:
    """Slices cover page + ±1,600-char windows around service-provider and tokenization mentions."""
    snippets = [text[:3200]]
    spans = [(0, 3200)]
    for m in WINDOW_REGEX.finditer(text):
        s, e = max(3200, m.start() - 1600), min(len(text), m.end() + 1600)
        if any(a <= s <= b for a, b in spans):
            continue
        spans.append((s, e))
        snippets.append(text[s:e])
        if sum(len(x) for x in snippets) >= max_chars:
            break
    return "\n\n--- EXCERPT ---\n\n".join(snippets)[:max_chars]


def analyze_tokenization(form_type: str, filing_text: str) -> TokenizationExtraction:
    condensed = slice_relevant_windows(filing_text)
    response = anthropic_client.messages.parse(
        model="claude-haiku-5-5",
        max_tokens=2048,
        system=(
            "You are an institutional 1940-Act & Digital Asset SEC filing analyst. "
            "Extract exact facts from the SEC filing excerpts. Never guess or invent entity names—return null if undisclosed."
        ),
        messages=[
            {
                "role": "user",
                "content": f"Form Type: {form_type}\n\nFiling Excerpts:\n{condensed}",
            }
        ],
        output_format=TokenizationExtraction,
    )
    return response.parsed_output


def run_backfill():
    # Step A: Evaluate existing 2026 rows already in public.sec_filings first
    print("Checking existing 2026 rows in public.sec_filings...")
    existing_res = (
        supabase.table("sec_filings")
        .select("*")
        .gte("filing_date", "2026-01-01")
        .is_("tokenization_type", "null")
        .execute()
    )

    tagged_existing = 0
    seen_funds = set()

    for row in existing_res.data:
        blob = " ".join(
            filter(
                None,
                [
                    row.get("fund_name"),
                    row.get("strategy_asset_class"),
                    row.get("verbatim_key_excerpt"),
                    json.dumps(row.get("raw_payload") or {}),
                ],
            )
        )
        hits = {m.group(0).lower() for m in TOK_REGEX.finditer(blob)}
        if len(hits) < 2:
            continue

        dedup = (row.get("fund_name") or row.get("trust_or_registrant_name") or row["accession_number"]).strip().lower()
        if dedup in seen_funds:
            continue
        seen_funds.add(dedup)

        try:
            extraction = analyze_tokenization(row["form_type"], blob)
        except Exception as e:
            print(f"Skipping {row['accession_number']} due to parse error: {e}")
            continue

        if extraction.is_tokenized:
            update_data = {
                "is_tokenized": True,
                "tokenization_type": extraction.tokenization_type,
                "digital_transfer_agent": extraction.digital_transfer_agent,
                "crypto_custodian": extraction.crypto_custodian,
                "blockchain_network": extraction.blockchain_network,
            }
            if not row.get("legal_counsel_firm") and extraction.legal_counsel_firm:
                update_data["legal_counsel_firm"] = extraction.legal_counsel_firm

            supabase.table("sec_filings").update(update_data).eq(
                "accession_number", row["accession_number"]
            ).execute()
            tagged_existing += 1
            print(f"[DB Update] Tagged {row.get('fund_name') or row['accession_number']} -> {extraction.tokenization_type}")

    # Step B: Pull 2026 S-1 / N-1A / N-2 / 40-APP filings from EDGAR (including S-1 crypto ETPs not in scraper.py)
    print("Scanning 2026 EDGAR filings (Jan 1, 2026 - Present) for Tokenized & Digital Asset products...")
    filings = get_filings(form=["N-1A", "N-2", "S-1", "40-APP"], filing_date="2026-01-01:")
    print(f"Total 2026 candidate filings in range: {len(filings)}")

    inserted_new = 0
    for filing in filings:
        acc_num = filing.accession_number
        check = (
            supabase.table("sec_filings")
            .select("accession_number")
            .eq("accession_number", acc_num)
            .execute()
        )
        if check.data:
            continue

        try:
            text = filing.text()
            if not text:
                continue

            hits = {m.group(0).lower() for m in TOK_REGEX.finditer(text)}
            if len(hits) < 2:
                continue

            extraction = analyze_tokenization(filing.form, text)
            if not extraction.is_tokenized:
                continue

            dedup = (extraction.fund_name or extraction.trust_or_registrant_name or acc_num).strip().lower()
            if dedup in seen_funds:
                continue
            seen_funds.add(dedup)

            new_row = {
                "accession_number": acc_num,
                "form_type": filing.form,
                "filing_date": str(filing.filing_date),
                "edgar_url": filing.filing_url,
                "vertical": extraction.vertical,
                "brief_category": extraction.brief_category,
                "trust_or_registrant_name": extraction.trust_or_registrant_name,
                "fund_name": extraction.fund_name,
                "investment_adviser": extraction.investment_adviser,
                "legal_counsel_firm": extraction.legal_counsel_firm,
                "strategy_asset_class": extraction.strategy_asset_class,
                "verbatim_key_excerpt": extraction.verbatim_key_excerpt,
                "is_tokenized": True,
                "tokenization_type": extraction.tokenization_type,
                "digital_transfer_agent": extraction.digital_transfer_agent,
                "crypto_custodian": extraction.crypto_custodian,
                "blockchain_network": extraction.blockchain_network,
                "raw_payload": extraction.model_dump(),
            }
            supabase.table("sec_filings").upsert(new_row).execute()
            inserted_new += 1
            print(f"[EDGAR Backfill] Inserted {filing.form}: {extraction.fund_name or extraction.trust_or_registrant_name} ({extraction.tokenization_type})")

        except Exception as e:
            print(f"Error on {acc_num}: {e}")

    print(f"Done! Tagged {tagged_existing} existing rows and inserted {inserted_new} new 2026 tokenized filings.")


if __name__ == "__main__":
    run_backfill()
