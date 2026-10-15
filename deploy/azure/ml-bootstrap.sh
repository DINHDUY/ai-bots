#!/bin/bash
# Install at the approved workspaceStorage path before enabling managed ML create.
# The only argument is base64 non-secret configuration plus pinned installer references.
set -eu
umask 077
install -d -m 700 /etc/agentbot
printf %s "$1" | base64 -d > /etc/agentbot/create.sh
bash /etc/agentbot/create.sh
