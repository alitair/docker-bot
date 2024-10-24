FROM python:3.10-bullseye

# Install OpenGL dependencies
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir /app
COPY *.py /app/
COPY requirements.txt /app/

WORKDIR /app
RUN pip3 install -r requirements.txt

EXPOSE 7860

CMD ["python3", "server.py"]