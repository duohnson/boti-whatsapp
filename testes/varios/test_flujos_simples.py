from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from core.conversaciones import procesar_mensaje_whatsapp
from core.models import Empresa, NodoBot, OpcionNodo, SesionUsuario, SesionWhatsApp


class PruebasFlujosSimples(TestCase):
    def setUp(self):
        usuario = User.objects.create_user(username='flujo_uno', password='clave-prueba')
        self.empresa = Empresa.objects.create(propietario=usuario)
        self.sesion_whatsapp = SesionWhatsApp.objects.create(empresa=self.empresa, estado='conectado')
        self.menu = NodoBot.objects.create(
            empresa=self.empresa,
            nombre='inicio',
            tipo_nodo='MENU',
            contenido_mensaje='elige',
            es_nodo_inicial=True,
        )

    def enviar_mensaje(self, texto, identificador):
        with patch('core.conversaciones.enviar_mensaje_whatsapp') as enviar:
            procesar_mensaje_whatsapp(self.sesion_whatsapp.identificador, '50620000000', texto, identificador)
        return enviar

    def test_uno_bienvenida_envia_menu(self):
        enviar = self.enviar_mensaje('hola', 'flujo-uno')
        self.assertIn('elige', enviar.call_args.args[2])

    def test_dos_opcion_humana_cambia_estado(self):
        humano = NodoBot.objects.create(empresa=self.empresa, nombre='humano', tipo_nodo='HUMAN_AGENT', contenido_mensaje='espera')
        OpcionNodo.objects.create(nodo_padre=self.menu, nodo_siguiente=humano, entrada_esperada='1')
        self.enviar_mensaje('hola', 'flujo-dos-inicio')
        self.enviar_mensaje('1', 'flujo-dos-opcion')
        conversacion = SesionUsuario.objects.get(empresa=self.empresa, telefono_cliente='50620000000')
        self.assertEqual(conversacion.estado, 'humano')

    def test_tres_opcion_final_cierra_chat(self):
        final = NodoBot.objects.create(empresa=self.empresa, nombre='final', tipo_nodo='END', contenido_mensaje='adios')
        OpcionNodo.objects.create(nodo_padre=self.menu, nodo_siguiente=final, entrada_esperada='2')
        self.enviar_mensaje('hola', 'flujo-tres-inicio')
        self.enviar_mensaje('2', 'flujo-tres-opcion')
        conversacion = SesionUsuario.objects.get(empresa=self.empresa, telefono_cliente='50620000000')
        self.assertEqual(conversacion.estado, 'cerrada')

    def test_cuatro_volver_abre_inicio(self):
        submenu = NodoBot.objects.create(empresa=self.empresa, nombre='submenu', tipo_nodo='MENU', contenido_mensaje='submenu')
        OpcionNodo.objects.create(nodo_padre=self.menu, nodo_siguiente=submenu, entrada_esperada='3')
        self.enviar_mensaje('hola', 'flujo-cuatro-inicio')
        self.enviar_mensaje('3', 'flujo-cuatro-opcion')
        self.enviar_mensaje('volver', 'flujo-cuatro-volver')
        conversacion = SesionUsuario.objects.get(empresa=self.empresa, telefono_cliente='50620000000')
        self.assertEqual(conversacion.nodo_actual, self.menu)

    def test_cinco_valor_invalido_mantiene_menu(self):
        self.enviar_mensaje('hola', 'flujo-cinco-inicio')
        self.enviar_mensaje('99', 'flujo-cinco-invalido')
        conversacion = SesionUsuario.objects.get(empresa=self.empresa, telefono_cliente='50620000000')
        self.assertEqual(conversacion.nodo_actual, self.menu)

    def test_seis_texto_final_limpia_nodo_actual(self):
        texto = NodoBot.objects.create(empresa=self.empresa, nombre='texto', tipo_nodo='TEXT', contenido_mensaje='respuesta')
        OpcionNodo.objects.create(nodo_padre=self.menu, nodo_siguiente=texto, entrada_esperada='4')
        self.enviar_mensaje('hola', 'flujo-seis-inicio')
        self.enviar_mensaje('4', 'flujo-seis-opcion')
        conversacion = SesionUsuario.objects.get(empresa=self.empresa, telefono_cliente='50620000000')
        self.assertIsNone(conversacion.nodo_actual)
