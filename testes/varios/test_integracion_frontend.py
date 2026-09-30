import json
import uuid
from datetime import datetime, time, timezone, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.forms.models import model_to_dict
from django.test import TestCase, override_settings
from django.urls import reverse

from core.conversaciones import fuera_del_horario, procesar_mensaje_whatsapp
from core.forms import ConfiguracionEmpresaForm
from core.models import Empresa, HistorialChat, NodoBot, SesionUsuario, SesionWhatsApp


@override_settings(WHATSAPP_INTERNAL_SECRET='secreto-prueba')
class PruebasIntegracionFrontend(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = User.objects.create_user(username='panel', password='Clave-segura-123')
        cls.empresa = Empresa.objects.create(propietario=cls.usuario)
        cls.sesion = SesionWhatsApp.objects.create(empresa=cls.empresa)
        cls.otro_usuario = User.objects.create_user(username='otra_cuenta')
        cls.otra_empresa = Empresa.objects.create(propietario=cls.otro_usuario)

    def setUp(self):
        self.client.force_login(self.usuario)

    def evento(self, **datos):
        return self.client.post(reverse('evento_whatsapp_interno'), json.dumps({
            'identificador': str(self.sesion.identificador), **datos,
        }), content_type='application/json', HTTP_AUTHORIZATION='Bearer secreto-prueba')

    @patch('core.views.solicitar_whatsapp')
    def test_inicio_qr_evento_y_consulta(self, solicitar):
        self.assertEqual(self.client.post(reverse('conectar_whatsapp')).status_code, 200)
        solicitar.assert_called_once()
        self.assertEqual(self.evento(estado='esperando_qr', codigo_qr='data:image/png;base64,cHJ1ZWJh').status_code, 200)
        respuesta = self.client.get(reverse('estado_whatsapp'))
        self.assertEqual(respuesta.json()['codigo_qr'], 'data:image/png;base64,cHJ1ZWJh')
        self.assertIn('no-store', respuesta['Cache-Control'])
        self.evento(estado='conectado', numero_telefono='50688888888')
        respuesta = self.client.get(reverse('estado_whatsapp')).json()
        self.assertEqual(respuesta['estado'], 'conectado')
        self.assertEqual(respuesta['codigo_qr'], '')

    @patch('core.views.solicitar_whatsapp')
    def test_reintento_no_borra_el_qr_actual(self, solicitar):
        self.evento(estado='esperando_qr', codigo_qr='data:image/png;base64,cHJ1ZWJh')
        respuesta = self.client.post(reverse('conectar_whatsapp'))
        self.assertEqual(respuesta.json()['codigo_qr'], 'data:image/png;base64,cHJ1ZWJh')

    @patch('core.views.solicitar_whatsapp')
    def test_codigo_manual(self, solicitar):
        self.client.post(reverse('conectar_whatsapp'), {'telefono': '+50688888888'})
        self.assertEqual(solicitar.call_args.args[1]['telefono'], '50688888888')
        self.assertEqual(self.evento(estado='esperando_codigo', codigo_manual='ABCD1234').status_code, 200)
        self.assertEqual(self.client.get(reverse('estado_whatsapp')).json()['codigo_manual'], 'ABCD1234')
        self.client.post(reverse('desconectar_whatsapp'))
        self.assertEqual(self.client.get(reverse('estado_whatsapp')).json()['codigo_manual'], '')

    @patch('core.views.solicitar_whatsapp', side_effect=RuntimeError('servicio caido'))
    def test_error_del_servicio_no_anuncia_exito(self, solicitar):
        with self.assertLogs('core.views', level='ERROR'):
            respuesta = self.client.post(reverse('conectar_whatsapp'))
        self.assertEqual(respuesta.status_code, 503)
        self.sesion.refresh_from_db()
        self.assertEqual(self.sesion.estado, 'error')

    def test_eventos_rechazan_codigos_invalidos(self):
        self.assertEqual(self.evento(estado='esperando_qr', codigo_qr='javascript:alert(1)').status_code, 400)
        self.assertEqual(self.evento(estado='esperando_codigo', codigo_manual='<script>').status_code, 400)
        self.assertEqual(self.client.post(reverse('conectar_whatsapp'), {'telefono': 'no es numero'}).status_code, 400)

    def test_configuracion_muestra_y_guarda_los_campos_reales(self):
        datos = {clave: valor for clave, valor in model_to_dict(self.empresa).items() if valor is not None}
        datos.update(bienvenida='Hola desde el panel', despedida='Hasta pronto', tono='formal', idioma='pt', derivar_auto=True)
        respuesta = self.client.post(reverse('configuracion_bot'), datos, follow=True)
        self.assertContains(respuesta, 'Hola desde el panel')
        self.assertContains(respuesta, 'name="prompt_sistema_ia"')
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.tono, 'formal')
        datos['zona_horaria'] = 'zona/inexistente'
        respuesta = self.client.post(reverse('configuracion_bot'), datos)
        self.assertContains(respuesta, 'Usa una zona válida')

    def test_editor_crea_pasos_y_opciones(self):
        self.client.post(reverse('crear_nodo'), {'nombre':'Inicio', 'tipo_nodo':'MENU', 'contenido_mensaje':'Elige', 'es_nodo_inicial':'on'})
        nodo = NodoBot.objects.get(empresa=self.empresa)
        self.client.post(reverse('crear_opcion', args=[nodo.pk]), {'entrada_esperada':'1', 'etiqueta':'Volver', 'nodo_siguiente':nodo.pk})
        respuesta = self.client.get(reverse('configuracion_bot'))
        self.assertContains(respuesta, reverse('guardar_nodo', args=[nodo.pk]))
        self.assertEqual(nodo.opciones_salida.count(), 1)

    def test_conversaciones_y_metricas_aisladas(self):
        ajena = SesionUsuario.objects.create(empresa=self.otra_empresa, telefono_cliente='AJENO', estado='humano')
        propia = SesionUsuario.objects.create(empresa=self.empresa, telefono_cliente='50611111111', estado='humano')
        HistorialChat.objects.create(sesion_usuario=propia, rol='user', contenido='<script>prueba</script>')
        respuesta = self.client.get(reverse('atencion_humana'), {'c':propia.pk})
        self.assertContains(respuesta, '&lt;script&gt;prueba&lt;/script&gt;')
        self.assertNotContains(respuesta, 'AJENO')
        actualizacion = self.client.get(reverse('atencion_humana'), {'c':propia.pk, 'formato':'json'})
        self.assertEqual(actualizacion.json()['mensajes'][0]['contenido'], '<script>prueba</script>')
        self.assertEqual(self.client.get(reverse('atencion_humana'), {'c':ajena.pk, 'formato':'json'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('atencion_humana'), {'c':ajena.pk}).status_code, 404)
        self.assertEqual(self.client.post(reverse('responder_agente', args=[ajena.pk]), {'texto':'hola', 'id_envio':str(uuid.uuid4())}).status_code, 404)
        self.assertEqual(self.client.get(reverse('metricas')).context['conversaciones'], 1)

    @patch('core.views.enviar_mensaje_whatsapp', return_value={'estado':'enviado'})
    def test_respuesta_humana_y_despedida(self, enviar):
        self.sesion.estado = 'conectado'
        self.sesion.save()
        chat = SesionUsuario.objects.create(empresa=self.empresa, telefono_cliente='50611111111', estado='humano')
        respuesta = self.client.post(reverse('responder_agente', args=[chat.pk]), {'texto':'Hola cliente', 'id_envio':str(uuid.uuid4())})
        self.assertEqual(respuesta.json()['estado'], 'enviado')
        self.assertEqual(chat.historialchat_set.get().contenido, 'Hola cliente')
        self.empresa.despedida = 'Gracias por escribir'
        self.empresa.save()
        self.client.post(reverse('cambiar_estado_conversacion', args=[chat.pk, 'cerrada']))
        self.assertEqual(enviar.call_args.args[2], 'Gracias por escribir')
        chat.refresh_from_db()
        self.assertEqual(chat.estado, 'cerrada')

    @patch('core.views.enviar_mensaje_whatsapp', side_effect=RuntimeError('fallo'))
    def test_error_de_envio_conserva_respuesta_pendiente(self, enviar):
        self.sesion.estado = 'conectado'
        self.sesion.save()
        chat = SesionUsuario.objects.create(empresa=self.empresa, telefono_cliente='50611111111', estado='humano')
        with self.assertLogs('core.entregas', level='ERROR'):
            respuesta = self.client.post(reverse('responder_agente', args=[chat.pk]), {'texto':'no enviado', 'id_envio':str(uuid.uuid4())})
        self.assertEqual(respuesta.json()['estado'], 'fallido')
        self.assertEqual(chat.historialchat_set.get().contenido, 'no enviado')
        self.assertEqual(chat.historialchat_set.get().estado_entrega, 'fallido')

    @patch('core.conversaciones.enviar_mensaje_whatsapp')
    def test_bienvenida_y_derivacion_por_frase(self, enviar):
        self.sesion.estado = 'conectado'
        self.sesion.save()
        self.empresa.bienvenida = 'Bienvenido'
        self.empresa.derivar_auto = True
        self.empresa.palabras_clave = 'persona'
        self.empresa.save()
        NodoBot.objects.create(empresa=self.empresa, nombre='inicio', tipo_nodo='TEXT', contenido_mensaje='Menu', es_nodo_inicial=True)
        procesar_mensaje_whatsapp(self.sesion.identificador, '50611111111', 'hola', 'uno')
        self.assertEqual(enviar.call_args_list[0].args[2], 'Bienvenido')
        procesar_mensaje_whatsapp(self.sesion.identificador, '50611111111', 'quiero una persona', 'dos')
        self.assertEqual(SesionUsuario.objects.get(empresa=self.empresa).estado, 'humano')
        self.assertEqual(HistorialChat.objects.filter(rol='assistant').count(), 3)

    def test_horario_diurno_y_nocturno(self):
        self.empresa.horario_inicio = time(8)
        self.empresa.horario_fin = time(17)
        self.assertFalse(fuera_del_horario(self.empresa, datetime(2026, 9, 29, 14, tzinfo=timezone.utc)))
        self.assertTrue(fuera_del_horario(self.empresa, datetime(2026, 9, 29, 23, tzinfo=timezone.utc)))
        self.empresa.horario_inicio = time(22)
        self.empresa.horario_fin = time(6)
        self.assertFalse(fuera_del_horario(self.empresa, datetime(2026, 9, 29, 7, tzinfo=timezone.utc)))

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    @patch('core.seguridad.secrets.randbelow', return_value=123456)
    def test_registro_y_recordarme(self, aleatorio):
        from core.models import LimiteAcceso
        self.client.logout()
        respuesta = self.client.post(reverse('registro'), {'username':'nuevo', 'first_name':'Nombre', 'email':'nuevo@example.com', 'password1':'Clave-segura-nueva-963', 'password2':'Clave-segura-nueva-963'})
        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(Empresa.objects.filter(propietario__username='nuevo').exists())
        self.client.post(reverse('verificar_codigo'), {'codigo':'123456'})
        self.assertTrue(Empresa.objects.filter(propietario__username='nuevo').exists())
        self.usuario.email = 'panel@example.com'
        self.usuario.save(update_fields=['email'])
        for recordar in ['', '1']:
            self.client.logout()
            LimiteAcceso.objects.all().delete()
            self.client.post(reverse('ingresar'), {'username':'panel', 'password':'Clave-segura-123', 'recordarme':recordar})
            self.assertNotIn('_auth_user_id', self.client.session)
            self.client.post(reverse('verificar_codigo'), {'codigo':'123456'})
            self.assertEqual(self.client.session.get_expire_at_browser_close(), not bool(recordar))

    @patch('core.conversaciones.enviar_mensaje_whatsapp')
    @patch('core.conversaciones.timezone.now')
    def test_aviso_fuera_de_horario_reemplaza_el_flujo(self, ahora, enviar):
        ahora.return_value = datetime(2026, 9, 29, 23, tzinfo=timezone.utc)
        self.sesion.estado = 'conectado'
        self.sesion.save()
        self.empresa.fuera_horario = True
        self.empresa.mensaje_fuera_horario = 'Volvemos mañana'
        self.empresa.save()
        procesar_mensaje_whatsapp(self.sesion.identificador, '50611111111', 'hola', 'fuera-horario')
        self.assertEqual(enviar.call_args.args[2], 'Volvemos mañana')
        self.assertEqual(enviar.call_count, 1)

    @patch('core.conversaciones.enviar_mensaje_whatsapp')
    @patch('core.conversaciones.generar_respuesta_ia', return_value='Olá')
    def test_tono_e_idioma_llegan_a_la_ia(self, generar, enviar):
        self.empresa.plan = 'corporativo'
        self.empresa.plan_hasta = datetime.now(timezone.utc) + timedelta(days=7)
        self.sesion.estado = 'conectado'
        self.sesion.save()
        self.empresa.ia_desde_primer_mensaje = True
        self.empresa.tono = 'formal'
        self.empresa.idioma = 'pt'
        self.empresa.save()
        procesar_mensaje_whatsapp(self.sesion.identificador, '50611111111', 'hola', 'idioma')
        instrucciones = generar.call_args.args[0][0]['content']
        self.assertIn('Portugués', instrucciones)
        self.assertIn('formal', instrucciones)

    def test_perfil_guarda_solo_la_cuenta_actual(self):
        self.client.post(reverse('perfil'), {'first_name':'Mi nombre', 'last_name':'Apellido', 'email':'yo@example.com'})
        self.usuario.refresh_from_db()
        self.otro_usuario.refresh_from_db()
        self.assertEqual(self.usuario.first_name, 'Mi nombre')
        self.assertEqual(self.otro_usuario.first_name, '')

    def test_descarga_pdf_no_permite_opciones_ajenas(self):
        from core.models import OpcionNodo
        nodo = NodoBot.objects.create(empresa=self.otra_empresa, nombre='privado', tipo_nodo='TEXT', contenido_mensaje='privado')
        opcion = OpcionNodo.objects.create(nodo_padre=nodo, nodo_siguiente=nodo, entrada_esperada='1')
        self.assertEqual(self.client.get(reverse('archivo_opcion', args=[opcion.pk])).status_code, 404)
