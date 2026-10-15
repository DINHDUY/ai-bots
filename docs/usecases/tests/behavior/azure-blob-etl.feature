# Run from the repo root with: behave
# Operator setup through the control UI: docs/usecases/azure-blob-etl-playbook.md
Feature: Curate a daily orders file in Azure Blob Storage
  In order to publish a cleaned orders file without giving the agent a standing cloud credential
  As a data engineer
  I want an agentbot session to extract one CSV from Azure Blob Storage, transform it in the sandbox, and load the result back to Blob Storage

  The sandbox image has Python 3 and bash. It does not include the Azure SDK or the Azure CLI.
  The pipeline is a script under /workspace that calls the Blob REST API with a user-supplied SAS.
  Writing a file and running bash each pause until the engineer approves them.
  Bash is limited to 30 seconds, so this use case covers one daily file, not a multi-hour batch.
  The SAS is written to a workspace file. It must not appear in a bash command, because that command is shown in the approval detail.

  Background:
    Given the gateway health check returns status "ok"
    And the sandbox image "agentbot-sandbox" is present
    And storage account "etlstore" exposes these containers:
      | container | SAS the engineer holds |
      | raw       | read                   |
      | curated   | create and write       |
    And blob "raw/orders/2026-10-06.csv" contains:
      """
      order_id,customer_id,amount,currency,status
      1001,c-9,12.50,USD,paid
      1002,c-4,8.00,USD,cancelled
      1003,c-9,3.25,USD,paid
      """
    And the engineer is connected to "ws://127.0.0.1:8000/ws"

  Rule: An approved session writes the script, runs it, and publishes the curated blobs

    Scenario Outline: Publish the curated orders file for one day
      When the engineer starts session "etl-orders-2026-10-06" on framework "<framework>" with this prompt:
        """
        Build /workspace/etl_orders.py and run it with python3.
        Read RAW_READ_SAS and CURATED_WRITE_SAS from /workspace/azure.env.
        Download https://etlstore.blob.core.windows.net/raw/orders/2026-10-06.csv with the read SAS.
        Keep rows whose status is paid and whose amount is a decimal.
        Upload the kept rows to curated/orders/2026-10-06.csv with header order_id,customer_id,amount,currency.
        Upload curated/orders/2026-10-06.summary.json with source, rows_in, rows_out, and output.
        Do not print either SAS, and do not put a SAS on a command line.
        """
      Then the gateway emits event "session" for "etl-orders-2026-10-06"
      And the gateway asks for approval to write "/workspace/azure.env"
      When the engineer approves that request
      Then the gateway emits event "artifact_written" for "/workspace/azure.env"
      And the gateway asks for approval to write "/workspace/etl_orders.py"
      When the engineer approves that request
      Then the gateway emits event "artifact_written" for "/workspace/etl_orders.py"
      And the gateway asks for approval to run this bash command:
        """
        python3 /workspace/etl_orders.py
        """
      When the engineer approves that request
      Then the gateway emits a "TOOL_CALL" log for that command
      And blob "curated/orders/2026-10-06.csv" contains:
        """
        order_id,customer_id,amount,currency
        1001,c-9,12.50,USD
        1003,c-9,3.25,USD
        """
      And blob "curated/orders/2026-10-06.summary.json" contains:
        """
        {"source":"raw/orders/2026-10-06.csv","rows_in":3,"rows_out":2,"output":"curated/orders/2026-10-06.csv"}
        """
      And neither SAS value appears in any log frame
      And the gateway emits event "done" for "etl-orders-2026-10-06"

      Examples:
        | framework |
        | microsoft |
        | anthropic |

  Rule: The engineer can stop a command that would expose the SAS

    Scenario: Deny a bash command that includes the SAS
      Given session "etl-orders-2026-10-06" is already running on framework "microsoft"
      And the gateway asks for approval to run a bash command whose text contains "RAW_READ_SAS"
      When the engineer denies that request
      Then the tool result is "User denied this action."
      And blob "curated/orders/2026-10-06.csv" is absent
      And blob "curated/orders/2026-10-06.summary.json" is absent
      And the gateway emits event "done" for "etl-orders-2026-10-06"

  Rule: A failed extract does not publish curated data

    Scenario: Missing source blob leaves the curated container unchanged
      Given blob "raw/orders/2026-10-06.csv" does not exist
      And the curated container has no "orders/2026-10-06.csv" blob
      When the engineer runs the approved pipeline for session "etl-orders-2026-10-06"
      Then the script receives HTTP 404 from the Blob REST API
      And the gateway emits a "TOOL_CALL" log that includes "exit" and "404"
      And blob "curated/orders/2026-10-06.csv" is absent
      And blob "curated/orders/2026-10-06.summary.json" is absent
      And the gateway emits event "done" for "etl-orders-2026-10-06"

    Scenario: A download that exceeds the bash limit does not publish a partial file
      Given blob "raw/orders/2026-10-06.csv" cannot be downloaded within 30 seconds
      When the engineer approves "python3 /workspace/etl_orders.py"
      Then the command times out after 30 seconds without uploading a partial file
      And blob "curated/orders/2026-10-06.csv" is absent
      And the gateway emits event "done" for "etl-orders-2026-10-06"

  Rule: The same session can rerun, and closing it drops the SAS file

    Scenario: A follow-up turn reuses the workspace and loads the next day
      Given session "etl-orders-2026-10-06" has already published the 2026-10-06 curated blobs
      And "/workspace/etl_orders.py" and "/workspace/azure.env" are still in that session's container
      And blob "raw/orders/2026-10-07.csv" contains one paid row and one cancelled row
      When the engineer starts another turn on session "etl-orders-2026-10-06" with this prompt:
        """
        Rerun /workspace/etl_orders.py for raw/orders/2026-10-07.csv.
        Write curated/orders/2026-10-07.csv and curated/orders/2026-10-07.summary.json.
        """
      Then the gateway does not create a second container for "etl-orders-2026-10-06"
      When the engineer approves the file write and the bash command
      Then blob "curated/orders/2026-10-07.summary.json" reports rows_in 2 and rows_out 1
      And blob "curated/orders/2026-10-06.csv" is unchanged

    Scenario: Closing the session removes the workspace copy of the SAS
      Given session "etl-orders-2026-10-06" has "/workspace/azure.env" in its container
      When the engineer sends action "close"
      Then the gateway emits event "closed" for "etl-orders-2026-10-06"
      And that session's container is gone
      When the engineer starts a new turn on session "etl-orders-2026-10-06"
      Then the new container's workspace has no "/workspace/azure.env"
      And the new container's workspace has no "/workspace/etl_orders.py"
