from django import forms
from .models import Empresa, NodoBot, OpcionNodo


class ConfiguracionEmpresaForm(forms.ModelForm):
    # aca el cliente deja su contexto y decide cuando entra la ia
    class Meta:
        model = Empresa
        fields = ['prompt_sistema_ia', 'ia_desde_primer_mensaje']
        labels = {
            'prompt_sistema_ia': 'Contexto e instrucciones para la IA',
            'ia_desde_primer_mensaje': 'Responder con IA desde el primer mensaje entrante',
        }
        widgets = {
            'prompt_sistema_ia': forms.Textarea(attrs={'rows': 6}),
        }


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
        self.fields['tipo_nodo'].choices = [
            eleccion for eleccion in NodoBot.TIPO_NODO_OPCIONES
            if eleccion[0] != 'AI_AGENT'
        ] + [('AI_AGENT', 'Responder con IA')]

    def save(self, commit=True):
        nodo = super().save(commit=False)
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
