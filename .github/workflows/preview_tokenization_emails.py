import os
from supabase import create_client

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def render_league_table_html(title: str, subtitle: str, headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    th_html = "".join(
        f'<th style="text-align:{"left" if i == 0 else "right"};padding:8px 10px;'
        f'border-bottom:2px solid #111827;font-size:11px;text-transform:uppercase;'
        f'letter-spacing:0.04em;color:#4b5563;">{h}</th>'
        for i, h in enumerate(headers)
    )
    tr_html = ""
    for idx, r in enumerate(rows[:5], 1):
        bg = "#f9fafb" if idx % 2 == 0 else "#ffffff"
        tds = "".join(
            f'<td style="text-align:{"left" if i == 0 else "right"};padding:8px 10px;'
            f'border-bottom:1px solid #e5e7eb;font-size:13px;color:#111827;'
            f'font-weight:{"600" if i == 0 else "400"};">{val}</td>'
            for i, val in enumerate(r)
        )
        tr_html += f'<tr style="background:{bg};">{tds}</tr>'

    return f"""
    <div style="margin:24px 0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
      <div style="font-size:14px;font-weight:700;color:#111827;margin-bottom:2px;">{title}</div>
      <div style="font-size:12px;color:#6b7280;margin-bottom:10px;">{subtitle}</div>
      <table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;">
        <thead><tr>{th_html}</tr></thead>
        <tbody>{tr_html}</tbody>
      </table>
    </div>
    """


def render_filings_list_html(heading: str, filings: list[dict]) -> str:
    if not filings:
        return f"<p style='color:#6b7280;font-size:13px;'>No new {heading} filings in this window.</p>"
    items = ""
    for f in filings[:6]:
        name = f.get("fund_name") or f.get("trust_or_registrant_name") or "Untitled Registrant"
        ttype = f.get("tokenization_type") or ""
        sponsor = f.get("investment_adviser") or "Undisclosed Sponsor"
        counsel = f.get("legal_counsel_firm") or "—"
        rail = f.get("digital_transfer_agent") or f.get("crypto_custodian") or "—"
        url = f.get("edgar_url") or "#"
        items += f"""
        <div style="padding:10px 0;border-bottom:1px solid #e5e7eb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
          <div style="font-size:13px;font-weight:700;color:#111827;">
            <a href="{url}" style="color:#1d4ed8;text-decoration:none;">{name}</a>
            <span style="font-size:11px;font-weight:600;background:#eef2ff;color:#3730a3;padding:2px 6px;border-radius:4px;margin-left:6px;">{ttype}</span>
          </div>
          <div style="font-size:12px;color:#374151;margin-top:3px;">
            <strong>Sponsor:</strong> {sponsor} &nbsp;|&nbsp;
            <strong>Infra/Custody:</strong> {rail} &nbsp;|&nbsp;
            <strong>Counsel:</strong> {counsel}
          </div>
        </div>
        """
    return f"<h3 style='font-size:15px;color:#111827;margin:20px 0 6px;font-family:sans-serif;'>{heading}</h3>{items}"


def build_previews():
    # 1. ETF Launches Newsletter Preview (Track 2: Crypto & Digital Asset ETPs)
    etp_filings = (
        supabase.table("sec_filings")
        .select("*")
        .eq("is_tokenized", True)
        .eq("tokenization_type", "Spot/Staked Crypto ETP")
        .order("filing_date", desc=True)
        .limit(5)
        .execute()
        .data
    )
    etp_custodians = supabase.table("tok_league_etp_custodians").select("*").limit(5).execute().data
    custodian_rows = [
        [r["crypto_custodian"], str(r["total_mandates"]), str(r["distinct_sponsors"])]
        for r in etp_custodians
    ]

    etf_html = f"""
    <html><body style="max-width:640px;margin:20px auto;padding:20px;background:#ffffff;">
      {render_filings_list_html("Digital Asset & Staked Crypto ETP Filings", etp_filings)}
      {render_league_table_html(
          "2026 YTD Crypto ETP Custodian League Table",
          "Ranked by 2026 SEC registration mandates (Spot & Staked Crypto ETPs)",
          ["Custodian", "Mandates", "Sponsors"],
          custodian_rows,
      )}
    </body></html>
    """
    with open("preview_etf_tokenization.html", "w") as f:
        f.write(etf_html)

    # 2. Private Markets Newsletter Preview (Track 1: On-Chain & Tokenized Funds)
    onchain_filings = (
        supabase.table("sec_filings")
        .select("*")
        .eq("is_tokenized", True)
        .neq("tokenization_type", "Spot/Staked Crypto ETP")
        .order("filing_date", desc=True)
        .limit(5)
        .execute()
        .data
    )
    onchain_tas = supabase.table("tok_league_onchain_transfer_agents").select("*").limit(5).execute().data
    ta_rows = [
        [
            r["digital_transfer_agent"],
            ", ".join(r.get("networks") or []) or "Multi / Undisclosed",
            str(r["total_mandates"]),
        ]
        for r in onchain_tas
    ]

    pm_html = f"""
    <html><body style="max-width:640px;margin:20px auto;padding:20px;background:#ffffff;">
      {render_filings_list_html("Tokenized Funds & On-Chain Share Class Filings", onchain_filings)}
      {render_league_table_html(
          "2026 YTD On-Chain Transfer Agent & Tokenization Platform League Table",
          "Ranked by 2026 SEC fund registrations & 40-APP exemptive relief filings",
          ["Platform / Transfer Agent", "Networks", "Mandates"],
          ta_rows,
      )}
    </body></html>
    """
    with open("preview_pm_tokenization.html", "w") as f:
        f.write(pm_html)

    print("Saved preview_etf_tokenization.html and preview_pm_tokenization.html!")


if __name__ == "__main__":
    build_previews()
