import os
import logging
import requests

logger = logging.getLogger(__name__)

# modelos ia distintos para reduncancia, se pueden agregar mas, no configurable en panel admin, solo disponible en .env

class ErrorProveedorIA(Exception):
    # indicar que ningun proveedor pudo generar una respuesta
    pass


def proveedores_ia_activos():
    # ordenar los proveedores activos por prioridad
    proveedores = []
    configuraciones = {
        'openai': ('IA_OPENAI_ACTIVA', 'OPENAI_API_KEY'),
        'gemini': ('IA_GEMINI_ACTIVA', 'GEMINI_API_KEY'),
        'claude': ('IA_CLAUDE_ACTIVA', 'CLAUDE_API_KEY'),
    }
    principal = os.environ.get('IA_PROVEEDOR_PRINCIPAL', '').strip().lower()
    respaldo = [valor.strip().lower() for valor in os.environ.get('IA_PROVEEDORES_RESPALDO', '').split(',') if valor.strip()]
    # evitar proveedores repetidos y proveedores sin clave
    for proveedor in [principal, *respaldo, *configuraciones]:
        if proveedor in proveedores or proveedor not in configuraciones:
            continue
        variable_activa, variable_clave = configuraciones[proveedor]
        if os.environ.get(variable_activa, '0') == '1' and os.environ.get(variable_clave):
            proveedores.append(proveedor)
    return proveedores


def generar_respuesta_ia(mensajes):
    # probar el siguiente proveedor si el actual falla
    proveedores = proveedores_ia_activos()
    if not proveedores:
        raise ErrorProveedorIA('No hay un proveedor de IA activo y configurado.')
    for proveedor in proveedores:
        try:
            return _generar_respuesta(proveedor, mensajes)
        except (requests.RequestException, KeyError, TypeError, ValueError) as error:
            logger.warning('El proveedor de IA %s no respondió correctamente: %s', proveedor, error)
    raise ErrorProveedorIA('Los proveedores de IA activos no pudieron responder.')


def _generar_respuesta(proveedor, mensajes):
    # adaptar el historial al formato de cada proveedor
    if proveedor == 'openai':
        respuesta = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers={'Authorization': f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={'model': os.environ.get('OPENAI_MODELO', 'gpt-4o-mini'), 'messages': mensajes, 'temperature': 0.7},
            timeout=45,
        )
        respuesta.raise_for_status()
        return respuesta.json()['choices'][0]['message']['content'].strip()
    if proveedor == 'gemini':
        # gemini recibe el historial como un solo contenido
        modelo = os.environ.get('GEMINI_MODELO', 'gemini-2.0-flash')
        contenido = '\n'.join(f"{mensaje['role']}: {mensaje['content']}" for mensaje in mensajes)
        respuesta = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={os.environ["GEMINI_API_KEY"]}',
            json={'contents': [{'parts': [{'text': contenido}]}]},
            timeout=45,
        )
        respuesta.raise_for_status()
        return respuesta.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    if proveedor == 'claude':
        # claude separa las instrucciones del historial del chat
        sistema = next((mensaje['content'] for mensaje in mensajes if mensaje['role'] == 'system'), '')
        conversacion = [mensaje for mensaje in mensajes if mensaje['role'] != 'system']
        respuesta = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': os.environ['CLAUDE_API_KEY'],
                'anthropic-version': '2023-06-01',
            },
            json={
                'model': os.environ.get('CLAUDE_MODELO', 'claude-3-5-haiku-latest'),
                'max_tokens': 1024,
                'system': sistema,
                'messages': conversacion,
            },
            timeout=45,
        )
        respuesta.raise_for_status()
        return respuesta.json()['content'][0]['text'].strip()
    raise ErrorProveedorIA('Proveedor de IA no compatible.')
