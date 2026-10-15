FROM ubuntu:26.04
LABEL agentbot.sandbox_protocol="2"
LABEL agentbot.computer_protocol="3"

ENV DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONUNBUFFERED=1 \
    DISPLAY=:99

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-pil \
        xvfb \
        openbox \
        xdotool \
        scrot \
        ca-certificates \
        fonts-liberation \
        bash \
        coreutils \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --non-unique --uid 1000 --shell /bin/bash agent \
    && mkdir -p /workspace /ms-playwright \
    && chown agent:agent /workspace

ARG PLAYWRIGHT_VERSION=1.63.0
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi \
    && pip3 install --break-system-packages playwright==${PLAYWRIGHT_VERSION} \
    && python3 -m playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

COPY docker/sandbox/agentbot_sandbox/ /opt/agentbot_sandbox/
COPY packages/agentbot/src/agentbot/sandbox/desktop_plan.py /opt/agentbot_sandbox/desktop_plan.py
COPY docker/sandbox/entrypoint.sh /entrypoint.sh
    RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

USER agent
ENV HOME=/home/agent
WORKDIR /workspace
ENTRYPOINT ["/entrypoint.sh"]
