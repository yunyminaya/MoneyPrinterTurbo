# Usa un runtime oficial de Python como imagen base
FROM python:3.11-slim-bullseye

# Establece el directorio de trabajo dentro del contenedor
WORKDIR /MoneyPrinterTurbo

# Establece los permisos del directorio /MoneyPrinterTurbo en 777
RUN chmod 777 /MoneyPrinterTurbo

ENV PYTHONPATH="/MoneyPrinterTurbo"

# Los usuarios locales siguen usando por defecto primero el espejo chino; al publicar la imagen GHCR con GitHub Actions se usa "default",
# para evitar que los runners en el extranjero se ralenticen al acceder al espejo chino y la publicación quede bloqueada.
ARG DOCKER_BUILD_MIRROR=china
ARG PIP_USE_OFFICIAL=0

# Instala las dependencias del sistema con lógica de reintento
RUN if [ "$DOCKER_BUILD_MIRROR" = "china" ]; then \
        echo "deb http://mirrors.aliyun.com/debian bullseye main" > /etc/apt/sources.list && \
        echo "deb http://mirrors.aliyun.com/debian-security bullseye-security main" >> /etc/apt/sources.list; \
    else \
        echo "Using default Debian mirrors"; \
    fi && \
    ( \
        for i in 1 2 3; do \
            echo "Attempt $i: installing system dependencies"; \
            apt-get update && apt-get install -y --no-install-recommends \
                git \
                ffmpeg && break || \
            echo "Attempt $i failed, retrying..."; \
            if [ "$DOCKER_BUILD_MIRROR" = "china" ] && [ $i -eq 3 ]; then \
                echo "Aliyun mirror failed, switching to Tsinghua mirror"; \
                sed -i 's/mirrors.aliyun.com/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list && \
                sed -i 's/mirrors.aliyun.com\/debian-security/mirrors.tuna.tsinghua.edu.cn\/debian-security/g' /etc/apt/sources.list && \
                ( \
                    apt-get update && apt-get install -y --no-install-recommends \
                        git \
                        ffmpeg || \
                    ( \
                        echo "Tsinghua mirror failed, switching to default Debian mirror"; \
                        sed -i 's/mirrors.tuna.tsinghua.edu.cn/deb.debian.org/g' /etc/apt/sources.list && \
                        sed -i 's/mirrors.tuna.tsinghua.edu.cn\/debian-security/security.debian.org/g' /etc/apt/sources.list; \
                        apt-get update && apt-get install -y --no-install-recommends \
                            git \
                            ffmpeg; \
                    ); \
                ); \
            fi; \
            sleep 5; \
        done \
    ) && rm -rf /var/lib/apt/lists/*

# Copia primero solo requirements.txt para aprovechar la caché de Docker
COPY requirements.txt ./

# Localmente se usa por defecto primero el espejo chino de PyPI; en la publicación de GHCR se usa el PyPI oficial, para evitar que los runners en el extranjero ralenticen el acceso transfronterizo al espejo.
RUN if [ "$PIP_USE_OFFICIAL" = "1" ]; then \
        pip install --no-cache-dir --retries 3 --timeout 60 -r requirements.txt; \
    else \
        pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com --retries 3 --timeout 60 -r requirements.txt || \
        pip install --no-cache-dir -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/ --trusted-host mirrors.tuna.tsinghua.edu.cn --retries 3 --timeout 60 -r requirements.txt || \
        pip install --no-cache-dir --retries 3 --timeout 60 -r requirements.txt; \
    fi

# Ahora copia el resto del código fuente en la imagen
COPY . .

# Expone el puerto en el que se ejecuta la aplicación
EXPOSE 8501

# Dentro del contenedor se debe escuchar en 0.0.0.0; el host sigue limitado a 127.0.0.1 mediante el mapeo de puertos de Docker.
# browser.serverAddress solo determina la dirección de acceso que muestra el navegador; no sustituye a server.address.
CMD ["streamlit", "run", "./webui/Main.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.serverAddress=127.0.0.1", "--server.enableCORS=True", "--browser.gatherUsageStats=False", "--client.toolbarMode=minimal", "--logger.hideWelcomeMessage=True", "--server.showEmailPrompt=False"]

# 1. Compila la imagen Docker con el siguiente comando
# docker build -t moneyprinterturbo .

# 2. Ejecuta el contenedor Docker con el siguiente comando
## Para Linux o macOS:
# docker run -v $(pwd)/config.toml:/MoneyPrinterTurbo/config.toml -v $(pwd)/storage:/MoneyPrinterTurbo/storage -p 127.0.0.1:8501:8501 moneyprinterturbo
## Para Windows:
# docker run -v ${PWD}/config.toml:/MoneyPrinterTurbo/config.toml -v ${PWD}/storage:/MoneyPrinterTurbo/storage -p 127.0.0.1:8501:8501 moneyprinterturbo
