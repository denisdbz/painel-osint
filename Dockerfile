# Usa imagem base Python slim
FROM python:3.12-slim

# Impede prompts interativos durante a instalação de pacotes
ENV DEBIAN_FRONTEND=noninteractive

# Define o diretório de trabalho padrão no Render
WORKDIR /opt/render/project/src

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
# Instala PhoneInfoga (versão 2.10.8, amd64 compatível com Render)
# =====================================================
RUN wget https://github.com/sundowndev/phoneinfoga/releases/download/v2.10.8/phoneinfoga_Linux_x86_64.tar.gz \
    && tar -xzf phoneinfoga_Linux_x86_64.tar.gz -C /usr/local/bin \
    && chmod +x /usr/local/bin/phoneinfoga \
    && rm phoneinfoga_Linux_x86_64.tar.gz

# =====================================================
# Instala Sherlock no diretório de ferramentas
# =====================================================
RUN git clone https://github.com/sherlock-project/sherlock.git tools/sherlock \
    && pip install -r tools/sherlock/requirements.txt

# =====================================================
# Copia o projeto principal
# =====================================================
COPY . .

# Instala as bibliotecas Python do projeto principal
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Exposição de porta
ENV PORT=10000
EXPOSE 10000

# Número de workers configurável (Render recomenda usar variável de ambiente WEB_CONCURRENCY)
ENV WEB_CONCURRENCY=1

# Comando para iniciar a aplicação com Gunicorn
# - gevent -> suporte async
# - t 180 -> timeout aumentado
CMD ["sh", "-c", "gunicorn -k gevent -w ${WEB_CONCURRENCY:-1} -t 180 -b 0.0.0.0:10000 painel_unificado:create_app()"]
