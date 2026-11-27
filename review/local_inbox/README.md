# Local pickup inbox

Send a fictional shopper email, see how it was interpreted, and inspect the carrier checks behind the reply. The model runs on your computer. The carrier records, bookings and notifications use the agent's test fixtures.

## Start the inbox

Use Python 3.9 or later. Install [Ollama](https://ollama.com/download), start it, and download the model once with `ollama pull qwen2.5:1.5b`. The inbox connects to Ollama on its default local port, 11434.

From the repository root:

```sh
python3 -m pip install -r requirements.txt
python3 review/local_inbox/serve.py
```

On Windows use `py -3` in place of `python3`. Open [the local inbox](http://127.0.0.1:8766/) and leave the terminal open. If port 8766 is occupied, pass `--port 8767` and open the address printed in the terminal.

## Try a conversation

1. Leave **Carrier recorded a missed pickup** selected. Click **Use example email**, then **Send email**. A model interpretation and the carrier checks appear alongside the shopper's message.
2. Click **Choose Thursday**, then **Send email**. The replacement is booked with the simulated carrier.
3. Click **New case**, choose **Carrier marked the shopper unavailable**, and submit the original example again. Support receives the conflicting accounts.

Clear messages can match a rule directly. If Ollama is unavailable, the inbox identifies the unavailable model when a message needs interpretation. Refresh the page to start a fresh conversation. Stop the server with Ctrl+C.
