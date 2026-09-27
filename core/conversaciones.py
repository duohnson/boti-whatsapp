import logging
from django.utils import timezone
from django.db import IntegrityError, transaction
from .models import Empresa, SesionWhatsApp, SesionUsuario, NodoBot, HistorialChat, CicloFacturacion
from .utils import enviar_mensaje_whatsapp
from .ia import ErrorProveedorIA, generar_respuesta_ia

logger = logging.getLogger(__name__)


def mensaje_con_opciones(nodo):
    # mostrar las conexiones configuradas desde este paso
    opciones = list(nodo.opciones_salida.filter(nodo_siguiente__empresa_id=nodo.empresa_id).order_by('pk'))
    if not opciones:
        return nodo.contenido_mensaje
    lineas = [f"{opcion.entrada_esperada}. {opcion.etiqueta or opcion.entrada_esperada}" for opcion in opciones]
    return f"{nodo.contenido_mensaje}\n\n" + '\n'.join(lineas)


def guardar_mensaje_cliente(sesion, texto, identificador):
    # ignoro el reintento si ya guarde este mensaje
    if identificador and HistorialChat.objects.filter(sesion_usuario=sesion, identificador_mensaje=identificador).exists():
        return None
    try:
        return HistorialChat.objects.create(
            sesion_usuario=sesion,
            rol='user',
            contenido=texto,
            identificador_mensaje=identificador or '',
        )
    except IntegrityError:
        return None


def responder_con_ia(empresa, sesion, sesion_whatsapp, ahora, opcion_pdf=None):
    # preparar el historial para el proveedor de ia
    historial = HistorialChat.objects.filter(sesion_usuario=sesion).order_by('fecha')
    mensajes = [{'role': 'system', 'content': empresa.prompt_sistema_ia}]
    for item in historial:
        rol = 'user' if item.rol == 'user' else 'assistant'
        mensajes.append({'role': rol, 'content': item.contenido})

    # bloquear el consumo para no superar el limite con mensajes simultaneos
    empresa = Empresa.objects.select_for_update().get(pk=empresa.pk)
    if empresa.respuestas_ia_utilizadas >= empresa.limite_respuestas_ia:
        enviar_respuesta_de_nodo_texto(
            sesion_whatsapp,
            sesion.telefono_cliente,
            'Se alcanzó el límite de respuestas de IA para esta cuenta.',
            destino_chat=None,
        )
        return
    try:
        respuesta = generar_respuesta_ia(mensajes)
    except ErrorProveedorIA as error:
        logger.warning('La IA no está disponible para empresa %s: %s', empresa.pk, error)
        enviar_respuesta_de_nodo_texto(
            sesion_whatsapp,
            sesion.telefono_cliente,
            'El agente de IA no está disponible en este momento. Puedes elegir otra opción.',
        )
        return
    # guardar y contar solo las respuestas generadas correctamente
    HistorialChat.objects.create(sesion_usuario=sesion, rol='assistant', contenido=respuesta)
    empresa.respuestas_ia_utilizadas += 1
    empresa.save(update_fields=['respuestas_ia_utilizadas'])
    try:
        enviar_mensaje_whatsapp(sesion_whatsapp, sesion.telefono_cliente, respuesta, opcion_pdf)
    except Exception:
        logger.exception('No se pudo entregar respuesta de IA a WhatsApp')
    ciclo, _ = CicloFacturacion.objects.get_or_create(
        empresa=empresa,
        mes=ahora.month,
        anio=ahora.year,
    )
    ciclo.conteo_mensajes_ia += 1
    ciclo.save(update_fields=['conteo_mensajes_ia'])


def enviar_respuesta_de_nodo_texto(sesion_whatsapp, telefono, texto, destino_chat=None):
    # enviar mensajes del sistema sin depender de un nodo
    try:
        enviar_mensaje_whatsapp(sesion_whatsapp, telefono, texto, destino_chat=destino_chat)
    except Exception:
        logger.exception('No se pudo entregar una respuesta a WhatsApp')


def enviar_respuesta_de_nodo(nodo, opcion, sesion_whatsapp, telefono, destino_chat=None):
    # si eligio una opcion con pdf tambien mando su adjunto
    texto = mensaje_con_opciones(nodo)
    try:
        enviar_mensaje_whatsapp(
            sesion_whatsapp,
            telefono,
            texto,
            opcion.pk if opcion and opcion.archivo_pdf else None,
            destino_chat,
        )
    except Exception:
        logger.exception('No se pudo entregar respuesta del bot a WhatsApp')
        return False
    return True


def asignar_nodo(sesion, nodo):
    # al entrar a este paso dejo el estado listo para el siguiente mensaje
    sesion.nodo_actual = nodo
    if nodo.tipo_nodo == 'HUMAN_AGENT':
        sesion.estado = 'humano'
    elif nodo.tipo_nodo == 'END':
        sesion.estado = 'cerrada'
        sesion.activo = False
    else:
        sesion.estado = 'bot'
        sesion.activo = True
    sesion.save(update_fields=['nodo_actual', 'estado', 'activo', 'ultima_actividad'])


@transaction.atomic
def procesar_mensaje_whatsapp(identificador, telefono_cliente, texto_usuario, identificador_mensaje='', destino_chat=None):
    # busco la empresa usando la sesion exacta que recibio el mensaje
    sesion_whatsapp = SesionWhatsApp.objects.select_related('empresa').get(
        identificador=identificador,
        estado='conectado',
        empresa__activo=True,
    )
    empresa = sesion_whatsapp.empresa
    ahora = timezone.now()
    sesion, creada = SesionUsuario.objects.get_or_create(
        empresa=empresa,
        telefono_cliente=telefono_cliente,
        defaults={'activo': True},
    )
    # bloquear la conversacion para procesar los mensajes en orden
    sesion = SesionUsuario.objects.select_for_update().get(pk=sesion.pk)
    mensaje_cliente = guardar_mensaje_cliente(sesion, texto_usuario, identificador_mensaje)
    if not mensaje_cliente:
        return

    sesion.ultima_actividad = ahora
    sesion.save(update_fields=['ultima_actividad'])
    sesion_whatsapp.ultima_actividad = ahora
    sesion_whatsapp.save(update_fields=['ultima_actividad'])

    # si pidieron una persona o cerraron el chat, no responde el bot
    if sesion.estado in ['humano', 'cerrada']:
        return

    # usar la bienvenida marcada o el primer paso disponible
    nodo_inicial = NodoBot.objects.filter(empresa=empresa, es_nodo_inicial=True).prefetch_related('opciones_salida').first()
    if not nodo_inicial:
        nodo_inicial = NodoBot.objects.filter(empresa=empresa).prefetch_related('opciones_salida').order_by('pk').first()
    if creada:
        # el cliente puede saltarse el menu y arrancar directo con la ia
        if empresa.ia_desde_primer_mensaje:
            responder_con_ia(empresa, sesion, sesion_whatsapp, ahora)
            return
        if not nodo_inicial:
            return
        asignar_nodo(sesion, nodo_inicial)
        if nodo_inicial.tipo_nodo == 'AI_AGENT':
            responder_con_ia(empresa, sesion, sesion_whatsapp, ahora)
        else:
            enviar_respuesta_de_nodo(nodo_inicial, None, sesion_whatsapp, telefono_cliente, destino_chat)
        return

    nodo_actual = sesion.nodo_actual
    if not nodo_actual or nodo_actual.empresa_id != empresa.id:
        if empresa.ia_desde_primer_mensaje:
            responder_con_ia(empresa, sesion, sesion_whatsapp, ahora)
            return
        if nodo_inicial:
            asignar_nodo(sesion, nodo_inicial)
            enviar_respuesta_de_nodo(nodo_inicial, None, sesion_whatsapp, telefono_cliente, destino_chat)
        return

    if (texto_usuario or '').strip().casefold() == 'volver' and nodo_inicial and nodo_actual.pk != nodo_inicial.pk:
        # volver siempre abre el menu inicial
        asignar_nodo(sesion, nodo_inicial)
        enviar_respuesta_de_nodo(nodo_inicial, None, sesion_whatsapp, telefono_cliente, destino_chat)
        return

    if nodo_actual.tipo_nodo in ['MENU', 'TEXT']:
        # buscar la conexion que coincida con el valor enviado
        opciones = list(nodo_actual.opciones_salida.filter(nodo_siguiente__empresa=empresa).select_related('nodo_siguiente').order_by('pk'))
        entrada_aceptada = normalizar_entrada(texto_usuario)
        opcion_elegida = next((
            opcion for opcion in opciones
            if entrada_aceptada in {
                normalizar_entrada(opcion.entrada_esperada),
                normalizar_entrada(opcion.etiqueta),
            }
        ), None)

        if not opcion_elegida:
            enviar_respuesta_de_nodo(nodo_actual, None, sesion_whatsapp, telefono_cliente, destino_chat)
            return

        # mover la conversacion al paso conectado
        nodo_siguiente = opcion_elegida.nodo_siguiente
        sesion.nodo_actual = nodo_siguiente
        if nodo_siguiente.tipo_nodo == 'HUMAN_AGENT':
            sesion.estado = 'humano'
        elif nodo_siguiente.tipo_nodo == 'END':
            sesion.estado = 'cerrada'
            sesion.activo = False
        else:
            sesion.estado = 'bot'
            sesion.activo = True
        sesion.save(update_fields=['nodo_actual', 'estado', 'activo', 'ultima_actividad'])

        if nodo_siguiente.tipo_nodo == 'AI_AGENT':
            responder_con_ia(empresa, sesion, sesion_whatsapp, ahora, opcion_elegida.pk if opcion_elegida.archivo_pdf else None)
        else:
            enviar_respuesta_de_nodo(nodo_siguiente, opcion_elegida, sesion_whatsapp, telefono_cliente, destino_chat)
            if nodo_siguiente.tipo_nodo == 'TEXT' and not nodo_siguiente.opciones_salida.exists():
                # reiniciar en el siguiente mensaje despues de un texto final
                sesion.nodo_actual = None
                sesion.save(update_fields=['nodo_actual', 'ultima_actividad'])
        return

    if nodo_actual.tipo_nodo == 'AI_AGENT':
        responder_con_ia(empresa, sesion, sesion_whatsapp, ahora)
    elif nodo_actual.tipo_nodo == 'HUMAN_AGENT':
        sesion.estado = 'humano'
        sesion.save(update_fields=['estado'])
        if nodo_actual.contenido_mensaje:
            enviar_respuesta_de_nodo(nodo_actual, None, sesion_whatsapp, telefono_cliente, destino_chat)
    elif nodo_actual.tipo_nodo == 'END':
        sesion.estado = 'cerrada'
        sesion.activo = False
        sesion.save(update_fields=['estado', 'activo'])
        if nodo_actual.contenido_mensaje:
            enviar_respuesta_de_nodo(nodo_actual, None, sesion_whatsapp, telefono_cliente, destino_chat)
    else:
        enviar_respuesta_de_nodo(nodo_actual, None, sesion_whatsapp, telefono_cliente, destino_chat)


def normalizar_entrada(entrada):
    # aceptar valores con espacios o puntuacion adicional
    return (entrada or '').strip().casefold().strip(' .,!;:¿?¡!')

