import requests
from django.conf import settings
from .models import Empresa

def enviar_mensaje_whatsapp(waba_id, telefono_id, token, destino, texto):
    url = f"https://graph.facebook.com/v17.0/{telefono_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": destino,
        "type": "text",
        "text": {"preview_url": False, "body": texto}
    }
    respuesta = requests.post(url, headers=headers, json=payload)
    return respuesta.json()
