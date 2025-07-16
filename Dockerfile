# Usa una imagen base de Python
FROM python:3.11-slim

# Instalar dependencias del sistema necesarias para Chrome
RUN apt-get update && apt-get install -y \
    wget \
    ca-certificates \
    curl \
    unzip \
    libx11-dev \
    libxrender1 \
    libxext6 \
    libglib2.0-0 \
    libnss3 \
    libasound2 \
    fonts-liberation \
    libappindicator3-1 \
    libgdk-pixbuf2.0-0 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libnspr4 \
    libxcomposite1 \
    libxrandr2 \
    libgconf-2-4 \
    libkwineffects6 \
    libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

# Instalar Google Chrome
RUN curl -sS https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o google-chrome.deb && \
    dpkg -i google-chrome.deb; \
    apt-get install -f -y

# Instalar ChromeDriver
RUN LATEST_CHROMEDRIVER=$(curl -sS chromedriver.storage.googleapis.com/LATEST_RELEASE) && \
    curl -sS -o chromedriver_linux64.zip https://chromedriver.storage.googleapis.com/$LATEST_CHROMEDRIVER/chromedriver_linux64.zip && \
    unzip chromedriver_linux64.zip -d /usr/local/bin/ && \
    rm chromedriver_linux64.zip

# Establecer variables de entorno
ENV CHROME_BIN=/usr/bin/google-chrome
ENV CHROMEDRIVER_PATH=/usr/local/bin/chromedriver

# Crear directorio de trabajo
WORKDIR /app

# Copiar los archivos de tu aplicación al contenedor
COPY . /app

# Instalar dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# Exponer el puerto 5000 para la aplicación Flask
EXPOSE 5000

# Comando para ejecutar la aplicación
CMD ["python", "app.py"]
