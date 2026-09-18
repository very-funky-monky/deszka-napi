"""
Összeállítja és elküldi a napi digest e-mailt a Brevo API-n keresztül.

Miért Brevo?
- Nincs szükség saját domainre: elég egyetlen feladó e-mail címet
  hitelesíteni (Brevo küld rá egy megerősítő linket), utána bármelyik
  címzettnek küldhetsz - nem csak magadnak, mint a domain nélküli
  Resendnél/SendGridnél.
- Ingyenes csomag: napi 300 e-mail (nekünk napi 1 kell).

Egy fontos korlátja van: a Brevo API v3 NEM támogat valódi beágyazott
(cid) képet az e-mail törzsében - csak egy nyilvánosan elérhető URL-ről
tud képet betölteni. Ezért a generált képeket a GitHub repóba mentjük
(lásd image_host.py), és az itteni HTML ezekre a raw.githubusercontent.com
linkekre hivatkozik cid helyett.
"""

from __future__ import annotations

import logging

import requests

from config import (
    EMAIL_TO_LIST, EMAIL_FROM, EMAIL_FROM_NAME, BREVO_API_KEY,
    EMAIL_SUBJECT_PREFIX, ACCENT_COLORS, DEFAULT_ACCENT,
)

log = logging.getLogger(__name__)

BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"
REQUEST_TIMEOUT = 30


def send_digest(manifest_items: list[dict], image_urls: list[str], target_date_str: str) -> None:
    if not BREVO_API_KEY:
        raise RuntimeError("Hiányzik a BREVO_API_KEY környezeti változó.")
    if not EMAIL_TO_LIST:
        raise RuntimeError("Hiányzik a DIGEST_EMAIL_TO környezeti változó (vesszővel elválasztott lista).")
    if not EMAIL_FROM:
        raise RuntimeError("Hiányzik a DIGEST_EMAIL_FROM környezeti változó.")

    subject = f"{EMAIL_SUBJECT_PREFIX} – {target_date_str}"
    html_body = _build_html(manifest_items, image_urls)

    payload = {
        "sender": {"name": EMAIL_FROM_NAME, "email": EMAIL_FROM},
        "to": [{"email": addr} for addr in EMAIL_TO_LIST],
        "subject": subject,
        "htmlContent": html_body,
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": BREVO_API_KEY,
    }

    resp = requests.post(BREVO_ENDPOINT, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    log.info("Brevo válasz: %s %s", resp.status_code, resp.text[:300])
    if resp.status_code >= 300:
        raise RuntimeError(f"Brevo hibát adott vissza: {resp.status_code} {resp.text}")


def _build_html(manifest_items: list[dict], image_urls: list[str]) -> str:
    blocks = []
    for item, img_url in zip(manifest_items, image_urls):
        category = item["category"]
        accent = ACCENT_COLORS.get(category, DEFAULT_ACCENT)
        accent_hex = "#%02x%02x%02x" % accent
        pill_bg = "rgba(%d,%d,%d,0.16)" % accent
        url = item["url"]
        blocks.append(f"""
        <tr>
          <td style="padding:0 0 32px 0;">
            <a href="{url}" target="_blank" style="text-decoration:none;">
              <img src="{img_url}" alt="{_escape(item['title'])}"
                   style="width:100%;max-width:420px;display:block;border-radius:8px;" />
            </a>
            <div style="font-family:'Urbanist',Arial,sans-serif;margin-top:10px;">
              <span style="display:inline-block;background:{pill_bg};color:{accent_hex};
                           font-size:12px;font-weight:bold;padding:5px 14px;border-radius:999px;
                           letter-spacing:0.5px;border:1px solid rgba(255,255,255,0.15);">{_escape(category.upper())}</span>
              <div style="color:{accent_hex};font-style:italic;font-size:13px;margin-top:6px;opacity:0.85;">
                {_escape(item['author'])}
              </div>
              <a href="{url}" target="_blank"
                 style="color:#111827;font-size:18px;font-weight:bold;text-decoration:none;
                        display:block;margin-top:4px;line-height:1.3;">
                {_escape(item['title'])}
              </a>
              <a href="{url}" target="_blank" style="color:#0d9488;font-size:12px;">
                {_escape(url)}
              </a>
            </div>
          </td>
        </tr>
        """)

    return f"""
    <html>
      <body style="background:#f4f4f5;margin:0;padding:24px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td align="center">
              <table role="presentation" width="480" cellpadding="0" cellspacing="0"
                     style="background:#ffffff;border-radius:10px;padding:24px;">
                <tr>
                  <td style="font-family:Arial,sans-serif;font-size:20px;font-weight:bold;
                             padding-bottom:20px;color:#111827;">
                    Deszkavízió – napi összefoglaló
                  </td>
                </tr>
                {''.join(blocks) if blocks else '<tr><td style="font-family:Arial,sans-serif;color:#555;">Ma nem jelent meg cikk.</td></tr>'}
              </table>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
