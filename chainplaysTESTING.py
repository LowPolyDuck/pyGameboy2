import time, threading, json, queue
from web3 import Web3
from web3._utils.events import get_event_data
from pyboy import PyBoy

# ---- config ----
RPC_WSS        = "wss://jsonrpcws-mezo.boar.network"
CONTRACT_ADDR  = Web3.to_checksum_address("0x7c8A35C98Bf46a67324Af3F54aD027DBE2138E98")
PRINT_ONLY     = False  # True = don't open emulator, just print

# ---- ABI (only the event is needed) ----
ABI = json.loads(r"""
[{
  "anonymous": false,
  "inputs": [
    {"indexed": true,  "internalType":"address","name":"sender","type":"address"},
    {"indexed": false, "internalType":"enum ChainPlays.Cmd","name":"cmd","type":"uint8"},
    {"indexed": false, "internalType":"uint256","name":"weight","type":"uint256"},
    {"indexed": false, "internalType":"string","name":"memo","type":"string"}
  ],
  "name": "Move",
  "type": "event"
}]
""")

# ---- mapping ----
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

# ---- queue ----
actions_q: "queue.Queue[str]" = queue.Queue()

def make_web3_provider(rpc_url: str):
    # use available WS provider, else HTTP
    if hasattr(Web3, "WebsocketProvider"):
        return Web3(Web3.WebsocketProvider(rpc_url))
    if hasattr(Web3, "WebSocketProvider"):
        return Web3(Web3.WebSocketProvider(rpc_url))
    if hasattr(Web3, "LegacyWebSocketProvider"):
        return Web3(Web3.LegacyWebSocketProvider(rpc_url))
    http_url = rpc_url.replace("wss://", "https://").replace("ws://", "http://")
    return Web3(Web3.HTTPProvider(http_url))

def chain_listener(w3: Web3, topic0: str):
    """Read logs and enqueue button strings. Nothing else."""
    last_block = w3.eth.block_number
    print("Listening for Move events… from block", last_block)
    while True:
        try:
            latest = w3.eth.block_number
            if latest >= last_block:
                logs = w3.eth.get_logs({
                    "address": CONTRACT_ADDR,
                    "topics":  [topic0],
                    "fromBlock": last_block,
                    "toBlock":   latest
                })
                for log in logs:
                    evt   = get_event_data(w3.codec, ABI[0], log)
                    cmd   = int(evt["args"]["cmd"])
                    btn   = CMD_INDEX_TO_BUTTON.get(cmd)
                    if btn:
                        actions_q.put(btn)
                        print(f"[VOTE] -> {btn}")
                last_block = latest + 1
            time.sleep(0.05)
        except Exception as e:
            print("Listener error:", e)
            time.sleep(0.6)

def main():
    # web3
    w3 = make_web3_provider(RPC_WSS)
    if not w3.is_connected():
        raise RuntimeError("RPC connect failed")

    # topic0 for Move(address,uint8,uint256,string)
    topic0 = Web3.to_hex(w3.keccak(text="Move(address,uint8,uint256,string)")).lower()

    # start listener
    threading.Thread(target=chain_listener, args=(w3, topic0), daemon=True).start()

    if PRINT_ONLY:
        print("PRINT_ONLY mode.")
        while True:
            try:
                btn = actions_q.get(timeout=0.1)
                print(f"[APPLY would] {btn}")
            except queue.Empty:
                pass
        return

    # PyBoy on main thread
    pyboy = PyBoy("roms/pokemon.gb", window="SDL2")
    try:
        pyboy.set_window_scale(3)
    except Exception:
        pass

    # boot a bit
    for _ in range(240):
        if pyboy.tick() is False:
            return

    # main loop: one press frame, one release frame. nothing else.
    while True:
        try:
            btn = actions_q.get_nowait()
            pyboy.button(btn, True)
            if pyboy.tick() is False:  # press frame
                return
            pyboy.button(btn, False)
            if pyboy.tick() is False:  # release frame
                return
            print(f"[APPLY] {btn}")
        except queue.Empty:
            if pyboy.tick() is False:
                return

if __name__ == "__main__":
    main()