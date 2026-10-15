"""Standalone daily orders ETL demo; not installed or registered by Agent Control.

No SDK or credentials are bundled. azure.env supplies BLOB_ENDPOINT (account
service root), RAW_READ_SAS and CURATED_WRITE_SAS. Network failures are bounded
and never retried: a PUT may already have succeeded when its response is lost.
"""

import argparse
import csv
import io
import json
import re
import sys
import time
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BYTES = 4 * 1024 * 1024
FIELDS = ["order_id", "customer_id", "amount", "currency"]


class ETLError(ValueError):
    """A diagnostic that is safe to show without leaking URLs or SAS values."""


def validate_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ETLError("Use one date in YYYY-MM-DD format.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ETLError("The requested date is invalid.") from None
    return value


def read_config(path):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            text = handle.read(16385)
    except OSError:
        raise ETLError(
            "Provide /workspace/azure.env with the endpoint and both SAS credentials."
        ) from None
    if len(text) > 16384:
        raise ETLError("azure.env exceeds 16 KiB.")
    config = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.removeprefix("export ").partition("=")
        if not separator:
            raise ETLError("Use KEY=value lines in azure.env.")
        value = value.strip()
        if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
            value = value[1:-1]
        config[key.strip()] = value
    return config


def account_endpoint(value):
    """Accept Azure service roots and Azurite's /account service root only."""
    try:
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.netloc.endswith(":")
        ):
            raise ValueError
        _ = parsed.port  # Also validate a supplied port's range and syntax.
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError
        segments = [part for part in parsed.path.split("/") if part]
        azure_host = parsed.hostname.endswith(
            (
                ".blob.core.windows.net",
                ".blob.core.usgovcloudapi.net",
                ".blob.core.chinacloudapi.cn",
            )
        )
        if (azure_host and (segments or parsed.scheme != "https")) or len(segments) > 1:
            raise ValueError
        if segments and not re.fullmatch(r"[a-z0-9]{3,24}", segments[0]):
            raise ValueError
        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                "/" + segments[0] if segments else "",
                "",
                "",
            )
        )
    except ValueError:
        raise ETLError(
            "BLOB_ENDPOINT must be an account service root, without container, blob path, or SAS query. Use https://ACCOUNT.blob.core.windows.net or http://HOST:10000/ACCOUNT."
        ) from None


def validate_sas(value, name, now):
    token = value.strip().removeprefix("?")
    if not token or any(c in token for c in "\r\n#") or "://" in token:
        raise ETLError(f"Provide {name} as a SAS query string in azure.env.")
    fields = parse_qs(token)
    if not fields.get("sig") or len(fields.get("se", [])) != 1:
        raise ETLError(f"{name} must include a signature and explicit expiry (se).")
    for key in ("se", "st"):
        if key not in fields:
            continue
        try:
            stamp = datetime.fromisoformat(fields[key][0].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError
        except ValueError:
            raise ETLError(f"{name} has an invalid {key} timestamp.") from None
        if key == "se" and stamp <= now:
            raise ETLError(
                f"{name} has expired. Supply a fresh SAS in azure.env; no uploads attempted."
            )
        if key == "st" and stamp > now:
            raise ETLError(f"{name} is not yet valid. Check its start time.")
    permissions = fields.get("sp", [""])[0]
    if (name == "RAW_READ_SAS" and "r" not in permissions) or (
        name == "CURATED_WRITE_SAS" and "w" not in permissions
    ):
        raise ETLError(
            f"{name} lacks the required {'read' if name == 'RAW_READ_SAS' else 'write'} permission."
        )
    return token


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not send a scoped SAS to another endpoint, even on a redirect.
        return None


def request_blob(endpoint, path, sas, *, payload=None, content_type=None, deadline=None):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ETLError("ETL deadline exceeded; inspect destination blobs before retrying.")
    url = f"{endpoint}/{quote(path, safe='/')}?{sas}"
    headers = {"x-ms-version": "2021-12-02"}
    if payload is not None:
        headers.update({"x-ms-blob-type": "BlockBlob", "Content-Type": content_type})
    request = Request(
        url, data=payload, headers=headers, method="GET" if payload is None else "PUT"
    )
    try:
        with build_opener(NoRedirects()).open(request, timeout=min(8, remaining)) as response:
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise ETLError(
                    "Source exceeds the 4 MiB daily-file limit; no uploads attempted."
                    if payload is None
                    else "Upload response exceeds 4 MiB; inspect destination blobs before retrying."
                )
            return body
    except HTTPError as exc:
        code = exc.code
        exc.close()
        hint = (
            "Check BLOB_ENDPOINT and the requested source date."
            if code == 404
            else "Check the configured endpoint and SAS permissions."
        )
        raise ETLError(
            f"Blob {'download' if payload is None else 'upload'} HTTP {code}. {hint} No automatic retry."
        ) from None
    except ETLError:
        raise
    except (URLError, OSError, TimeoutError, ValueError):
        raise ETLError(
            "Blob request failed or timed out. Inspect destination blobs before retrying; an upload may have completed."
        ) from None


def transform(raw):
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        if not set(FIELDS + ["status"]).issubset(reader.fieldnames or []):
            raise ETLError("Source CSV is missing required order columns; no uploads attempted.")
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        rows_in = rows_out = 0
        for row in reader:
            rows_in += 1
            if None in row or any(row.get(key) is None for key in FIELDS + ["status"]):
                raise ETLError("Source CSV has malformed rows; no uploads attempted.")
            if row["status"] != "paid":
                continue
            try:
                amount = Decimal(row["amount"])
                if not amount.is_finite():
                    continue
            except InvalidOperation:
                continue
            writer.writerow({key: row[key] for key in FIELDS})
            rows_out += 1
        return output.getvalue().encode(), rows_in, rows_out
    except (UnicodeError, csv.Error):
        raise ETLError("Source is not a valid UTF-8 CSV; no uploads attempted.") from None


def run(day, *, env_path="/workspace/azure.env", endpoint="", request=request_blob):
    day = validate_date(day)
    config = read_config(env_path)
    root = account_endpoint(endpoint or config.get("BLOB_ENDPOINT", ""))
    now = datetime.now(UTC)
    read_sas = validate_sas(config.get("RAW_READ_SAS", ""), "RAW_READ_SAS", now)
    write_sas = validate_sas(config.get("CURATED_WRITE_SAS", ""), "CURATED_WRITE_SAS", now)
    source, output = f"raw/orders/{day}.csv", f"curated/orders/{day}.csv"
    deadline = time.monotonic() + 24
    raw = request(root, source, read_sas, deadline=deadline)
    cleaned, rows_in, rows_out = transform(raw)
    summary = {
        "source": source,
        "rows_in": rows_in,
        "rows_out": rows_out,
        "output": output,
    }
    request(
        root,
        output,
        write_sas,
        payload=cleaned,
        content_type="text/csv",
        deadline=deadline,
    )
    try:
        request(
            root,
            f"curated/orders/{day}.summary.json",
            write_sas,
            payload=json.dumps(summary).encode(),
            content_type="application/json",
            deadline=deadline,
        )
    except ETLError as exc:
        raise ETLError(f"CSV uploaded, but summary upload failed. {exc}") from None
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("date")
    parser.add_argument("--endpoint", default="")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.date, endpoint=args.endpoint)))
    except ETLError as exc:
        print(f"ETL error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
