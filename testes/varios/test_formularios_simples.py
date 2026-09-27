from django.contrib.auth.models import User
from django.test import TestCase

from core.forms import ConfiguracionEmpresaForm, NodoBotForm, OpcionNodoForm
from core.models import Empresa, NodoBot


class PruebasFormulariosSimples(TestCase):
    def setUp(self):
        usuario_uno = User.objects.create_user(username='formulario_uno', password='clave-prueba')
        usuario_dos = User.objects.create_user(username='formulario_dos', password='clave-prueba')
        self.empresa_uno = Empresa.objects.create(propietario=usuario_uno)
        self.empresa_dos = Empresa.objects.create(propietario=usuario_dos)
        self.nodo_uno = NodoBot.objects.create(
            empresa=self.empresa_uno,
            nombre='nodo uno',
            tipo_nodo='TEXT',
            contenido_mensaje='uno',
        )
        self.nodo_dos = NodoBot.objects.create(
            empresa=self.empresa_dos,
            nombre='nodo dos',
            tipo_nodo='TEXT',
            contenido_mensaje='dos',
        )

    def test_uno_formulario_empresa_es_valido(self):
        formulario = ConfiguracionEmpresaForm({'prompt_sistema_ia': 'responde corto'}, instance=self.empresa_uno)
        self.assertTrue(formulario.is_valid())

    def test_dos_formulario_nodo_es_valido(self):
        formulario = NodoBotForm(
            {'nombre': 'nuevo paso', 'tipo_nodo': 'TEXT', 'contenido_mensaje': 'mensaje'},
            empresa=self.empresa_uno,
        )
        self.assertTrue(formulario.is_valid())

    def test_tres_formulario_nodo_guarda_empresa(self):
        formulario = NodoBotForm(
            {'nombre': 'nuevo paso', 'tipo_nodo': 'TEXT', 'contenido_mensaje': 'mensaje'},
            empresa=self.empresa_uno,
        )
        nodo = formulario.save()
        self.assertEqual(nodo.empresa, self.empresa_uno)

    def test_cuatro_formulario_opcion_muestra_nodos_propios(self):
        formulario = OpcionNodoForm(empresa=self.empresa_uno)
        nodos = list(formulario.fields['nodo_siguiente'].queryset)
        self.assertIn(self.nodo_uno, nodos)

    def test_cinco_formulario_opcion_oculta_nodos_ajenos(self):
        formulario = OpcionNodoForm(empresa=self.empresa_uno)
        nodos = list(formulario.fields['nodo_siguiente'].queryset)
        self.assertNotIn(self.nodo_dos, nodos)

    def test_seis_formulario_opcion_pide_valor(self):
        formulario = OpcionNodoForm(
            {'etiqueta': 'ver', 'nodo_siguiente': self.nodo_uno.pk},
            empresa=self.empresa_uno,
        )
        self.assertFalse(formulario.is_valid())
