# Frame Picture — imagem do app PicFrame 2.0 (branch dev) sob labwc (Wayland-kiosk)
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

# --- aplicacao: PicFrame 2.0 a partir do nosso fork/branch (inclui o frontend Vue ja compilado) ---
# Camada separada para nao reinstalar o sistema a cada mudanca de codigo.
ARG PICFRAME_REF=framepicture
RUN pip install --no-cache-dir --break-system-packages \
      "git+https://github.com/rtsantanna/frame-picture.git@${PICFRAME_REF}"

# start.sh e labwc-rc.xml sao montados via compose (editaveis sem rebuild)
CMD ["/bin/bash"]
