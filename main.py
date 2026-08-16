import json
import os
import asyncio
import websockets
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

REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime-mini"
VOICE = "alloy"

SYSTEM_PROMPT = """You are Maria Reyes, a 34-year-old patient calling Pivot Point
Orthopedics. You hurt your right knee playing soccer two weekends ago and it's
still swollen. You want to book an appointment as soon as possible.

Your date of birth is March 12, 1992.

Speak naturally, like a real person on the phone. Use short sentences. Don't be
overly formal or polite — you're a normal person, slightly frustrated about the
knee. Don't volunteer all your information at once; answer what you're asked.

If the agent asks something you don't have an answer for, improvise plausibly.
Never mention that you are an AI. Never break character.


You are ONLY the patient. You are never the receptionist or scheduler. Do not
ask the other person for their date of birth, do not offer appointment times,
and do not confirm bookings — you are the one being scheduled, not the one
scheduling. If there is silence, wait. Do not fill it by inventing the other
side's dialogue. Keep each turn to one or two sentences, then stop and listen.

Always speak English, even if you hear other languages or IVR prompts.

Your goal is to book the appointment. Do not end the call while the agent is
still speaking or has asked you a question. Answer their question first. Only
say goodbye after the agent has finished and asked whether there's anything
else — then decline, thank them, and end the call.

Never agree to wait, hold, or check messages during the call. If asked to do
something outside the call, say you'll handle it later and return to booking
the appointment.

Listen to what is actually asked before answering. Do not say "yes, that's
correct" unless you were asked a yes/no question.

"""

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

async def connect_to_openai():
    """Open a WebSocket to the Realtime API and configure the session."""
    ws = await websockets.connect(
        REALTIME_URL,
        additional_headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
    )

    session_config = {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "instructions": SYSTEM_PROMPT,
            "audio": {
                "input": {
                    "format": {"type": "audio/pcmu"},
                    "transcription": {"model": "whisper-1"},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "silence_duration_ms": 1100,
                    },
                },
                "output": {
                    "format": {"type": "audio/pcmu"},
                    "voice": VOICE,
                },
            },
            "tools": [{
                "type": "function",
                "name": "end_call",
                "description": "End the phone call. Use this after saying goodbye, once the appointment is booked or it's clear the agent cannot help.",
                "parameters": {"type": "object", "properties": {}},
            }],    
        },
    }
    await ws.send(json.dumps(session_config))
    print(">>> Connected to OpenAI Realtime API")
    return ws

@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """Bridge audio between Twilio and OpenAI."""
    await websocket.accept()
    print(">>> Twilio connected to media stream")

    openai_ws = await connect_to_openai()
    stream_sid = None

    async def twilio_to_openai():
        """Forward caller audio from Twilio to OpenAI."""
        nonlocal stream_sid
        try:
            async for message in websocket.iter_text():
                data = json.loads(message)
                event = data.get("event")

                if event == "start":
                    stream_sid = data["start"]["streamSid"]
                    print(f">>> Stream started: {stream_sid}")
                elif event == "media":
                    await openai_ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": data["media"]["payload"],
                    }))
                elif event == "stop":
                    print(">>> Twilio stream stopped")
                    break
        except Exception as e:
            print(f">>> twilio_to_openai error: {e}")

    async def openai_to_twilio():
        """Forward generated audio from OpenAI back to Twilio."""
        try:
            async for message in openai_ws:
                event = json.loads(message)
                etype = event.get("type")

                if etype == "response.output_audio.delta" and stream_sid:
                    await websocket.send_json({
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": event["delta"]},
                    })
                elif etype == "response.output_audio_transcript.done":
                    print(f"[PATIENT] {event['transcript']}")
                elif etype == "conversation.item.input_audio_transcription.completed":
                    print(f"[AGENT]   {event['transcript']}")
                elif etype == "error":
                    print(f">>> OpenAI error: {event}")
                elif etype == "response.function_call_arguments.done":
                    if event.get("name") == "end_call":
                        print(">>> Bot requested hangup")
                        break
        except Exception as e:
            print(f">>> openai_to_twilio error: {e}")

    MAX_CALL_SECONDS = 180

    try:
        await asyncio.wait_for(
            asyncio.gather(twilio_to_openai(), openai_to_twilio()),
            timeout=MAX_CALL_SECONDS,
        )
    except asyncio.TimeoutError:
        print(f">>> Call hit {MAX_CALL_SECONDS}s timeout, hanging up")
    finally:
        await openai_ws.close()
        print(">>> Call ended")

@app.post("/start-call")
async def start_call(request: Request):
    """Trigger an outbound call."""
    body = await request.json()
    public_url = body["public_url"]

    call = twilio_client.calls.create(
        to=TARGET_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url=f"{public_url}/twiml",
        record=True,
    )
    return {"call_sid": call.sid}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)