import html
import os
from datetime import datetime, timedelta, timezone
from supabase import create_client

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# --- CADENCE SETTINGS ---
# Weekday for Private Markets weekly brief: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
PM_WEEKLY_DAY = 4  # Friday

# --- EDITION CONFIGURATIONS ---
EDITIONS = {
    "etf_launches": {
        "output_file": "brief_launches.html",
        "source_table": "sec_filings",
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
        "source_table": "pm_email_filings",
        "kicker": "Alternative & Illiquid Registered Funds",
        "title": "Private Markets in Public Funds Brief",
        "subtitle": "Interval Funds, Tender Offer Funds, BDCs, Private Credit & Exemptive Relief",
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
      <div style="margin-bottom:6px;">
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


def fetch_pm_ytd_tracker(current_year: int) -> dict:
    """Fetches YTD scoreboard, top law firms, and top sponsors for the active calendar year."""
    sb_res = (
        supabase.table("pm_ytd_scoreboard")
        .select("*")
        .eq("filing_year", current_year)
        .execute()
    )
    law_res = (
        supabase.table("pm_league_law_firms")
        .select("*")
        .eq("filing_year", current_year)
        .neq("law_firm", "Unspecified")
        .limit(8)
        .execute()
    )
    sponsor_res = (
        supabase.table("pm_league_sponsors")
        .select("*")
        .eq("filing_year", current_year)
        .limit(8)
        .execute()
    )
    return {
        "scoreboard": (sb_res.data[0] if sb_res.data else {}),
        "law_firms": (law_res.data or []),
        "sponsors": (sponsor_res.data or []),
    }


def render_pm_ytd_tracker_html(tracker: dict, current_year: int, cfg: dict) -> str:
    """Renders the bottom YTD Scoreboard & League Tables section."""
    sb = tracker.get("scoreboard") or {}
    law_firms = tracker.get("law_firms") or []
    sponsors = tracker.get("sponsors") or []

    new_interval = sb.get("new_interval_funds", 0)
    new_tender = sb.get("new_tender_offer_funds", 0)
    new_bdc = sb.get("new_bdcs", 0)
    new_exemptive = sb.get("new_exemptive_apps", 0)
    total_n2 = sb.get("total_new_n2_launches", 0)
    n2_amend = sb.get("n2_amendments", 0)

    # Law Firm League Table (Firm Name Only + Full Math Breakdown)
    law_rows_html = ""
    for idx, row in enumerate(law_firms, start=1):
        firm = html.escape(str(row.get("law_firm") or "Unspecified"))
        n2_count = int(row.get("new_launches") or 0)
        n2a_count = int(row.get("amendments") or 0)
        app_count = int(row.get("exemptive_apps") or 0)
        total_count = int(row.get("total_filings") or 0)
        law_rows_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0;">
          <td style="padding:8px 6px;font-size:12.5px;color:#64748b;font-weight:700;">{idx}</td>
          <td style="padding:8px 6px;font-size:12.5px;color:#0f172a;font-weight:600;">{firm}</td>
          <td align="right" style="padding:8px 6px;font-size:12.5px;color:#0f172a;font-weight:600;">{n2_count}</td>
          <td align="right" style="padding:8px 6px;font-size:12.5px;color:#334155;">{n2a_count}</td>
          <td align="right" style="padding:8px 6px;font-size:12.5px;color:#334155;">{app_count}</td>
          <td align="right" style="padding:8px 6px;font-size:12.5px;color:{cfg['accent_color']};font-weight:700;">{total_count}</td>
        </tr>
        """

    sponsor_rows = ""
    for idx, row in enumerate(sponsors, start=1):
        structures = ", ".join(row.get("structures") or [])
        sponsor_rows += f"""
        <tr style="border-bottom:1px solid #e2e8f0;">
          <td style="padding:8px 6px;font-size:12.5px;color:#64748b;font-weight:700;">{idx}</td>
          <td style="padding:8px 6px;font-size:12.5px;color:#0f172a;font-weight:600;">
            {html.escape(str(row.get('sponsor') or '—'))}
            <div style="font-size:11px;color:#64748b;font-weight:400;">{html.escape(structures)}</div>
          </td>
          <td align="center" style="padding:8px 6px;font-size:12.5px;color:#0f172a;font-weight:600;">{row.get('new_launches', 0)}</td>
          <td align="right" style="padding:8px 6px;font-size:12.5px;color:{cfg['accent_color']};font-weight:700;">{row.get('total_filings', 0)}</td>
        </tr>
        """

    return f"""
    <div id="ytd-tracker" name="ytd-tracker" style="margin-top:36px;padding-top:24px;border-top:3px solid {cfg['accent_color']};">
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:{cfg['badge_text']};">
        Year-to-Date Market Tracker
      </div>
      <h2 style="margin:4px 0 14px 0;font-size:18px;font-weight:800;color:#0f172a;">
        {current_year} Private Markets Activity &amp; League Tables
      </h2>

      <!-- 4-Card Structure Scoreboard -->
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:12px;">
        <tr>
          <td width="25%" style="padding-right:6px;">
            <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:4px;padding:10px 8px;text-align:center;">
              <div style="font-size:20px;font-weight:800;color:{cfg['accent_color']};">{new_interval}</div>
              <div style="font-size:10.5px;font-weight:700;color:#475569;text-transform:uppercase;margin-top:2px;">Interval Funds</div>
            </div>
          </td>
          <td width="25%" style="padding:0 3px;">
            <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:4px;padding:10px 8px;text-align:center;">
              <div style="font-size:20px;font-weight:800;color:{cfg['accent_color']};">{new_tender}</div>
              <div style="font-size:10.5px;font-weight:700;color:#475569;text-transform:uppercase;margin-top:2px;">Tender Offer</div>
            </div>
          </td>
          <td width="25%" style="padding:0 3px;">
            <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:4px;padding:10px 8px;text-align:center;">
              <div style="font-size:20px;font-weight:800;color:{cfg['accent_color']};">{new_bdc}</div>
              <div style="font-size:10.5px;font-weight:700;color:#475569;text-transform:uppercase;margin-top:2px;">New BDCs</div>
            </div>
          </td>
          <td width="25%" style="padding-left:6px;">
            <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:4px;padding:10px 8px;text-align:center;">
              <div style="font-size:20px;font-weight:800;color:{cfg['accent_color']};">{new_exemptive}</div>
              <div style="font-size:10.5px;font-weight:700;color:#475569;text-transform:uppercase;margin-top:2px;">40-APP Relief</div>
            </div>
          </td>
        </tr>
      </table>
      <div style="font-size:11.5px;color:#64748b;margin-bottom:22px;">
        <strong>{current_year} YTD Totals:</strong> {total_n2} initial N-2 launches &bull; {n2_amend} N-2/A registration amendments &bull; {new_exemptive} new exemptive relief applications.
      </div>

      <!-- League Table A: Most Active Law Firms -->
      <h3 style="font-size:12.5px;text-transform:uppercase;letter-spacing:0.8px;color:{cfg['accent_color']};border-bottom:1.5px solid {cfg['accent_color']};padding-bottom:5px;margin:0 0 6px 0;">
        {current_year} YTD League Table: Most Active Law Firms
      </h3>
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;margin-bottom:24px;">
        <thead>
          <tr style="border-bottom:1px solid #cbd5e1;font-size:10.5px;text-transform:uppercase;color:#64748b;">
            <th align="left" style="padding:6px;">#</th>
            <th align="left" style="padding:6px;">Law Firm</th>
            <th align="right" style="padding:6px;white-space:nowrap;">New N-2</th>
            <th align="right" style="padding:6px;white-space:nowrap;">N-2/A</th>
            <th align="right" style="padding:6px;white-space:nowrap;">Exemp. Relief</th>
            <th align="right" style="padding:6px;">Total</th>
          </tr>
        </thead>
        <tbody>
          {law_rows_html or '<tr><td colspan="6" style="padding:10px;font-size:12.5px;color:#64748b;">No law firm data recorded yet for this year.</td></tr>'}
        </tbody>
      </table>

      <!-- League Table B: Most Active Sponsors -->
      <h3 style="font-size:12.5px;text-transform:uppercase;letter-spacing:0.8px;color:{cfg['accent_color']};border-bottom:1.5px solid {cfg['accent_color']};padding-bottom:5px;margin:0 0 6px 0;">
        {current_year} YTD League Table: Most Active Fund Sponsors
      </h3>
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
        <thead>
          <tr style="border-bottom:1px solid #cbd5e1;font-size:10.5px;text-transform:uppercase;color:#64748b;">
            <th align="left" style="padding:6px;">#</th>
            <th align="left" style="padding:6px;">Adviser / Sponsor</th>
            <th align="center" style="padding:6px;">New N-2</th>
            <th align="right" style="padding:6px;">Total</th>
          </tr>
        </thead>
        <tbody>
          {sponsor_rows or '<tr><td colspan="4" style="padding:10px;font-size:12.5px;color:#64748b;">No sponsor data recorded yet for this year.</td></tr>'}
        </tbody>
      </table>
    </div>
    """


def build_brief_html(filings: list[dict], cfg: dict, ytd_tracker_html: str = "", show_jump_btn: bool = False) -> str:
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%B %d, %Y")
    current_year = now_utc.year
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
          No new primary launches or exemptive applications were filed in the past 7 days. See the full YTD scoreboard and league tables below.
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

    jump_button_html = ""
    if show_jump_btn:
        jump_button_html = f"""
        <td align="right" valign="middle" style="padding-left:12px;">
          <a href="#ytd-tracker" style="display:inline-block;background-color:rgba(255,255,255,0.16);border:1px solid rgba(255,255,255,0.45);color:#ffffff;text-decoration:none;font-size:11.5px;font-weight:700;padding:7px 12px;border-radius:4px;white-space:nowrap;">
            {current_year} YTD Tracker &darr;
          </a>
        </td>
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
    
    <!-- Masthead with Optional Right-Aligned Jump Button -->
    <div style="background:{cfg['accent_color']};color:#ffffff;padding:24px 28px;">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td align="left" valign="middle">
            <div style="font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:#cbd5e1;font-weight:600;">
              {cfg['kicker']} &bull; {today_str}
            </div>
            <h1 style="margin:6px 0 4px 0;font-size:22px;font-weight:800;letter-spacing:-0.3px;color:#ffffff;">
              {cfg['title']}
            </h1>
            <div style="font-size:13px;color:#e2e8f0;">
              {cfg['subtitle']}
            </div>
          </td>
          {jump_button_html}
        </tr>
      </table>
    </div>

    {presenting_html}

    <!-- Main Body -->
    <div style="padding:10px 28px 28px 28px;">
      <div style="font-size:13.5px;color:#475569;margin-top:12px;line-height:1.5;">
        Here are the <strong>{len(filings)} notable filings</strong> spotted on SEC EDGAR, complete with counsel, adviser, and key prospectus disclosures.
      </div>

      {sections_html}

      {ytd_tracker_html}
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
    now_utc = datetime.now(timezone.utc)
    current_year = now_utc.year
    seven_days_ago = (now_utc - timedelta(days=7)).strftime("%Y-%m-%d")
    is_manual_dispatch = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"

    for vertical_key, cfg in EDITIONS.items():
        if vertical_key == "private_markets":
            # Weekly cadence check (runs on PM_WEEKLY_DAY or manual workflow_dispatch)
            if now_utc.weekday() != PM_WEEKLY_DAY and not is_manual_dispatch:
                print(f"[private_markets] Skipping scheduled send (runs 1x/week on weekday {PM_WEEKLY_DAY}).")

            # Fetch last 7 days of high-signal filings (N-2, 40-APP, and N-2/A; excludes 40-APP/A noise)
            response = (
                supabase.table(cfg["source_table"])
                .select("*")
                .gte("filing_date", seven_days_ago)
                .in_("form_type", ["N-2", "40-APP", "N-2/A"])
                .order("filing_date", desc=True)
                .limit(25)
                .execute()
            )
            filings = response.data or []
            print(f"[{vertical_key}] Loaded {len(filings)} weekly filings from {cfg['source_table']}.")

            tracker_data = fetch_pm_ytd_tracker(current_year)
            ytd_html = render_pm_ytd_tracker_html(tracker_data, current_year, cfg)
            brief_output = build_brief_html(filings, cfg, ytd_tracker_html=ytd_html, show_jump_btn=True)
        else:
            response = (
                supabase.table(cfg["source_table"])
                .select("*")
                .eq("vertical", vertical_key)
                .order("filing_date", desc=True)
                .limit(15)
                .execute()
            )
            filings = response.data or []
            print(f"[{vertical_key}] Loaded {len(filings)} filings from {cfg['source_table']}.")
            brief_output = build_brief_html(filings, cfg)

        with open(cfg["output_file"], "w", encoding="utf-8") as f:
            f.write(brief_output)
        print(f"[{vertical_key}] Generated {cfg['output_file']} successfully.")


if __name__ == "__main__":
    run()
