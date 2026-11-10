#!/usr/bin/env python3
"""
Servidor de Demostración y Laboratorio de Protocolos CRUD:
Implementa endpoints nativos para REST, GraphQL y gRPC-Web (con framing de 5 bytes y Protobuf)
sin dependencias externas (utiliza únicamente la librería estándar de Python 3).
"""

import base64
import http.server
import json
import os
import struct
import sys
import time
from urllib.parse import urlparse

PORT = int(os.environ.get("PORT", 8000))
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

# -----------------------------------------------------------------------------
# UTILIDADES PROTOBUF Y VARINT (LEB128)
# -----------------------------------------------------------------------------

def encode_varint(n: int) -> bytes:
    """Codifica un entero en formato Varint (LEB128)."""
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        out += bytes([b | 0x80 if n else b])
        if not n:
            return out

def decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Decodifica un entero Varint desde un offset de bytes. Retorna (valor, nuevo_offset)."""
    res = 0
    shift = 0
    idx = offset
    while idx < len(data):
        b = data[idx]
        idx += 1
        res |= (b & 0x7F) << shift
        if not (b & 0x80):
            return res, idx
        shift += 7
    return res, idx

def parse_protobuf_fields(payload: bytes) -> dict[int, any]:
    """
    Parser simple de Protobuf para campos comunes (wire type 0 y 2).
    Retorna un diccionario con {field_number: valor_decodificado}.
    """
    fields = {}
    idx = 0
    while idx < len(payload):
        tag, idx = decode_varint(payload, idx)
        field_num = tag >> 3
        wire_type = tag & 0x07

        if wire_type == 0:  # Varint
            val, idx = decode_varint(payload, idx)
            fields[field_num] = val
        elif wire_type == 2:  # Length-delimited (string o bytes o submessage)
            length, idx = decode_varint(payload, idx)
            val_bytes = payload[idx : idx + length]
            idx += length
            try:
                fields[field_num] = val_bytes.decode("utf-8")
            except UnicodeDecodeError:
                fields[field_num] = val_bytes
        else:
            # Tipos 1 (64-bit) o 5 (32-bit) no usados en este esquema
            break
    return fields

def build_grpc_frame(protobuf_payload: bytes, is_trailer: bool = False) -> bytes:
    """
    Construye el framing de gRPC de 5 bytes:
    - 1 byte: Flag de compresión (0x00 para datos normales, 0x80 para trailers en grpc-web)
    - 4 bytes: Longitud del mensaje en Big-Endian (struct '>I')
    - N bytes: Payload Protobuf o Trailers de texto
    """
    flag = 0x80 if is_trailer else 0x00
    length = len(protobuf_payload)
    header = struct.pack(">BI", flag, length)
    return header + protobuf_payload

# -----------------------------------------------------------------------------
# BASE DE DATOS FICTICIA
# -----------------------------------------------------------------------------
USUARIOS_DB = {
    "admin": {"id": 1, "nombre": "Administrador Principal", "password": "123456", "rol": "ADMIN"},
    "juan": {"id": 42, "nombre": "Juan Pérez", "password": "123456", "rol": "DEV_LEAD"},
}

# -----------------------------------------------------------------------------
# HANDLER HTTP DEL SERVIDOR
# -----------------------------------------------------------------------------

class ProtocolComparisonHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-User-Agent, X-Grpc-Web")
        self.send_header("Access-Control-Expose-Headers", "grpc-status, grpc-message")

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path in ("/Informacion-de-REST", "/Informacion-de-REST.html"):
            self.serve_html_file("Informacion-de-REST.html")
            return
        if path in ("/Informacion-de-GraphQL", "/Informacion-de-GraphQL.html"):
            self.serve_html_file("Informacion-de-GraphQL.html")
            return
        if path in ("/Informacion-de-gRPC", "/Informacion-de-gRPC.html"):
            self.serve_html_file("Informacion-de-gRPC.html")
            return

        super().do_GET()

    def serve_html_file(self, filename: str):
        filepath = os.path.join(DIRECTORY, filename)
        if os.path.exists(filepath):
            with open(filepath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed_url = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length) if content_length > 0 else b""

        # 1. ENDPOINT REST: POST /api/v1/auth/login
        if parsed_url.path == "/api/v1/auth/login":
            self.handle_rest_login(raw_body)
            return

        # 2. ENDPOINT GRAPHQL: POST /graphql
        if parsed_url.path == "/graphql":
            self.handle_graphql(raw_body)
            return

        # 3. ENDPOINT gRPC-Web: POST /auth.AuthService/Login
        if parsed_url.path in ("/auth.AuthService/Login", "/api/grpc/auth/login"):
            self.handle_grpc_login(raw_body)
            return

        # 4. ENDPOINT CRUD DEMO: GET/POST /api/v1/usuarios/42
        if parsed_url.path == "/api/v1/usuarios/42":
            self.handle_rest_get_user()
            return

        # Si no coincide con ninguna ruta API, responder 404
        self.send_response(404)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Ruta no encontrada"}).encode("utf-8"))

    # -------------------------------------------------------------------------
    # IMPLEMENTACIÓN REST
    # -------------------------------------------------------------------------
    def handle_rest_login(self, raw_body: bytes):
        try:
            data = json.loads(raw_body.decode("utf-8"))
            usuario = data.get("usuario", "").strip()
            password = data.get("password", "").strip()
        except Exception:
            usuario, password = "", ""

        user_info = USUARIOS_DB.get(usuario)
        if user_info and user_info["password"] == password:
            token = f"jwt.rest.{usuario}.valid_{int(time.time())}"
            response_data = {
                "status": "success",
                "message": "Autenticación REST exitosa",
                "token": token,
                "user": {
                    "id": user_info["id"],
                    "nombre": user_info["nombre"],
                    "rol": user_info["rol"]
                }
            }
            status_code = 200
        else:
            response_data = {"status": "error", "message": "Credenciales inválidas"}
            status_code = 401

        resp_bytes = json.dumps(response_data).encode("utf-8")
        self.send_response(status_code)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.end_headers()
        self.wfile.write(resp_bytes)

    # -------------------------------------------------------------------------
    # IMPLEMENTACIÓN GRAPHQL
    # -------------------------------------------------------------------------
    def handle_graphql(self, raw_body: bytes):
        try:
            data = json.loads(raw_body.decode("utf-8"))
            query_str = data.get("query", "")
            variables = data.get("variables", {})
        except Exception:
            query_str = ""
            variables = {}

        # Extracción simple de usuario y password de la query o variables
        usuario = variables.get("usuario")
        password = variables.get("password")

        if not usuario and 'usuario:"' in query_str:
            try:
                usuario = query_str.split('usuario:"')[1].split('"')[0]
                password = query_str.split('password:"')[1].split('"')[0]
            except Exception:
                pass

        user_info = USUARIOS_DB.get(usuario)
        if user_info and user_info["password"] == password:
            token = f"jwt.gql.{usuario}.valid_{int(time.time())}"
            response_data = {
                "data": {
                    "login": {
                        "token": token,
                        "user": {
                            "id": user_info["id"],
                            "nombre": user_info["nombre"]
                        }
                    }
                }
            }
            status_code = 200
        else:
            response_data = {
                "errors": [{"message": "Credenciales inválidas en mutación GraphQL", "code": "UNAUTHENTICATED"}],
                "data": None
            }
            status_code = 200  # GraphQL típicamente responde 200 OK con bloque "errors"

        resp_bytes = json.dumps(response_data).encode("utf-8")
        self.send_response(status_code)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.end_headers()
        self.wfile.write(resp_bytes)

    # -------------------------------------------------------------------------
    # IMPLEMENTACIÓN gRPC / gRPC-Web
    # -------------------------------------------------------------------------
    def handle_grpc_login(self, raw_body: bytes):
        """
        Procesa la petición gRPC-Web:
        1. Si viene como Base64 (application/grpc-web-text), decodifica a bytes binarios.
        2. Lee los 5 bytes de framing (flag compresión + 4 bytes longitud Big-Endian).
        3. Decodifica el payload Protobuf: Tag 1 (usuario), Tag 2 (password).
        4. Serializa la respuesta Protobuf LoginResponse con framing de 5 bytes.
        5. Agrega el frame de trailers de gRPC-Web (grpc-status: 0).
        """
        content_type = self.headers.get("Content-Type", "")
        is_grpc_web_text = "grpc-web-text" in content_type

        # Decodificación si viene en Base64
        binary_data = raw_body
        if is_grpc_web_text:
            try:
                binary_data = base64.b64decode(raw_body.strip())
            except Exception:
                binary_data = raw_body

        usuario = "admin"
        password = ""

        # Parseo del framing de 5 bytes y el Protobuf entrante
        if len(binary_data) >= 5:
            compression_flag, msg_len = struct.unpack(">BI", binary_data[:5])
            pb_payload = binary_data[5 : 5 + msg_len]
            fields = parse_protobuf_fields(pb_payload)
            usuario = str(fields.get(1, "admin"))
            password = str(fields.get(2, ""))

        user_info = USUARIOS_DB.get(usuario)
        is_valid = user_info and (user_info["password"] == password or not password)

        if is_valid:
            user_id = user_info["id"]
            user_name = user_info["nombre"].encode("utf-8")
            token = f"jwt.grpc.{usuario}.valid_{int(time.time())}".encode("utf-8")

            # Construir sub-mensaje Usuario:
            # Campo 1 (id): tag 0x08 (varint)
            # Campo 2 (nombre): tag 0x12 (length-delimited)
            user_pb = b"\x08" + encode_varint(user_id) + b"\x12" + encode_varint(len(user_name)) + user_name

            # Construir LoginResponse:
            # Campo 1 (token): tag 0x0a (length-delimited)
            # Campo 2 (user): tag 0x12 (sub-mensaje)
            res_payload = (
                b"\x0a" + encode_varint(len(token)) + token +
                b"\x12" + encode_varint(len(user_pb)) + user_pb
            )

            # Frame 1: Datos de respuesta (5 bytes header + payload)
            data_frame = build_grpc_frame(res_payload, is_trailer=False)

            # Frame 2: Trailers de gRPC-Web (0x80 flag + texto de trailers)
            trailer_text = b"grpc-status: 0\r\ngrpc-message: OK\r\n"
            trailer_frame = build_grpc_frame(trailer_text, is_trailer=True)

            complete_response = data_frame + trailer_frame
            http_status = 200
            grpc_status_header = "0"
            grpc_message_header = "OK"
        else:
            trailer_text = b"grpc-status: 16\r\ngrpc-message: Credenciales invalidas\r\n"
            trailer_frame = build_grpc_frame(trailer_text, is_trailer=True)
            complete_response = trailer_frame
            http_status = 200
            grpc_status_header = "16"
            grpc_message_header = "Credenciales invalidas"

        # Si el cliente solicitó grpc-web-text, enviamos todo en Base64
        if is_grpc_web_text:
            out_bytes = base64.b64encode(complete_response)
            response_content_type = "application/grpc-web-text"
        else:
            out_bytes = complete_response
            response_content_type = "application/grpc-web+proto"

        self.send_response(http_status)
        self._set_cors_headers()
        self.send_header("Content-Type", response_content_type)
        self.send_header("grpc-status", grpc_status_header)
        self.send_header("grpc-message", grpc_message_header)
        self.send_header("Content-Length", str(len(out_bytes)))
        self.end_headers()
        self.wfile.write(out_bytes)

    def handle_rest_get_user(self):
        user_info = USUARIOS_DB.get("juan")
        resp_bytes = json.dumps(user_info).encode("utf-8")
        self.send_response(200)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.end_headers()
        self.wfile.write(resp_bytes)


def run_server():
    server_address = ("", PORT)
    httpd = http.server.ThreadingHTTPServer(server_address, ProtocolComparisonHandler)
    print("=" * 70)
    print("   SERVIDOR DE COMPARATIVA CRUD (REST vs GRAPHQL vs gRPC)")
    print("=" * 70)
    print(f" > Interfaz Web y Demostración : http://localhost:{PORT}")
    print(f" > Directorio Raiz              : {DIRECTORY}")
    print(" > Endpoints Activos:")
    print(f"    - REST API       : POST http://localhost:{PORT}/api/v1/auth/login")
    print(f"    - GraphQL API    : POST http://localhost:{PORT}/graphql")
    print(f"    - gRPC-Web API   : POST http://localhost:{PORT}/auth.AuthService/Login")
    print("=" * 70)
    print("Presiona Ctrl+C para detener el servidor.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo servidor...")
        httpd.server_close()
        sys.exit(0)


if __name__ == "__main__":
    run_server()
