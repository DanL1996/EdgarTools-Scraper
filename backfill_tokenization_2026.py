import os
import re
import json
from typing import Literal, Optional
from pydantic import BaseModel, Field
from edgar import set_identity, get_filings
from anthropic import Anthropic
from supabase import create_client

# 1. Initialize clients
set_identity(os.environ["EDGAR_IDENTITY"])
anthropic_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

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
    legal_counsel_firm: Optional[str] = Field(default=None)
    digital_transfer_agent: Optional[str] = Field(default=None)
    crypto_custodian: Optional[str] = Field(default=None)
    blockchain_network: Optional[str] = Field(default=None)
    strategy_asset_class: Optional[str] = Field(default=None)
    verbatim_key_excerpt: Optional[str] = Field(default=None)


def slice_relevant_windows(text: str, max_chars: int = 12000) -> str:
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
    print("Scanning Jan 1, 2026 - Jun 15, 2026 EDGAR filings for Tokenized & Digital Asset products...", flush=True)
    filings = get_filings(form=["N-1A", "N-2", "S-1", "40-APP"], filing_date="2026-01-01:2026-06-15")
    print(f"Total candidate filings in Jan-Jun 2026 range: {len(filings)}", flush=True)

    seen_funds = set()
    inserted_new = 0

    for idx, filing in enumerate(filings, 1):
        if idx % 50 == 0:
            print(f"Progress: scanned {idx}/{len(filings)} filings ({inserted_new} inserted)...", flush=True)

        # Skip non-fund corporate S-1 IPOs in 0ms before downloading full filing text
        if filing.form == "S-1":
            comp = (filing.company or "").lower()
            if not any(
                k in comp
                for k in (
                    "trust", "etf", "etp", "fund", "bitcoin", "ethereum", "solana",
                    "crypto", "digital", "token", "coin", "blockchain", "asset",
                    "capital", "shares", "strategy", "treasury",
                )
            ):
                continue

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
            print(
                f"[EDGAR Backfill] Inserted {filing.form} ({filing.filing_date}): "
                f"{extraction.fund_name or extraction.trust_or_registrant_name} ({extraction.tokenization_type})",
                flush=True,
            )

        except Exception as e:
            print(f"Error on {acc_num}: {e}", flush=True)

    print(f"Done! Inserted {inserted_new} new Jan-Jun 2026 tokenized filings.", flush=True)


if __name__ == "__main__":
    run_backfill()
