import argparse
import json
import os

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simule une réponse utilisateur vers POST /chat (événement Google Chat)."
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--space-id", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--token", default=os.getenv("START_ENDPOINT_TOKEN", "change-me"))
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    event = {
        "type": "MESSAGE",
        "space": {"name": args.space_id},
        "message": {"text": args.text},
    }
    with httpx.Client(timeout=30.0) as client:
        chat_resp = client.post(f"{base}/chat", json=event)
        chat_resp.raise_for_status()
        inspect = client.get(
            f"{base}/conversations",
            params={"space_id": args.space_id},
            headers={"Authorization": f"Bearer {args.token}"},
        )
        inspect.raise_for_status()
        state = inspect.json()

    last_agent = next(
        (turn["text"] for turn in reversed(state.get("history") or []) if turn.get("role") == "agent"),
        "",
    )
    print(json.dumps(
        {
            "status": state.get("status"),
            "current_field_id": state.get("current_field_id"),
            "answers": state.get("answers"),
            "last_agent_message": last_agent,
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
