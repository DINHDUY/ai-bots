#!/bin/bash
# Invoked as root by approved ML creation script / VM customData, or manually.
set -eu
umask 077
apt-get update -qq
apt-get install -y --no-install-recommends docker.io python3-venv python3-pip iptables ca-certificates curl unzip
systemctl enable --now docker
install -d -m 700 /var/lib/agentbot-host /opt/agentbot-host /etc/agentbot
python3 - <<'PY'
import hashlib, json, pathlib, urllib.request, zipfile
settings = json.loads(pathlib.Path('/etc/agentbot/bootstrap.json').read_text())
archive = pathlib.Path('/var/lib/agentbot-host/package.zip')
with urllib.request.urlopen(settings['package_url'], timeout=60) as source, archive.open('wb') as target:
    while block := source.read(1024 * 1024):
        target.write(block)
if hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest() != settings['package_sha256']:
    raise SystemExit('Host package checksum mismatch')
root = pathlib.Path('/opt/agentbot-host/wheels')
root.mkdir(exist_ok=True)
with zipfile.ZipFile(archive) as bundle:
    for item in bundle.infolist():
        if pathlib.PurePosixPath(item.filename).name != item.filename or not item.filename.endswith('.whl') or item.file_size > 500 * 1024 * 1024:
            raise SystemExit('Unexpected host package member')
        (root / item.filename).write_bytes(bundle.read(item))
PY
python3 -m venv /opt/agentbot-host/venv
/opt/agentbot-host/venv/bin/pip install --no-index --find-links /opt/agentbot-host/wheels agentbot-computer-agent

# VM workspace lives on its explicitly provisioned data disk, never the temp disk.
python3 - <<'PY'
import json, pathlib, subprocess
settings = json.loads(pathlib.Path('/etc/agentbot/bootstrap.json').read_text())
root = pathlib.Path(settings['workspace_root'])
if settings.get('ownership') == 'managed' and settings['provider'] == 'azure_vm' and settings['storage_policy'] == 'managed_data_disk':
    disk = pathlib.Path('/dev/disk/azure/scsi1/lun0')
    if not disk.exists():
        raise SystemExit('Dedicated data disk LUN 0 is missing')
    root.mkdir(parents=True, exist_ok=True)
    check = subprocess.run(['blkid', '-o', 'value', '-s', 'TYPE', str(disk)], capture_output=True, text=True)
    if not check.stdout.strip():
        subprocess.run(['mkfs.ext4', '-F', str(disk)], check=True)
    elif check.stdout.strip() != 'ext4':
        raise SystemExit('Unexpected data disk filesystem; refusing to format')
    uuid = subprocess.check_output(['blkid', '-o', 'value', '-s', 'UUID', str(disk)], text=True).strip()
    entry = f'UUID={uuid} {root} ext4 defaults,nofail 0 2\n'
    fstab = pathlib.Path('/etc/fstab')
    if entry not in fstab.read_text():
        with fstab.open('a') as stream:
            stream.write(entry)
    subprocess.run(['mount', str(root)], check=True)
else:
    root.mkdir(parents=True, exist_ok=True)
    source = subprocess.check_output(['findmnt', '-n', '-o', 'SOURCE', '--target', str(root)], text=True).strip()
    kind = subprocess.check_output(['findmnt', '-n', '-o', 'FSTYPE', '--target', str(root)], text=True).strip()
    if kind not in {'ext4', 'xfs'} or not source.startswith('/dev/'):
        raise SystemExit('Workspace must be a dedicated directory on a persistent local disk')
PY

cat > /usr/local/sbin/agentbot-network <<'SH'
#!/bin/bash
set -eu
if [ "${1:-}" = install ]; then
    docker network inspect agentbot-workloads >/dev/null 2>&1 || docker network create --driver bridge --opt com.docker.network.bridge.name=br-agentbot --opt com.docker.network.bridge.enable_icc=false agentbot-workloads >/dev/null
fi
for dest in 169.254.0.0/16 168.63.129.16/32 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16; do
    if ! iptables -C DOCKER-USER -i br-agentbot -d "$dest" -j REJECT 2>/dev/null; then
        [ "${1:-}" = install ] || exit 1
        iptables -I DOCKER-USER 1 -i br-agentbot -d "$dest" -j REJECT
    fi
done
if ! iptables -C INPUT -i br-agentbot -j REJECT 2>/dev/null; then
    [ "${1:-}" = install ] || exit 1
    iptables -I INPUT 1 -i br-agentbot -j REJECT
fi
SH
chmod 755 /usr/local/sbin/agentbot-network
/usr/local/sbin/agentbot-network install
cat > /etc/systemd/system/agentbot-computer-agent.service <<'UNIT'
[Unit]
Description=Agent Control trusted cloud host service
After=network-online.target docker.service
Requires=docker.service
Wants=network-online.target

[Service]
Type=simple
User=root
UMask=0077
ExecStartPre=/usr/local/sbin/agentbot-network install
ExecStart=/opt/agentbot-host/venv/bin/agentbot-computer-agent run
ExecStopPost=/opt/agentbot-host/venv/bin/agentbot-computer-agent fence
Restart=always
RestartSec=5
TimeoutStopSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT
if [ ! -f /var/lib/agentbot-host/agent.json ] && python3 -c 'import json; raise SystemExit(json.load(open("/etc/agentbot/bootstrap.json")).get("ownership") != "managed")'; then
    /opt/agentbot-host/venv/bin/agentbot-computer-agent bootstrap
fi
systemctl daemon-reload
if [ -f /var/lib/agentbot-host/agent.json ]; then
    systemctl enable --now agentbot-computer-agent
else
    echo 'Host installed. Generate identity, enroll interactively, pull the approved sandbox digest, then enable the service.'
fi
