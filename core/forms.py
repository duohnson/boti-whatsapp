from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Empresa, NodoBot, OpcionNodo


class ConfiguracionEmpresaForm(forms.ModelForm):
    # aca el cliente deja su contexto y decide cuando entra la ia
    class Meta:
        model = Empresa
        fields = ['prompt_sistema_ia', 'ia_desde_primer_mensaje', 'bienvenida', 'despedida', 'tono', 'idioma', 'derivar_auto', 'palabras_clave', 'fuera_horario', 'horario_inicio', 'horario_fin', 'zona_horaria', 'mensaje_fuera_horario', 'reabrir_conversaciones', 'max_mensajes_ia', 'accion_limite_ia', 'mensaje_limite_ia']
        labels = {
            'reabrir_conversaciones': 'Reabrir el chat cuando el cliente vuelva a escribir',
            'max_mensajes_ia': 'Mensajes recientes que recuerda la IA (1 a 50)',
            'accion_limite_ia': 'Al agotar el saldo de IA',
            'mensaje_limite_ia': 'Aviso al agotar el saldo',
            'bienvenida': 'Bienvenida adicional al iniciar un chat',
            'despedida': 'Despedida al cerrar desde el panel',
            'tono': 'Tono de la IA', 'idioma': 'Idioma de la IA',
            'derivar_auto': 'Derivar a una persona por palabras clave',
            'palabras_clave': 'Palabras o frases separadas por comas',
            'fuera_horario': 'Responder con un aviso fuera del horario de atención',
            'horario_inicio': 'Inicio de atención diaria', 'horario_fin': 'Fin de atención diaria',
            'zona_horaria': 'Zona horaria', 'mensaje_fuera_horario': 'Aviso fuera de horario',
            'prompt_sistema_ia': 'Contexto e instrucciones para la IA',
            'ia_desde_primer_mensaje': 'Responder con IA desde el primer mensaje entrante',
        }
        widgets = {
            'prompt_sistema_ia': forms.Textarea(attrs={'rows': 4}),
            'mensaje_limite_ia': forms.Textarea(attrs={'rows': 2}),
            'bienvenida': forms.Textarea(attrs={'rows': 2}),
            'despedida': forms.Textarea(attrs={'rows': 2}),
            'mensaje_fuera_horario': forms.Textarea(attrs={'rows': 2}),
            'derivar_auto': forms.CheckboxInput(attrs={'aria-label': 'Derivar a una persona automáticamente'}),
            'fuera_horario': forms.CheckboxInput(attrs={'aria-label': 'Responder fuera de horario'}),
            'horario_inicio': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
            'horario_fin': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
        }


    def clean_zona_horaria(self):
        zona = self.cleaned_data['zona_horaria']
        try:
            ZoneInfo(zona)
        except (ZoneInfoNotFoundError, ValueError):
            raise forms.ValidationError('Usa una zona válida, por ejemplo America/Costa_Rica.')
        return zona

    def clean(self):
        datos = super().clean()
        if datos.get('fuera_horario') and datos.get('horario_inicio') == datos.get('horario_fin'):
            self.add_error('horario_fin', 'El inicio y el fin deben ser distintos.')
        if datos.get('derivar_auto') and not datos.get('palabras_clave', '').strip(' ,'):
            self.add_error('palabras_clave', 'Agrega al menos una palabra o frase.')
        return datos


class RegistroForm(UserCreationForm):
    first_name = forms.CharField(label='Nombre', max_length=150)
    email = forms.EmailField(label='Correo electrónico')

    class Meta(UserCreationForm.Meta):
        fields = ['username', 'first_name', 'email', 'password1', 'password2']


class PerfilForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        labels = {'first_name': 'Nombre', 'last_name': 'Apellidos', 'email': 'Correo electrónico'}


class NodoBotForm(forms.ModelForm):
    # cada tipo de paso define que hace el bot al llegar
    class Meta:
        model = NodoBot
        fields = ['nombre', 'tipo_nodo', 'contenido_mensaje', 'es_nodo_inicial']
        labels = {
            'nombre': 'Nombre interno del paso',
            'tipo_nodo': 'Qué debe hacer el bot',
            'contenido_mensaje': 'Mensaje que verá el cliente',
            'es_nodo_inicial': 'Usar como bienvenida al iniciar una conversación',
        }
        widgets = {
            'contenido_mensaje': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        # mantener ia como una opcion disponible del formulario
        self.fields['tipo_nodo'].choices = [
            eleccion for eleccion in NodoBot.TIPO_NODO_OPCIONES
            if eleccion[0] != 'AI_AGENT'
        ] + [('AI_AGENT', 'Responder con IA')]

    def save(self, commit=True):
        nodo = super().save(commit=False)
        # asociar cada paso con la empresa del usuario autenticado
        nodo.empresa = self.empresa
        if commit:
            if nodo.es_nodo_inicial:
                # dejo una sola bienvenida por empresa
                NodoBot.objects.filter(empresa=self.empresa, es_nodo_inicial=True).exclude(pk=nodo.pk).update(es_nodo_inicial=False)
            nodo.save()
            self.save_m2m()
        return nodo


class OpcionNodoForm(forms.ModelForm):
    # cada opcion puede tener su propio pdf o seguir sin adjunto
    class Meta:
        model = OpcionNodo
        fields = ['entrada_esperada', 'etiqueta', 'nodo_siguiente', 'archivo_pdf']
        labels = {
            'entrada_esperada': 'Valor que debe responder el cliente (por ejemplo, 5)',
            'etiqueta': 'Texto que se mostrará junto al valor',
            'nodo_siguiente': 'Paso que abrirá esta opción',
            'archivo_pdf': 'PDF opcional que se enviará al elegirla',
        }
        widgets = {
            'archivo_pdf': forms.ClearableFileInput(attrs={'accept': '.pdf,application/pdf'}),
        }

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        # dejo elegir solo pasos del mismo cliente
        self.fields['nodo_siguiente'].queryset = NodoBot.objects.filter(empresa=empresa).order_by('nombre')
        self.fields['archivo_pdf'].required = False
        self.fields['etiqueta'].required = False
        self.fields['entrada_esperada'].help_text = 'Cada valor debe ser único dentro de este paso.'
        self.fields['nodo_siguiente'].help_text = 'Puedes enlazar este paso con cualquier otro paso de tu flujo.'
