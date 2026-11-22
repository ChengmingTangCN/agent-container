# syntax=docker/dockerfile:1

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

ARG TARGETARCH
ARG APT_MIRROR=http://mirrors.ustc.edu.cn/ubuntu

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    test "${TARGETARCH}" = "amd64" \
 && rm -f /etc/apt/apt.conf.d/docker-clean \
 && sed -i "s|http://archive.ubuntu.com/ubuntu|${APT_MIRROR}|g" \
      /etc/apt/sources.list.d/ubuntu.sources \
 && dpkg --add-architecture i386 \
 && if ! timeout 45s apt-get \
      -o Acquire::Retries=1 \
      -o Acquire::http::Timeout=10 \
      -o Acquire::https::Timeout=10 \
      -o APT::Update::Error-Mode=any update; then \
      echo "Configured APT mirror was unavailable; using archive.ubuntu.com" >&2; \
      sed -i "s|${APT_MIRROR}|http://archive.ubuntu.com/ubuntu|g" \
        /etc/apt/sources.list.d/ubuntu.sources; \
      apt-get -o Acquire::Retries=5 update; \
    fi \
 && apt-get -o Acquire::Retries=5 install -y \
    bubblewrap \
    ca-certificates \
    curl \
    dbus-x11 \
    file \
    fonts-dejavu-core \
    fonts-liberation \
    fonts-noto-cjk \
    libegl-mesa0 \
    libegl-mesa0:i386 \
    libgl1-mesa-dri \
    libgl1-mesa-dri:i386 \
    libglx-mesa0 \
    libglx-mesa0:i386 \
    libpulse0 \
    libpulse0:i386 \
    libvulkan1 \
    libvulkan1:i386 \
    locales \
    mesa-utils \
    mesa-va-drivers \
    mesa-va-drivers:i386 \
    mesa-vulkan-drivers \
    mesa-vulkan-drivers:i386 \
    pulseaudio-utils \
    steam-installer \
    sudo \
    vulkan-tools \
    x11-utils \
    xdg-utils \
    zenity \
 && locale-gen en_US.UTF-8 zh_CN.UTF-8 \
 && rm -rf /var/lib/apt/lists/*

ENV LANG=zh_CN.UTF-8
ENV LANGUAGE=zh_CN:zh
ENV LC_ALL=zh_CN.UTF-8
ENV PATH=/usr/games:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

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
    echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/${USERNAME}"; \
    chmod 0440 "/etc/sudoers.d/${USERNAME}"

COPY --chmod=0755 entrypoint.sh /usr/local/bin/steam-entrypoint

USER ${USERNAME}
WORKDIR /home/${USERNAME}

ENTRYPOINT ["/usr/local/bin/steam-entrypoint"]
CMD ["run"]
