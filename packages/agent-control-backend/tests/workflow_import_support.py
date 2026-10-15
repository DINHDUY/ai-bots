"""Synthetic definitions and HTTP import helpers."""

from control_support import _key


def draft(client, *, count=3, framework="microsoft"):
    key = _key(client, "anthropic" if framework == "anthropic" else "openai")["id"]
    return {
        "workspace_name": "Imported workflow",
        "defaults": {
            "framework": framework,
            "credential_id": key,
            "model": "claude-sonnet-5" if framework == "anthropic" else "gpt-4.1",
        },
        "files": [
            {
                "file_id": f"file{index}",
                "filename": f"agent{index}.agent.md",
                "content": f"---\r\nname: Agent {index}\r\ndescription: Role {index}\r\ntools: [foreign]\r\n---\r\n\r\n# Agent {index}\r\n  Instructions  \r\n",
            }
            for index in range(count)
        ],
    }


def command(client, source, request_id="workflow_import_01"):
    response = client.post("/api/workflow-imports/preview", json=source)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["valid"], preview
    return {**source, "request_id": request_id, "preview_digest": preview["preview_digest"]}


def imported(client, source, request_id="workflow_import_01"):
    response = client.post("/api/workflow-imports", json=command(client, source, request_id))
    assert response.status_code == 201, response.text
    return response.json()
