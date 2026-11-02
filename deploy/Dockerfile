# Frame Picture — imagem do app PicFrame 2.0 (fork local) sob labwc (Wayland-kiosk)
# Base casando com o host (Debian 13 trixie ARM64). Mesa/driver vc4-v3d vem do host via /dev/dri.
FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV LANG=en_US.UTF-8

# --- dependencias de sistema ---
# GL/SDL runtime (validados na Missao 01) + stack 2.0 (GTK4/GStreamer/GI) + compositor labwc + seatd
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git procps psmisc \
      build-essential \
      python3 python3-dev python3-pip python3-venv \
      python3-gi python3-gst-1.0 \
      libgl1-mesa-dri libgles2 libegl1 libgbm1 \
      libsdl2-2.0-0 \
      mesa-utils \
      gir1.2-glib-2.0 gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 gir1.2-gtk-4.0 \
      gstreamer1.0-libav gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
      gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-gtk4 \
      gstreamer1.0-tools gstreamer1.0-gl \
      labwc seatd libseat1 \
      locales fonts-dejavu-core \
      libjpeg62-turbo libopenjp2-7 libtiff6 zlib1g \
 && apt-get clean

# --- locale (o app tenta setar en_US.UTF-8) ---
RUN sed -i 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && locale-gen

# --- tooling extra (camada propria p/ nao invalidar a camada pesada de apt): ---
#  * exiftool: EXIF/XMP/IPTC de fotos + metadados de contêiner de video.
#  * wlr-randr: liga/desliga o output HDMI sob o compositor wlroots/labwc
#    (usado pelo WaylandDisplayPower e pelo agendador noturno).
RUN apt-get update && apt-get install -y --no-install-recommends \
      libimage-exiftool-perl wlr-randr \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# --- timezone America/Sao_Paulo ---
# TZ (lido pela libc/Python) + /etc/localtime e /etc/timezone (apps que ignoram TZ).
# tzdata ja vem como dependencia da stack; o zoneinfo America/Sao_Paulo esta presente.
ENV TZ=America/Sao_Paulo
RUN ln -sf /usr/share/zoneinfo/America/Sao_Paulo /etc/localtime \
 && echo "America/Sao_Paulo" > /etc/timezone

# --- aplicacao: PicFrame 2.0 a partir do codigo local do fork (inclui o frontend Vue ja compilado) ---
# Instala a arvore de fontes presente no contexto de build (app-src/), sem depender de push ao GitHub.
# Camada separada para nao reinstalar o sistema a cada mudanca de codigo.
ARG PICFRAME_VERSION=2.0.0.dev0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${PICFRAME_VERSION}
COPY app-src/ /opt/picframe-src/
RUN pip install --no-cache-dir --break-system-packages /opt/picframe-src \
 && rm -rf /opt/picframe-src

# start.sh e labwc-rc.xml sao montados via compose (editaveis sem rebuild)
CMD ["/bin/bash"]
