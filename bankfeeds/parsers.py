"""
Read bank statements downloaded from online banking.

* **CSV** from any bank or the M-Pesa business portal. The header row is found
  automatically (statements often start with a few lines about the account), and
  columns are recognised by their usual names: date, description/narration/details,
  money in/credit/paid in, money out/debit/withdrawn, a single signed amount, a
  reference and the running balance.
* **OFX / QFX** ("Money" or "Quicken" format), offered by many banks.

Each parser returns a list of `StatementLine`s with a stable `external_id`, so
uploading the same statement twice, or two statements that overlap, never adds a
line twice.
"""

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


class StatementError(Exception):
    """The file can't be read as a statement. The message is shown to the user."""


@dataclass
class StatementLine:
    date: date
    amount: Decimal
    description: str = ""
    reference: str = ""
    balance: Decimal | None = None
    payer_name: str = ""
    payer_phone: str = ""
    external_id: str = ""
    raw: dict = field(default_factory=dict)


# ---------------------------------------------------------------- helpers

DATE_FORMATS_DAY_FIRST = [
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d %b %Y", "%d-%b-%Y", "%d-%b-%y",
    "%d %B %Y", "%b %d, %Y", "%d/%b/%Y", "%Y/%m/%d", "%m/%d/%Y",
]
DATE_FORMATS_MONTH_FIRST = ["%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%b %d, %Y", "%d %b %Y", "%d-%b-%Y", "%Y/%m/%d"]


def parse_date(value, month_first=False):
    text = (value or "").strip()
    if not text:
        return None
    # Drop a time of day: "2026-10-31 14:05:11", "31/10/2026 2:05 PM", "2026-10-31T14:05:11".
    text = re.split(r"[ T](?=\d{1,2}:\d{2})", text)[0].strip()
    for fmt in DATE_FORMATS_MONTH_FIRST if month_first else DATE_FORMATS_DAY_FIRST:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(value):
    """'1,250.00' '(1,250.00)' '-1250' 'KSh 1,250.00' '1,250.00 CR' '1,250.00 DR' -> Decimal or None."""
    text = (value or "").strip()
    if not text or text in {"-", "—", "–"}:
        return None
    negative = False
    upper = text.upper()
    if upper.endswith("DR"):
        negative, text = True, text[:-2]
    elif upper.endswith("CR"):
        text = text[:-2]
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    text = re.sub(r"[^\d.\-]", "", text)
    if text.startswith("-"):
        negative, text = not negative, text[1:]
    if not text or text == ".":
        return None
    try:
        amount = Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return -amount if negative else amount


def _norm(header):
    return re.sub(r"[^a-z]", "", (header or "").lower())


COLUMN_NAMES = {
    "date": ["transactiondate", "date", "transdate", "postingdate", "postdate", "bookingdate", "completiontime",
             "trandate", "txndate", "datetime", "initiationtime", "valuedate"],
    "description": ["description", "narration", "narrative", "details", "particulars", "transactiondetails",
                    "remarks", "memo", "transactiondescription", "payee", "name"],
    "money_in": ["moneyin", "credit", "credits", "paidin", "deposit", "deposits", "creditamount", "cr", "amountin", "receipts", "in"],
    "money_out": ["moneyout", "debit", "debits", "withdrawn", "withdrawal", "withdrawals", "debitamount", "dr", "amountout", "payments", "out"],
    "amount": ["amount", "transactionamount", "amountkes", "value"],
    "direction": ["type", "drcr", "crdr", "debitcredit", "transactiontype"],
    "reference": ["reference", "referenceno", "ref", "refno", "receiptno", "receipt", "chequeno", "chequenumber",
                  "checknumber", "transactionid", "transactionref", "bankreference", "documentno"],
    "balance": ["balance", "runningbalance", "closingbalance", "ledgerbalance", "availablebalance", "bookbalance"],
    "other_party": ["otherpartyinfo", "otherparty", "counterparty", "sender", "paidby"],
    "status": ["transactionstatus", "status"],
}


def _map_columns(headers):
    normed = [_norm(h) for h in headers]
    mapping = {}
    for key, names in COLUMN_NAMES.items():
        for name in names:  # names are in order of preference
            if name in normed:
                idx = normed.index(name)
                if idx not in mapping.values():
                    mapping[key] = idx
                    break
    return mapping


def _fingerprint(*parts):
    return "h-" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:24]


def _split_party(text):
    """M-Pesa 'Other Party Info' looks like '2547******123 - JOHN DOE'."""
    m = re.match(r"^\s*([\d*+ ]{6,})\s*[-–]\s*(.+)$", text or "")
    return (m.group(2).strip(), m.group(1).strip()) if m else ((text or "").strip(), "")


# -------------------------------------------------------------------- CSV

def parse_csv(content, month_first=False):
    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect)]
    header_idx, mapping = None, None
    for i, row in enumerate(rows[:40]):
        m = _map_columns(row)
        if "date" in m and ("amount" in m or "money_in" in m or "money_out" in m):
            header_idx, mapping = i, m
            break
    if header_idx is None:
        raise StatementError(
            "Couldn't find the column headings. The statement needs a date column and either an amount column "
            "or money in / money out columns. Download it from online banking as CSV and upload it unchanged."
        )
    headers = rows[header_idx]
    lines, seen = [], {}

    def cell(row, key):
        idx = mapping.get(key)
        return row[idx].strip() if idx is not None and idx < len(row) else ""

    for row in rows[header_idx + 1:]:
        if not any(c.strip() for c in row):
            continue
        d = parse_date(cell(row, "date"), month_first)
        if d is None:
            continue  # totals, page footers, "Opening balance" lines...
        status = cell(row, "status").lower()
        if status and status not in {"completed", "complete", "success", "successful"}:
            continue
        if "amount" in mapping and "money_in" not in mapping and "money_out" not in mapping:
            amount = parse_amount(cell(row, "amount"))
            direction = cell(row, "direction").lower()
            if amount is not None and direction in {"dr", "debit", "d", "withdrawal", "out"}:
                amount = -abs(amount)
            elif amount is not None and direction in {"cr", "credit", "c", "deposit", "in"}:
                amount = abs(amount)
        else:
            money_in = parse_amount(cell(row, "money_in")) or Decimal("0")
            money_out = parse_amount(cell(row, "money_out")) or Decimal("0")
            amount = abs(money_in) - abs(money_out)
        if not amount:
            continue
        description = cell(row, "description")
        party = cell(row, "other_party")
        name, phone = _split_party(party) if party else ("", "")
        reference = cell(row, "reference")[:60]
        balance = parse_amount(cell(row, "balance"))
        key = (d.isoformat(), str(amount), description, reference, str(balance))
        seen[key] = seen.get(key, 0) + 1
        external_id = f"r-{reference}"[:80] if reference and reference.upper() not in {"-", "N/A", "NA"} else _fingerprint(*key, seen[key])
        if reference and seen[key] > 1:
            external_id = f"{external_id}-{seen[key]}"[:80]
        lines.append(StatementLine(
            date=d, amount=amount, description=(description or party)[:255], reference=reference, balance=balance,
            payer_name=name[:150] if amount > 0 else "", payer_phone=phone[:40] if amount > 0 else "",
            external_id=external_id, raw=dict(zip(headers, row)),
        ))
    if not lines:
        raise StatementError("No transactions were found in this statement.")
    return lines


# -------------------------------------------------------------------- OFX

def _ofx_value(block, tag):
    m = re.search(rf"<{tag}>([^<\r\n]*)", block, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def parse_ofx(content):
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    blocks = re.findall(r"<STMTTRN>(.*?)(?=</STMTTRN>|<STMTTRN>|</BANKTRANLIST>)", text, re.IGNORECASE | re.DOTALL)
    if not blocks:
        raise StatementError("No transactions were found in this OFX file.")
    lines = []
    for b in blocks:
        posted = _ofx_value(b, "DTPOSTED")[:8]
        try:
            d = datetime.strptime(posted, "%Y%m%d").date()
        except ValueError:
            continue
        amount = parse_amount(_ofx_value(b, "TRNAMT"))
        if not amount:
            continue
        name, memo = _ofx_value(b, "NAME"), _ofx_value(b, "MEMO")
        fitid = _ofx_value(b, "FITID")
        reference = (_ofx_value(b, "CHECKNUM") or _ofx_value(b, "REFNUM") or fitid)[:60]
        description = " · ".join([p for p in [name] if p] + ([memo] if memo and memo != name else []))[:255]
        lines.append(StatementLine(
            date=d, amount=amount, description=description, reference=reference,
            payer_name=name[:150] if amount > 0 else "",
            external_id=(f"o-{fitid}" if fitid else _fingerprint(d, amount, description))[:80],
            raw={"FITID": fitid, "NAME": name, "MEMO": memo, "TRNTYPE": _ofx_value(b, "TRNTYPE")},
        ))
    closing = parse_amount(_ofx_value(text.split("</BANKTRANLIST>")[-1], "BALAMT")) if "</BANKTRANLIST>" in text.upper() else None
    if lines and closing is not None:
        lines[-1].raw["closing_balance"] = str(closing)
    return lines


def parse_statement(file_name, content, month_first=False):
    name = (file_name or "").lower()
    head = (content[:200].decode("utf-8", errors="ignore") if isinstance(content, bytes) else content[:200]).upper()
    if name.endswith((".ofx", ".qfx")) or "OFXHEADER" in head or "<OFX>" in head:
        return parse_ofx(content)
    if name.endswith((".xlsx", ".xls", ".pdf")):
        raise StatementError("Please download the statement as CSV (or OFX). Excel and PDF statements can't be read yet; "
                             "in Excel, use File → Save As → CSV.")
    return parse_csv(content, month_first)
