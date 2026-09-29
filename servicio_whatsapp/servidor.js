const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash, timingSafeEqual } = require('node:crypto');
// cargo el mismo archivo que usa django sin reemplazar el entorno del servicio
try { process.loadEnvFile(path.join(__dirname, '..', '.env')); }
catch (error) { if (error.code !== 'ENOENT') throw error; }

const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const codigoQr = require('qrcode');
const { entregarUnaVez } = require('./entregas');
const { resolverDestinoParaEnvio } = require('./destinos');

const clientes = new Map();
const estados = new Map();
const puerto = Number(process.env.PUERTO_WHATSAPP || 11223);
const secreto = process.env.WHATSAPP_INTERNAL_SECRET || '';
const urlDjango = (process.env.DJANGO_URL_INTERNA || 'http://127.0.0.1:7213').replace(/\/$/, '');
const carpetaEntregas = process.env.WHATSAPP_DELIVERY_DIR || path.join(__dirname, 'entregas');
const carpetaSesiones = process.env.WHATSAPP_SESSION_DIR || path.join(__dirname, 'sesiones_whatsapp');
const reintentosSesion = Number(process.env.WHATSAPP_SESION_REINTENTOS || 20);
const esperaSesionMs = Number(process.env.WHATSAPP_SESION_RETRY_MS || 3000);

if (!secreto) throw new Error('Falta configurar WHATSAPP_INTERNAL_SECRET');
// al no configurar el secreto, el servicio no autentica las solicitudes internas


function responder(respuesta, codigo, datos) {
    respuesta.writeHead(codigo, { 'Content-Type': 'application/json' });
    respuesta.end(JSON.stringify(datos));
}


function autorizado(peticion) {
    const recibido = Buffer.from(peticion.headers.authorization || '');
    const esperado = Buffer.from(`Bearer ${secreto}`);
    return recibido.length === esperado.length && timingSafeEqual(recibido, esperado);
}


async function leerJson(peticion) {
    let cuerpo = '';
    for await (const fragmento of peticion) {
        cuerpo += fragmento;
        if (cuerpo.length > 22 * 1024 * 1024) throw new Error('Solicitud demasiado grande');
    }
    return cuerpo ? JSON.parse(cuerpo) : {};
}

async function avisarDjango(datos) {
    const respuesta = await fetch(`${urlDjango}/api/interno/whatsapp/evento/`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${secreto}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(datos),
        signal: AbortSignal.timeout(30000)
    });
    if (!respuesta.ok) throw new Error(`Django respondió ${respuesta.status}`);
    return respuesta.json();
}

// reutilizo la sesion y su ultimo codigo
async function crearSesion(identificador, telefono = '') {
    const existente = clientes.get(identificador);
    if (existente) {
        if (!existente.info && existente.telefonoVinculacion !== telefono) {
            if (telefono) await existente.requestPairingCode(telefono);
            else await existente.cancelPairingCode();
            existente.telefonoVinculacion = telefono;
        }
        const estado = estados.get(identificador);
        if (estado) avisarDjango(estado).catch(error => console.error(error.message));
        return existente;
    }
    const cliente = new Client({
        authStrategy: new LocalAuth({ clientId: identificador, dataPath: carpetaSesiones }),
        pairWithPhoneNumber: { phoneNumber: telefono, showNotification: true, intervalMs: 180000 },
        puppeteer: { headless: true, args: ['--no-sandbox', '--disable-setuid-sandbox'] }
    });
    cliente.telefonoVinculacion = telefono;
    clientes.set(identificador, cliente);
    function actualizarEstado(datos) {
        if (clientes.get(identificador) !== cliente) return Promise.resolve();
        const estado = { identificador, ...datos };
        estados.set(identificador, estado);
        return avisarDjango(estado);
    }
    estados.set(identificador, { identificador, estado: 'autenticando' });
    cliente.on('code', (codigo) => {
        actualizarEstado({ estado: 'esperando_codigo', codigo_manual: codigo }).catch(error => console.error(error.message));
    });
    cliente.on('qr', async (valor) => {
        try {
            const imagen = await codigoQr.toDataURL(valor);
            await actualizarEstado({ estado: 'esperando_qr', codigo_qr: imagen });
        } catch (error) {
            console.error(`No se pudo enviar el QR de ${identificador}: ${error.message}`);
        }
    });
    cliente.on('authenticated', () => {
        actualizarEstado({ estado: 'autenticando' }).catch((error) => console.error(error.message));
    });
    cliente.on('ready', () => {
        const numero = cliente.info?.wid?.user || '';
        actualizarEstado({ estado: 'conectado', numero_telefono: numero }).catch((error) => console.error(error.message));
    });
    cliente.on('auth_failure', (detalle) => {
        actualizarEstado({ estado: 'error' }).catch((error) => console.error(error.message));
        console.error(`Falló la autenticación de ${identificador}: ${detalle}`);
        if (clientes.get(identificador) === cliente) clientes.delete(identificador);
        cliente.destroy().catch(error => console.error(error.message));
    });
    cliente.on('disconnected', (detalle) => {
        actualizarEstado({ estado: 'desconectado' }).catch((error) => console.error(error.message));
        console.error(`Sesión desconectada ${identificador}: ${detalle}`);
        if (clientes.get(identificador) === cliente) clientes.delete(identificador);
        cliente.destroy().catch(error => console.error(error.message));
    });
    cliente.on('message', async (mensaje) => {
        if (mensaje.fromMe || !mensaje.body?.trim()) return;
        const origen = mensaje.from || '';
        if (!origen.endsWith('@c.us') && !origen.endsWith('@lid')) return;
        let contacto;
        try {
            [contacto] = await cliente.getContactLidAndPhone([origen]);
        } catch (error) {
            console.warn(`No se pudo resolver el contacto ${origen}: ${error.message}`);
            // continua con informacion minima si no resuelve
        }
        const jidTelefono = contacto?.pn || (origen.endsWith('@c.us') ? origen : '');
        const telefono = jidTelefono.split('@')[0].split(':')[0] || origen.split('@')[0].split(':')[0];
        const idMensaje = mensaje.id?._serialized || createHash('sha256')
            .update(`${origen}|${mensaje.timestamp || ''}|${mensaje.body}`)
            .digest('hex');
        try {
            const evento = {
                tipo: 'mensaje',
                identificador,
                id_mensaje: idMensaje,
                telefono_cliente: telefono,
                destino: contacto?.lid || origen,
                texto: mensaje.body,
                fecha: mensaje.timestamp
            };
            for (let intento = 0; intento < 3; intento++) {
                try { await avisarDjango(evento); break; }
                catch (error) {
                    if (intento === 2) throw error;
                    await new Promise(resolver => setTimeout(resolver, 1000 * (intento + 1)));
                }
            }
        } catch (error) {
            console.error(`No se pudo procesar un mensaje de ${identificador}: ${error.message}`);
        }
    });
    cliente.initialize().catch((error) => {
        actualizarEstado({ estado: 'error' }).catch(() => {});
        console.error(`No se pudo iniciar ${identificador}: ${error.message}`);
        if (clientes.get(identificador) === cliente) clientes.delete(identificador);
        cliente.destroy().catch(error => console.error(error.message));
    });
    return cliente;
}

async function desconectarSesion(identificador) {
    const cliente = clientes.get(identificador);
    clientes.delete(identificador);
    estados.delete(identificador);
    if (cliente) {
        try {
            await cliente.logout();
        } catch {}
        try {
            await cliente.destroy();
        } catch {}
        clientes.delete(identificador);
    }
    await fs.rm(path.join(carpetaSesiones, `session-${identificador}`), { recursive: true, force: true });
    avisarDjango({ identificador, estado: 'desconectado' }).catch(error => console.error(error.message));
}

async function recuperarSesiones() {
    const respuesta = await fetch(`${urlDjango}/api/interno/whatsapp/sesiones/`, {
        headers: { 'Authorization': `Bearer ${secreto}` },
        signal: AbortSignal.timeout(15000)
    });
    if (!respuesta.ok) throw new Error(`Django respondió ${respuesta.status}`);
    const datos = await respuesta.json();
    for (const identificador of datos.identificadores) await crearSesion(identificador);
    return datos.identificadores || [];
}

async function iniciarRecuperacionSesiones(intento = 1) {
    try {
        const sesiones = await recuperarSesiones();
        if (sesiones.length) {
            console.log(`Sesiones recuperadas: ${sesiones.length}`);
        }
        return true;
    } catch (error) {
        if (intento < reintentosSesion) {
            console.warn(`No se pudieron recuperar las sesiones (intento ${intento}/${reintentosSesion}): ${error.message}. Reintentando en ${esperaSesionMs} ms...`);
            setTimeout(() => iniciarRecuperacionSesiones(intento + 1), esperaSesionMs);
            return false;
        }
        console.error(`No se pudieron recuperar las sesiones tras ${reintentosSesion} intentos: ${error.message}`);
        return false;
    }
}

const servidor = http.createServer(async (peticion, respuesta) => {
    if (!autorizado(peticion)) return responder(respuesta, 401, { error: 'No autorizado' });
    try {
        const ruta = new URL(peticion.url, 'http://localhost').pathname;
        const consulta = ruta.match(/^\/api\/sesiones\/([0-9a-f-]{36})\/diagnostico\/$/i);
        if (peticion.method === 'GET' && consulta) {
            const cliente = clientes.get(consulta[1]);
            const ultimo = estados.get(consulta[1]);
            return responder(respuesta, 200, { servicio: 'disponible', cliente_activo: Boolean(cliente),
                estado: cliente?.info ? 'conectado' : (ultimo?.estado || 'desconectado') });
        }
        if (peticion.method === 'POST' && ruta === '/api/sesiones/iniciar/') {
            const datos = await leerJson(peticion);
            if (!/^[0-9a-f-]{36}$/i.test(datos.identificador || '')) return responder(respuesta, 400, { error: 'Identificador no válido' });
            const telefono = datos.telefono || '';
            if (typeof telefono !== 'string' || (telefono && !/^[0-9]{7,15}$/.test(telefono))) return responder(respuesta, 400, { error: 'Número no válido' });
            await crearSesion(datos.identificador, telefono);
            return responder(respuesta, 202, { estado: 'autenticando' });
        }
        const coincidencia = ruta.match(/^\/api\/sesiones\/([0-9a-f-]{36})\/(mensajes|desconectar)\/$/i);
        if (!coincidencia) return responder(respuesta, 404, { error: 'Ruta no encontrada' });
        const [, identificador, accion] = coincidencia;
        if (peticion.method !== 'POST') return responder(respuesta, 405, { error: 'Método no permitido' });
        if (accion === 'desconectar') {
            await desconectarSesion(identificador);
            return responder(respuesta, 200, { estado: 'desconectado' });
        }
        const cliente = clientes.get(identificador);
        if (!cliente || !cliente.info) return responder(respuesta, 409, { error: 'Sesión no conectada' });
        const datos = await leerJson(peticion);
        if (typeof datos.texto !== 'string' || !datos.texto.trim()) {
            return responder(respuesta, 400, { error: 'Mensaje no válido' });
        }
        const destinoChat = datos.destino_chat || datos.destino || '';
        const destinoFinal = await resolverDestinoParaEnvio(cliente, destinoChat);
        if (!destinoFinal) {
            return responder(respuesta, 400, { error: 'Destino o mensaje no válido' });
        }
        if (datos.opcion_pdf != null && (!Number.isSafeInteger(datos.opcion_pdf) || datos.opcion_pdf < 1)) {
            return responder(respuesta, 400, { error: 'Identificador de PDF no válido' });
        }
        if (!/^[0-9a-f-]{36}$/i.test(datos.id_envio || '')) return responder(respuesta, 400, { error: 'Identificador de entrega no válido' });
        let documento;
        if (datos.opcion_pdf) {
            if (typeof datos.pdf_base64 !== 'string') return responder(respuesta, 400, {error:'Falta el PDF'});
            const pdf = Buffer.from(datos.pdf_base64, 'base64');
            if (pdf.length > 15 * 1024 * 1024 || pdf.subarray(0, 5).toString() !== '%PDF-') return responder(respuesta, 400, {error:'PDF no válido'});
            documento = new MessageMedia('application/pdf', datos.pdf_base64, `opcion-${datos.opcion_pdf}.pdf`);
        }
        const entrega = await entregarUnaVez(carpetaEntregas, identificador, datos,
            async () => {
                const enviado = await cliente.sendMessage(destinoFinal, datos.texto);
                if (!enviado) throw new Error('WhatsApp no confirmó el mensaje');
            },
            async () => {
                return async () => {
                    if (!await cliente.sendMessage(destinoFinal, documento)) throw new Error('WhatsApp no confirmó el PDF');
                };
            });
        return responder(respuesta, 200, entrega);
    } catch (error) {
        console.error(`Error en servicio WhatsApp: ${error.stack || error.message}`);
        return responder(respuesta, 500, { error: 'Error en el servicio de WhatsApp' });
    }
});

servidor.listen(puerto, '127.0.0.1', () => {
    console.log(`Servicio WhatsApp escuchando en 127.0.0.1:${puerto}`);
    iniciarRecuperacionSesiones();
});

async function cerrarServicio() {
    servidor.close();
    await Promise.all([...clientes.values()].map((cliente) => cliente.destroy().catch(() => {})));
    process.exit(0);
}
// manejo de cierre del servicio y limpieza de clientes
process.on('SIGINT', cerrarServicio);
process.on('SIGTERM', cerrarServicio);

