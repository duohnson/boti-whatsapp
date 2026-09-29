import logging
from datetime import timedelta
import requests
from django.db import transaction
from django.utils import timezone
from .models import HistorialChat, SesionWhatsApp
from .utils import enviar_mensaje_whatsapp

registro = logging.getLogger(__name__)


def entregar_mensaje(identificador, enviar=None):
    enviar = enviar or enviar_mensaje_whatsapp
    with transaction.atomic():
        mensaje = HistorialChat.objects.select_for_update().select_related('sesion_usuario').get(pk=identificador)
        if mensaje.rol == 'user' or mensaje.estado_entrega in ['enviado', 'historico']:
            return mensaje.estado_entrega
        if mensaje.estado_entrega == 'enviando' and mensaje.intento_entrega and mensaje.intento_entrega > timezone.now() - timedelta(seconds=60):
            return 'enviando'
        mensaje.estado_entrega = 'enviando'
        mensaje.intento_entrega = timezone.now()
        mensaje.save(update_fields=['estado_entrega', 'intento_entrega'])
    try:
        whatsapp = SesionWhatsApp.objects.get(empresa=mensaje.sesion_usuario.empresa, estado='conectado')
        respuesta = enviar(whatsapp, mensaje.sesion_usuario.telefono_cliente, mensaje.contenido,
                           mensaje.pk if mensaje.adjunto_entrega else mensaje.opcion_pdf_id, mensaje.sesion_usuario.destino_chat or None,
                           id_envio=str(mensaje.id_envio), **({'adjunto': mensaje.adjunto_entrega} if mensaje.adjunto_entrega else {}))
        estado = respuesta.get('estado') if isinstance(respuesta, dict) else None
        if estado not in ['enviado', 'fallido', 'incierto', 'enviando']:
            estado = 'incierto'
        error = '' if estado == 'enviado' else 'No hay confirmación completa. Revisa el chat antes de resolver la entrega.'
    except SesionWhatsApp.DoesNotExist:
        estado, error = 'fallido', 'Conecta WhatsApp para entregar este mensaje.'
    except (requests.Timeout, requests.ConnectionError):
        estado, error = 'incierto', 'Se perdió la comunicación. Reintenta con el mismo identificador para consultar la entrega.'
    except Exception:
        registro.exception('No se pudo entregar el mensaje %s', identificador)
        estado, error = 'fallido', 'No se pudo entregar. Puedes reintentar desde el panel.'
    HistorialChat.objects.filter(pk=identificador).update(estado_entrega=estado, error_entrega=error)
    return estado
