# syntax=docker/dockerfile:1

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

ARG TARGETARCH

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    if [ "${TARGETARCH}" = "arm64" ]; then \
        sed -i 's|http://ports.ubuntu.com/ubuntu-ports|http://mirrors.ustc.edu.cn/ubuntu-ports|g' /etc/apt/sources.list.d/ubuntu.sources; \
    elif [ "${TARGETARCH}" = "amd64" ]; then \
        sed -i 's|http://archive.ubuntu.com/ubuntu|http://mirrors.ustc.edu.cn/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources; \
    fi \
 && rm -f /etc/apt/apt.conf.d/docker-clean \
 && apt-get update \
 && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
    sudo \
    curl \
    wget \
    git \
    ca-certificates \
    build-essential \
    pkg-config \
    locales \
    python3 \
    python3-pip \
    python3-venv \
    bubblewrap \
    tmux \
    gdb \
    gdbserver \
    strace \
    ltrace \
    file \
    procps \
    psmisc \
    net-tools \
    iproute2 \
    iputils-ping \
    ncurses-term \
    ripgrep \
    fd-find \
    jq \
    vim \
    less \
    bash-completion \
 && locale-gen en_US.UTF-8 zh_CN.UTF-8

ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

ARG USERNAME=dev
ARG UID=1000
ARG GID=1000

RUN set -eux; \
    if getent passwd "${UID}" >/dev/null; then \
        EXISTING_USER="$(getent passwd "${UID}" | cut -d: -f1)"; \
        userdel -r "${EXISTING_USER}" || userdel "${EXISTING_USER}" || true; \
    fi; \
    if getent group "${GID}" >/dev/null; then \
        EXISTING_GROUP="$(getent group "${GID}" | cut -d: -f1)"; \
        groupdel "${EXISTING_GROUP}" || true; \
    fi; \
    if id "${USERNAME}" >/dev/null 2>&1; then \
        userdel -r "${USERNAME}" || userdel "${USERNAME}" || true; \
    fi; \
    if getent group "${USERNAME}" >/dev/null; then \
        groupdel "${USERNAME}" || true; \
    fi; \
    groupadd -g "${GID}" "${USERNAME}"; \
    useradd -m -u "${UID}" -g "${GID}" -s /bin/bash "${USERNAME}"; \
    install -d -o "${USERNAME}" -g "${USERNAME}" "/home/${USERNAME}/.npm-global"; \
    echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/${USERNAME}"; \
    chmod 0440 "/etc/sudoers.d/${USERNAME}"

ENV NPM_CONFIG_PREFIX=/home/${USERNAME}/.npm-global
ENV PATH=/home/${USERNAME}/.node/bin:/home/${USERNAME}/.npm-global/bin:${PATH}

USER ${USERNAME}
RUN set -eux; \
    NODE_ARCH="$([ "${TARGETARCH}" = "arm64" ] && echo arm64 || echo x64)"; \
    NODE_VERSION="$(curl -fsSL https://nodejs.org/dist/latest-v24.x/ | grep -oE 'node-v24\.[0-9]+\.[0-9]+' | sort -Vu | tail -1 | sed 's/^node-v//')"; \
    curl -fsSL --retry 3 "https://nodejs.org/dist/node-v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" -o /tmp/node.tar.xz; \
    mkdir -p "${HOME}/.node"; \
    tar -xJf /tmp/node.tar.xz -C "${HOME}/.node" --strip-components=1; \
    rm -f /tmp/node.tar.xz; \
    node --version; \
    npm --version

RUN npm i -g --registry=https://registry.npmmirror.com @openai/codex opencode-ai@latest @earendil-works/pi-coding-agent

WORKDIR /work

CMD ["bash"]
