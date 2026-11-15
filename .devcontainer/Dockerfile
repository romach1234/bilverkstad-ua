# Образ для Linux: усі інструменти tools/ однакові на кожному комп'ютері.
FROM ubuntu:24.04

ARG USERNAME=dev
ARG USER_UID=1000
ARG USER_GID=1000
ARG TZ=Europe/Kyiv

ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 TZ=$TZ PYTHONUTF8=1

# poppler-utils — pdftotext для freeze.py; gh — GitHub CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git openssh-client gh sudo less jq ripgrep tzdata unzip poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# uv — Python і залежності tools/ (pyproject.toml); той самий спосіб запуску, що на Windows: `uv run tools/...`
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# deno — JS-рантайм для yt-dlp: без нього YouTube віддає лише автодубляж замість оригінальної доріжки
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh -s -- -y --no-modify-path && deno --version

# Користувач з тим самим ім'ям і UID, що на хості: тоді шляхи (/home/<user>/.claude, репо) збігаються з хостом,
# і Claude Code бачить ті самі чати. В образі ubuntu:24.04 UID 1000 зайнятий користувачем ubuntu — прибрати
RUN (userdel -r ubuntu 2>/dev/null || true) \
    && groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m -s /bin/bash $USERNAME \
    && echo "$USERNAME ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME

USER $USERNAME
# Claude Code для термінала (розширення VS Code має свій, але `claude` у терміналі контейнера теж потрібен)
RUN curl -fsSL https://claude.ai/install.sh | bash
ENV PATH=/home/$USERNAME/.local/bin:$PATH
