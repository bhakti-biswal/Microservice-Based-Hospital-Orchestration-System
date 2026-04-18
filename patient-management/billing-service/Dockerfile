FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Compile proto → billing_service_pb2.py + billing_service_pb2_grpc.py
COPY proto/ ./proto/
RUN python -m grpc_tools.protoc \
    -I./proto \
    --python_out=. \
    --grpc_python_out=. \
    ./proto/billing_service.proto

COPY . .
EXPOSE 50051
CMD ["python", "grpc_server.py"]
