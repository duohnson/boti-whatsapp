from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False)
class PruebasAccesoWeb(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = User.objects.create_user(
            username='acceso_web', email='acceso@example.com', password='clave-prueba-web'
        )

    def test_visitante_llega_al_formulario_desde_la_raiz(self):
        respuesta = self.client.get('/', follow=True)
        self.assertEqual(respuesta.redirect_chain, [
            ('/api/dashboard/', 302),
            ('/cuentas/ingresar/?next=/api/dashboard/', 302),
        ])
        self.assertContains(respuesta, 'action="/cuentas/ingresar/"')
        self.assertContains(respuesta, 'name="next" value="/api/dashboard/"')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    @patch('core.seguridad.secrets.randbelow', return_value=123456)
    def test_ingreso_correcto_abre_dashboard_y_permite_salir(self, aleatorio):
        respuesta = self.client.post(reverse('ingresar'), {
            'username': self.usuario.username,
            'password': 'clave-prueba-web',
            'next': reverse('dashboard'),
        }, follow=True)
        self.assertRedirects(respuesta, reverse('verificar_codigo'))
        respuesta = self.client.post(reverse('verificar_codigo'), {'codigo':'123456'}, follow=True)
        self.assertRedirects(respuesta, reverse('dashboard'))
        self.assertContains(respuesta, 'action="/cuentas/salir/"')
        self.assertRedirects(
            self.client.post(reverse('salir')), reverse('ingresar')
        )

    def test_clave_incorrecta_muestra_error_sin_fallar(self):
        respuesta = self.client.post(reverse('ingresar'), {
            'username': self.usuario.username, 'password': 'incorrecta',
        })
        self.assertContains(respuesta, 'Usuario o contraseña incorrectos')

    def test_registro_se_renderiza(self):
        self.assertContains(
            self.client.get(reverse('registro')), 'href="/cuentas/ingresar/"'
        )

    def test_paginas_del_panel_se_renderizan(self):
        self.client.force_login(self.usuario)
        for nombre in ('dashboard', 'configuracion_bot', 'atencion_humana'):
            with self.subTest(pagina=nombre):
                self.assertEqual(self.client.get(reverse(nombre)).status_code, 200)
