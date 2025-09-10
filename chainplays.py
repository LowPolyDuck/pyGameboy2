import time, threading, json, collections, queue
from web3 import Web3
from web3._utils.events import get_event_data
from pyboy import PyBoy

# ---- hardcoded config ----
RPC_WSS        = "wss://jsonrpcws-mezo.boar.network"  # or your Alchemy/Infura WSS
CONTRACT_ADDR  = Web3.to_checksum_address("0x7c8A35C98Bf46a67324Af3F54aD027DBE2138E98")
DEMOCRACY_MS   = 3000        # vote window (ms)
PRINT_ONLY     = False       # True = don't open emulator, just print

# ---- ABI (only the event is needed) ----
ABI = json.loads(r"""
[{
  "anonymous": false,
  "inputs": [
    {"indexed": true, "internalType":"address","name":"sender","type":"address"},
    {"indexed": false,"internalType":"enum ChainPlays.Cmd","name":"cmd","type":"uint8"},
    {"indexed": false,"internalType":"uint256","name":"weight","type":"uint256"},
    {"indexed": false,"internalType":"string","name":"memo","type":"string"}
  ],
  "name": "Move",
  "type": "event"
}]
""")

# ---- key mapping for PyBoy (Game Boy) ----
CMD_INDEX_TO_BUTTON = {
    0: "up",
    1: "down",
    2: "left",
    3: "right",
    4: "a",
    5: "b",
    6: "start",
    7: "select",
}

# ---- tallies and action queue (thread-safe) ----
tally_lock = threading.Lock()
tally = collections.Counter()
actions_q: "queue.Queue[str]" = queue.Queue()  # main thread will consume button names

def make_web3_provider(rpc_url: str):
    """Try WebSocketProvider first, then LegacyWebSocketProvider, then HTTPProvider."""
    if hasattr(Web3, "WebSocketProvider"):
        return Web3(Web3.WebSocketProvider(rpc_url))
    elif hasattr(Web3, "LegacyWebSocketProvider"):
        return Web3(Web3.LegacyWebSocketProvider(rpc_url))
    else:
        http_url = rpc_url.replace("wss://", "https://").replace("ws://", "http://")
        return Web3(Web3.HTTPProvider(http_url))

def vote_aggregator(interval_ms: int):
    """Runs off the main thread. Only computes winning vote and enqueues the button."""
    while True:
        time.sleep(interval_ms / 1000.0)
        with tally_lock:
            if not tally:
                continue
            cmd_idx, _ = tally.most_common(1)[0]
            tally.clear()
        btn = CMD_INDEX_TO_BUTTON.get(cmd_idx)
        if btn:
            actions_q.put(btn)

def chain_listener(w3: Web3, event_topic0: str):
    """Runs off the main thread. Only updates the tally; never touches PyBoy."""
    last_block = w3.eth.block_number
    print("Listening for Move events…")
    while True:
        try:
            latest = w3.eth.block_number
            if latest >= last_block:
                logs = w3.eth.get_logs({
                    "address": CONTRACT_ADDR,
                    "topics": [event_topic0],
                    "fromBlock": last_block,
                    "toBlock": latest
                })
                for log in logs:
                    evt = get_event_data(w3.codec, ABI[0], log)
                    cmd = int(evt["args"]["cmd"])
                    sender = evt["args"]["sender"]
                    memo = evt["args"]["memo"]
                    with tally_lock:
                        tally[cmd] += 1
                    print(f"[VOTE] {sender} -> {CMD_INDEX_TO_BUTTON.get(cmd, '?')} ({memo})")
                last_block = latest + 1
            time.sleep(1.0)
        except Exception as e:
            print("Listener loop error:", e)
            time.sleep(2.0)

def main():
    # ---- web3 setup (off-UI) ----
    w3 = make_web3_provider(RPC_WSS)
    if not w3.is_connected():
        raise RuntimeError("RPC connect failed")

    # Build the event topic0 with a guaranteed 0x prefix
    topic0 = w3.keccak(text="Move(address,uint8,uint256,string)").hex()
    if not topic0.startswith("0x"):
        topic0 = "0x" + topic0
    topic0 = topic0.lower()

    # ---- start background workers (no UI work here) ----
    threading.Thread(target=vote_aggregator, args=(DEMOCRACY_MS,), daemon=True).start()
    threading.Thread(target=chain_listener, args=(w3, topic0), daemon=True).start()

    # ---- main thread: emulator loop & input application ----
    if PRINT_ONLY:
        print("PRINT_ONLY mode. No emulator window will open.")
        while True:
            try:
                btn = actions_q.get(timeout=0.1)
                print(f"[APPLY] {btn}")
            except queue.Empty:
                pass
            time.sleep(0.01)
    else:
        # PyBoy must live on the main thread on macOS when using SDL2
        pyboy = PyBoy("roms/pokemon.gb", window="SDL2")
        try:
            pyboy.set_window_scale(3)
        except Exception:
            pass

        # Let the game boot a bit
        for _ in range(240):
            pyboy.tick()

        # Main emulation loop ~60 FPS; apply queued actions when present
        last_apply_print = 0.0
        while True:
            try:
                btn = actions_q.get_nowait()
                # Hold the button for a few frames so it registers well
                pyboy.button(btn, True)
                for _ in range(6):
                    pyboy.tick()
                pyboy.button(btn, False)
                for _ in range(2):
                    pyboy.tick()
                # Throttle stdout a bit
                now = time.time()
                if now - last_apply_print > 0.05:
                    print(f"[APPLY] {btn}")
                    last_apply_print = now
            except queue.Empty:
                # No action; just tick one frame
                pyboy.tick()

            time.sleep(0.005)  # tune as desired; 0 for max speed

if __name__ == "__main__":
    main()