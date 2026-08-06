# syntax=docker/dockerfile:1

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
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
    nodejs \
    npm \
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
ENV PATH=/home/${USERNAME}/.npm-global/bin:${PATH}

USER ${USERNAME}
RUN npm i -g @openai/codex opencode-ai@latest

WORKDIR /work

CMD ["bash"]
