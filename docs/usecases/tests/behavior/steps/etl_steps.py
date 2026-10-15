"""Step definitions for the Azure Blob ETL use cases."""

from __future__ import annotations

import json
import time

import httpx
from behave import step

from docs.usecases.tests.behavior import support
from docs.usecases.tests.behavior.support import (
    PIPELINE_PROMPT,
    SESSION,
    Engineer,
    assert_no_sas,
    ensure_azurite,
    ensure_blob_host,
    ensure_image,
    session_containers,
    start_hang_proxy,
    wait_until,
    workspace_exists,
)  # noqa: E402


@step('the gateway health check returns status "{status}"')
def health(context, status: str) -> None:
    response = httpx.get("http://127.0.0.1:8000/health", timeout=5)
    assert response.status_code == 200
    assert response.json()["status"] == status


@step('the sandbox image "{image}" is present')
def sandbox_image(context, image: str) -> None:
    ensure_image(context, image)
    context.docker.images.get(image)


@step('storage account "{account}" exposes these containers:')
def storage_account(context, account: str) -> None:
    ensure_azurite(context, account)
    ensure_blob_host(context, support.IMAGE)
    context.plan.endpoint = f"http://{context.blob_host}:10000/{account}"
    for row in context.table:
        name = row["container"]
        access = row["SAS the engineer holds"]
        context.blobs.ensure_container(name)
        if "write" in access:
            context.plan.curated_sas = context.blobs.sas(name, read=False, create=True, write=True)
        elif "read" in access:
            context.plan.raw_sas = context.blobs.sas(name, read=True, create=False, write=False)


@step('blob "{path}" contains:')
def blob_contains(context, path: str) -> None:
    expected = context.text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if context.step_kind.lower() == "given":
        context.blobs.upload(path, expected + "\n")
        return
    actual = (
        context.blobs.download(path)
        .decode("utf-8")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .strip()
    )
    assert actual == expected


@step('the engineer is connected to "{url}"')
def connect(context, url: str) -> None:
    context.engineer = Engineer(url)


@step('the engineer starts session "{session_id}" on framework "{framework}" with this prompt:')
def start_session(context, session_id: str, framework: str) -> None:
    context.session_id = session_id
    context.framework = framework
    context.plan.name = "etl"
    context.engineer.send_start(session_id, framework, context.text.strip())


@step('the gateway emits event "session" for "{session_id}"')
def event_session(context, session_id: str) -> None:
    frame = context.engineer.until(
        lambda item: item.get("event") == "session" and item.get("session_id") == session_id
    )
    assert frame["session_id"] == session_id


@step('the gateway emits event "done" for "{session_id}"')
def event_done(context, session_id: str) -> None:
    frame = context.engineer.until(
        lambda item: item.get("event") == "done" and item.get("session_id") == session_id
    )
    assert frame["event"] == "done"
    if context.check_sas:
        assert_no_sas(context.plan, context.engineer.frames)


@step('the gateway emits event "closed" for "{session_id}"')
def event_closed(context, session_id: str) -> None:
    context.engineer.until(
        lambda item: item.get("event") == "closed" and item.get("session_id") == session_id
    )


@step('the gateway emits event "artifact_written" for "{path}"')
def event_artifact(context, path: str) -> None:
    context.engineer.until(
        lambda item: (
            item.get("event") == "artifact_written"
            and str(item.get("meta", {}).get("path", "")) == path
        )
    )


@step('the gateway asks for approval to write "{path}"')
def ask_write(context, path: str) -> None:
    frame = context.engineer.until(lambda item: item.get("event") == "approval_required")
    detail = str(frame.get("detail", ""))
    assert path in detail
    assert "python3" not in detail
    context.pending = frame


@step("the gateway asks for approval to run this bash command:")
def ask_bash(context) -> None:
    command = context.text.strip()
    context.command = command
    frame = context.engineer.until(lambda item: item.get("event") == "approval_required")
    assert command in str(frame.get("detail", ""))
    context.pending = frame


@step("the engineer approves that request")
def approve(context) -> None:
    context.engineer.decide(context.pending, "approve")


@step("the engineer denies that request")
def deny(context) -> None:
    context.engineer.decide(context.pending, "deny")


@step('the gateway emits a "TOOL_CALL" log for that command')
def tool_call_for_command(context) -> None:
    command = context.command
    context.engineer.until(
        lambda item: (
            item.get("event") == "log"
            and item.get("type") == "TOOL_CALL"
            and command in str(item.get("payload", ""))
        )
    )


@step("neither SAS value appears in any log frame")
def no_sas(context) -> None:
    context.check_sas = True
    assert_no_sas(context.plan, context.engineer.frames)


@step('session "{session_id}" is already running on framework "{framework}"')
def already_running(context, session_id: str, framework: str) -> None:
    context.session_id = session_id
    context.framework = framework
    context.plan.name = "deny"
    context.engineer.send_start(session_id, framework, "Run the orders pipeline.")
    context.engineer.until(
        lambda item: item.get("event") == "session" and item.get("session_id") == session_id
    )


@step('the gateway asks for approval to run a bash command whose text contains "{text}"')
def ask_bash_containing(context, text: str) -> None:
    frame = context.engineer.until(lambda item: item.get("event") == "approval_required")
    assert text in str(frame.get("detail", ""))
    context.pending = frame


@step('the tool result is "{text}"')
def tool_result_is(context, text: str) -> None:
    context.engineer.until(lambda item: item.get("event") == "log" and item.get("payload") == text)


@step('the tool result contains "{text}"')
def tool_result_contains(context, text: str) -> None:
    context.engineer.until(lambda item: text in json.dumps(item))


@step('blob "{path}" is absent')
def blob_absent(context, path: str) -> None:
    context.blobs.absent(path)


@step('blob "{path}" does not exist')
def blob_missing(context, path: str) -> None:
    context.blobs.delete(path)
    context.blobs.absent(path)


@step('the curated container has no "{blob}" blob')
def curated_absent(context, blob: str) -> None:
    context.blobs.delete(f"curated/{blob}")
    context.blobs.absent(f"curated/{blob}")


@step('the engineer runs the approved pipeline for session "{session_id}"')
def run_approved(context, session_id: str) -> None:
    context.session_id = session_id
    context.plan.name = "etl"
    context.engineer.send_start(session_id, context.framework, PIPELINE_PROMPT)
    context.engineer.approve_until_bash_result()


@step("the script receives HTTP 404 from the Blob REST API")
def http_404(context) -> None:
    _wait_for(
        context,
        lambda item: (
            item.get("event") == "log" and "HTTP Error 404" in str(item.get("payload", ""))
        ),
    )


@step('the gateway emits a "TOOL_CALL" log that includes "{first}" and "{second}"')
def tool_call_includes(context, first: str, second: str) -> None:
    _wait_for(
        context,
        lambda item: (
            item.get("event") == "log"
            and item.get("type") == "TOOL_CALL"
            and first in str(item.get("payload", ""))
            and second in str(item.get("payload", ""))
        ),
    )


@step('blob "{path}" cannot be downloaded within {seconds:d} seconds')
def hang_download(context, path: str, seconds: int) -> None:
    assert seconds == 30
    context.hang = start_hang_proxy(delay_seconds=seconds + 20)
    port = context.hang.server_address[1]
    context.plan.endpoint = f"http://{context.blob_host}:{port}/{context.account}"
    context.engineer.timeout = seconds + 45


@step('the engineer approves "{command}"')
def approve_named_command(context, command: str) -> None:
    if not context.engineer.started:
        context.plan.name = "etl"
        context.session_id = SESSION
        context.engineer.send_start(SESSION, context.framework, PIPELINE_PROMPT)
    while True:
        frame = context.engineer.until(lambda item: item.get("event") == "approval_required")
        if command in str(frame.get("detail", "")):
            context.command_started_at = time.monotonic()
            context.engineer.decide(frame, "approve")
            return
        context.engineer.decide(frame, "approve")


@step("the command times out after {seconds:d} seconds without uploading a partial file")
def command_times_out(context, seconds: int) -> None:
    context.engineer.until(
        lambda item: (
            item.get("event") == "log"
            and "bash error: command timed out." in str(item.get("payload", ""))
        )
    )
    elapsed = time.monotonic() - context.command_started_at
    assert seconds - 2 <= elapsed < seconds + 30, elapsed
    assert context.hang.puts == 0, "A timed-out download attempted to upload output"


@step('session "{session_id}" has already published the 2026-10-06 curated blobs')
def already_published(context, session_id: str) -> None:
    context.session_id = session_id
    context.plan.name = "etl"
    context.engineer.send_start(session_id, context.framework, PIPELINE_PROMPT)
    context.engineer.finish_by_approving(session_id)
    containers = session_containers(context, session_id)
    assert len(containers) == 1
    context.container_id = containers[0].id
    context.snapshots["curated/orders/2026-10-06.csv"] = context.blobs.download(
        "curated/orders/2026-10-06.csv"
    )


@step('"{first}" and "{second}" are still in that session\'s container')
def files_remain(context, first: str, second: str) -> None:
    assert workspace_exists(context, context.session_id, first)
    assert workspace_exists(context, context.session_id, second)


@step('blob "{path}" contains one paid row and one cancelled row')
def upload_next_day(context, path: str) -> None:
    context.blobs.upload(
        path,
        "order_id,customer_id,amount,currency,status\n"
        "2001,c-1,5.00,USD,paid\n"
        "2002,c-2,1.00,USD,cancelled\n",
    )


@step('the engineer starts another turn on session "{session_id}" with this prompt:')
def start_another(context, session_id: str) -> None:
    context.session_id = session_id
    context.plan.name = "rerun"
    context.engineer.send_start(session_id, context.framework, context.text.strip())


@step('the gateway does not create a second container for "{session_id}"')
def no_second_container(context, session_id: str) -> None:
    frame = context.engineer.until(lambda item: item.get("event") == "approval_required")
    context.pending = frame
    containers = session_containers(context, session_id)
    assert [item.id for item in containers] == [context.container_id]


@step("the engineer approves the file write and the bash command")
def approve_write_and_bash(context) -> None:
    frame = context.pending
    assert "/workspace/etl_orders.py" in str(frame.get("detail", ""))
    context.engineer.decide(frame, "approve")
    bash = context.engineer.until(lambda item: item.get("event") == "approval_required")
    assert "python3 /workspace/etl_orders.py" in str(bash.get("detail", ""))
    context.engineer.decide(bash, "approve")
    context.engineer.until(
        lambda item: (
            item.get("event") == "log"
            and item.get("type") == "TOOL_CALL"
            and "python3 /workspace/etl_orders.py" in str(item.get("payload", ""))
        )
    )


@step('blob "{path}" reports rows_in {rows_in:d} and rows_out {rows_out:d}')
def summary_counts(context, path: str, rows_in: int, rows_out: int) -> None:
    payload = json.loads(context.blobs.download(path).decode("utf-8"))
    assert payload["rows_in"] == rows_in
    assert payload["rows_out"] == rows_out


@step('blob "{path}" is unchanged')
def blob_unchanged(context, path: str) -> None:
    assert context.blobs.download(path) == context.snapshots[path]


@step('session "{session_id}" has "{path}" in its container')
def seed_workspace(context, session_id: str, path: str) -> None:
    context.session_id = session_id
    context.plan.name = "seed"
    context.engineer.send_start(session_id, context.framework, "Write the orders workspace files.")
    context.engineer.finish_by_approving(session_id)
    assert workspace_exists(context, session_id, path)
    assert workspace_exists(context, session_id, "/workspace/etl_orders.py")


@step('the engineer sends action "{action}"')
def send_action(context, action: str) -> None:
    context.engineer.ws.send(json.dumps({"action": action}))


@step("that session's container is gone")
def container_gone(context) -> None:
    def gone() -> bool:
        return session_containers(context, context.session_id) == []

    wait_until(gone, timeout=20)


@step('the engineer starts a new turn on session "{session_id}"')
def start_new_turn(context, session_id: str) -> None:
    context.session_id = session_id
    context.plan.name = "list"
    context.engineer.send_start(session_id, context.framework, "List the files in the workspace.")
    context.engineer.until(lambda item: item.get("event") == "approval_required")


@step('the new container\'s workspace has no "{path}"')
def workspace_missing(context, path: str) -> None:
    deadline = time.time() + 15
    while time.time() < deadline:
        if session_containers(context, context.session_id):
            break
        time.sleep(0.2)
    assert not workspace_exists(context, context.session_id, path)


def _wait_for(context, predicate) -> None:
    for frame in context.engineer.frames:
        if predicate(frame):
            return
    context.engineer.until(predicate)
