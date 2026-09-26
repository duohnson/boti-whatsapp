import logging
from django.utils import timezone
from .models import SesionWhatsApp, SesionUsuario, NodoBot, HistorialChat, CicloFacturacion
from .utils import enviar_mensaje_whatsapp
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

logger = logging.getLogger(__name__)


def mensaje_con_opciones(nodo):
    # mando las opciones numeradas para que respondan desde whatsapp
    opciones = list(nodo.opciones_salida.filter(nodo_siguiente__empresa_id=nodo.empresa_id).order_by('pk'))
    if not opciones:
        # si no hay menu, envio solo el texto del paso
        return nodo.contenido_mensaje
    lineas = [f"{indice}. {opcion.etiqueta or opcion.entrada_esperada}" for indice, opcion in enumerate(opciones, start=1)]
    return f"{nodo.contenido_mensaje}\n\n" + '\n'.join(lineas)


def guardar_mensaje_cliente(sesion, texto, identificador):
    # ignoro el reintento si ya guarde este mensaje
    if identificador and HistorialChat.objects.filter(sesion_usuario=sesion, identificador_mensaje=identificador).exists():
        return None
    return HistorialChat.objects.create(
        sesion_usuario=sesion,
        rol='user',
        contenido=texto,
        identificador_mensaje=identificador or '',
    )


def responder_con_ia(empresa, sesion, sesion_whatsapp, ahora, opcion_pdf=None):
    # uso el contexto que dejo el cliente para responder
    historial = HistorialChat.objects.filter(sesion_usuario=sesion).order_by('fecha')
    mensajes = [SystemMessage(content=empresa.prompt_sistema_ia)]
    for item in historial:
        if item.rol == 'user':
            mensajes.append(HumanMessage(content=item.contenido))
        else:
            mensajes.append(AIMessage(content=item.contenido))

    # le paso el historial junto con las instrucciones que puso el cliente
    respuesta = str(ChatOpenAI(temperature=0.7).invoke(mensajes).content)
    HistorialChat.objects.create(sesion_usuario=sesion, rol='assistant', contenido=respuesta)
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
    # guardo el tiempo antes de actualizarlo para detectar chats viejos
    inactiva = not creada and sesion.ultima_actividad < ahora - timezone.timedelta(hours=2)
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

    if inactiva:
        # despues de un rato vuelvo a empezar el flujo del cliente
        HistorialChat.objects.filter(sesion_usuario=sesion).exclude(pk=mensaje_cliente.pk).delete()
        if empresa.ia_desde_primer_mensaje:
            sesion.nodo_actual = None
            sesion.save(update_fields=['nodo_actual'])
            responder_con_ia(empresa, sesion, sesion_whatsapp, ahora)
            return
        if not nodo_inicial:
            sesion.nodo_actual = None
            sesion.save(update_fields=['nodo_actual'])
            return
        asignar_nodo(sesion, nodo_inicial)
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

    if nodo_actual.tipo_nodo in ['MENU', 'TEXT']:
        # acepta el numero, la respuesta o el nombre visible de la opcion, y normaliza entradas raras como '1.', 'hola', emojis o puntos
        opciones = list(nodo_actual.opciones_salida.filter(nodo_siguiente__empresa=empresa).select_related('nodo_siguiente').order_by('pk'))
        entrada = (texto_usuario or '').strip()
        entrada_normalizada = ''.join(ch for ch in entrada.casefold() if not ch.isdigit() or ch.isdigit())
        entrada_normalizada = entrada_normalizada.strip(' .,!;:¿?¡!').strip()
        entrada_aceptada = entrada_normalizada
        valores_aceptados = set()
        for indice, opcion in enumerate(opciones, start=1):
            valores_aceptados.add(str(indice))
            valores_aceptados.add(str(indice) + '.')
            valores_aceptados.add(str(indice) + ')')
            valores_aceptados.add(opcion.entrada_esperada.strip().casefold())
            valores_aceptados.add((opcion.entrada_esperada or '').strip().casefold().strip(' .,!;:¿?¡!'))
            etiqueta = (opcion.etiqueta or '').strip().casefold().strip(' .,!;:¿?¡!')
            valores_aceptados.add(etiqueta)
        opcion_elegida = next((
            opcion for indice, opcion in enumerate(opciones, start=1)
            if entrada_aceptada in {
                str(indice),
                f'{indice}.',
                f'{indice})',
                opcion.entrada_esperada.strip().casefold(),
                (opcion.entrada_esperada or '').strip().casefold().strip(' .,!;:¿?¡!'),
                (opcion.etiqueta or '').strip().casefold().strip(' .,!;:¿?¡!'),
            }
            or entrada_aceptada in {str(indice), str(indice) + '.', str(indice) + ')'}
        ), None)

        if not opcion_elegida:
            entrada_reducida = ''.join(ch for ch in entrada_normalizada if ch not in ' .,!;:¿?¡!')
            if entrada_reducida and any(car.isalpha() for car in entrada_reducida):
                entrada_reducida = ''.join(ch for ch in entrada_reducida if ch.isalpha() or ch.isspace())
            if not entrada_reducida or not any(car.isalnum() for car in entrada_reducida):
                enviar_respuesta_de_nodo(nodo_actual, None, sesion_whatsapp, telefono_cliente, destino_chat)
                return
            opcion_elegida = next((
                opcion for opcion in opciones
                if entrada_reducida in {
                    (opcion.entrada_esperada or '').strip().casefold().strip(' .,!;:¿?¡!'),
                    (opcion.etiqueta or '').strip().casefold().strip(' .,!;:¿?¡!'),
                }
            ), None)

        if not opcion_elegida:
            enviar_respuesta_de_nodo(nodo_actual, None, sesion_whatsapp, telefono_cliente, destino_chat)
            return

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

