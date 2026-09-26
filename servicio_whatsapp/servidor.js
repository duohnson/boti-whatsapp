const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash, timingSafeEqual } = require('node:crypto');
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const codigoQr = require('qrcode');
const { resolverDestinoParaEnvio } = require('./destinos');

const clientes = new Map();
const puerto = Number(process.env.PUERTO_WHATSAPP || 11223);
const secreto = process.env.WHATSAPP_INTERNAL_SECRET || '';
const urlDjango = (process.env.DJANGO_URL_INTERNA || 'http://127.0.0.1:7213').replace(/\/$/, '');
const carpetaSesiones = process.env.WHATSAPP_SESSION_DIR || path.join(__dirname, 'sesiones_whatsapp');
const reintentosSesion = Number(process.env.WHATSAPP_SESION_REINTENTOS || 20);
const esperaSesionMs = Number(process.env.WHATSAPP_SESION_RETRY_MS || 3000);

if (!secreto) throw new Error('Falta configurar WHATSAPP_INTERNAL_SECRET');

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
        if (cuerpo.length > 1000000) throw new Error('Solicitud demasiado grande');
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

function crearSesion(identificador) {
    if (clientes.has(identificador)) return clientes.get(identificador);
    const cliente = new Client({
        authStrategy: new LocalAuth({ clientId: identificador, dataPath: carpetaSesiones }),
        puppeteer: { headless: true, args: ['--no-sandbox', '--disable-setuid-sandbox'] }
    });
    clientes.set(identificador, cliente);
    cliente.on('qr', async (valor) => {
        try {
            const imagen = await codigoQr.toDataURL(valor);
            await avisarDjango({ identificador, estado: 'esperando_qr', codigo_qr: imagen });
        } catch (error) {
            console.error(`No se pudo enviar el QR de ${identificador}: ${error.message}`);
        }
    });
    cliente.on('authenticated', () => {
        avisarDjango({ identificador, estado: 'autenticando' }).catch((error) => console.error(error.message));
    });
    cliente.on('ready', () => {
        const numero = cliente.info?.wid?.user || '';
        avisarDjango({ identificador, estado: 'conectado', numero_telefono: numero }).catch((error) => console.error(error.message));
    });
    cliente.on('auth_failure', (detalle) => {
        avisarDjango({ identificador, estado: 'error' }).catch((error) => console.error(error.message));
        console.error(`Falló la autenticación de ${identificador}: ${detalle}`);
        clientes.delete(identificador);
    });
    cliente.on('disconnected', (detalle) => {
        avisarDjango({ identificador, estado: 'desconectado' }).catch((error) => console.error(error.message));
        console.error(`Sesión desconectada ${identificador}: ${detalle}`);
        clientes.delete(identificador);
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
        }
        const jidTelefono = contacto?.pn || (origen.endsWith('@c.us') ? origen : '');
        const telefono = jidTelefono.split('@')[0].split(':')[0] || origen.split('@')[0].split(':')[0];
        const idMensaje = mensaje.id?._serialized || createHash('sha256')
            .update(`${origen}|${mensaje.timestamp || ''}|${mensaje.body}`)
            .digest('hex');
        try {
            await avisarDjango({
                tipo: 'mensaje',
                identificador,
                id_mensaje: idMensaje,
                telefono_cliente: telefono,
                destino: contacto?.lid || origen,
                texto: mensaje.body,
                fecha: mensaje.timestamp
            });
        } catch (error) {
            console.error(`No se pudo procesar un mensaje de ${identificador}: ${error.message}`);
        }
    });
    cliente.initialize().catch((error) => {
        avisarDjango({ identificador, estado: 'error' }).catch(() => {});
        console.error(`No se pudo iniciar ${identificador}: ${error.message}`);
        clientes.delete(identificador);
    });
    return cliente;
}

async function desconectarSesion(identificador) {
    const cliente = clientes.get(identificador);
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
    await avisarDjango({ identificador, estado: 'desconectado' });
}

async function recuperarSesiones() {
    const respuesta = await fetch(`${urlDjango}/api/interno/whatsapp/sesiones/`, {
        headers: { 'Authorization': `Bearer ${secreto}` },
        signal: AbortSignal.timeout(15000)
    });
    if (!respuesta.ok) throw new Error(`Django respondió ${respuesta.status}`);
    const datos = await respuesta.json();
    for (const identificador of datos.identificadores) crearSesion(identificador);
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
        if (peticion.method === 'POST' && ruta === '/api/sesiones/iniciar/') {
            const datos = await leerJson(peticion);
            if (!/^[0-9a-f-]{36}$/i.test(datos.identificador || '')) return responder(respuesta, 400, { error: 'Identificador no válido' });
            crearSesion(datos.identificador);
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
        console.log(`Enviando a ${destinoFinal}`);
        const mensajeEnviado = await cliente.sendMessage(destinoFinal, datos.texto);
        if (!mensajeEnviado) throw new Error(`WhatsApp no creó el mensaje para ${destinoFinal}`);
        if (datos.opcion_pdf !== undefined && datos.opcion_pdf !== null) {
            if (!Number.isSafeInteger(datos.opcion_pdf) || datos.opcion_pdf < 1) {
                return responder(respuesta, 400, { error: 'Identificador de PDF no válido' });
            }
            const respuestaPdf = await fetch(
                `${urlDjango}/api/interno/whatsapp/${identificador}/opciones/${datos.opcion_pdf}/pdf/`,
                {
                    headers: { 'Authorization': `Bearer ${secreto}` },
                    signal: AbortSignal.timeout(30000)
                }
            );
            if (!respuestaPdf.ok) throw new Error(`Django no pudo entregar el PDF: ${respuestaPdf.status}`);
            const pdf = Buffer.from(await respuestaPdf.arrayBuffer());
            const documento = new MessageMedia('application/pdf', pdf.toString('base64'), `opcion-${datos.opcion_pdf}.pdf`);
            const pdfEnviado = await cliente.sendMessage(destinoFinal, documento);
            if (!pdfEnviado) throw new Error(`WhatsApp no creó el PDF para ${destinoFinal}`);
        }
        return responder(respuesta, 200, { estado: 'enviado' });
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

process.on('SIGINT', cerrarServicio);
process.on('SIGTERM', cerrarServicio);
