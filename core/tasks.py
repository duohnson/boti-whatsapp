import os
from celery import shared_task
from django.utils import timezone
from .models import Empresa, SesionUsuario, NodoBot, OpcionNodo, HistorialChat, CicloFacturacion
from .utils import enviar_mensaje_whatsapp
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

@shared_task
def procesar_mensaje_whatsapp(data):
    try:
        entradas = data.get("entry", [])
        for entrada in entradas:
            cambios = entrada.get("changes", [])
            for cambio in cambios:
                valor = cambio.get("value", {})
                mensajes = valor.get("messages", [])
                metadatos = valor.get("metadata", {})
                telefono_id = metadatos.get("phone_number_id")

                if not mensajes or not telefono_id:
                    continue

                empresa = Empresa.objects.filter(telefono_id=telefono_id, activo=True).first()
                if not empresa:
                    continue

                for mensaje in mensajes:
                    if mensaje.get("type") != "text":
                        continue

                    texto_usuario = mensaje["text"]["body"]
                    telefono_cliente = mensaje["from"]

                    sesion, creado = SesionUsuario.objects.get_or_create(
                        telefono_cliente=telefono_cliente,
                        defaults={"activo": True}
                    )

                    if creado or not sesion.nodo_actual:
                        nodo_inicial = NodoBot.objects.filter(empresa=empresa, es_nodo_inicial=True).first()
                        if nodo_inicial:
                            sesion.nodo_actual = nodo_inicial
                            sesion.save()
                            enviar_mensaje_whatsapp(
                                empresa.waba_id, empresa.telefono_id, empresa.token_acceso,
                                telefono_cliente, nodo_inicial.contenido_mensaje
                            )
                        continue

                    sesion.ultima_actividad = timezone.now()
                    sesion.save()

                    nodo_actual = sesion.nodo_actual

                    if nodo_actual.tipo_nodo in ["MENU", "TEXT"]:
                        opcion = OpcionNodo.objects.filter(
                            nodo_padre=nodo_actual,
                            entrada_esperada__iexact=texto_usuario.strip()
                        ).first()

                        if opcion:
                            nodo_siguiente = opcion.nodo_siguiente
                            sesion.nodo_actual = nodo_siguiente
                            sesion.save()
                            enviar_mensaje_whatsapp(
                                empresa.waba_id, empresa.telefono_id, empresa.token_acceso,
                                telefono_cliente, nodo_siguiente.contenido_mensaje
                            )
                        else:
                            enviar_mensaje_whatsapp(
                                empresa.waba_id, empresa.telefono_id, empresa.token_acceso,
                                telefono_cliente, nodo_actual.contenido_mensaje
                            )
                    
                    elif nodo_actual.tipo_nodo == "AI_AGENT":
                        HistorialChat.objects.create(
                            sesion_usuario=sesion,
                            rol="user",
                            contenido=texto_usuario
                        )

                        historial_bd = HistorialChat.objects.filter(sesion_usuario=sesion).order_by("fecha")
                        mensajes_llm = [SystemMessage(content=empresa.prompt_sistema_ia)]
                        for h in historial_bd:
                            if h.rol == "user":
                                mensajes_llm.append(HumanMessage(content=h.contenido))
                            else:
                                mensajes_llm.append(AIMessage(content=h.contenido))

                        llm = ChatOpenAI(temperature=0.7)
                        respuesta_ia = llm.invoke(mensajes_llm)
                        contenido_respuesta = respuesta_ia.content

                        HistorialChat.objects.create(
                            sesion_usuario=sesion,
                            rol="assistant",
                            contenido=contenido_respuesta
                        )

                        enviar_mensaje_whatsapp(
                            empresa.waba_id, empresa.telefono_id, empresa.token_acceso,
                            telefono_cliente, contenido_respuesta
                        )

                        hoy = timezone.now()
                        ciclo, _ = CicloFacturacion.objects.get_or_create(
                            empresa=empresa,
                            mes=hoy.month,
                            anio=hoy.year
                        )
                        ciclo.conteo_mensajes_ia += 1
                        ciclo.save()

    except Exception:
        pass

@shared_task
def limpiar_sesiones_inactivas():
    limite = timezone.now() - timezone.timedelta(hours=2)
    sesiones = SesionUsuario.objects.filter(ultima_actividad__lt=limite, activo=True)
    for sesion in sesiones:
        nodo_inicial = NodoBot.objects.filter(empresa=sesion.nodo_actual.empresa, es_nodo_inicial=True).first()
        if nodo_inicial:
            sesion.nodo_actual = nodo_inicial
            sesion.ultima_actividad = timezone.now()
            sesion.save()
            HistorialChat.objects.filter(sesion_usuario=sesion).delete()
