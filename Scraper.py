import os
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional
from pydantic import BaseModel, Field
from edgar import set_identity, get_filings
from anthropic import Anthropic
from supabase import create_client

# 1. Authenticate clients from GitHub Secrets
set_identity(os.environ["EDGAR_IDENTITY"])
anthropic_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# 2. Target 1940-Act product launch & exemptive forms
TARGET_FORMS = ["N-1A", "485APOS", "485BPOS", "N-2", "40-APP"]


class FilingExtraction(BaseModel):
    brief_category: Literal[
        "New Fund Launch / Registration",
        "Material Amendment / Conversion",
        "Exemptive Relief Application",
        "Routine / Ignore",
    ]
    trust_or_registrant_name: Optional[str] = Field(
        None, description="Full legal name of the Trust or Registrant"
    )
    fund_name: Optional[str] = Field(
        None, description="Specific new fund or series name if applicable"
    )
    investment_adviser: Optional[str] = Field(
        None, description="Primary investment adviser / sponsor"
    )
    strategy_asset_class: Optional[str] = Field(
        None, description="Concise summary of investment strategy, wrapper (ETF/Interval/Mutual Fund), and asset class"
    )
    legal_counsel_firm: Optional[str] = Field(
        None, description="Outside fund counsel or law firm named on cover page or signature block"
    )
    verbatim_key_excerpt: Optional[str] = Field(
        None, description="Exact 1-2 sentence verbatim quote from filing describing the new product or relief sought"
    )


def extract_with_claude(form_type: str, filing_text: str) -> FilingExtraction:
    prompt = f"""You are a senior 1940-Act regulatory analyst. Extract structured intelligence from this SEC Form {form_type} filing.
Rules:
- Only classify as 'New Fund Launch / Registration', 'Material Amendment / Conversion', or 'Exemptive Relief Application' if it introduces a new fund/series, converts a mutual fund to an ETF, or requests novel 1940-Act exemptive relief.
- Classify routine annual prospectus updates (485BPOS with no new fund/material change) or routine administrative filings as 'Routine / Ignore'.
- Do NOT guess or fabricate law firms, advisers, or quotes. Return null if not explicitly present in the text.

FILING EXCERPT:
{filing_text[:28000]}
"""
    response = anthropic_client.messages.parse(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
        output_format=FilingExtraction,
    )
    return response.parsed_output


def run():
    # Look back 3 days so weekend/holiday manual runs still catch recent SEC filings
    start_date = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    print(f"Fetching 1940-Act filings since {start_date}...")

    filings = get_filings(form=TARGET_FORMS, filing_date=f"{start_date}:")
    if not filings or len(filings) == 0:
        print("No matching filings found in window.")
        return

    # Cap at 25 filings per run to keep test runs fast and low-cost
    batch = list(filings)[:25]
    print(f"Inspecting {len(batch)} filings...")

    inserted = 0
    for filing in batch:
        acc_no = filing.accession_no
        existing = (
            supabase.table("sec_filings")
            .select("accession_number")
            .eq("accession_number", acc_no)
            .execute()
        )
        if existing.data:
            continue

        try:
            text = filing.text()
            if not text or len(text.strip()) < 200:
                continue

            extracted = extract_with_claude(filing.form, text)
            if extracted.brief_category == "Routine / Ignore":
                print(f"
