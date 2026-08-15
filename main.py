import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi import FastAPI, Request
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
    """Twilio fetches this when the call connects, to ask what to do."""
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Hello. This is a test call from the voice agent tester.</Say>
    <Pause length="2"/>
    <Say>Goodbye.</Say>
</Response>"""
    return HTMLResponse(content=twiml, media_type="application/xml")

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