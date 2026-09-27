from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.conversaciones import mensaje_con_opciones, normalizar_entrada, procesar_mensaje_whatsapp
from core.models import Empresa, HistorialChat, NodoBot, OpcionNodo, SesionUsuario, SesionWhatsApp


class PruebasBasicasBot(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username='prueba_basica', password='clave-prueba')
        self.empresa = Empresa.objects.create(propietario=self.usuario)
        self.sesion_whatsapp = SesionWhatsApp.objects.create(empresa=self.empresa, estado='conectado')
        self.menu = NodoBot.objects.create(
            empresa=self.empresa,
            nombre='menu principal',
            tipo_nodo='MENU',
            contenido_mensaje='elige una opcion',
            es_nodo_inicial=True,
        )
        self.informacion = NodoBot.objects.create(
            empresa=self.empresa,
            nombre='informacion',
            tipo_nodo='TEXT',
            contenido_mensaje='informacion basica',
        )
        self.opcion = OpcionNodo.objects.create(
            nodo_padre=self.menu,
            nodo_siguiente=self.informacion,
            entrada_esperada='1',
            etiqueta='ver informacion',
        )

    def test_uno_dashboard_pide_inicio_de_sesion(self):
        respuesta = self.client.get(reverse('dashboard'))
        self.assertEqual(respuesta.status_code, 302)

    def test_dos_dashboard_responde_200_con_usuario(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('dashboard'))
        self.assertEqual(respuesta.status_code, 200)

    def test_tres_configuracion_responde_200_con_usuario(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('configuracion_bot'))
        self.assertEqual(respuesta.status_code, 200)

    def test_cuatro_estado_whatsapp_responde_200(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('estado_whatsapp'))
        self.assertEqual(respuesta.status_code, 200)

    def test_cinco_estado_whatsapp_devuelve_conectado(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('estado_whatsapp'))
        self.assertEqual(respuesta.json()['estado'], 'conectado')

    def test_seis_normalizar_quita_espacios(self):
        self.assertEqual(normalizar_entrada('  hola  '), 'hola')

    def test_siete_normalizar_quita_punto(self):
        self.assertEqual(normalizar_entrada('1.'), '1')

    def test_ocho_normalizar_convierte_minusculas(self):
        self.assertEqual(normalizar_entrada('HOLA'), 'hola')

    def test_nueve_menu_muestra_opcion(self):
        texto = mensaje_con_opciones(self.menu)
        self.assertIn('1. ver informacion', texto)

    def test_diez_menu_muestra_contenido(self):
        texto = mensaje_con_opciones(self.menu)
        self.assertIn('elige una opcion', texto)

    def test_once_texto_sin_opciones_muestra_contenido(self):
        self.assertEqual(mensaje_con_opciones(self.informacion), 'informacion basica')

    def test_doce_opcion_guarda_destino(self):
        self.assertEqual(self.opcion.nodo_siguiente, self.informacion)

    def test_trece_mensaje_crea_conversacion(self):
        with patch('core.conversaciones.enviar_mensaje_whatsapp'):
            procesar_mensaje_whatsapp(self.sesion_whatsapp.identificador, '50611112222', 'hola', 'prueba-13')
        self.assertTrue(SesionUsuario.objects.filter(empresa=self.empresa, telefono_cliente='50611112222').exists())

    def test_catorce_mensaje_guarda_historial(self):
        with patch('core.conversaciones.enviar_mensaje_whatsapp'):
            procesar_mensaje_whatsapp(self.sesion_whatsapp.identificador, '50611112222', 'hola', 'prueba-14')
        self.assertTrue(HistorialChat.objects.filter(contenido='hola').exists())

    def test_quince_opcion_llega_al_paso_conectado(self):
        with patch('core.conversaciones.enviar_mensaje_whatsapp'):
            procesar_mensaje_whatsapp(self.sesion_whatsapp.identificador, '50611112222', 'hola', 'prueba-15-inicio')
            procesar_mensaje_whatsapp(self.sesion_whatsapp.identificador, '50611112222', '1', 'prueba-15-opcion')
        conversacion = SesionUsuario.objects.get(empresa=self.empresa, telefono_cliente='50611112222')
        self.assertIsNone(conversacion.nodo_actual)

    def test_dieciseis_mensaje_repetido_no_duplica_historial(self):
        with patch('core.conversaciones.enviar_mensaje_whatsapp'):
            procesar_mensaje_whatsapp(self.sesion_whatsapp.identificador, '50611112222', 'hola', 'prueba-16')
            procesar_mensaje_whatsapp(self.sesion_whatsapp.identificador, '50611112222', 'hola', 'prueba-16')
        self.assertEqual(HistorialChat.objects.filter(identificador_mensaje='prueba-16').count(), 1)

    def test_diecisiete_atencion_humana_responde_200(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('atencion_humana'))
        self.assertEqual(respuesta.status_code, 200)
