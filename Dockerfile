FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

# Instala dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    exiftool \
    mediainfo \
    poppler-utils \
    ffmpeg \
    binutils \
    file \
    strings \
    git \
    curl \
    wget \
    unzip \
    tar \
    python3-pip \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# =====================================================
# 📱 Instala PhoneInfoga (versão 2.10.8, amd64 compatível com Render)
# =====================================================
RUN wget https://github.com/sundowndev/phoneinfoga/releases/download/v2.10.8/phoneinfoga_Linux_x86_64.tar.gz \
    && tar -xzf phoneinfoga_Linux_x86_64.tar.gz -C /usr/local/bin \
    && chmod +x /usr/local/bin/phoneinfoga \
    && rm phoneinfoga_Linux_x86_64.tar.gz

# Diretório de trabalho do projeto
WORKDIR /app
RUN mkdir uploads runs tools

# Copia arquivos do projeto
COPY . /app

# Atualiza pip e instala bibliotecas Python
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Exposição de porta
ENV PORT=10000
EXPOSE 10000

# Comando default via Gunicorn
CMD ["gunicorn", "-b", "0.0.0.0:10000", "painel_unificado:create_app()"]
