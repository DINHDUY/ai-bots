# Azure Blob ETL setup playbook

Operator path for [azure-blob-etl.feature](tests/behavior/azure-blob-etl.feature) through the agent-control UI at `http://127.0.0.1:5174`. The Behave feature drives the raw gateway with `framework` and `session_id`. Here you sign in, create a bot, and approve the same file writes and bash command.

This is an optional demo, not a backend tool or frontend preset. Use the generic bot editor to enter your own instructions and optionally save a **Default Prompt**. The standalone [blob_orders.py](blob_orders.py) sample uses only the Python standard library and is not imported by either application.

To run the sample manually after preparing `/workspace/azure.env`, copy it to the demo workspace and invoke `python3 /workspace/blob_orders.py <DATE>`. Review the script and authorize file/network operations through the ordinary controls when an agent performs them.

## 1. Bring up the stack

From the repo root, with `AGENTBOT_SECRET` set:

```bash
docker build -f docker/sandbox/Dockerfile -t agentbot-sandbox .
agentbot-control
```

In another terminal:

```bash
cd packages/agent-control-frontend
npm install
npm run dev
```

`agentbot-control` listens on `http://127.0.0.1:8000`. The dev server is `http://127.0.0.1:5174`. `CORS_ORIGINS` must include that origin. Run `agentbot-control`, not `agentbot`. Both bind port 8000.

## 2. Blob storage the sandbox can reach

For a local run, start Azurite the same way the Behave steps do. The account key below is Microsoft's public Azurite development key. It only unlocks the emulator.

```bash
docker run -d --name agentbot-azurite-etl -p 10000:10000 -e AZURITE_ACCOUNTS=etlstore:Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw== mcr.microsoft.com/azure-storage/azurite azurite-blob --blobHost 0.0.0.0 --blobPort 10000 --skipApiVersionCheck
```

The sandbox reaches Azurite at `http://host.docker.internal:10000/etlstore`. That URL is `BLOB_ENDPOINT`. From the host, the same service is `http://127.0.0.1:10000/etlstore`.

Create container `raw` (read SAS) and container `curated` (create and write SAS), upload the sample file, and print the two tokens. Run this with the repo virtualenv, which has `azure-storage-blob`:

```python
from datetime import datetime, timedelta, timezone

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient, ContainerSasPermissions, generate_container_sas

account = "etlstore"
key = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
service = BlobServiceClient(account_url=f"http://127.0.0.1:10000/{account}", credential=key)
for name in ("raw", "curated"):
    try:
        service.create_container(name)
    except ResourceExistsError:
        pass

sample = """order_id,customer_id,amount,currency,status
1001,c-9,12.50,USD,paid
1002,c-4,8.00,USD,cancelled
1003,c-9,3.25,USD,paid
"""
service.get_blob_client("raw", "orders/2026-10-06.csv").upload_blob(sample, overwrite=True)


def sas(container: str, *, read: bool, create: bool, write: bool) -> str:
    return generate_container_sas(
        account,
        container,
        account_key=key,
        permission=ContainerSasPermissions(read=read, create=create, write=write),
        start=datetime.now(timezone.utc) - timedelta(minutes=5),
        expiry=datetime.now(timezone.utc) + timedelta(hours=4),
        protocol="https,http",
    )


print("RAW_READ_SAS=" + sas("raw", read=True, create=False, write=False))
print("CURATED_WRITE_SAS=" + sas("curated", read=False, create=True, write=True))
print("BLOB_ENDPOINT=http://host.docker.internal:10000/etlstore")
```

Hold the two SAS tokens outside the bot. For a real storage account, use that account's endpoint as `BLOB_ENDPOINT` and SAS tokens you issued yourself. The sandbox still has no Azure SDK and no Azure CLI.

## 3. Account and key

Open `http://127.0.0.1:5174`. **Create account** or **Sign in**, then **API keys**.

- An `anthropic` bot needs an Anthropic key.
- A `microsoft` bot needs an OpenAI key or an Azure Foundry key.

## 4. New bot

**New bot**: enter a demo name and the sample instructions below, select the framework, API key and model, then **Add bot**. Select the general file and terminal tools explicitly if the agent will create and execute the script.

For an existing demo bot, edit **Instructions** in Bot settings and select **Save**.

Standing instructions:

```text
The sandbox image has Python 3 and bash. It does not include the Azure SDK or the Azure CLI.
Write a script under /workspace that calls the Blob REST API with urllib and a user-supplied SAS.
Write SAS values only to /workspace/azure.env. Do not print either SAS, and do not put a SAS on a command line.
Bash is limited to 30 seconds, so handle one daily file per run.
Read BLOB_ENDPOINT from /workspace/azure.env when the account is not the public blob host.
```

## 5. First turn

Paste the sample below into the message composer yourself, or save it as an optional **Default Prompt**. Replace `<DATE>`, `<RAW_READ_SAS>`, `<CURATED_WRITE_SAS>`, and `<BLOB_ENDPOINT>` before sending.

The SAS values belong in this message so the model can write `/workspace/azure.env`. They must not appear in a bash command, because that command is the approval detail. The transcript keeps the message until you delete the bot.

```text
Build /workspace/etl_orders.py and run it with python3.
Write /workspace/azure.env with these lines and do not print them:
RAW_READ_SAS=<RAW_READ_SAS>
CURATED_WRITE_SAS=<CURATED_WRITE_SAS>
BLOB_ENDPOINT=<BLOB_ENDPOINT>
Read RAW_READ_SAS and CURATED_WRITE_SAS from /workspace/azure.env.
Download <BLOB_ENDPOINT>/raw/orders/<DATE>.csv with the read SAS.
Keep rows whose status is paid and whose amount is a decimal.
Upload the kept rows to curated/orders/<DATE>.csv with header order_id,customer_id,amount,currency.
Upload curated/orders/<DATE>.summary.json with source, rows_in, rows_out, and output.
Do not print either SAS, and do not put a SAS on a command line.
```

For the sample file, `<DATE>` is `2026-10-06`.

## 6. Approvals

Answer the cards in this order:

1. **Allow once** for the write of `/workspace/azure.env`.
2. **Allow once** for the write of `/workspace/etl_orders.py`.
3. **Allow once** for bash `python3 /workspace/etl_orders.py`.

**Deny** any bash detail that contains a SAS token or `RAW_READ_SAS`. A denied command returns "User denied this action." and must not publish the curated blobs.

Confirm `curated/orders/2026-10-06.csv` and `curated/orders/2026-10-06.summary.json` in storage. The Terminal tab shows the bash command. The curated CSV keeps the paid rows and drops `status`:

```text
order_id,customer_id,amount,currency
1001,c-9,12.50,USD
1003,c-9,3.25,USD
```

The summary is `{"source":"raw/orders/2026-10-06.csv","rows_in":3,"rows_out":2,"output":"curated/orders/2026-10-06.csv"}`.

Leave the sandbox open if you want the next-day turn to reuse `/workspace/etl_orders.py` and `/workspace/azure.env`.

## 7. Next day

Upload `raw/orders/2026-10-07.csv` with one paid row and one cancelled row. On the same bot, send this follow-up. Replace `<DATE>` with `2026-10-07`.

```text
Rerun /workspace/etl_orders.py for raw/orders/<DATE>.csv.
Write curated/orders/<DATE>.csv and curated/orders/<DATE>.summary.json.
Keep /workspace/azure.env as it is. Do not print either SAS, and do not put a SAS on a command line.
```

Approve the script rewrite and `python3 /workspace/etl_orders.py`. The summary reports `rows_in` 2 and `rows_out` 1. `curated/orders/2026-10-06.csv` stays unchanged. The gateway does not create a second container for this bot.

## 8. Close the sandbox

**Close sandbox** removes the container, including `/workspace/azure.env` and `/workspace/etl_orders.py`. The bot and its transcript remain. The next turn starts a new container with an empty workspace, so send the first prompt again, including the SAS lines, before that run.

## 9. Failure checks

- Delete `raw/orders/2026-10-06.csv` and run the approved pipeline. The script gets HTTP 404 from the Blob REST API. The Terminal log includes the exit and `404`. Neither curated blob is published.
- If the download cannot finish within 30 seconds, the tool result contains `bash error: command timed out after 30s.` and `curated/orders/2026-10-06.csv` is absent.
