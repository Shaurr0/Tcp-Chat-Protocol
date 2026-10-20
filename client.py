"""
client.py

Command-line client for the custom protocol. Each client opens ONE
persistent TCP socket to the server and uses it for both chat and file
traffic, per the "single connection model" from the BACKGROUND slide.

Two threads:
  - a receiver thread that continuously reads frames and reacts to them
    (print chat text, write incoming file chunks to disk)
  - the main thread, which reads commands from the terminal and sends them

Commands typed at the prompt:
  <text>                          send a chat message to everyone
  /sendfile <path> <dest_id>      send a file to another client id
  /quit                           disconnect
"""

import os
import socket
import sys
import threading

import protocol as proto

DOWNLOAD_DIR = "received_files"


class ChatFileClient:
    def __init__(self, host: str, port: int, username: str):
        self.host = host
        self.port = port
        self.username = username
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.my_id = 0  # server assigns the real id via the ACK on JOIN
        self.send_lock = threading.Lock()
        self._incoming_files = {}  # (peer_id, filename) -> open file handle
        self._running = True

    def send(self, msg_type: int, payload: bytes = b""):
        with self.send_lock:
            proto.send_message(self.sock, msg_type, self.my_id, payload)

    # -- setup -----------------------------------------------------------

    def connect(self):
        self.sock.connect((self.host, self.port))
        self.send(proto.JOIN, proto.encode_join_payload(self.username))
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        threading.Thread(target=self._receive_loop, daemon=True).start()

    # -- receiving ---------------------------------------------------------

    def _receive_loop(self):
        try:
            while self._running:
                msg_type, sender_id, payload = proto.read_message(self.sock)
                self._dispatch(msg_type, sender_id, payload)
        except (ConnectionError, proto.ProtocolError) as exc:
            print(f"\n[client] disconnected: {exc}")
            self._running = False

    def _dispatch(self, msg_type: int, sender_id: int, payload: bytes):
        if msg_type == proto.CHAT:
            print(f"\n{proto.decode_chat_payload(payload)}\n> ", end="", flush=True)

        elif msg_type == proto.ACK:
            note = proto.decode_error_payload(payload)
            print(f"\n[server ACK] {note}\n> ", end="", flush=True)
            # Server encodes our assigned id in the ACK text as "id=<n>";
            # a real deployment would use a dedicated field instead.
            if self.my_id == 0 and "id=" in note:
                try:
                    self.my_id = int(note.rsplit("id=", 1)[1].rstrip(")"))
                except ValueError:
                    pass

        elif msg_type == proto.ERROR:
            print(f"\n[server ERROR] {proto.decode_error_payload(payload)}\n> ",
                  end="", flush=True)

        elif msg_type == proto.FILE_META:
            filename, filesize, _dest_id = proto.decode_file_meta_payload(payload)
            path = os.path.join(DOWNLOAD_DIR, f"{sender_id}_{filename}")
            self._incoming_files[(sender_id, filename)] = open(path, "wb")
            print(f"\n[file] receiving '{filename}' ({filesize} bytes) "
                  f"from client {sender_id}\n> ", end="", flush=True)

        elif msg_type == proto.FILE_CHUNK:
            _dest_id, seq_num, data = proto.decode_file_chunk_payload(payload)
            fh = self._find_open_file(sender_id)
            if fh:
                fh.write(data)

        elif msg_type == proto.FILE_END:
            _dest_id, filename = proto.decode_file_end_payload(payload)
            key = (sender_id, filename)
            fh = self._incoming_files.pop(key, None)
            if fh:
                fh.close()
                print(f"\n[file] '{filename}' from client {sender_id} complete "
                      f"-> {DOWNLOAD_DIR}/{sender_id}_{filename}\n> ", end="", flush=True)

    def _find_open_file(self, peer_id: int):
        for (pid, _name), fh in self._incoming_files.items():
            if pid == peer_id:
                return fh
        return None

    # -- sending -------------------------------------------------------------

    def send_chat(self, text: str):
        self.send(proto.CHAT, proto.encode_chat_payload(text))

    def send_file(self, path: str, dest_id: int):
        if not os.path.isfile(path):
            print(f"[client] no such file: {path}")
            return
        filesize = os.path.getsize(path)
        filename = os.path.basename(path)

        self.send(proto.FILE_META, proto.encode_file_meta_payload(filename, filesize, dest_id))

        with open(path, "rb") as f:
            seq = 0
            while True:
                chunk = f.read(proto.FILE_CHUNK_SIZE)
                if not chunk:
                    break
                self.send(proto.FILE_CHUNK, proto.encode_file_chunk_payload(dest_id, seq, chunk))
                seq += 1

        self.send(proto.FILE_END, proto.encode_file_end_payload(dest_id, filename))
        print(f"[client] sent '{filename}' ({filesize} bytes, {seq} chunks) to client {dest_id}")

    # -- command loop ----------------------------------------------------------

    def run(self):
        self.connect()
        print("Connected. Type a message and press Enter, or use /sendfile <path> <dest_id>, "
              "or /quit.")
        while self._running:
            try:
                line = input("> ")
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line == "/quit":
                break
            if line.startswith("/sendfile "):
                parts = line.split()
                if len(parts) != 3:
                    print("usage: /sendfile <path> <dest_client_id>")
                    continue
                _, path, dest_id_str = parts
                try:
                    self.send_file(path, int(dest_id_str))
                except OSError as exc:
                    print(f"[client] error sending file: {exc}")
            else:
                self.send_chat(line)
        self.sock.close()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("usage: python client.py <server_host> <port> <username>")
        sys.exit(1)
    host, port, username = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    ChatFileClient(host, port, username).run()
