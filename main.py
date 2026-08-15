import json
import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse
from twilio.rest import Client

load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TARGET_NUMBER = os.getenv("TARGET_NUMBER")
PORT = int(os.getenv("PORT", 5050))

app = FastAPI()

@app.get("/")
async def health_check():
    return {"status": "ok"}

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

@app.api_route("/twiml", methods=["GET", "POST"])
async def twiml_handler(request: Request):
    """Twilio fetches this when the call connects."""
    host = request.url.hostname
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://{host}/media-stream" />
    </Connect>
</Response>"""
    return HTMLResponse(content=twiml, media_type="application/xml")

@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """Twilio opens this and streams call audio through it."""
    await websocket.accept()
    print(">>> Twilio connected to media stream")

    packet_count = 0
    try:
        async for message in websocket.iter_text():
            data = json.loads(message)
            event = data.get("event")

            if event == "start":
                print(f">>> Stream started: {data['start']['streamSid']}")
            elif event == "media":
                packet_count += 1
                if packet_count % 50 == 0:
                    print(f">>> Received {packet_count} audio packets")
            elif event == "stop":
                print(">>> Stream stopped")
    except Exception as e:
        print(f">>> Media stream error: {e}")
    finally:
        print(f">>> Call ended. Total packets: {packet_count}")

@app.post("/start-call")
async def start_call(request: Request):
    """Trigger an outbound call."""
    body = await request.json()
    public_url = body["public_url"]

    call = twilio_client.calls.create(
        to=TARGET_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url=f"{public_url}/twiml",
    )
    return {"call_sid": call.sid}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)