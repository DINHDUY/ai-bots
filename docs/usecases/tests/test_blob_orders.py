from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError
from urllib.parse import urlencode

import pytest

from docs.usecases import blob_orders as etl


def config(tmp_path, *, expired=False):
    expiry = datetime.now(UTC) + timedelta(days=-1 if expired else 1)
    token = urlencode(
        {"sig": "private-signature", "se": expiry.isoformat(), "sp": "rcw"}
    )
    path = tmp_path / "azure.env"
    path.write_text(
        f"BLOB_ENDPOINT=http://emulator:10000/etlstore\nRAW_READ_SAS='{token}'\nCURATED_WRITE_SAS={token}\n",
        encoding="utf-8",
    )
    return path


def test_daily_orders_transform_and_endpoint_used_once(tmp_path):
    calls = []
    source = b"order_id,customer_id,amount,currency,status\n1,c1,12.50,USD,paid\n2,c2,8.00,USD,cancelled\n3,c3,NaN,USD,paid\n4,c4,bad,USD,paid\n5,c5,3.25,USD,paid\n"

    def request(endpoint, path, sas, **kwargs):
        calls.append((endpoint, path, kwargs))
        return source if "payload" not in kwargs else b""

    summary = etl.run("2026-10-06", env_path=config(tmp_path), request=request)
    assert summary == {
        "source": "raw/orders/2026-10-06.csv",
        "rows_in": 5,
        "rows_out": 2,
        "output": "curated/orders/2026-10-06.csv",
    }
    assert len(calls) == 3
    assert all(root == "http://emulator:10000/etlstore" for root, _, _ in calls)
    assert (
        calls[1][2]["payload"]
        == b"order_id,customer_id,amount,currency\n1,c1,12.50,USD\n5,c5,3.25,USD\n"
    )
    assert calls[2][1] == "curated/orders/2026-10-06.summary.json"


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://etlstore.blob.core.windows.net/raw",
        "http://emulator:10000/etlstore/raw",
        "https://etlstore.blob.core.windows.net/?sig=secret",
        "file:///tmp/a",
        "https://user:secret@host/",
        "http://host:/",
    ],
)
def test_container_urls_and_credentials_are_rejected(endpoint):
    with pytest.raises(etl.ETLError, match="account service root") as error:
        etl.account_endpoint(endpoint)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("value", ["2026-02-30", "2026-1-1", "2026-10-06; echo secret"])
def test_invalid_dates(value):
    with pytest.raises(etl.ETLError):
        etl.validate_date(value)


def test_expired_or_missing_credentials_never_touch_network(tmp_path):
    def unexpected(*args, **kwargs):
        pytest.fail("No requests with invalid credentials")

    with pytest.raises(etl.ETLError, match="expired"):
        etl.run(
            "2026-10-06", env_path=config(tmp_path, expired=True), request=unexpected
        )
    with pytest.raises(etl.ETLError, match="Provide /workspace/azure.env"):
        etl.run("2026-10-06", env_path=tmp_path / "missing", request=unexpected)


def test_bad_source_never_uploads_and_partial_upload_reports_status(tmp_path):
    path = config(tmp_path)
    calls = []

    def missing(*args, **kwargs):
        calls.append(args)
        raise etl.ETLError("Blob download HTTP 404")

    with pytest.raises(etl.ETLError, match="404"):
        etl.run("2026-10-06", env_path=path, request=missing)
    assert len(calls) == 1
    calls.clear()

    def partial(*args, **kwargs):
        calls.append(args)
        if len(calls) == 3:
            raise etl.ETLError("Blob upload HTTP 403")
        return b"order_id,customer_id,amount,currency,status\n1,c,1,USD,paid\n"

    with pytest.raises(etl.ETLError, match="CSV uploaded, but summary upload failed"):
        etl.run("2026-10-06", env_path=path, request=partial)
    assert len(calls) == 3  # No ambiguous retry of either PUT.


def test_http_error_redacts_url_sas_and_server_reason(monkeypatch):
    import time

    class Opener:
        def open(self, request, **kwargs):
            assert (
                request.full_url
                == "http://emulator:10000/etlstore/raw/orders.csv?sig=secret"
            )
            raise HTTPError(request.full_url, 404, "server echoed secret", {}, None)

    monkeypatch.setattr(etl, "build_opener", lambda *args: Opener())
    with pytest.raises(etl.ETLError, match="HTTP 404") as error:
        etl.request_blob(
            "http://emulator:10000/etlstore",
            "raw/orders.csv",
            "sig=secret",
            deadline=time.monotonic() + 10,
        )
    assert "secret" not in str(error.value)


def test_rejects_non_csv_and_oversized_local_config(tmp_path):
    for data in (
        b"wrong,columns\n1,2",
        b"order_id,customer_id,amount,currency,status\n1,2",
    ):
        with pytest.raises(etl.ETLError):
            etl.transform(data)
    path = config(tmp_path)
    path.write_text("x" * 20000)
    with pytest.raises(etl.ETLError, match="16 KiB"):
        etl.read_config(path)


def test_download_limit_reports_bounded_error_without_upload(monkeypatch):
    import io
    import time

    class Opener:
        def open(self, request, **kwargs):
            assert request.method == "GET"
            return io.BytesIO(b"x" * (etl.MAX_BYTES + 1))

    monkeypatch.setattr(etl, "build_opener", lambda *args: Opener())
    with pytest.raises(etl.ETLError, match="4 MiB daily-file limit"):
        etl.request_blob(
            "http://emulator:10000/account",
            "raw/orders.csv",
            "sig=secret",
            deadline=time.monotonic() + 10,
        )
