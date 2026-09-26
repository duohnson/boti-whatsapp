import requests
from django.conf import settings

def solicitar_whatsapp(ruta, datos=None, metodo='post'):
    # django solo habla con el servicio local usando este secreto
    secreto = settings.WHATSAPP_INTERNAL_SECRET
    if not secreto:
        raise RuntimeError('Falta configurar WHATSAPP_INTERNAL_SECRET')

    url = f"{settings.WHATSAPP_NODE_URL.rstrip('/')}{ruta}"
    headers = {
        "Authorization": f"Bearer {secreto}",
        "Content-Type": "application/json"
    }
    respuesta = requests.request(metodo, url, headers=headers, json=datos, timeout=20)
    respuesta.raise_for_status()
    return respuesta.json() if respuesta.content else {}

def enviar_mensaje_whatsapp(sesion, destino, texto, opcion_pdf=None, destino_chat=None):
    # mando el id de sesion para no cruzar numeros de clientes
    datos = {'destino': destino, 'texto': texto}
    if destino_chat:
        datos['destino_chat'] = destino_chat
    if opcion_pdf:
        datos['opcion_pdf'] = opcion_pdf
    return solicitar_whatsapp(
        f'/api/sesiones/{sesion.identificador}/mensajes/',
        datos,
    )
