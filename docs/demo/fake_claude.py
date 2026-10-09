#!/usr/bin/env python3
"""A stand-in for the `claude` program, for the demo recording (make_demo.py).
The server runs it (LTT_CLAUDE) instead of the real Claude Code, so nothing
real is ever called or messaged. It answers only what the demo needs:

  claude agents --json --all     the made-up background agents (a JSON file)
  claude -p ... "Deliver ..."    the note relay: pretends to deliver each
                                 message with SendMessage, after a short wait
                                 so the arrow shows its sending animation

Anything else exits with an error. Settings come from environment variables
that make_demo.py sets: LTT_DEMO_AGENTS (the agents file) and LTT_DEMO_DELAY
(a file holding the relay's wait in seconds).
"""
import json
import os
import re
import sys
import time


def main(argv):
    if argv[:1] == ["agents"]:
        with open(os.environ["LTT_DEMO_AGENTS"], encoding="utf-8") as f:
            print(f.read())
        return 0
    if "-p" in argv and "--output-format" in argv and argv[argv.index("--output-format") + 1] == "stream-json":
        prompt = argv[-1]
        items = re.findall(r"^ITEM \d+\nTO: ([^\n]*)\nBEGIN\n(.*?)\nEND$", prompt, re.M | re.S)
        try:
            with open(os.environ["LTT_DEMO_DELAY"], encoding="utf-8") as f:
                time.sleep(float(f.read().strip() or 0))
        except (OSError, ValueError, KeyError):
            pass
        for i, (to, message) in enumerate(items, 1):
            call = {"type": "tool_use", "id": f"toolu_demo{i}", "name": "SendMessage",
                    "input": {"to": to, "message": message}}
            print(json.dumps({"type": "assistant", "message": {"content": [call]}}))
            result = {"type": "tool_result", "tool_use_id": call["id"],
                      "content": json.dumps({"success": True, "message": f"Message queued for {to}"})}
            print(json.dumps({"type": "user", "message": {"content": [result]}}))
        print(json.dumps({"type": "result", "result": "done", "total_cost_usd": 0.0004}))
        return 0
    print("fake claude: not part of the demo", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
