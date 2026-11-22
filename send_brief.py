import os
from datetime import datetime, timezone
from supabase import create_client

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# --- SPONSOR CONFIGURATION ---
# Set to None when unsold so no placeholder text appears in live issues.
# Populate the dictionary fields below once a sponsor is booked.
PRESENTING_SPONSOR = None
# Example when active:
# PRESENTING_SPONSOR = {
#     "name": "Tidal Financial Group",
#     "tagline": "Powering the next generation of 1940-Act ETFs & Interval Funds.",
#     "cta_text": "Learn more",
#     "url": "https://example.com"
# }

PARTNER_SPOTLIGHT = None
# Example when active:
# PARTNER_SPOTLIGHT = {
#     "headline": "Launching an Active ETF or Mutual Fund Conversion in 2026?",
#     "body": "Tidal provides turnkey 1940-Act trust administration, capital markets support, and compliance infrastructure—getting your fund from initial N-1A to listing in 75 days.",
#     "cta_text": "Request a Launch Timeline",
#     "url": "https://example.com"
# }


def format_meta_pills(row: dict) -> str:
    """Builds clean inline metadata badges only for populated fields."""
    items = []
    if row.get("investment_adviser"):
        items.append(f"<strong>Adviser:</strong> {row['investment_adviser']}")
    if row.get("sub_adviser"):
        items.append(f"<strong>Sub-Adviser:</strong> {row['sub_adviser']}")

    counsel_parts = [p for p in [row.get("lead_attorney"), row.get("legal_counsel_firm")] if p]
    if counsel_parts:
        items.append(f"<strong>Counsel:</strong> {', '.join(counsel_parts)}")

    if row.get("listing_exchange"):
        items.append(f"<strong>Exchange:</strong> {row['listing_exchange']}")
    if row.get("management_fee"):
        items.append(f"<strong>Mgmt Fee:</strong> {row['management_fee']}")
    if row.get("distributor_or_admin"):
        items.append(f"<strong>Admin/Dist:</strong> {row['distributor_or_admin']}")

    return " &nbsp;|&nbsp; ".join(items)


def render_filing_card(row: dict) -> str:
    title = row.get("fund_name") or row.get("trust_or_registrant_name") or "Unnamed Registrant"
    trust = row.get("trust_or_registrant_name")
    subtitle = f"<div style='font-size:13px;color:#64748b;margin-top:2px;'>{trust}</div>" if trust and trust != title else ""
    meta_html = format_meta_pills(row)
    strategy = row.get("strategy_asset_class") or ""
    excerpt = row.get("verbatim_key_excerpt") or ""
    url = row.get("edgar_url") or "#"
    form_type = row.get("form_type") or ""
    filing_date = row.get("filing_date") or ""

    return f"""
    <div style="border-bottom:1px solid #e2e8f0;padding:18px 0;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
        <span style="display:inline-block;background:#eff6ff;color:#1d4ed8;font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;letter-spacing:0.4px;">
          FORM {form_type} &bull; {filing_date}
        </span>
      </div>
      <div style="font-size:16px;font-weight:700;color:#0f172a;line-height:1.35;">
        {title}
      </div>
      {subtitle}
      <div style="font-size:13px;color:#334155;margin-top:8px;line-height:1.5;">
        {meta_html}
      </div>
      <p style="font-size:14px;color:#1e293b;margin:10px 0 8px 0;line-height:1.55;">
        {strategy}
      </p>
      {f'<blockquote style="margin:8px 0 10px 0;padding:8px 12px;border-left:3px solid #94a3b8;background:#f8fafc;color:#475569;font-size:13px;font-style:italic;line-height:1.5;">“{excerpt}”</blockquote>' if excerpt else ''}
      <a href="{url}" target="_blank" style="font-size:13px;font-weight:600;color:#1d4ed8;text-decoration:none;">
        View Official SEC Filing &rarr;
      </a>
    </div>
    """


def build_brief_html(filings: list[dict]) -> str:
    today_str = datetime.now(timezone.utc).strftime("%B %d, %Y")

    grouped = {
        "New Fund Launch": [],
        "ETF Conversion / Material Amendment": [],
        "Exemptive Relief Application": [],
    }
    for f in filings:
        cat = f.get("brief_category")
        if cat in grouped:
            grouped[cat].append(f)
        else:
            grouped["New Fund Launch"].append(f)

    sections_html = ""
    section_index = 0

    for category, items in grouped.items():
        if not items:
            continue
        section_index += 1
        cards = "".join(render_filing_card(item) for item in items)
        sections_html += f"""
        <div style="margin-top:26px;">
          <h2 style="font-size:13px;text-transform:uppercase;letter-spacing:1px;color:#0f172a;border-bottom:2px solid #0f172a;padding-bottom:6px;margin:0;">
            {category} ({len(items)})
          </h2>
          {cards}
        </div>
        """

        if section_index == 1 and PARTNER_SPOTLIGHT:
            sections_html += f"""
            <div style="margin:24px 0;padding:18px 20px;background:#f8fafc;border:1px solid #cbd5e1;border-left:4px solid #0f172a;border-radius:4px;">
              <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#64748b;margin-bottom:6px;">
                Partner Spotlight &bull; Sponsored
              </div>
              <div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:6px;">
                {PARTNER_SPOTLIGHT["headline"]}
              </div>
              <div style="font-size:13.5px;color:#334155;line-height:1.55;margin-bottom:10px;">
                {PARTNER_SPOTLIGHT["body"]}
              </div>
              <a href="{PARTNER_SPOTLIGHT["url"]}" target="_blank" style="display:inline-block;background:#0f172a;color:#ffffff;font-size:12.5px;font-weight:600;padding:7px 14px;border-radius:4px;text-decoration:none;">
                {PARTNER_SPOTLIGHT["cta_text"]} &rarr;
              </a>
            </div>
            """

    presenting_html = ""
    if PRESENTING_SPONSOR:
        presenting_html = f"""
        <div style="background:#f8fafc;border-bottom:1px solid #e2e8f0;padding:12px 28px;font-size:12.5px;color:#334155;">
          <span style="font-weight:700;text-transform:uppercase;font-size:10px;letter-spacing:0.8px;color:#64748b;margin-right:8px;">
            Presented By
          </span>
          <strong>{PRESENTING_SPONSOR["name"]}</strong>:
          {PRESENTING_SPONSOR["tagline"]}
          <a href="{PRESENTING_SPONSOR["url"]}" target="_blank" style="color:#1d4ed8;font-weight:600;text-decoration:none;margin-left:4px;">{PRESENTING_SPONSOR["cta_text"]} &rarr;</a>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>1940-Act Daily Regulatory Brief — {today_str}</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <div style="max-width:680px;margin:24px auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;">
    
    <!-- Masthead -->
    <div style="background:#0f172a;color:#ffffff;padding:24px 28px;">
      <div style="font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:#94a3b8;font-weight:600;">
        Daily SEC EDGAR Intelligence &bull; {today_str}
      </div>
      <h1 style="margin:6px 0 4px 0;font-size:22px;font-weight:800;letter-spacing:-0.3px;">
        The 1940-Act Filing Brief
      </h1>
      <div style="font-size:13px;color:#cbd5e1;">
        New ETF &amp; Fund Launches, Conversions, and Exemptive Relief Applications
      </div>
    </div>

    {presenting_html}

    <!-- Main Body -->
    <div style="padding:10px 28px 28px 28px;">
      <div style="font-size:13.5px;color:#475569;margin-top:12px;line-height:1.5;">
        Good morning. Here are the <strong>{len(filings)} actionable 1940-Act filings</strong> spotted on SEC EDGAR, complete with counsel, adviser, and key prospectus disclosures.
      </div>

      {sections_html}
    </div>

    <!-- Footer -->
    <div style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:18px 28px;font-size:12px;color:#64748b;line-height:1.5;">
      <strong>Interested in sponsoring The 1940-Act Filing Brief?</strong> Reach 1940-Act legal counsel, ETF issuers, and fund executives every morning. Reply to this email for the 2026 media kit.
    </div>

  </div>
</body>
</html>
"""


def run():
    response = (
        supabase.table("sec_filings")
        .select("*")
        .order("filing_date", desc=True)
        .limit(15)
        .execute()
    )
    filings = response.data or []
    print(f"Loaded {len(filings)} filings from Supabase.")

    html = build_brief_html(filings)
    with open("daily_brief.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Generated daily_brief.html successfully.")


if __name__ == "__main__":
    run()
