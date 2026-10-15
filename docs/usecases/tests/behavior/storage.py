from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import (
    BlobServiceClient,
    ContainerSasPermissions,
    generate_container_sas,
)


class BlobStore:
    def __init__(self, account: str, key: str, host_url: str) -> None:
        self.account = account
        self.key = key
        self.client = BlobServiceClient(account_url=host_url, credential=key)

    def ensure_container(self, name: str) -> None:
        try:
            self.client.create_container(name)
        except ResourceExistsError:
            return

    def sas(self, container: str, *, read: bool, create: bool, write: bool) -> str:
        return generate_container_sas(
            self.account,
            container,
            account_key=self.key,
            permission=ContainerSasPermissions(read=read, create=create, write=write),
            start=datetime.now(UTC) - timedelta(minutes=5),
            expiry=datetime.now(UTC) + timedelta(hours=4),
            protocol="https,http",
        )

    def upload(self, path: str, text: str) -> None:
        container, blob = split_blob(path)
        self.client.get_blob_client(container, blob).upload_blob(
            text.encode("utf-8"), overwrite=True
        )

    def download(self, path: str) -> bytes:
        container, blob = split_blob(path)
        return self.client.get_blob_client(container, blob).download_blob().readall()

    def absent(self, path: str) -> None:
        container, blob = split_blob(path)
        try:
            self.client.get_blob_client(container, blob).get_blob_properties()
        except ResourceNotFoundError:
            return
        raise AssertionError(f"{path} exists")

    def delete(self, path: str) -> None:
        container, blob = split_blob(path)
        try:
            self.client.get_blob_client(container, blob).delete_blob()
        except ResourceNotFoundError:
            return

    def clear(self) -> None:
        for name in ("raw", "curated"):
            try:
                container = self.client.get_container_client(name)
                for blob in container.list_blobs():
                    container.delete_blob(blob.name)
            except ResourceNotFoundError:
                continue


def split_blob(path: str) -> tuple[str, str]:
    container, blob = path.split("/", 1)
    return container, blob


class _HangHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        server: HangProxy = self.server  # type: ignore[assignment]
        if server.delay_token in self.path.split("?", 1)[0]:
            deadline = time.time() + server.delay_seconds
            while time.time() < deadline:
                if server.stopping:
                    return
                time.sleep(0.2)
        self._forward("GET")

    def do_PUT(self) -> None:
        server: HangProxy = self.server  # type: ignore[assignment]
        server.puts += 1
        self._forward("PUT")

    def _forward(self, method: str) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else None
        connection = HTTPConnection("127.0.0.1", 10000, timeout=20)
        try:
            headers = {key: value for key, value in self.headers.items() if key.lower() != "host"}
            connection.request(method, self.path, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() in {"transfer-encoding", "connection", "content-length"}:
                    continue
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        finally:
            connection.close()


class HangProxy(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    delay_token = "raw/orders/2026-10-06.csv"
    delay_seconds = 45.0
    puts = 0
    stopping = False


def start_hang_proxy(delay_seconds: float) -> HangProxy:
    server = HangProxy(("0.0.0.0", 0), _HangHandler)
    server.delay_seconds = delay_seconds
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def stop_hang_proxy(server: HangProxy) -> None:
    server.stopping = True
    server.shutdown()
    server.server_close()
