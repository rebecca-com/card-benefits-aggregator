import re
import csv
import json
import yaml
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

OUT_DIR = Path("public/data")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return normalize_ws(soup.get_text(separator=" "))

def pick_snippet(text: str, keyword: str, window: int = 220) -> str:
    if not text:
        return ""
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return ""
    start = max(0, idx - window)
    end = min(len(text), idx + window)
    return normalize_ws(text[start:end])

def find_first(patterns, text):
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            return normalize_ws(m.group(0))
    return ""

def parse_fields(text: str) -> dict:
    # Heuristics: simple patterns that often work on issuer pages
    welcome_bonus = find_first([
        r"(Earn|Get)\s+(?:up to\s+)?[\d,]+\s+(points|miles)\b[^.]{0,120}",
        r"[\d,]+\s+(points|miles)\s+(welcome|bonus)[^.]{0,120}",
        r"(Earn|Get)\s+\$[\d,]+\b[^.]{0,120}",
    ], text)

    spend_requirement = find_first([
        r"after you spend\s+\$[\d,]+[^.]{0,120}",
        r"after spending\s+\$[\d,]+[^.]{0,120}",
        r"spend\s+\$[\d,]+[^.]{0,120}",
    ], text)

    annual_fee = find_first([
        r"annual fee[^.]{0,60}",
        r"\$\d+\s+annual fee[^.]{0,60}",
    ], text)

    # Earn / accelerator hints (very rough)
    accelerators = find_first([
        r"\b\d+x\b[^.]{0,140}",
        r"\b\d+\s*(points|miles)\b\s+per\s+\$1[^.]{0,140}",
        r"earn\s+\d+\s*(points|miles)[^.]{0,140}",
    ], text)

    perks_hint = find_first([
        r"free\s+checked\s+bag[^.]{0,140}",
        r"priority\s+boarding[^.]{0,140}",
        r"anniversary[^.]{0,140}",
        r"companion[^.]{0,140}",
        r"statement\s+credit[^.]{0,140}",
        r"lounge[^.]{0,140}",
    ], text)

    # Evidence snippets for auditing
    evidence = {
        "bonus_snippet": pick_snippet(text, "bonus") or pick_snippet(text, "Earn"),
        "spend_snippet": pick_snippet(text, "spend") or pick_snippet(text, "after you spend"),
        "fee_snippet": pick_snippet(text, "annual fee"),
        "earn_snippet": pick_snippet(text, "per $1") or pick_snippet(text, "x"),
    }

    return {
        "welcome_bonus": welcome_bonus,
        "spend_requirement": spend_requirement,
        "accelerators": accelerators,
        "annual_fee_text": annual_fee,
        "perks_hint": perks_hint,
        **evidence,
    }

def main():
    with open("cards.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    cards = cfg.get("cards", [])
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        for c in cards:
            url = c.get("url", "")
            row = {
                "id": c.get("id", ""),
                "name": c.get("name", ""),
                "issuer": c.get("issuer", ""),
                "url": url,
            }

            if not url or "PASTE_PUBLIC_CARD_URL_HERE" in url:
                row.update({"status": "MISSING_URL"})
                results.append(row)
                continue

            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                html = page.content()
                text = extract_visible_text(html)
                fields = parse_fields(text)
                row.update(fields)
                row["status"] = "OK"
            except Exception as e:
                row["status"] = f"ERROR: {type(e).__name__}"
            results.append(row)

        context.close()
        browser.close()

    # Write JSON
    (OUT_DIR / "cards.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    # Write CSV
    csv_path = OUT_DIR / "cards.csv"
    cols = [
        "id","name","issuer","url","status",
        "welcome_bonus","spend_requirement","accelerators","annual_fee_text","perks_hint",
        "bonus_snippet","spend_snippet","fee_snippet","earn_snippet",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in cols})

if __name__ == "__main__":
    main()
