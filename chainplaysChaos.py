import time, threading, json, queue
from web3 import Web3
from web3._utils.events import get_event_data
from pyboy import PyBoy

# ---- hardcoded config ----
RPC_WSS        = "wss://jsonrpcws-mezo.boar.network"
CONTRACT_ADDR  = Web3.to_checksum_address("0x7c8A35C98Bf46a67324Af3F54aD027DBE2138E98")
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

# ---- queue (thread-safe) ----
actions_q: "queue.Queue[str]" = queue.Queue()

def make_web3_provider(rpc_url: str):
    if hasattr(Web3, "WebSocketProvider"):
        return Web3(Web3.WebSocketProvider(rpc_url))
    elif hasattr(Web3, "LegacyWebSocketProvider"):
        return Web3(Web3.LegacyWebSocketProvider(rpc_url))
    else:
        http_url = rpc_url.replace("wss://", "https://").replace("ws://", "http://")
        return Web3(Web3.HTTPProvider(http_url))

def chain_listener(w3: Web3, event_topic0: str):
    """Every Move event → immediate button enqueue (chaos)."""
    last_block = w3.eth.block_number
    print("Listening for Move events (CHAOS MODE)…")
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
                    btn = CMD_INDEX_TO_BUTTON.get(cmd)
                    if btn:
                        actions_q.put(btn)
                        print(f"[CHAOS VOTE] {sender} -> {btn} ({memo})")
                last_block = latest + 1
            time.sleep(0.5)  # faster polling
        except Exception as e:
            print("Listener loop error:", e)
            time.sleep(1.0)

def main():
    # ---- web3 setup ----
    w3 = make_web3_provider(RPC_WSS)
    if not w3.is_connected():
        raise RuntimeError("RPC connect failed")

    # topic0 for Move event
    topic0 = w3.keccak(text="Move(address,uint8,uint256,string)").hex()
    if not topic0.startswith("0x"):
        topic0 = "0x" + topic0
    topic0 = topic0.lower()

    # start listener
    threading.Thread(target=chain_listener, args=(w3, topic0), daemon=True).start()

    if PRINT_ONLY:
        print("PRINT_ONLY chaos mode.")
        while True:
            try:
                btn = actions_q.get(timeout=0.1)
                print(f"[APPLY] {btn}")
            except queue.Empty:
                pass
            time.sleep(0.01)
    else:
        # PyBoy must run on main thread
        pyboy = PyBoy("roms/pokemon.gb", window="SDL2")
        try:
            pyboy.set_window_scale(3)
        except Exception:
            pass

        # Boot a little
        for _ in range(240):
            pyboy.tick()

        while True:
            try:
                btn = actions_q.get_nowait()
                # quick tap = pure chaos
                pyboy.button(btn, True)
                pyboy.tick()
                pyboy.button(btn, False)
                print(f"[APPLY] {btn}")
            except queue.Empty:
                pyboy.tick()

            time.sleep(0.002)  # tight loop

if __name__ == "__main__":
    main()