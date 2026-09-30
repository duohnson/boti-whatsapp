from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import Empresa, PerfilUsuario, CodigoCorreo, LimiteAcceso, AvisoPlan, SuscripcionPlan


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PruebasSeguridadCorreo(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username='cuenta', email='cuenta@example.com', password='Clave-anterior-963')
        self.empresa = Empresa.objects.create(propietario=self.usuario)
        self.azar = patch('core.seguridad.secrets.randbelow', return_value=123456)
        self.azar.start()
        self.addCleanup(self.azar.stop)

    def ingresar(self, **datos):
        return self.client.post(reverse('ingresar'), {'username':'cuenta', 'password':'Clave-anterior-963', **datos})

    def verificar(self, codigo='123456'):
        return self.client.post(reverse('verificar_codigo'), {'codigo': codigo})

    def test_login_no_abre_sesion_sin_codigo(self):
        self.ingresar()
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(len(mail.outbox), 1)
        self.verificar()
        self.assertEqual(int(self.client.session['_auth_user_id']), self.usuario.pk)
        self.assertEqual(PerfilUsuario.objects.get(usuario=self.usuario).correo_verificado, self.usuario.email)

    def test_codigo_no_se_guarda_en_claro(self):
        self.ingresar()
        codigo = CodigoCorreo.objects.get()
        self.assertNotEqual(codigo.huella, '123456')
        self.assertNotIn('Clave-anterior-963', str(codigo.datos))
        self.assertEqual(len(codigo.huella), 64)

    def test_cinco_intentos_bloquean_codigo_correcto(self):
        self.ingresar()
        for _ in range(5):
            self.verificar('000000')
        self.verificar()
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(CodigoCorreo.objects.get().intentos, 5)

    def test_codigo_vencido_no_abre_sesion(self):
        self.ingresar()
        CodigoCorreo.objects.update(vence=timezone.now() - timedelta(seconds=1))
        self.verificar()
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_codigo_de_otra_sesion_no_sirve(self):
        self.ingresar()
        otro = Client()
        sesion = otro.session
        sesion['codigo_pendiente'] = self.client.session['codigo_pendiente']
        sesion.save()
        otro.post(reverse('verificar_codigo'), {'codigo':'123456'})
        self.assertNotIn('_auth_user_id', otro.session)

    def test_reenvio_inmediato_no_envia_otro(self):
        self.ingresar()
        self.client.post(reverse('reenviar_codigo'))
        self.assertEqual(len(mail.outbox), 1)

    def test_reenvio_invalida_codigo_anterior(self):
        self.ingresar()
        viejo = CodigoCorreo.objects.get()
        LimiteAcceso.objects.update(inicio=timezone.now() - timedelta(minutes=2))
        with patch('core.seguridad.secrets.randbelow', return_value=654321):
            self.client.post(reverse('reenviar_codigo'))
        viejo.refresh_from_db()
        self.assertTrue(viejo.usado)
        self.verificar('123456')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.verificar('654321')
        self.assertIn('_auth_user_id', self.client.session)

    @patch('core.seguridad.enviar_correo', side_effect=RuntimeError('smtp caido'))
    def test_fallo_smtp_no_da_acceso(self, enviar):
        respuesta = self.ingresar()
        self.assertContains(respuesta, 'No pudimos enviar')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertTrue(CodigoCorreo.objects.get().usado)

    def test_cambio_clave_invalida_codigo_de_login(self):
        self.ingresar()
        self.usuario.set_password('Otra-clave-582')
        self.usuario.save()
        self.verificar()
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_next_externo_se_descarta(self):
        self.ingresar(next='https://ajeno.example/')
        respuesta = self.verificar()
        self.assertEqual(respuesta.url, reverse('dashboard'))

    def test_registro_no_crea_usuario_antes_de_verificar(self):
        datos = {'username':'nuevo','email':'nuevo@example.com','first_name':'Nuevo','password1':'Clave-nueva-963','password2':'Clave-nueva-963'}
        self.client.post(reverse('registro'), datos)
        self.assertFalse(User.objects.filter(username='nuevo').exists())
        self.verificar()
        self.assertTrue(Empresa.objects.filter(propietario__username='nuevo').exists())
        self.assertEqual(User.objects.get(username='nuevo').email, 'nuevo@example.com')

    def test_email_duplicado_no_permite_cuenta_nueva(self):
        self.client.post(reverse('registro'), {'username':'nuevo','email':'CUENTA@example.com','first_name':'Nuevo','password1':'Clave-nueva-963','password2':'Clave-nueva-963'})
        self.assertFalse(CodigoCorreo.objects.exists())

    def test_perfil_no_cambia_correo_por_post_directo(self):
        self.client.force_login(self.usuario)
        self.client.post(reverse('perfil'), {'first_name':'Nombre','email':'intruso@example.com','telefono':'+53 5 1652038','organizacion':'Prueba','ubicacion':'La Habana','cedula_juridica':'ABC-123','codigo_postal':'10100'})
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'cuenta@example.com')
        self.assertEqual(PerfilUsuario.objects.get(usuario=self.usuario).organizacion, 'Prueba')

    def test_correo_necesita_ambas_verificaciones(self):
        self.client.force_login(self.usuario)
        self.client.post(reverse('cambiar_correo'), {'correo':'nuevo@example.com','clave_actual':'Clave-anterior-963'})
        self.assertEqual(mail.outbox[-1].to, ['cuenta@example.com'])
        self.verificar()
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'cuenta@example.com')
        self.assertEqual(mail.outbox[-1].to, ['nuevo@example.com'])
        self.verificar()
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'nuevo@example.com')

    def test_clave_no_cambia_antes_de_codigo(self):
        self.client.force_login(self.usuario)
        self.client.post(reverse('cambiar_clave'), {'old_password':'Clave-anterior-963','new_password1':'Clave-distinta-852','new_password2':'Clave-distinta-852'})
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('Clave-anterior-963'))
        self.verificar()
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('Clave-distinta-852'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_limite_credenciales_fallidas(self):
        for _ in range(11):
            respuesta = self.client.post(reverse('ingresar'), {'username':'cuenta','password':'incorrecta'})
        self.assertContains(respuesta, 'Demasiados intentos')
        self.assertFalse(CodigoCorreo.objects.exists())

    def test_admin_no_omite_codigo(self):
        respuesta = self.client.get('/admin/login/')
        self.assertIn('/cuentas/ingresar/', respuesta.url)

    def test_correo_tiene_html_y_texto(self):
        self.ingresar()
        self.assertIn('123456', mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].alternatives[0].mimetype, 'text/html')
        self.assertIn('No compartas', mail.outbox[0].alternatives[0].content)

    def preparar_aviso(self):
        PerfilUsuario.objects.create(usuario=self.usuario, correo_verificado=self.usuario.email)
        self.empresa.plan = 'premium'
        self.empresa.plan_hasta = timezone.now() + timedelta(days=3)
        self.empresa.save()

    def test_recordatorio_unico_por_periodo(self):
        self.preparar_aviso()
        for _ in range(2):
            call_command('enviar_recordatorios', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(AvisoPlan.objects.get().estado, 'enviado')
        self.assertIn('por vencer', mail.outbox[0].subject)

    def test_recordatorio_renovacion_no_dice_cancelado(self):
        self.preparar_aviso()
        SuscripcionPlan.objects.create(empresa=self.empresa, plan='premium', periodo='semana', importe=1, estado='activo', paypal_plan='P-PRUEBA')
        call_command('enviar_recordatorios', stdout=StringIO())
        self.assertIn('renovación', mail.outbox[0].subject)
        self.assertIn('1.00 USD', mail.outbox[0].body)

    def test_no_avisa_fuera_de_ventana(self):
        self.preparar_aviso()
        self.empresa.plan_hasta = timezone.now() + timedelta(days=4)
        self.empresa.save()
        call_command('enviar_recordatorios', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 0)
