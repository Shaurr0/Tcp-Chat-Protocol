# Custom TCP-Based Protocol — Implementation (core ~60%)

This implements the protocol described in the slides: one custom
application-layer message format, carried over a single persistent TCP
socket per client, unifying chat and file transfer.

## Files

- `protocol.py` — the wire format: 9-byte header (type, sender id, payload
  length), variable payload, 2-byte checksum trailer. All seven message
  types from the PROTOCOL DESIGN slide (`JOIN`, `CHAT`, `FILE_META`,
  `FILE_CHUNK`, `FILE_END`, `ACK`, `ERROR`), plus the pack/unpack helpers
  for each payload shape.
- `server.py` — the Connection Manager, Broadcast Module, and File Relay
  Module from the SYSTEM DESIGN slide. Thread-per-client concurrency;
  assigns each client an id on JOIN; broadcasts CHAT frames to everyone
  else; relays FILE_META/FILE_CHUNK/FILE_END frames to whichever client id
  the sender named, without buffering the whole file in memory.
- `client.py` — connects, sends JOIN, then runs a receiver thread (prints
  chat, writes incoming file chunks to `received_files/`) alongside a
  command loop for typing chat lines or `/sendfile <path> <dest_id>`.
- `test_protocol.py` — starts the server and two in-process clients, sends
  a chat message, sends a 50 KB file, and checks the received file's
  SHA-256 matches the original — confirms chunking/reassembly is
  byte-exact.

## Running it

Terminal 1:
```
python3 server.py
```

Terminal 2 and 3 (one per client):
```
python3 client.py 127.0.0.1 5555 alice
python3 client.py 127.0.0.1 5555 bob
```

At a client's `>` prompt: type a line to chat, or
`/sendfile path/to/file.txt 2` to send a file to client id 2 (the id each
client was assigned is echoed back in the server's ACK on join).

Or just run the automated check:
```
python3 test_protocol.py
```

## What this covers vs. what's left

This is the core protocol and its two services — framing, checksums,
concurrent multi-client handling, chat broadcast, and chunked file relay —
which is the part the slides treat as the actual contribution. Deliberately
left out, as the "path to higher TRL" slide itself frames as future work:

- Encryption / authentication (the slides note security is "added as an
  afterthought" in prior work and call it out separately from this core)
- A GUI (the client here is CLI-only)
- Persistence/logging of chat history or transfer records
- Resuming an interrupted file transfer, or flow control beyond what TCP
  already provides
- WAN-scale testing and load testing past a handful of concurrent clients

Extending the `Type` field with new message values (e.g. `PRIVATE_MSG`, an
encrypted variant of `FILE_CHUNK`) doesn't require touching the framing or
connection logic — that extensibility is by design, matching the
"extensible design" point on the OUR APPROACH slide.
