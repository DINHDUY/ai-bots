from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


SESSION = "etl-orders-2026-10-06"


IMAGE = "agentbot-sandbox"


AZURITE_NAME = "agentbot-azurite-etl"


AZURITE_KEY = (
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
)


GATEWAY = "http://127.0.0.1:8000"


PIPELINE_PROMPT = """
Build /workspace/etl_orders.py and run it with python3.
Read RAW_READ_SAS and CURATED_WRITE_SAS from /workspace/azure.env.
Download https://etlstore.blob.core.windows.net/raw/orders/2026-10-06.csv with the read SAS.
Keep rows whose status is paid and whose amount is a decimal.
Upload the kept rows to curated/orders/2026-10-06.csv with header order_id,customer_id,amount,currency.
Upload curated/orders/2026-10-06.summary.json with source, rows_in, rows_out, and output.
Do not print either SAS, and do not put a SAS on a command line.
""".strip()


ETL_SCRIPT = """\
import json
import sys
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path

ENV_PATH = Path("/workspace/azure.env")
DATE = "2026-10-06"


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def transform(text: str) -> tuple[list[str], int]:
    lines = [line for line in text.splitlines() if line.strip()]
    rows = lines[1:]
    kept: list[str] = []
    for row in rows:
        parts = row.split(",")
        if len(parts) != 5:
            continue
        order_id, customer_id, amount, currency, status = parts
        if status != "paid":
            continue
        try:
            Decimal(amount)
        except InvalidOperation:
            continue
        kept.append(",".join((order_id, customer_id, amount, currency)) + chr(10))
    return kept, len(rows)


def http_get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def http_put(url: str, body: bytes, content_type: str) -> None:
    request = urllib.request.Request(
        url,
        data=body,
        method="PUT",
        headers={
            "x-ms-blob-type": "BlockBlob",
            "x-ms-version": "2023-11-03",
            "Content-Type": content_type,
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        response.read()


def main() -> int:
    env = load_env(ENV_PATH)
    endpoint = env.get("BLOB_ENDPOINT", "https://etlstore.blob.core.windows.net").rstrip("/")
    source = f"raw/orders/{DATE}.csv"
    output = f"curated/orders/{DATE}.csv"
    summary_path = f"curated/orders/{DATE}.summary.json"
    try:
        raw = http_get(f"{endpoint}/{source}?{env['RAW_READ_SAS']}")
    except urllib.error.HTTPError as exc:
        print(f"HTTP Error {exc.code}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"download failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    kept, rows_in = transform(raw.decode("utf-8"))
    body = "order_id,customer_id,amount,currency" + chr(10) + "".join(kept)
    summary = json.dumps(
        {"source": source, "rows_in": rows_in, "rows_out": len(kept), "output": output},
        separators=(",", ":"),
    )
    try:
        http_put(f"{endpoint}/{output}?{env['CURATED_WRITE_SAS']}", body.encode("utf-8"), "text/csv")
        http_put(
            f"{endpoint}/{summary_path}?{env['CURATED_WRITE_SAS']}",
            summary.encode("utf-8"),
            "application/json",
        )
    except urllib.error.HTTPError as exc:
        print(f"HTTP Error {exc.code}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"upload failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
