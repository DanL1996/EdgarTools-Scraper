import os
from datetime import datetime, timezone
from supabase import create_client

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# --- EDITION CONFIGURATIONS ---
# Update titles, subtitles, and sponsor dicts here whenever you finalize names or book sponsors.
EDITIONS = {
    "etf_launches": {
        "output_file": "brief_launches.html",
        "kicker": "1940-Act Regulatory Intelligence",
        "title": "ETF & Fund Launch Brief",
        "subtitle": "New ETF & Mutual Fund Launches, Conversions, and Exemptive Relief Applications",
        "accent_color": "#0f172a",   # Navy Slate
        "badge_bg": "#eff6ff",
        "badge_text": "#1d4ed8",
        "categories": [
            "New Fund Launch",
            "ETF Conversion / Material Amendment",
            "Exemptive Relief Application",
        ],
        "presenting_sponsor": None,
        "partner_spotlight": None,
    },
    "private_markets": {
        "output_file": "brief_private_markets.html",
        "kicker": "Alternative & Illiquid Registered Funds",
        "title": "Private Markets in Public Funds Brief",
        "subtitle": "Interval Funds, Tender Offer Funds, BDCs, Private Credit & PE-in-ETF Filings",
        "accent_color": "#064e3b",   # Institutional Forest Green
        "badge_bg": "#ecfdf5",
        "badge_text": "#047857",
        "categories": [
            "New Interval / Tender Offer Fund",
            "Private Credit / PE ETF Launch",
            "Co-Investment & Multi-Class Relief",
        ],
        "presenting_sponsor": None,
        "partner_spotlight": None,
    },
}


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


def render_filing_card(row: dict, cfg: dict) -> str:
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
        <span style="display:inline-block;background:{cfg['badge_bg']};color:{cfg['badge_text']};font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;letter-spacing:0.4px;">
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
      <a href="{url}" target="_blank" style="font-size:13px;font-weight:600;color:{cfg['badge_text']};text-decoration:none;">
        View Official SEC Filing &rarr;
      </a>
    </div>
    """


def build_brief_html(filings: list[dict], cfg: dict) -> str:
    today_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    default_cat = cfg["categories"][0]

    grouped = {cat: [] for cat in cfg["categories"]}
    for f in filings:
        cat = f.get("brief_category")
        if cat in grouped:
            grouped[cat].append(f)
        else:
            grouped[default_cat].append(f)

    sections_html = ""
    section_index = 0
    spotlight = cfg.get("partner_spotlight")

    for category, items in grouped.items():
        if not items:
            continue
        section_index += 1
        cards = "".join(render_filing_card(item, cfg) for item in items)
        sections_html += f"""
        <div style="margin-top:26px;">
          <h2 style="font-size:13px;text-transform:uppercase;letter-spacing:1px;color:{cfg['accent_color']};border-bottom:2px solid {cfg['accent_color']};padding-bottom:6px;margin:0;">
            {category} ({len(items)})
          </h2>
          {cards}
        </div>
        """

        if section_index == 1 and spotlight:
            sections_html += f"""
            <div style="margin:24px 0;padding:18px 20px;background:#f8fafc;border:1px solid #cbd5e1;border-left:4px solid {cfg['accent_color']};border-radius:4px;">
              <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#64748b;margin-bottom:6px;">
                Partner Spotlight &bull; Sponsored
              </div>
              <div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:6px;">
                {spotlight["headline"]}
              </div>
              <div style="font-size:13.5px;color:#334155;line-height:1.55;margin-bottom:10px;">
                {spotlight["body"]}
              </div>
              <a href="{spotlight["url"]}" target="_blank" style="display:inline-block;background:{cfg['accent_color']};color:#ffffff;font-size:12.5px;font-weight:600;padding:7px 14px;border-radius:4px;text-decoration:none;">
                {spotlight["cta_text"]} &rarr;
              </a>
            </div>
            """

    if not sections_html:
        sections_html = """
        <div style="margin-top:24px;padding:20px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:4px;color:#475569;font-size:14px;">
          No new filings matched this vertical in the latest run. Once N-2 and private-market filings are ingested, they will populate here automatically.
        </div>
        """

    presenting = cfg.get("presenting_sponsor")
    presenting_html = ""
    if presenting:
        presenting_html = f"""
        <div style="background:#f8fafc;border-bottom:1px solid #e2e8f0;padding:12px 28px;font-size:12.5px;color:#334155;">
          <span style="font-weight:700;text-transform:uppercase;font-size:10px;letter-spacing:0.8px;color:#64748b;margin-right:8px;">
            Presented By
          </span>
          <strong>{presenting["name"]}</strong>:
          {presenting["tagline"]}
          <a href="{presenting["url"]}" target="_blank" style="color:{cfg['badge_text']};font-weight:600;text-decoration:none;margin-left:4px;">{presenting["cta_text"]} &rarr;</a>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{cfg['title']} — {today_str}</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <div style="max-width:680px;margin:24px auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;">
    
    <!-- Masthead -->
    <div style="background:{cfg['accent_color']};color:#ffffff;padding:24px 28px;">
      <div style="font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:#cbd5e1;font-weight:600;">
        {cfg['kicker']} &bull; {today_str}
      </div>
      <h1 style="margin:6px 0 4px 0;font-size:22px;font-weight:800;letter-spacing:-0.3px;">
        {cfg['title']}
      </h1>
      <div style="font-size:13px;color:#e2e8f0;">
        {cfg['subtitle']}
      </div>
    </div>

    {presenting_html}

    <!-- Main Body -->
    <div style="padding:10px 28px 28px 28px;">
      <div style="font-size:13.5px;color:#475569;margin-top:12px;line-height:1.5;">
        Here are the <strong>{len(filings)} notable filings</strong> spotted on SEC EDGAR, complete with counsel, adviser, and key prospectus disclosures.
      </div>

      {sections_html}
    </div>

    <!-- Footer -->
    <div style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:18px 28px;font-size:12px;color:#64748b;line-height:1.5;">
      <strong>Interested in sponsoring the {cfg['title']}?</strong> Reach 1940-Act legal counsel, fund sponsors, and product heads. Reply to this email for the media kit.
    </div>

  </div>
</body>
</html>
"""


def run():
    for vertical_key, cfg in EDITIONS.items():
        response = (
            supabase.table("sec_filings")
            .select("*")
            .eq("vertical", vertical_key)
            .order("filing_date", desc=True)
            .limit(15)
            .execute()
        )
        filings = response.data or []
        print(f"[{vertical_key}] Loaded {len(filings)} filings from Supabase.")

        html = build_brief_html(filings, cfg)
        with open(cfg["output_file"], "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[{vertical_key}] Generated {cfg['output_file']} successfully.")


if __name__ == "__main__":
    run()
