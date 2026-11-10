import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

TEST_PORT = 8008

def test():
    env = os.environ.copy()
    env["PORT"] = str(TEST_PORT)
    proc = subprocess.Popen([sys.executable, "app.py"], env=env)
    time.sleep(1.2)
    base_url = f"http://localhost:{TEST_PORT}"
    try:
        # 1. Probar HTML
        with urllib.request.urlopen(f"{base_url}/") as res:
            assert res.status == 200
            print("OK -> GET / (HTML Servido correctamente)")

        # 1.1 Probar Páginas de Información Técnica
        for proto in ["REST", "GraphQL", "gRPC"]:
            url = f"{base_url}/Informacion-de-{proto}"
            with urllib.request.urlopen(url) as res:
                assert res.status == 200
                html = res.read().decode()
                assert len(html) > 500
                print(f"OK -> GET /Informacion-de-{proto} (Página de informe técnico servida)")

        # 2. Probar REST
        req = urllib.request.Request(
            f"{base_url}/api/v1/auth/login",
            data=json.dumps({"usuario": "admin", "password": "123456"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read().decode())
            assert data["status"] == "success"
            print("OK -> POST /api/v1/auth/login (REST autenticado)")

        # 3. Probar GraphQL
        req_gql = urllib.request.Request(
            f"{base_url}/graphql",
            data=json.dumps({
                "query": "mutation { login { token } }",
                "variables": {"usuario": "admin", "password": "123456"},
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_gql) as res:
            data = json.loads(res.read().decode())
            assert "data" in data
            print("OK -> POST /graphql (GraphQL mutation resuelta)")

        # 4. Probar gRPC-Web
        frame = b"\x00\x00\x00\x00\x11\x0a\x05admin\x12\x06123456"
        b64 = base64.b64encode(frame)
        req_grpc = urllib.request.Request(
            f"{base_url}/auth.AuthService/Login",
            data=b64,
            headers={"Content-Type": "application/grpc-web-text"},
            method="POST",
        )
        with urllib.request.urlopen(req_grpc) as res:
            assert res.status == 200
            assert res.headers.get("grpc-status") == "0"
            raw_out = res.read()
            assert len(raw_out) > 0
            print("OK -> POST /auth.AuthService/Login (gRPC-Web con trailers validado)")

        print("\nTODOS LOS TESTS DEL SERVIDOR Y ENDPOINTS PASARON EXITOSAMENTE.")
    finally:
        proc.terminate()
        proc.wait()


if __name__ == "__main__":
    test()
