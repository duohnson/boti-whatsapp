import requests
import base64
from django.conf import settings

def solicitar_whatsapp(ruta, datos=None, metodo='post', espera=20):
    # django solo habla con el servicio local usando este secreto
    secreto = settings.WHATSAPP_INTERNAL_SECRET
    if not secreto:
        raise RuntimeError('Falta configurar WHATSAPP_INTERNAL_SECRET')

    url = f"{settings.WHATSAPP_NODE_URL.rstrip('/')}{ruta}"
    headers = {
        "Authorization": f"Bearer {secreto}",
        "Content-Type": "application/json"
    }
    respuesta = requests.request(metodo, url, headers=headers, json=datos, timeout=espera)
    respuesta.raise_for_status()
    return respuesta.json() if respuesta.content else {}

def enviar_mensaje_whatsapp(sesion, destino, texto, opcion_pdf=None, destino_chat=None, id_envio=None, adjunto=None):
    # mando el id de sesion para no cruzar numeros de clientes
    datos = {'destino': destino, 'texto': texto}
    if id_envio:
        datos['id_envio'] = id_envio
    if destino_chat:
        datos['destino_chat'] = destino_chat
    if opcion_pdf or adjunto:
        from .models import OpcionNodo
        archivo_pdf = adjunto or OpcionNodo.objects.get(pk=opcion_pdf, nodo_padre__empresa=sesion.empresa).archivo_pdf
        if not archivo_pdf:
            raise ValueError('El adjunto ya no está disponible')
        with archivo_pdf.open('rb') as archivo:
            contenido = archivo.read(15 * 1024 * 1024 + 1)
        if len(contenido) > 15 * 1024 * 1024 or not contenido.startswith(b'%PDF-'):
            raise ValueError('PDF no válido')
        datos['opcion_pdf'] = opcion_pdf
        datos['pdf_base64'] = base64.b64encode(contenido).decode('ascii')
    return solicitar_whatsapp(
        f'/api/sesiones/{sesion.identificador}/mensajes/',
        datos,
    )
