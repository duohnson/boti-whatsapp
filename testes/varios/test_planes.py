import json
from datetime import datetime, timedelta, timezone as zona
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import Empresa, NodoBot, SesionWhatsApp, SesionUsuario, HistorialChat, PagoPlan, SuscripcionPlan
from core.planes import actualizar_cupo, contar_respuesta, puede_responder, sumar_meses, activar_pago
from core.conversaciones import procesar_mensaje_whatsapp
from core.paypal import registrar_cobro, ErrorPaypal, validar_plan, frecuencia


class PruebasPlanes(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username='titular')
        self.empresa = Empresa.objects.create(propietario=self.usuario)
        self.client.force_login(self.usuario)
        self.whatsapp = SesionWhatsApp.objects.create(empresa=self.empresa, estado='conectado')
        NodoBot.objects.create(empresa=self.empresa, nombre='inicio', tipo_nodo='TEXT', contenido_mensaje='hola', es_nodo_inicial=True)

    def suscripcion(self, **datos):
        return SuscripcionPlan.objects.create(empresa=self.empresa, plan='premium', periodo='semana', importe=1, paypal_id='I-PRUEBA', paypal_plan='P-PRUEBA', **datos)

    def test_cuenta_nueva_gratis(self):
        self.assertEqual(self.empresa.plan, 'gratis')
        self.assertEqual(self.empresa.respuestas_gratis, 0)
        respuesta = self.client.get(reverse('planes'))
        self.assertNotContains(respuesta, 'Cancelar renovación</button>')
        self.assertContains(respuesta, '50 respuestas')
        self.assertContains(respuesta, 'https://wa.me/5351652038')

    @patch('core.conversaciones.enviar_mensaje_whatsapp', return_value={'estado':'enviado'})
    def test_respuesta_cincuenta_bloquea_y_reintento_no_cuenta(self, enviar):
        self.empresa.respuestas_gratis = 49
        self.empresa.save()
        ahora = timezone.now()
        procesar_mensaje_whatsapp(self.whatsapp.identificador, '123456789', 'hola', 'entrada-1')
        procesar_mensaje_whatsapp(self.whatsapp.identificador, '123456789', 'hola', 'entrada-1')
        procesar_mensaje_whatsapp(self.whatsapp.identificador, '123456789', 'otra', 'entrada-2')
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.respuestas_gratis, 50)
        self.assertEqual(self.empresa.respuestas_totales, 1)
        self.assertEqual(enviar.call_count, 1)
        self.assertGreaterEqual(self.empresa.bloqueado_hasta, sumar_meses(ahora))

    def test_mes_calendario_y_reinicio(self):
        enero = datetime(2026, 1, 31, 12, tzinfo=zona.utc)
        self.assertEqual(sumar_meses(enero), datetime(2026, 2, 28, 12, tzinfo=zona.utc))
        self.empresa.respuestas_gratis = 50
        self.empresa.bloqueado_hasta = sumar_meses(enero)
        actualizar_cupo(self.empresa, self.empresa.bloqueado_hasta)
        self.assertTrue(puede_responder(self.empresa))
        self.assertEqual(self.empresa.respuestas_gratis, 0)

    def test_pago_y_renovacion_no_reponen_ia(self):
        suscripcion = self.suscripcion()
        ahora = timezone.now()
        registrar_cobro(suscripcion, 'cobro1', '1.00', 'USD', ahora)
        self.empresa.refresh_from_db()
        self.empresa.respuestas_ia_utilizadas = 200
        self.empresa.save()
        registrar_cobro(suscripcion, 'cobro1', '1.00', 'USD', ahora)
        registrar_cobro(suscripcion, 'cobro2', '1.00', 'USD', ahora + timedelta(days=7))
        self.empresa.refresh_from_db()
        self.assertEqual(PagoPlan.objects.count(), 2)
        self.assertEqual(self.empresa.plan_hasta, ahora + timedelta(days=14))
        self.assertEqual(self.empresa.respuestas_ia_utilizadas, 200)
        self.assertEqual(self.empresa.limite_respuestas_ia, 0)

    def test_reinicio_mensual_ia(self):
        self.empresa.plan = 'corporativo'
        self.empresa.plan_hasta = timezone.now() + timedelta(days=180)
        self.empresa.ciclo_ia_hasta = timezone.now() - timedelta(seconds=1)
        self.empresa.respuestas_ia_utilizadas = 1000
        actualizar_cupo(self.empresa)
        self.assertEqual(self.empresa.respuestas_ia_utilizadas, 0)
        self.assertEqual(self.empresa.limite_respuestas_ia, 1000)

    def test_vencimiento_no_regala_cupo_gratis(self):
        self.empresa.plan = 'premium'
        self.empresa.plan_hasta = timezone.now() - timedelta(seconds=1)
        self.empresa.respuestas_gratis = 50
        self.empresa.bloqueado_hasta = timezone.now() + timedelta(days=5)
        actualizar_cupo(self.empresa)
        self.assertEqual(self.empresa.plan, 'gratis')
        self.assertFalse(puede_responder(self.empresa))

    def test_cobro_importe_incorrecto_no_activa(self):
        suscripcion = self.suscripcion()
        with self.assertRaises(ErrorPaypal):
            registrar_cobro(suscripcion, 'cobro', '0.01', 'USD', timezone.now())
        self.assertFalse(PagoPlan.objects.exists())
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.plan, 'gratis')

    @patch('core.paypal.verificar_evento', return_value=False)
    def test_webhook_falso_rechazado(self, verificar):
        respuesta = self.client.post(reverse('webhook_paypal'), json.dumps({'event_type':'PAYMENT.SALE.COMPLETED'}), content_type='application/json')
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(PagoPlan.objects.exists())

    @patch('core.paypal.consultar_suscripcion')
    @patch('core.paypal.verificar_evento', return_value=True)
    def test_webhook_repetido_no_extiende_dos_veces(self, verificar, consultar):
        self.suscripcion()
        evento = {'event_type': 'PAYMENT.SALE.COMPLETED', 'resource': {'billing_agreement_id':'I-PRUEBA', 'id':'venta', 'amount':{'total':'1.00','currency':'USD'}, 'create_time':timezone.now().isoformat()}}
        for _ in range(2):
            respuesta = self.client.post(reverse('webhook_paypal'), json.dumps(evento), content_type='application/json')
            self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(PagoPlan.objects.count(), 1)

    @patch('core.paypal.solicitar', return_value={})
    @patch('core.paypal.consultar_suscripcion', return_value={'status':'ACTIVE'})
    def test_cancelar_conserva_periodo(self, consultar, solicitar):
        suscripcion = self.suscripcion(estado='activo')
        registrar_cobro(suscripcion, 'venta', '1', 'USD', timezone.now())
        self.empresa.refresh_from_db()
        fin = self.empresa.plan_hasta
        respuesta = self.client.post(reverse('cancelar_plan', args=[suscripcion.pk]))
        self.assertEqual(respuesta.status_code, 302)
        self.empresa.refresh_from_db()
        suscripcion.refresh_from_db()
        self.assertEqual(suscripcion.estado, 'cancelado')
        self.assertEqual(self.empresa.plan_hasta, fin)
        self.assertEqual(self.empresa.plan, 'premium')

    def test_otra_empresa_no_cancela(self):
        suscripcion = self.suscripcion()
        otro = User.objects.create_user(username='otro')
        Empresa.objects.create(propietario=otro)
        self.client.force_login(otro)
        self.assertEqual(self.client.post(reverse('cancelar_plan', args=[suscripcion.pk])).status_code, 404)

    @patch('core.paypal.crear_suscripcion')
    def test_cuba_no_crea_paypal(self, crear):
        self.client.post(reverse('suscribir_plan'), {'plan':'premium','periodo':'semana','mercado':'cuba','acepto':'1'})
        crear.assert_not_called()
        self.assertFalse(SuscripcionPlan.objects.exists())

    @override_settings(PAYPAL_WEBHOOK_ID='webhook', PAYPAL_PLANES={'premium_semana':'P-PRUEBA'})
    @patch('core.paypal.crear_suscripcion', return_value='https://www.sandbox.paypal.com/checkout')
    def test_precio_se_calcula_en_servidor(self, crear):
        respuesta = self.client.post(reverse('suscribir_plan'), {'plan':'premium','periodo':'semana','mercado':'internacional','acepto':'1','importe':'0.01'})
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(SuscripcionPlan.objects.get().importe, Decimal('1'))

    @patch('core.paypal.sincronizar')
    def test_redireccion_no_activa_sin_cobro(self, sincronizar):
        self.suscripcion()
        self.client.get(reverse('retorno_paypal'), {'subscription_id':'I-PRUEBA'})
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.plan, 'gratis')

    @patch('core.paypal.solicitar')
    def test_catalogo_precio_distinto_rechazado(self, solicitar):
        solicitar.return_value = {'status':'ACTIVE','billing_cycles':[{'tenure_type':'REGULAR','total_cycles':0,'frequency':frecuencia('semana'),'pricing_scheme':{'fixed_price':{'value':'2','currency_code':'USD'}}}]}
        with self.assertRaises(ErrorPaypal):
            validar_plan('P-PRUEBA', 'premium', 'semana')

    def test_agente_bloqueado_no_envia(self):
        import uuid
        self.empresa.respuestas_gratis = 50
        self.empresa.bloqueado_hasta = timezone.now() + timedelta(days=10)
        self.empresa.save()
        chat = SesionUsuario.objects.create(empresa=self.empresa, telefono_cliente='123', estado='humano')
        respuesta = self.client.post(reverse('responder_agente', args=[chat.pk]), {'texto':'hola','id_envio':str(uuid.uuid4())})
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(HistorialChat.objects.exists())

    @patch('core.conversaciones.generar_respuesta_ia')
    @patch('core.conversaciones.enviar_mensaje_whatsapp', return_value={'estado':'enviado'})
    def test_ultima_respuesta_no_genera_ia_sin_cupo(self, enviar, generar):
        self.empresa.respuestas_gratis = 49
        self.empresa.ia_desde_primer_mensaje = True
        self.empresa.bienvenida = 'bienvenido'
        self.empresa.save()
        procesar_mensaje_whatsapp(self.whatsapp.identificador, '123', 'hola', 'uno')
        self.empresa.refresh_from_db()
        generar.assert_not_called()
        self.assertEqual(self.empresa.respuestas_gratis, 50)
        self.assertEqual(enviar.call_count, 1)

    @patch('core.conversaciones.generar_respuesta_ia')
    @patch('core.conversaciones.enviar_mensaje_whatsapp', return_value={'estado':'enviado'})
    def test_corporativo_agotado_conserva_flujos(self, enviar, generar):
        self.empresa.plan = 'corporativo'
        self.empresa.plan_hasta = timezone.now() + timedelta(days=10)
        self.empresa.respuestas_ia_utilizadas = 1000
        self.empresa.ia_desde_primer_mensaje = True
        self.empresa.save()
        procesar_mensaje_whatsapp(self.whatsapp.identificador, '123', 'hola', 'uno')
        generar.assert_not_called()
        self.empresa.ia_desde_primer_mensaje = False
        self.empresa.save(update_fields=['ia_desde_primer_mensaje'])
        procesar_mensaje_whatsapp(self.whatsapp.identificador, '456', 'hola', 'dos')
        self.assertEqual(enviar.call_count, 2)

    @patch('core.paypal.consultar_suscripcion', side_effect=ErrorPaypal('sin conexion'))
    def test_cancelacion_fallida_no_cambia_estado(self, consultar):
        suscripcion = self.suscripcion(estado='activo')
        self.client.post(reverse('cancelar_plan', args=[suscripcion.pk]))
        suscripcion.refresh_from_db()
        self.assertEqual(suscripcion.estado, 'activo')

    @patch('core.paypal.verificar_evento', return_value=True)
    def test_reembolso_no_se_reactiva_al_consultar_venta(self, verificar):
        suscripcion = self.suscripcion()
        fecha = timezone.now()
        registrar_cobro(suscripcion, 'venta', '1', 'USD', fecha)
        evento = {'event_type':'PAYMENT.SALE.REFUNDED','resource':{'sale_id':'venta','id':'reembolso'}}
        self.assertEqual(self.client.post(reverse('webhook_paypal'), json.dumps(evento), content_type='application/json').status_code, 200)
        registrar_cobro(suscripcion, 'venta', '1', 'USD', fecha)
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.plan, 'gratis')
        self.assertEqual(PagoPlan.objects.get().estado, 'revisar')

    @override_settings(PAYPAL_WEBHOOK_ID='webhook')
    @patch('core.paypal.solicitar', return_value={'verification_status':'SUCCESS'})
    def test_verificacion_firma_usa_id_configurado(self, solicitar):
        from django.test import RequestFactory
        from core.paypal import verificar_evento
        cabeceras = {f'HTTP_PAYPAL_{nombre}':'valor' for nombre in ['AUTH_ALGO','CERT_URL','TRANSMISSION_ID','TRANSMISSION_SIG','TRANSMISSION_TIME']}
        solicitud = RequestFactory().post('/', **cabeceras)
        self.assertTrue(verificar_evento(solicitud, {'id':'evento'}))
        self.assertEqual(solicitar.call_args.args[1]['webhook_id'], 'webhook')

    @override_settings(PAYPAL_WEBHOOK_ID='webhook', PAYPAL_PLANES={'premium_semana':'P-PRUEBA'})
    @patch('core.paypal.crear_suscripcion', return_value='https://www.sandbox.paypal.com/checkout')
    def test_reintentar_creacion_conserva_identificador(self, crear):
        datos = {'plan':'premium','periodo':'semana','mercado':'internacional','acepto':'1'}
        self.client.post(reverse('suscribir_plan'), datos)
        self.client.post(reverse('suscribir_plan'), datos)
        self.assertEqual(SuscripcionPlan.objects.count(), 1)
        self.assertEqual(crear.call_args_list[0].args[0].identificador, crear.call_args_list[1].args[0].identificador)

    def test_configuracion_no_permite_autocontratar(self):
        from django.forms.models import model_to_dict
        from core.forms import ConfiguracionEmpresaForm
        datos = model_to_dict(self.empresa, fields=ConfiguracionEmpresaForm.Meta.fields)
        datos.update(plan='corporativo', respuestas_gratis=0, limite_respuestas_ia=99999)
        self.empresa.respuestas_gratis = 35
        self.empresa.save()
        self.client.post(reverse('configuracion_bot'), datos)
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.plan, 'gratis')
        self.assertEqual(self.empresa.respuestas_gratis, 35)
        self.assertEqual(self.empresa.limite_respuestas_ia, 0)

    @patch('core.conversaciones.generar_respuesta_ia')
    @patch('core.conversaciones.enviar_mensaje_whatsapp', return_value={'estado': 'enviado'})
    def test_planes_sin_ia_recuperan_flujo_y_derivan_nodo_ia(self, enviar, generar):
        for plan in ['gratis', 'premium']:
            with self.subTest(plan=plan):
                self.empresa.plan = plan
                self.empresa.plan_hasta = timezone.now() + timedelta(days=7)
                self.empresa.ia_desde_primer_mensaje = True
                self.empresa.limite_respuestas_ia = 99999
                self.empresa.save()
                nodo = NodoBot.objects.get(empresa=self.empresa)
                nodo.tipo_nodo = 'TEXT'
                nodo.save()
                procesar_mensaje_whatsapp(self.whatsapp.identificador, plan, 'hola', plan)
                self.assertEqual(enviar.call_args.args[2], 'hola')
                nodo.tipo_nodo = 'AI_AGENT'
                nodo.save()
                procesar_mensaje_whatsapp(self.whatsapp.identificador, plan + '-ia', 'hola', plan + '-ia')
                self.assertEqual(SesionUsuario.objects.get(telefono_cliente=plan + '-ia').estado, 'humano')
                self.empresa.refresh_from_db()
                self.assertEqual(self.empresa.limite_respuestas_ia, 0)
        generar.assert_not_called()

    def test_premium_muestra_ilimitado_sin_contador_ia(self):
        self.empresa.plan = 'premium'
        self.empresa.plan_hasta = timezone.now() + timedelta(days=7)
        self.empresa.save()
        respuesta = self.client.get(reverse('planes'))
        self.assertContains(respuesta, 'Nodos, flujos y respuestas de flujo ilimitados. Sin IA.')
        self.assertNotContains(respuesta, '<progress')
        self.assertContains(respuesta, '1000 respuestas de IA al mes')

    def test_simulador_premium_deriva_ia_sin_consumir(self):
        self.empresa.plan = 'premium'
        self.empresa.plan_hasta = timezone.now() + timedelta(days=7)
        self.empresa.save()
        NodoBot.objects.filter(empresa=self.empresa).update(tipo_nodo='AI_AGENT')
        respuesta = self.client.post(reverse('simulador'), {'texto': 'hola'})
        self.assertEqual(respuesta.context['simulacion']['estado'], 'humano')
        self.assertContains(respuesta, 'La IA requiere el plan Corporativo.')
        self.assertFalse(HistorialChat.objects.exists())

    @patch('core.conversaciones.generar_respuesta_ia', return_value='respuesta ia')
    @patch('core.conversaciones.enviar_mensaje_whatsapp', return_value={'estado': 'enviado'})
    def test_corporativo_permite_mil_y_bloquea_la_siguiente(self, enviar, generar):
        self.empresa.plan = 'corporativo'
        self.empresa.plan_hasta = timezone.now() + timedelta(days=7)
        self.empresa.respuestas_ia_utilizadas = 999
        self.empresa.ia_desde_primer_mensaje = True
        self.empresa.save()
        for numero in ['uno', 'dos']:
            procesar_mensaje_whatsapp(self.whatsapp.identificador, numero, 'hola', numero)
        self.empresa.refresh_from_db()
        self.assertEqual(generar.call_count, 1)
        self.assertEqual(self.empresa.respuestas_ia_utilizadas, 1000)
        self.assertEqual(enviar.call_count, 2)

    def test_cobro_antiguo_no_cambia_plan_actual(self):
        suscripcion = self.suscripcion()
        self.empresa.plan = 'corporativo'
        self.empresa.plan_hasta = timezone.now() + timedelta(days=20)
        self.empresa.save()
        registrar_cobro(suscripcion, 'antiguo', '1', 'USD', timezone.now() - timedelta(days=40))
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.plan, 'corporativo')
        self.assertEqual(PagoPlan.objects.get().estado, 'completado')
