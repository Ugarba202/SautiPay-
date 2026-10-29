from contextlib import asynccontextmanager
from fastapi import FastAPI, Form, Response
from app.config import settings
from app.models import init_db
from app.dashboard import dashboard_router
from app.ussd_handler import ussd_handler
from app.settlement import settle, SettlementError
from pydantic import BaseModel

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="SautiPay API", version="1.0.0", lifespan=lifespan)

# Mount Dashboard Pages
app.include_router(dashboard_router)

@app.get("/health")
def health():
    return {"status": "ok", "product": "SautiPay", "demo_mode": settings.DEMO_MODE}

# Africa's Talking USSD Webhook endpoint
@app.post("/ussd")
async def ussd_endpoint(
    sessionId: str = Form(...),
    phoneNumber: str = Form(...),
    text: str = Form(default=""),
    serviceCode: str = Form(default="*384#")
):
    response_text = ussd_handler.handle(sessionId, phoneNumber, text)
    return Response(content=response_text, media_type="text/plain")

class SettleWebhookRequest(BaseModel):
    invoice_id: str
    preimage: str

# LND Settlement Hook endpoint (verifies settlement via settle())
@app.post("/webhook/lnd")
async def lnd_webhook(payload: SettleWebhookRequest):
    try:
        payment = settle(payload.invoice_id, payload.preimage)
        return {"status": "success", "payment": payment}
    except SettlementError as e:
        return {"status": "error", "message": str(e)}
