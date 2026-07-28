import os
import io
import re
import json
import time
import uuid
import threading
import contextlib
import traceback
import requests
from typing import List, Dict, Any
from datetime import datetime
from collections import defaultdict
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# --- Config & Setup ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
BASE_URL = os.environ.get("BASE_URL")  # Only needed for proxies like AIProxy
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8000").rstrip("/")

if not BOT_TOKEN or not LLM_API_KEY:
    print("WARNING: BOT_TOKEN and LLM_API_KEY must be set in the environment.")

# Initialize OpenAI client
client_kwargs = {"api_key": LLM_API_KEY}
if BASE_URL:
    client_kwargs["base_url"] = BASE_URL
# Handle AIPROXY token convention
if LLM_API_KEY.startswith("eyJ") and not BASE_URL:
    client_kwargs["base_url"] = "https://aiproxy.sanand.workers.dev/openai/v1"

client = OpenAI(**client_kwargs)

app = FastAPI()

# --- State & Logging ---
chat_histories: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
LOG_FILE = "run.jsonl"

def log_event(event: dict):
    event["timestamp"] = datetime.utcnow().isoformat()
    try:
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        print(f"Failed to log event: {e}")

# --- Tool Execution ---
def run_python(code: str) -> str:
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            # Run code in a fresh namespace
            exec(code, {})
        res = output.getvalue()
        if not res.strip():
            res = "Code executed successfully with no output."
        if len(res) > 8000:
            res = res[:4000] + "\n...[output truncated]...\n" + res[-4000:]
        return res
    except Exception as e:
        err = traceback.format_exc()
        if len(err) > 8000:
            err = err[:4000] + "\n...[error truncated]...\n" + err[-4000:]
        return f"Error executing code:\n{err}"

TOOLS = [{
    "type": "function",
    "function": {
        "name": "run_python",
        "description": "Execute Python code server-side to fetch and analyze datasets. Returns stdout. Environment has pandas, numpy, requests, bs4, openpyxl.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The Python code to execute."
                }
            },
            "required": ["code"]
        }
    }
}]

# --- Helper Functions ---
def extract_json(text: str) -> dict:
    text = re.sub(r'```(?:json)?', '', text).strip()
    match = re.search(r'(\{.*\})', text, re.DOTALL)
    
    parsed = None
    if match:
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
            
    if parsed is None:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"answer": text}
            
    if isinstance(parsed, dict) and "answer" not in parsed:
        # Wrap it if missing answer key, though questions usually specify the format
        parsed = {"answer": parsed}
    elif not isinstance(parsed, dict):
        parsed = {"answer": parsed}
        
    return parsed

def process_message(chat_id: int, user_text: str):
    history = chat_histories[chat_id]
    
    # Prune history to keep only last ~20 messages to save context limit
    if len(history) > 20:
        history = history[-20:]
        
    history.append({"role": "user", "content": user_text})
    
    start_time = time.time()
    max_duration = 210  # Seconds budget
    max_steps = 10
    
    system_prompt = {
        "role": "system", 
        "content": (
            "You are a data analyst agent. You will answer questions by analyzing datasets.\n"
            "You can use the 'run_python' tool to execute Python code to download data and perform analysis.\n"
            "You have access to pandas, numpy, requests, bs4, and openpyxl.\n"
            "You must reply to the LATEST message. Earlier messages are context.\n"
            "Use run_python to fetch/compute. Never guess a number it can compute. For published statistics where fetching fails, answer from knowledge.\n"
            "Output ONLY the JSON object the question asks for. No prose, no markdown fences.\n"
            "Use \"LOG_URL_PLACEHOLDER\" for the log_url key.\n"
            "Match the requested answer shape exactly. Do not add extra keys to the answer.\n"
            "If a mid-conversation message is only setup ('I'll send data next'), still reply with a small JSON ack (e.g. {\"answer\": \"acknowledged\", \"log_url\": \"LOG_URL_PLACEHOLDER\"}).\n"
        )
    }
    
    messages = [system_prompt] + history
    log_run = {"chat_id": chat_id, "question": user_text, "steps": []}
    
    for step in range(max_steps):
        elapsed = time.time() - start_time
        if elapsed > max_duration:
            messages.append({"role": "system", "content": "Time limit exceeded. You must answer immediately with the best JSON answer you have."})
            # Remove tools to force completion
            tools_param = None
        else:
            tools_param = TOOLS
            
        try:
            response = client.chat.completions.create(
                model=os.environ.get("LLM_MODEL", "gpt-4o"),
                messages=messages,
                tools=tools_param,
                temperature=0.0
            )
        except Exception as e:
            # Try falling back
            try:
                response = client.chat.completions.create(
                    model=os.environ.get("LLM_FALLBACK_MODEL", "gpt-4o-mini"),
                    messages=messages,
                    tools=tools_param,
                    temperature=0.0
                )
            except Exception as e2:
                print(f"LLM API Error: {e2}")
                err_msg = {"answer": f"API Error: {str(e2)}", "log_url": f"{PUBLIC_URL}/run.jsonl"}
                send_telegram_message(chat_id, json.dumps(err_msg))
                return

        msg = response.choices[0].message
        
        if msg.tool_calls:
            messages.append(msg)
            for tool_call in msg.tool_calls:
                if tool_call.function.name == "run_python":
                    args = tool_call.function.arguments
                    try:
                        parsed_args = json.loads(args)
                        code = parsed_args.get("code", "")
                    except:
                        code = ""
                        
                    result = run_python(code)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "content": result
                    })
                    
                    log_run["steps"].append({"code": code, "result": result})
        else:
            # Final text response
            final_text = msg.content
            messages.append({"role": "assistant", "content": final_text})
            history.append({"role": "assistant", "content": final_text})
            
            parsed_json = extract_json(final_text)
            parsed_json["log_url"] = f"{PUBLIC_URL}/run.jsonl"
            
            final_output = json.dumps(parsed_json)
            log_run["final_reply"] = final_output
            log_event(log_run)
            
            send_telegram_message(chat_id, final_output)
            return
            
    # If we exit loop without returning, force answer
    parsed_json = {"answer": "timeout or max steps reached", "log_url": f"{PUBLIC_URL}/run.jsonl"}
    final_output = json.dumps(parsed_json)
    log_run["final_reply"] = final_output
    log_event(log_run)
    send_telegram_message(chat_id, final_output)


def send_telegram_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Failed to send message: {e}")

# --- Background Threads ---
def telegram_poller():
    offset = 0
    while True:
        if not BOT_TOKEN:
            time.sleep(5)
            continue
            
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        try:
            params = {"offset": offset, "timeout": 30}
            resp = requests.get(url, params=params, timeout=40)
            if resp.status_code == 200:
                data = resp.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    if "message" in update and "text" in update["message"]:
                        chat_id = update["message"]["chat"]["id"]
                        text = update["message"]["text"]
                        
                        # Process each message in a separate thread so it doesn't block others
                        threading.Thread(target=process_message, args=(chat_id, text)).start()
        except Exception as e:
            print(f"Poller error: {e}")
            time.sleep(5)

def keep_warm_pinger():
    while True:
        time.sleep(600)  # Every 10 mins
        try:
            # Self-ping
            requests.get(f"{PUBLIC_URL}/health", timeout=10)
        except:
            pass

# Start threads
threading.Thread(target=telegram_poller, daemon=True).start()
threading.Thread(target=keep_warm_pinger, daemon=True).start()


# --- API Routes ---
@app.get("/health")
def health_check():
    return JSONResponse({"ok": True, "status": "running"})

@app.get("/run.jsonl")
def get_log():
    if not os.path.exists(LOG_FILE):
        return JSONResponse({"error": "No logs yet"}, status_code=404)
    return FileResponse(LOG_FILE, media_type="application/jsonl")

if __name__ == "__main__":
    import uvicorn
    # Optional: read PORT from env if deploying to Render etc.
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
