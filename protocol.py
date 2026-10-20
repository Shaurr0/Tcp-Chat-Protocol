"""
protocol.py

Implements the custom application-layer message format described in the
project's PROTOCOL DESIGN slide:

    Header (9 bytes)                         Payload            Trailer
    +--------+-----------+------------------+ ... variable ... +----------+
    | Type   | Sender ID | Payload Length   |     Payload      | Checksum |
    | 1 byte | 4 bytes   | 4 bytes          |     variable     | 2 bytes  |
    +--------+-----------+------------------+ ... variable ... +----------+

All integer fields are big-endian ("network byte order"), matching normal
TCP/IP convention. The protocol is carried over a single persistent TCP
socket per client, so no message-level retransmission is implemented --
TCP already guarantees in-order, lossless delivery of the byte stream.
This module only has to turn that byte stream back into discrete frames.
"""

import socket
import struct

# ---------------------------------------------------------------------------
# Message types (the "Type" field of the header)
# ---------------------------------------------------------------------------
JOIN = 0x01        # client registers with the server (payload: username)
CHAT = 0x02        # broadcast text message (payload: utf-8 text)
FILE_META = 0x03   # filename, size, destination client id
FILE_CHUNK = 0x04  # one ordered block of file data
FILE_END = 0x05    # marks end of a file transfer
ACK = 0x06         # delivery confirmation
ERROR = 0x07       # failure / rejection notice

TYPE_NAMES = {
    JOIN: "JOIN", CHAT: "CHAT", FILE_META: "FILE_META",
    FILE_CHUNK: "FILE_CHUNK", FILE_END: "FILE_END",
    ACK: "ACK", ERROR: "ERROR",
}

HEADER_FORMAT = "!BII"          # type(1) + sender_id(4) + payload_len(4)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)   # 9 bytes
CHECKSUM_FORMAT = "!H"          # 2-byte checksum
CHECKSUM_SIZE = struct.calcsize(CHECKSUM_FORMAT)

MAX_PAYLOAD = 16 * 1024 * 1024  # 16 MB safety cap on a single frame
FILE_CHUNK_SIZE = 4096          # fixed-size block for chunked file streaming


class ProtocolError(Exception):
    """Raised when a frame fails validation (bad checksum, oversized, etc.)."""


def checksum16(data: bytes) -> int:
    """
    16-bit ones'-complement checksum, computed the same way as the classic
    IP/TCP checksum: sum 16-bit words with end-around carry, then invert.
    Cheap to compute and enough to catch accidental corruption; it is a
    frame-integrity check, not a cryptographic one.
    """
    if len(data) % 2 == 1:
        data = data + b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        word = (data[i] << 8) + data[i + 1]
        total += word
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def pack_message(msg_type: int, sender_id: int, payload: bytes) -> bytes:
    """Build one full wire frame: header + payload + checksum."""
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError(f"payload of {len(payload)} bytes exceeds MAX_PAYLOAD")
    header = struct.pack(HEADER_FORMAT, msg_type, sender_id, len(payload))
    trailer = struct.pack(CHECKSUM_FORMAT, checksum16(header + payload))
    return header + payload + trailer


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """
    Read exactly n bytes from a TCP stream socket, or raise ConnectionError
    if the peer closes early. recv() on a stream socket can return fewer
    bytes than requested, so framing requires looping until we have them all
    -- this is the "framing of application data on top of a byte stream"
    the background slide calls out.
    """
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed while reading a frame")
        buf.extend(chunk)
    return bytes(buf)


def read_message(sock: socket.socket):
    """
    Read one full frame from the socket and return (msg_type, sender_id, payload).
    Raises ConnectionError on a clean disconnect, ProtocolError on a corrupt frame.
    """
    header = _recv_exact(sock, HEADER_SIZE)
    msg_type, sender_id, payload_len = struct.unpack(HEADER_FORMAT, header)
    if payload_len > MAX_PAYLOAD:
        raise ProtocolError(f"declared payload length {payload_len} too large")
    payload = _recv_exact(sock, payload_len) if payload_len else b""
    trailer = _recv_exact(sock, CHECKSUM_SIZE)
    (recv_checksum,) = struct.unpack(CHECKSUM_FORMAT, trailer)
    if checksum16(header + payload) != recv_checksum:
        raise ProtocolError("checksum mismatch: frame corrupted in transit")
    return msg_type, sender_id, payload


def send_message(sock: socket.socket, msg_type: int, sender_id: int, payload: bytes = b""):
    sock.sendall(pack_message(msg_type, sender_id, payload))


# ---------------------------------------------------------------------------
# Small helpers for the payload formats used by specific message types.
# Each of these is a minimal, explicit wire format -- not a generic
# serialization library -- to keep the framing easy to reason about.
# ---------------------------------------------------------------------------

def encode_join_payload(username: str) -> bytes:
    return username.encode("utf-8")


def decode_join_payload(payload: bytes) -> str:
    return payload.decode("utf-8")


def encode_chat_payload(text: str) -> bytes:
    return text.encode("utf-8")


def decode_chat_payload(payload: bytes) -> str:
    return payload.decode("utf-8")


def encode_file_meta_payload(filename: str, filesize: int, dest_id: int) -> bytes:
    """dest_id(4B) + filesize(8B) + filename(utf-8, rest of payload)."""
    name_bytes = filename.encode("utf-8")
    return struct.pack("!IQ", dest_id, filesize) + name_bytes


def decode_file_meta_payload(payload: bytes):
    dest_id, filesize = struct.unpack("!IQ", payload[:12])
    filename = payload[12:].decode("utf-8")
    return filename, filesize, dest_id


def encode_file_chunk_payload(dest_id: int, seq_num: int, data: bytes) -> bytes:
    """dest_id(4B) + seq_num(4B) + raw chunk bytes."""
    return struct.pack("!II", dest_id, seq_num) + data


def decode_file_chunk_payload(payload: bytes):
    dest_id, seq_num = struct.unpack("!II", payload[:8])
    return dest_id, seq_num, payload[8:]


def encode_file_end_payload(dest_id: int, filename: str) -> bytes:
    return struct.pack("!I", dest_id) + filename.encode("utf-8")


def decode_file_end_payload(payload: bytes):
    (dest_id,) = struct.unpack("!I", payload[:4])
    filename = payload[4:].decode("utf-8")
    return dest_id, filename


def encode_error_payload(message: str) -> bytes:
    return message.encode("utf-8")


def decode_error_payload(payload: bytes) -> str:
    return payload.decode("utf-8")
