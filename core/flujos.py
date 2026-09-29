import re
from zoneinfo import ZoneInfo
from .models import NodoBot


def normalizar_entrada(entrada):
    return (entrada or '').strip().casefold().strip(' .,!;:¿?¡!')


def mensaje_con_opciones(nodo):
    opciones = list(nodo.opciones_salida.filter(nodo_siguiente__empresa_id=nodo.empresa_id).order_by('pk'))
    lineas = [f'{opcion.entrada_esperada}. {opcion.etiqueta or opcion.entrada_esperada}' for opcion in opciones]
    return nodo.contenido_mensaje + ('\n\n' + '\n'.join(lineas) if lineas else '')


def fuera_del_horario(empresa, ahora):
    hora = ahora.astimezone(ZoneInfo(empresa.zona_horaria)).time()
    inicio, fin = empresa.horario_inicio, empresa.horario_fin
    return not (inicio <= hora < fin if inicio < fin else hora >= inicio or hora < fin)


def pide_atencion_humana(empresa, texto):
    return any(re.search(r'(?<!\w)' + re.escape(frase.strip().casefold()) + r'(?!\w)', normalizar_entrada(texto))
               for frase in empresa.palabras_clave.split(',') if frase.strip())


def resolver_turno(empresa, nodo_actual, estado, nueva, texto, ahora):
    # el simulador y whatsapp recorren los mismos pasos
    resultado = {'nodo': nodo_actual, 'estado': estado, 'salidas': [], 'ia': False, 'motivo': ''}
    def aviso(mensaje, motivo):
        resultado['salidas'].append({'texto': mensaje, 'opcion': None})
        resultado['motivo'] = motivo
        return resultado
    if estado == 'cerrada':
        if not empresa.reabrir_conversaciones:
            resultado['motivo'] = 'El chat permanece cerrado por configuración.'
            return resultado
        estado, nueva, nodo_actual = 'bot', True, None
        resultado.update(estado='bot', nodo=None)
    if estado == 'humano':
        resultado['motivo'] = 'La conversación espera una respuesta humana.'
        return resultado
    if empresa.derivar_auto and pide_atencion_humana(empresa, texto):
        resultado['estado'] = 'humano'
        mensaje = empresa.mensaje_fuera_horario if empresa.fuera_horario and fuera_del_horario(empresa, ahora) else 'Una persona continuará esta conversación.'
        return aviso(mensaje, 'Se detectó una palabra de derivación.')
    if empresa.fuera_horario and fuera_del_horario(empresa, ahora):
        return aviso(empresa.mensaje_fuera_horario, 'Fuera del horario configurado.')
    if nueva and empresa.bienvenida:
        resultado['salidas'].append({'texto': empresa.bienvenida, 'opcion': None})
    nodos = NodoBot.objects.filter(empresa=empresa)
    inicial = nodos.filter(es_nodo_inicial=True).first() or nodos.order_by('pk').first()
    opcion = None
    if nueva or not nodo_actual or nodo_actual.empresa_id != empresa.pk:
        if empresa.ia_desde_primer_mensaje:
            resultado.update(ia=True, nodo=None, motivo='IA desde el primer mensaje.')
            return resultado
        nodo = inicial
    elif normalizar_entrada(texto) == 'volver' and inicial:
        nodo = inicial
    elif nodo_actual.tipo_nodo in ['MENU', 'TEXT']:
        entrada = normalizar_entrada(texto)
        opcion = next((opcion for opcion in nodo_actual.opciones_salida.select_related('nodo_siguiente').order_by('pk')
                       if opcion.nodo_siguiente.empresa_id == empresa.pk and entrada and entrada in
                       {normalizar_entrada(opcion.entrada_esperada), normalizar_entrada(opcion.etiqueta)}), None)
        nodo = opcion.nodo_siguiente if opcion else nodo_actual
    else:
        nodo = nodo_actual
    if not nodo:
        resultado['motivo'] = 'No hay pasos configurados.'
        return resultado
    resultado.update(nodo=nodo, motivo=f'Paso: {nodo.nombre} ({nodo.get_tipo_nodo_display()}).')
    if nodo.tipo_nodo == 'AI_AGENT':
        resultado.update(ia=True, opcion=opcion)
    else:
        resultado['salidas'].append({'texto': mensaje_con_opciones(nodo), 'opcion': opcion})
        if nodo.tipo_nodo == 'HUMAN_AGENT':
            resultado['estado'] = 'humano'
        elif nodo.tipo_nodo == 'END':
            resultado['estado'] = 'cerrada'
        elif nodo.tipo_nodo == 'TEXT' and opcion and not nodo.opciones_salida.exists():
            resultado['nodo'] = None
    return resultado


def validar_flujo(empresa):
    nodos = list(NodoBot.objects.filter(empresa=empresa).prefetch_related('opciones_salida'))
    avisos = []
    iniciales = [nodo for nodo in nodos if nodo.es_nodo_inicial]
    if not iniciales:
        avisos.append('Falta marcar un paso inicial. El bot usa el primer paso como respaldo.')
    inicio = iniciales[0] if iniciales else next(iter(nodos), None)
    por_id = {nodo.pk: nodo for nodo in nodos}
    alcanzables, pendientes = set(), [inicio.pk] if inicio else []
    while pendientes:
        identificador = pendientes.pop()
        if identificador in alcanzables or identificador not in por_id:
            continue
        alcanzables.add(identificador)
        pendientes.extend(opcion.nodo_siguiente_id for opcion in por_id[identificador].opciones_salida.all())
    for nodo in nodos:
        opciones = list(nodo.opciones_salida.all())
        if nodo.pk not in alcanzables:
            avisos.append(f'{nodo.nombre}: no se puede alcanzar desde el inicio.')
        if nodo.tipo_nodo == 'MENU' and not opciones:
            avisos.append(f'{nodo.nombre}: el menú no tiene opciones.')
        if nodo.tipo_nodo in ['END', 'HUMAN_AGENT', 'AI_AGENT'] and opciones:
            avisos.append(f'{nodo.nombre}: este tipo de paso no recorre sus opciones.')
        entradas = {}
        for opcion in opciones:
            for entrada in {normalizar_entrada(opcion.entrada_esperada), normalizar_entrada(opcion.etiqueta)} - {''}:
                if entrada == 'volver':
                    avisos.append(f'{nodo.nombre}: "volver" está reservado para regresar al inicio.')
                if entrada in entradas and entradas[entrada] != opcion.pk:
                    avisos.append(f'{nodo.nombre}: la entrada "{entrada}" coincide con varias opciones.')
                entradas[entrada] = opcion.pk
            if opcion.nodo_siguiente_id not in por_id:
                avisos.append(f'{nodo.nombre}: una opción apunta fuera de este flujo.')
            elif opcion.nodo_siguiente_id == nodo.pk:
                avisos.append(f'{nodo.nombre}: la opción {opcion.entrada_esperada} vuelve al mismo paso.')
    return avisos
