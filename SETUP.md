# SETUP — Step by Step

## What you need

- A computer with Python 3.8 or newer installed (Windows, macOS, or Linux
  all work — no extra libraries are required, only the Python standard
  library).
- Three terminal / command-prompt windows (one server, two clients) — or
  two laptops on the same Wi-Fi if you want to demo across machines.

Check Python is installed:
```
python3 --version
```
(On Windows, this may be just `python --version`.)

## Step 1 — Unzip and enter the folder

Unzip this package, then open a terminal and move into the folder:
```
cd chat_protocol
```
You should see `protocol.py`, `server.py`, `client.py`, `test_protocol.py`,
`start_server.sh`, `README.md`, and `Execution_Demonstration_Report.docx`
in this folder. `client.py` and `server.py` both `import protocol`, so all
three `.py` files must stay in the same folder — don't move just one of
them elsewhere.

## Step 2 — Run the automated test first

Before doing a live demo, confirm everything works on your machine:
```
python3 test_protocol.py
```
This starts a server and two clients internally, sends a chat message and
a file between them, and checks the file arrived byte-for-byte identical.
You should see `ALL TESTS PASSED` at the end. If you see an error instead,
see Troubleshooting below before continuing.

## Step 3 — Start the server (Terminal 1)

```
python3 server.py
```
Leave this window open and running for the rest of the demo. You should see:
```
[server] listening on 0.0.0.0:5555
```
(On macOS, the first run may prompt for a firewall permission — click
"Allow".)

## Step 4 — Connect the first client (Terminal 2)

Open a second terminal, `cd` into the same folder, and run:
```
python3 client.py 127.0.0.1 5555 alice
```
`127.0.0.1` means "this same computer"; `5555` is the port the server is
listening on; `alice` is just a display name — use any name you like.
You should see the server terminal print `client 1 connected` and
`registered as 'alice'`, and your client terminal print
`[server ACK] joined as alice (id=1)`.

## Step 5 — Connect the second client (Terminal 3)

Open a third terminal, `cd` into the same folder, and run:
```
python3 client.py 127.0.0.1 5555 bob
```
Alice's terminal should now print `* bob joined the chat`.

## Step 6 — Send a chat message

In either client's terminal, just type a line of text and press Enter:
```
> hello from alice
```
It should appear in the other client's terminal as `alice: hello from alice`,
and in the server terminal as `[server] chat << alice: hello from alice`.

## Step 7 — Send a file

Put any file (for example, a short `.txt` file) into the `chat_protocol`
folder, then in alice's terminal:
```
> /sendfile myfile.txt 2
```
`2` is bob's client ID — each client's ID is shown in its own join ACK
message (alice is usually `1`, bob `2`, in the order they connected). You
should see progress on both sides, and the file will appear in a new
`received_files/` folder inside `chat_protocol`, named `1_myfile.txt`
(prefixed with the sender's ID).

## Step 8 — Disconnect

Type `/quit` in a client terminal to close that client. Press `Ctrl+C` in
the server terminal to stop the server.

## Running across two separate computers (optional)

If you want client A and client B on different laptops on the same
network instead of one machine:
1. On the machine running the server, find its local IP address
   (`ipconfig` on Windows, `ifconfig` or `ip addr` on macOS/Linux — look
   for something like `192.168.x.x`).
2. Run `python3 server.py` on that machine as before.
3. On each other laptop, run `python3 client.py <that IP> 5555 <name>`
   instead of `127.0.0.1`.
4. All machines must be on the same Wi-Fi/LAN, and the server machine's
   firewall must allow incoming connections on port 5555.

## Troubleshooting

- **`Address already in use`** when starting the server — a previous
  server is still running. Find and stop it, or edit `PORT = 5555` near
  the top of `server.py` and `client.py`'s command-line port argument to
  a different number, e.g. `5556`.
- **Client hangs on connect** — the server isn't running yet, or you typed
  the wrong IP/port. Start the server first (Step 3) before any client.
- **`ModuleNotFoundError: No module named 'protocol'`** — you're running
  the client or server from the wrong folder, or `protocol.py` got
  separated from the other files. `cd` back into `chat_protocol` and
  confirm all three `.py` files are together.
- **Firewall prompt** — allow Python to accept incoming network
  connections when your OS asks; otherwise clients on other machines
  won't be able to reach the server.

## What's in this package

| File | Purpose |
|---|---|
| `protocol.py` | The wire format: message types, header packing/parsing, checksum |
| `server.py` | Multi-client server: connection handling, chat broadcast, file relay |
| `client.py` | Command-line client: join, send/receive chat, send/receive files |
| `test_protocol.py` | Automated self-test (no manual typing needed) |
| `start_server.sh` | One-line launcher for the server (macOS/Linux) |
| `README.md` | Technical summary of what's implemented and what's left as future work |
| `Execution_Demonstration_Report.docx` | Write-up with a captured run and viva talking points, ready to submit or present |
