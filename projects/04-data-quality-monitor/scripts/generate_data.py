"""Generates the Contoso Pay sample data (fictional) and plants known data quality defects.

Writes one SQL file that empties the wallet and dq run tables and reloads the data with COPY,
plus evaluation/planted-defects.json: for every planted defect, the rule that must catch it and
the exact record ids it must report. That answer key is what the evaluation grades against.

    python scripts/generate_data.py                 # data with 16 planted defects (one per rule)
    python scripts/generate_data.py --clean         # clean data: every rule must pass
    docker exec -i <postgres-container> psql -U <user> -d contoso_dq -q < data/seed.sql

Clean data obeys every rule by construction: unique references, correct fees, balances that never
go negative, and a daily ledger built from the completed transactions. Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIRST = ["Tendai", "Rudo", "Farai", "Chipo", "Tatenda", "Nyasha", "Kudzai", "Tafadzwa", "Rutendo", "Tinashe",
         "Vimbai", "Takudzwa", "Ruvimbo", "Simba", "Nokuthula", "Sipho", "Thandeka", "Blessing", "Precious", "Tawanda"]
LAST = ["Moyo", "Ncube", "Dube", "Sibanda", "Mpofu", "Chikwanha", "Mutasa", "Marufu", "Gumbo", "Ndlovu",
        "Zhou", "Chari", "Mhlanga", "Nyathi", "Musoni", "Banda", "Mlambo", "Chirwa", "Makoni", "Shumba"]
CENT = Decimal("0.01")


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


def withdrawal_fee(amount: Decimal) -> Decimal:
    """FSD-2026-031 BR-03: 1.5% of the amount, minimum 0.25, maximum 15.00, rounded to the cent."""
    return money(min(max(amount * Decimal("0.015"), Decimal("0.25")), Decimal("15.00")))


def ts(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M:%S+00")


def copy_block(table: str, columns: list[str], rows: list[list]) -> str:
    def cell(v):
        if v is None:
            return r"\N"
        return str(v).replace("\\", "\\\\").replace("\t", " ").replace("\n", " ")
    lines = ["\t".join(cell(v) for v in r) for r in rows]
    return f"COPY {table} ({', '.join(columns)}) FROM STDIN;\n" + "\n".join(lines) + "\n\\.\n"


def generate(seed: int, clean: bool, days: int, per_day: int):
    rnd = random.Random(seed)
    now = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
    today = now.date()
    first_day = today - dt.timedelta(days=days)
    planted: list[dict] = []

    def plant(rule, ids, what, keywords):
        planted.append({"rule_code": rule, "expected_record_ids": sorted(str(i) for i in ids), "defect": what,
                        "cause_keywords": keywords})

    # ── customers ────────────────────────────────────────────────────────────
    customers = []
    for cid in range(1001, 2501):
        first, last = rnd.choice(FIRST), rnd.choice(LAST)
        created = now - dt.timedelta(days=rnd.randint(days + 1, 720), minutes=rnd.randint(0, 1439))
        kyc = rnd.choices(["verified", "pending", "rejected"], [88, 9, 3])[0]
        customers.append({"customer_id": cid, "full_name": f"{first} {last}", "email": f"{first}.{last}{cid}@example.com".lower(),
                          "phone": f"+263 77 555 {cid:04d}", "kyc_status": kyc, "country": "ZW", "created_at": created})

    # ── wallets: one per customer, plus a second wallet for some ──────────────
    wallets = []
    for c in customers:
        wallets.append({"wallet_id": 50000 + c["customer_id"], "customer_id": c["customer_id"], "currency": "USD", "status": "active",
                        "opened_at": c["created_at"] + dt.timedelta(minutes=5)})
    for c in rnd.sample(customers, 300):
        wallets.append({"wallet_id": 60000 + c["customer_id"], "customer_id": c["customer_id"],
                        "currency": rnd.choice(["ZWG", "ZAR"]), "status": "active",
                        "opened_at": c["created_at"] + dt.timedelta(days=1)})
    balance = {w["wallet_id"]: money(rnd.uniform(50, 1500)) for w in wallets}
    start_balance = dict(balance)

    # ── transactions, in time order, so balances never go negative ───────────
    txns = []
    txn_id = 9_000_000
    wallet_ids = [w["wallet_id"] for w in wallets]
    latest_full_day = today - dt.timedelta(days=1)
    for d in range(days):
        day = first_day + dt.timedelta(days=d)
        if day > latest_full_day:
            break
        n = int(per_day * rnd.uniform(0.88, 1.12))
        if not clean and day == latest_full_day:
            n = int(per_day * 0.3)                       # planted volume drop on the latest day
        times = sorted(dt.datetime.combine(day, dt.time(), dt.timezone.utc) + dt.timedelta(seconds=rnd.randint(0, 86399))
                       for _ in range(n))
        for seq, t in enumerate(times, 1):
            wid = rnd.choice(wallet_ids)
            kind = rnd.choices(["deposit", "withdrawal", "p2p_send", "p2p_receive"], [35, 25, 20, 20])[0]
            if kind == "deposit":
                amount = money(rnd.uniform(5, 1500))
            elif kind == "withdrawal":
                amount = money(rnd.choice([rnd.uniform(2, 16), rnd.uniform(16, 1000), rnd.uniform(1000, 2500)]))
            else:
                amount = money(rnd.uniform(1, 800))
            fee = withdrawal_fee(amount) if kind == "withdrawal" else Decimal("0.00")
            status = rnd.choices(["completed", "failed", "pending"], [95, 4, 1])[0]
            debit = amount + fee if kind in ("withdrawal", "p2p_send") else Decimal(0)
            if status == "completed" and debit > balance[wid]:
                status = "failed"                          # insufficient balance: rejected, as in production
            if status == "completed":
                balance[wid] += amount if kind in ("deposit", "p2p_receive") else -debit
            txn_id += 1
            txns.append({"txn_id": txn_id, "wallet_id": wid, "txn_type": kind, "amount": amount, "fee": fee, "status": status,
                         "external_ref": f"CPS{day:%Y%m%d}{seq:06d}", "created_at": t})
    for w in wallets:
        w["balance"] = balance[w["wallet_id"]]

    feeds = [
        {"feed_name": "mobile_money_transactions", "source_system": "Payment switch", "last_loaded_at": now - dt.timedelta(minutes=50), "rows_loaded": len(txns), "sla_hours": 2},
        {"feed_name": "core_banking_ledger", "source_system": "Core banking", "last_loaded_at": now - dt.timedelta(hours=3), "rows_loaded": 0, "sla_hours": 24},
        {"feed_name": "kyc_updates", "source_system": "KYC provider", "last_loaded_at": now - dt.timedelta(hours=7), "rows_loaded": 412, "sla_hours": 48},
        {"feed_name": "card_settlements", "source_system": "Card processor", "last_loaded_at": now - dt.timedelta(hours=5), "rows_loaded": 1873, "sla_hours": 24},
    ]

    if not clean:
        by_id = {c["customer_id"]: c for c in customers}
        pick = rnd.sample(range(1001, 2501), 10)
        # completeness
        for cid, value in zip(pick[0:3], [None, "", "   "]):
            by_id[cid]["email"] = value
        plant("CUST_EMAIL_MISSING", pick[0:3], "3 customers saved without an email (NULL, empty, spaces)",
              ["optional", "required", "mandatory", "validation", "not captured", "onboarding", "sign-up", "registration", "import"])
        # validity
        by_id[pick[3]]["email"] = "tendai.moyo@example"
        by_id[pick[4]]["email"] = "rudo.ncube at example.com"
        plant("CUST_EMAIL_FORMAT", pick[3:5], "2 emails with no top-level domain / no @",
              ["validation", "format", "typo", "regex", "free-text", "free text", "domain", "manual"])
        # uniqueness
        shared = by_id[pick[5]]["email"]
        by_id[pick[6]]["email"] = shared.upper()
        plant("CUST_EMAIL_DUPLICATE", [shared], "a second customer saved with the same email in a different case",
              ["duplicate", "unique", "shared", "same email", "re-regist", "merge", "case"])
        for cid in pick[7:9]:
            by_id[cid]["kyc_status"] = "approved"
        plant("CUST_KYC_STATUS", pick[7:9], "2 customers with KYC status 'approved' (not an allowed value)",
              ["mapping", "enum", "allowed", "source system", "provider", "code", "translat", "lookup", "vendor"])
        # wallets
        orphans = []
        for k in range(3):
            wid = 59001 + k
            wallets.append({"wallet_id": wid, "customer_id": 99001 + k, "currency": "USD", "status": "active",
                            "opened_at": now - dt.timedelta(days=3), "balance": money(20 + k)})
            orphans.append(wid)
        plant("WALLET_ORPHAN", orphans, "3 wallets whose customer_id doesn't exist",
              ["deleted", "referential", "foreign key", "load order", "migration", "orphan", "not yet loaded", "sequence", "missing customer"])
        neg = rnd.sample([w for w in wallets if w["wallet_id"] < 59000], 3)
        neg[0]["balance"], neg[1]["balance"] = Decimal("-45.20"), Decimal("-310.00")
        plant("WALLET_NEGATIVE_BALANCE", [neg[0]["wallet_id"], neg[1]["wallet_id"]], "2 wallets with a negative balance",
              ["overdraft", "race", "concurrent", "double", "reversal", "fee", "insufficient", "balance check", "duplicate"])
        neg[2]["currency"] = "US$"
        plant("WALLET_CURRENCY", [neg[2]["wallet_id"]], "1 wallet with currency 'US$' instead of the ISO code USD",
              ["iso", "code", "mapping", "free-text", "free text", "symbol", "standard", "manual"])

        def new_txn(**kw):
            nonlocal txn_id
            txn_id += 1
            base = {"txn_id": txn_id, "status": "completed", "fee": Decimal("0.00"),
                    "external_ref": f"CPSX{txn_id}", "created_at": now - dt.timedelta(days=2, hours=rnd.randint(1, 20))}
            base.update(kw)
            txns.append(base)
            return txn_id
        # duplicate payments: same reference posted twice
        originals = rnd.sample([t for t in txns if t["status"] == "completed" and t["txn_type"] == "deposit"], 4)
        for o in originals:
            copy = {k: v for k, v in o.items() if k != "txn_id"}
            copy["created_at"] = o["created_at"] + dt.timedelta(seconds=2)
            new_txn(**copy)
        plant("TXN_DUPLICATE_REF", [o["external_ref"] for o in originals], "4 deposits posted twice with the same switch reference",
              ["duplicate", "retry", "replay", "twice", "double", "idempoten", "resubmit", "re-sent", "resent"])
        good_wallet = wallets[0]["wallet_id"]
        ids = [new_txn(wallet_id=good_wallet, txn_type="deposit", amount=a) for a in (Decimal("0.00"), Decimal("-25.00"), Decimal("15000.00"))]
        plant("TXN_AMOUNT_RANGE", ids, "deposits of 0.00, -25.00 and 15,000.00",
              ["validation", "limit", "zero", "negative", "reversal", "refund", "sign", "decimal", "cents", "unit"])
        ids = [new_txn(wallet_id=good_wallet, txn_type="deposit", amount=Decimal("120.00"), created_at=now + dt.timedelta(days=2, hours=h))
               for h in (1, 3)]
        plant("TXN_FUTURE_DATE", ids, "2 deposits dated two days in the future",
              ["time zone", "timezone", "clock", "utc", "offset", "timestamp", "date format", "server time"])
        ids = [new_txn(wallet_id=99901 + k, txn_type="deposit", amount=Decimal("75.00")) for k in range(2)]
        plant("TXN_ORPHAN_WALLET", ids, "2 transactions on wallet ids that don't exist",
              ["load order", "referential", "foreign key", "deleted", "migration", "not yet loaded", "test", "missing wallet", "sequence"])
        ids = [new_txn(wallet_id=good_wallet, txn_type="withdrawal", amount=a, fee=f)
               for a, f in ((Decimal("10.00"), Decimal("0.15")), (Decimal("2000.00"), Decimal("30.00")), (Decimal("33.33"), Decimal("0.49")))]
        plant("TXN_WITHDRAWAL_FEE", ids, "fees without the 0.25 minimum, without the 15.00 maximum, and truncated instead of rounded",
              ["minimum", "maximum", "cap", "floor", "ceiling", "round", "truncat", "min", "max"])
        for f in feeds:
            if f["feed_name"] == "card_settlements":
                f["last_loaded_at"] = now - dt.timedelta(hours=50)
        plant("FEED_FRESHNESS", ["card_settlements"], "the card settlement feed last loaded 50 hours ago (SLA 24 h)",
              ["job", "pipeline", "fail", "delay", "stale", "schedul", "outage", "late", "credential", "stopped"])
        plant("TXN_VOLUME_DROP", [latest_full_day.isoformat()], "the latest day has 30% of the usual transaction volume",
              ["outage", "incomplete", "partial", "load", "pipeline", "feed", "missing", "downtime", "cut-off", "cutoff"])

    # ── daily ledger, built from the completed transactions as loaded ─────────
    ledger_moves: dict[tuple, list] = {}
    for t in sorted(txns, key=lambda t: t["created_at"]):
        if t["status"] != "completed":
            continue
        key = (t["created_at"].date(), t["wallet_id"])
        cr = t["amount"] if t["txn_type"] in ("deposit", "p2p_receive") else Decimal(0)
        db = t["amount"] + t["fee"] if t["txn_type"] in ("withdrawal", "p2p_send") else Decimal(0)
        m = ledger_moves.setdefault(key, [Decimal(0), Decimal(0)])
        m[0] += cr
        m[1] += db
    running = {w: start_balance.get(w, Decimal("0.00")) for w in {k[1] for k in ledger_moves}}
    ledger = []
    for (day, wid), (cr, db) in sorted(ledger_moves.items()):
        opening = running[wid]
        closing = opening + cr - db
        running[wid] = closing
        ledger.append({"ledger_date": day, "wallet_id": wid, "opening_balance": opening, "total_credits": cr,
                       "total_debits": db, "closing_balance": closing})
    if not clean:
        normal = [l for l in ledger if l["wallet_id"] < 59000 and l["ledger_date"] < latest_full_day - dt.timedelta(days=3)]
        a, b = rnd.sample(normal, 2)
        a["closing_balance"] += Decimal("12.50")
        plant("LEDGER_ARITHMETIC", [f"{a['wallet_id']}@{a['ledger_date']}"], "one ledger row's closing balance is 12.50 too high",
              ["manual", "adjustment", "rounding", "calculation", "posting", "override", "sync", "overwrit", "edit"])
        b["total_credits"] += Decimal("100.00")
        b["closing_balance"] += Decimal("100.00")
        plant("LEDGER_TXN_RECON", [f"{b['wallet_id']}@{b['ledger_date']}"], "one ledger row has a 100.00 credit with no matching transaction",
              ["missing", "reversal", "late", "cut-off", "cutoff", "adjustment", "manual", "duplicate", "timing", "posted", "unrecorded"])
    return customers, wallets, txns, ledger, feeds, planted, now


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clean", action="store_true", help="no planted defects")
    ap.add_argument("--seed", type=int, default=31)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--per-day", type=int, default=300)
    ap.add_argument("--out", default=str(ROOT / "data" / "seed.sql"))
    ap.add_argument("--keep-history", action="store_true", help="keep earlier monitor runs and incidents")
    args = ap.parse_args()

    customers, wallets, txns, ledger, feeds, planted, now = generate(args.seed, args.clean, args.days, args.per_day)
    parts = ["-- Generated by scripts/generate_data.py. Fictional data for Contoso Pay.\nSET client_min_messages = warning;\nBEGIN;\n",
             "TRUNCATE wallet.customers, wallet.wallets, wallet.transactions, wallet.daily_ledger, wallet.feed_loads;\n"]
    if not args.keep_history:
        parts.append("TRUNCATE dq.incidents, dq.results, dq.runs RESTART IDENTITY;\n")
    parts += [
        copy_block("wallet.customers", ["customer_id", "full_name", "email", "phone", "kyc_status", "country", "created_at"],
                   [[c["customer_id"], c["full_name"], c["email"], c["phone"], c["kyc_status"], c["country"], ts(c["created_at"])] for c in customers]),
        copy_block("wallet.wallets", ["wallet_id", "customer_id", "currency", "status", "balance", "opened_at"],
                   [[w["wallet_id"], w["customer_id"], w["currency"], w["status"], w["balance"], ts(w["opened_at"])] for w in wallets]),
        copy_block("wallet.transactions", ["txn_id", "wallet_id", "txn_type", "amount", "fee", "status", "external_ref", "created_at"],
                   [[t["txn_id"], t["wallet_id"], t["txn_type"], t["amount"], t["fee"], t["status"], t["external_ref"], ts(t["created_at"])] for t in txns]),
        copy_block("wallet.daily_ledger", ["ledger_date", "wallet_id", "opening_balance", "total_credits", "total_debits", "closing_balance"],
                   [[l["ledger_date"], l["wallet_id"], l["opening_balance"], l["total_credits"], l["total_debits"], l["closing_balance"]] for l in ledger]),
        copy_block("wallet.feed_loads", ["feed_name", "source_system", "last_loaded_at", "rows_loaded", "sla_hours"],
                   [[f["feed_name"], f["source_system"], ts(f["last_loaded_at"]), f["rows_loaded"], f["sla_hours"]] for f in feeds]),
        "COMMIT;\nANALYZE wallet.transactions;\n",
    ]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(parts), encoding="utf-8")

    key = ROOT / "evaluation" / ("planted-defects.json" if not args.clean else "planted-defects-clean.json")
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_text(json.dumps({"generated_at": now.isoformat(), "seed": args.seed, "clean": args.clean,
                               "counts": {"customers": len(customers), "wallets": len(wallets), "transactions": len(txns), "ledger_rows": len(ledger)},
                               "defects": planted}, indent=2) + "\n", encoding="utf-8")
    print(f"{out}: {len(customers)} customers, {len(wallets)} wallets, {len(txns)} transactions, {len(ledger)} ledger rows; "
          f"{len(planted)} planted defects -> {key.name}")


if __name__ == "__main__":
    main()
