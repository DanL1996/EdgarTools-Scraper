import os
import re
import json
import time
import urllib.request
import anthropic
from supabase import create_client

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# Fast keyword filter for candidate detection
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

SEC_HEADERS = {"User-Agent": os.environ.get("SEC_USER_AGENT", "RegisteredAltsMonitor admin@registeredaltsmonitor.com")}


def fetch_edgar_if_needed(row: dict) -> str:
    """Uses stored text/payload first; fetches edgar_url only if text isn't already stored."""
    stored = " ".join(
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
    if len(stored) > 2500:
        return stored

    url = row.get("edgar_url")
    if not url:
        return stored

    try:
        req = urllib.request.Request(url, headers=SEC_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        clean = re.sub(r"<[^>]+>", " ", html)
        clean = re.sub(r"\s+", " ", clean)
        time.sleep(0.15)  # Respect SEC 10 req/sec rate limit
        return clean
    except Exception:
        return stored


def slice_relevant_windows(text: str, max_chars: int = 11000) -> str:
    snippets = [text[:3000]]
    spans = [(0, 3000)]
    for m in WINDOW_REGEX.finditer(text):
        s, e = max(3000, m.start() - 1600), min(len(text), m.end() + 1600)
        if any(a <= s <= b for a, b in spans):
            continue
        spans.append((s, e))
        snippets.append(text[s:e])
        if sum(len(x) for x in snippets) >= max_chars:
            break
    return "\n\n---\n\n".join(snippets)[:max_chars]


PROMPT = """You are an institutional 1940-Act & Digital Asset SEC filing analyst.
Return ONLY valid JSON matching this exact schema:
{
  "is_tokenized": boolean,
  "tokenization_type": "Tokenized Share Class" | "On-Chain MMF/Treasury" | "Spot/Staked Crypto ETP" | "Tokenized Private/Interval Fund" | null,
  "digital_transfer_agent": string | null,
  "crypto_custodian": string | null,
  "blockchain_network": string | null,
  "legal_counsel_firm": string | null,
  "verbatim_key_excerpt": string | null
}
Rules:
- Set is_tokenized to false if the filing merely mentions digital assets/crypto inside generic boilerplate risk factors.
- Normalize entity names cleanly (e.g., "Securitize", "Superstate", "Franklin Templeton", "Coinbase Custody", "Anchorage Digital", "BitGo", "Fireblocks", "BNY Mellon", "Dechert LLP", "Ropes & Gray LLP", "Stradley Ronon Stevens & Young, LLP", "Cahill Gordon & Reindel LLP", "Chapman and Cutler LLP").
"""


def run_backfill():
    res = (
        supabase.table("sec_filings")
        .select(
            "accession_number, form_type, filing_date, edgar_url, fund_name, "
            "trust_or_registrant_name, strategy_asset_class, legal_counsel_firm, "
            "verbatim_key_excerpt, raw_payload"
        )
        .gte("filing_date", "2026-01-01")
        .is_("tokenization_type", "null")
        .order("filing_date", desc=False)
        .execute()
    )

    seen_funds = set()
    tagged_count = 0

    for row in res.data:
        # Deduplicate by normalized fund/registrant name so we don't pay twice for amendments
        dedup_key = (row.get("fund_name") or row.get("trust_or_registrant_name") or row["accession_number"]).strip().lower()
        if dedup_key in seen_funds:
            continue

        full_text = fetch_edgar_if_needed(row)
        hits = {m.group(0).lower() for m in TOK_REGEX.finditer(full_text)}
        if len(hits) < 2:
            continue

        seen_funds.add(dedup_key)
        condensed = slice_relevant_windows(full_text)

        msg = claude.messages.create(
            model="claude-haiku-5-5",
            max_tokens=400,
            temperature=0,
            messages=[{"role": "user", "content": f"{PROMPT}\n\nFILING TEXT:\n{condensed}"}],
        )
        raw_json = re.sub(r"^```json|```$", "", msg.content[0].text.strip()).strip()
        parsed = json.loads(raw_json)

        if parsed.get("is_tokenized"):
            update_payload = {
                "is_tokenized": True,
                "tokenization_type": parsed.get("tokenization_type"),
                "digital_transfer_agent": parsed.get("digital_transfer_agent"),
                "crypto_custodian": parsed.get("crypto_custodian"),
                "blockchain_network": parsed.get("blockchain_network"),
            }
            if not row.get("legal_counsel_firm") and parsed.get("legal_counsel_firm"):
                update_payload["legal_counsel_firm"] = parsed["legal_counsel_firm"]
            if not row.get("verbatim_key_excerpt") and parsed.get("verbatim_key_excerpt"):
                update_payload["verbatim_key_excerpt"] = parsed["verbatim_key_excerpt"]

            supabase.table("sec_filings").update(update_payload).eq(
                "accession_number", row["accession_number"]
            ).execute()
            tagged_count += 1
            print(f"[+] Tagged {row.get('fund_name') or row['accession_number']} -> {parsed.get('tokenization_type')}")

    print(f"Complete: {tagged_count} tokenized/digital filings tagged in public.sec_filings.")


if __name__ == "__main__":
    run_backfill()
