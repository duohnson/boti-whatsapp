import json
import tempfile
import uuid
from datetime import timedelta
from unittest.mock import patch
import requests
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms.models import model_to_dict
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import Empresa, AgenteEmpresa, NodoBot, OpcionNodo, SesionUsuario, SesionWhatsApp, HistorialChat
from core.conversaciones import procesar_mensaje_whatsapp, contexto_ia
from core.flujos import validar_flujo
from core.intercambio import exportar_flujo, importar_flujo
from core.entregas import entregar_mensaje


class PruebasOperacionBot(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = User.objects.create_user(username='propietario')
        cls.agente = User.objects.create_user(username='agente')
        cls.otro = User.objects.create_user(username='ajeno')
        cls.empresa = Empresa.objects.create(propietario=cls.usuario)
        cls.otra = Empresa.objects.create(propietario=cls.otro)
        AgenteEmpresa.objects.create(empresa=cls.empresa, usuario=cls.agente)
        cls.whatsapp = SesionWhatsApp.objects.create(empresa=cls.empresa, estado='conectado')
        cls.inicio = NodoBot.objects.create(empresa=cls.empresa, nombre='inicio', tipo_nodo='MENU', contenido_mensaje='elige', es_nodo_inicial=True)
        cls.final = NodoBot.objects.create(empresa=cls.empresa, nombre='final', tipo_nodo='END', contenido_mensaje='hasta pronto')
        OpcionNodo.objects.create(nodo_padre=cls.inicio, nodo_siguiente=cls.final, entrada_esperada='1', etiqueta='terminar')

    def setUp(self):
        self.client.force_login(self.usuario)

    def chat(self, **datos):
        return SesionUsuario.objects.create(empresa=self.empresa, telefono_cliente='50611111111', **datos)

    @patch('core.conversaciones.enviar_mensaje_whatsapp', return_value={'estado':'enviado'})
    def test_mismo_mensaje_no_repite_entrega(self, enviar):
        for _ in range(2):
            procesar_mensaje_whatsapp(self.whatsapp.identificador, '50611111111', 'hola', 'entrada-1')
        self.assertEqual(enviar.call_count, 1)
        self.assertEqual(HistorialChat.objects.filter(rol='assistant', estado_entrega='enviado').count(), 1)

    @patch('core.conversaciones.enviar_mensaje_whatsapp')
    @patch('core.conversaciones.generar_respuesta_ia', return_value='respuesta generada')
    def test_reintento_ia_reusa_texto_identificador_y_saldo(self, generar, enviar):
        self.empresa.plan = 'corporativo'
        self.empresa.plan_hasta = timezone.now() + timedelta(days=7)
        self.empresa.ia_desde_primer_mensaje = True
        self.empresa.save()
        enviar.side_effect = [requests.Timeout(), {'estado':'enviado'}]
        procesar_mensaje_whatsapp(self.whatsapp.identificador, '50611111111', 'hola', 'entrada-1')
        mensaje = HistorialChat.objects.get(rol='assistant')
        self.assertEqual(mensaje.estado_entrega, 'incierto')
        procesar_mensaje_whatsapp(self.whatsapp.identificador, '50611111111', 'hola', 'entrada-1')
        self.empresa.refresh_from_db()
        mensaje.refresh_from_db()
        self.assertEqual(mensaje.estado_entrega, 'enviado')
        self.assertEqual(generar.call_count, 1)
        self.assertEqual(self.empresa.respuestas_ia_utilizadas, 1)
        self.assertEqual(enviar.call_args_list[0].kwargs['id_envio'], enviar.call_args_list[1].kwargs['id_envio'])

    @patch('core.conversaciones.enviar_mensaje_whatsapp', return_value={'estado':'enviado'})
    def test_chat_cerrado_reabre_al_recibir_otro_mensaje(self, enviar):
        for texto, identificador in [('hola','1'), ('1','2'), ('hola de nuevo','3')]:
            procesar_mensaje_whatsapp(self.whatsapp.identificador, '50611111111', texto, identificador)
        chat = SesionUsuario.objects.get(empresa=self.empresa)
        self.assertEqual(chat.estado, 'bot')
        self.assertEqual(chat.nodo_actual_id, self.inicio.pk)
        self.assertEqual(enviar.call_count, 3)

    @patch('core.conversaciones.enviar_mensaje_whatsapp', return_value={'estado':'enviado'})
    def test_reapertura_desactivada_conserva_el_cierre(self, enviar):
        self.empresa.reabrir_conversaciones = False
        self.empresa.save()
        self.chat(estado='cerrada', activo=False)
        procesar_mensaje_whatsapp(self.whatsapp.identificador, '50611111111', 'hola', 'entrada')
        enviar.assert_not_called()

    @patch('core.conversaciones.generar_respuesta_ia')
    @patch('core.conversaciones.enviar_mensaje_whatsapp', return_value={'estado':'enviado'})
    def test_saldo_agotado_deriva_sin_llamar_ia(self, enviar, generar):
        self.empresa.ia_desde_primer_mensaje = True
        self.empresa.plan = 'corporativo'
        self.empresa.plan_hasta = timezone.now() + timedelta(days=7)
        self.empresa.respuestas_ia_utilizadas = 1000
        self.empresa.accion_limite_ia = 'humano'
        self.empresa.save()
        procesar_mensaje_whatsapp(self.whatsapp.identificador, '50611111111', 'hola', 'entrada')
        generar.assert_not_called()
        self.assertEqual(SesionUsuario.objects.get().estado, 'humano')

    def test_historial_ia_tiene_limite_y_omite_entregas_fallidas(self):
        chat = self.chat()
        for _ in range(30):
            HistorialChat.objects.create(sesion_usuario=chat, rol='user', contenido='x' * 5000)
        HistorialChat.objects.create(sesion_usuario=chat, rol='assistant', contenido='NO INCLUIR', estado_entrega='fallido')
        mensajes = contexto_ia(self.empresa, chat)
        self.assertLessEqual(len(mensajes), self.empresa.max_mensajes_ia + 1)
        self.assertLessEqual(sum(len(m['content']) for m in mensajes[1:]), 16000)
        self.assertNotIn('NO INCLUIR', str(mensajes))

    @patch('core.conversaciones.enviar_mensaje_whatsapp')
    @patch('core.conversaciones.generar_respuesta_ia')
    def test_simulador_recorre_flujo_sin_mutar_chats_ni_enviar(self, generar, enviar):
        self.client.post(reverse('simulador'), {'texto':'hola'})
        respuesta = self.client.post(reverse('simulador'), {'texto':'1'})
        self.assertContains(respuesta, 'hasta pronto')
        self.assertEqual(respuesta.context['simulacion']['estado'], 'cerrada')
        self.assertFalse(SesionUsuario.objects.exists())
        self.assertFalse(HistorialChat.objects.exists())
        enviar.assert_not_called()
        generar.assert_not_called()
        self.client.post(reverse('simulador'), {'reiniciar':'1'})
        self.assertNotIn(f'simulador_{self.empresa.pk}', self.client.session)

    def test_validacion_avisos_de_inicio_menu_y_pasos_aislados(self):
        self.inicio.es_nodo_inicial = False
        self.inicio.save()
        NodoBot.objects.create(empresa=self.empresa, nombre='aislado', tipo_nodo='MENU', contenido_mensaje='elige')
        avisos = ' '.join(validar_flujo(self.empresa))
        self.assertIn('Falta marcar', avisos)
        self.assertIn('no se puede alcanzar', avisos)
        self.assertIn('no tiene opciones', avisos)

    def test_formulario_invalido_conserva_texto_y_campos(self):
        respuesta = self.client.post(reverse('crear_nodo'), {'nombre':'mi borrador', 'tipo_nodo':'MENU', 'contenido_mensaje':''})
        self.assertContains(respuesta, 'mi borrador')
        self.assertTrue(respuesta.context['formulario_nodo'].is_bound)
        self.assertIn('contenido_mensaje', respuesta.context['formulario_nodo'].errors)
        self.assertFalse(NodoBot.objects.filter(nombre='mi borrador').exists())

    def test_opcion_invalida_conserva_etiqueta_y_no_cruza_empresa(self):
        ajeno = NodoBot.objects.create(empresa=self.otra, nombre='privado', tipo_nodo='TEXT', contenido_mensaje='privado')
        respuesta = self.client.post(reverse('crear_opcion', args=[self.inicio.pk]), {'entrada_esperada':'2', 'etiqueta':'mi opcion', 'nodo_siguiente':ajeno.pk})
        self.assertContains(respuesta, 'mi opcion')
        self.assertEqual(self.inicio.opciones_salida.count(), 1)

    def test_duplicar_conserva_inicio_y_copia_opciones(self):
        self.client.post(reverse('duplicar_nodo', args=[self.inicio.pk]))
        copia = NodoBot.objects.get(nombre='inicio (copia)')
        self.assertFalse(copia.es_nodo_inicial)
        self.assertEqual(copia.opciones_salida.get().nodo_siguiente_id, self.final.pk)
        self.assertEqual(NodoBot.objects.filter(empresa=self.empresa, es_nodo_inicial=True).count(), 1)

    def test_exportacion_importacion_recrea_enlaces_sin_borrar_actuales(self):
        datos = exportar_flujo(self.empresa)
        archivo = SimpleUploadedFile('flujo.json', json.dumps(datos).encode())
        self.assertEqual(importar_flujo(self.empresa, archivo), 2)
        self.assertEqual(NodoBot.objects.filter(empresa=self.empresa).count(), 4)
        self.assertEqual(NodoBot.objects.filter(empresa=self.empresa, es_nodo_inicial=True).count(), 1)
        nuevos = NodoBot.objects.filter(empresa=self.empresa).exclude(pk__in=[self.inicio.pk,self.final.pk])
        inicio = nuevos.get(tipo_nodo='MENU')
        self.assertIn(inicio.opciones_salida.get().nodo_siguiente_id, list(nuevos.values_list('pk',flat=True)))

    def test_importacion_invalida_no_deja_pasos_parciales(self):
        datos = exportar_flujo(self.empresa)
        datos['pasos'][0]['opciones'][0]['destino'] = 999999
        with self.assertRaises(ValidationError):
            importar_flujo(self.empresa, SimpleUploadedFile('flujo.json',json.dumps(datos).encode()))
        self.assertEqual(NodoBot.objects.filter(empresa=self.empresa).count(), 2)

    def test_exportacion_importacion_incluye_pdf(self):
        with tempfile.TemporaryDirectory() as carpeta, override_settings(MEDIA_ROOT=carpeta):
            opcion = self.inicio.opciones_salida.get()
            opcion.archivo_pdf = SimpleUploadedFile('guia.pdf', b'%PDF-1.4\ncontenido de prueba')
            opcion.save()
            datos = exportar_flujo(self.empresa)
            importar_flujo(self.otra, SimpleUploadedFile('flujo.json',json.dumps(datos).encode()))
            nueva = OpcionNodo.objects.get(nodo_padre__empresa=self.otra)
            with nueva.archivo_pdf.open('rb') as archivo:
                self.assertEqual(archivo.read(), b'%PDF-1.4\ncontenido de prueba')

    def test_agente_toma_chat_y_bloquea_otro_agente(self):
        chat = self.chat(estado='humano')
        self.client.force_login(self.agente)
        self.assertEqual(self.client.post(reverse('tomar_conversacion',args=[chat.pk])).status_code,200)
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.post(reverse('tomar_conversacion',args=[chat.pk])).status_code,409)
        respuesta = self.client.post(reverse('responder_agente',args=[chat.pk]), {'texto':'otra respuesta','id_envio':str(uuid.uuid4())})
        self.assertEqual(respuesta.status_code,409)
        self.client.post(reverse('tomar_conversacion',args=[chat.pk]), {'liberar':'1'})
        chat.refresh_from_db()
        self.assertIsNone(chat.asignado_a)

    def test_agente_no_modifica_flujo_ni_accede_otra_empresa(self):
        self.client.force_login(self.agente)
        self.assertEqual(self.client.post(reverse('crear_nodo'),{}).status_code,403)
        self.assertEqual(self.client.post(reverse('elegir_empresa'),{'empresa':self.otra.pk}).status_code,404)
        ajeno = SesionUsuario.objects.create(empresa=self.otra,telefono_cliente='ajeno',estado='humano')
        self.assertEqual(self.client.get(reverse('atencion_humana'),{'c':ajeno.pk}).status_code,404)

    def test_quitar_agente_revoca_sesion_activa(self):
        self.client.force_login(self.agente)
        self.client.post(reverse('elegir_empresa'),{'empresa':self.empresa.pk})
        AgenteEmpresa.objects.filter(empresa=self.empresa,usuario=self.agente).delete()
        respuesta = self.client.get(reverse('atencion_humana'))
        self.assertIsNone(respuesta.context['empresa_activa'])

    @patch('core.views.enviar_mensaje_whatsapp', return_value={'estado':'enviado'})
    def test_respuesta_humana_idempotente(self, enviar):
        chat = self.chat(estado='humano')
        datos = {'texto':'respuesta','id_envio':str(uuid.uuid4())}
        for _ in range(2):
            self.assertEqual(self.client.post(reverse('responder_agente',args=[chat.pk]),datos).json()['estado'],'enviado')
        self.assertEqual(enviar.call_count,1)
        self.assertEqual(chat.historialchat_set.count(),1)

    @patch('core.views.solicitar_whatsapp', return_value={'servicio':'disponible','estado':'desconectado','cliente_activo':False})
    def test_diagnostico_distingue_estado_real_y_guardado(self, solicitar):
        datos = self.client.get(reverse('diagnostico_whatsapp')).json()
        self.assertEqual(datos['estado_guardado'],'conectado')
        self.assertEqual(datos['estado'],'desconectado')
        self.assertEqual(solicitar.call_args.kwargs['espera'],4)

    @patch('core.views.solicitar_whatsapp', side_effect=RuntimeError())
    def test_diagnostico_servicio_caido(self, solicitar):
        self.assertEqual(self.client.get(reverse('diagnostico_whatsapp')).json()['estado'],'desconocido')

    def test_entrega_historica_no_se_reenvia(self):
        mensaje = HistorialChat.objects.create(sesion_usuario=self.chat(),rol='assistant',contenido='anterior',estado_entrega='historico')
        with patch('core.entregas.enviar_mensaje_whatsapp') as enviar:
            self.assertEqual(entregar_mensaje(mensaje.pk),'historico')
            enviar.assert_not_called()

    @patch('core.utils.solicitar_whatsapp', return_value={'estado': 'enviado'})
    def test_entrega_conserva_pdf_al_eliminar_opcion(self, solicitar):
        with tempfile.TemporaryDirectory() as carpeta, override_settings(MEDIA_ROOT=carpeta):
            opcion = OpcionNodo.objects.create(nodo_padre=self.inicio, nodo_siguiente=self.final, entrada_esperada='pdf', etiqueta='documento', archivo_pdf=SimpleUploadedFile('guia.pdf', b'%PDF-1.4\ncontenido'))
            mensaje = HistorialChat.objects.create(sesion_usuario=self.chat(), rol='assistant', contenido='documento', estado_entrega='generado', opcion_pdf=opcion, adjunto_entrega=opcion.archivo_pdf.name)
            opcion.delete()
            self.assertEqual(entregar_mensaje(mensaje.pk), 'enviado')
            self.assertIn('pdf_base64', solicitar.call_args.args[1])

    def test_otro_agente_no_resuelve_entrega_asignada(self):
        mensaje = HistorialChat.objects.create(sesion_usuario=self.chat(asignado_a=self.usuario), rol='agent', contenido='pendiente', estado_entrega='incierto')
        self.client.force_login(self.agente)
        respuesta = self.client.post(reverse('reintentar_entrega', args=[mensaje.pk]), {'confirmado': '1'})
        self.assertEqual(respuesta.status_code, 403)
        mensaje.refresh_from_db()
        self.assertEqual(mensaje.estado_entrega, 'incierto')
