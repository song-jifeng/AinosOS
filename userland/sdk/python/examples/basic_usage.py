"""Basic usage example for the Ainos Python SDK.

Prerequisites:
    - The Ainos AI Daemon must be running (listening on 127.0.0.1:9500).
    - The ainos-sdk package must be installed (``pip install .``).

Run this script::

    python examples/basic_usage.py
"""

import time
from ainos import AinosClient, AinosConnectionError, AinosError


def main() -> None:
    print("=" * 60)
    print("Ainos AI Daemon - Python SDK Example")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Connect to the daemon
    # ------------------------------------------------------------------
    print("\n[1] Connecting to daemon at 127.0.0.1:9500 ...")

    try:
        client = AinosClient(
            host="127.0.0.1",
            port=9500,
            connect_timeout=5.0,
            read_timeout=30.0,
        )
        client.connect()
    except AinosConnectionError as e:
        print(f"  ERROR: {e}")
        print("  Make sure the Ainos AI Daemon is running.")
        return

    print("  Connected.")

    # ------------------------------------------------------------------
    # 2. System status
    # ------------------------------------------------------------------
    print("\n[2] Querying daemon status ...")

    try:
        status = client.status()
        print(f"  Uptime:             {status.uptime} seconds")
        print(f"  Models loaded:      {status.models_loaded}")
        print(f"  Total requests:     {status.total_requests}")
        print(f"  Network available:  {status.network_available}")
    except AinosError as e:
        print(f"  ERROR: {e}")

    # ------------------------------------------------------------------
    # 3. List models
    # ------------------------------------------------------------------
    print("\n[3] Listing available models ...")

    try:
        models = client.model_list()
        if models:
            print(f"  Found {len(models)} model(s):")
            for m in models:
                loaded = "LOADED" if m.loaded else "unloaded"
                print(f"    - {m.name} ({m.size_mb} MB) [{loaded}]")
                print(f"      id: {m.id}, arch: {m.architecture}")
        else:
            print("  No models registered.")
    except AinosError as e:
        print(f"  ERROR: {e}")

    # ------------------------------------------------------------------
    # 4. Inference
    # ------------------------------------------------------------------
    print("\n[4] Running inference ...")

    prompts = [
        "Hello, Ainos!",
        "What can you do?",
    ]

    for prompt in prompts:
        print(f'\n  Prompt: "{prompt}"')
        try:
            resp = client.infer(
                prompt=prompt,
                model="default",
                temperature=0.7,
                max_tokens=256,
            )
            print(f"  Response: {resp.output}")
            print(f"  Tokens: {resp.tokens_generated}, "
                  f"Time: {resp.inference_ms}ms, "
                  f"Source: {resp.source}")
        except AinosError as e:
            print(f"  ERROR: {e}")

        time.sleep(0.5)

    # ------------------------------------------------------------------
    # 5. Context store
    # ------------------------------------------------------------------
    print("\n[5] Context store demo ...")

    try:
        client.context_store("user_name", "Alice")
        client.context_store("user_language", "Python")
        print("  Stored: user_name=Alice, user_language=Python")

        name = client.context_retrieve("user_name")
        lang = client.context_retrieve("user_language")
        missing = client.context_retrieve("nonexistent_key")

        print(f"  Retrieved: user_name={name}")
        print(f"  Retrieved: user_language={lang}")
        print(f"  Retrieved: nonexistent_key={missing}")
    except AinosError as e:
        print(f"  ERROR: {e}")

    # ------------------------------------------------------------------
    # 6. Disconnect
    # ------------------------------------------------------------------
    print("\n[6] Disconnecting ...")
    client.disconnect()
    print("  Disconnected.")

    # ------------------------------------------------------------------
    # 7. Context manager alternative
    # ------------------------------------------------------------------
    print("\n[7] Using context manager (equivalent to connect/disconnect):")

    with AinosClient() as cm_client:
        s = cm_client.status()
        print(f"  Status via context manager: uptime={s.uptime}s")

    print("  (auto-disconnected on exit)")

    print("\n" + "=" * 60)
    print("Example complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()