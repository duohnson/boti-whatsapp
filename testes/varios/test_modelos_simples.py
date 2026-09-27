from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import Empresa, NodoBot, OpcionNodo, SesionUsuario, SesionWhatsApp


class PruebasModelosSimples(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username='modelo_uno', password='clave-prueba')
        self.empresa = Empresa.objects.create(propietario=self.usuario)
        self.menu = NodoBot.objects.create(
            empresa=self.empresa,
            nombre='menu',
            tipo_nodo='MENU',
            contenido_mensaje='menu',
            es_nodo_inicial=True,
        )
        self.texto = NodoBot.objects.create(
            empresa=self.empresa,
            nombre='texto',
            tipo_nodo='TEXT',
            contenido_mensaje='texto',
        )

    def test_uno_empresa_inicia_activa(self):
        self.assertTrue(self.empresa.activo)

    def test_dos_empresa_tiene_limite_ia(self):
        self.assertEqual(self.empresa.limite_respuestas_ia, 100)

    def test_tres_sesion_whatsapp_tiene_identificador(self):
        sesion = SesionWhatsApp.objects.create(empresa=self.empresa)
        self.assertIsNotNone(sesion.identificador)

    def test_cuatro_sesion_usuario_inicia_con_bot(self):
        sesion = SesionUsuario.objects.create(empresa=self.empresa, telefono_cliente='50610000000')
        self.assertEqual(sesion.estado, 'bot')

    def test_cinco_opcion_muestra_etiqueta(self):
        opcion = OpcionNodo.objects.create(
            nodo_padre=self.menu,
            nodo_siguiente=self.texto,
            entrada_esperada='1',
            etiqueta='ver texto',
        )
        self.assertEqual(str(opcion), 'ver texto')

    def test_seis_opcion_sin_etiqueta_muestra_valor(self):
        opcion = OpcionNodo.objects.create(
            nodo_padre=self.menu,
            nodo_siguiente=self.texto,
            entrada_esperada='2',
        )
        self.assertEqual(str(opcion), '2')

    def test_siete_opcion_repetida_no_es_valida(self):
        OpcionNodo.objects.create(
            nodo_padre=self.menu,
            nodo_siguiente=self.texto,
            entrada_esperada='1',
        )
        opcion = OpcionNodo(
            nodo_padre=self.menu,
            nodo_siguiente=self.texto,
            entrada_esperada='1',
        )
        with self.assertRaises(ValidationError):
            opcion.full_clean()
