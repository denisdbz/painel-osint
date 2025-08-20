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
    python3-pip \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Diretórios do projeto
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
