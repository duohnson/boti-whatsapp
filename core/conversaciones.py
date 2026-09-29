import logging
from django.db import transaction
from django.utils import timezone
from .models import Empresa, SesionWhatsApp, SesionUsuario, HistorialChat, CicloFacturacion
from .utils import enviar_mensaje_whatsapp
from .ia import ErrorProveedorIA, generar_respuesta_ia
from .entregas import entregar_mensaje
from .flujos import resolver_turno, mensaje_con_opciones, normalizar_entrada, fuera_del_horario, pide_atencion_humana

registro = logging.getLogger(__name__)


def contexto_ia(empresa, sesion):
    instrucciones = f'{empresa.prompt_sistema_ia[:4000]}\nResponde en {empresa.get_idioma_display()} con tono {empresa.get_tono_display().lower()}.'
    historial = HistorialChat.objects.filter(sesion_usuario=sesion).exclude(
        estado_entrega__in=['fallido', 'incierto', 'generado', 'enviando']
    ).order_by('-fecha', '-pk')[:empresa.max_mensajes_ia]
    mensajes, restantes = [], 16000
    for mensaje in historial:
        contenido = mensaje.contenido[-min(4000, restantes):]
        if not contenido or restantes <= 0:
            break
        mensajes.append({'role': 'user' if mensaje.rol == 'user' else 'assistant', 'content': contenido})
        restantes -= len(contenido)
    return [{'role': 'system', 'content': instrucciones}, *reversed(mensajes)]


@transaction.atomic
def preparar_turno(identificador, telefono, texto, id_mensaje, destino):
    whatsapp = SesionWhatsApp.objects.select_related('empresa').get(identificador=identificador, estado='conectado', empresa__activo=True)
    # bloqueo la empresa antes del chat para mantener el mismo orden entre solicitudes
    empresa = Empresa.objects.select_for_update().get(pk=whatsapp.empresa_id)
    sesion, nueva = SesionUsuario.objects.get_or_create(empresa=empresa, telefono_cliente=telefono)
    sesion = SesionUsuario.objects.select_for_update().get(pk=sesion.pk)
    entrada = HistorialChat.objects.filter(sesion_usuario=sesion, identificador_mensaje=id_mensaje).first() if id_mensaje else None
    if entrada:
        return list(entrada.respuestas.exclude(estado_entrega='enviado').values_list('pk', flat=True))
    entrada = HistorialChat.objects.create(sesion_usuario=sesion, rol='user', contenido=texto, identificador_mensaje=id_mensaje or '')
    if destino:
        sesion.destino_chat = destino
    resultado = resolver_turno(empresa, sesion.nodo_actual, sesion.estado, nueva, texto, timezone.now())
    sesion.nodo_actual = resultado['nodo']
    sesion.estado = resultado['estado']
    sesion.activo = sesion.estado != 'cerrada'
    if sesion.estado != 'humano':
        sesion.asignado_a = None
    if resultado['ia']:
        opcion = resultado.get('opcion')
        if empresa.respuestas_ia_utilizadas >= empresa.limite_respuestas_ia:
            respuesta = empresa.mensaje_limite_ia
            if empresa.accion_limite_ia == 'humano':
                sesion.estado = 'humano'
        else:
            try:
                respuesta = generar_respuesta_ia(contexto_ia(empresa, sesion))
                if not isinstance(respuesta, str) or not respuesta.strip():
                    raise ErrorProveedorIA('Respuesta vacía')
                empresa.respuestas_ia_utilizadas += 1
                empresa.save(update_fields=['respuestas_ia_utilizadas'])
                ahora = timezone.localtime()
                ciclo, _ = CicloFacturacion.objects.get_or_create(empresa=empresa, mes=ahora.month, anio=ahora.year)
                ciclo.conteo_mensajes_ia += 1
                ciclo.save(update_fields=['conteo_mensajes_ia'])
            except ErrorProveedorIA:
                respuesta = 'La IA no está disponible en este momento. Puedes solicitar atención humana.'
        resultado['salidas'].append({'texto': respuesta, 'opcion': opcion})
    sesion.save()
    whatsapp.ultima_actividad = timezone.now()
    whatsapp.save(update_fields=['ultima_actividad'])
    pendientes = []
    for salida in resultado['salidas']:
        opcion = salida['opcion']
        mensaje = HistorialChat.objects.create(
            sesion_usuario=sesion, rol='assistant', contenido=salida['texto'], respuesta_a=entrada,
            estado_entrega='generado', opcion_pdf=opcion if opcion and opcion.archivo_pdf else None,
            adjunto_entrega=opcion.archivo_pdf.name if opcion and opcion.archivo_pdf else '',
        )
        pendientes.append(mensaje.pk)
    return pendientes


def procesar_mensaje_whatsapp(identificador, telefono_cliente, texto_usuario, identificador_mensaje='', destino_chat=None):
    pendientes = preparar_turno(identificador, telefono_cliente, texto_usuario, identificador_mensaje, destino_chat)
    # las respuestas quedan guardadas antes de llamar al servicio de whatsapp
    for identificador in pendientes:
        entregar_mensaje(identificador, enviar=enviar_mensaje_whatsapp)
