"""
Script demostrativo: Comparativa de serialización en bytes entre Protobuf y JSON.
Implementa codificación Varint y serialización manual de Protobuf sin dependencias externas.
"""

import json


def varint(n: int) -> bytes:
    """Codifica un número entero positivo en formato Varint de Protobuf (LEB128)."""
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        out += bytes([b | 0x80 if n else b])
        if not n:
            return out


def encode_usuario(id_: int, nombre: str) -> bytes:
    """
    Serializa manualmente el mensaje de Usuario con esquema protobuf:
    message Usuario {
      int32 id = 1;
      string nombre = 2;
    }

    Tag 1 (id): (1 << 3) | 0 = 0x08 (wire type 0: varint)
    Tag 2 (nombre): (2 << 3) | 2 = 0x12 (wire type 2: length-delimited)
    """
    n = nombre.encode("utf-8")
    return b"\x08" + varint(id_) + b"\x12" + varint(len(n)) + n


def main():
    obj = {"id": 42, "nombre": "Juan"}

    # Serialización Protobuf manual
    pb = encode_usuario(id_=42, nombre="Juan")

    # Serializaciones JSON
    js_standard = json.dumps(obj).encode("utf-8")
    js_compact = json.dumps(obj, separators=(",", ":")).encode("utf-8")

    print("=" * 65)
    print("DEMOSTRACIÓN: SERIALIZACIÓN EN BYTES (PROTOBUF vs JSON)")
    print("=" * 65)
    print(f"Objeto de prueba  : {obj}")
    print("-" * 65)
    print(f"Protobuf          : {pb.hex(' '):<28} -> {len(pb)} bytes")
    print(f"JSON estándar     : {js_standard.decode():<28} -> {len(js_standard)} bytes")
    print(f"JSON compacto     : {js_compact.decode():<28} -> {len(js_compact)} bytes")
    print("-" * 65)
    print(f"Ahorro de Protobuf vs JSON estándar : {(1 - len(pb)/len(js_standard)) * 100:.1f}%")
    print(f"Ahorro de Protobuf vs JSON compacto : {(1 - len(pb)/len(js_compact)) * 100:.1f}%")
    print("=" * 65)


if __name__ == "__main__":
    main()
