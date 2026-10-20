"""
gateway.py  --  web frontend bridge (stdlib only, no installs).

Browsers cannot open raw TCP sockets, so this process sits between them and
server.py. Each browser tab gets its own persistent TCP connection to the
chat server, speaking the unchanged protocol from protocol.py. The browser
talks to the gateway over plain HTTP (POST for actions, Server-Sent Events
for incoming messages).

    python3 server.py          # terminal 1
    python3 gateway.py         # terminal 2, then open http://127.0.0.1:8000
"""
import json
import os
import socket
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import protocol as proto

HERE = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS = os.path.join(HERE, "received_files")
SESSIONS = {}


class Session:
    def __init__(self, host, port, username):
        self.username, self.my_id = username, 0
        self.sock = socket.create_connection((host, port), timeout=5)
        self.sock.settimeout(None)
        self.events, self.cv = [], threading.Condition()
        self.lock = threading.Lock()
        self.incoming = {}  # sender_id -> [file handle, name, size, got, chunks]
        os.makedirs(DOWNLOADS, exist_ok=True)
        self.send(proto.JOIN, proto.encode_join_payload(username))
        threading.Thread(target=self._reader, daemon=True).start()

    def emit(self, **ev):
        with self.cv:
            self.events.append(ev)
            self.cv.notify_all()

    def frame(self, direction, t, sender, payload, count=1):
        raw = proto.pack_message(t, sender, payload)
        self.emit(kind="frame", dir=direction, type=proto.TYPE_NAMES.get(t, hex(t)),
                  sender=sender, length=len(payload), checksum=raw[-2:].hex(), count=count)

    def send(self, t, payload=b"", log=True):
        with self.lock:
            proto.send_message(self.sock, t, self.my_id, payload)
        if log:
            self.frame("out", t, self.my_id, payload)

    def _reader(self):
        try:
            while True:
                t, sender, payload = proto.read_message(self.sock)
                self._dispatch(t, sender, payload)
        except (ConnectionError, proto.ProtocolError, OSError) as exc:
            self.emit(kind="closed", reason=str(exc))

    def _dispatch(self, t, sender, payload):
        if t not in (proto.FILE_CHUNK,):
            self.frame("in", t, sender, payload)
        if t == proto.CHAT:
            text = proto.decode_chat_payload(payload)
            if sender == 0:
                self.emit(kind="system", text=text.lstrip("* "))
            else:
                name, _, body = text.partition(": ")
                self.emit(kind="chat", sender=sender, name=name, text=body)
        elif t == proto.ACK:
            note = proto.decode_error_payload(payload)
            if self.my_id == 0 and "id=" in note:
                self.my_id = int(note.rsplit("id=", 1)[1].rstrip(")"))
                self.emit(kind="joined", id=self.my_id, name=self.username)
        elif t == proto.ERROR:
            self.emit(kind="error", text=proto.decode_error_payload(payload))
        elif t == proto.FILE_META:
            name, size, _ = proto.decode_file_meta_payload(payload)
            safe = os.path.basename(name) or "file"
            fh = open(os.path.join(DOWNLOADS, f"{sender}_{safe}"), "wb")
            self.incoming[sender] = [fh, safe, size, 0, 0]
            self.emit(kind="file_start", sender=sender, name=safe, size=size)
        elif t == proto.FILE_CHUNK:
            _, _, data = proto.decode_file_chunk_payload(payload)
            rec = self.incoming.get(sender)
            if rec:
                rec[0].write(data)
                rec[3] += len(data)
                rec[4] += 1
                if rec[4] % 8 == 0:
                    self.emit(kind="file_progress", sender=sender, name=rec[1], got=rec[3])
        elif t == proto.FILE_END:
            rec = self.incoming.pop(sender, None)
            if rec:
                rec[0].close()
                self.emit(kind="frame", dir="in", type="FILE_CHUNK", sender=sender,
                          length=proto.FILE_CHUNK_SIZE, checksum="....", count=rec[4])
                self.emit(kind="file_done", sender=sender, name=rec[1], size=rec[3],
                          url=f"/files/{sender}_{rec[1]}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _session(self, q):
        return SESSIONS.get(q.get("sid", [""])[0])

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/events":
            s = self._session(q)
            if not s:
                return self._json({"error": "unknown session"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            idx = 0
            try:
                while True:
                    with s.cv:
                        if idx >= len(s.events):
                            s.cv.wait(15)
                        batch = s.events[idx:]
                        idx += len(batch)
                    if not batch:
                        self.wfile.write(b": ping\n\n")
                    for ev in batch:
                        self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
        elif u.path.startswith("/files/"):
            path = os.path.join(DOWNLOADS, os.path.basename(unquote(u.path[7:])))
            if not os.path.isfile(path):
                return self._json({"error": "not found"}, 404)
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition",
                             f'attachment; filename="{os.path.basename(path).split("_", 1)[-1]}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        n = int(self.headers.get("Content-Length") or 0)
        if u.path == "/api/connect":
            data = json.loads(self.rfile.read(n) or b"{}")
            try:
                s = Session(data.get("host") or "127.0.0.1", int(data.get("port") or 5555),
                            (data.get("username") or "guest").strip()[:32])
            except OSError as exc:
                return self._json({"error": f"Can't reach the chat server: {exc}"}, 502)
            sid = uuid.uuid4().hex
            SESSIONS[sid] = s
            return self._json({"sid": sid})
        s = self._session(q)
        if not s:
            return self._json({"error": "unknown session"}, 404)
        try:
            if u.path == "/api/chat":
                text = json.loads(self.rfile.read(n))["text"]
                s.send(proto.CHAT, proto.encode_chat_payload(text))
            elif u.path == "/api/file":
                dest = int(q["dest"][0])
                name = os.path.basename(unquote(q["name"][0]))
                s.send(proto.FILE_META, proto.encode_file_meta_payload(name, n, dest))
                seq, left = 0, n
                while left:
                    data = self.rfile.read(min(proto.FILE_CHUNK_SIZE, left))
                    if not data:
                        break
                    s.send(proto.FILE_CHUNK, proto.encode_file_chunk_payload(dest, seq, data), log=False)
                    seq, left = seq + 1, left - len(data)
                s.emit(kind="frame", dir="out", type="FILE_CHUNK", sender=s.my_id,
                       length=proto.FILE_CHUNK_SIZE, checksum="....", count=seq)
                s.send(proto.FILE_END, proto.encode_file_end_payload(dest, name))
            elif u.path == "/api/leave":
                s.sock.close()
                SESSIONS.pop(q["sid"][0], None)
            self._json({"ok": True})
        except (OSError, KeyError, ValueError) as exc:
            self._json({"error": str(exc)}, 400)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"[gateway] open http://127.0.0.1:{port}  (chat server must be running)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
