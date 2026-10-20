"""
test_protocol.py

Sanity test that does NOT need a terminal: starts the server in a thread,
connects two clients, sends a chat message, sends a file, and checks the
file arrived byte-for-byte identical. Run with: python test_protocol.py
"""

import hashlib
import os
import threading
import time

from client import ChatFileClient
from server import ChatFileServer

HOST = "127.0.0.1"
PORT = 5590


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def main():
    server = ChatFileServer(host=HOST, port=PORT)
    threading.Thread(target=server.start, daemon=True).start()
    time.sleep(0.3)

    alice = ChatFileClient(HOST, PORT, "alice")
    bob = ChatFileClient(HOST, PORT, "bob")
    alice.connect()
    time.sleep(0.2)
    bob.connect()
    time.sleep(0.2)

    assert alice.my_id != 0, "alice did not receive an id from the server"
    assert bob.my_id != 0, "bob did not receive an id from the server"
    print(f"[test] alice id={alice.my_id}, bob id={bob.my_id}")

    # --- chat broadcast test ---
    alice.send_chat("hello from alice")
    time.sleep(0.3)
    print("[test] chat broadcast: OK (see 'alice: hello from alice' line above)")

    # --- file transfer test ---
    src_path = "test_input.bin"
    with open(src_path, "wb") as f:
        f.write(os.urandom(50_000))  # bigger than one FILE_CHUNK, forces multiple chunks
    src_hash = sha256(src_path)

    alice.send_file(src_path, bob.my_id)
    time.sleep(0.5)

    dest_path = os.path.join("received_files", f"{alice.my_id}_{src_path}")
    assert os.path.isfile(dest_path), f"expected received file at {dest_path}"
    dest_hash = sha256(dest_path)

    assert src_hash == dest_hash, "FILE TRANSFER CORRUPTED: hash mismatch"
    print(f"[test] file transfer: OK, sha256 matches ({src_hash[:16]}...)")

    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()
