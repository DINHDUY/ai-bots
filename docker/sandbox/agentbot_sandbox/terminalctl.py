import json
import socket
import sys

with socket.socket(socket.AF_UNIX) as client:
    client.settimeout(5)
    client.connect("/tmp/agentbot-terminal.sock")
    client.sendall(sys.argv[1].encode() + b"\n")
    data = bytearray()
    while b"\n" not in data and len(data) < 32768:
        data.extend(client.recv(32768))
    result = json.loads(data)
    print(json.dumps(result))
    sys.exit(0 if result.get("ok") else 1)
