"""
server.py

The "Chat and Transfer Server" from the SYSTEM DESIGN slide. It plays three
roles, each corresponding to one box in that diagram:

  Connection Manager  -- accept(), assign client ids, track sockets, clean
                          up on disconnect. One thread per client (the
                          "concurrent server core" from the OUR APPROACH slide).
  Broadcast Module     -- relays CHAT frames to every connected client.
  File Relay Module    -- relays FILE_META / FILE_CHUNK / FILE_END frames
                          from a sending client to the destination client
                          named in the payload. The server does not need to
                          buffer whole files: it forwards each chunk frame
                          as it arrives, so memory use stays flat regardless
                          of file size.

Server id 0 is reserved for frames the server itself originates (ACK/ERROR).
"""

import socket
import threading

import protocol as proto

HOST = "0.0.0.0"
PORT = 5555
SERVER_ID = 0


class ClientHandle:
    def __init__(self, client_id: int, sock: socket.socket, addr):
        self.id = client_id
        self.sock = sock
        self.addr = addr
        self.username = f"user{client_id}"
        self.lock = threading.Lock()  # serializes writes from other threads

    def send(self, msg_type: int, sender_id: int, payload: bytes = b""):
        with self.lock:
            proto.send_message(self.sock, msg_type, sender_id, payload)


class ChatFileServer:
    def __init__(self, host: str = HOST, port: int = PORT):
        self.host = host
        self.port = port
        self.clients: dict[int, ClientHandle] = {}
        self.clients_lock = threading.Lock()
        self._next_id = 1
        self._server_sock = None

    # -- Connection Manager --------------------------------------------------

    def start(self):
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen()
        print(f"[server] listening on {self.host}:{self.port}")
        try:
            while True:
                sock, addr = self._server_sock.accept()
                client_id = self._allocate_id()
                handle = ClientHandle(client_id, sock, addr)
                with self.clients_lock:
                    self.clients[client_id] = handle
                threading.Thread(
                    target=self._client_thread, args=(handle,), daemon=True
                ).start()
        except KeyboardInterrupt:
            print("\n[server] shutting down")
        finally:
            self._server_sock.close()

    def _allocate_id(self) -> int:
        with self.clients_lock:
            cid = self._next_id
            self._next_id += 1
            return cid

    def _client_thread(self, handle: ClientHandle):
        print(f"[server] client {handle.id} connected from {handle.addr}")
        try:
            self._serve(handle)
        except (ConnectionError, proto.ProtocolError) as exc:
            print(f"[server] client {handle.id} disconnected: {exc}")
        finally:
            self._remove_client(handle)

    def _remove_client(self, handle: ClientHandle):
        with self.clients_lock:
            self.clients.pop(handle.id, None)
        handle.sock.close()
        self._broadcast_system(f"{handle.username} left the chat", exclude=handle.id)

    # -- Per-client message loop ---------------------------------------------

    def _serve(self, handle: ClientHandle):
        while True:
            msg_type, sender_id, payload = proto.read_message(handle.sock)

            if msg_type == proto.JOIN:
                self._handle_join(handle, payload)

            elif msg_type == proto.CHAT:
                self._handle_chat(handle, payload)

            elif msg_type in (proto.FILE_META, proto.FILE_CHUNK, proto.FILE_END):
                self._relay_file_frame(handle, msg_type, payload)

            else:
                handle.send(proto.ERROR, SERVER_ID,
                            proto.encode_error_payload("unknown message type"))

    # -- JOIN handling --------------------------------------------------------

    def _handle_join(self, handle: ClientHandle, payload: bytes):
        username = proto.decode_join_payload(payload)
        handle.username = username
        handle.send(proto.ACK, SERVER_ID,
                    proto.encode_error_payload(f"joined as {username} (id={handle.id})"))
        self._broadcast_system(f"{username} joined the chat", exclude=handle.id)
        print(f"[server] client {handle.id} registered as '{username}'")

    # -- Broadcast Module -----------------------------------------------------

    def _handle_chat(self, handle: ClientHandle, payload: bytes):
        text = proto.decode_chat_payload(payload)
        full_text = f"{handle.username}: {text}"
        print(f"[server] chat << {full_text}")
        with self.clients_lock:
            targets = [c for cid, c in self.clients.items() if cid != handle.id]
        for target in targets:
            try:
                target.send(proto.CHAT, handle.id, proto.encode_chat_payload(full_text))
            except OSError:
                pass  # target dropped mid-broadcast; its own thread will clean it up

    def _broadcast_system(self, text: str, exclude: int = -1):
        with self.clients_lock:
            targets = [c for cid, c in self.clients.items() if cid != exclude]
        for target in targets:
            try:
                target.send(proto.CHAT, SERVER_ID, proto.encode_chat_payload(f"* {text}"))
            except OSError:
                pass

    # -- File Relay Module ------------------------------------------------------

    def _relay_file_frame(self, handle: ClientHandle, msg_type: int, payload: bytes):
        if msg_type == proto.FILE_META:
            filename, filesize, dest_id = proto.decode_file_meta_payload(payload)
            print(f"[server] {handle.username} -> client {dest_id}: "
                  f"FILE_META {filename} ({filesize} bytes)")
        elif msg_type == proto.FILE_CHUNK:
            dest_id, _seq, _data = proto.decode_file_chunk_payload(payload)
        else:  # FILE_END
            dest_id, filename = proto.decode_file_end_payload(payload)
            print(f"[server] {handle.username} -> client {dest_id}: FILE_END {filename}")

        with self.clients_lock:
            target = self.clients.get(dest_id)
        if target is None:
            handle.send(proto.ERROR, SERVER_ID,
                        proto.encode_error_payload(f"destination client {dest_id} not connected"))
            return
        try:
            target.send(msg_type, handle.id, payload)
        except OSError:
            handle.send(proto.ERROR, SERVER_ID,
                        proto.encode_error_payload(f"failed to relay to client {dest_id}"))


if __name__ == "__main__":
    ChatFileServer().start()
